"""Vault reads, writes, session lookup, and mutation locking."""

from __future__ import annotations

import fcntl
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator

from .config import Config
from .frontmatter import (
    frontmatter_value,
    is_agent_session,
    project_stem,
    set_frontmatter_value,
    split_frontmatter,
    validate_slug,
)
from .markdown import CASE_STUDY, has_heading, placeholders

NOTE_DIRS = ("Projects", "Decisions", "Sessions", "Research", "Agents", "Maps")
REQUIRED_SESSION_HEADINGS = (
    CASE_STUDY,
    "## Architecture",
    "## Important Notes",
    "## High-Level Plan",
    "## Tech Stack and Reasons",
    "## Outcome",
    "## Evidence",
)


def atomic_write(path: Path, text: str, *, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.is_file():
        backup_path = path.with_name(f"{path.name}.bak")
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    descriptor, name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_if_changed(path: Path, text: str) -> bool:
    """Write text only when the file content differs. Returns True on write."""
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass
    atomic_write(path, text)
    return True


def is_watcher_command(cmdline: str) -> bool:
    text = cmdline.replace("\0", " ")
    return (
        "watch-knowledge" in text
        or "work_graph.watcher" in text
        or ("work-graph" in text and "watcher" in text)
    )


@contextmanager
def mutation_lock(config: Config) -> Iterator[None]:
    """Serialize mutations across concurrent agent sessions."""
    config.state.mkdir(parents=True, exist_ok=True)
    lock_path = config.state / "work-graph.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class SessionInfo:
    path: Path
    stem: str
    text: str
    frontmatter: str
    status: str
    project: str
    date: str

    @property
    def running(self) -> bool:
        return self.status == "running"


@dataclass
class NoteIndex:
    config: Config
    sessions: list[SessionInfo] = field(default_factory=list)
    projects: list[Path] = field(default_factory=list)
    notes: list[Path] = field(default_factory=list)
    _text_cache: dict[Path, str] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, config: Config) -> "NoteIndex":
        index = cls(config=config)
        index.projects = sorted(
            path for path in config.projects.glob("*.md") if path.is_file()
        )
        if config.sessions.is_dir():
            for path in sorted(config.sessions.glob("*.md")):
                if path.name == "Active.md":
                    continue
                text = path.read_text(encoding="utf-8")
                if not is_agent_session(text):
                    continue
                _, frontmatter = split_frontmatter(text)
                index._text_cache[path] = text
                index.sessions.append(
                    SessionInfo(
                        path=path,
                        stem=path.stem,
                        text=text,
                        frontmatter=frontmatter,
                        status=frontmatter_value(frontmatter, "status"),
                        project=project_stem(frontmatter_value(frontmatter, "project")),
                        date=frontmatter_value(frontmatter, "date"),
                    )
                )
        for name in NOTE_DIRS:
            directory = config.vault / name
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                if path.name == "Active.md":
                    continue
                index.notes.append(path)
        return index

    def read(self, path: Path) -> str:
        """Return a note body once per index; reuse it across checks and builds."""
        try:
            return self._text_cache[path]
        except KeyError:
            text = path.read_text(encoding="utf-8")
            self._text_cache[path] = text
            return text

    def body(self, path: Path) -> str:
        return split_frontmatter(self.read(path))[0]

    def session(self, stem: str) -> SessionInfo | None:
        return next((item for item in self.sessions if item.stem == stem), None)

    def running(self) -> list[SessionInfo]:
        return [item for item in self.sessions if item.running]

    def running_for_project(self, project: str) -> list[SessionInfo]:
        return [item for item in self.sessions if item.running and item.project == project]


def find_session(
    config: Config, name: str
) -> tuple[SessionInfo | None, list[SessionInfo]]:
    """Resolve a session name. Returns ``(match, candidates)``.

    ``Sessions/Active.md`` is never a session. When more than one note matches,
    the caller gets the candidates instead of a misleading "not found".
    """
    index = NoteIndex.load(config)
    cleaned = name.strip()
    if cleaned.endswith(".md"):
        cleaned = cleaned[:-3]
    if cleaned in {"", "Active", "Sessions/Active"}:
        return None, []
    direct = index.session(cleaned)
    if direct is not None:
        return direct, []
    if "/" in cleaned:
        cleaned = cleaned.rsplit("/", 1)[-1]
    matches = [item for item in index.sessions if cleaned.lower() in item.stem.lower()]
    if len(matches) == 1:
        return matches[0], []
    return None, matches


def read_active(config: Config) -> tuple[str, str, str]:
    path = config.active
    if not path.is_file():
        return "", "No running sessions right now.", "No closed sessions yet."
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"(## Running\n)(.*?)(\n## Recently closed\n)(.*)", re.S)
    match = pattern.search(text)
    if not match:
        raise ValueError("Active.md is missing the Running or Recently closed section")
    return text[: match.start()], match.group(2).strip(), match.group(4).strip()


def write_active(config: Config, prefix: str, running: str, closed: str) -> None:
    body = (
        f"{prefix}## Running\n\n{running.strip()}\n\n"
        f"## Recently closed\n\n{closed.strip()}\n"
    )
    atomic_write(config.active, body)


def add_running(config: Config, stem: str) -> None:
    prefix, running, closed = read_active(config)
    link = f"[[Sessions/{stem}]]"
    running_lines = [line for line in running.splitlines() if link not in line]
    closed_lines = [line for line in closed.splitlines() if link not in line]
    running_text = "\n".join(running_lines).strip()
    if not running_text or running_text == "No running sessions right now.":
        running_text = f"- {link} running"
    else:
        running_text += f"\n- {link} running"
    write_active(config, prefix, running_text, "\n".join(closed_lines))


def close_running(config: Config, stem: str, label: str = "done") -> None:
    prefix, running, closed = read_active(config)
    link = f"[[Sessions/{stem}]]"
    running_lines = [line for line in running.splitlines() if link not in line]
    closed_lines = [
        line
        for line in closed.splitlines()
        if link not in line and line.strip() != "No closed sessions yet."
    ]
    running_text = "\n".join(running_lines).strip() or "No running sessions right now."
    closed_lines.insert(0, f"- {link} {label}")
    write_active(config, prefix, running_text, "\n".join(closed_lines))


def add_to_project(config: Config, project: str, stem: str) -> None:
    path = config.projects / f"{project}.md"
    text = path.read_text(encoding="utf-8")
    link = f"- [[Sessions/{stem}]]"
    if link in text:
        return
    if "## Sessions" not in text:
        text = text.rstrip() + f"\n\n## Sessions\n\n{link}\n"
    else:
        before, rest = text.split("## Sessions", 1)
        index = rest.find("\n## ")
        if index == -1:
            text = before + "## Sessions" + rest.rstrip() + f"\n\n{link}\n"
        else:
            section = rest[:index].rstrip()
            after = rest[index:]
            text = before + "## Sessions" + section + f"\n\n{link}\n" + after
    atomic_write(path, text)


def touch_project(config: Config, project: str) -> None:
    path = config.projects / f"{project}.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    atomic_write(path, set_frontmatter_value(text, "updated", date.today().isoformat()))


def validate_project(config: Config, project: str) -> str:
    project = validate_slug(project, "project")
    if not (config.projects / f"{project}.md").is_file():
        raise ValueError(f"project MOC not found: {config.projects / (project + '.md')}")
    return project


def session_template(project: str, title: str) -> str:
    return "\n".join(
        [
            "---",
            "type: agent-session",
            "status: running",
            f"date: {date.today().isoformat()}",
            f'project: "[[Projects/{project}]]"',
            "tags: [agent/session]",
            "---",
            "",
            f"# {title}",
            "",
            "## Case Study",
            "",
            "Problem: _What problem does this session address?_",
            "",
            "Approach: _How was it approached?_",
            "",
            "Challenges: _What made it hard?_",
            "",
            "Result: _What changed or what was learned?_",
            "",
            "## Architecture",
            "",
            "## Important Notes",
            "",
            "## High-Level Plan",
            "",
            "## Tech Stack and Reasons",
            "",
            "## Decisions",
            "",
            "## Open questions",
            "",
            "## Artifacts",
            "",
            "## Outcome",
            "",
            "Pending.",
            "",
            "## Evidence",
            "",
            "Pending.",
            "",
        ]
    )


def strict_issues(text: str) -> list[str]:
    issues = []
    for heading in REQUIRED_SESSION_HEADINGS:
        if not has_heading(text, heading):
            issues.append(f"missing {heading}")
    if "Pending." in text:
        issues.append("Outcome or Evidence still says Pending.")
    for placeholder in placeholders(text):
        issues.append(f"placeholder still present: {placeholder}")
    return issues
