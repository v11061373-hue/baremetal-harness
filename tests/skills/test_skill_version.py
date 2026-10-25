from baremetal_harness.skills.parser import SkillParser


def test_parser_reads_version_and_enabled() -> None:
    skill = SkillParser().parse(
        "---\nname: demo\ndescription: d\ntriggers:\nversion: 2.0.0\n"
        "enabled: false\n---\nbody",
        source_id="user:demo",
    )
    assert skill.version == "2.0.0"
    assert skill.enabled is False
