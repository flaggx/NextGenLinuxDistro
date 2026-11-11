"""Terminal front end for the director. The stage and props come later."""

from __future__ import annotations

import argparse
import os
import sys

from .agent import Director
from .models import load_model
from .models.base import ToolCall
from .permissions import RunningAsRootError, ensure_not_root, make_terminal_approver
from .tools import default_tools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="director", description="Talk to your desktop.")
    parser.add_argument("--backend", default=os.environ.get("DIRECTOR_BACKEND", "anthropic"),
                        choices=["anthropic", "local"])
    parser.add_argument("--model", default=os.environ.get("DIRECTOR_MODEL"))
    parser.add_argument("--quiet", action="store_true", help="hide backstage tool activity")
    parser.add_argument("prompt", nargs="*", help="one-shot request; omit for a conversation")
    args = parser.parse_args(argv)

    try:
        ensure_not_root()
    except RunningAsRootError as e:
        print(e, file=sys.stderr)
        return 1

    def show_tool(call: ToolCall) -> None:
        if not args.quiet:
            detail = call.input.get("command") or call.input.get("path") or call.input.get("pattern", "")
            print(f"  · {call.name} {detail}", file=sys.stderr)

    director = Director(
        model=load_model(args.backend, args.model),
        tools=default_tools(),
        approver=make_terminal_approver(),
        on_tool=show_tool,
    )

    if args.prompt:
        print(director.ask(" ".join(args.prompt)))
        return 0

    print("Director ready. Ctrl-D to leave.")
    while True:
        try:
            text = input("\n› ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text:
            print(director.ask(text))


if __name__ == "__main__":
    sys.exit(main())
