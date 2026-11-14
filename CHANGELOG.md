# Changelog

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
