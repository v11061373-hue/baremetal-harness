from baremetal_harness.skills.discovery import discover_skills


def test_discovery_skips_disabled(tmp_path) -> None:
    root = tmp_path / ".baremetal_harness" / "skills"
    (root / "on").mkdir(parents=True)
    (root / "off").mkdir(parents=True)
    (root / "on" / "SKILL.md").write_text(
        "---\nname: on\ndescription: d\ntriggers:\n---\nbody"
    )
    (root / "off" / "SKILL.md").write_text(
        "---\nname: off\ndescription: d\ntriggers:\nenabled: false\n---\nbody"
    )
    skills = discover_skills(tmp_path, user_root=tmp_path / "user")
    assert [s.name for s in skills] == ["on"]
