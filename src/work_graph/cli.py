"""Command line interface for the work graph."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from . import builder, checker, watcher
from .config import Config
from .frontmatter import set_frontmatter_value, slugify, validate_slug
from .store import (
    NoteIndex,
    add_running,
    add_to_project,
    atomic_write,
    close_running,
    find_session,
    mutation_lock,
    session_template,
    strict_issues,
    touch_project,
    validate_project,
)


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _config(args: argparse.Namespace) -> Config:
    config = Config.from_env()
    if args.vault:
        config = replace(config, vault=args.vault.expanduser().resolve())
    if args.view:
        config = replace(config, view=args.view.expanduser().resolve())
    if args.state:
        config = replace(config, state=args.state.expanduser().resolve())
    if args.home:
        config = replace(config, home=args.home.expanduser().resolve())
    return config


def _build(config: Config, *, compact: bool = False, home: bool = True) -> int:
    try:
        output = builder.build(config, compact=compact, home=home)
    except FileNotFoundError as error:
        return fail(str(error))
    print(f"Wrote {output} ({output.stat().st_size} bytes)")
    if home and config.home != output and config.home.is_file():
        print(f"Wrote {config.home} ({config.home.stat().st_size} bytes)")
    return 0


def start(args: argparse.Namespace) -> int:
    config = _config(args)
    try:
        project = validate_project(config, args.project)
        slug = validate_slug(args.slug)
    except ValueError as error:
        return fail(str(error))
    with mutation_lock(config):
        index = NoteIndex.load(config)
        running = index.running_for_project(project)
        if running and not args.force:
            names = ", ".join(item.stem for item in running)
            return fail(
                f"{project} already has a running session: {names}. "
                "Close it first or pass --force."
            )
        stem = f"{date.today().isoformat()}-{slug}"
        path = config.sessions / f"{stem}.md"
        if path.exists():
            return fail(f"session already exists: {path}")
        title = args.title or slug.replace("-", " ").title()
        atomic_write(path, session_template(project, title))
        add_running(config, stem)
        add_to_project(config, project, stem)
        touch_project(config, project)
    print(path)
    if args.no_build:
        return 0
    return _build(config)


def _resolve_or_fail(config: Config, name: str) -> tuple[Path | None, int]:
    match, candidates = find_session(config, name)
    if match is not None:
        return match.path, 0
    if candidates:
        print(f"ambiguous session name: {name}", file=sys.stderr)
        for candidate in candidates:
            print(f"  {candidate.stem}", file=sys.stderr)
        return None, 1
    return None, fail(f"session not found: {name}")


def close(args: argparse.Namespace) -> int:
    config = _config(args)
    path, code = _resolve_or_fail(config, args.name)
    if path is None:
        return code
    text = path.read_text(encoding="utf-8")
    issues = strict_issues(text)
    if issues and not args.force:
        print("refusing to close an incomplete session:", file=sys.stderr)
        for issue in issues:
            print(f"  {issue}", file=sys.stderr)
        print("Pass --force to close anyway.", file=sys.stderr)
        return 1
    with mutation_lock(config):
        text = set_frontmatter_value(text, "status", "done")
        text = set_frontmatter_value(text, "updated", date.today().isoformat())
        atomic_write(path, text)
        close_running(config, path.stem)
        index = NoteIndex.load(config)
        session = index.session(path.stem)
        project = session.project if session else ""
        if project:
            add_to_project(config, project, path.stem)
            touch_project(config, project)
    print(path)
    if args.no_build:
        return 0
    return _build(config)


def abandon(args: argparse.Namespace) -> int:
    config = _config(args)
    path, code = _resolve_or_fail(config, args.name)
    if path is None:
        return code
    with mutation_lock(config):
        text = path.read_text(encoding="utf-8")
        text = set_frontmatter_value(text, "status", "abandoned")
        text = set_frontmatter_value(text, "updated", date.today().isoformat())
        atomic_write(path, text)
        close_running(config, path.stem, label="abandoned")
        index = NoteIndex.load(config)
        session = index.session(path.stem)
        if session and session.project:
            add_to_project(config, session.project, path.stem)
            touch_project(config, session.project)
    print(path)
    if args.no_build:
        return 0
    return _build(config)


def _watcher_state(config: Config) -> dict:
    if not config.pid_file.is_file():
        return {"running": False, "pid": None}
    try:
        pid = int(config.pid_file.read_text().strip())
        os.kill(pid, 0)
    except (ValueError, OSError):
        return {"running": False, "pid": None}
    return {"running": True, "pid": pid}


def _stale(index: NoteIndex) -> list[dict]:
    today = date.today()
    stale = []
    for session in index.sessions:
        if not session.running or not session.date:
            continue
        try:
            started = datetime.strptime(session.date, "%Y-%m-%d").date()
        except ValueError:
            continue
        age = (today - started).days
        if age > checker.STALE_DAYS:
            stale.append({"stem": session.stem, "project": session.project, "days": age})
    return stale


def status(args: argparse.Namespace) -> int:
    config = _config(args)
    index = NoteIndex.load(config)
    running = [
        {"stem": session.stem, "project": session.project, "date": session.date}
        for session in index.running()
    ]
    stale = _stale(index)
    watcher_state = _watcher_state(config)
    check_result = checker.check(config)
    payload = {
        "vault": str(config.vault),
        "view": str(config.view),
        "home": str(config.home),
        "running": running,
        "stale": stale,
        "watcher": watcher_state,
        "check": check_result.as_dict(),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if check_result.ok else 1
    print(f"vault:   {config.vault}")
    print(f"view:    {config.view}")
    print(f"home:    {config.home}")
    if running:
        print("running:")
        for item in running:
            print(f"  {item['stem']} ({item['project'] or 'unassigned'})")
    else:
        print("running: none")
    if stale:
        print("stale:")
        for item in stale:
            print(f"  {item['stem']} ({item['days']} days)")
    if watcher_state["running"]:
        print(f"watcher: running (pid {watcher_state['pid']})")
    else:
        print("watcher: not running")
    print(f"check: {len(check_result.errors)} errors, {len(check_result.warnings)} warnings")
    for message in check_result.errors:
        print(f"  ERROR {message}")
    for message in check_result.warnings:
        print(f"  WARN  {message}")
    return 0 if check_result.ok else 1


def check(args: argparse.Namespace) -> int:
    config = _config(args)
    result = checker.check(config, fix=args.fix)
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
        return 0 if result.ok else 1
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


def fix(args: argparse.Namespace) -> int:
    config = _config(args)
    result = checker.check(config, fix=True)
    for message in result.fixed:
        print(f"FIXED {message}")
    for message in result.errors:
        print(f"ERROR {message}")
    for message in result.warnings:
        print(f"WARN  {message}")
    if not result.ok:
        return 1
    if args.no_build:
        return 0
    return _build(config)


def build(args: argparse.Namespace) -> int:
    config = _config(args)
    return _build(config, compact=args.compact, home=not args.no_home)


def watch(args: argparse.Namespace) -> int:
    return watcher.run(_config(args), once=args.once)


def doctor(args: argparse.Namespace) -> int:
    config = _config(args)
    index = NoteIndex.load(config)
    problems = []
    for name in checker.NOTE_DIRS:
        if not (config.vault / name).is_dir():
            problems.append(f"missing {name}/")
    if not config.view.is_file():
        problems.append(f"missing view: {config.view}")
    if not (config.vault / ".git").is_dir():
        problems.append("vault is not a git repository")
    watcher_state = _watcher_state(config)
    if not watcher_state["running"]:
        problems.append("watcher is not running")
    print(f"vault:   {config.vault}")
    print(f"view:    {config.view}")
    print(f"home:    {config.home}")
    print(f"state:   {config.state}")
    print(f"notes:   {len(index.notes)}")
    print(f"sessions:{len(index.sessions)}")
    print(f"watcher: {'running (pid ' + str(watcher_state['pid']) + ')' if watcher_state['running'] else 'not running'}")
    if problems:
        for problem in problems:
            print(f"WARN  {problem}")
        return 1
    print("doctor: ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="work-graph", description=__doc__)
    parser.add_argument("--vault", type=Path, help="vault root (default: $WORK_GRAPH_VAULT)")
    parser.add_argument("--view", type=Path, help="full view path (default: $WORK_GRAPH_VIEW)")
    parser.add_argument("--state", type=Path, help="state directory (default: $WORK_GRAPH_STATE)")
    parser.add_argument("--home", type=Path, help="compact home path (default: $WORK_GRAPH_HOME)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="create a running session")
    start_parser.add_argument("slug")
    start_parser.add_argument("--project", required=True)
    start_parser.add_argument("--title")
    start_parser.add_argument("--force", action="store_true", help="allow a second running session")
    start_parser.add_argument("--no-build", action="store_true")
    start_parser.set_defaults(func=start)

    close_parser = subparsers.add_parser("close", help="close a session")
    close_parser.add_argument("name")
    close_parser.add_argument("--force", action="store_true", help="close despite placeholders")
    close_parser.add_argument("--no-build", action="store_true")
    close_parser.set_defaults(func=close)

    abandon_parser = subparsers.add_parser("abandon", help="mark a session abandoned")
    abandon_parser.add_argument("name")
    abandon_parser.add_argument("--no-build", action="store_true")
    abandon_parser.set_defaults(func=abandon)

    status_parser = subparsers.add_parser("status", help="show running state")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=status)

    check_parser = subparsers.add_parser("check", help="validate the vault")
    check_parser.add_argument("--fix", action="store_true")
    check_parser.add_argument("--json", action="store_true")
    check_parser.add_argument("--portable", action="store_true")
    check_parser.set_defaults(func=check)

    fix_parser = subparsers.add_parser("fix", help="apply safe repairs and rebuild")
    fix_parser.add_argument("--no-build", action="store_true")
    fix_parser.set_defaults(func=fix)

    build_parser = subparsers.add_parser("build", help="rebuild the generated views")
    build_parser.add_argument("--compact", action="store_true")
    build_parser.add_argument("--no-home", action="store_true")
    build_parser.set_defaults(func=build)

    watch_parser = subparsers.add_parser("watcher", help="run the file watcher")
    watch_parser.add_argument("--once", action="store_true")
    watch_parser.set_defaults(func=watch)

    doctor_parser = subparsers.add_parser("doctor", help="check the local installation")
    doctor_parser.set_defaults(func=doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
