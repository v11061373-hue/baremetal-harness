from baremetal_harness.subagents.factory import _child_prompt
from baremetal_harness.subagents.types import SubagentSpec


def test_child_prompt_injects_success_criteria() -> None:
    spec = SubagentSpec("a", "do thing", 0, 4, 4, ("read",), "tests pass")
    assert "You are done only when: tests pass" in _child_prompt(spec)


def test_child_prompt_omits_criteria_when_empty() -> None:
    spec = SubagentSpec("a", "do thing", 0, 4, 4, ("read",))
    assert "done only when" not in _child_prompt(spec)
