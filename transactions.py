"""Transaction logic for Spendwise. No Streamlit imports, so everything here can be tested."""
import json
import re

import pandas as pd

CURRENCIES = {
    "USD": "$",
    "NGN": "₦",
    "EUR": "€",
    "GBP": "£",
    "AED": "AED ",
}
DEFAULT_CURRENCY = "USD"


def detect_currency(df):
    """Guess the currency from a Currency column or symbols in Amount. Returns a code or None."""
    if "Currency" in df.columns:
        values = df["Currency"].dropna().astype(str).str.strip().str.upper()
        if not values.empty and values.iloc[0] in CURRENCIES:
            return values.iloc[0]

    sample = " ".join(df["Amount"].astype(str).head(50))
    for code, symbol in CURRENCIES.items():
        if symbol.strip() in sample:
            return code
    return None


def clean_amounts(series):
    """Strip symbols and thousands separators, then convert to float."""
    return series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True).astype(float)


def parse_transactions(file):
    """Read a transactions CSV. Returns (dataframe, detected currency code or None)."""
    df = pd.read_csv(file)
    df.columns = [col.strip() for col in df.columns]

    currency = detect_currency(df)

    df["Amount"] = clean_amounts(df["Amount"])
    df["Date"] = pd.to_datetime(df["Date"], format="%d %b %Y")
    return df, currency


def normalize_text(text):
    """Lowercase and collapse runs of whitespace, so "POS  PURCHASE" equals "pos purchase"."""
    return " ".join(str(text).lower().split())


def build_rules(categories):
    """Turn categories into (pattern, category, keyword) rules, longest keyword first.

    A keyword matches as a whole word or phrase anywhere in the details, so "Bolt"
    matches "BOLT.EU/O/2609" but not "BOLTON STORES". Longest first means the most
    specific keyword wins: "Uber Eats" beats "Uber".
    """
    rules = []
    for category, keywords in categories.items():
        if category == "Uncategorized":
            continue
        for keyword in keywords:
            normalized = normalize_text(keyword)
            if normalized:
                pattern = re.compile(r"(?<!\w)" + re.escape(normalized) + r"(?!\w)")
                rules.append((len(normalized), pattern, category, keyword.strip()))

    rules.sort(key=lambda rule: rule[0], reverse=True)
    return [(pattern, category, keyword) for _, pattern, category, keyword in rules]


def match_rule(details, rules):
    """Return (category, keyword) for the most specific matching rule, or ("Uncategorized", None)."""
    text = normalize_text(details)
    for pattern, category, keyword in rules:
        if pattern.search(text):
            return category, keyword
    return "Uncategorized", None


def match_category(details, rules):
    """Return the category of the most specific matching rule, or Uncategorized."""
    return match_rule(details, rules)[0]


def categorize_transactions(df, categories):
    """Set each row's Category, and the Keyword that matched it, from the keyword lists."""
    rules = build_rules(categories)
    matches = [match_rule(details, rules) for details in df["Details"]]
    df["Category"] = [category for category, _ in matches]
    df["Keyword"] = [keyword for _, keyword in matches]
    return df


def move_keyword_to_category(categories, category, keyword):
    """Assign a keyword to one category, removing it from every other category.

    Changes `categories` in place. Uncategorized never stores keywords.
    """
    keyword = keyword.strip()
    if not keyword:
        return

    for name, keywords in categories.items():
        if name != category:
            keywords[:] = [k for k in keywords if k.strip().lower() != keyword.lower()]

    existing = [k.strip().lower() for k in categories[category]]
    if category != "Uncategorized" and keyword.lower() not in existing:
        categories[category].append(keyword)




def parse_categories(data):
    """Parse an exported categories file (text or bytes). Raises ValueError with a user-facing message."""
    try:
        categories = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("That file isn't valid JSON.") from None

    valid = isinstance(categories, dict) and all(
        isinstance(name, str)
        and isinstance(keywords, list)
        and all(isinstance(k, str) for k in keywords)
        for name, keywords in categories.items()
    )
    if not valid:
        raise ValueError("Expected category names, each with a list of keywords.")

    categories.setdefault("Uncategorized", [])
    return categories


def categories_to_json(categories):
    """Turn categories into JSON text for downloading."""
    return json.dumps(categories, indent=2, ensure_ascii=False)




def format_money(amount, symbol):
    """Format an amount with a currency symbol and thousands separators, e.g. -₦1,250.00."""
    sign = "-" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,.2f}"


def summarize(debits, credits):
    """Headline numbers for the KPI cards."""
    total_spent = float(debits["Amount"].sum())
    total_income = float(credits["Amount"].sum())

    if total_income > 0:
        savings_rate = (total_income - total_spent) / total_income * 100
    else:
        savings_rate = None

    categorized = debits[debits["Category"] != "Uncategorized"]
    if categorized.empty:
        top_category, top_amount = None, 0.0
    else:
        totals = categorized.groupby("Category")["Amount"].sum()
        top_category, top_amount = totals.idxmax(), float(totals.max())

    return {
        "total_spent": total_spent,
        "total_income": total_income,
        "savings_rate": savings_rate,
        "top_category": top_category,
        "top_amount": top_amount,
    }




def format_compact(amount, symbol):
    """Short form for cards: ₦1.23M, ₦750K, $980.50. Exact amounts use format_money."""
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(amount) >= limit:
            short = f"{abs(amount) / limit:.2f}".rstrip("0").rstrip(".")
            sign = "-" if amount < 0 else ""
            return f"{sign}{symbol}{short}{suffix}"
    return format_money(amount, symbol)




def month_options(df):
    """Months present in the data, newest first, as (label, period) pairs like ("Nov 2026", Period)."""
    periods = sorted(df["Date"].dt.to_period("M").unique(), reverse=True)
    return [(period.strftime("%b %Y"), period) for period in periods]


def filter_by_month(df, period):
    """Rows from one month. A period of None means all months."""
    if period is None:
        return df
    return df[df["Date"].dt.to_period("M") == period]


def monthly_totals(debits, credits):
    """Spent and income per month, oldest first, with a "Month" label column."""
    spent = debits.groupby(debits["Date"].dt.to_period("M"))["Amount"].sum()
    income = credits.groupby(credits["Date"].dt.to_period("M"))["Amount"].sum()

    totals = pd.DataFrame({"Spent": spent, "Income": income}).fillna(0.0).sort_index()
    totals.index = totals.index.strftime("%b %Y")
    totals.index.name = "Month"
    return totals.reset_index()




def remove_keyword(categories, category, keyword):
    """Remove a keyword from one category, ignoring case and extra spaces. Changes `categories` in place."""
    if category not in categories:
        return
    target = normalize_text(keyword)
    categories[category][:] = [k for k in categories[category] if normalize_text(k) != target]


def keyword_table(categories):
    """All keyword rules as a Category/Keyword table, sorted by category then keyword."""
    rows = [
        (category, keyword)
        for category, keywords in categories.items()
        if category != "Uncategorized"
        for keyword in keywords
    ]
    rows.sort(key=lambda row: (row[0].lower(), row[1].lower()))
    return pd.DataFrame(rows, columns=["Category", "Keyword"])