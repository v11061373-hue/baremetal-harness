import json
from collections.abc import Iterable

from baremetal_harness.context.tokens import CharacterTokenEstimator
from baremetal_harness.context.types import (
    AgentContext,
    ContextBudget,
    ContextBudgetExceeded,
    ContextSource,
)
from baremetal_harness.core.messages import Message, TextContent

DEFAULT_CONTEXT_PRIORITIES = {
    "system": 100,
    "tools": 90,
    "plan": 80,
    "recent_messages": 70,
    "memory": 60,
    "older_messages": 30,
}


class ContextBuilder:
    def __init__(self, estimator: CharacterTokenEstimator) -> None:
        self.estimator = estimator

    def build(
        self,
        sources: Iterable[ContextSource],
        budget: ContextBudget,
    ) -> AgentContext:
        indexed = tuple(enumerate(sources))
        required = tuple(item for item in indexed if item[1].required)
        optional = sorted(
            (item for item in indexed if not item[1].required),
            key=lambda item: (-item[1].priority, item[0]),
        )
        selected_indices: set[int] = set()
        used = 0
        for index, source in required:
            used += self.estimator.estimate(source.text)
            selected_indices.add(index)
        if used > budget.input_limit:
            raise ContextBudgetExceeded("required context exceeds input budget")
        for index, source in optional:
            cost = self.estimator.estimate(source.text)
            if used + cost <= budget.input_limit:
                used += cost
                selected_indices.add(index)
        items = tuple(
            source for index, source in indexed if index in selected_indices
        )
        dropped = tuple(
            source.source_id
            for index, source in indexed
            if index not in selected_indices
        )
        return AgentContext(items, used, dropped)


def sources_from_messages(messages: tuple[Message, ...]) -> tuple[ContextSource, ...]:
    sources = []
    recent_start = max(0, len(messages) - 4)
    for index, message in enumerate(messages):
        text = "".join(
            item.text for item in message.content if isinstance(item, TextContent)
        )
        if not text:
            text = json.dumps(
                [
                    item.__class__.__name__
                    for item in message.content
                ],
                separators=(",", ":"),
            )
        category = "recent_messages" if index >= recent_start else "older_messages"
        sources.append(
            ContextSource(
                f"message:{index}",
                f"{message.role}: {text}",
                DEFAULT_CONTEXT_PRIORITIES[category],
            )
        )
    return tuple(sources)
