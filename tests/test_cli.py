import re

import pytest

from offna.cli import PIPELINE_STAGES, STAGES, build_parser, main
from offna.config import PROJECT_ROOT

MAKE_PIPELINE = re.compile(r"^pipeline:(.*)$", re.MULTILINE)


def make_pipeline_targets() -> list[str]:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    return MAKE_PIPELINE.search(makefile).group(1).split()


def test_cli_pipeline_runs_the_same_stages_as_make_pipeline() -> None:
    assert make_pipeline_targets() == PIPELINE_STAGES


def test_every_pipeline_stage_is_a_cli_stage() -> None:
    assert set(PIPELINE_STAGES) <= set(STAGES) - {"pipeline"}


def test_cli_uses_demo_data_by_default() -> None:
    args = build_parser().parse_args(["pipeline"])
    assert args.profile == "demo"
    assert not args.full


@pytest.mark.parametrize("arguments", [["unknown-stage"], ["pipeline", "--profile", "unknown-profile"]])
def test_invalid_cli_choices_show_an_error(arguments: list[str], capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_missing_input_shows_message_without_traceback(monkeypatch, capsys) -> None:
    def missing_input(args):
        raise FileNotFoundError("sample.parquet not found")

    monkeypatch.setitem(STAGES, "etl", missing_input)
    assert main(["etl"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "error: sample.parquet not found\n"
