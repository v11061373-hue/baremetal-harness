from dataclasses import dataclass
from pathlib import Path

from baremetal_harness.context.types import ContextSource


class ProjectRulesError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectRules:
    version: str
    content: str


def parse_project_rules(text: str) -> ProjectRules:
    """Parse AGENTS.md: ---\nversion: x.y.z\n---\n<body>."""
    if not text.startswith("---\n"):
        raise ProjectRulesError("frontmatter is required")
    try:
        frontmatter, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ProjectRulesError("frontmatter is not closed") from exc
    version = "0.0.0"
    for line in frontmatter.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "version":
            version = value.strip()
    return ProjectRules(version, body.strip())


class ProjectRulesProvider:
    def __init__(self, rules: ProjectRules | None) -> None:
        self.rules = rules

    @classmethod
    def load(cls, project_root: Path) -> "ProjectRulesProvider":
        path = project_root / ".baremetal_harness" / "AGENTS.md"
        if not path.is_file():
            return cls(None)
        return cls(parse_project_rules(path.read_text()))

    async def build(self, prompt: str) -> tuple[ContextSource, ...]:
        if self.rules is None:
            return ()
        return (
            ContextSource("project-rules", self.rules.content, 90, required=True),
        )
