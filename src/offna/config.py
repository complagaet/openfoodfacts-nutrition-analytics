from dataclasses import dataclass
from pathlib import Path

HF_DATASET = "https://huggingface.co/datasets/openfoodfacts/product-database"
PINNED_REVISION = "11cc007d7e6709c304405410e4fb23720c4a4aa2"
PINNED_SHA256 = "be58c2f3b3987e06c3cb0d87726c0da6c5242e7fb11e331f7e1dfcae8906707c"


def parquet_url(revision: str) -> str:
    return f"{HF_DATASET}/resolve/{revision}/food.parquet"


PARQUET_URL = parquet_url(PINNED_REVISION)
CSV_URL = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv"

SEED = 43


def find_project_root(package_file: Path, working_dir: Path) -> Path:
    source_checkout = package_file.resolve().parents[2]
    if (source_checkout / "pyproject.toml").exists():
        return source_checkout
    for candidate in [working_dir, *working_dir.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "sql").is_dir():
            return candidate
    raise FileNotFoundError("run offna from the project checkout (the folder with pyproject.toml and sql/)")


PROJECT_ROOT = find_project_root(Path(__file__), Path.cwd())
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "off_sample.parquet"

RAW_SCALAR_COLUMNS: list[str] = [
    "code",
    "brands",
    "lang",
    "nutriscore_grade",
    "nutriscore_score",
    "nova_group",
    "created_t",
    "last_modified_t",
    "additives_n",
    "ingredients_n",
    "with_sweeteners",
    "with_non_nutritive_sweeteners",
    "no_nutrition_data",
    "nutrition_data_per",
    "completeness",
    "obsolete",
    "schema_version",
]
RAW_LIST_COLUMNS: list[str] = [
    "countries_tags",
    "categories_tags",
    "food_groups_tags",
    "misc_tags",
    "allergens_tags",
    "additives_tags",
]
RAW_NESTED_COLUMNS: list[str] = ["nutriments", "product_name", "ingredients_text"]
RAW_COLUMNS: list[str] = RAW_SCALAR_COLUMNS + RAW_LIST_COLUMNS + RAW_NESTED_COLUMNS

NUTRIENTS: dict[str, str] = {
    "energy-kj": "energy_kj_declared_100g",
    "energy": "energy_100g",
    "energy-kcal": "energy_kcal_100g",
    "fat": "fat_100g",
    "saturated-fat": "saturated_fat_100g",
    "carbohydrates": "carbohydrates_100g",
    "sugars": "sugars_100g",
    "fiber": "fiber_100g",
    "proteins": "proteins_100g",
    "salt": "salt_100g",
    "sodium": "sodium_100g",
    "alcohol": "alcohol_100g",
    "fruits-vegetables-legumes-estimate-from-ingredients": "fvl_estimate_100g",
    "fruits-vegetables-nuts-estimate-from-ingredients": "fvn_estimate_100g",
    "fruits-vegetables-legumes": "fvl_declared_100g",
    "fruits-vegetables-nuts": "fvn_declared_100g",
}
CORE_NUTRIENTS: list[str] = [
    "energy_kcal_100g",
    "fat_100g",
    "saturated_fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
]
GRAMS_PER_100G_NUTRIENTS: list[str] = [
    "fat_100g",
    "saturated_fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "sodium_100g",
]
VALID_GRADES: list[str] = ["a", "b", "c", "d", "e"]
MAX_ENERGY_KJ_100G = 3900.0
MAX_ENERGY_KCAL_100G = 935.0
OFF_LAUNCH_YEAR = 2012


@dataclass(frozen=True)
class Profile:
    name: str
    raw_path: Path
    data_dir: Path
    output_dir: Path

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def bench_subset_path(self) -> Path:
        return self.data_dir / "bench_subset.parquet"

    @property
    def reports_dir(self) -> Path:
        return self.output_dir / "reports"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "off.sqlite"

    @property
    def aggregates_dir(self) -> Path:
        return self.output_dir / "aggregates"

    @property
    def figures_dir(self) -> Path:
        return self.output_dir / "figures"


PROFILES: dict[str, Profile] = {
    "demo": Profile(
        "demo",
        FIXTURE_PATH,
        PROJECT_ROOT / "data" / "demo",
        PROJECT_ROOT / "outputs" / "demo",
    ),
    "full": Profile(
        "full",
        PROJECT_ROOT / "data" / "raw" / "food.parquet",
        PROJECT_ROOT / "data" / "full",
        PROJECT_ROOT / "outputs" / "full",
    ),
}


def get_profile(name: str) -> Profile:
    if name not in PROFILES:
        raise KeyError(f"unknown profile {name!r}; expected one of {sorted(PROFILES)}")
    return PROFILES[name]
