"""Terminal front end for the director. The stage and props come later."""

from __future__ import annotations

import argparse
import os
import sys

from .agent import Director
from .models import load_model
from .models.base import ModelError, ModelSetupError, ToolCall
from .models.residency import Residency
from .permissions import RunningAsRootError, ensure_not_root, make_terminal_approver
from .tiers import TieredDirector
from .tools import default_tools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="director", description="Talk to your desktop.")
    parser.add_argument("--backend", default=os.environ.get("DIRECTOR_BACKEND", "anthropic"),
                        choices=["anthropic", "local"])
    parser.add_argument("--model", default=os.environ.get("DIRECTOR_MODEL"))
    parser.add_argument("--worker", default=os.environ.get("DIRECTOR_WORKER"),
                        help="local backend: a larger model loaded on demand; --model stays loaded")
    parser.add_argument("--worker-idle", default=os.environ.get("DIRECTOR_WORKER_IDLE", "5m"),
                        help="how long the worker stays loaded after use (default 5m)")
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

    def backstage(text: str) -> None:
        if not args.quiet:
            print(f"  · {text}", file=sys.stderr)

    if args.worker and args.backend != "local":
        print("director: --worker needs --backend local", file=sys.stderr)
        return 1
    try:
        if args.worker:
            residency = Residency(args.worker)
            residency.watch(on_unload=lambda why: backstage(f"unloaded {args.worker}: {why}"))
            director = TieredDirector(
                resident=load_model("local", args.model, keep_alive=-1),
                worker=load_model("local", args.worker, keep_alive=args.worker_idle),
                tools=default_tools(),
                approver=make_terminal_approver(),
                residency=residency,
                on_tool=show_tool,
                on_handoff=lambda why: backstage(f"handing over to {args.worker} ({why})"),
            )
        else:
            director = Director(
                model=load_model(args.backend, args.model),
                tools=default_tools(),
                approver=make_terminal_approver(),
                on_tool=show_tool,
            )
    except ModelError as e:
        return _fail(e)

    if args.prompt:
        try:
            print(director.ask(" ".join(args.prompt)))
        except ModelError as e:
            return _fail(e)
        return 0

    print("Director ready. Ctrl-D to leave.")
    while True:
        try:
            text = input("\n› ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        try:
            print(director.ask(text))
        except ModelSetupError as e:
            return _fail(e)
        except ModelError as e:
            # Transient (network, rate limit): keep the conversation open.
            print(f"director: {e}", file=sys.stderr)


def _fail(error: ModelError) -> int:
    print(f"director: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
