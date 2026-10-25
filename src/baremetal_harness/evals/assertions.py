from baremetal_harness.agent.loop import ApprovalRequested, RunResult
from baremetal_harness.core.messages import TextContent, ToolCall, ToolResultContent
from baremetal_harness.evals.types import EvalAssertion


def evaluate_assertion(
    assertion: EvalAssertion,
    result: RunResult,
) -> str | None:
    if assertion.kind == "output_equals":
        actual = result.output
    elif assertion.kind == "status_equals":
        actual = result.status.value
    elif assertion.kind == "event_sequence_contains":
        actual = [event.payload.__class__.__name__ for event in result.events]
        expected = assertion.expected
        if not isinstance(expected, list) or not all(
            item in actual for item in expected
        ):
            return "event sequence does not contain expected event types"
        return None
    elif assertion.kind == "tool_called":
        names = {
            content.name
            for message in result.messages
            for content in message.content
            if isinstance(content, ToolCall)
        }
        if assertion.expected not in names:
            return f"tool_called: expected {assertion.expected!r} not called"
        return None
    elif assertion.kind == "tool_not_called":
        names = {
            content.name
            for message in result.messages
            for content in message.content
            if isinstance(content, ToolCall)
        }
        if assertion.expected in names:
            return f"tool_not_called: {assertion.expected!r} was called"
        return None
    elif assertion.kind == "approval_count":
        count = sum(
            isinstance(event.payload, ApprovalRequested) for event in result.events
        )
        if count != assertion.expected:
            return f"approval_count expected {assertion.expected!r}, got {count!r}"
        return None
    elif assertion.kind == "no_secret_in_trace":
        # 覆盖边界：output + 消息文本 + 工具结果。不含 ToolCall.arguments
        # 与事件 payload——机械门只检已知载体，接受漏检（设计文档 §一.7）。
        secret = str(assertion.expected)
        haystacks = [result.output]
        for message in result.messages:
            for content in message.content:
                if isinstance(content, TextContent):
                    haystacks.append(content.text)
                elif isinstance(content, ToolResultContent):
                    haystacks.append(content.output)
        if any(secret in haystack for haystack in haystacks):
            return "no_secret_in_trace: secret leaked into trace"
        return None
    else:
        return f"assertion kind is not supported by this runner: {assertion.kind}"
    if actual != assertion.expected:
        return f"{assertion.kind} expected {assertion.expected!r}, got {actual!r}"
    return None
