"""Tests for transactions.py. Run with: python -m pytest"""
import io

import pandas as pd
import pytest

from transactions import (
    categories_to_json,
    categorize_transactions,
    clean_amounts,
    detect_currency,
    move_keyword_to_category,
    parse_categories,
    parse_transactions,
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


def test_categorize_requires_exact_match():
    # Current behaviour: "UBER *TRIP" does not match "Uber". Smarter matching comes in a later PR.
    df = categorize_transactions(make_df(["UBER *TRIP 123"]), {"Transport": ["Uber"]})
    assert df["Category"].tolist() == ["Uncategorized"]


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