import pickle
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import polars as pl
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from offna.config import SEED, VALID_GRADES, Profile
from offna.etl import scan_processed
from offna.measure import peak_rss_mib, write_json
from offna.nutriscore import score_2021, score_2023

NUMERIC_FEATURES: list[str] = [
    "energy_kj_100g",
    "energy_kcal_100g",
    "fat_100g",
    "saturated_fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "fvl_estimate_100g",
    "fvl_declared_100g",
    "with_non_nutritive_sweeteners",
    "additives_n",
]
FLAG_FEATURES: list[str] = [
    "is_beverage_2023",
    "is_water",
    "is_cheese",
    "is_fat_oil_nuts_seeds",
    "is_red_meat",
]
CATEGORICAL_FEATURES: list[str] = ["food_group"]
FEATURES: list[str] = NUMERIC_FEATURES + FLAG_FEATURES + CATEGORICAL_FEATURES
FORBIDDEN_FEATURE_PATTERNS: list[str] = ["nutriscore", "grade", "score", "misc", "rule_", "nutrition-score"]
EXTRA_COLUMNS: list[str] = [
    "code",
    "brand",
    "product_name",
    "nutriscore_grade",
    "nutriscore_score",
    "off_grade_2021",
    "off_grade_2023",
    "is_beverage_2021",
    "is_fat_2021",
    "is_nutriscore_exempt",
    "fvn_estimate_100g",
    "fvn_declared_100g",
    "sodium_100g",
]
TEST_SHARE = 0.2
HGB_ITERATIONS = 300


@dataclass
class Split:
    train: pd.DataFrame
    test: pd.DataFrame


def check_allowlist(features: list[str]) -> None:
    leaks = [name for name in features for pattern in FORBIDDEN_FEATURE_PATTERNS if pattern in name]
    if leaks:
        raise ValueError(f"leaking features in allowlist: {leaks}")


def load_labelled(profile: Profile) -> pd.DataFrame:
    columns = list(dict.fromkeys([*FEATURES, *EXTRA_COLUMNS]))
    frame = (
        scan_processed(profile)
        .filter(pl.col("nutriscore_grade").is_in(VALID_GRADES))
        .select(columns)
        .with_columns(pl.col("food_group").cast(pl.String))
        .collect(engine="streaming")
        .to_pandas()
    )
    for flag in [*FLAG_FEATURES, "is_beverage_2021", "is_fat_2021", "is_nutriscore_exempt"]:
        frame[flag] = frame[flag].astype(bool)
    return frame


def product_groups(frame: pd.DataFrame) -> np.ndarray:
    codes = frame["code"].str.lstrip("0").fillna("")
    names = frame["brand"].str.lower().str.strip() + "|" + frame["product_name"].str.lower().str.strip()
    rows = len(frame)
    code_ids, code_values = pd.factorize(codes)
    name_ids, name_values = pd.factorize(names)
    has_name = name_ids >= 0
    row_index = np.arange(rows)
    sources = np.concatenate([row_index, row_index[has_name]])
    targets = np.concatenate([rows + code_ids, rows + len(code_values) + name_ids[has_name]])
    size = rows + len(code_values) + len(name_values)
    graph = coo_matrix((np.ones(len(sources), dtype=np.int8), (sources, targets)), shape=(size, size))
    return connected_components(graph, directed=False)[1][:rows]


def group_split(frame: pd.DataFrame) -> Split:
    groups = product_groups(frame)
    splitter = GroupShuffleSplit(n_splits=1, test_size=TEST_SHARE, random_state=SEED)
    train_index, test_index = next(splitter.split(frame, groups=groups))
    frame = frame.assign(group_id=groups)
    return Split(frame.iloc[train_index].copy(), frame.iloc[test_index].copy())


def logistic_pipeline() -> Pipeline:
    numeric = Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)), ("scale", StandardScaler())])
    columns = ColumnTransformer(
        [
            ("numeric", numeric, NUMERIC_FEATURES),
            ("flags", "passthrough", FLAG_FEATURES),
            ("group", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )
    return Pipeline([("features", columns), ("model", LogisticRegression(max_iter=1000, C=1.0))])


def boosting_pipeline() -> Pipeline:
    columns = ColumnTransformer(
        [
            ("numeric", "passthrough", NUMERIC_FEATURES + FLAG_FEATURES),
            (
                "group",
                OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1, encoded_missing_value=-1),
                CATEGORICAL_FEATURES,
            ),
        ],
        verbose_feature_names_out=False,
    )
    model = HistGradientBoostingClassifier(
        max_iter=HGB_ITERATIONS,
        learning_rate=0.1,
        categorical_features=[len(NUMERIC_FEATURES) + len(FLAG_FEATURES)],
        early_stopping=False,
        random_state=SEED,
    )
    return Pipeline([("features", columns), ("model", model)])


def candidate_models() -> dict[str, object]:
    return {
        "dummy_most_frequent": DummyClassifier(strategy="most_frequent"),
        "dummy_stratified": DummyClassifier(strategy="stratified", random_state=SEED),
        "logistic_regression": logistic_pipeline(),
        "hist_gradient_boosting": boosting_pipeline(),
    }


def classification_metrics(truth: pd.Series, predicted: np.ndarray) -> dict:
    per_class = f1_score(truth, predicted, labels=VALID_GRADES, average=None, zero_division=0)
    return {
        "n": len(truth),
        "macro_f1": round(float(f1_score(truth, predicted, labels=VALID_GRADES, average="macro", zero_division=0)), 4),
        "accuracy": round(float(accuracy_score(truth, predicted)), 4),
        "f1_per_class": {grade: round(float(value), 4) for grade, value in zip(VALID_GRADES, per_class, strict=True)},
    }


def confusion_frame(truth: pd.Series, predicted: np.ndarray) -> pd.DataFrame:
    matrix = confusion_matrix(truth, predicted, labels=VALID_GRADES)
    return pd.DataFrame(matrix, index=[f"true_{g}" for g in VALID_GRADES], columns=[f"pred_{g}" for g in VALID_GRADES])


def sample_train(train: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    if len(train) <= max_rows:
        return train
    return train.sample(n=max_rows, random_state=SEED)


def fit_and_score(name: str, model: object, train: pd.DataFrame, test: pd.DataFrame, covered: np.ndarray) -> dict:
    started = time.perf_counter()
    model.fit(train[FEATURES], train["nutriscore_grade"])
    fit_seconds = time.perf_counter() - started
    started = time.perf_counter()
    predicted = model.predict(test[FEATURES])
    predict_seconds = time.perf_counter() - started
    return {
        "model": name,
        "fit_seconds": round(fit_seconds, 2),
        "predict_seconds": round(predict_seconds, 3),
        "model_bytes": len(pickle.dumps(model)),
        "all_labelled_test": classification_metrics(test["nutriscore_grade"], predicted),
        "rule_covered_test": classification_metrics(test["nutriscore_grade"][covered], predicted[covered]),
        "predictions": predicted,
    }


def rule_results(test: pd.DataFrame) -> tuple[dict, dict[str, pd.DataFrame]]:
    rules = {"rule_2023": score_2023(test), "rule_2021": score_2021(test)}
    summary = {}
    for name, result in rules.items():
        covered = result["rule_covered"].to_numpy()
        predicted = result["rule_grade"].to_numpy(dtype=object)
        score_match = (result["rule_score"].astype("Float64") == test["nutriscore_score"].astype("Float64"))[covered]
        summary[name] = {
            "coverage": round(float(covered.mean()), 4),
            "rule_covered_test": classification_metrics(test["nutriscore_grade"][covered], predicted[covered]),
            "exact_score_match": round(float(score_match.fillna(False).mean()), 4),
        }
    return summary, rules


def version_evidence(labelled: pd.DataFrame) -> dict:
    tagged = labelled.dropna(subset=["off_grade_2021", "off_grade_2023"])
    differing = tagged[tagged["off_grade_2021"] != tagged["off_grade_2023"]]
    return {
        "labelled_rows": len(labelled),
        "rows_with_version_comparison_tag": len(tagged),
        "label_equals_2023_tag": round(float((tagged["nutriscore_grade"] == tagged["off_grade_2023"]).mean()), 4),
        "rows_where_2021_and_2023_differ": len(differing),
        "of_those_label_equals_2023": round(
            float((differing["nutriscore_grade"] == differing["off_grade_2023"]).mean()), 4
        ),
        "of_those_label_equals_2021": round(
            float((differing["nutriscore_grade"] == differing["off_grade_2021"]).mean()), 4
        ),
    }


def product_type(frame: pd.DataFrame) -> pd.Series:
    kinds = np.select(
        [
            frame["is_water"],
            frame["is_beverage_2023"],
            frame["is_cheese"],
            frame["is_fat_oil_nuts_seeds"],
            frame["is_red_meat"],
        ],
        ["water", "beverage", "cheese", "fat_oil_nuts_seeds", "red_meat"],
        default="general_food",
    )
    return pd.Series(kinds, index=frame.index)


def rule_error_breakdown(test: pd.DataFrame, rule: pd.DataFrame) -> pd.DataFrame:
    covered = rule["rule_covered"]
    frame = pd.DataFrame(
        {
            "product_type": product_type(test),
            "fiber_missing": test["fiber_100g"].isna(),
            "fvl_missing": test["fvl_estimate_100g"].isna() & test["fvl_declared_100g"].isna(),
            "agree": rule["rule_grade"] == test["nutriscore_grade"],
        }
    )[covered]
    return (
        frame.groupby(["product_type", "fiber_missing", "fvl_missing"], observed=True)["agree"]
        .agg(products="size", agreement="mean")
        .reset_index()
        .sort_values("products", ascending=False)
    )


def class_balance(split: Split) -> dict:
    return {
        part: frame["nutriscore_grade"].value_counts(normalize=True).sort_index().round(4).to_dict()
        for part, frame in {"train": split.train, "test": split.test}.items()
    }


def save_split(profile: Profile, split: Split) -> None:
    ids = pd.concat(
        [
            split.train[["code", "group_id"]].assign(split="train"),
            split.test[["code", "group_id"]].assign(split="test"),
        ]
    )
    profile.data_dir.mkdir(parents=True, exist_ok=True)
    ids.to_parquet(profile.data_dir / "model_split.parquet", index=False)


def run_model_stage(profile: Profile, max_train_rows: int) -> dict:
    check_allowlist(FEATURES)
    labelled = load_labelled(profile)
    split = group_split(labelled)
    save_split(profile, split)
    rules_summary, rules = rule_results(split.test)
    covered = rules["rule_2023"]["rule_covered"].to_numpy()
    train = sample_train(split.train, max_train_rows)
    model_dir = profile.output_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    models = []
    for name, model in candidate_models().items():
        result = fit_and_score(name, model, train, split.test, covered)
        confusion_frame(split.test["nutriscore_grade"], result.pop("predictions")).to_csv(
            model_dir / f"confusion_{name}.csv"
        )
        models.append(result)
    rule_grade = rules["rule_2023"]["rule_grade"].to_numpy(dtype=object)
    confusion_frame(split.test["nutriscore_grade"][covered], rule_grade[covered]).to_csv(
        model_dir / "confusion_rule_2023.csv"
    )
    rule_error_breakdown(split.test, rules["rule_2023"]).to_csv(
        model_dir / "rule_2023_agreement_by_type.csv", index=False
    )
    report = {
        "profile": profile.name,
        "seed": SEED,
        "features": FEATURES,
        "labelled_rows": len(labelled),
        "groups": int(labelled.pipe(product_groups).max() + 1),
        "train_rows": len(split.train),
        "train_rows_used": len(train),
        "test_rows": len(split.test),
        "class_balance": class_balance(split),
        "version_evidence": version_evidence(labelled),
        "rules": rules_summary,
        "models": models,
        "peak_rss_mib": round(peak_rss_mib(), 1),
    }
    write_json(profile.reports_dir / "model_report.json", report)
    return report
