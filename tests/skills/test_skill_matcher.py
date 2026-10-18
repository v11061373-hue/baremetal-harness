from baremetal_harness.skills.context import skills_context
from baremetal_harness.skills.matcher import SkillMatcher
from baremetal_harness.skills.types import Skill


def skill(name: str, description: str, triggers=()) -> Skill:
    return Skill(name, description, tuple(triggers), "project", "instructions", f"project:{name}")


def test_trigger_beats_description_overlap() -> None:
    skills = (
        skill("triggered", "other", ("summarize",)),
        skill("overlap", "summarize project material"),
    )
    matches = SkillMatcher().match("summarize this")
    selected = matches.select(skills)
    assert [item.skill.name for item in selected] == ["triggered", "overlap"]


def test_explicit_selection_and_implicit_limit() -> None:
    skills = tuple(skill(f"s{index}", "common words") for index in range(6))
    explicit = (skill("chosen", "none"),) + skills

    assert SkillMatcher().match("/skill chosen").select(explicit)[0].score == 100
    assert len(SkillMatcher().match("common words").select(skills)) == 4


def test_skill_context_is_instruction_text() -> None:
    matches = SkillMatcher().match("/skill chosen").select(
        (skill("chosen", "none"),)
    )

    source = skills_context(matches)

    assert source.priority == 95
    assert '<skill name="chosen" source="project:chosen">' in source.text
    assert "instructions" in source.text
