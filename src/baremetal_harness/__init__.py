"""BareMetal Harness — 可嵌入的评测迭代 Agent harness。

两条公开面：
- 嵌入：`create_app` + `run_prompt`，进程内当库用。
- 评测迭代：`baremetal_harness.meta` 的 run-mine-gate-eval 外循环。
"""

from baremetal_harness.agent.loop import RunResult, Verifier
from baremetal_harness.app import BareMetalHarnessApp, create_app
from baremetal_harness.config import BareMetalHarnessConfig
from baremetal_harness.model.base import ModelProvider

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "create_app",
    "BareMetalHarnessApp",
    "BareMetalHarnessConfig",
    "ModelProvider",
    "Verifier",
    "RunResult",
]
