from pathlib import Path

import pandas as pd

from offna.csv_reader import ParseStats, iter_csv_chunks, iter_validated_records


def test_valid_records_pass_and_embedded_newline_is_stitched(tsv_file: Path) -> None:
    stats = ParseStats()
    frame = pd.concat(iter_csv_chunks(tsv_file, chunk_rows=2, stats=stats))
    assert frame["code"].tolist() == ["001", "002", "003"]
    assert frame.loc[frame["code"] == "002", "product_name"].item() == "Choc\nolate bar"
    assert stats.stitched_records == 1


def test_fragments_and_column_shifted_rows_are_rejected(tsv_file: Path) -> None:
    stats = ParseStats()
    list(iter_csv_chunks(tsv_file, chunk_rows=10, stats=stats))
    assert stats.empty_lines == 1
    assert stats.rejected_fragments >= 2
    assert stats.implausible_records == 1


def test_every_accepted_record_has_header_width() -> None:
    lines = ["a\tb\tc", "x\ty", "\tz\tw", "1\t2\t3\t4", "5\t6\t7"]
    records = list(iter_validated_records(lines, 3, ParseStats()))
    assert all(len(record) == 3 for record in records)
    assert ["5", "6", "7"] in records
