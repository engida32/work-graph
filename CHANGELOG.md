# Changelog

## 0.1.4 - 2026-11-15

### Fixed

- `work-graph start` now initializes `Sessions/Active.md` on a fresh vault
  instead of crashing with `FileNotFoundError`.
- `work-graph close` removes the `No closed sessions yet.` placeholder when it
  records the first closed session.
- The `Home.md` freshness check compares the generated `Source updated` stamp
  instead of file mtime, so a byte-identical no-op rebuild no longer reports a
  false stale warning.

### Added

- Regression tests for fresh-vault start, first-close placeholder cleanup, and
  stamp-based freshness.

## 0.1.3 - 2026-11-14

### Changed

- `work-graph build` now writes `Home.md` and `Open Questions.md` only.
  `Knowledge.md` is an opt-in archive via `--archive`, so normal builds no
  longer regenerate a 600 KB page that no daily view reads.
- `Home.md` caps its open-question section at 20 items and links the rest to
  `Open Questions`; the dashboard no longer grows with every logged question.
- Builds reuse one `NoteIndex` read instead of re-reading every note for each
  section. Builder and checker project lookups use maps instead of repeated
  linear scans.
- Generated timestamps come from the newest source note, and unchanged outputs
  are not rewritten. An unchanged vault is a no-op instead of a new mtime on
  every watcher tick.
- The checker now verifies `Home.md` freshness instead of `Knowledge.md`.

### Added

- `WORK_GRAPH_QUESTIONS` (default `<vault>/Open Questions.md`).
- `work-graph build --archive`.
- Regression tests for dashboard-only builds, archive builds, question
  capping, and unchanged-build no-ops.


## 0.1.2 - 2026-11-14

### Fixed

- Duplicate open-question warnings now only consider checklist items inside a
  `## Open questions` section, so repeated plan checkboxes no longer warn.
- The watcher PID check recognizes the installed `work-graph watcher` console
  script, not just the legacy `watch-knowledge` script names.

### Added

- A regression test for duplicate-question scoping and watcher command
  detection.

### Changed

- `Home.md` now defaults to the vault root (`<vault>/Home.md`) so Obsidian sees
  it; `WORK_GRAPH_HOME` still overrides the path.

### Fixed

- Compact `Home.md` open questions now come only from `## Open questions` and
  join wrapped continuation lines instead of truncating them.
- Compact `Home.md` open-question links now use full page names
  (`Projects/...`, `Sessions/...`) so they resolve in Logseq and Obsidian.

## 0.1.1 - 2026-11-14

### Added

- `./install.sh --hermes` installs the package and links the skill into
  `~/.agents/skills/work-graph` and `~/.hermes/skills/work-graph`.
- `python3 -m work_graph` as a fallback when the console script is not on
  `PATH`.
- `./install.sh --uninstall` removes the package and only the skill links the
  script created.

### Fixed

- The installer now finds a Python interpreter that actually has `pip` instead
  of assuming `python3` does.

## 0.1.0 - 2026-11-14

First standalone release, extracted from the personal vault scripts.

### Fixed

- `Sessions/Active.md` can no longer be resolved as a session or corrupted by
  `close`/`abandon`.
- `start` enforces one running session per project and supports `--force`.
- `close` refuses incomplete notes by default; `--force` is explicit.
- Project names and session slugs reject path separators.
- Ambiguous session names list candidates instead of reporting "not found".
- Mutations are atomic and serialized with a file lock.
- The checker no longer crashes when `Active.md` lacks a Running section.
- Wikilinks with `#anchors` resolve correctly.
- `fix` adds missing project session links and updates `updated:`.

### Added

- `abandon` command.
- `status --json`, `check --json`, and `check --portable`.
- Stale running-session warnings (`WORK_GRAPH_STALE_DAYS`, default 7).
- `Home.md` compact dashboard.
- `WORK_GRAPH_VAULT`, `WORK_GRAPH_VIEW`, `WORK_GRAPH_HOME`,
  `WORK_GRAPH_STATE`, `WORK_GRAPH_AUTOSTART`, and `WORK_GRAPH_COMPACT`.
- `doctor` command.
- `watcher --once`.
- Unit tests for the P0 bugs and the generated views.
- CI workflow.

### Changed

- The package is installable with `pip install --user --editable .`.
- The CLI is `work-graph`; the old `scripts/*.py` names can remain as thin
  wrappers for an existing vault.
