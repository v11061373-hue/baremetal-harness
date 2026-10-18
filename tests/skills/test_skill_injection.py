from pathlib import Path

from baremetal_harness.agent.loop import AgentLoop, ContextInjected
from baremetal_harness.context.builder import ContextBuilder
from baremetal_harness.context.tokens import CharacterTokenEstimator
from baremetal_harness.context.types import ContextBudget, ContextSource
from baremetal_harness.core.messages import ResponseCompleted, TextContent, TextDelta
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.skills.parser import SkillParser
from baremetal_harness.skills.provider import SkillContextProvider

SKILL_DOCUMENT = """---
name: release-notes-writer
description: Write concise release notes
triggers:
  - release
scope: project
---
Always inspect evidence before writing release notes.
"""


def _skill():
    return SkillParser().parse(SKILL_DOCUMENT, source_id="project:release-notes-writer")


def _loop(provider: ScriptedModel, providers: tuple) -> AgentLoop:
    return AgentLoop(
        provider,
        "test-model",
        context_builder=ContextBuilder(CharacterTokenEstimator()),
        context_budget=ContextBudget(32_000, 4_000),
        context_providers=providers,
    )


async def test_matching_skill_reaches_the_model_as_a_system_message() -> None:
    provider = ScriptedModel(((TextDelta("ok"), ResponseCompleted("stop")),))

    await _loop(provider, (SkillContextProvider((_skill(),)),)).run(
        "write a release note for this repo"
    )

    system = [
        message
        for message in provider.requests[0].messages
        if message.role == "system"
    ]
    assert len(system) == 1
    text = "".join(
        item.text for item in system[0].content if isinstance(item, TextContent)
    )
    assert "Always inspect evidence" in text
    assert 'name="release-notes-writer"' in text


async def test_non_matching_prompt_injects_no_skill() -> None:
    provider = ScriptedModel(((TextDelta("ok"), ResponseCompleted("stop")),))

    await _loop(provider, (SkillContextProvider((_skill(),)),)).run(
        "unrelated arithmetic question"
    )

    assert not [
        message
        for message in provider.requests[0].messages
        if message.role == "system"
    ]


async def test_injection_is_recorded_as_an_auditable_event() -> None:
    provider = ScriptedModel(((TextDelta("ok"), ResponseCompleted("stop")),))

    result = await _loop(provider, (SkillContextProvider((_skill(),)),)).run(
        "write a release note"
    )

    injected = [
        event.payload
        for event in result.events
        if isinstance(event.payload, ContextInjected)
    ]
    assert injected == [ContextInjected(("skills",))]


async def test_blank_context_sources_are_not_injected() -> None:
    class EmptyProvider:
        async def build(self, prompt: str) -> tuple[ContextSource, ...]:
            return (ContextSource("memory", "   ", 60),)

    provider = ScriptedModel(((TextDelta("ok"), ResponseCompleted("stop")),))

    result = await _loop(provider, (EmptyProvider(),)).run("anything")

    assert not [
        message
        for message in provider.requests[0].messages
        if message.role == "system"
    ]
    assert not [
        event for event in result.events if isinstance(event.payload, ContextInjected)
    ]


async def test_injected_context_persists_across_turns(tmp_path: Path) -> None:
    provider = ScriptedModel(
        (
            (TextDelta("thinking"), ResponseCompleted("length")),
            (TextDelta("ok"), ResponseCompleted("stop")),
        )
    )

    await _loop(provider, (SkillContextProvider((_skill(),)),)).run(
        "write a release note"
    )

    # The run stops after a non-stop/non-tool finish reason, so only one
    # request is made; the first one must already carry the skill.
    assert provider.requests[0].messages[0].role == "system"
