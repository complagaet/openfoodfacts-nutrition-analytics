import pandas as pd

from offna.aggregates import DASHBOARD_TABLES
from offna.config import Profile

ALL = "(all)"


class AggregatesMissingError(FileNotFoundError):
    pass


def load_aggregates(profile: Profile) -> dict[str, pd.DataFrame]:
    tables = {}
    for name in DASHBOARD_TABLES:
        path = profile.aggregates_dir / f"{name}.parquet"
        try:
            tables[name] = pd.read_parquet(path)
        except FileNotFoundError as error:
            raise AggregatesMissingError(
                f"Aggregate file {path.name} for profile '{profile.name}' is missing. Run the pipeline first."
            ) from error
    return tables


def _mask(frame: pd.DataFrame, country: str, food_group: str) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    if country != ALL:
        mask &= frame["country"] == country
    if food_group != ALL:
        mask &= frame["food_group"] == food_group
    return mask


def filter_aggregates(
    tables: dict[str, pd.DataFrame], country: str, food_group: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    profile_table = tables["country_food_group"]
    selected = profile_table[_mask(profile_table, country, food_group)]
    grade_table = tables["grade_counts"]
    grades = (
        grade_table[_mask(grade_table, country, food_group)]
        .groupby("nutriscore_grade", as_index=False)["products"]
        .sum()
    )
    return selected, grades


def weighted_share(frame: pd.DataFrame, column: str) -> float:
    total = frame["products"].sum()
    return float((frame[column] * frame["products"]).sum() / total) if total else 0.0


def summarise(frame: pd.DataFrame) -> dict:
    products = int(frame["products"].sum())
    return {
        "products": products,
        "graded_share": float(frame["graded"].sum() / products) if products else 0.0,
        "complete_share": weighted_share(frame, "complete_nutrition_share"),
        "ingredients_share": weighted_share(frame, "ingredients_text_share"),
    }
