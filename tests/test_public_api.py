"""The curated public surface: embed (create_app) and eval-iterate (meta)."""

import baremetal_harness
from baremetal_harness import (
    BareMetalHarnessApp,
    BareMetalHarnessConfig,
    ModelProvider,
    RunResult,
    Verifier,
    create_app,
)
from baremetal_harness.meta import (
    EvolutionTask,
    eval_gate,
    eval_suite_manifest,
    evolve,
    mine_eval_cases,
    mine_rule,
    run_task,
)


def test_version_exported() -> None:
    assert baremetal_harness.__version__ == "0.1.0"


def test_embed_surface_exported() -> None:
    assert callable(create_app)
    assert BareMetalHarnessConfig.__name__ == "BareMetalHarnessConfig"
    assert BareMetalHarnessApp.__name__ == "BareMetalHarnessApp"
    assert ModelProvider.__name__ == "ModelProvider"
    assert Verifier.__name__ == "Verifier"
    assert RunResult.__name__ == "RunResult"


def test_eval_iteration_surface_exported() -> None:
    assert callable(run_task)
    assert callable(evolve)
    assert callable(mine_rule)
    assert callable(mine_eval_cases)
    assert callable(eval_gate)
    assert callable(eval_suite_manifest)
    assert EvolutionTask.__name__ == "EvolutionTask"
