from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.agent.loop import AgentLoop, VerificationFailed
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.model.fake import FakeModel
from baremetal_harness.sessions.serialization import decode_event, encode_event


class ScriptedVerifier:
    def __init__(self, decisions: list[str | None]) -> None:
        self._decisions = decisions
        self.calls: list[str] = []

    async def verify(self, output: str, prompt: str) -> str | None:
        self.calls.append(output)
        return self._decisions.pop(0)


async def test_verifier_pass_completes() -> None:
    verifier = ScriptedVerifier([None])
    loop = AgentLoop(
        FakeModel([TextDelta("ok"), ResponseCompleted("stop")]),
        model="fake",
        verifier=verifier,
    )

    result = await loop.run("say ok")

    assert result.status is RunStatus.COMPLETED
    assert result.output == "ok"
    assert verifier.calls == ["ok"]


async def test_verification_failed_roundtrips() -> None:
    envelope = EventEnvelope.create(
        run_id="r",
        session_id="s",
        sequence=1,
        payload=VerificationFailed("ok", "no config file"),
    )
    decoded = decode_event(encode_event(envelope))
    assert decoded.payload == VerificationFailed("ok", "no config file")


async def test_verifier_fail_then_pass_retries() -> None:
    verifier = ScriptedVerifier(["no config file", None])
    loop = AgentLoop(
        FakeModel([TextDelta("ok"), ResponseCompleted("stop")]),
        model="fake",
        verifier=verifier,
    )

    result = await loop.run("say ok")

    assert result.status is RunStatus.COMPLETED
    assert result.output == "ok"
    assert verifier.calls == ["ok", "ok"]
    failed = [
        e.payload
        for e in result.events
        if e.payload.__class__.__name__ == "VerificationFailed"
    ]
    assert len(failed) == 1
    assert failed[0].reason == "no config file"


async def test_verifier_fail_exhausts_turn_budget() -> None:
    loop = AgentLoop(
        FakeModel([TextDelta("ok"), ResponseCompleted("stop")]),
        model="fake",
        limits=RunLimits(max_turns=2),
        verifier=ScriptedVerifier(["no config", "no config"]),
    )

    result = await loop.run("say ok")

    assert result.status is RunStatus.EXHAUSTED
