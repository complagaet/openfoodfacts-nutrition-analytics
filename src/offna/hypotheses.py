from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from scipy.stats import chi2_contingency, mannwhitneyu

from offna.config import CORE_NUTRIENTS, SEED, VALID_GRADES

ALPHA = 0.05
H1_TOP_COUNTRIES = 10
H1_MIN_PRODUCTS_PER_CELL = 200
H1_MIN_EFFECT_V = 0.1
H2_MIN_PER_ARM = 30
BOOTSTRAP_RESAMPLES = 1000
MIN_EXPECTED_COUNT = 5
GRADE_BANDS: dict[str, list[str]] = {"ab": ["a", "b"], "c": ["c"], "de": ["d", "e"]}

H1_PROTOCOL = (
    "Unit: products sold in exactly one country (avoids counting one product several times), known food group, "
    f"top {H1_TOP_COUNTRIES} countries. Outcome: all 8 core per-100 g nutrients present. "
    f"Per food group with >=2 countries of >={H1_MIN_PRODUCTS_PER_CELL} products: chi-square test of independence "
    f"country x complete, effect Cramer's V, Holm correction over food groups, alpha {ALPHA}. "
    f"H1 supported if a majority of tested groups is Holm-significant with V >= {H1_MIN_EFFECT_V}."
)
H2_PROTOCOL = (
    "Unit: products with parsed ingredients (ingredients_n > 0), so a missing sweetener flag means 'none detected', "
    "not 'unknown'. Strata: level-2 food groups (comparable categories) with >= "
    f"{H2_MIN_PER_ARM} products in each arm. Sugars: two-sided Mann-Whitney U, effect = median difference "
    f"(sweetener - none) with bootstrap 95% CI ({BOOTSTRAP_RESAMPLES} resamples, seed {SEED}) and rank-biserial r. "
    "Bootstrap uses every observation of both arms. Nutri-Score: chi-square sweetener x grade on graded products "
    f"when all expected counts are >= {MIN_EXPECTED_COUNT}; otherwise grades are merged into AB/C/DE, and the "
    "stratum is skipped if that is still too sparse. Cramer's V, Holm correction within each family."
)


def holm_adjust(p_values: list[float]) -> list[float]:
    order = np.argsort(p_values)
    count = len(p_values)
    adjusted = np.empty(count)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (count - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted.tolist()


def cramers_v(table: np.ndarray) -> float:
    chi2 = chi2_contingency(table, correction=False)[0]
    total = table.sum()
    smaller = min(table.shape) - 1
    return float(np.sqrt(chi2 / (total * smaller))) if total and smaller else float("nan")


def h1_frame(products: pl.LazyFrame) -> pd.DataFrame:
    single = products.filter((pl.col("countries_tags").list.len() == 1) & (pl.col("food_group") != "unknown")).select(
        pl.col("countries_tags").list.first().alias("country"),
        pl.col("food_group").cast(pl.String),
        pl.all_horizontal(pl.col(column).is_not_null() for column in CORE_NUTRIENTS).alias("complete"),
    )
    frame = single.collect(engine="streaming").to_pandas()
    top = frame["country"].value_counts().head(H1_TOP_COUNTRIES).index
    return frame[frame["country"].isin(top)]


def h1_group_test(group: pd.DataFrame) -> dict | None:
    sizes = group["country"].value_counts()
    eligible = sizes[sizes >= H1_MIN_PRODUCTS_PER_CELL].index
    group = group[group["country"].isin(eligible)]
    if len(eligible) < 2:
        return None
    table = pd.crosstab(group["country"], group["complete"]).reindex(columns=[False, True], fill_value=0)
    if (table.sum(axis=0) == 0).any():
        return None
    shares = group.groupby("country")["complete"].mean()
    return {
        "countries": len(eligible),
        "products": len(group),
        "p_value": float(chi2_contingency(table.to_numpy(), correction=False)[1]),
        "cramers_v": round(cramers_v(table.to_numpy()), 4),
        "min_complete_share": round(float(shares.min()), 4),
        "max_complete_share": round(float(shares.max()), 4),
        "min_country": shares.idxmin(),
        "max_country": shares.idxmax(),
    }


def test_h1(products: pl.LazyFrame, output_dir: Path) -> dict:
    frame = h1_frame(products)
    rows = []
    for food_group, group in frame.groupby("food_group"):
        result = h1_group_test(group)
        if result is not None:
            rows.append({"food_group": food_group, **result})
    if not rows:
        return {"protocol": H1_PROTOCOL, "tested_groups": 0, "verdict": "not testable: too few products"}
    table = pd.DataFrame(rows)
    table["p_holm"] = holm_adjust(table["p_value"].tolist())
    table["supports"] = (table["p_holm"] < ALPHA) & (table["cramers_v"] >= H1_MIN_EFFECT_V)
    table.to_csv(output_dir / "h1_completeness_by_country.csv", index=False)
    supported = int(table["supports"].sum())
    return {
        "protocol": H1_PROTOCOL,
        "tested_groups": len(table),
        "supporting_groups": supported,
        "median_cramers_v": round(float(table["cramers_v"].median()), 4),
        "verdict": "supported" if supported * 2 > len(table) else "not supported",
    }


def h2_frame(products: pl.LazyFrame) -> pd.DataFrame:
    return (
        products.filter((pl.col("ingredients_n").fill_null(0) > 0) & pl.col("food_group_l2").is_not_null())
        .select("food_group_l2", "with_non_nutritive_sweeteners", "sugars_100g", "nutriscore_grade")
        .collect(engine="streaming")
        .to_pandas()
    )


def bootstrap_median_difference(
    treated: np.ndarray, control: np.ndarray, rng: np.random.Generator
) -> tuple[float, float]:
    draws = [
        np.median(rng.choice(treated, len(treated))) - np.median(rng.choice(control, len(control)))
        for _ in range(BOOTSTRAP_RESAMPLES)
    ]
    low, high = np.percentile(draws, [2.5, 97.5])
    return float(low), float(high)


def h2_sugar_test(group: pd.DataFrame, rng: np.random.Generator) -> dict | None:
    sugars = group.dropna(subset=["sugars_100g"])
    treated = sugars.loc[sugars["with_non_nutritive_sweeteners"] == 1, "sugars_100g"].to_numpy()
    control = sugars.loc[sugars["with_non_nutritive_sweeteners"] == 0, "sugars_100g"].to_numpy()
    if min(len(treated), len(control)) < H2_MIN_PER_ARM:
        return None
    statistic, p_value = mannwhitneyu(treated, control, alternative="two-sided")
    low, high = bootstrap_median_difference(treated, control, rng)
    return {
        "n_sweetener": len(treated),
        "n_none": len(control),
        "median_sugars_sweetener": round(float(np.median(treated)), 2),
        "median_sugars_none": round(float(np.median(control)), 2),
        "median_difference": round(float(np.median(treated) - np.median(control)), 2),
        "ci95_low": round(low, 2),
        "ci95_high": round(high, 2),
        "rank_biserial": round(float(2 * statistic / (len(treated) * len(control)) - 1), 4),
        "p_value": float(p_value),
    }


def _min_expected(table: pd.DataFrame) -> float:
    return float(chi2_contingency(table.to_numpy(), correction=False)[3].min())


def chi2_ready_table(table: pd.DataFrame) -> tuple[str, pd.DataFrame | None]:
    table = table.loc[:, table.sum(axis=0) > 0]
    if table.shape[1] < 2:
        return "skipped_single_grade", None
    if _min_expected(table) >= MIN_EXPECTED_COUNT:
        return "chi2_5_grades", table
    merged = pd.DataFrame(
        {band: table.reindex(columns=grades, fill_value=0).sum(axis=1) for band, grades in GRADE_BANDS.items()}
    )
    merged = merged.loc[:, merged.sum(axis=0) > 0]
    if merged.shape[1] >= 2 and _min_expected(merged) >= MIN_EXPECTED_COUNT:
        return "chi2_merged_ab_c_de", merged
    return "skipped_expected_below_5", None


def h2_grade_test(group: pd.DataFrame) -> dict | None:
    graded = group[group["nutriscore_grade"].isin(VALID_GRADES)]
    table = pd.crosstab(graded["with_non_nutritive_sweeteners"], graded["nutriscore_grade"])
    if table.shape[0] < 2 or table.sum(axis=1).min() < H2_MIN_PER_ARM:
        return None
    method, tested = chi2_ready_table(table)
    shares = table.div(table.sum(axis=1), axis=0)
    summary = {
        "graded_sweetener": int(table.loc[1].sum()),
        "graded_none": int(table.loc[0].sum()),
        "share_ab_sweetener": round(float(shares.loc[1, [g for g in ["a", "b"] if g in shares]].sum()), 4),
        "share_ab_none": round(float(shares.loc[0, [g for g in ["a", "b"] if g in shares]].sum()), 4),
        "grade_test": method,
    }
    if tested is None:
        return summary
    return {
        **summary,
        "grade_cramers_v": round(cramers_v(tested.to_numpy()), 4),
        "grade_p_value": float(chi2_contingency(tested.to_numpy(), correction=False)[1]),
    }


def test_h2(products: pl.LazyFrame, output_dir: Path) -> dict:
    frame = h2_frame(products)
    rng = np.random.default_rng(SEED)
    rows = []
    for food_group, group in frame.groupby("food_group_l2"):
        sugar = h2_sugar_test(group, rng)
        if sugar is not None:
            rows.append({"food_group_l2": food_group, **sugar, **(h2_grade_test(group) or {})})
    if not rows:
        return {"protocol": H2_PROTOCOL, "tested_groups": 0, "verdict": "not testable: too few products"}
    table = pd.DataFrame(rows)
    table["p_holm"] = holm_adjust(table["p_value"].tolist())
    if "grade_p_value" in table:
        tested = table["grade_p_value"].notna()
        table.loc[tested, "grade_p_holm"] = holm_adjust(table.loc[tested, "grade_p_value"].tolist())
    table.to_csv(output_dir / "h2_sweeteners.csv", index=False)
    significant = table[table["p_holm"] < ALPHA]
    return {
        "protocol": H2_PROTOCOL,
        "population_products": len(frame),
        "share_with_sweetener": round(float((frame["with_non_nutritive_sweeteners"] == 1).mean()), 4),
        "tested_groups": len(table),
        "sugar_significant_groups": len(significant),
        "sugar_lower_with_sweetener_groups": int((significant["median_difference"] < 0).sum()),
        "grade_significant_groups": int((table.get("grade_p_holm", pd.Series(dtype=float)) < ALPHA).sum()),
        "grade_test_methods": table.get("grade_test", pd.Series(dtype=str)).value_counts().to_dict(),
        "verdict": "supported" if len(significant) * 2 > len(table) else "not supported",
    }
