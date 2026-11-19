"""Transaction logic for Spendwise. No Streamlit imports, so everything here can be tested."""
import json

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


def categorize_transactions(df, categories):
    """Set each row's Category from the keyword lists in `categories`."""
    df["Category"] = "Uncategorized"

    for category, keywords in categories.items():
        if category == "Uncategorized" or not keywords:
            continue

        lowered_keywords = [keyword.lower().strip() for keyword in keywords]

        for idx, row in df.iterrows():
            details = row["Details"].lower()
            if details in lowered_keywords:
                df.at[idx, "Category"] = category

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