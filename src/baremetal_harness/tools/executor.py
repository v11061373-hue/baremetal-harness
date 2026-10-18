import logging

from baremetal_harness.core.errors import ToolArgumentsInvalid, ToolNotFound
from baremetal_harness.core.messages import ToolCall, ToolResultContent
from baremetal_harness.sandbox.router import SandboxRouter
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.tools.schema import validate_arguments
from baremetal_harness.tools.types import ToolContext

logger = logging.getLogger(__name__)

MAX_REASON_CHARACTERS = 300


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        sandbox_router: SandboxRouter | None = None,
    ) -> None:
        self.registry = registry
        self.sandbox_router = sandbox_router

    async def execute(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolResultContent:
        try:
            tool = self.registry.get(call.name)
            arguments = validate_arguments(tool.spec.parameters, call.arguments)
            output = await tool.handler(arguments, context)
        except ToolNotFound:
            return ToolResultContent(call.id, "tool not found", is_error=True)
        except ToolArgumentsInvalid:
            return ToolResultContent(call.id, "tool arguments invalid", is_error=True)
        except Exception as error:
            # The operator gets the traceback; the model gets only what is safe
            # to show it. Returning a bare "failed" to both made production
            # failures impossible to diagnose.
            logger.exception(
                "tool %s failed in run %s", call.name, context.run_id
            )
            return ToolResultContent(
                call.id,
                f"tool execution failed: {_describe(error)}",
                is_error=True,
            )
        return ToolResultContent(call.id, output)


def _describe(error: Exception) -> str:
    """Summarize a failure without leaking incidental internals.

    Tools raise ValueError deliberately to tell the caller what was wrong with
    a request, so that message is worth forwarding: it is how the model
    corrects itself. Any other exception is unplanned and its message may
    carry paths or payloads, so only the type is named.
    """
    if isinstance(error, ValueError):
        message = " ".join(str(error).split())
        if message:
            return message[:MAX_REASON_CHARACTERS]
    return type(error).__name__
