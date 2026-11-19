# Work Graph

A local-first knowledge graph for agent work. Notes are plain Markdown with
YAML frontmatter and `[[wikilinks]]`. The same vault opens in Obsidian, Logseq,
Foam, or any text editor.

`work-graph` adds the parts that keep a vault honest:

- one running session per project, enforced by the CLI;
- a required case-study and evidence contract for session notes;
- a checker for broken links, stale sessions, duplicate questions, and drift;
- a watcher that rebuilds generated views and snapshots the vault with git;
- a compact `Home.md` dashboard, an `Open Questions` index, and an optional
  full `Knowledge.md` archive.

No database, daemon, or plugin is required to read the notes.

## What a session looks like

`start` writes the note and refreshes the dashboard. `close` refuses while the
note still holds placeholders, so a session without an outcome cannot pass as a
finished one. Transcript from a demo vault:

```console
$ work-graph start cache-bench --project demo --title "Cache hit rates"
demo-vault/Sessions/2026-11-19-cache-bench.md
Wrote demo-vault/Home.md (823 bytes)
Wrote demo-vault/Open Questions.md (251 bytes)

$ work-graph status
running:
  2026-11-19-cache-bench (demo)
check: 0 errors, 1 warnings
  WARN  watcher PID file is missing

$ work-graph close 2026-11-19-cache-bench
refusing to close an incomplete session:
  Outcome or Evidence still says Pending.
  placeholder still present: Pending.
Pass --force to close anyway.

$ work-graph close 2026-11-19-cache-bench   # after filling Outcome and Evidence
demo-vault/Sessions/2026-11-19-cache-bench.md
Wrote demo-vault/Home.md (718 bytes)
Wrote demo-vault/Open Questions.md (251 bytes)

$ work-graph check
Work graph check
Errors: 0
Warnings: 1
WARN  watcher PID file is missing
```

The one remaining warning is the watcher, which was not running for this
transcript.

## Install

Python 3.10 or newer.

```bash
python3 -m pip install --user --editable /path/to/work-graph
```

Or install the published package:

```bash
python3 -m pip install --user git+https://github.com/engida32/work-graph.git
```

For Hermes, install the package and link the skill in one step:

```bash
./install.sh --hermes
```

That symlinks `skills/work-graph` into `~/.agents/skills/work-graph` and
`~/.hermes/skills/work-graph`. Restart Hermes or run `hermes skills list` to
confirm it loads. Use `./install.sh --uninstall` to remove the command and only
the links this script created.

The command is `work-graph`. If it is not on `PATH`, invoke the module with the
Python that owns the install: `/usr/bin/python3 -m work_graph`.

## Quick start

Point the tool at a vault:

```bash
export WORK_GRAPH_VAULT="$HOME/work-graph-source"
export WORK_GRAPH_HOME="$HOME/work-graph-source/Home.md"
export WORK_GRAPH_VIEW="$HOME/work-graph/Knowledge.md"
export WORK_GRAPH_STATE="$HOME/.local/state/work-graph-knowledge"
```

The vault needs the source directories from [Vault layout](#vault-layout) and a
project note at `Projects/<project>.md` before the first `start`; without it the
CLI exits with `project MOC not found: <vault>/Projects/<project>.md`.

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
work-graph build                 # Home.md + Open Questions.md
work-graph build --archive       # also write Knowledge.md
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

Daily reads use the source pages plus two generated files:

- `WORK_GRAPH_HOME` (default `<vault>/Home.md`) is a compact dashboard with
  running sessions, project summaries, recent sessions, and at most 20 open
  questions. It stays under 50 KB for a typical vault.
- `WORK_GRAPH_QUESTIONS` (default `<vault>/Open Questions.md`) lists every open
  question and links the page that owns it. The dashboard links here instead of
  growing without bound.

`WORK_GRAPH_VIEW` (default `~/work-graph/Knowledge.md`) is an optional full-text
archive. `work-graph build` no longer writes it; pass `--archive` when you want
the single-file export. This keeps the watcher fast and avoids a 600 KB page in
the graph.

The builder is atomic and skips unchanged outputs. It writes a temporary file,
fsyncs it, and renames it over the old file. Generated timestamps come from the
newest source note, so rebuilding an unchanged vault is a no-op. The watcher
also commits a snapshot to git when the vault is a git repository.

`work-graph build --compact` is a legacy mode that writes the dashboard to
`WORK_GRAPH_VIEW`; use `--archive` for the full export.

## Logseq and Obsidian

Open the **source vault** as the graph, not the generated view. The notes already
use compatible frontmatter and wikilinks, and `Home.md` is the dashboard.

For Logseq, set `Home` as the start page and disable journals. The generated
dashboard links directly to project and session pages, so each note loads on its
own; `Open Questions` is a normal generated page. For Obsidian, open the vault
and use `Home.md` as the entry point.

`Home.md` and `Open Questions.md` are written to the vault root by default;
override them with:

```bash
export WORK_GRAPH_HOME="$HOME/work-graph/Home.md"
export WORK_GRAPH_QUESTIONS="$HOME/work-graph/Open Questions.md"
```

Add both generated pages to the vault's `.gitignore` if you do not want them in
the snapshot. The source notes remain canonical.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `WORK_GRAPH_VAULT` | `~/work-graph-source` | source vault root |
| `WORK_GRAPH_VIEW` | `~/work-graph/Knowledge.md` | full archive (opt-in) |
| `WORK_GRAPH_HOME` | `<vault>/Home.md` | compact dashboard |
| `WORK_GRAPH_QUESTIONS` | `<vault>/Open Questions.md` | full open-question index |
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
writes `validation.json`, rebuilds `Home.md` and `Open Questions.md`, and
snapshots the vault. It sends
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
