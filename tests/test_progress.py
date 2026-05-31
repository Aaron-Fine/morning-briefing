import logging
from morning_digest import progress


def test_track_logs_start_and_done(caplog):
    progress.reset()
    with caplog.at_level(logging.INFO):
        with progress.track("desk ai_tech"):
            assert progress.in_flight_labels() == ["desk ai_tech"]
    assert progress.in_flight_labels() == []
    msgs = [r.message for r in caplog.records]
    assert any("desk ai_tech: start" in m for m in msgs)
    assert any("desk ai_tech: done" in m for m in msgs)


def test_heartbeat_line_formats_in_flight():
    progress.reset()
    with progress.track("a"):
        with progress.track("b"):
            line = progress.heartbeat_line()
    assert line is not None
    assert "waiting on 2 op" in line
    assert "a" in line and "b" in line


def test_heartbeat_line_quiet_when_idle():
    progress.reset()
    assert progress.heartbeat_line() is None
