from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.meta.evolve import mine_rule_llm
from baremetal_harness.meta.tasks import FailureTrace
from baremetal_harness.model.scripted import ScriptedModel


async def test_mine_rule_llm_returns_text() -> None:
    model = ScriptedModel((
        (TextDelta("always validate config"), ResponseCompleted("stop")),
    ))
    rule = await mine_rule_llm(model, (FailureTrace("a", "no config", ""),))
    assert rule == "always validate config"


async def test_mine_rule_llm_none_on_empty() -> None:
    assert await mine_rule_llm(None, ()) is None
