"""Validate a work-graph vault before the view is rebuilt."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .config import Config
from .frontmatter import frontmatter_value, project_stem, set_frontmatter_value, split_frontmatter
from .markdown import (
    CASE_STUDY,
    LINK_RE,
    question_items,
    fenced_flags,
    has_heading,
    insert_case_study,
    strip_anchor,
)
from .store import NoteIndex, SessionInfo, atomic_write, is_watcher_command

NOTE_DIRS = ("Projects", "Decisions", "Sessions", "Research", "Agents", "Maps")
FIX_DIRS = ("Projects", "Sessions", "Research", "Agents", "Maps")
REQUIRED_HEADINGS = (
    CASE_STUDY,
    "## Architecture",
    "## Important Notes",
    "## High-Level Plan",
    "## Tech Stack and Reasons",
)
STALE_DAYS = int(os.environ.get("WORK_GRAPH_STALE_DAYS", "7"))


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "fixed": self.fixed,
            "counts": {"errors": len(self.errors), "warnings": len(self.warnings)},
        }


def _notes(directory: Path, exclude: set[str] | None = None) -> list[Path]:
    if not directory.is_dir():
        return []
    excluded = exclude or set()
    return sorted(path for path in directory.glob("*.md") if path.name not in excluded)


def _check_structure(config: Config, result: CheckResult) -> None:
    for name in NOTE_DIRS:
        if not (config.vault / name).is_dir():
            result.errors.append(f"missing source directory: {name}/")
    if not config.autostart.is_file():
        result.warnings.append("autostart entry is missing")


def _check_sessions(index: NoteIndex, result: CheckResult) -> None:
    for item in index.sessions:
        lines = item.text.splitlines()
        if len(lines) > 150:
            result.errors.append(f"{index.config.relative(item.path)} is {len(lines)} lines, cap is 150")
        for heading in REQUIRED_HEADINGS:
            if not has_heading(item.text, heading):
                result.errors.append(
                    f"{index.config.relative(item.path)} missing {heading}"
                )


def _check_running(index: NoteIndex, result: CheckResult) -> None:
    running: dict[str, list[str]] = defaultdict(list)
    for item in index.sessions:
        if item.running:
            running[item.project or "unassigned"].append(item.stem)
    for project, names in running.items():
        if len(names) > 1:
            result.errors.append(
                f"multiple running sessions for {project}: {', '.join(names)}"
            )

    active = index.config.active
    if not active.is_file():
        result.errors.append("Sessions/Active.md is missing")
        return
    active_text = active.read_text(encoding="utf-8")
    if "## Running" not in active_text or "## Recently closed" not in active_text:
        result.errors.append("Sessions/Active.md is missing Running or Recently closed")
        return
    running_section = active_text.split("## Running", 1)[1].split("## Recently closed", 1)[0]
    linked = {
        match.group(1).removeprefix("Sessions/")
        for match in LINK_RE.finditer(running_section)
    }
    actual = {name for names in running.values() for name in names}
    for name in sorted(actual - linked):
        result.errors.append(f"running session is not linked under Active Running: {name}")
    for name in sorted(linked - actual):
        result.errors.append(f"Active Running links a non-running session: {name}")


def _resolve_link(target: str, config: Config, stems: set[str]) -> bool:
    target = strip_anchor(target)
    if not target or target.startswith(("http://", "https://")):
        return True
    if "/" in target:
        candidate = (config.vault / f"{target}.md").resolve()
        try:
            candidate.relative_to(config.vault.resolve())
        except ValueError:
            return False
        return candidate.is_file()
    return target in stems


def _check_links(index: NoteIndex, result: CheckResult) -> None:
    stems = {path.stem for path in index.notes}
    for path in index.notes:
        body = index.body(path)
        lines = body.splitlines()
        for line, fenced in zip(lines, fenced_flags(lines)):
            if fenced:
                continue
            for match in LINK_RE.finditer(line):
                target = match.group(1).strip()
                if not _resolve_link(target, index.config, stems):
                    result.errors.append(
                        f"{index.config.relative(path)} broken link: [[{target}]]"
                    )


def _check_projects(index: NoteIndex, result: CheckResult) -> None:
    by_project: dict[str, list[SessionInfo]] = defaultdict(list)
    for session in index.sessions:
        by_project[session.project].append(session)
    owner_by_stem = {session.stem: session.project for session in index.sessions}
    for project in index.projects:
        text = index.read(project)
        if not has_heading(text, CASE_STUDY):
            result.errors.append(f"{index.config.relative(project)} missing {CASE_STUDY}")
        _, frontmatter = split_frontmatter(text)
        updated = frontmatter_value(frontmatter, "updated")
        project_sessions = by_project.get(project.stem, [])
        for session in project_sessions:
            if f"[[Sessions/{session.stem}]]" not in text:
                result.warnings.append(
                    f"{index.config.relative(project)} does not link {session.stem}"
                )
        if project_sessions and not updated:
            result.warnings.append(f"{index.config.relative(project)} is missing updated:")
        if project_sessions and updated:
            latest = max((session.date for session in project_sessions if session.date), default="")
            if latest and latest > updated:
                result.warnings.append(
                    f"{index.config.relative(project)} updated {updated}, latest session {latest}"
                )
        if "## Sessions" in text:
            section = text.split("## Sessions", 1)[1].split("\n## ", 1)[0]
            for match in LINK_RE.finditer(section):
                target = match.group(1).strip()
                if not target.startswith("Sessions/"):
                    continue
                stem = target.removeprefix("Sessions/").split("#", 1)[0]
                owner = owner_by_stem.get(stem, "")
                if owner and owner != project.stem:
                    result.errors.append(
                        f"{index.config.relative(project)} Sessions links {target} "
                        f"owned by {owner}"
                    )


def _check_questions(index: NoteIndex, result: CheckResult) -> None:
    seen: dict[str, list[str]] = defaultdict(list)
    for path in index.notes:
        body = index.body(path)
        for text in question_items(body):
            key = re.sub(r"\s+", " ", text).lower()
            seen[key].append(index.config.relative(path))
    for key, paths in seen.items():
        if len(paths) < 2:
            continue
        kinds = {path.split("/", 1)[0] for path in paths}
        if kinds <= {"Projects", "Sessions"} and "Projects" in kinds:
            continue
        result.warnings.append(f"duplicate open question in {', '.join(paths)}: {key}")


def _check_freshness(index: NoteIndex, result: CheckResult) -> None:
    home = index.config.home
    if not home.is_file():
        result.errors.append("Home.md is missing; run `work-graph build`")
        return
    if index.notes:
        latest = max(path.stat().st_mtime for path in index.notes)
        if home.stat().st_mtime < latest:
            result.warnings.append("Home.md is older than the newest source note")


def _check_watcher(index: NoteIndex, result: CheckResult) -> None:
    pid_file = index.config.pid_file
    if not pid_file.is_file():
        result.warnings.append("watcher PID file is missing")
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
    except (ValueError, OSError):
        result.warnings.append("watcher is not running")
        return
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text()
    except OSError:
        result.warnings.append("watcher process is not readable")
        return
    if not is_watcher_command(cmdline):
        result.warnings.append(f"PID {pid} is not the knowledge watcher")


def _check_stale(index: NoteIndex, result: CheckResult) -> None:
    today = date.today()
    for item in index.sessions:
        if not item.running or not item.date:
            continue
        try:
            started = datetime.strptime(item.date, "%Y-%m-%d").date()
        except ValueError:
            continue
        age = (today - started).days
        if age > STALE_DAYS:
            result.warnings.append(
                f"{index.config.relative(item.path)} has been running for {age} days"
            )


def _fix_case_studies(index: NoteIndex, result: CheckResult) -> None:
    for name in FIX_DIRS:
        directory = index.config.vault / name
        for path in _notes(directory, exclude={"Active.md"} if name == "Sessions" else None):
            text = index.read(path)
            if has_heading(text, CASE_STUDY):
                continue
            atomic_write(path, insert_case_study(text))
            result.fixed.append(f"{index.config.relative(path)} (case study)")


def _fix_project_links(index: NoteIndex, result: CheckResult) -> None:
    by_project: dict[str, list[SessionInfo]] = defaultdict(list)
    for session in index.sessions:
        by_project[session.project].append(session)
    for project in index.projects:
        text = index.read(project)
        changed = False
        for session in by_project.get(project.stem, []):
            link = f"- [[Sessions/{session.stem}]]"
            if link in text:
                continue
            if "## Sessions" not in text:
                text = text.rstrip() + f"\n\n## Sessions\n\n{link}\n"
            else:
                before, rest = text.split("## Sessions", 1)
                marker = rest.find("\n## ")
                if marker == -1:
                    text = before + "## Sessions" + rest.rstrip() + f"\n\n{link}\n"
                else:
                    text = (
                        before
                        + "## Sessions"
                        + rest[:marker].rstrip()
                        + f"\n\n{link}\n"
                        + rest[marker:]
                    )
            changed = True
        if changed:
            text = set_frontmatter_value(text, "updated", date.today().isoformat())
            atomic_write(project, text)
            result.fixed.append(f"{index.config.relative(project)} (session links)")


def check(
    config: Config,
    *,
    fix: bool = False,
    index: NoteIndex | None = None,
    return_index: bool = False,
) -> CheckResult | tuple[CheckResult, NoteIndex]:
    result = CheckResult()
    index = index or NoteIndex.load(config)
    if fix:
        _fix_case_studies(index, result)
        _fix_project_links(index, result)
        if result.fixed:
            index = NoteIndex.load(config)

    _check_structure(config, result)
    _check_sessions(index, result)
    _check_running(index, result)
    _check_links(index, result)
    _check_projects(index, result)
    for name in ("Research", "Agents", "Maps"):
        for path in _notes(config.vault / name):
            text = path.read_text(encoding="utf-8")
            if not has_heading(text, CASE_STUDY):
                result.errors.append(f"{config.relative(path)} missing {CASE_STUDY}")
    _check_questions(index, result)
    _check_freshness(index, result)
    _check_watcher(index, result)
    _check_stale(index, result)
    if return_index:
        return result, index
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="apply safe repairs")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--portable", action="store_true", help="relative paths only")
    args = parser.parse_args(argv)
    result = check(Config.from_env(), fix=args.fix)
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print("Work graph check")
        print(f"Errors: {len(result.errors)}")
        print(f"Warnings: {len(result.warnings)}")
        for message in result.fixed:
            print(f"FIXED {message}")
        for message in result.errors:
            print(f"ERROR {message}")
        for message in result.warnings:
            print(f"WARN  {message}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
