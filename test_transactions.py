"""Tests for transactions.py. Run with: python -m pytest"""
import io
from pathlib import Path

import pandas as pd
import pytest

from transactions import (
    categories_to_json,
    categorize_transactions,
    clean_amounts,
    detect_currency,
    filter_by_month,
    format_compact,
    format_money,
    keyword_table,
    month_options,
    monthly_totals,
    move_keyword_to_category,
    parse_categories,
    parse_transactions,
    remove_keyword,
    summarize,
)


def make_csv(text):
    """Turn CSV text into a file-like object, like Streamlit's uploader gives us."""
    return io.StringIO(text.strip())


SAMPLE_CSV = """
Date,Details,Amount,Debit/Credit
02 Jan 2026,Salary,"12,500.00",Credit
03 Jan 2026,Carrefour,"245.60",Debit
05 Jan 2026,Uber,"38.00",Debit
"""


# ---------- clean_amounts ----------

def test_clean_amounts_removes_thousands_separators():
    assert clean_amounts(pd.Series(["12,500.00"])).tolist() == [12500.0]


def test_clean_amounts_removes_currency_symbols():
    assert clean_amounts(pd.Series(["₦245.60", "$38.00", "£1,000"])).tolist() == [245.6, 38.0, 1000.0]


def test_clean_amounts_handles_plain_numbers():
    assert clean_amounts(pd.Series([38, 12.5])).tolist() == [38.0, 12.5]


def test_clean_amounts_keeps_negative_sign():
    assert clean_amounts(pd.Series(["-50.25"])).tolist() == [-50.25]


# ---------- detect_currency ----------

def test_detect_currency_from_column():
    df = pd.DataFrame({"Amount": ["10"], "Currency": ["gbp"]})
    assert detect_currency(df) == "GBP"


def test_detect_currency_from_naira_symbol():
    df = pd.DataFrame({"Amount": ["₦12,500.00", "₦300"]})
    assert detect_currency(df) == "NGN"


def test_detect_currency_from_dollar_symbol():
    df = pd.DataFrame({"Amount": ["$38.00"]})
    assert detect_currency(df) == "USD"


def test_detect_currency_returns_none_without_hints():
    df = pd.DataFrame({"Amount": ["38.00", "12,500.00"]})
    assert detect_currency(df) is None


def test_detect_currency_ignores_unknown_currency_column():
    df = pd.DataFrame({"Amount": ["10"], "Currency": ["XYZ"]})
    assert detect_currency(df) is None


# ---------- parse_transactions ----------

def test_parse_transactions_converts_types():
    df, _ = parse_transactions(make_csv(SAMPLE_CSV))
    assert df["Amount"].tolist() == [12500.0, 245.6, 38.0]
    assert pd.api.types.is_datetime64_any_dtype(df["Date"])
    assert df["Date"].iloc[0] == pd.Timestamp("2026-01-02")


def test_parse_transactions_strips_column_names():
    csv = "Date , Details ,Amount, Debit/Credit\n03 Jan 2026,Uber,38.00,Debit"
    df, _ = parse_transactions(make_csv(csv))
    assert list(df.columns) == ["Date", "Details", "Amount", "Debit/Credit"]


def test_parse_transactions_detects_currency():
    csv = 'Date,Details,Amount,Debit/Credit\n03 Jan 2026,Shoprite,"₦4,500.00",Debit'
    df, currency = parse_transactions(make_csv(csv))
    assert currency == "NGN"
    assert df["Amount"].iloc[0] == 4500.0


def test_parse_transactions_rejects_wrong_date_format():
    csv = "Date,Details,Amount,Debit/Credit\n2026-01-03,Uber,38.00,Debit"
    with pytest.raises(ValueError):
        parse_transactions(make_csv(csv))


def test_parse_transactions_rejects_missing_column():
    csv = "Date,Details,Debit/Credit\n03 Jan 2026,Uber,Debit"
    with pytest.raises(KeyError):
        parse_transactions(make_csv(csv))


# ---------- categorize_transactions ----------

def make_df(details):
    return pd.DataFrame({"Details": details, "Amount": [1.0] * len(details)})


def test_categorize_matches_keyword_ignoring_case():
    df = categorize_transactions(make_df(["CARREFOUR"]), {"Groceries": ["carrefour "]})
    assert df["Category"].tolist() == ["Groceries"]


def test_categorize_leaves_unknown_as_uncategorized():
    df = categorize_transactions(make_df(["Uber"]), {"Groceries": ["Carrefour"]})
    assert df["Category"].tolist() == ["Uncategorized"]


def test_categorize_resets_previous_categories():
    df = make_df(["Uber"])
    df["Category"] = "Transport"
    df = categorize_transactions(df, {"Uncategorized": []})
    assert df["Category"].tolist() == ["Uncategorized"]


def test_categorize_ignores_uncategorized_keywords():
    df = categorize_transactions(make_df(["Uber"]), {"Uncategorized": ["Uber"]})
    assert df["Category"].tolist() == ["Uncategorized"]


def test_categorize_matches_keyword_inside_details():
    df = categorize_transactions(make_df(["UBER *TRIP 123"]), {"Transport": ["Uber"]})
    assert df["Category"].tolist() == ["Transport"]


def test_categorize_matches_real_bank_narrations():
    details = ["POS PURCHASE SHOPRITE LEKKI 0423", "WEB PURCHASE BOLT.EU/O/2609 LAGOS"]
    categories = {"Groceries": ["Shoprite"], "Transport": ["Bolt"]}
    df = categorize_transactions(make_df(details), categories)
    assert df["Category"].tolist() == ["Groceries", "Transport"]


def test_categorize_needs_whole_words():
    categories = {"Transport": ["Bolt"], "Rent": ["Rent"]}
    df = categorize_transactions(make_df(["BOLTON STORES", "CURRENT ACCOUNT FEE"]), categories)
    assert df["Category"].tolist() == ["Uncategorized", "Uncategorized"]


def test_categorize_longest_keyword_wins():
    categories = {"Transport": ["Uber"], "Food": ["Uber Eats"]}
    df = categorize_transactions(make_df(["UBER EATS ORDER 55", "UBER *TRIP 9"]), categories)
    assert df["Category"].tolist() == ["Food", "Transport"]


def test_categorize_longest_wins_regardless_of_category_order():
    categories = {"Food": ["Uber Eats"], "Transport": ["Uber"]}
    df = categorize_transactions(make_df(["UBER EATS ORDER 55"]), categories)
    assert df["Category"].tolist() == ["Food"]


def test_categorize_ignores_extra_whitespace():
    df = categorize_transactions(make_df(["POS   CHICKEN  REPUBLIC  AJAH"]), {"Food": [" Chicken Republic "]})
    assert df["Category"].tolist() == ["Food"]


def test_categorize_handles_punctuation_in_keywords():
    categories = {"Food": ["Domino's"], "Tech": ["C++ Books"]}
    df = categorize_transactions(make_df(["DOMINO'S PIZZA LEKKI", "C++ BOOKS LTD"]), categories)
    assert df["Category"].tolist() == ["Food", "Tech"]


def test_categorize_ignores_blank_keywords():
    df = categorize_transactions(make_df(["Anything"]), {"Food": ["", "   "]})
    assert df["Category"].tolist() == ["Uncategorized"]


def test_categorize_handles_missing_details():
    df = categorize_transactions(make_df([None, "UBER *TRIP"]), {"Transport": ["Uber"]})
    assert df["Category"].tolist() == ["Uncategorized", "Transport"]


def test_full_details_keyword_overrides_shorter_rule():
    # Re-categorising one row stores its full details as a keyword. Being longer, it beats "Shoprite".
    categories = {"Uncategorized": [], "Groceries": ["Shoprite"], "Food": []}
    move_keyword_to_category(categories, "Food", "POS PURCHASE SHOPRITE CAFE 0099")
    df = categorize_transactions(
        make_df(["POS PURCHASE SHOPRITE CAFE 0099", "POS PURCHASE SHOPRITE LEKKI 0423"]), categories
    )
    assert df["Category"].tolist() == ["Food", "Groceries"]


def test_shorter_rule_still_matches_after_moving_row_to_uncategorized():
    # Moving a row to Uncategorized in the table doesn't remove a shorter rule; remove_keyword does.
    categories = {"Uncategorized": [], "Groceries": ["Shoprite"]}
    move_keyword_to_category(categories, "Uncategorized", "POS PURCHASE SHOPRITE LEKKI 0423")
    df = categorize_transactions(make_df(["POS PURCHASE SHOPRITE LEKKI 0423"]), categories)
    assert df["Category"].tolist() == ["Groceries"]


# ---------- move_keyword_to_category ----------

def test_move_adds_keyword():
    categories = {"Uncategorized": [], "Groceries": []}
    move_keyword_to_category(categories, "Groceries", "Carrefour")
    assert categories["Groceries"] == ["Carrefour"]


def test_move_removes_keyword_from_other_categories():
    categories = {"Uncategorized": [], "Groceries": ["Carrefour"], "Food": []}
    move_keyword_to_category(categories, "Food", "carrefour")
    assert categories["Groceries"] == []
    assert categories["Food"] == ["carrefour"]


def test_move_to_uncategorized_only_removes():
    categories = {"Uncategorized": [], "Groceries": ["Carrefour"]}
    move_keyword_to_category(categories, "Uncategorized", "Carrefour")
    assert categories == {"Uncategorized": [], "Groceries": []}


def test_move_does_not_duplicate():
    categories = {"Uncategorized": [], "Groceries": ["Carrefour"]}
    move_keyword_to_category(categories, "Groceries", " CARREFOUR ")
    assert categories["Groceries"] == ["Carrefour"]


def test_move_ignores_blank_keyword():
    categories = {"Uncategorized": [], "Groceries": []}
    move_keyword_to_category(categories, "Groceries", "   ")
    assert categories["Groceries"] == []


def test_move_then_categorize_round_trip():
    categories = {"Uncategorized": [], "Groceries": [], "Food": []}
    move_keyword_to_category(categories, "Groceries", "Carrefour")
    move_keyword_to_category(categories, "Food", "Carrefour")
    df = categorize_transactions(make_df(["Carrefour", "Carrefour", "Uber"]), categories)
    assert df["Category"].tolist() == ["Food", "Food", "Uncategorized"]




# ---------- parse_categories / categories_to_json ----------

def test_categories_round_trip():
    categories = {"Uncategorized": [], "Groceries": ["Carrefour", "Shoprite"]}
    assert parse_categories(categories_to_json(categories)) == categories


def test_parse_categories_accepts_bytes():
    assert parse_categories(b'{"Food": ["KFC"]}') == {"Food": ["KFC"], "Uncategorized": []}


def test_parse_categories_adds_uncategorized():
    assert "Uncategorized" in parse_categories('{"Food": []}')


def test_parse_categories_keeps_non_ascii():
    text = categories_to_json({"Uncategorized": [], "Food": ["Café"]})
    assert "Café" in text
    assert parse_categories(text)["Food"] == ["Café"]


@pytest.mark.parametrize("bad", ["not json", b"\xff\xfe\x00", ""])
def test_parse_categories_rejects_invalid_json(bad):
    with pytest.raises(ValueError, match="valid JSON"):
        parse_categories(bad)


@pytest.mark.parametrize("bad", ['["Food"]', '{"Food": "KFC"}', '{"Food": [1, 2]}', "42"])
def test_parse_categories_rejects_wrong_shape(bad):
    with pytest.raises(ValueError, match="list of keywords"):
        parse_categories(bad)




# ---------- demo data ----------

DEMO_DIR = Path(__file__).parent / "sample_data"


def test_demo_data_parses_and_is_fully_categorised():
    df, currency = parse_transactions(DEMO_DIR / "demo_transactions.csv")
    categories = parse_categories((DEMO_DIR / "demo_categories.json").read_bytes())
    df = categorize_transactions(df, categories)

    assert currency == "NGN"
    debits = df[df["Debit/Credit"] == "Debit"]
    assert not debits.empty
    assert (debits["Category"] != "Uncategorized").all()




# ---------- format_money ----------

def test_format_money_adds_symbol_and_separators():
    assert format_money(1250000, "₦") == "₦1,250,000.00"


def test_format_money_puts_minus_before_symbol():
    assert format_money(-45.5, "$") == "-$45.50"


def test_format_money_handles_zero():
    assert format_money(0, "£") == "£0.00"


# ---------- summarize ----------

def make_debits(rows):
    return pd.DataFrame(rows, columns=["Category", "Amount"])


def test_summarize_totals_and_savings_rate():
    debits = make_debits([("Rent", 600.0), ("Food", 200.0)])
    credits = pd.DataFrame({"Amount": [1000.0]})
    summary = summarize(debits, credits)
    assert summary["total_spent"] == 800.0
    assert summary["total_income"] == 1000.0
    assert summary["savings_rate"] == pytest.approx(20.0)


def test_summarize_negative_savings_when_overspending():
    debits = make_debits([("Rent", 1500.0)])
    credits = pd.DataFrame({"Amount": [1000.0]})
    assert summarize(debits, credits)["savings_rate"] == pytest.approx(-50.0)


def test_summarize_no_income_gives_no_savings_rate():
    debits = make_debits([("Rent", 100.0)])
    credits = pd.DataFrame({"Amount": pd.Series([], dtype=float)})
    assert summarize(debits, credits)["savings_rate"] is None


def test_summarize_top_category_ignores_uncategorized():
    debits = make_debits([("Uncategorized", 900.0), ("Food", 50.0), ("Food", 70.0), ("Transport", 100.0)])
    summary = summarize(debits, pd.DataFrame({"Amount": [1000.0]}))
    assert summary["top_category"] == "Food"
    assert summary["top_amount"] == 120.0


def test_summarize_no_top_category_when_all_uncategorized():
    debits = make_debits([("Uncategorized", 100.0)])
    summary = summarize(debits, pd.DataFrame({"Amount": [1000.0]}))
    assert summary["top_category"] is None


def test_summarize_demo_data():
    df, _ = parse_transactions(DEMO_DIR / "demo_transactions.csv")
    categories = parse_categories((DEMO_DIR / "demo_categories.json").read_bytes())
    df = categorize_transactions(df, categories)
    summary = summarize(df[df["Debit/Credit"] == "Debit"], df[df["Debit/Credit"] == "Credit"])
    assert summary["total_spent"] == 1232200.0
    assert summary["total_income"] == 2765000.0
    assert summary["top_category"] == "Rent"




# ---------- format_compact ----------

@pytest.mark.parametrize(
    "amount, expected",
    [
        (1232200, "₦1.23M"),
        (750000, "₦750K"),
        (1500, "₦1.5K"),
        (2_000_000_000, "₦2B"),
        (980.5, "₦980.50"),
        (-1_250_000, "-₦1.25M"),
        (0, "₦0.00"),
    ],
)
def test_format_compact(amount, expected):
    assert format_compact(amount, "₦") == expected




# ---------- months ----------

def make_dated(rows):
    """rows: (date string, amount) pairs."""
    df = pd.DataFrame(rows, columns=["Date", "Amount"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def test_month_options_newest_first():
    df = make_dated([("2026-09-03", 1.0), ("2026-11-02", 1.0), ("2026-09-20", 1.0), ("2026-10-05", 1.0)])
    assert [label for label, _ in month_options(df)] == ["Nov 2026", "Oct 2026", "Sep 2026"]


def test_month_options_spans_years():
    df = make_dated([("2025-12-30", 1.0), ("2026-01-02", 1.0)])
    assert [label for label, _ in month_options(df)] == ["Jan 2026", "Dec 2025"]


def test_filter_by_month_keeps_only_that_month():
    df = make_dated([("2026-09-03", 10.0), ("2026-10-05", 20.0), ("2026-10-28", 30.0)])
    october = dict(month_options(df))["Oct 2026"]
    assert filter_by_month(df, october)["Amount"].tolist() == [20.0, 30.0]


def test_filter_by_month_none_returns_everything():
    df = make_dated([("2026-09-03", 10.0), ("2026-10-05", 20.0)])
    assert len(filter_by_month(df, None)) == 2


def test_monthly_totals_fills_missing_months_with_zero():
    debits = make_dated([("2026-09-03", 100.0), ("2026-09-10", 50.0), ("2026-10-05", 80.0)])
    credits = make_dated([("2026-10-01", 500.0)])
    totals = monthly_totals(debits, credits)
    assert totals["Month"].tolist() == ["Sep 2026", "Oct 2026"]
    assert totals["Spent"].tolist() == [150.0, 80.0]
    assert totals["Income"].tolist() == [0.0, 500.0]


def test_monthly_totals_demo_data():
    df, _ = parse_transactions(DEMO_DIR / "demo_transactions.csv")
    totals = monthly_totals(df[df["Debit/Credit"] == "Debit"], df[df["Debit/Credit"] == "Credit"])
    assert totals["Month"].tolist() == ["Sep 2026", "Oct 2026", "Nov 2026"]
    assert totals["Spent"].sum() == 1232200.0
    assert totals["Income"].tolist() == [970000.0, 850000.0, 945000.0]




# ---------- matched keyword ----------

def test_categorize_records_matching_keyword():
    categories = {"Transport": ["Uber"], "Food": ["Uber Eats"]}
    df = categorize_transactions(make_df(["UBER EATS ORDER 55", "UBER *TRIP 9", "RANDOM SHOP"]), categories)
    assert df["Keyword"].tolist()[:2] == ["Uber Eats", "Uber"]
    assert pd.isna(df["Keyword"].iloc[2])


def test_categorize_keyword_is_stripped():
    df = categorize_transactions(make_df(["SPAR VI"]), {"Groceries": ["  Spar "]})
    assert df["Keyword"].tolist() == ["Spar"]


def test_categorize_empty_dataframe():
    df = categorize_transactions(make_df([]), {"Groceries": ["Spar"]})
    assert df.empty
    assert {"Category", "Keyword"} <= set(df.columns)


# ---------- remove_keyword / keyword_table ----------

def test_remove_keyword_ignores_case_and_spaces():
    categories = {"Uncategorized": [], "Groceries": ["Shoprite", "Spar"]}
    remove_keyword(categories, "Groceries", "  SHOPRITE ")
    assert categories["Groceries"] == ["Spar"]


def test_remove_keyword_unknown_category_does_nothing():
    categories = {"Uncategorized": [], "Groceries": ["Spar"]}
    remove_keyword(categories, "Food", "Spar")
    assert categories == {"Uncategorized": [], "Groceries": ["Spar"]}


def test_removing_shorter_rule_lets_row_be_uncategorized():
    categories = {"Uncategorized": [], "Groceries": ["Shoprite"]}
    remove_keyword(categories, "Groceries", "Shoprite")
    df = categorize_transactions(make_df(["POS PURCHASE SHOPRITE LEKKI 0423"]), categories)
    assert df["Category"].tolist() == ["Uncategorized"]


def test_keyword_table_sorted_and_skips_uncategorized():
    categories = {"Uncategorized": ["ignored"], "Transport": ["Uber", "bolt"], "Food": ["KFC"]}
    table = keyword_table(categories)
    assert table.values.tolist() == [["Food", "KFC"], ["Transport", "bolt"], ["Transport", "Uber"]]


def test_keyword_table_empty():
    table = keyword_table({"Uncategorized": []})
    assert table.empty
    assert list(table.columns) == ["Category", "Keyword"]