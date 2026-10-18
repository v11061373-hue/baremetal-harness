import re
import subprocess
from pathlib import Path

SECRET_PATTERNS = (
    re.compile("sk-" + r"[A-Za-z0-9_-]{16,}"),
    re.compile("Bearer " + r"[A-Za-z0-9._-]{16,}"),
    re.compile("OPENAI_API_KEY" + r"=.+"),
)
RUNTIME_PARTS = {
    ".env",
    "state.db",
    "events.jsonl",
    "checkpoints",
    "sandboxes",
}


def repository_files() -> tuple[Path, ...]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
    )
    return tuple(
        Path(item.decode())
        for item in output.split(b"\0")
        if item
    )


def main() -> int:
    secret_findings = []
    runtime_findings = []
    for path in repository_files():
        if any(part in RUNTIME_PARTS for part in path.parts):
            runtime_findings.append(str(path))
        if path == Path(".env.example"):
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                secret_findings.append(f"{path}:{line_number}")

    if secret_findings:
        raise SystemExit(
            "possible tracked secret assignments: "
            + ", ".join(secret_findings)
        )
    if runtime_findings:
        raise SystemExit(
            "tracked runtime state paths: " + ", ".join(runtime_findings)
        )
    print("repository secret and runtime-state scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
