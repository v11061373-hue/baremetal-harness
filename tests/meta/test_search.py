from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.meta.evolve import build_rule_skill
from baremetal_harness.meta.search import (
    RulesProvider,
    ScaffoldState,
    branch_search,
    evaluate_state,
    promote_state,
    propose_candidates,
)
from baremetal_harness.meta.tasks import EvolutionTask, FailureTrace
from baremetal_harness.model.scripted import ScriptedModel


def test_scaffold_state_default() -> None:
    assert ScaffoldState().rules == ()


async def test_rules_provider_empty() -> None:
    assert await RulesProvider(()).build("prompt") == ()


async def test_rules_provider_nonempty() -> None:
    sources = await RulesProvider(("r1", "r2")).build("prompt")
    assert len(sources) == 1
    source = sources[0]
    assert source.source_id == "harness-rules"
    assert "r1" in source.text
    assert source.required is True
    assert source.priority == 90


def test_propose_candidates_one_failure() -> None:
    candidates = propose_candidates(
        ScaffoldState(),
        (FailureTrace("t", "no config", "RunCompleted"),),
    )
    assert candidates == (ScaffoldState(("no config",)),)


def test_propose_candidates_three_failures() -> None:
    candidates = propose_candidates(
        ScaffoldState(("r0",)),
        (
            FailureTrace("a", "fa", ""),
            FailureTrace("b", "fb", ""),
            FailureTrace("c", "fc", ""),
        ),
    )
    assert candidates == (
        ScaffoldState(("r0", "fa")),
        ScaffoldState(("r0", "fa fb")),
        ScaffoldState(("r0", "fa fb fc")),
    )


def test_propose_candidates_empty() -> None:
    assert propose_candidates(ScaffoldState(), ()) == ()


class _Pass:
    async def verify(self, output: str, prompt: str) -> str | None:
        return None


class _Eq:
    def __init__(self, expected: str) -> None:
        self.expected = expected

    async def verify(self, output: str, prompt: str) -> str | None:
        return None if output.strip() == self.expected else f"want {self.expected}"


async def test_evaluate_state_injects_rules() -> None:
    model = ScriptedModel(((TextDelta("ok"), ResponseCompleted("stop")),))
    task = EvolutionTask("t", "6*7", _Pass(), ())
    runs = await evaluate_state(
        ScaffoldState(("rule-xyz",)),
        (task,),
        provider=model,
        model="m",
        tools=None,
        workspace=None,
        limits=RunLimits(),
    )
    assert len(runs) == 1
    system = model.requests[-1].messages[0]
    assert system.role == "system"
    assert "rule-xyz" in system.content[0].text


async def test_branch_search_promotes() -> None:
    model = ScriptedModel((
        (TextDelta("6"), ResponseCompleted("stop")),
        (TextDelta("42"), ResponseCompleted("stop")),
    ))
    task = EvolutionTask("math", "6*7", _Eq("42"), ())
    steps = await branch_search(
        (task,),
        provider=model,
        model="m",
        tools=None,
        workspace=None,
        limits=RunLimits(max_turns=1),
        iterations=1,
    )
    assert steps[-1].promoted is not None
    assert steps[-1].promoted.rules == ("want 42",)


async def test_branch_search_no_improvement_stops() -> None:
    model = ScriptedModel((
        (TextDelta("6"), ResponseCompleted("stop")),
        (TextDelta("6"), ResponseCompleted("stop")),
    ))
    task = EvolutionTask("math", "6*7", _Eq("42"), ())
    steps = await branch_search(
        (task,),
        provider=model,
        model="m",
        tools=None,
        workspace=None,
        limits=RunLimits(max_turns=1),
        iterations=1,
    )
    assert steps[-1].promoted is None


async def test_branch_search_rejects_regression() -> None:
    model = ScriptedModel((
        (TextDelta("42"), ResponseCompleted("stop")),
        (TextDelta("6"), ResponseCompleted("stop")),
    ))
    task = EvolutionTask("math", "6*7", _Eq("42"), ())
    steps = await branch_search(
        (task,),
        provider=model,
        model="m",
        tools=None,
        workspace=None,
        limits=RunLimits(max_turns=1),
        iterations=1,
    )
    assert steps[-1].promoted is None


def test_promote_state_writes_skill(tmp_path) -> None:
    promote_state(ScaffoldState(("r1",)), skills_dir=tmp_path)
    path = tmp_path / "harness-rules" / "SKILL.md"
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == build_rule_skill(("r1",))
