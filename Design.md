# Agent-Oriented Linux Distro — Design Doc

Working title: TBD. Status: early prototype planning.

## Vision

Rethink what an operating system does for its user. Instead of menus, file browsers and heavy UIs, the user talks to an agent that "puts on a show": like a Broadway production, the user sees the performance, not the rigging. The agent acts as a director, in the spirit of Left 4 Dead's AI Director, adapting what it presents based on what the user has been doing.

Non-technical users get a conversation. Technical users can always drop backstage into a shell.

## Guiding principles

- Invent as little software as possible. The only truly new piece is the orchestration layer (the director).
- Reuse industry-standard components as props rather than reinventing them.
- Visuals stay, but they are assembled on demand by the agent instead of being permanent chrome.
- A personal desktop OS, not a server OS. Old paradigms (like sudo) are questioned, not inherited by default.
- The agent is the main thing that needs watching, so safety is designed around it.

## Architecture

- **Base:** NixOS on the Linux kernel. The whole system is declared in text config, which agents edit well, and every change creates a generation that can be rolled back.
- **Stage:** a tiling Wayland compositor (e.g. Sway or Hyprland), controlled programmatically over IPC so the agent can open, place and close panes.
- **Props:** existing viewers and editors wrapped as tools: a text viewer, an image viewer, a code editor (Monaco, the editor component from VS Code), media player, tables, forms.
- **Director:** the orchestration layer, with its own harness rather than an agent framework: the permission model, the stage, the props and local-model handling are what make it different, and they are what a framework would replace. An agent loop with tools for the shell, files, the window manager and the props, plus a memory of recent activity to decide what to show and when.
- **Model:** user's choice, either a local model or a plugged-in subscription.
- **Backstage:** a shell is always available for manual control.

## Permission model

- The agent never has root.
- System changes are written as proposed Nix config changes.
- The user approves outcomes in plain language ("install a photo editor and enable Bluetooth?"), not commands or passwords.
- Everyday actions (opening files, arranging windows) need no approval. System changes and anything irreversible (deleting, sending data out) do.
- Nix rollback is the safety net.
- Treat prompt injection from web pages and files as a core threat.
- No inbound remote channels: the director takes requests only from the person at the machine, never from messaging apps or network listeners, which would be ways in for attackers.
- MCP servers are untrusted code: each runs sandboxed with only the access it needs, its tools go through the same permission tiers as built-in ones, and what it returns is data, not instructions.

## Prototype roadmap

1. **The brain:** a simple agent loop with a pluggable model (local or subscription) and basic tools like running commands and finding files.
2. **The stage:** give it control of the compositor via IPC.
3. **The props:** support MCP (Model Context Protocol) first, so tools and props speak the common standard: the director can use existing MCP servers, and its props can be used by other agents. Then wrap a few existing viewers as MCP servers, and define the contract for how the agent tells a prop what to do and hears back what the user did.
4. **The director's memory:** track recent activity and use it to decide pacing and presentation.
5. **The distro:** package everything as a NixOS-based image with its own name and branding.

Build steps 1 to 4 on an existing machine first; each step should produce something usable.

## Licensing notes

Not legal advice. The kernel and most userland are GPL or similar: modifying and redistributing is allowed, but shipped binaries need source availability. The bigger catch is trademarks: use your own name and branding rather than the base distro's.

## Known risks and open questions

- **Speed:** routing every action through a model is slow; quick direct controls are needed alongside the director.
- **Unpredictability:** the same request may produce a different stage, which works against habit and muscle memory.
- **Model capability:** strong local models need lots of GPU memory; smaller ones are weaker at tool use. A subscription means the OS depends on the internet.
- **Approval fatigue:** too many prompts and users approve everything.
- **Wrapping props:** most apps weren't built to be controlled by another program; this may be where most of the effort goes.
- **Blank-box problem:** non-technical users may not know what to ask.
- **Big apps:** browsers and games won't fit neatly as props.
- **Timing:** this may be ahead of the technology. The prototype is for learning; the permission design, props contract and director pacing can be worked out now regardless of model quality.
