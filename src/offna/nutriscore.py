from collections.abc import Sequence

import numpy as np
import pandas as pd

THRESHOLDS_2023: dict[str, list[float]] = {
    "energy": [335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350],
    "energy_beverages": [30, 90, 150, 210, 240, 270, 300, 330, 360, 390],
    "sugars": [3.4, 6.8, 10, 14, 17, 20, 24, 27, 31, 34, 37, 41, 44, 48, 51],
    "sugars_beverages": [0.5, 2, 3.5, 5, 6, 7, 8, 9, 10, 11],
    "saturated_fat": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "salt": [0.2, 0.4, 0.6, 0.8, 1, 1.2, 1.4, 1.6, 1.8, 2, 2.2, 2.4, 2.6, 2.8, 3, 3.2, 3.4, 3.6, 3.8, 4],
    "energy_from_saturated_fat": [120, 240, 360, 480, 600, 720, 840, 960, 1080, 1200],
    "saturated_fat_ratio": [10, 16, 22, 28, 34, 40, 46, 52, 58, 64],
    "fvl": [40, 60, 80, 80, 80],
    "fvl_beverages": [40, 40, 60, 60, 80, 80],
    "fiber": [3.0, 4.1, 5.2, 6.3, 7.4],
    "proteins": [2.4, 4.8, 7.2, 9.6, 12, 14, 17],
    "proteins_beverages": [1.2, 1.5, 1.8, 2.1, 2.4, 2.7, 3.0],
}
THRESHOLDS_2021: dict[str, list[float]] = {
    "energy": [335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350],
    "energy_beverages": [0, 30, 60, 90, 120, 150, 180, 210, 240, 270],
    "sugars": [4.5, 9, 13.5, 18, 22.5, 27, 31, 36, 40, 45],
    "sugars_beverages": [0, 1.5, 3, 4.5, 6, 7.5, 9, 10.5, 12, 13.5],
    "saturated_fat": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "saturated_fat_ratio": [10, 16, 22, 28, 34, 40, 46, 52, 58, 64],
    "sodium_mg": [90, 180, 270, 360, 450, 540, 630, 720, 810, 900],
    "fvn": [40, 60, 80, 80, 80],
    "fvn_beverages": [40, 40, 60, 60, 80, 80, 80, 80, 80, 80],
    "fiber": [0.9, 1.9, 2.8, 3.7, 4.7],
    "proteins": [1.6, 3.2, 4.8, 6.4, 8.0],
}
GRADE_CUTOFFS_2023: dict[str, list[int]] = {
    "food": [0, 2, 10, 18],
    "fat_oil_nuts_seeds": [-6, 2, 10, 18],
    "beverage": [-1000, 2, 6, 9],
}
GRADE_CUTOFFS_2021: dict[str, list[int]] = {
    "food": [-1, 2, 10, 18],
    "beverage": [-1000, 1, 5, 9],
}
GRADE_LETTERS = np.array(["a", "b", "c", "d", "e"])
REQUIRED_INPUTS: list[str] = [
    "energy_kj_100g",
    "fat_100g",
    "saturated_fat_100g",
    "sugars_100g",
    "salt_100g",
    "proteins_100g",
]
PROTEIN_LIMIT_FOOD = 11
PROTEIN_LIMIT_FATS = 7
RED_MEAT_PROTEIN_CAP = 2
NON_NUTRITIVE_SWEETENER_POINTS = 4
KJ_PER_GRAM_SATURATED_FAT = 37


def threshold_points(values: np.ndarray, thresholds: Sequence[float], inclusive: bool = False) -> np.ndarray:
    filled = np.where(np.isnan(values), -np.inf, values)
    grid = np.asarray(thresholds, dtype=float)
    hits = filled[:, None] >= grid if inclusive else filled[:, None] > grid
    return hits.sum(axis=1).astype(np.int16)


def _column(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame:
        return np.full(len(frame), np.nan)
    return frame[name].to_numpy(dtype=float, na_value=np.nan)


def _flag(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame:
        return np.zeros(len(frame), dtype=bool)
    return frame[name].fillna(False).to_numpy(dtype=bool)


def _by_type(beverage: np.ndarray, beverage_points: np.ndarray, food_points: np.ndarray) -> np.ndarray:
    return np.where(beverage, beverage_points, food_points)


def _deduced_inputs(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    carbohydrates = _column(frame, "carbohydrates_100g")
    fat = _column(frame, "fat_100g")
    sugars = _column(frame, "sugars_100g")
    saturated = _column(frame, "saturated_fat_100g")
    sugars = np.where(np.isnan(sugars) & (carbohydrates == 0), 0.0, sugars)
    saturated = np.where(np.isnan(saturated) & (fat == 0), 0.0, saturated)
    return {"sugars": sugars, "saturated_fat": saturated, "fat": fat}


def saturated_fat_ratio(saturated: np.ndarray, fat: np.ndarray) -> np.ndarray:
    safe_fat = np.where(fat > 0, fat, saturated)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(saturated > 0, saturated / safe_fat * 100, 0.0)
    return np.round(ratio, 1)


def fruit_veg_share(frame: pd.DataFrame, declared: str, estimate: str) -> np.ndarray:
    share = _column(frame, declared)
    share = np.where(np.isnan(share), _column(frame, estimate), share)
    return np.round(np.nan_to_num(share, nan=0.0), 1)


def has_required_inputs(frame: pd.DataFrame) -> pd.Series:
    deduced = _deduced_inputs(frame)
    present = ~np.isnan(_column(frame, "energy_kj_100g"))
    present &= ~np.isnan(deduced["fat"]) & ~np.isnan(deduced["saturated_fat"]) & ~np.isnan(deduced["sugars"])
    present &= ~np.isnan(_column(frame, "salt_100g")) & ~np.isnan(_column(frame, "proteins_100g"))
    return pd.Series(present, index=frame.index)


def _negative_points_2023(frame: pd.DataFrame, beverage: np.ndarray, fats: np.ndarray) -> np.ndarray:
    table = THRESHOLDS_2023
    deduced = _deduced_inputs(frame)
    energy = _column(frame, "energy_kj_100g")
    energy_points = _by_type(
        beverage,
        threshold_points(energy, table["energy_beverages"]),
        threshold_points(energy, table["energy"]),
    )
    energy_points = np.where(
        fats,
        threshold_points(deduced["saturated_fat"] * KJ_PER_GRAM_SATURATED_FAT, table["energy_from_saturated_fat"]),
        energy_points,
    )
    sugars = deduced["sugars"]
    sugar_points = _by_type(
        beverage,
        threshold_points(sugars, table["sugars_beverages"]),
        threshold_points(sugars, table["sugars"]),
    )
    ratio = saturated_fat_ratio(deduced["saturated_fat"], deduced["fat"])
    saturated_points = np.where(
        fats,
        threshold_points(ratio, table["saturated_fat_ratio"], inclusive=True),
        threshold_points(deduced["saturated_fat"], table["saturated_fat"]),
    )
    salt_points = threshold_points(_column(frame, "salt_100g"), table["salt"])
    sweetener = (np.nan_to_num(_column(frame, "with_non_nutritive_sweeteners"), nan=0.0) > 0) & beverage
    sweetener_points = np.where(sweetener, NON_NUTRITIVE_SWEETENER_POINTS, 0)
    return energy_points + sugar_points + saturated_points + salt_points + sweetener_points


def _positive_points_2023(frame: pd.DataFrame, beverage: np.ndarray, negative: np.ndarray) -> np.ndarray:
    table = THRESHOLDS_2023
    fats = _flag(frame, "is_fat_oil_nuts_seeds")
    proteins = _column(frame, "proteins_100g")
    protein_points = _by_type(
        beverage,
        threshold_points(proteins, table["proteins_beverages"]),
        threshold_points(proteins, table["proteins"]),
    )
    protein_points = np.where(
        _flag(frame, "is_red_meat"), np.minimum(protein_points, RED_MEAT_PROTEIN_CAP), protein_points
    )
    limit = np.where(fats, PROTEIN_LIMIT_FATS, PROTEIN_LIMIT_FOOD)
    counted = beverage | _flag(frame, "is_cheese") | (negative < limit)
    share = fruit_veg_share(frame, "fvl_declared_100g", "fvl_estimate_100g")
    fvl_points = _by_type(
        beverage, threshold_points(share, table["fvl_beverages"]), threshold_points(share, table["fvl"])
    )
    fiber_points = threshold_points(_column(frame, "fiber_100g"), table["fiber"])
    return np.where(counted, protein_points, 0) + fvl_points + fiber_points


def grade_from_score(score: np.ndarray, cutoffs: Sequence[int]) -> np.ndarray:
    return GRADE_LETTERS[np.searchsorted(np.asarray(cutoffs), score, side="left")]


def score_2023(frame: pd.DataFrame) -> pd.DataFrame:
    beverage = _flag(frame, "is_beverage_2023")
    fats = _flag(frame, "is_fat_oil_nuts_seeds") & ~beverage
    negative = _negative_points_2023(frame, beverage, fats)
    score = negative - _positive_points_2023(frame, beverage, negative)
    grade = np.where(
        beverage,
        grade_from_score(score, GRADE_CUTOFFS_2023["beverage"]),
        np.where(
            fats,
            grade_from_score(score, GRADE_CUTOFFS_2023["fat_oil_nuts_seeds"]),
            grade_from_score(score, GRADE_CUTOFFS_2023["food"]),
        ),
    )
    grade = np.where(beverage & _flag(frame, "is_water"), "a", grade)
    return _result(frame, score, grade)


def _rounded(values: np.ndarray, digits: int) -> np.ndarray:
    return np.floor(values * 10**digits + 0.5) / 10**digits


def _sugars_2021(sugars: np.ndarray) -> np.ndarray:
    two_digits = _rounded(sugars, 2)
    fraction = two_digits - np.trunc(two_digits)
    return np.where((fraction > 0.9) | (fraction < 0.1), _rounded(sugars, 1), two_digits)


def score_2021(frame: pd.DataFrame) -> pd.DataFrame:
    table = THRESHOLDS_2021
    beverage = _flag(frame, "is_beverage_2021")
    fats = _flag(frame, "is_fat_2021")
    deduced = _deduced_inputs(frame)
    energy = _rounded(np.nan_to_num(_column(frame, "energy_kj_100g"), nan=0.0), 1)
    sugars = _sugars_2021(np.nan_to_num(deduced["sugars"], nan=0.0))
    saturated = _rounded(np.nan_to_num(deduced["saturated_fat"], nan=0.0), 1)
    ratio = _rounded(saturated_fat_ratio(saturated, np.nan_to_num(deduced["fat"], nan=0.0)), 1)
    sodium_mg = _rounded(np.nan_to_num(_column(frame, "salt_100g"), nan=0.0) / 2.5 * 1000, 1)
    share = fruit_veg_share(frame, "fvn_declared_100g", "fvn_estimate_100g")
    fiber = _rounded(np.nan_to_num(_column(frame, "fiber_100g"), nan=0.0), 2)
    proteins = _rounded(np.nan_to_num(_column(frame, "proteins_100g"), nan=0.0), 2)

    negative = (
        _by_type(
            beverage,
            threshold_points(energy, table["energy_beverages"]),
            threshold_points(energy, table["energy"]),
        )
        + _by_type(
            beverage,
            threshold_points(sugars, table["sugars_beverages"]),
            threshold_points(sugars, table["sugars"]),
        )
        + np.where(
            fats,
            threshold_points(ratio, table["saturated_fat_ratio"], inclusive=True),
            threshold_points(saturated, table["saturated_fat"]),
        )
        + threshold_points(sodium_mg, table["sodium_mg"])
    )
    fruit_points = _by_type(
        beverage, threshold_points(share, table["fvn_beverages"]), threshold_points(share, table["fvn"])
    )
    fruit_max = np.where(beverage, 10, 5)
    counted = (negative < PROTEIN_LIMIT_FOOD) | _flag(frame, "is_cheese") | (fruit_points == fruit_max)
    positive = fruit_points + threshold_points(fiber, table["fiber"])
    positive = positive + np.where(counted, threshold_points(proteins, table["proteins"]), 0)
    score = negative - positive
    grade = np.where(
        beverage,
        grade_from_score(score, GRADE_CUTOFFS_2021["beverage"]),
        grade_from_score(score, GRADE_CUTOFFS_2021["food"]),
    )
    grade = np.where(beverage & _flag(frame, "is_water"), "a", grade)
    return _result(frame, score, grade)


def _result(frame: pd.DataFrame, score: np.ndarray, grade: np.ndarray) -> pd.DataFrame:
    covered = has_required_inputs(frame).to_numpy() & ~_flag(frame, "is_nutriscore_exempt")
    return pd.DataFrame(
        {
            "rule_score": pd.array(np.where(covered, score, 0), dtype="Int16"),
            "rule_grade": pd.array(np.where(covered, grade, None), dtype="string"),
            "rule_covered": covered,
        },
        index=frame.index,
    ).assign(
        rule_score=lambda result: result["rule_score"].mask(~result["rule_covered"]),
    )
