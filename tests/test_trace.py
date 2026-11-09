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


def test_trace_event_pagination_returns_stable_cursor(tmp_path) -> None:
    recorder = TraceRecorder(str(tmp_path / "trace-pages.db"))
    trace_id = recorder.start_trace("user-a", "session-1")
    for index in range(5):
        recorder.record_event(
            trace_id,
            f"event-{index}",
            step_index=index,
            status="succeeded",
        )
    recorder.finish_trace(trace_id, status="succeeded", stop_reason="final_answer")

    first_page = recorder.get_trace("user-a", trace_id, event_limit=2)
    assert first_page is not None
    assert len(first_page["events"]) == 2
    assert first_page["has_more_events"] is True

    second_page = recorder.get_trace(
        "user-a",
        trace_id,
        event_limit=2,
        after_event_id=first_page["next_after_event_id"],
    )
    assert second_page is not None
    assert len(second_page["events"]) == 2
    assert second_page["events"][0]["event_id"] > first_page["events"][-1]["event_id"]

    last_page = recorder.get_trace(
        "user-a",
        trace_id,
        event_limit=2,
        after_event_id=second_page["next_after_event_id"],
    )
    assert last_page is not None
    assert len(last_page["events"]) == 1
    assert last_page["has_more_events"] is False


def test_trace_retention_deletes_finished_traces_and_cascades_events(tmp_path) -> None:
    import sqlite3

    database_path = str(tmp_path / "trace-retention.db")
    recorder = TraceRecorder(database_path)
    trace_id = recorder.start_trace("user-a", "session-1")
    recorder.record_event(trace_id, "runtime.completed", status="succeeded")
    recorder.finish_trace(trace_id, status="succeeded", stop_reason="final_answer")

    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE traces SET finished_at = '2000-01-01T00:00:00+00:00' WHERE trace_id = ?",
        (trace_id,),
    )
    connection.commit()
    connection.close()

    deleted = recorder.prune_older_than(30)

    assert deleted == 1
    assert recorder.get_trace("user-a", trace_id) is None
    connection = sqlite3.connect(database_path)
    remaining_events = connection.execute(
        "SELECT COUNT(*) FROM trace_events WHERE trace_id = ?",
        (trace_id,),
    ).fetchone()[0]
    connection.close()
    assert remaining_events == 0


def test_trace_classifies_provider_timeout_storage_and_validation_errors() -> None:
    import sqlite3

    from min_agent.llm.errors import LLMProviderError

    assert TraceRecorder.classify_error(LLMProviderError("provider")) == "provider"
    assert TraceRecorder.classify_error(TimeoutError("timeout")) == "timeout"
    assert TraceRecorder.classify_error(sqlite3.OperationalError("locked")) == "storage"
    assert TraceRecorder.classify_error(ValueError("invalid")) == "validation"
