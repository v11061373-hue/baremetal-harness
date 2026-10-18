import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from baremetal_harness.app import create_app
from baremetal_harness.config import BareMetalHarnessConfig
from baremetal_harness.core.messages import ResponseCompleted, TextDelta, ToolCallDelta
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.permissions.approval import InMemoryApprovalProvider
from baremetal_harness.permissions.types import ApprovalResolution, PermissionRequest
from baremetal_harness.sessions.events import JsonlEventStore


class ExampleApprovalProvider:
    async def resolve(
        self,
        request: PermissionRequest,
    ) -> ApprovalResolution:
        approved = request.tool_name != "run_command"
        return ApprovalResolution(
            request.request_id,
            approved,
            "approved for offline example" if approved else "denied for offline example",
        )


def tool_turn(
    call_id: str,
    name: str,
    arguments: str,
) -> tuple[ToolCallDelta, ResponseCompleted]:
    return (
        ToolCallDelta(0, call_id, name, arguments),
        ResponseCompleted("tool_calls"),
    )


async def run_fake() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        project = root / "project"
        project.mkdir()
        (project / "README.md").write_text("original\n")
        skill_directory = project / ".baremetal_harness" / "skills" / "release-notes-writer"
        skill_directory.mkdir(parents=True)
        (skill_directory / "SKILL.md").write_text(
            """---
name: release-notes-writer
description: Write concise release notes
triggers:
  - release
scope: project
---
Inspect evidence before writing release notes.
"""
        )
        provider = ScriptedModel(
            (
                tool_turn(
                    "plan-1",
                    "create_plan",
                    (
                        '{"plan_id":"demo","goal":"build release notes","tasks":['
                        '{"task_id":"inspect","title":"Inspect project","depends_on":[]},'
                        '{"task_id":"write","title":"Write notes","depends_on":["inspect"]},'
                        '{"task_id":"verify","title":"Verify output","depends_on":["write"]}'
                        "]}"
                    ),
                ),
                tool_turn(
                    "delegate-1",
                    "delegate_task",
                    (
                        '{"agent_id":"reader","task":"inspect README",'
                        '"max_turns":2,"allowed_tools":["read_file"]}'
                    ),
                ),
                # The delegated child now runs a real AgentLoop against this
                # same provider, so it consumes its own model turns here.
                tool_turn(
                    "child-read-1",
                    "read_file",
                    '{"path":"README.md"}',
                ),
                (
                    TextDelta("child inspected README"),
                    ResponseCompleted("stop"),
                ),
                tool_turn(
                    "write-1",
                    "write_file",
                    '{"path":"notes.txt","content":"BareMetal Harness release note\\n"}',
                ),
                tool_turn(
                    "command-1",
                    "run_command",
                    '{"argv":["python","-c","print(42)"]}',
                ),
                tool_turn(
                    "memory-1",
                    "remember",
                    (
                        '{"memory_id":"note-1","text":"Artifacts require explicit apply",'
                        '"source_ref":"demo:notes.txt","tags":["safety"]}'
                    ),
                ),
                tool_turn(
                    "schedule-1",
                    "schedule_task",
                    (
                        '{"task_id":"job-1","task":"review notes",'
                        '"run_at":"2030-01-01T00:00:00+00:00","idempotent":true}'
                    ),
                ),
                tool_turn(
                    "cancel-1",
                    "cancel_scheduled_task",
                    '{"task_id":"job-1"}',
                ),
                (
                    TextDelta("offline BareMetal Harness flow completed"),
                    ResponseCompleted("stop"),
                ),
            )
        )
        app = await create_app(
            BareMetalHarnessConfig(root / "data", project, model="fake"),
            provider=provider,
            approval_provider=ExampleApprovalProvider(),
        )
        result = await app.run_prompt("build a release note")

        source_unchanged = not (project / "notes.txt").exists()
        memory_found = bool(await app.memory.search("explicit apply"))
        job = await app.scheduler.get("job-1")
        denied = any(
            getattr(item, "output", "") == "permission denied"
            for message in result.messages
            for item in message.content
        )
        applied = await app.workspace_session.apply_artifacts_approved(
            project,
            (Path("notes.txt"),),
            approval_provider=InMemoryApprovalProvider({"artifact-1": True}),
            event_store=JsonlEventStore(app.paths.data / "artifact-events.jsonl"),
            request_id="artifact-1",
        )
        trace_files = tuple(app.paths.traces.glob("*.jsonl"))

        print("skill loaded:", app.skills[0].name)
        print("plan tasks:", len((await app.plans.get("demo")).tasks))
        delegation = _delegation_result(result.messages)
        print(
            "delegation:",
            f"{delegation['status']} in run {delegation['child_run_id']};",
            f"evidence={delegation['evidence']}",
        )
        print("high-risk command denied:", "yes" if denied else "no")
        print("memory saved:", "yes" if memory_found else "no")
        print("scheduled job status:", job.status.value)
        print("source unchanged before apply:", "yes" if source_unchanged else "no")
        print("applied artifacts:", ",".join(path.as_posix() for path in applied))
        print("trace written:", "yes" if trace_files else "no")
        print("final response:", result.output)
        await app.aclose()


def _delegation_result(messages) -> dict:
    for message in messages:
        for item in message.content:
            output = getattr(item, "output", "")
            if '"agent_id"' in output:
                return json.loads(output)
    raise AssertionError("no delegation result recorded")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()
    if not args.fake:
        parser.error("this deterministic example requires --fake")
    asyncio.run(run_fake())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
