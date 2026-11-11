"""Run director tasks against local models and compare them.

    python -m bench.run qwen3.5:4b qwen3.5:9b --out results.json

Each task gets a fresh fake home; commands run sandboxed (see sandbox.py).
Every model is unloaded first, so its cold load time is measured too.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from director.agent import Director
from director.models.base import ModelError
from director.models.local import LocalModel, endpoint_from_env

from . import fixtures
from .sandbox import sandboxed_tools
from .tasks import TASKS, Record, Task, dishonest_summaries


class MeteredModel(LocalModel):
    """LocalModel that keeps Ollama's timing stats and can switch thinking on or off."""

    def __init__(self, model: str, num_ctx: int, think: bool | None) -> None:
        super().__init__(model, num_ctx=num_ctx)
        self.think = think
        self.replies: list[dict[str, Any]] = []

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.think is not None:
            body = {**body, "think": self.think}
        reply = super().post(path, body)
        self.replies.append(reply)
        return reply


def ollama(path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(endpoint_from_env() + path, data=data), timeout=120) as r:
        return json.loads(r.read())


def unload_all() -> None:
    for m in ollama("/api/ps").get("models", []):
        ollama("/api/generate", {"model": m["name"], "keep_alive": 0})


def run_task(model_name: str, task: Task, workdir: Path, num_ctx: int, think: bool | None) -> dict[str, Any]:
    home = fixtures.build_home(workdir / task.name / "home")
    model = MeteredModel(model_name, num_ctx, think)
    record = Record()

    def approver(request):
        record.approvals.append((request, task.approve))
        return task.approve

    director = Director(model, sandboxed_tools(home), approver=approver, on_tool=record.calls.append)
    start = time.monotonic()
    error = None
    try:
        record.answer = director.ask(task.prompt)
    except ModelError as e:
        error = f"model error: {e}"
    seconds = time.monotonic() - start

    replies = model.replies
    raw_calls = sum(len((r.get("message") or {}).get("tool_calls") or []) for r in replies)
    gen_tokens = sum(r.get("eval_count", 0) for r in replies)
    gen_seconds = sum(r.get("eval_duration", 0) for r in replies) / 1e9
    return {
        "task": task.name,
        "category": task.category,
        "failure": error or task.check(home, record),
        "seconds": round(seconds, 2),
        "load_seconds": round(sum(r.get("load_duration", 0) for r in replies) / 1e9, 2),
        "model_calls": len(replies),
        "tool_calls": len(record.calls),
        # The director rejects these before they run (bad arguments, unknown tool).
        "invalid_calls": raw_calls - len(record.calls),
        "approvals": len(record.approvals),
        "dishonest_summaries": dishonest_summaries(record),
        "gen_tokens": gen_tokens,
        "gen_tok_per_s": round(gen_tokens / gen_seconds, 1) if gen_seconds else None,
        "prompt_tokens": sum(r.get("prompt_eval_count", 0) for r in replies),
        "commands": record.commands(),
        "answer": record.answer[:600],
    }


def run_model(
    name: str, tasks: list[Task], workdir: Path, num_ctx: int, think: bool | None, repeat: int
) -> dict[str, Any]:
    unload_all()
    results = []
    memory: dict[str, Any] = {}
    for rep in range(repeat):
        for task in tasks:
            result = run_task(name, task, workdir / str(rep), num_ctx, think)
            results.append(result)
            mark = "ok  " if result["failure"] is None else "FAIL"
            print(f"  {mark} {task.name:16} {result['seconds']:6.1f}s  {result['failure'] or ''}", flush=True)
            if not memory:
                loaded = next((m for m in ollama("/api/ps").get("models", []) if m["name"] == name), None)
                if loaded:
                    memory = {"size_gb": round(loaded["size"] / 1e9, 1),
                              "gpu_fraction": round(loaded["size_vram"] / loaded["size"], 2)}
    return {"model": name, "think": think, "num_ctx": num_ctx, "repeat": repeat, **memory,
            "cold_load_seconds": results[0]["load_seconds"] if results else None, "results": results}


def summarize(run: dict[str, Any]) -> dict[str, Any]:
    rs = run["results"]
    by_cat: dict[str, list[bool]] = {}
    for r in rs:
        by_cat.setdefault(r["category"], []).append(r["failure"] is None)
    speeds = [r["gen_tok_per_s"] for r in rs if r["gen_tok_per_s"]]
    return {
        "model": run["model"] + ("" if run["think"] is None else f" (think={run['think']})"),
        "passed": f"{sum(r['failure'] is None for r in rs)}/{len(rs)}",
        **{cat: f"{sum(v)}/{len(v)}" for cat, v in by_cat.items()},
        "unsafe": sum(str(r["failure"]).startswith("UNSAFE") for r in rs),
        "dishonest": sum(len(r["dishonest_summaries"]) for r in rs),
        "invalid_calls": sum(r["invalid_calls"] for r in rs),
        "lookup_prompts": sum(r["approvals"] for r in rs if r["category"] == "lookup"),
        "median_s": round(statistics.median(r["seconds"] for r in rs), 1) if rs else None,
        "tok/s": round(statistics.median(speeds)) if speeds else None,
        "cold_load_s": run.get("cold_load_seconds"),
        "size_gb": run.get("size_gb"),
        "on_gpu": run.get("gpu_fraction"),
    }


def markdown_table(rows: list[dict[str, Any]]) -> str:
    cols = list(dict.fromkeys(k for row in rows for k in row))
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(row.get(c, "")) for c in cols) + " |" for row in rows]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench", description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="+")
    parser.add_argument("--out", type=Path, default=Path("bench-results.json"))
    parser.add_argument("--workdir", type=Path, help="where the fake homes go (default: a temp dir)")
    parser.add_argument("--tasks", help="comma-separated task names (default: all)")
    parser.add_argument("--num-ctx", type=int, default=16384)
    parser.add_argument("--think", choices=["default", "on", "off"], default="default")
    parser.add_argument("--repeat", type=int, default=1, help="runs per task; small models vary")
    args = parser.parse_args(argv)

    tasks = TASKS if not args.tasks else [t for t in TASKS if t.name in args.tasks.split(",")]
    think = {"default": None, "on": True, "off": False}[args.think]
    workdir = Path(tempfile.mkdtemp(prefix="bench-", dir=args.workdir))
    runs = json.loads(args.out.read_text()) if args.out.exists() else []

    for name in args.models:
        print(f"\n== {name}", flush=True)
        runs.append(run_model(name, tasks, workdir / str(len(runs)), args.num_ctx, think, args.repeat))
        args.out.write_text(json.dumps(runs, indent=1))

    print("\n" + markdown_table([summarize(r) for r in runs]))
    unload_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
