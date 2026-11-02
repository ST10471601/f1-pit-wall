import time
from collections import deque
from collections.abc import Callable, Sequence


class RateLimiter:
    """Blocks until a call fits every (max_calls, period_seconds) sliding window."""

    def __init__(
        self,
        windows: Sequence[tuple[int, float]],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._windows = list(windows)
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque(maxlen=max(max_calls for max_calls, _ in windows))

    def wait(self) -> None:
        """Sleep until another call is allowed, then record it."""
        while (delay := self._delay()) > 0:
            self._sleep(delay)
        self._calls.append(self._clock())

    def _delay(self) -> float:
        now = self._clock()
        # A window is full when its max_calls-th most recent call is younger than the period.
        return max(
            (
                self._calls[-max_calls] + period - now
                for max_calls, period in self._windows
                if len(self._calls) >= max_calls
            ),
            default=0.0,
        )
