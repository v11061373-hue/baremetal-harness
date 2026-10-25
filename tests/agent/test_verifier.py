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


async def test_verification_failed_roundtrips() -> None:
    envelope = EventEnvelope.create(
        run_id="r",
        session_id="s",
        sequence=1,
        payload=VerificationFailed("ok", "no config file"),
    )
    decoded = decode_event(encode_event(envelope))
    assert decoded.payload == VerificationFailed("ok", "no config file")
