import polars as pl

BEVERAGE_ROOTS: list[str] = ["en:beverages", "en:beverage-preparations"]
NOT_BEVERAGES_2023: list[str] = ["en:meal-replacement", "en:soups"]
ALSO_BEVERAGES_2023: list[str] = [
    "en:milks",
    "en:plant-based-milk-alternatives",
    "en:dairy-drinks",
    "en:plant-based-beverages",
    "en:tea-based-beverages",
    "en:iced-teas",
    "en:herbal-tea-beverages",
    "en:coffee-beverages",
    "en:coffee-drinks",
    "en:coffees",
    "en:herbal-teas",
    "en:teas",
]
NOT_BEVERAGES_2021: list[str] = [
    "en:plant-milks",
    "en:milks",
    "en:meal-replacement",
    "en:plant-based-milk-alternatives",
    "en:chocolate-powders",
    "en:soups",
]
ALSO_BEVERAGES_2021: list[str] = [
    "en:tea-based-beverages",
    "en:iced-teas",
    "en:herbal-tea-beverages",
    "en:coffee-beverages",
    "en:coffee-drinks",
    "en:coffees",
    "en:herbal-teas",
    "en:teas",
]
EXEMPT_FROM_NUTRISCORE: list[str] = [
    "en:alcoholic-beverages",
    "en:baby-foods",
    "en:baby-milks",
    "en:chewing-gum",
    "en:food-additives",
    "en:dietary-supplements",
    "en:meal-replacements",
    "en:salts",
    "en:spices",
    "en:sugar-substitutes",
    "en:vinegars",
    "en:non-food-products",
]
NOT_EXEMPT_FROM_NUTRISCORE: list[str] = [
    "en:tea-based-beverages",
    "en:iced-teas",
    "en:herbal-tea-beverages",
    "en:coffee-beverages",
    "en:coffee-drinks",
]
FAT_OIL_NUTS_SEEDS: list[str] = ["en:fats", "en:creams", "en:seeds", "en:nuts", "en:peanuts"]
RED_MEAT: list[str] = [
    "en:beef",
    "en:veal",
    "en:pork",
    "en:lamb-meat",
    "en:mutton",
    "en:horse-meat",
    "en:game-meat",
    "en:offals",
]
WATERS: list[str] = ["en:spring-waters"]
FLAVOURED_WATERS: list[str] = ["en:flavored-waters", "en:flavoured-waters"]


def has_any(tags: list[str], column: str = "categories_tags") -> pl.Expr:
    return pl.col(column).list.eval(pl.element().is_in(tags)).list.any().fill_null(False)


def category_flag_expressions() -> list[pl.Expr]:
    beverage_root = has_any(BEVERAGE_ROOTS)
    return [
        ((beverage_root & ~has_any(NOT_BEVERAGES_2023)) | has_any(ALSO_BEVERAGES_2023)).alias("is_beverage_2023"),
        ((has_any(["en:beverages"]) & ~has_any(NOT_BEVERAGES_2021)) | has_any(ALSO_BEVERAGES_2021)).alias(
            "is_beverage_2021"
        ),
        (has_any(WATERS) & ~has_any(FLAVOURED_WATERS)).alias("is_water"),
        (has_any(["en:cheeses"]) & ~has_any(["fr:fromages-blancs"])).alias("is_cheese"),
        (has_any(FAT_OIL_NUTS_SEEDS) & ~has_any(["en:chestnuts"])).alias("is_fat_oil_nuts_seeds"),
        has_any(["en:fats"]).alias("is_fat_2021"),
        has_any(RED_MEAT).alias("is_red_meat"),
        (has_any(EXEMPT_FROM_NUTRISCORE) & ~has_any(NOT_EXEMPT_FROM_NUTRISCORE)).alias("is_nutriscore_exempt"),
    ]
