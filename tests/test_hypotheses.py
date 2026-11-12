import numpy as np
import pandas as pd

from offna.hypotheses import bootstrap_median_difference, chi2_ready_table


def grade_table(rows: dict[int, list[int]]) -> pd.DataFrame:
    return pd.DataFrame.from_dict(rows, orient="index", columns=list("abcde"))


def test_large_expected_counts_keep_five_grades() -> None:
    method, table = chi2_ready_table(grade_table({0: [50, 60, 70, 80, 90], 1: [40, 30, 35, 45, 50]}))
    assert method == "chi2_5_grades"
    assert table.shape == (2, 5)


def test_sparse_grades_are_merged_into_three_bands() -> None:
    method, table = chi2_ready_table(grade_table({0: [400, 300, 500, 600, 700], 1: [1, 2, 10, 12, 15]}))
    assert method == "chi2_merged_ab_c_de"
    assert list(table.columns) == ["ab", "c", "de"]


def test_too_sparse_table_is_skipped() -> None:
    method, table = chi2_ready_table(grade_table({0: [400, 300, 500, 600, 700], 1: [0, 1, 1, 0, 2]}))
    assert method == "skipped_expected_below_5"
    assert table is None


def test_bootstrap_uses_every_observation() -> None:
    rng = np.random.default_rng(0)
    treated = np.concatenate([np.zeros(6000), np.full(6000, 10.0)])
    low, high = bootstrap_median_difference(treated, np.zeros(7000), rng)
    assert low <= 5.0 <= high


def test_single_grade_stratum_is_skipped() -> None:
    method, table = chi2_ready_table(grade_table({0: [0, 0, 50, 0, 0], 1: [0, 0, 40, 0, 0]}))
    assert method == "skipped_single_grade"
    assert table is None
