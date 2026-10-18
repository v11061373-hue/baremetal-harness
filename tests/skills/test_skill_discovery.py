from pathlib import Path

from baremetal_harness.skills.discovery import discover_skills


def write_skill(root: Path, name: str, description: str) -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n"
        f"triggers:\n  - {name}\n---\nUse {name}.\n"
    )


def test_project_skill_shadows_user_skill(tmp_path: Path) -> None:
    project = tmp_path / "project" / ".baremetal_harness" / "skills"
    user = tmp_path / "user"
    write_skill(user, "review", "user version")
    write_skill(project, "review", "project version")

    skills = discover_skills(tmp_path / "project", user_root=user)

    assert len(skills) == 1
    assert skills[0].description == "project version"
    assert skills[0].source_id == "project:review"
