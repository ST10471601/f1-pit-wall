from pitwall.ingestion.rate_limit import RateLimiter
from tests.conftest import FakeClock


def _limiter(clock: FakeClock) -> RateLimiter:
    return RateLimiter([(3, 1.0), (30, 60.0)], clock=clock, sleep=clock.sleep)


def test_burst_up_to_the_per_second_limit_does_not_wait(clock: FakeClock) -> None:
    limiter = _limiter(clock)

    for _ in range(3):
        limiter.wait()

    assert clock.sleeps == []


def test_fourth_call_in_a_second_waits_for_the_window(clock: FakeClock) -> None:
    limiter = _limiter(clock)
    for _ in range(3):
        limiter.wait()
    clock.now = 0.25

    limiter.wait()

    assert clock.sleeps == [0.75]
    assert clock.now == 1.0


def test_per_minute_limit_holds_the_31st_call_until_a_minute_after_the_first(
    clock: FakeClock,
) -> None:
    limiter = _limiter(clock)
    for _ in range(30):
        limiter.wait()
    assert clock.now == 9.0

    limiter.wait()

    assert clock.now == 60.0
