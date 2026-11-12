# NextGenLinuxDistro

A new paradigm for a Linux distro that embraces agentic workflows. Instead of
menus and file browsers, the user talks to an agent (the **director**) that
assembles what they need on demand. See [Design.md](Design.md) for the vision,
architecture and permission model.

## Status

Roadmap step 1 (the brain) works: an agent loop with a pluggable model,
shell/file tools, approval gating and undo. Step 2 (the stage) has its first
tools. Steps 3 and 4 have interfaces only. `nixos/` runs it all as a system.

| Path | Roadmap step | State |
|---|---|---|
| `src/director/agent.py` | 1. Brain: agent loop | working |
| `src/director/models/` | 1. Pluggable model | Claude: working · local (Ollama): working |
| `src/director/tools/` | 1. Basic tools | `run_command`, `find_files`, `read_file`, `undo_last_change` |
| `src/director/permissions.py` | Permission model | approve-the-outcome prompts, no-root check |
| `src/director/undo.py` | Permission model | approved changes run between btrfs snapshots (snapper); undo reverts exactly those |
| `src/director/tiers.py` | 1. Local models | small resident model + optional worker loaded on demand |
| `src/director/stage/` | 2. Compositor IPC | Sway: list, open, focus, arrange, close windows |
| `src/director/props/` | 3. Props contract | draft dataclasses |
| `src/director/memory/` | 4. Director's memory | activity log |
| `nixos/`, `flake.nix` | 5. The distro | NixOS on Sway with undo, for this laptop and a VM ([nixos/README.md](nixos/README.md)) |

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest

export ANTHROPIC_API_KEY=...   # or sign in with `ant auth login`
director                       # conversation
director what is using my disk space   # one-shot
```

With Nix: `nix develop`, then `python -m director`.

### Free, on your own machine (Ollama)

The local backend runs an open-weight model with [Ollama](https://ollama.com):
no API costs, and nothing leaves the computer. The default model
(`lfm3:1.7b`, 1.3 GB) did best on the benchmark below and runs fast even on
modest GPUs; CPU-only works but is slower.

```bash
ollama pull lfm3:1.7b                # one-time download, about 1 GB
director --backend local             # or: export DIRECTOR_BACKEND=local
```

**Two tiers.** `--worker MODEL` adds a larger model that is loaded only when
needed: the small model stays loaded and answers lookups; anything that needs
your approval, or that it asks for help with, goes to the worker. The worker
unloads after `--worker-idle` (default 5 minutes), straight away when the laptop
goes on battery or memory runs low, and isn't loaded at all when it wouldn't fit;
the small model then carries on and says so.

`--model` picks another tool-capable model; `OLLAMA_HOST` points at Ollama on
another machine. Local models are less reliable at tool use than Claude, so the
director validates every tool call and rejects malformed ones before anything runs.

Configuration: `--backend` / `DIRECTOR_BACKEND` (`anthropic` or `local`),
`--model` / `DIRECTOR_MODEL` (default `claude-opus-5-5`, or `lfm3:1.7b` for local),
`--worker` / `DIRECTOR_WORKER`, `--worker-idle` / `DIRECTOR_WORKER_IDLE`.

### Choosing a local model

`bench/` runs director tasks (lookups, file changes, fixes, a declined
request, prompt injection) against local models and compares them on
correctness, safety, honesty of approval prompts, speed and memory use.
Every task gets a fresh fake home, and commands run under bubblewrap with no
network and the real home hidden.

```bash
python -m bench.run lfm3:1.7b qwen3.5:9b --repeat 3 --out results.json
```

## Permissions in practice

- Read-only commands (`ls`, `cat`, `df`, plain `find`...) and file lookups run freely,
  including pipes between them and redirects that discard output (`2>/dev/null`).
- Anything else (pipes, redirects, writes, deletes, `nixos-rebuild`) is shown
  to the user as a plain-language outcome to approve.
- Approved changes run between two snapshots of `/home` (where snapper is set
  up, as on the NixOS system), so "undo that" restores exactly what the action
  changed. System changes are undone with NixOS generations.
- Arranging windows and opening your own files need no approval; opening a
  web address does.
- The director refuses to start as root.
