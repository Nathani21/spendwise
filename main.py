import streamlit as st
import plotly.express as px
import json
import os

from transactions import (
    CURRENCIES,
    DEFAULT_CURRENCY,
    categorize_transactions,
    move_keyword_to_category,
    parse_transactions,
)

st.set_page_config(page_title="Simple Finance App", page_icon="💰", layout="wide")

category_file = "categories.json"





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



def load_transactions(file):
    try:
        df, currency = parse_transactions(file)
        return categorize_transactions(df, st.session_state.categories), currency
    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        return None, None


def main():
    st.title("Simple Finance Dashboard")
    
    uploaded_file = st.file_uploader("Upload your transaction CSV file", type=["csv"])

    if uploaded_file is not None:
        file_key = f"{uploaded_file.name}-{uploaded_file.size}"
        if st.session_state.get("file_key") != file_key:
            df, detected = load_transactions(uploaded_file)
            if df is not None:
                st.session_state.file_key = file_key
                st.session_state.df = df
                st.session_state.detected = detected
                st.session_state.debits_df = df[df["Debit/Credit"] == "Debit"].copy()
                st.session_state.editor_version = 0
        else:
            df = st.session_state.df
            detected = st.session_state.detected

        if df is not None:
            codes = list(CURRENCIES.keys())
            default = detected or DEFAULT_CURRENCY
            currency = st.sidebar.selectbox("Currency", codes, index=codes.index(default))
            if detected:
                st.sidebar.caption(f"Detected {detected} from your file")
            symbol = CURRENCIES[currency]
            money_format = f"{symbol}%.2f"
            credits_df = df[df["Debit/Credit"] == "Credit"].copy()

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
                    key=f"category_editor_{st.session_state.editor_version}"
                )

                save_button = st.button("Apply Changes", type="primary")
                if save_button:
                    for idx, row in edited_df.iterrows():
                        new_category = row["Category"]
                        if new_category == st.session_state.debits_df.at[idx, "Category"]:
                            continue
                        move_keyword_to_category(st.session_state.categories, new_category, row["Details"])

                    save_categories()
                    st.session_state.debits_df = categorize_transactions(
                        st.session_state.debits_df, st.session_state.categories
                    )
                    st.session_state.editor_version += 1
                    st.rerun()
                
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