import pytest

from baremetal_harness.context.builder import ContextBuilder
from baremetal_harness.context.tokens import CharacterTokenEstimator
from baremetal_harness.context.types import (
    ContextBudget,
    ContextBudgetExceeded,
    ContextSource,
)


def test_builder_keeps_required_sources_and_drops_low_priority() -> None:
    builder = ContextBuilder(CharacterTokenEstimator(chars_per_token=1))
    sources = (
        ContextSource("system", "must keep", priority=100, required=True),
        ContextSource("recent", "keep", priority=80),
        ContextSource("old", "drop-me", priority=10),
    )

    context = builder.build(sources, ContextBudget(total=13, reserve_output=0))

    assert [item.source_id for item in context.items] == ["system", "recent"]
    assert context.dropped_source_ids == ("old",)


def test_required_source_cannot_be_silently_dropped() -> None:
    builder = ContextBuilder(CharacterTokenEstimator(chars_per_token=1))

    with pytest.raises(ContextBudgetExceeded):
        builder.build(
            (ContextSource("system", "too large", 100, required=True),),
            ContextBudget(total=2, reserve_output=0),
        )

