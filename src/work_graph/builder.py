"""Build Logseq and Obsidian-friendly views from a work-graph vault."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

from .config import Config
from .frontmatter import project_stem, split_frontmatter
from .markdown import fenced_flags, question_items
from .store import NoteIndex, SessionInfo, atomic_write, atomic_write_if_changed

FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
HOME_QUESTION_LIMIT = 20


def first_heading(text: str) -> str:
    lines = text.splitlines()
    for line, fenced in zip(lines, fenced_flags(lines)):
        if not fenced and line.startswith("# "):
            return line[2:].strip()
    return ""


def strip_first_heading(text: str, title: str) -> str:
    lines = text.splitlines()
    flags = fenced_flags(lines)
    for index, line in enumerate(lines):
        if not flags[index] and line.strip() == f"# {title}":
            del lines[index]
            break
    return "\n".join(lines).strip()


def demote_headings(text: str, levels: int = 2) -> str:
    lines = text.splitlines()
    flags = fenced_flags(lines)
    output = []
    for line, fenced in zip(lines, flags):
        if fenced:
            output.append(line)
            continue
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            hashes = min(6, len(match.group(1)) + levels)
            line = f"{'#' * hashes} {match.group(2)}"
        output.append(line)
    return "\n".join(output)


def rewrite_wikilinks(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        target = match.group(1)
        alias = match.group(2)
        return alias or target

    lines = text.splitlines()
    flags = fenced_flags(lines)
    output = []
    for line, fenced in zip(lines, flags):
        if fenced:
            output.append(line)
        else:
            output.append(re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", replace, line))
    return "\n".join(output)


def tidy(text: str) -> str:
    lines = text.splitlines()
    flags = fenced_flags(lines)
    output = []
    blank_run = 0
    for line, fenced in zip(lines, flags):
        if fenced:
            output.append(line)
            blank_run = 0
            continue
        if line.strip():
            output.append(line)
            blank_run = 0
        else:
            blank_run += 1
            if blank_run <= 1:
                output.append("")
    return "\n".join(output).strip()


def load_note(path: Path, raw: str | None = None) -> tuple[str, str, str]:
    raw = raw if raw is not None else path.read_text(encoding="utf-8")
    body, frontmatter = split_frontmatter(raw)
    title = first_heading(body) or path.stem
    body = strip_first_heading(body, title)
    body = rewrite_wikilinks(body)
    body = demote_headings(body, 2)
    return title, frontmatter, body


def frontmatter_value(frontmatter: str, key: str) -> str:
    for line in frontmatter.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def section(kind: str, path: Path, historical: bool = False, raw: str | None = None) -> str:
    title, frontmatter, body = load_note(path, raw)
    status = frontmatter_value(frontmatter, "status")
    date = frontmatter_value(frontmatter, "date")
    updated = frontmatter_value(frontmatter, "updated")
    project = project_stem(frontmatter_value(frontmatter, "project"))
    meta = []
    if status:
        meta.append(f"Status: `{status}`")
    if date:
        meta.append(f"Date: `{date}`")
    if updated:
        meta.append(f"Updated: `{updated}`")
    if project:
        meta.append(f"Project: #project/{project}")
    meta_line = " | ".join(meta)
    parts = [f"### {title}", "", f"Tags: #{kind}/{path.stem}"]
    if meta_line:
        parts.append(meta_line)
    if historical:
        parts.append("")
        parts.append("> Historical session record. Current state lives in the project MOC.")
    parts.extend(["", tidy(body), ""])
    return "\n".join(parts)


def project_session_table(index: NoteIndex) -> str:
    if not index.projects and not index.sessions:
        return "No projects or sessions yet."
    mapping: dict[str, list[SessionInfo]] = {}
    for session in index.sessions:
        mapping.setdefault(session.project or "unassigned", []).append(session)
    rows = ["| Project | Sessions |", "| --- | --- |"]
    for path in index.projects:
        names = [session.stem for session in mapping.pop(path.stem, [])]
        rows.append(f"| {path.stem} | {', '.join(names) if names else 'None'} |")
    for project, sessions in sorted(mapping.items()):
        rows.append(f"| {project} | {', '.join(session.stem for session in sessions)} |")
    return "\n".join(rows)


def mermaid_label(text: str) -> str:
    return text.replace('"', "'").replace("[", "(").replace("]", ")")


def mermaid_graph(index: NoteIndex) -> str:
    lines = ["```mermaid", "graph TD", "  K[Work Graph Knowledge]"]
    project_positions = {path.stem: position for position, path in enumerate(index.projects)}
    for position, path in enumerate(index.projects):
        lines.append(f'  P{position}["{mermaid_label(path.stem)}"]')
        lines.append(f"  K --> P{position}")
    for position, session in enumerate(index.sessions):
        lines.append(f'  S{position}["{mermaid_label(session.stem)}"]')
        project_index = project_positions.get(session.project)
        if project_index is None:
            lines.append(f"  K --> S{position}")
        else:
            lines.append(f"  P{project_index} --> S{position}")
    lines.append("```")
    return "\n".join(lines)


def count_chart(index: NoteIndex) -> str:
    if not index.sessions:
        return "No sessions yet."
    counts = Counter(session.project or "unassigned" for session in index.sessions)
    rows = ["| Project | Sessions | Count |", "| --- | ---: | --- |"]
    for project, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        rows.append(f"| {project} | {count} | {'█' * count} |")
    return "\n".join(rows)


def timeline(index: NoteIndex) -> str:
    if not index.sessions:
        return "No sessions yet."
    rows = ["| Date | Session | Status | Project |", "| --- | --- | --- | --- |"]
    entries = [
        (session.date or "unknown", session.stem, session.status or "unknown", session.project or "unassigned")
        for session in index.sessions
    ]
    known = sorted((entry for entry in entries if entry[0] != "unknown"), reverse=True)
    unknown = sorted(entry for entry in entries if entry[0] == "unknown")
    for date_value, stem, status, project in known + unknown:
        rows.append(f"| {date_value} | {stem} | {status} | {project} |")
    return "\n".join(rows)


def question_lines(index: NoteIndex) -> list[str]:
    questions: OrderedDict[str, str] = OrderedDict()
    for path in index.notes:
        body = index.body(path)
        relative = index.config.relative(path)
        page = relative[:-3] if relative.endswith(".md") else relative
        for text in question_items(body):
            key = re.sub(r"\s+", " ", text).lower()
            if key not in questions:
                questions[key] = f"- [[{page}]]: {text}"
    return list(questions.values())


def open_questions(index: NoteIndex, limit: int | None = None) -> str:
    lines = question_lines(index)
    if not lines:
        return "No open questions recorded."
    if limit is not None and len(lines) > limit:
        remaining = len(lines) - limit
        lines = lines[:limit] + [f"- ... {remaining} more in [[Open Questions]]"]
    return "\n".join(lines)


def load_validation(path: Path | None) -> list[str]:
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    errors = payload.get("errors", []) if isinstance(payload, dict) else []
    return [str(item).strip() for item in errors if str(item).strip()]


def validation_banner(errors: list[str]) -> list[str]:
    lines = [
        "## Validation",
        "",
        f"> {len(errors)} validation error(s) at build time. The graph was rebuilt;",
        "> fix these notes to clear this banner.",
        "",
    ]
    for message in errors[:20]:
        lines.append(f"- {message}")
    if len(errors) > 20:
        lines.append(f"- ... and {len(errors) - 20} more; see watcher.log")
    lines.append("")
    return lines


def generated_stamp(index: NoteIndex) -> str:
    """Use the newest source mtime so an unchanged vault rebuilds byte-identically."""
    latest = max((path.stat().st_mtime for path in index.notes), default=None)
    moment = datetime.fromtimestamp(latest) if latest is not None else datetime.now()
    return moment.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def dashboard(
    index: NoteIndex,
    config: Config,
    generated: str,
    validation_errors: list[str] | None = None,
) -> str:
    running = [session for session in index.sessions if session.running]
    recent = sorted(
        index.sessions,
        key=lambda session: (session.date or "", session.stem),
        reverse=True,
    )[:30]
    by_project: dict[str, list[SessionInfo]] = {}
    for session in index.sessions:
        by_project.setdefault(session.project, []).append(session)
    projects = []
    for path in index.projects:
        owned = by_project.get(path.stem, [])
        latest = max(owned, key=lambda session: session.date or "", default=None)
        projects.append((path, len(owned), latest))

    parts = [
        "---",
        "title: Work Graph Home",
        "tags: [knowledge-graph, work-graph, home]",
        "---",
        "",
        "# Work Graph Home",
        "",
        f"Source updated {generated}. Rebuilt from `{config.vault}`.",
        "",
        f"- Projects: **{len(index.projects)}**",
        f"- Sessions: **{len(index.sessions)}**",
        f"- Running: **{len(running)}**",
        f"- Open questions: [[Open Questions]]",
        "",
    ]
    if validation_errors:
        parts.extend(
            [
                "## Validation",
                "",
                f"> {len(validation_errors)} error(s) at build time. See the watcher log.",
                "",
            ]
        )
    parts.extend(
        [
            "## Running",
            "",
        ]
    )
    if running:
        parts.extend(["| Session | Project | Since |", "| --- | --- | --- |"])
        for session in running:
            parts.append(
                f"| [[Sessions/{session.stem}]] | [[Projects/{session.project}]] | {session.date or '?'} |"
            )
    else:
        parts.append("No running sessions.")
    parts.extend(["", "## Projects", "", "| Project | Sessions | Latest |", "| --- | ---: | --- |"])
    for path, count, latest in projects:
        latest_link = f"[[Sessions/{latest.stem}]]" if latest else "None"
        parts.append(f"| [[Projects/{path.stem}]] | {count} | {latest_link} |")
    parts.extend(["", "## Recent sessions", "", "| Date | Session | Status | Project |", "| --- | --- | --- | --- |"])
    for session in recent:
        parts.append(
            f"| {session.date or '?'} | [[Sessions/{session.stem}]] | {session.status or '?'} | "
            f"[[Projects/{session.project}]] |"
        )
    parts.extend(
        [
            "",
            "## Open questions",
            "",
            open_questions(index, limit=HOME_QUESTION_LIMIT),
            "",
        ]
    )
    parts.extend(
        [
            "## Decisions",
            "",
            "\n".join(f"- [[Decisions/{path.stem}]]" for path in sorted((config.vault / "Decisions").glob("*.md")))
            or "No decisions recorded.",
            "",
            "## Maps",
            "",
            "\n".join(f"- [[Maps/{path.stem}]]" for path in sorted((config.vault / "Maps").glob("*.md")))
            or "No maps recorded.",
            "",
        ]
    )
    return tidy("\n".join(parts)) + "\n"


def questions_page(index: NoteIndex, generated: str) -> str:
    lines = question_lines(index)
    body = "\n".join(lines) if lines else "No open questions recorded."
    parts = [
        "---",
        "title: Open Questions",
        "tags: [knowledge-graph, work-graph, questions]",
        "---",
        "",
        "# Open Questions",
        "",
        f"Source updated {generated}. Rebuilt from `{index.config.vault}`. Open the linked page to answer one.",
        "",
        body,
        "",
    ]
    return tidy("\n".join(parts)) + "\n"


def build(
    config: Config,
    *,
    validation_path: Path | None = None,
    compact: bool = False,
    home: bool = True,
    archive: bool = False,
    index: NoteIndex | None = None,
) -> Path:
    index = index or NoteIndex.load(config)
    if not index.notes:
        raise FileNotFoundError(f"No notes found under {config.vault}")
    generated = generated_stamp(index)
    validation_errors = load_validation(validation_path)
    if not home and not archive:
        archive = True

    if compact:
        text = dashboard(index, config, generated, validation_errors)
        atomic_write_if_changed(config.view, text)
        if home and config.home != config.view:
            atomic_write_if_changed(config.home, text)
        if home:
            atomic_write_if_changed(config.questions_path, questions_page(index, generated))
        return config.view

    if archive:
        section_specs = [
            ("Projects", index.projects, "project", False),
            ("Decisions", sorted((config.vault / "Decisions").glob("*.md")), "decision", False),
            ("Sessions", [session.path for session in index.sessions], "session", True),
            ("Research", sorted((config.vault / "Research").glob("*.md")), "research", False),
            ("Agents", sorted((config.vault / "Agents").glob("*.md")), "agent", False),
            ("Maps", sorted((config.vault / "Maps").glob("*.md")), "map", False),
        ]
        parts = [
            "---",
            "title: Work Graph Knowledge",
            "tags: [knowledge-graph, work-graph]",
            "---",
            "",
            "# Work Graph Knowledge",
            "",
            f"Source updated {generated}. Generated from `{config.vault}`.",
            "",
            "Full-text archive export. Daily reading uses the individual pages and",
            "`Home.md`; regenerate this file with `work-graph build --archive`.",
            "",
            "## Knowledge Map",
            "",
            "The graph view uses the tags below as nodes. The Mermaid block renders when",
            "a Mermaid plugin is installed.",
            "",
            mermaid_graph(index),
            "",
            "## Session Count",
            "",
            count_chart(index),
            "",
            "## Project Sessions",
            "",
            project_session_table(index),
            "",
            "## Timeline",
            "",
            timeline(index),
            "",
        ]
        if validation_errors:
            marker = parts.index("## Knowledge Map")
            parts[marker:marker] = validation_banner(validation_errors)
        for heading, paths, kind, historical in section_specs:
            parts.extend([f"## {heading}", ""])
            if paths:
                parts.append(
                    "\n".join(
                        section(kind, path, historical=historical, raw=index.read(path))
                        for path in paths
                    )
                )
            else:
                parts.append("No notes yet.")
            parts.append("")
        parts.extend(
            [
                "## Open Questions",
                "",
                open_questions(index),
                "",
                "## Source Files",
                "",
                "\n".join(f"- `{config.relative(path)}`" for path in index.notes),
                "",
            ]
        )
        atomic_write_if_changed(config.view, tidy("\n".join(parts)) + "\n")

    if home:
        atomic_write_if_changed(
            config.home,
            dashboard(index, config, generated, validation_errors),
        )
        atomic_write_if_changed(config.questions_path, questions_page(index, generated))
        return config.home
    return config.view


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, help="JSON file with checker errors")
    parser.add_argument("--compact", action="store_true", help="write the dashboard instead of the full view")
    parser.add_argument("--archive", action="store_true", help="also write the full Knowledge.md archive")
    parser.add_argument("--no-home", action="store_true", help="do not write Home.md")
    args = parser.parse_args(argv)
    try:
        output = build(
            Config.from_env(),
            validation_path=args.validation,
            compact=args.compact,
            home=not args.no_home,
            archive=args.archive,
        )
    except FileNotFoundError as error:
        print(error, file=os.sys.stderr)
        return 1
    print(f"Wrote {output} ({output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
