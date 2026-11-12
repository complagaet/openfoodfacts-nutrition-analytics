import sqlite3
from collections.abc import Callable

import pandas as pd

from offna.config import Profile
from offna.dashboard import AggregatesMissingError, load_aggregates
from offna.database import query_files
from offna.measure import read_json
from offna.nutriscore import score_2023

Reader = Callable[[str], str]
Writer = Callable[[str], None]

MENU_TEXT = """
1  Pipeline reports summary
2  Top sales countries by product count
3  Nutri-Score distribution for one country
4  Run a saved SQL query
5  Compute Nutri-Score 2023 for your own product
0  Exit"""
MANUAL_INPUTS: dict[str, str] = {
    "energy_kj_100g": "Energy, kJ per 100 g",
    "sugars_100g": "Sugars, g per 100 g",
    "saturated_fat_100g": "Saturated fat, g per 100 g",
    "fat_100g": "Fat, g per 100 g",
    "salt_100g": "Salt, g per 100 g",
    "fiber_100g": "Fibre, g per 100 g",
    "proteins_100g": "Proteins, g per 100 g",
    "fvl_declared_100g": "Fruit/vegetables/legumes, %",
}


def ask_number(read: Reader, write: Writer, prompt: str, maximum: float) -> float:
    while True:
        raw = read(f"{prompt}: ").strip().replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            write(f"'{raw}' is not a number, try again")
            continue
        if 0 <= value <= maximum:
            return value
        write(f"value must be between 0 and {maximum}")


def show_reports(profile: Profile, write: Writer) -> None:
    for name in ["etl_report", "audit_summary", "model_report"]:
        try:
            report = read_json(profile.reports_dir / f"{name}.json")
        except FileNotFoundError as error:
            write(str(error))
            continue
        keys = [key for key in report if isinstance(report[key], int | float | str)]
        write(f"{name}: " + ", ".join(f"{key}={report[key]}" for key in keys))


def top_countries(profile: Profile, write: Writer) -> None:
    table = load_aggregates(profile)["country_food_group"]
    ranking = table.groupby("country")["products"].sum().nlargest(10)
    for country, products in ranking.items():
        write(f"{country:<30} {products:>10,}")


def country_grades(profile: Profile, read: Reader, write: Writer) -> None:
    grades = load_aggregates(profile)["grade_counts"]
    country = read("Country (e.g. france): ").strip().lower()
    selected = grades[grades["country"] == country]
    if selected.empty:
        write(f"no graded products for '{country}'")
        return
    shares = selected.groupby("nutriscore_grade")["products"].sum()
    for grade, share in (shares / shares.sum()).items():
        write(f"{grade.upper()}: {share:6.1%}")


def run_query(profile: Profile, read: Reader, write: Writer) -> None:
    files = query_files()
    for index, path in enumerate(files, start=1):
        write(f"{index:>2}  {path.stem}")
    choice = int(ask_number(read, write, "Query number", len(files)))
    if choice == 0:
        return
    with sqlite3.connect(profile.sqlite_path) as connection:
        frame = pd.read_sql_query(files[choice - 1].read_text(encoding="utf-8"), connection)
    write(frame.head(15).to_string(index=False))


def manual_score(read: Reader, write: Writer) -> None:
    values = {
        column: ask_number(read, write, label, 4000 if column.startswith("energy") else 100)
        for column, label in MANUAL_INPUTS.items()
    }
    product = pd.DataFrame([values]).assign(carbohydrates_100g=float("nan"))
    result = score_2023(product).iloc[0]
    write(f"Nutri-Score 2023 (general food rule): score {result['rule_score']}, grade {result['rule_grade'].upper()}")


def handle(choice: str, profile: Profile, read: Reader, write: Writer) -> bool:
    if choice == "0":
        return False
    if choice == "1":
        show_reports(profile, write)
    elif choice == "2":
        top_countries(profile, write)
    elif choice == "3":
        country_grades(profile, read, write)
    elif choice == "4":
        run_query(profile, read, write)
    elif choice == "5":
        manual_score(read, write)
    else:
        write(f"unknown option '{choice}'")
    return True


def run_menu(profile: Profile, read: Reader = input, write: Writer = print) -> None:
    running = True
    while running:
        write(MENU_TEXT)
        choice = read("Choose: ").strip()
        try:
            running = handle(choice, profile, read, write)
        except (AggregatesMissingError, FileNotFoundError, sqlite3.OperationalError) as error:
            write(f"cannot do that yet: {error}")
