from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunMetrics:
    model_requests: int
    input_tokens: int | None
    output_tokens: int | None
    approval_requested: int
    approval_approved: int
    approval_denied: int
    final_status: str | None
