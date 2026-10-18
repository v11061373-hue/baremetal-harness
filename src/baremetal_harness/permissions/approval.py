from collections.abc import Callable, Iterable

from baremetal_harness.permissions.types import ApprovalResolution, PermissionRequest


class InMemoryApprovalProvider:
    def __init__(self, resolutions: dict[str, bool]) -> None:
        self.resolutions = dict(resolutions)
        self.consumed: set[str] = set()

    async def resolve(self, request: PermissionRequest) -> ApprovalResolution:
        if request.request_id in self.consumed:
            return ApprovalResolution(
                request.request_id, False, "approval already consumed"
            )
        self.consumed.add(request.request_id)
        approved = self.resolutions.get(request.request_id, False)
        return ApprovalResolution(
            request.request_id,
            approved,
            "approved" if approved else "denied",
        )


class UnattendedApprovalProvider:
    """Approve only what a human pre-authorized, because none is present.

    Background runs (scheduled tasks) must not silently escalate privileges, so
    an ASK decision degrades to a denial. A tool can still be granted ahead of
    time by naming it in `approved_tools`, which is how a scheduled job is
    allowed to do something the policy would otherwise stop to ask about.
    """

    def __init__(self, approved_tools: Iterable[str] = ()) -> None:
        self.approved_tools = frozenset(approved_tools)

    async def resolve(self, request: PermissionRequest) -> ApprovalResolution:
        if request.tool_name in self.approved_tools:
            return ApprovalResolution(
                request.request_id,
                True,
                "pre-authorized for unattended runs",
            )
        return ApprovalResolution(
            request.request_id,
            False,
            "unattended run cannot obtain approval",
        )


class CliApprovalProvider:
    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self.input_fn = input_fn
        self.output_fn = output_fn
        self.consumed: set[str] = set()

    async def resolve(self, request: PermissionRequest) -> ApprovalResolution:
        if request.request_id in self.consumed:
            return ApprovalResolution(
                request.request_id, False, "approval already consumed"
            )
        self.consumed.add(request.request_id)
        self.output_fn(
            f"{request.tool_name}: {request.arguments_preview}\n"
            f"reason: {request.reason}"
        )
        answer = self.input_fn("Approve? [y/n] ").strip().casefold()
        approved = answer == "y"
        return ApprovalResolution(
            request.request_id,
            approved,
            "approved" if approved else "denied",
        )
