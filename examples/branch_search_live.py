"""Σ-RSI 分支搜索训练回路，接真模型（OpenAI 兼容端点），无端点离线回放。

展示 baremetal_harness.meta.search 的 Σ 派（scaffold 级）RSI 闭环：
ScaffoldState 候选枚举 → evaluate_state 离线评测 → weighted_gate 选最优非回退 →
promote_state 原子写回 SKILL.md，规则经 context_providers 回注当前轮。
LLM 挖规则走 mine_rule_llm（miner_client），所有候选必经机械 gate，LLM 提案不自由注入。

改的是脚手架（规则 + 评测套件），不是模型权重——Σ-RSI，非 θ 派（weight 训练）。

运行（需 OpenAI 兼容端点，例如 Ollama / vLLM / 任意 /v1 端点）：
  BAREMETAL_HARNESS_BASE_URL=http://localhost:11434/v1 \
  BAREMETAL_HARNESS_API_KEY=ollama \
  BAREMETAL_HARNESS_MODEL=qwen2.5 \
  uv run python examples/branch_search_live.py

不设端点则离线跑通同一条闭环（ScriptedModel 回放 fail→pass）。
"""

import asyncio
import os
import tempfile
from pathlib import Path

from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.meta import EvolutionTask, branch_search, promote_state
from baremetal_harness.model.openai_compat import OpenAICompatibleClient
from baremetal_harness.model.scripted import ScriptedModel


class CheckContains:
    """Verifier：输出必须含 needle，否则返回失败原因（机械判据，可离线自评）。"""

    def __init__(self, needle: str) -> None:
        self._needle = needle

    async def verify(self, output: str, prompt: str) -> str | None:
        if self._needle in output:
            return None
        return f"output missing {self._needle!r}"


async def main() -> None:
    base_url = os.environ.get("BAREMETAL_HARNESS_BASE_URL")
    api_key = os.environ.get("BAREMETAL_HARNESS_API_KEY")
    model = os.environ.get("BAREMETAL_HARNESS_MODEL", "default")

    tasks = (
        EvolutionTask(
            "math", "What is 6*7? Answer with just the number.", CheckContains("42")
        ),
    )

    if base_url and api_key:
        # 同一个无状态 client 既当跑任务的 provider，又当挖规则的 miner_client。
        provider = OpenAICompatibleClient(base_url, api_key)
        miner = provider
    else:
        print("no endpoint set — offline ScriptedModel demo")
        # provider 4 turn：baseline 2 次失败耗尽（AgentLoop 验证回环会重试）
        # → 机械候选通过 → LLM 候选通过
        provider = ScriptedModel((
            (TextDelta("6"), ResponseCompleted("stop")),
            (TextDelta("6"), ResponseCompleted("stop")),
            (TextDelta("42"), ResponseCompleted("stop")),
            (TextDelta("42"), ResponseCompleted("stop")),
        ))
        # miner 1 turn：LLM 挖规则回放
        miner = ScriptedModel(((TextDelta("answer 42"), ResponseCompleted("stop")),))
        model = "scripted"

    steps = await branch_search(
        tasks,
        provider=provider,
        miner_client=miner,
        model=model,
        tools=None,
        workspace=None,
        limits=RunLimits(2, 2),
        iterations=1,
    )

    for i, step in enumerate(steps):
        rules = step.promoted.rules if step.promoted else None
        print(f"step {i}: scores={step.scores} promoted={rules}")

    final = steps[-1].promoted if steps else None
    if final is None:
        print("== no promotion ==")
        return
    with tempfile.TemporaryDirectory() as tmp:
        skills = Path(tmp) / "skills"
        promote_state(final, skills_dir=skills)
        print("== promoted SKILL.md ==")
        print((skills / "harness-rules" / "SKILL.md").read_text(encoding="utf-8").rstrip())


if __name__ == "__main__":
    asyncio.run(main())
