import re

from baremetal_harness.skills.types import Skill

_ALLOWED_FRONTMATTER_KEYS = frozenset(
    {"name", "description", "triggers", "scope", "version", "enabled"}
)


class SkillParseError(ValueError):
    pass


class SkillParser:
    def parse(self, text: str, *, source_id: str) -> Skill:
        if "\t" in text:
            raise SkillParseError("tabs are not allowed")
        if len(text.encode()) > 64 * 1024:
            raise SkillParseError("skill body exceeds 64 KiB")
        if not text.startswith("---\n"):
            raise SkillParseError("frontmatter is required")
        try:
            frontmatter, body = text[4:].split("\n---\n", 1)
        except ValueError as exc:
            raise SkillParseError("frontmatter is not closed") from exc
        values: dict[str, object] = {}
        current_list: str | None = None
        for line in frontmatter.splitlines():
            if line.startswith("  - "):
                if current_list != "triggers":
                    raise SkillParseError("nested values are not supported")
                values.setdefault("triggers", [])
                values["triggers"].append(line[4:].strip())
                continue
            if line.startswith(" "):
                raise SkillParseError("nested values are not supported")
            if ":" not in line:
                raise SkillParseError("invalid frontmatter line")
            key, raw_value = line.split(":", 1)
            if key in values:
                raise SkillParseError(f"duplicate key: {key}")
            if key not in _ALLOWED_FRONTMATTER_KEYS:
                raise SkillParseError(f"unknown key: {key}")
            raw_value = raw_value.strip()
            if key == "triggers":
                if raw_value:
                    raise SkillParseError("triggers must be a list")
                values[key] = []
                current_list = key
            else:
                if not raw_value:
                    raise SkillParseError(f"{key} must be a scalar")
                values[key] = raw_value
                current_list = None
        name = values.get("name")
        description = values.get("description")
        if not isinstance(name, str) or not isinstance(description, str):
            raise SkillParseError("name and description are required")
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
            raise SkillParseError("invalid skill name")
        scope = values.get("scope", source_id.split(":", 1)[0])
        if scope not in {"user", "project"}:
            raise SkillParseError("scope must be user or project")
        triggers = values.get("triggers", [])
        if not isinstance(triggers, list) or not all(
            isinstance(item, str) and item for item in triggers
        ):
            raise SkillParseError("invalid triggers")
        version = str(values.get("version", "0.0.0"))
        enabled = str(values.get("enabled", "true")).lower() != "false"
        return Skill(
            name,
            description,
            tuple(triggers),
            str(scope),
            body.strip(),
            source_id,
            version=version,
            enabled=enabled,
        )
