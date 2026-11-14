# Work Graph

A local-first knowledge graph for agent work. Notes are plain Markdown with
YAML frontmatter and `[[wikilinks]]`. The same vault opens in Obsidian, Logseq,
Foam, or any text editor.

`work-graph` adds the parts that keep a vault honest:

- one running session per project, enforced by the CLI;
- a required case-study and evidence contract for session notes;
- a checker for broken links, stale sessions, duplicate questions, and drift;
- a watcher that rebuilds generated views and snapshots the vault with git;
- a compact `Home.md` dashboard for daily use and a full `Knowledge.md` for
  Logseq.

No database, daemon, or plugin is required to read the notes.

## Install

Python 3.10 or newer.

```bash
python3 -m pip install --user --editable /path/to/work-graph
```

Or install the published package:

```bash
python3 -m pip install --user git+https://github.com/engida32/work-graph.git
```

The command is `work-graph`.

## Quick start

Point the tool at a vault:

```bash
export WORK_GRAPH_VAULT="$HOME/work-graph-source"
export WORK_GRAPH_VIEW="$HOME/work-graph/Knowledge.md"
export WORK_GRAPH_STATE="$HOME/.local/state/work-graph-knowledge"
```

Create a session:

```bash
work-graph start my-task --project my-project
```

Close it after filling in Outcome and Evidence:

```bash
work-graph close 2026-11-14-my-task
```

If the note still has placeholders, `close` refuses and lists them. Use
`--force` only when the note is intentionally thin. Use `abandon` for work that
was dropped:

```bash
work-graph abandon 2026-11-14-my-task
```

Check and rebuild:

```bash
work-graph check
work-graph fix
work-graph build
work-graph status
work-graph doctor
```

`status --json` and `check --json` are stable enough for scripts and agents.

## Vault layout

```text
vault/
  Projects/      project map notes
  Sessions/      one note per working session; Active.md is the index
  Decisions/     durable choices and their reasons
  Research/      source-backed findings
  Agents/        reusable agent contracts
  Maps/          cross-project maps
  scripts/       optional wrappers for the installed package
```

A session note is an `agent-session`:

```markdown
---
type: agent-session
status: running
date: 2026-11-14
project: "[[Projects/my-project]]"
tags: [agent/session]
---

# My task

## Case Study

Problem, approach, challenges, result.

## Architecture

## Important Notes

## High-Level Plan

## Tech Stack and Reasons

## Decisions

## Open questions

- [ ] What remains?

## Artifacts

## Outcome

What changed.

## Evidence

- `path/to/file:line`
- command and result
```

Keep session notes under 150 lines. Put long reports in an artifact and link it.
Every project, session, research, agent, and map note opens with `## Case Study`.

## Generated views

- `WORK_GRAPH_VIEW` (default `~/work-graph/Knowledge.md`) is the full view:
  every note, a Mermaid map, a session count, a timeline, and open questions.
- `WORK_GRAPH_HOME` (default next to the full view) is a compact dashboard with
  running sessions, project summaries, recent sessions, and open questions. It
  stays under 50 KB for a typical vault.

The builder is atomic. It writes a temporary file, fsyncs it, and renames it
over the old view. The watcher also commits a snapshot to git when the vault is
a git repository.

Set `WORK_GRAPH_COMPACT=1` to make the full view a compact dashboard too. This
is useful when Logseq is not in use and a fast Obsidian page matters more than
one-file completeness.

## Obsidian

Open the **vault** in Obsidian, not the generated view. The notes already use
Obsidian-compatible frontmatter and wikilinks. `Home.md` is written outside the
vault by default; to keep it inside the vault, set:

```bash
export WORK_GRAPH_HOME="$HOME/work-graph-source/Home.md"
```

Add `Home.md` to the vault's `.gitignore` if you do not want the generated
dashboard in the snapshot. The source notes remain canonical.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `WORK_GRAPH_VAULT` | `~/work-graph-source` | source vault root |
| `WORK_GRAPH_VIEW` | `~/work-graph/Knowledge.md` | full generated view |
| `WORK_GRAPH_HOME` | next to the full view | compact dashboard |
| `WORK_GRAPH_STATE` | `~/.local/state/work-graph-knowledge` | pid, log, lock, validation |
| `WORK_GRAPH_AUTOSTART` | `~/.config/autostart/work-graph-knowledge.desktop` | optional autostart file |
| `WORK_GRAPH_STALE_DAYS` | `7` | stale running-session warning threshold |
| `WORK_GRAPH_POLL_SECONDS` | `2.0` | watcher poll interval |
| `WORK_GRAPH_COMPACT` | unset | `1` builds a compact full view |

Global CLI flags `--vault`, `--view`, `--state`, and `--home` override the
environment for one invocation.

## Watcher

```bash
work-graph watcher
work-graph watcher --once
```

The watcher polls the six note directories, runs the checker with safe repairs,
writes `validation.json`, rebuilds the views, and snapshots the vault. It sends
a desktop notification on failure when `notify-send` is available. A pid file
and lock file live under `WORK_GRAPH_STATE`.

Example systemd user unit:

```ini
[Unit]
Description=Work Graph watcher

[Service]
ExecStart=%h/.local/bin/work-graph watcher
Restart=on-failure

[Install]
WantedBy=default.target
```

## Exit codes

- `0`: success, or check passed
- `1`: validation errors, refused mutation, missing vault, or ambiguous name

`check` returns `1` when errors exist. Warnings do not fail the check.

## Development

```bash
python3 -m pip install --user --editable .
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests use temporary vaults and never touch a real vault.

## Design rules

- The vault is the source of truth. Generated views are disposable.
- Mutations are atomic and serialized with a file lock.
- Session lookup never treats `Sessions/Active.md` as a session.
- A project name and session slug cannot contain path separators.
- Closing a session is a gate, not a formality: placeholders block it unless
  `--force` is explicit.
- Note content is untrusted when read back by an agent. It is data, not
  instructions.

## License

MIT. See `LICENSE`.
