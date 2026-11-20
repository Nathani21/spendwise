from pathlib import Path

import streamlit as st
import plotly.express as px

from transactions import (
    CURRENCIES,
    DEFAULT_CURRENCY,
    categories_to_json,
    categorize_transactions,
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

APP_ICON = Path(__file__).parent / "assets" / "icon.png"

st.set_page_config(page_title="Spendwise", page_icon=str(APP_ICON), layout="wide")

DEMO_DIR = Path(__file__).parent / "sample_data"
DEMO_TRANSACTIONS = DEMO_DIR / "demo_transactions.csv"
DEMO_CATEGORIES = DEMO_DIR / "demo_categories.json"

SPENT_COLOR = "#F97316"
INCOME_COLOR = "#10B981"

if "categories" not in st.session_state:
    st.session_state.categories = {
        "Uncategorized": []
    }


def categories_sidebar():
    """Export and import categories, so they live with the user instead of on the server."""
    st.sidebar.subheader("Categories")
    st.sidebar.download_button(
        "Export categories",
        data=categories_to_json(st.session_state.categories),
        file_name="spendwise-categories.json",
        mime="application/json",
    )

    imported = st.sidebar.file_uploader("Import categories", type=["json"])
    if imported is None:
        return

    import_key = f"{imported.name}-{imported.size}"
    if st.session_state.get("categories_import_key") == import_key:
        return

    try:
        st.session_state.categories = parse_categories(imported.getvalue())
    except ValueError as e:
        st.sidebar.error(str(e))
        return

    st.session_state.categories_import_key = import_key
    if "debits_df" in st.session_state:
        st.session_state.debits_df = categorize_transactions(
            st.session_state.debits_df, st.session_state.categories
        )
        st.session_state.editor_version += 1
    st.sidebar.success("Categories imported")

def refresh_categories():
    """Re-categorise loaded transactions after the keyword lists change."""
    if "debits_df" in st.session_state:
        st.session_state.debits_df = categorize_transactions(
            st.session_state.debits_df, st.session_state.categories
        )
        st.session_state.editor_version += 1

def load_transactions(file):
    try:
        df, currency = parse_transactions(file)
        return categorize_transactions(df, st.session_state.categories), currency
    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        return None, None


def main():
    st.title("Spendwise")
    st.caption(
        "Upload a bank CSV to see where your money goes. "
        "Your file is processed in memory and isn't saved anywhere: close the tab and it's gone."
    )
    view_settings = st.sidebar.container()
    categories_sidebar()
    
    uploaded_file = st.file_uploader(
        "Upload your transaction CSV file",
        type=["csv"],
        help="Columns: Date (like 05 Jan 2026), Details, Amount, Debit/Credit. Optional: Currency.",
    )

    if uploaded_file is not None:
        source = uploaded_file
        file_key = f"{uploaded_file.name}-{uploaded_file.size}"
        st.session_state.use_demo = False
    elif st.session_state.get("use_demo"):
        source = DEMO_TRANSACTIONS
        file_key = "demo"
        st.info("You're looking at demo data. Upload your own CSV above to replace it.")
    else:
        source = None
        if st.button("Try demo data"):
            if list(st.session_state.categories) == ["Uncategorized"]:
                st.session_state.categories = parse_categories(DEMO_CATEGORIES.read_bytes())
            st.session_state.use_demo = True
            st.rerun()

    if source is not None:
        if st.session_state.get("file_key") != file_key:
            df, detected = load_transactions(source)
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
            view_settings.subheader("View")
            codes = list(CURRENCIES.keys())
            default = detected or DEFAULT_CURRENCY
            currency = view_settings.selectbox("Currency", codes, index=codes.index(default))
            if detected:
                source_name = "the demo data" if file_key == "demo" else "your file"
                view_settings.caption(f"Detected {detected} from {source_name}")
            symbol = CURRENCIES[currency]
            money_format = f"{symbol}%.2f"
            all_credits = df[df["Debit/Credit"] == "Credit"]
            months = month_options(df)
            month_label = view_settings.selectbox("Month", ["All months"] + [label for label, _ in months])
            period = dict(months).get(month_label)

            debits_view = filter_by_month(st.session_state.debits_df, period)
            credits_df = filter_by_month(all_credits, period).copy()

            summary = summarize(debits_view, credits_df)
            spent_col, income_col, savings_col, top_col = st.columns(4, border=True)
            spent_col.metric("Total spent", format_compact(summary["total_spent"], symbol))
            spent_col.caption(format_money(summary["total_spent"], symbol))

            income_col.metric("Income", format_compact(summary["total_income"], symbol))
            income_col.caption(format_money(summary["total_income"], symbol))

            rate = summary["savings_rate"]
            if rate is None:
                savings_col.metric("Savings rate", "—")
                savings_col.caption("No income in this file")
            else:
                saved = summary["total_income"] - summary["total_spent"]
                savings_col.metric("Savings rate", f"{rate:.0f}%")
                savings_col.caption(f"{format_money(saved, symbol)} kept")

            if summary["top_category"]:
                top_col.metric("Biggest category", summary["top_category"])
                top_col.caption(format_money(summary["top_amount"], symbol))
            else:
                top_col.metric("Biggest category", "—")
                top_col.caption("Categorise expenses to see this")

            tab1, tab2, tab3 = st.tabs(["Expenses", "Income", "Monthly trend"])
            with tab1:
                new_category = st.text_input("New Category Name")
                add_button = st.button("Add Category")
                if add_button and new_category:
                    if new_category not in st.session_state.categories:
                        st.session_state.categories[new_category] = []
                        st.rerun()

                with st.expander("Manage keywords"):
                    st.caption(
                        "A keyword matches when it appears as a whole word in a transaction's details. "
                        "If several match, the longest wins."
                    )
                    named = [name for name in st.session_state.categories if name != "Uncategorized"]
                    if not named:
                        st.info("Add a category first.")
                    else:
                        with st.form("add_keyword", clear_on_submit=True):
                            category_col, keyword_col = st.columns([1, 2])
                            keyword_category = category_col.selectbox("Category", named)
                            keyword_text = keyword_col.text_input("Keyword", placeholder="e.g. Shoprite")
                            if st.form_submit_button("Add keyword") and keyword_text.strip():
                                move_keyword_to_category(
                                    st.session_state.categories, keyword_category, keyword_text
                                )
                                refresh_categories()
                                st.rerun()

                        rules = keyword_table(st.session_state.categories).assign(Remove=False)
                        if rules.empty:
                            st.caption("No keywords yet.")
                        else:
                            edited_rules = st.data_editor(
                                rules,
                                column_config={"Remove": st.column_config.CheckboxColumn("Remove")},
                                disabled=["Category", "Keyword"],
                                hide_index=True,
                                width="stretch",
                                key=f"keyword_editor_{st.session_state.editor_version}",
                            )
                            if st.button("Remove selected keywords"):
                                for _, rule in edited_rules[edited_rules["Remove"]].iterrows():
                                    remove_keyword(
                                        st.session_state.categories, rule["Category"], rule["Keyword"]
                                    )
                                refresh_categories()
                                st.rerun()

                st.subheader("Your Expenses")
                edited_df = st.data_editor(
                    debits_view[["Date", "Details", "Amount", "Keyword", "Category"]],
                    column_config={
                        "Date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                        "Amount": st.column_config.NumberColumn("Amount", format=money_format),
                        "Keyword": st.column_config.TextColumn("Matched keyword"),
                        "Category": st.column_config.SelectboxColumn(
                            "Category",
                            options=list(st.session_state.categories.keys())
                        )
                    },
                    hide_index=True,
                    width="stretch",
                    disabled=["Keyword"],
                    key=f"category_editor_{st.session_state.editor_version}_{month_label}"
                )

                save_button = st.button("Apply Changes", type="primary")
                if save_button:
                    for idx, row in edited_df.iterrows():
                        new_category = row["Category"]
                        if new_category == st.session_state.debits_df.at[idx, "Category"]:
                            continue
                        move_keyword_to_category(st.session_state.categories, new_category, row["Details"])

                    st.session_state.debits_df = categorize_transactions(
                        st.session_state.debits_df, st.session_state.categories
                    )
                    st.session_state.editor_version += 1
                    st.rerun()
                
                st.subheader("Expense Summary")
                category_totals = debits_view.groupby("Category")["Amount"].sum().reset_index()
                category_totals = category_totals.sort_values("Amount", ascending=False)

                st.dataframe(
                    category_totals,
                    column_config={
                        "Amount": st.column_config.NumberColumn("Amount", format=money_format)
                    },
                    width="stretch",
                    hide_index=True
                )

                chart_data = category_totals.assign(
                    Label=category_totals["Amount"].apply(lambda amount: format_compact(amount, symbol))
                )
                fig = px.bar(
                    chart_data,
                    x="Amount",
                    y="Category",
                    orientation="h",
                    text="Label",
                    title="Expenses by Category",
                    color_discrete_sequence=[SPENT_COLOR],
                )
                fig.update_traces(
                    textposition="outside",
                    cliponaxis=False,
                    hovertemplate="%{y}: " + symbol + "%{x:,.2f}<extra></extra>",
                )
                fig.update_layout(
                    yaxis={"categoryorder": "total ascending", "title": None},
                    xaxis={"title": None, "showticklabels": False, "showgrid": False},
                    height=max(250, 50 * len(chart_data) + 100),
                    margin={"l": 0, "r": 60, "t": 50, "b": 0},
                )
                st.plotly_chart(fig, width="stretch")

            
            with tab2:
                st.subheader("Income")
                if credits_df.empty:
                    st.info("No income in this period.")
                else:
                    st.dataframe(
                        credits_df[["Date", "Details", "Amount"]].sort_values("Date"),
                        column_config={
                            "Date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                            "Amount": st.column_config.NumberColumn("Amount", format=money_format),
                        },
                        hide_index=True,
                        width="stretch",
                    )

            with tab3:
                trend = monthly_totals(st.session_state.debits_df, all_credits)
                if len(trend) < 2:
                    st.info("Upload transactions from at least two months to see a trend.")
                else:
                    trend_fig = px.bar(
                        trend,
                        x="Month",
                        y=["Spent", "Income"],
                        barmode="group",
                        title="Spending vs income by month",
                        color_discrete_map={"Spent": SPENT_COLOR, "Income": INCOME_COLOR},
                    )
                    trend_fig.update_traces(
                        hovertemplate="%{x}: " + symbol + "%{y:,.2f}<extra>%{fullData.name}</extra>"
                    )
                    trend_fig.update_layout(
                        xaxis_title=None,
                        yaxis_title=None,
                        legend_title_text=None,
                        margin={"l": 0, "r": 0, "t": 50, "b": 0},
                    )
                    st.plotly_chart(trend_fig, width="stretch")

main()