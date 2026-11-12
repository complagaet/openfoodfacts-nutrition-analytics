from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import polars as pl
from matplotlib import pyplot as plt

from offna.config import CORE_NUTRIENTS, SEED, VALID_GRADES, Profile
from offna.etl import scan_processed
from offna.hypotheses import test_h1, test_h2
from offna.measure import peak_rss_mib, write_json

GRADE_COLOURS: dict[str, str] = {
    "a": "#038141",
    "b": "#85bb2f",
    "c": "#fecb02",
    "d": "#ee8100",
    "e": "#e63e11",
}
BOX_SAMPLE_ROWS = 200_000
TOP_COUNTRIES = 12
FIGURE_DPI = 130


def save_figure(figure: plt.Figure, directory: Path, name: str) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(directory / name, dpi=FIGURE_DPI)
    plt.close(figure)
    return name


def descriptive_statistics(products: pl.LazyFrame) -> pd.DataFrame:
    graded = products.filter(pl.col("nutriscore_grade").is_not_null()).select(CORE_NUTRIENTS)
    return graded.collect(engine="streaming").to_pandas().describe(percentiles=[0.25, 0.5, 0.75, 0.95]).T.round(3)


def grade_share_by_food_group(products: pl.LazyFrame) -> pd.DataFrame:
    counts = (
        products.filter(pl.col("nutriscore_grade").is_not_null() & (pl.col("food_group") != "unknown"))
        .group_by("food_group", "nutriscore_grade")
        .len()
        .collect(engine="streaming")
        .to_pandas()
        .pivot(index="food_group", columns="nutriscore_grade", values="len")
        .reindex(columns=VALID_GRADES)
        .fillna(0)
    )
    return counts.div(counts.sum(axis=1), axis=0).sort_values("a")


def plot_grade_share(shares: pd.DataFrame, directory: Path) -> str:
    figure, axis = plt.subplots(figsize=(9, 5.5))
    left = np.zeros(len(shares))
    for grade in VALID_GRADES:
        axis.barh(shares.index, shares[grade], left=left, color=GRADE_COLOURS[grade], label=grade.upper())
        left += shares[grade].to_numpy()
    axis.set_xlabel("Share of graded products")
    axis.set_title("Nutri-Score grade distribution by food group (graded products only)")
    axis.legend(title="Grade", ncols=5, loc="lower center", bbox_to_anchor=(0.5, -0.25))
    return save_figure(figure, directory, "fig1_grade_share_by_food_group.png")


def plot_missing_heatmap(missing: pd.DataFrame, directory: Path) -> str:
    table = missing.set_index("country")[CORE_NUTRIENTS].head(TOP_COUNTRIES)
    figure, axis = plt.subplots(figsize=(10, 6))
    image = axis.imshow(table.to_numpy(), cmap="viridis", vmin=0, vmax=1, aspect="auto")
    axis.set_xticks(
        range(len(CORE_NUTRIENTS)),
        [name.replace("_100g", "") for name in CORE_NUTRIENTS],
        rotation=35,
        ha="right",
    )
    axis.set_yticks(range(len(table)), [name.replace("en:", "") for name in table.index])
    figure.colorbar(image, ax=axis, label="Missing share")
    axis.set_title("Missing per-100 g nutrient values by sales country (product-country pairs)")
    return save_figure(figure, directory, "fig2_missing_by_country.png")


def plot_sugar_by_grade(products: pl.LazyFrame, directory: Path) -> str:
    sample = (
        products.filter(pl.col("nutriscore_grade").is_not_null() & pl.col("sugars_100g").is_not_null())
        .select("nutriscore_grade", "sugars_100g")
        .collect(engine="streaming")
    )
    sample = sample.sample(n=min(BOX_SAMPLE_ROWS, sample.height), seed=SEED).to_pandas()
    figure, axis = plt.subplots(figsize=(8, 5))
    data = [sample.loc[sample["nutriscore_grade"] == grade, "sugars_100g"] for grade in VALID_GRADES]
    boxes = axis.boxplot(data, tick_labels=[g.upper() for g in VALID_GRADES], showfliers=False, patch_artist=True)
    for patch, grade in zip(boxes["boxes"], VALID_GRADES, strict=True):
        patch.set_facecolor(GRADE_COLOURS[grade])
    axis.set_xlabel("Nutri-Score grade")
    axis.set_ylabel("Sugars, g per 100 g")
    axis.set_title(f"Sugars by Nutri-Score grade (random sample of {len(sample):,}, outliers hidden)")
    return save_figure(figure, directory, "fig3_sugars_by_grade.png")


def products_per_year(products: pl.LazyFrame) -> pd.DataFrame:
    return (
        products.filter(pl.col("created_year").is_not_null())
        .group_by("created_year")
        .agg(pl.len().alias("products"), pl.col("nutriscore_grade").is_not_null().mean().alias("graded_share"))
        .sort("created_year")
        .collect(engine="streaming")
        .to_pandas()
    )


def plot_products_per_year(yearly: pd.DataFrame, directory: Path) -> str:
    figure, axis = plt.subplots(figsize=(9, 5))
    axis.bar(yearly["created_year"], yearly["products"], color="#4c72b0")
    axis.set_xlabel("Year the product was added to Open Food Facts")
    axis.set_ylabel("Products added")
    share_axis = axis.twinx()
    share_axis.plot(yearly["created_year"], yearly["graded_share"], color="#dd8452", marker="o")
    share_axis.set_ylabel("Share with a Nutri-Score grade", color="#dd8452")
    share_axis.set_ylim(0, 1)
    axis.set_title("Database growth and Nutri-Score coverage by creation year")
    return save_figure(figure, directory, "fig4_products_per_year.png")


def plot_interactive_profile(profile: Profile, directory: Path) -> str:
    table = pd.read_parquet(profile.aggregates_dir / "country_food_group.parquet")
    table = table[(table["food_group"] != "unknown") & (table["country"] != "(no country)")]
    top = table.groupby("country")["products"].sum().nlargest(TOP_COUNTRIES).index
    table = table[table["country"].isin(top)]
    figure = px.scatter(
        table,
        x="sugars_100g_mean",
        y="salt_100g_mean",
        size="products",
        color="food_group",
        hover_data=["country", "products", "complete_nutrition_share"],
        labels={"sugars_100g_mean": "Mean sugars, g/100 g", "salt_100g_mean": "Mean salt, g/100 g"},
        title="Mean sugars vs salt by sales country and food group (bubble size = product-country pairs)",
    )
    directory.mkdir(parents=True, exist_ok=True)
    figure.write_html(directory / "fig5_interactive_sugar_salt.html", include_plotlyjs="cdn")
    return "fig5_interactive_sugar_salt.html"


def run_eda(profile: Profile) -> dict:
    plt.switch_backend("Agg")
    products = scan_processed(profile)
    figures_dir = profile.figures_dir
    eda_dir = profile.output_dir / "eda"
    eda_dir.mkdir(parents=True, exist_ok=True)
    descriptive_statistics(products).to_csv(eda_dir / "descriptive_statistics.csv")
    shares = grade_share_by_food_group(products)
    shares.round(4).to_csv(eda_dir / "grade_share_by_food_group.csv")
    missing = pd.read_csv(profile.output_dir / "audit" / "missing_by_country.csv")
    yearly = products_per_year(products)
    figures = [
        plot_grade_share(shares, figures_dir),
        plot_missing_heatmap(missing, figures_dir),
        plot_sugar_by_grade(products, figures_dir),
        plot_products_per_year(yearly, figures_dir),
        plot_interactive_profile(profile, figures_dir),
    ]
    report = {
        "profile": profile.name,
        "figures": figures,
        "h1": test_h1(products, eda_dir),
        "h2": test_h2(products, eda_dir),
        "peak_rss_mib": round(peak_rss_mib(), 1),
    }
    write_json(profile.reports_dir / "eda_report.json", report)
    return report
