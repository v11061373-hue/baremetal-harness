from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.meta.evolve import build_rule_skill, inject_rule, mine_rule
from baremetal_harness.meta.tasks import FailureTrace


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


def test_mine_rule_mechanical_fallback_joins_reasons() -> None:
    traces = (
        FailureTrace("a", "no config", "RunCompleted"),
        FailureTrace("b", "missing key", "RunCompleted"),
    )
    assert mine_rule(None, traces) == "no config missing key"


def test_mine_rule_none_when_no_failures() -> None:
    assert mine_rule(None, ()) is None
