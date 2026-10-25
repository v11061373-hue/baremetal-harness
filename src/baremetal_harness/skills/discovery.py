from pathlib import Path

from baremetal_harness.skills.parser import SkillParser
from baremetal_harness.skills.types import Skill


def _discover(root: Path, scope: str) -> tuple[Skill, ...]:
    if not root.exists():
        return ()
    resolved_root = root.resolve()
    skills = []
    for path in sorted(root.glob("*/SKILL.md")):
        resolved = path.resolve()
        if not resolved.is_relative_to(resolved_root):
            continue
        skills.append(
            SkillParser().parse(
                path.read_text(),
                source_id=f"{scope}:{path.parent.name}",
            )
        )
    return tuple(skills)


def discover_skills(
    project_root: Path,
    *,
    user_root: Path | None = None,
) -> tuple[Skill, ...]:
    project_skills = _discover(
        project_root / ".baremetal_harness" / "skills",
        "project",
    )
    user_skills = _discover(
        user_root or Path.home() / ".baremetal_harness" / "skills",
        "user",
    )
    by_name = {skill.name: skill for skill in user_skills}
    by_name.update({skill.name: skill for skill in project_skills})
    return tuple(
        skill
        for skill in (by_name[name] for name in sorted(by_name))
        if skill.enabled
    )
