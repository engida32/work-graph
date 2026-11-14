"""Watch a work-graph vault and rebuild its generated views."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import builder, checker
from .config import Config
from .store import atomic_write, is_watcher_command

POLL_SECONDS = float(os.environ.get("WORK_GRAPH_POLL_SECONDS", "2.0"))
NOTIFY_COOLDOWN = 24 * 60 * 60
WATCH_DIRS = ("Projects", "Decisions", "Sessions", "Research", "Agents", "Maps")

running = True


def stop(*_args: object) -> None:
    global running
    running = False


def signature(config: Config) -> tuple[tuple[str, int, int], ...]:
    items = []
    for name in WATCH_DIRS:
        directory = config.vault / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name == "Active.md":
                continue
            stat = path.stat()
            items.append((str(path), stat.st_mtime_ns, stat.st_size))
    for path in (config.vault / "scripts" / "build-knowledge.py", config.vault / "scripts" / "check-work-graph.py"):
        if path.is_file():
            stat = path.stat()
            items.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(items)


def changes(previous, current) -> str:
    old = {path: (mtime, size) for path, mtime, size in previous}
    new = {path: (mtime, size) for path, mtime, size in current}
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    modified = sorted(path for path in old.keys() & new.keys() if old[path] != new[path])
    parts = []
    for label, paths in (("added", added), ("changed", modified), ("removed", removed)):
        if paths:
            parts.append(f"{label}: {', '.join(Path(path).name for path in paths)}")
    return "; ".join(parts)


def log(config: Config, message: str) -> None:
    config.state.mkdir(parents=True, exist_ok=True)
    if config.log_file.exists() and config.log_file.stat().st_size > 512_000:
        config.log_file.replace(config.log_file.with_suffix(".log.1"))
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with config.log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def notify(title: str, message: str) -> bool:
    binary = shutil.which("notify-send")
    if not binary:
        return False
    try:
        result = subprocess.run(
            [binary, "-a", "Work Graph", title, message],
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def shorten(text: str, limit: int = 180) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def write_json(path: Path, payload: object) -> None:
    atomic_write(path, json.dumps(payload, indent=2) + "\n")


def load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def clear_notification(config: Config, kind: str) -> None:
    path = config.state / "last-notify.json"
    state = load_json(path)
    if kind not in state:
        return
    state.pop(kind, None)
    if state:
        write_json(path, state)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def notify_failure(config: Config, kind: str, title: str, message: str, key: str) -> None:
    path = config.state / "last-notify.json"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    now = time.time()
    state = load_json(path)
    previous = state.get(kind, {})
    try:
        previous_time = float(previous.get("time", 0)) if isinstance(previous, dict) else 0.0
    except (TypeError, ValueError):
        previous_time = 0.0
    if (
        isinstance(previous, dict)
        and previous.get("hash") == digest
        and now - previous_time < NOTIFY_COOLDOWN
    ):
        log(config, f"notification suppressed for unchanged {kind} failure")
        return
    if not notify(title, message):
        log(config, f"notification not delivered for {kind} failure")
        return
    state[kind] = {"hash": digest, "time": now}
    write_json(path, state)


def snapshot(config: Config) -> None:
    if shutil.which("git") is None:
        log(config, "snapshot skipped: git not found")
        return
    if not (config.vault / ".git").is_dir():
        log(config, "snapshot skipped: vault is not a git repository")
        return
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    status = subprocess.run(
        ["git", "-C", str(config.vault), "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if status.returncode != 0:
        log(config, f"snapshot status failed: {status.stderr.strip()}")
        return
    if not status.stdout.strip():
        return
    add = subprocess.run(
        ["git", "-C", str(config.vault), "add", "-A"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if add.returncode != 0:
        log(config, f"snapshot add failed: {add.stderr.strip()}")
        return
    message = f"docs(work-graph): snapshot {time.strftime('%Y-%m-%d %H:%M:%S')}"
    commit = subprocess.run(
        ["git", "-C", str(config.vault), "commit", "-q", "-m", message],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if commit.returncode == 0:
        log(config, "snapshot committed")
    else:
        log(config, f"snapshot commit failed: {commit.stderr.strip()}")


def build(config: Config, reason: str = "") -> int:
    started = time.monotonic()
    if reason:
        log(config, reason)
    result = checker.check(config, fix=True)
    write_json(
        config.validation_file,
        {
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "errors": result.errors,
            "warnings": result.warnings,
            "fixed": result.fixed,
        },
    )
    for item in result.fixed:
        log(config, f"fixed: {item}")
    if result.errors:
        log(
            config,
            f"check failed: {len(result.errors)} error(s), "
            f"{len(result.warnings)} warning(s); building anyway",
        )
        detail = shorten(result.errors[0])
        if len(result.errors) > 1:
            detail += f" (+{len(result.errors) - 1} more)"
        notify_failure(config, "check", "Work graph validation failed", detail, "\n".join(result.errors))
    else:
        clear_notification(config, "check")

    try:
        output = builder.build(
            config,
            validation_path=config.validation_file,
            compact=os.environ.get("WORK_GRAPH_COMPACT") == "1",
        )
    except Exception as error:  # noqa: BLE001 - the watcher must keep running
        log(config, f"build failed: {error}")
        notify_failure(config, "build", "Work graph build failed", str(error), str(error))
        return 1
    elapsed = time.monotonic() - started
    log(config, f"wrote {output} ({output.stat().st_size} bytes) in {elapsed:.2f}s")
    clear_notification(config, "build")
    snapshot(config)
    return 0


def already_running(config: Config) -> bool:
    if not config.pid_file.exists():
        return False
    try:
        pid = int(config.pid_file.read_text().strip())
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text()
    except OSError:
        return False
    return is_watcher_command(cmdline)


def run(config: Config, *, once: bool = False) -> int:
    if once:
        return build(config, "manual build")
    if already_running(config):
        print(f"watcher already running: {config.pid_file.read_text().strip()}")
        return 0
    config.state.mkdir(parents=True, exist_ok=True)
    atomic_write(config.pid_file, f"{os.getpid()}\n")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log(config, "watcher started")
    last = signature(config)
    build(config, "initial build")
    try:
        while running:
            time.sleep(POLL_SECONDS)
            current = signature(config)
            if current != last:
                time.sleep(1.0)
                current = signature(config)
                build(config, changes(last, current))
                last = current
    finally:
        log(config, "watcher stopped")
        try:
            config.pid_file.unlink()
        except FileNotFoundError:
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="build once and exit")
    args = parser.parse_args(argv)
    return run(Config.from_env(), once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
