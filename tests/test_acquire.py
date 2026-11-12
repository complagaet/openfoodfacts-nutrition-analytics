from types import SimpleNamespace

from offna.acquire import hub_metadata
from offna.config import PARQUET_URL, PINNED_REVISION, PINNED_SHA256, parquet_url


def response(headers: dict, history: list | None = None, url: str = "https://cdn.example/x?sig=1") -> SimpleNamespace:
    return SimpleNamespace(headers=headers, history=history or [], url=url)


def test_revision_is_read_from_redirect_not_cdn_response() -> None:
    redirect = response({"X-Repo-Commit": "abc123", "X-Linked-ETag": '"deadbeef"', "X-Linked-Size": "42"})
    final = response({"ETag": '"cdn-etag"'}, history=[redirect])
    metadata = hub_metadata(final)
    assert metadata["hf_revision"] == "abc123"
    assert metadata["hub_sha256"] == "deadbeef"
    assert metadata["hub_size_bytes"] == 42
    assert metadata["final_url"] == "https://cdn.example/x"


def test_headers_without_redirect_are_read_directly() -> None:
    metadata = hub_metadata(response({"X-Repo-Commit": "abc123"}))
    assert metadata["hf_revision"] == "abc123"
    assert metadata["hub_sha256"] is None


def test_default_url_is_pinned_to_the_full_run_revision() -> None:
    assert PINNED_REVISION in PARQUET_URL
    assert parquet_url("main").endswith("/resolve/main/food.parquet")
    assert len(PINNED_SHA256) == 64


def test_installed_package_resolves_root_from_working_directory(tmp_path) -> None:
    from offna.config import find_project_root

    checkout = tmp_path / "checkout"
    (checkout / "sql").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\n")
    installed = tmp_path / "venv" / "lib" / "python3.12" / "site-packages" / "offna" / "config.py"
    assert find_project_root(installed, checkout / "docs") == checkout


def test_missing_hub_etag_falls_back_to_pinned_sha_for_default_revision() -> None:
    import pytest

    from offna.acquire import verify_sha256

    verify_sha256({"sha256": PINNED_SHA256, "url": PARQUET_URL, "hub_sha256": None})
    with pytest.raises(ValueError, match="does not match"):
        verify_sha256({"sha256": "0" * 64, "url": PARQUET_URL, "hub_sha256": None})


def test_unverifiable_custom_url_raises_unless_skipped() -> None:
    import pytest

    from offna.acquire import verify_sha256

    snapshot = {"sha256": "1" * 64, "url": "https://mirror.example/food.parquet", "hub_sha256": None}
    with pytest.raises(ValueError, match="cannot verify"):
        verify_sha256(snapshot)
    verify_sha256(snapshot, skip=True)


def test_root_falls_back_to_working_directory_outside_a_checkout(tmp_path) -> None:
    from offna.config import resolve_project_root

    installed = tmp_path / "venv" / "lib" / "python3.12" / "site-packages" / "offna" / "config.py"
    assert resolve_project_root(installed, tmp_path) == tmp_path


def test_benchmark_worker_runs_the_same_source_tree_as_the_parent() -> None:
    from pathlib import Path

    import offna
    from offna.benchmark import worker_command

    command = worker_command("polars_lazy", Path("a"), Path("b"))
    assert str(Path(offna.__file__).resolve().parents[1]) in command[3]
    assert "-m" not in command
