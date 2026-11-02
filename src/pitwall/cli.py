import argparse
import logging
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError

from pitwall.config import (
    CONFIG_FILE_ENV_VAR,
    DEFAULT_CONFIG_FILE,
    ConfigError,
    Settings,
    load_settings,
)
from pitwall.ingestion.openf1 import OpenF1Error
from pitwall.ingestion.race import SessionNotEligibleError
from pitwall.log import configure_logging, run_context
from pitwall.orchestration.run import run_session
from pitwall.run_id import new_run_id

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def _utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO 8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"timestamp needs a UTC offset, e.g. 2026-11-02T08:00:00Z: {value!r}"
        )
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pitwall",
        description="Batch pipeline for F1 race data: OpenF1 -> bronze -> silver -> DuckDB.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('pitwall')}")
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help=f"YAML config file (default: ${CONFIG_FILE_ENV_VAR} or {DEFAULT_CONFIG_FILE})",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    run = commands.add_parser("run", help="ingest, transform and publish due race sessions")
    run.add_argument(
        "--session",
        type=int,
        metavar="KEY",
        help="process only this OpenF1 session_key",
    )
    run.add_argument(
        "--as-of",
        type=_utc_timestamp,
        metavar="TIMESTAMP",
        help="logical run time in ISO 8601 with offset (default: now); "
        "fix it to make reruns and backfills reproducible",
    )

    commands.add_parser("release", help="upload the current serving snapshot to a GitHub Release")
    return parser


def _utc_now() -> datetime:
    """The wall clock. Read only here; everything downstream gets times or this function."""
    return datetime.now(UTC)


def _run(settings: Settings, run_id: str, session_key: int | None, as_of: datetime) -> int:
    log.info("run started", extra={"session_key": session_key, "as_of": as_of.isoformat()})
    if session_key is None:
        log.error("run selection is not implemented yet; pass --session KEY")
        return EXIT_FAILED

    try:
        run_session(settings, run_id, session_key, as_of=as_of, now=_utc_now)
    except (OpenF1Error, SessionNotEligibleError) as exc:
        log.error("run failed", extra={"error": str(exc)})
        return EXIT_FAILED

    log.info("run finished")
    return EXIT_OK


def _release() -> int:
    log.error("release is not implemented yet")
    return EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.config)
    except (ConfigError, ValidationError) as exc:
        parser.exit(EXIT_USAGE, f"pitwall: invalid configuration\n{exc}\n")

    configure_logging(settings.log_level)
    started_at = _utc_now()
    run_id = new_run_id(started_at)

    with run_context(run_id):
        if args.command == "run":
            return _run(settings, run_id, args.session, args.as_of or started_at)
        return _release()
