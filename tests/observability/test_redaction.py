from baremetal_harness.observability.redaction import Redactor


def test_redactor_masks_headers_keys_and_environment() -> None:
    payload = {
        "headers": {"Authorization": "Bearer test-value"},
        "api_key": "test-value",
        "environment": {"PATH": "/bin", "TOKEN": "test-value"},
        "nested": [{"password": "test-value"}],
    }
    assert Redactor().redact(payload) == {
        "headers": {"Authorization": "[REDACTED]"},
        "api_key": "[REDACTED]",
        "environment": {"PATH": "/bin", "TOKEN": "[REDACTED]"},
        "nested": [{"password": "[REDACTED]"}],
    }
