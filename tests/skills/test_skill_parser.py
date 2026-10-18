import pytest

from baremetal_harness.skills.parser import SkillParseError, SkillParser


def test_parser_reads_frontmatter_and_body() -> None:
    text = """---
name: summarize
description: Summarize long project material.
triggers:
  - summarize
  - summary
---
# Instructions
Return facts with source references.
"""
    skill = SkillParser().parse(text, source_id="project:summarize")
    assert skill.name == "summarize"
    assert skill.triggers == ("summarize", "summary")
    assert "source references" in skill.instructions


def test_parser_rejects_tabs_and_nested_values() -> None:
    with pytest.raises(SkillParseError):
        SkillParser().parse("---\nname:\tbad\n---\nbody", source_id="bad")
