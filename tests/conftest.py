from pathlib import Path

import pytest

from offna.config import FIXTURE_PATH, Profile
from offna.etl import run_etl


@pytest.fixture(scope="session")
def demo_profile(tmp_path_factory: pytest.TempPathFactory) -> Profile:
    root = tmp_path_factory.mktemp("offna")
    profile = Profile("demo", FIXTURE_PATH, root / "data", root / "outputs")
    run_etl(profile, batch_rows=2500)
    return profile


@pytest.fixture
def tsv_file(tmp_path: Path) -> Path:
    lines = [
        "code\tproduct_name\tnutriscore_grade\tsugars_100g",
        "001\tPlain yoghurt\ta\t4.1",
        "",
        "002\tChoc",
        "olate bar\te\t51",
        "\tsorted fragment",
        "003\tApple juice\tc\t10.2",
        "004\tBroken row\thttps://images.example/1.jpg\t3",
        "005\tTrailing\tb",
    ]
    path = tmp_path / "products.tsv"
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path
