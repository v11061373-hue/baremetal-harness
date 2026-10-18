from baremetal_harness.scheduler.store import SchedulerStore
from baremetal_harness.scheduler.tools import make_scheduler_tools


def make_builtin_scheduler_tools(store: SchedulerStore):
    return tuple(
        tool
        for tool in make_scheduler_tools(store)
        if tool.spec.name != "get_scheduled_task"
    )
