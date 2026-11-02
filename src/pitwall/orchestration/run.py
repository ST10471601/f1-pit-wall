from collections.abc import Callable
from datetime import datetime, timedelta

from pitwall.config import Settings
from pitwall.ingestion.openf1 import OpenF1Client
from pitwall.ingestion.race import IngestionRun, ingest_race
from pitwall.ops import connect_ops
from pitwall.validation.silver import DATASETS, build_silver


def run_session(
    settings: Settings,
    run_id: str,
    session_key: int,
    *,
    as_of: datetime,
    now: Callable[[], datetime],
) -> None:
    """Ingest one race session into bronze, then validate it into silver."""
    with (
        OpenF1Client(settings.api) as client,
        connect_ops(settings.ops_db, settings.duckdb) as ops,
    ):
        ingest_race(
            IngestionRun(
                run_id=run_id,
                client=client,
                ops=ops,
                bronze_dir=settings.bronze_dir,
                now=now,
            ),
            session_key,
            as_of=as_of,
            settle_delay=timedelta(hours=settings.run.settle_delay_hours),
        )
    for dataset in DATASETS:
        build_silver(
            dataset,
            session_key,
            run_id,
            bronze_dir=settings.bronze_dir,
            silver_dir=settings.silver_dir,
        )
