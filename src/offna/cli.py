import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from offna.config import CSV_URL, FIXTURE_PATH, PINNED_REVISION, PROFILES, Profile, get_profile, parquet_url

PIPELINE_STAGES: list[str] = ["etl", "audit", "aggregates", "sql", "model", "eda"]


def _print(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def stage_acquire(args: argparse.Namespace) -> dict:
    from offna import acquire

    profile = get_profile("full")
    if args.source == "parquet":
        return acquire.acquire_parquet(profile.raw_path, args.url or parquet_url(args.revision))
    if args.source == "sample":
        return acquire.acquire_sample(
            profile.raw_path.with_name(f"sample_{args.rows}.parquet"), args.rows, parquet_url(args.revision)
        )
    if args.source == "csv-head":
        return acquire.acquire_csv_head(profile.raw_path.with_name("csv_head.tsv"), args.bytes, args.url or CSV_URL)
    if args.source == "snapshot":
        url = args.url or parquet_url(args.revision)
        snapshot = acquire.describe_snapshot(profile.raw_path, url, acquire.remote_headers(url))
        acquire.verify_sha256(snapshot)
        acquire.write_json(profile.raw_path.parent.parent / "SNAPSHOT.json", snapshot)
        return snapshot
    return acquire.build_fixture(profile.raw_path, FIXTURE_PATH, args.rows)


def stage_etl(args: argparse.Namespace) -> dict:
    from offna.etl import run_etl

    return run_etl(_profile(args), args.batch_rows)


def stage_audit(args: argparse.Namespace) -> dict:
    from offna.audit import run_audit

    return run_audit(_profile(args))


def stage_csv_audit(args: argparse.Namespace) -> dict:
    from offna.csv_audit import run_csv_audit

    return run_csv_audit(Path(args.input), _profile(args))


def stage_aggregates(args: argparse.Namespace) -> dict:
    from offna.aggregates import build_aggregates

    return build_aggregates(_profile(args))


def stage_benchmark(args: argparse.Namespace) -> dict:
    from offna.benchmark import run_benchmark

    return run_benchmark(_profile(args), args.subset_rows, args.repeats, args.full)


def stage_sql(args: argparse.Namespace) -> dict:
    from offna.database import run_sql_stage

    return run_sql_stage(_profile(args))


def stage_model(args: argparse.Namespace) -> dict:
    from offna.model import run_model_stage

    return run_model_stage(_profile(args), args.max_train_rows)


def stage_eda(args: argparse.Namespace) -> dict:
    from offna.eda import run_eda

    return run_eda(_profile(args))


def stage_slides(args: argparse.Namespace) -> dict:
    from offna.slides import build_slides

    return build_slides()


def stage_pipeline(args: argparse.Namespace) -> dict:
    summary = {}
    for name in PIPELINE_STAGES:
        result = STAGES[name](args)
        summary[name] = {key: result[key] for key in list(result)[:6]}
    return summary


def stage_menu(args: argparse.Namespace) -> dict:
    from offna.menu import run_menu

    run_menu(_profile(args))
    return {"menu": "closed"}


STAGES: dict[str, Callable[[argparse.Namespace], dict]] = {
    "acquire": stage_acquire,
    "etl": stage_etl,
    "audit": stage_audit,
    "csv-audit": stage_csv_audit,
    "aggregates": stage_aggregates,
    "benchmark": stage_benchmark,
    "sql": stage_sql,
    "model": stage_model,
    "eda": stage_eda,
    "pipeline": stage_pipeline,
    "menu": stage_menu,
    "slides": stage_slides,
}


def _profile(args: argparse.Namespace) -> Profile:
    return get_profile(args.profile)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="offna", description="Open Food Facts nutrition analytics pipeline")
    parser.add_argument("stage", choices=sorted(STAGES))
    parser.add_argument("--profile", choices=sorted(PROFILES), default="demo")
    parser.add_argument("--source", choices=["parquet", "sample", "csv-head", "snapshot", "fixture"], default="parquet")
    parser.add_argument("--url")
    parser.add_argument("--revision", default=PINNED_REVISION)
    parser.add_argument("--rows", type=int, default=5000)
    parser.add_argument("--bytes", type=int, default=20_000_000)
    parser.add_argument("--input", default="data/raw/csv_head.tsv")
    parser.add_argument("--batch-rows", type=int, default=250_000)
    parser.add_argument("--subset-rows", type=int, default=1_000_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--max-train-rows", type=int, default=400_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = STAGES[args.stage](args)
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
