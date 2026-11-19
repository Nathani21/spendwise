import streamlit as st
import pandas as pd
import plotly.express as px
import json
import os
import re

st.set_page_config(page_title="Simple Finance App", page_icon="💰", layout="wide")

category_file = "categories.json"

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

if "categories" not in st.session_state:
    st.session_state.categories = {
        "Uncategorized": []
    }

if os.path.exists(category_file):
    with open(category_file, "r") as f:
        st.session_state.categories = json.load(f)

def save_categories():
    with open(category_file, "w") as f:
        json.dump(st.session_state.categories, f)

def categorize_transactions(df):
    df["Category"] = "Uncategorized"

    for category, keywords in st.session_state.categories.items():
        if category == "Uncategorized" or not keywords:
            continue

        lowered_keywords = [keyword.lower().strip() for keyword in keywords]

        for idx, row in df.iterrows():
            details = row["Details"].lower()
            if details in lowered_keywords:
                df.at[idx, "Category"] = category
    
    return df

def load_transactions(file):
    try:
        df = pd.read_csv(file)
        df.columns = [col.strip() for col in df.columns]

        currency = detect_currency(df)

        df["Amount"] = (
            df["Amount"].astype(str)
            .str.replace(r"[^0-9.\-]", "", regex=True)
            .astype(float)
        )
        df["Date"] = pd.to_datetime(df["Date"], format="%d %b %Y")

        return categorize_transactions(df), currency
    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        return None, None

def add_keyword_to_category(category, keyword):
    keyword = keyword.strip()
    if keyword and keyword not in st.session_state.categories[category]:
        st.session_state.categories[category].append(keyword)
        save_categories()
        return True
    return False

def main():
    st.title("Simple Finance Dashboard")
    
    uploaded_file = st.file_uploader("Upload your transaction CSV file", type=["csv"])

    if uploaded_file is not None:
        df, detected = load_transactions(uploaded_file)

        if df is not None:
            codes = list(CURRENCIES.keys())
            default = detected or DEFAULT_CURRENCY
            currency = st.sidebar.selectbox("Currency", codes, index=codes.index(default))
            if detected:
                st.sidebar.caption(f"Detected {detected} from your file")
            symbol = CURRENCIES[currency]
            money_format = f"{symbol}%.2f"
            debits_df = df[df["Debit/Credit"] == "Debit"].copy()
            credits_df = df[df["Debit/Credit"] == "Credit"].copy()

            st.session_state.debits_df = debits_df.copy()

            tab1, tab2 = st.tabs(["Expenses (Debits)", "Payments (Credits)"])
            with tab1:
                new_category = st.text_input("New Category Name")
                add_button = st.button("Add Category")
                if add_button and new_category:
                    if new_category not in st.session_state.categories:
                        st.session_state.categories[new_category] = []
                        save_categories()
                        st.rerun()
                st.subheader("Your Expenses")
                edited_df = st.data_editor(
                    st.session_state.debits_df[["Date", "Details", "Amount", "Category"]],
                    column_config={
                        "Date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                        "Amount": st.column_config.NumberColumn("Amount", format=money_format),
                        "Category": st.column_config.SelectboxColumn(
                            "Category",
                            options=list(st.session_state.categories.keys())
                        )
                    },
                    hide_index=True,
                    width="stretch",
                    key="category_editor"
                )

                save_button = st.button("Apply Changes", type="primary")
                if save_button:
                    for idx, row in edited_df.iterrows():
                        new_category = row["Category"]
                        if new_category == st.session_state.debits_df.at[idx, "Category"]:
                            continue

                        details = row["Details"]
                        st.session_state.debits_df.at[idx, "Category"] = new_category
                        add_keyword_to_category(new_category, details)
                
                st.subheader("Expense Summary")
                category_totals = st.session_state.debits_df.groupby("Category")["Amount"].sum().reset_index()
                category_totals = category_totals.sort_values("Amount", ascending=False)

                st.dataframe(
                    category_totals,
                    column_config={
                        "Amount": st.column_config.NumberColumn("Amount", format=money_format)
                    },
                    width="stretch",
                    hide_index=True
                )

                fig = px.pie(
                    category_totals,
                    values="Amount",
                    names="Category",
                    title="Expenses by Category"
                )
                st.plotly_chart(fig, width="stretch")

            
            with tab2:
                st.subheader("Payment Summary")
                total_payments = credits_df["Amount"].sum()
                st.metric("Total Payments", f"{symbol}{total_payments:,.2f}")
                st.write(credits_df)

main()