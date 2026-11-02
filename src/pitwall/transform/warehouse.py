import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pitwall.config import Settings

log = logging.getLogger(__name__)


class WarehouseBuildError(Exception):
    """dbt could not build a model, or a test with severity error failed."""


def build_warehouse(settings: Settings, run_id: str, session_key: int) -> None:
    """Rebuild one session's gold models and run their tests with dbt."""
    # The dbt installed with this interpreter, not whichever one is first on PATH.
    dbt = shutil.which("dbt", path=str(Path(sys.executable).parent))
    if dbt is None:
        raise WarehouseBuildError(f"dbt is not installed next to {sys.executable}")

    project = settings.dbt_project_dir.resolve()
    work_dir = (settings.data_dir / "dbt").resolve()
    settings.warehouse_db.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ | {
        "DBT_PITWALL_WAREHOUSE_PATH": settings.warehouse_db.resolve().as_posix(),
        "DBT_PITWALL_SILVER_DIR": settings.silver_dir.resolve().as_posix(),
        "DBT_PITWALL_DUCKDB_THREADS": str(settings.duckdb.threads),
        "DBT_PITWALL_DUCKDB_MEMORY_LIMIT": settings.duckdb.memory_limit,
        "DBT_PITWALL_TEMP_DIR": settings.duckdb_temp_dir.resolve().as_posix(),
        # Lands in run_results.json, tying the dbt invocation to this pipeline run.
        "DBT_ENV_CUSTOM_ENV_PITWALL_RUN_ID": run_id,
    }
    command = [
        dbt,
        "build",
        "--project-dir",
        str(project),
        "--profiles-dir",
        str(project),
        "--target-path",
        str(work_dir / "target"),
        "--log-path",
        str(work_dir / "logs"),
        "--vars",
        json.dumps({"session_key": session_key}),
        "--no-use-colors",
    ]

    log.info("dbt build started", extra={"session_key": session_key})
    # A separate process keeps dbt's global state out of the pipeline and releases the
    # warehouse file lock when it exits.
    result = subprocess.run(command, env=env, check=False)
    if result.returncode != 0:
        raise WarehouseBuildError(
            f"dbt build for session {session_key} exited with {result.returncode}; "
            f"details in {work_dir / 'logs' / 'dbt.log'}"
        )
    log.info("dbt build finished", extra={"session_key": session_key})
