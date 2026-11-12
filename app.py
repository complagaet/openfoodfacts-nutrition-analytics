import pandas as pd
import plotly.express as px
import streamlit as st

from offna.config import CORE_NUTRIENTS, PROFILES, VALID_GRADES
from offna.dashboard import ALL, AggregatesMissingError, filter_aggregates, load_aggregates, summarise

GRADE_COLOURS = {"a": "#038141", "b": "#85bb2f", "c": "#fecb02", "d": "#ee8100", "e": "#e63e11"}


def sidebar_filters(table: pd.DataFrame) -> tuple[str, str]:
    countries = [ALL, *sorted(table["country"].unique())]
    groups = [ALL, *sorted(table["food_group"].unique())]
    country = st.sidebar.selectbox("Sales country", countries)
    food_group = st.sidebar.selectbox("Food group", groups)
    return country, food_group


def show_metrics(summary: dict) -> None:
    columns = st.columns(4)
    columns[0].metric("Product-country pairs", f"{summary['products']:,}")
    columns[1].metric("With Nutri-Score", f"{summary['graded_share']:.1%}")
    columns[2].metric("Complete nutrition table", f"{summary['complete_share']:.1%}")
    columns[3].metric("Ingredients text present", f"{summary['ingredients_share']:.1%}")


def show_grade_chart(grades: pd.DataFrame) -> None:
    if grades.empty:
        st.info("No graded products for this selection.")
        return
    figure = px.bar(
        grades,
        x="nutriscore_grade",
        y="products",
        color="nutriscore_grade",
        color_discrete_map=GRADE_COLOURS,
        category_orders={"nutriscore_grade": VALID_GRADES},
        labels={"nutriscore_grade": "Nutri-Score grade", "products": "Product-country pairs"},
        title="Nutri-Score distribution",
    )
    st.plotly_chart(figure, use_container_width=True)


def show_nutrient_chart(table: pd.DataFrame) -> None:
    means = summarise_nutrients(table)
    figure = px.bar(
        means,
        x="nutrient",
        y="mean_100g",
        labels={"mean_100g": "Mean per 100 g", "nutrient": ""},
        title="Weighted mean nutrients (g/100 g; energy in kcal/100 g)",
    )
    st.plotly_chart(figure, use_container_width=True)


def summarise_nutrients(table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in CORE_NUTRIENTS:
        counts = table[f"{column}_count"]
        total = counts.sum()
        mean = (table[f"{column}_mean"].fillna(0) * counts).sum() / total if total else float("nan")
        rows.append({"nutrient": column.replace("_100g", ""), "mean_100g": mean})
    return pd.DataFrame(rows)


def main() -> None:
    st.set_page_config(page_title="Open Food Facts nutrition", layout="wide")
    st.title("Open Food Facts: nutrition and Nutri-Score explorer")
    profile_name = st.sidebar.radio("Data profile", list(PROFILES), index=0)
    try:
        tables = load_aggregates(PROFILES[profile_name])
    except AggregatesMissingError as error:
        st.error(str(error))
        st.code(f"make pipeline PROFILE={profile_name}")
        return
    country, food_group = sidebar_filters(tables["country_food_group"])
    selected, grades = filter_aggregates(tables, country, food_group)
    if selected.empty:
        st.warning("No products match this selection.")
        return
    show_metrics(summarise(selected))
    left, right = st.columns(2)
    with left:
        show_grade_chart(grades)
    with right:
        show_nutrient_chart(selected)
    st.caption(
        "Unit: product-country pairs. Countries are sales countries, not origin. Data: Open Food Facts, ODbL 1.0."
    )
    st.dataframe(selected.sort_values("products", ascending=False), use_container_width=True)


main()
