import uuid
from datetime import UTC, datetime


def new_run_id(started_at: datetime) -> str:
    """Return a run id like 20261102T080000Z-3f9a1c."""
    # Timestamp first so ids sort by start time (used to keep the last N serving snapshots).
    # The suffix separates runs started in the same second. No colons: ids go into Windows paths.
    return f"{started_at.astimezone(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
