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
