from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.meta.evolve import build_rule_skill, inject_rule


def test_build_rule_skill_has_frontmatter_and_rules() -> None:
    text = build_rule_skill(("always check config", "never force-push"))
    assert "name: harness-rules" in text
    assert "- always check config" in text
    assert "- never force-push" in text


async def test_inject_rule_writes_skill_and_memory(tmp_path) -> None:
    skills = tmp_path / "skills"
    store = SqliteMemoryStore(tmp_path / "state.db", tmp_path / "src")
    await store.initialize()
    await inject_rule("test rule", store=store, skills_dir=skills, run_id="r1")
    assert (skills / "harness-rules" / "SKILL.md").is_file()
    assert "test rule" in (skills / "harness-rules" / "SKILL.md").read_text()
    records = await store.search("mined rule", now=None)
    assert any("test rule" in r.text for r in records)
