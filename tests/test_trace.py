"""Tests for SQLite trace persistence and isolation."""

from min_agent.trace.recorder import TraceRecorder


def test_trace_lifecycle_persists_ordered_events_and_duration(tmp_path) -> None:
    recorder = TraceRecorder(str(tmp_path / "trace.db"))
    trace_id = recorder.start_trace("user-a", "session-1")
    recorder.record_event(
        trace_id,
        "llm.completed",
        step_index=1,
        status="succeeded",
        duration_ms=12.5,
        details={"tool_call_count": 1, "api_key": "must-not-be-stored"},
    )
    recorder.finish_trace(
        trace_id,
        status="succeeded",
        stop_reason="final_answer",
    )

    trace = recorder.get_trace("user-a", trace_id)

    assert trace is not None
    assert trace["status"] == "succeeded"
    assert trace["stop_reason"] == "final_answer"
    assert trace["duration_ms"] >= 0
    assert trace["events"][0]["event_type"] == "llm.completed"
    assert trace["events"][0]["details"] == {"tool_call_count": 1}
    assert recorder.get_trace("user-b", trace_id) is None


def test_trace_failure_records_type_without_exception_message(tmp_path) -> None:
    recorder = TraceRecorder(str(tmp_path / "trace.db"))
    trace_id = recorder.start_trace("user-a", "session-1")
    recorder.finish_trace(
        trace_id,
        status="failed",
        stop_reason="error",
        error=RuntimeError("sensitive-value-should-not-be-persisted"),
    )

    trace = recorder.get_trace("user-a", trace_id)

    assert trace is not None
    assert trace["status"] == "failed"
    assert trace["error_type"] == "RuntimeError"
    assert "sensitive-value" not in trace["error_message"]
