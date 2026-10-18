from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.agent.loop import AgentLoop, ContextBuilt
from baremetal_harness.context.builder import ContextBuilder
from baremetal_harness.context.tokens import CharacterTokenEstimator
from baremetal_harness.context.types import ContextBudget
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.model.fake import FakeModel
from baremetal_harness.sessions.checkpoints import FileCheckpointStore
from baremetal_harness.sessions.database import SessionRepository


async def test_agent_records_context_snapshot(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path / "state.db")
    await repository.initialize()
    store = FileCheckpointStore(tmp_path / "checkpoints", repository)
    loop = AgentLoop(
        FakeModel((TextDelta("done"), ResponseCompleted("stop"))),
        "fake",
        session_repository=repository,
        checkpoint_store=store,
        clock=lambda: datetime(2026, 7, 26, tzinfo=UTC),
        context_builder=ContextBuilder(
            CharacterTokenEstimator(chars_per_token=1)
        ),
        context_budget=ContextBudget(total=100, reserve_output=10),
    )

    result = await loop.run("hello")

    context_event = next(
        event.payload
        for event in result.events
        if isinstance(event.payload, ContextBuilt)
    )
    checkpoint = await store.latest_for_run(result.run_id)
    assert context_event.estimated_tokens == 11
    assert checkpoint is not None
    assert checkpoint.context_snapshot is not None
    assert checkpoint.context_snapshot.estimated_tokens == 11
