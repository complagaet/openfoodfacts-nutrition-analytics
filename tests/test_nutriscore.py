import numpy as np
import pandas as pd
import pytest

from offna.nutriscore import score_2021, score_2023, threshold_points

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
