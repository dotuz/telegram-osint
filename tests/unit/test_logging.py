import json

import pytest

from security.logging import (
    bind_job_id,
    bind_request_id,
    clear_context,
    configure_logging,
    get_logger,
)

pytestmark = pytest.mark.unit


def test_json_logging_includes_bound_context(capfd):
    configure_logging(level="INFO", json_output=True)
    bind_request_id("req-123")
    bind_job_id("job-abc")
    get_logger("test").info("hello", foo="bar")
    clear_context()

    err = capfd.readouterr().err.strip().splitlines()[-1]
    payload = json.loads(err)
    assert payload["event"] == "hello"
    assert payload["request_id"] == "req-123"
    assert payload["job_id"] == "job-abc"
    assert payload["foo"] == "bar"
    assert payload["level"] == "info"


def test_context_cleared_between_calls(capfd):
    configure_logging(level="INFO", json_output=True)
    clear_context()
    get_logger("test").info("no-context")
    err = capfd.readouterr().err.strip().splitlines()[-1]
    payload = json.loads(err)
    assert "request_id" not in payload
    assert "job_id" not in payload
