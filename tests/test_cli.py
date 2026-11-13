import re

from offna.cli import PIPELINE_STAGES, STAGES
from offna.config import PROJECT_ROOT

MAKE_PIPELINE = re.compile(r"^pipeline:(.*)$", re.MULTILINE)


def make_pipeline_targets() -> list[str]:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    return MAKE_PIPELINE.search(makefile).group(1).split()


def test_cli_pipeline_runs_the_same_stages_as_make_pipeline() -> None:
    assert PIPELINE_STAGES == make_pipeline_targets()


def test_every_pipeline_stage_is_a_cli_stage() -> None:
    assert set(PIPELINE_STAGES) <= set(STAGES) - {"pipeline"}
