"""Access logs retain useful metadata but omit HR query text and client IP."""

import json
import logging
import logging.config
from pathlib import Path

from uvicorn.logging import AccessFormatter

from app.core.log_safety import RequestMetadataFilter


def test_query_and_client_are_not_logged():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %s",
        (
            "PRIVATE_IP_CANARY",
            "GET",
            "/api/v1/policies/search?q=PRIVATE_HR_QUERY_CANARY",
            "1.1",
            200,
        ),
        None,
    )
    assert RequestMetadataFilter().filter(record)
    output = AccessFormatter(
        fmt="%(client_addr)s %(request_line)s %(status_code)s"
    ).format(record)
    assert "PRIVATE_" not in output
    assert "/api/v1/policies/search" in output and "200" in output


def test_packaged_log_configuration_applies_filter():
    config = json.loads(
        (Path(__file__).resolve().parents[2] / "logging.json").read_text()
    )
    assert config["handlers"]["access"]["filters"] == ["metadata"]
    assert (
        config["filters"]["metadata"]["()"]
        == "app.core.log_safety.RequestMetadataFilter"
    )
