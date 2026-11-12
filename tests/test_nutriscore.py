import numpy as np
import pandas as pd
import pytest

from offna.nutriscore import (
    GRADE_CUTOFFS_2021,
    GRADE_CUTOFFS_2023,
    grade_from_score,
    saturated_fat_ratio,
    score_2021,
    score_2023,
    threshold_points,
)

HAZELNUT_SPREAD = {
    "energy_kj_100g": 2524.0,
    "fat_100g": 48.0,
    "saturated_fat_100g": 10.0,
    "sugars_100g": 32.0,
    "salt_100g": 0.01,
    "proteins_100g": 8.0,
    "fvl_declared_100g": 0.0,
}
HARD_CHEESE = {
    "energy_kj_100g": 1500.0,
    "fat_100g": 28.0,
    "saturated_fat_100g": 18.0,
    "sugars_100g": 0.5,
    "salt_100g": 1.8,
    "proteins_100g": 25.0,
    "is_cheese": True,
}
OLIVE_OIL = {
    "energy_kj_100g": 3700.0,
    "fat_100g": 100.0,
    "saturated_fat_100g": 14.0,
    "sugars_100g": 0.0,
    "salt_100g": 0.0,
    "proteins_100g": 0.0,
    "fvl_declared_100g": 100.0,
    "is_fat_oil_nuts_seeds": True,
}
COLA = {
    "energy_kj_100g": 180.0,
    "fat_100g": 0.0,
    "saturated_fat_100g": 0.0,
    "sugars_100g": 10.6,
    "salt_100g": 0.0,
    "proteins_100g": 0.0,
    "is_beverage_2023": True,
}
DIET_COLA = {**COLA, "energy_kj_100g": 1.0, "sugars_100g": 0.0, "with_non_nutritive_sweeteners": 1.0}
SPRING_WATER = {**DIET_COLA, "with_non_nutritive_sweeteners": 0.0, "is_water": True}


def score(product: dict, rule=score_2023) -> tuple[int, str]:
    result = rule(pd.DataFrame([product])).iloc[0]
    return int(result["rule_score"]), result["rule_grade"]


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        (HAZELNUT_SPREAD, (25, "e")),
        (HARD_CHEESE, (15, "d")),
        (OLIVE_OIL, (0, "b")),
        (COLA, (12, "e")),
        (DIET_COLA, (4, "c")),
    ],
)
def test_hand_checked_products_2023(product: dict, expected: tuple[int, str]) -> None:
    assert score(product) == expected


def test_spring_water_is_always_a() -> None:
    assert score(SPRING_WATER)[1] == "a"


def test_2021_rule_differs_for_hazelnut_spread() -> None:
    assert score(HAZELNUT_SPREAD, score_2021) == (23, "e")


def test_points_are_awarded_strictly_above_threshold() -> None:
    values = np.array([3.4, 3.41, np.nan])
    assert threshold_points(values, [3.4, 6.8]).tolist() == [0, 1, 0]


def test_missing_required_nutrient_is_not_covered() -> None:
    incomplete = {key: value for key, value in HAZELNUT_SPREAD.items() if key != "salt_100g"}
    result = score_2023(pd.DataFrame([incomplete])).iloc[0]
    assert not result["rule_covered"]
    assert pd.isna(result["rule_grade"])


LEAN_BEEF = {
    "energy_kj_100g": 800.0,
    "fat_100g": 6.0,
    "saturated_fat_100g": 3.0,
    "sugars_100g": 0.0,
    "salt_100g": 1.0,
    "proteins_100g": 20.0,
}
MILK_DRINK = {
    "energy_kj_100g": 270.0,
    "fat_100g": 3.5,
    "saturated_fat_100g": 2.3,
    "sugars_100g": 4.8,
    "salt_100g": 0.1,
    "proteins_100g": 3.3,
    "is_beverage_2023": True,
}


def test_red_meat_protein_points_are_capped_at_two() -> None:
    assert score(LEAN_BEEF) == (1, "b")
    assert score({**LEAN_BEEF, "is_red_meat": True}) == (6, "c")


def test_beverages_use_beverage_protein_table_and_always_count_protein() -> None:
    assert score(MILK_DRINK) == (3, "c")
    assert score({**MILK_DRINK, "proteins_100g": 0.0}) == (10, "e")


def test_saturated_fat_ratio_threshold_is_inclusive_for_fats() -> None:
    oil = {**OLIVE_OIL, "fvl_declared_100g": 0.0, "fat_100g": 50.0}
    assert score({**oil, "saturated_fat_100g": 5.0})[0] == 2
    assert score({**oil, "saturated_fat_100g": 4.9})[0] == 1


def test_zero_fat_with_saturated_fat_follows_off_ratio_rule() -> None:
    assert saturated_fat_ratio(np.array([2.0, 0.0]), np.array([0.0, 0.0])).tolist() == [100.0, 0.0]


@pytest.mark.parametrize(
    ("cutoffs", "scores", "grades"),
    [
        (GRADE_CUTOFFS_2023["food"], [0, 1, 2, 3, 10, 11, 18, 19], "abbccdde"),
        (GRADE_CUTOFFS_2023["beverage"], [2, 3, 6, 7, 9, 10], "bccdde"),
        (GRADE_CUTOFFS_2023["fat_oil_nuts_seeds"], [-6, -5, 2, 3, 18, 19], "abbcde"),
        (GRADE_CUTOFFS_2021["food"], [-1, 0, 2, 3, 18, 19], "abbcde"),
    ],
)
def test_grade_boundaries(cutoffs: list[int], scores: list[int], grades: str) -> None:
    assert "".join(grade_from_score(np.array(scores), cutoffs)) == grades
