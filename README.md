# NextGenLinuxDistro

A new paradigm for a Linux distro that embraces agentic workflows. Instead of
menus and file browsers, the user talks to an agent (the **director**) that
assembles what they need on demand. See [Design.md](Design.md) for the vision,
architecture and permission model.

## Status

Roadmap step 1 (the brain) is scaffolded: a working agent loop with a
pluggable model, shell/file tools, and approval gating. Steps 2 to 4 have
interfaces only.

| Path | Roadmap step | State |
|---|---|---|
| `src/director/agent.py` | 1. Brain: agent loop | working |
| `src/director/models/` | 1. Pluggable model | Claude: working · local (Ollama): working |
| `src/director/tools/` | 1. Basic tools | `run_command`, `find_files`, `read_file` |
| `src/director/permissions.py` | Permission model | approve-the-outcome prompts, no-root check |
| `src/director/stage/` | 2. Compositor IPC | interface only |
| `src/director/props/` | 3. Props contract | draft dataclasses |
| `src/director/memory/` | 4. Director's memory | activity log |
| `flake.nix` | 5. The distro | dev shell only |

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
no API costs, and nothing leaves the computer. A GPU with 8 GB of video memory
runs the default model (`qwen3:8b`) comfortably; CPU-only works but is slow.

```bash
ollama pull qwen3:8b                 # one-time download, about 5 GB
director --backend local             # or: export DIRECTOR_BACKEND=local
```

`--model` picks another tool-capable model; `OLLAMA_HOST` points at Ollama on
another machine. Local models are less reliable at tool use than Claude, so the
director validates every tool call and rejects malformed ones before anything runs.

Configuration: `--backend` / `DIRECTOR_BACKEND` (`anthropic` or `local`),
`--model` / `DIRECTOR_MODEL` (default `claude-opus-5-5`, or `qwen3:8b` for local).

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
- The director refuses to start as root.
