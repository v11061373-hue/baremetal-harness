import argparse
import asyncio

from baremetal_harness.cli.repl import Repl
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.model.scripted import ScriptedModel


async def run_fake() -> None:
    provider = ScriptedModel(
        (
            (TextDelta("hello "), TextDelta("there"), ResponseCompleted("stop")),
            (TextDelta("second "), TextDelta("turn"), ResponseCompleted("stop")),
        )
    )
    repl = Repl(provider, "fake")
    await repl.run_turn("first")
    print()
    await repl.run_turn("second")
    print()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()
    if not args.fake:
        parser.error("this example requires --fake")
    asyncio.run(run_fake())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
