# 评测点声明模板：7 种 EvalAssertion 各一个「略微修改即用」样例。
#
# 只做样例，不进评分层（评分层机械跑 evaluate_assertion）。用户抄改。
#
# 校准指引（Phase 2 才碰，教科书公式，无新依赖）：
# - Cohen's κ：判官 vs 机械断言/人工标注一致性，κ = (p_o − p_e)/(1 − p_e)，目标 ≥ 0.7。
# - ECE：判官置信度 vs 实际正确率校准误差，分桶算 |acc − conf| 加权，目标 ≤ 0.1。
# - 两条标准库可写（statistics/纯算术）。不达标 = 判官不可信，不回写权重。
from baremetal_harness.evals.types import EvalAssertion
from baremetal_harness.meta.tasks import EvalPoint

# output_equals：结论精确匹配
correctness = EvalPoint("correctness", EvalAssertion("output_equals", "42"), 1.0)
# status_equals：状态机终态（RunStatus 是 StrEnum，expected 用小写 .value）
finished = EvalPoint("finish", EvalAssertion("status_equals", "completed"), 1.0)
# event_sequence_contains：关键事件链（expected 必须是 list）
used_tool = EvalPoint("tool_usage", EvalAssertion("event_sequence_contains", ["ToolCalled"]), 1.0)
# tool_called：正调用某工具
read_file = EvalPoint("read_usage", EvalAssertion("tool_called", "read_file"), 1.0)
# tool_not_called：负未调用某工具
write_file = EvalPoint("no_write", EvalAssertion("tool_not_called", "write_file"), 1.0)
# approval_count：审批次数（int）
approval_once = EvalPoint("approval", EvalAssertion("approval_count", 1), 1.0)
# no_secret_in_trace：痕迹无泄密（output + 文本消息 + 工具结果，不含 ToolCall.arguments）
no_secret = EvalPoint("no_leak", EvalAssertion("no_secret_in_trace", "API_KEY"), 1.0)
