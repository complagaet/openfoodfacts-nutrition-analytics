import hashlib
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import requests

from offna.config import CSV_URL, PARQUET_URL, PINNED_SHA256, RAW_COLUMNS, SEED
from offna.measure import utc_now_iso, write_json

DOWNLOAD_CHUNK_BYTES = 8 * 2**20
REQUEST_TIMEOUT_SECONDS = 60
FIXTURE_ODBL_NOTICE = (
    "Contains information from Open Food Facts (https://world.openfoodfacts.org), "
    "made available under the Open Database License (ODbL) v1.0: "
    "https://opendatacommons.org/licenses/odbl/1-0/. Individual contents: Database Contents License."
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def parquet_shape(path: Path) -> dict[str, int]:
    parquet = pq.ParquetFile(path)
    return {
        "rows": parquet.metadata.num_rows,
        "top_level_columns": len(parquet.schema_arrow),
        "parquet_leaf_columns": parquet.metadata.num_columns,
        "row_groups": parquet.metadata.num_row_groups,
    }


def _quoted(value: str | None) -> str | None:
    return value.strip('"') if value else None


def hub_metadata(response: requests.Response) -> dict:
    hub = response.history[0] if response.history else response
    size = hub.headers.get("X-Linked-Size")
    return {
        "final_url": response.url.split("?")[0],
        "hf_revision": hub.headers.get("X-Repo-Commit"),
        "hub_sha256": _quoted(hub.headers.get("X-Linked-ETag")),
        "hub_size_bytes": int(size) if size else None,
    }


def remote_headers(url: str) -> dict:
    response = requests.head(url, allow_redirects=False, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return hub_metadata(response)


def expected_sha256(snapshot: dict) -> str | None:
    if snapshot.get("hub_sha256"):
        return snapshot["hub_sha256"]
    if snapshot.get("url") == PARQUET_URL:
        return PINNED_SHA256
    return None


def verify_sha256(snapshot: dict, skip: bool = False) -> None:
    if skip:
        return
    expected = expected_sha256(snapshot)
    if expected is None:
        raise ValueError(
            f"cannot verify {snapshot.get('url')}: no hub ETag and not the pinned revision; use --skip-verify"
        )
    if expected != snapshot["sha256"]:
        raise ValueError(f"sha256 {snapshot['sha256']} does not match the expected {expected}")


def describe_snapshot(path: Path, url: str, extra: dict | None = None) -> dict:
    shape = parquet_shape(path) if path.suffix == ".parquet" else {}
    snapshot = {
        "url": url,
        "local_path": path.name,
        "described_at_utc": utc_now_iso(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        **shape,
        "license": FIXTURE_ODBL_NOTICE,
    }
    snapshot.update(extra or {})
    return snapshot


def download(url: str, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        headers = hub_metadata(response)
        with partial.open("wb") as handle:
            for block in response.iter_content(DOWNLOAD_CHUNK_BYTES):
                handle.write(block)
    partial.replace(destination)
    return headers


def acquire_parquet(destination: Path, url: str = PARQUET_URL, skip_verify: bool = False) -> dict:
    headers = download(url, destination)
    snapshot = describe_snapshot(destination, url, headers)
    verify_sha256(snapshot, skip_verify)
    write_json(destination.parent.parent / "SNAPSHOT.json", snapshot)
    return snapshot


def acquire_sample(destination: Path, rows: int, url: str = PARQUET_URL) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pl.scan_parquet(url).select(RAW_COLUMNS).head(rows).collect().write_parquet(destination)
    snapshot = describe_snapshot(destination, url, {"mode": f"first {rows} rows, column subset"})
    write_json(destination.with_suffix(".snapshot.json"), snapshot)
    return snapshot


def acquire_csv_head(destination: Path, size_bytes: int, url: str = CSV_URL) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {"Range": f"bytes=0-{size_bytes - 1}"}
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.content
    destination.write_bytes(body[: body.rfind(b"\n") + 1])
    snapshot = describe_snapshot(destination, url, {"mode": f"byte range head {size_bytes}"})
    write_json(destination.with_suffix(".snapshot.json"), snapshot)
    return snapshot


def build_fixture(source: Path, destination: Path, rows: int) -> dict:
    total = pq.ParquetFile(source).metadata.num_rows
    modulus = max(total // rows, 1)
    sampled = (
        pl.scan_parquet(source)
        .select(RAW_COLUMNS)
        .filter((pl.col("code").hash(seed=SEED) % modulus) == 0)
        .head(rows)
        .collect(engine="streaming")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    sampled.write_parquet(destination, compression="zstd", compression_level=19)
    snapshot = describe_snapshot(
        destination,
        PARQUET_URL,
        {"mode": f"hash sample 1/{modulus} of {total} rows, seed {SEED}, {len(RAW_COLUMNS)} raw columns"},
    )
    write_json(destination.with_suffix(".snapshot.json"), snapshot)
    return snapshot
