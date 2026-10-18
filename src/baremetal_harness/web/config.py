import json
from dataclasses import fields
from pathlib import Path

from baremetal_harness.web.search import SearchEndpoint

SEARCH_FILENAME = "search.json"
SEARCH_API_KEY_VARIABLE = "BAREMETAL_HARNESS_SEARCH_API_KEY"


class SearchConfigError(ValueError):
    pass


def load_search_endpoint(
    workspace: Path,
    *,
    user_root: Path | None = None,
) -> SearchEndpoint | None:
    """Read a vendor-neutral search endpoint definition, or None if unset.

    The API key is never read from this file: it comes from the environment so
    a checked-in project config cannot carry a credential.
    """
    known = {item.name for item in fields(SearchEndpoint)}
    for root in (
        workspace / ".baremetal_harness",
        user_root or Path.home() / ".baremetal_harness",
    ):
        path = root / SEARCH_FILENAME
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise SearchConfigError(f"{path}: cannot be read as JSON") from error
        if not isinstance(payload, dict):
            raise SearchConfigError(f"{path}: root must be an object")
        # Checked before the generic unknown-field error so a leaked credential
        # gets the message that says where the key actually belongs.
        if "api_key" in payload:
            raise SearchConfigError(
                f"{path}: put the key in {SEARCH_API_KEY_VARIABLE}, not in the file"
            )
        unknown = set(payload) - known
        if unknown:
            raise SearchConfigError(f"{path}: unknown fields {sorted(unknown)}")
        if not isinstance(payload.get("url"), str) or not payload["url"]:
            raise SearchConfigError(f"{path}: 'url' is required")
        return SearchEndpoint(**payload)
    return None
