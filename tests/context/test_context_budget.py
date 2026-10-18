from baremetal_harness.context.compaction import (
    CompactionRequest,
    DeterministicCompactor,
)
from baremetal_harness.context.tokens import CharacterTokenEstimator
from baremetal_harness.core.messages import Message, TextContent


def test_character_estimator_rounds_up() -> None:
    assert CharacterTokenEstimator(chars_per_token=4).estimate("12345") == 2


async def test_deterministic_compactor_keeps_first_and_last_sentence() -> None:
    request = CompactionRequest(
        (
            Message(
                "user",
                (TextContent("First fact. Middle detail. Last result."),),
            ),
        ),
        target_tokens=20,
    )

    summary = await DeterministicCompactor().compact(request)

    assert summary == Message(
        "assistant",
        (TextContent("[summary] First fact. Last result."),),
    )
