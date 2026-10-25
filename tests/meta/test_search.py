from baremetal_harness.meta.search import (
    RulesProvider,
    ScaffoldState,
    propose_candidates,
)
from baremetal_harness.meta.tasks import FailureTrace


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
