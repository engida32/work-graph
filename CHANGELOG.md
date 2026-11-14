# Changelog

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
