from baremetal_harness.planning.store import PlanStore
from baremetal_harness.planning.tools import make_planning_tools


def make_builtin_planning_tools(store: PlanStore):
    return tuple(
        tool for tool in make_planning_tools(store) if tool.spec.name != "list_todos"
    )
