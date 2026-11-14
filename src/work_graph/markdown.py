"""Markdown helpers that respect fenced code blocks."""

from __future__ import annotations

import re

FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
QUESTION_RE = re.compile(r"^\s*- \[ \]\s*(.+)$")
PLACEHOLDER_RE = re.compile(r"^_(?:What|How) .+_$|^Pending\.$", re.MULTILINE)

CASE_STUDY = "## Case Study"
CASE_STUDY_BLOCK = (
    CASE_STUDY,
    "",
    "Problem: _What problem does this note address?_",
    "",
    "Approach: _How was it approached?_",
    "",
    "Challenges: _What made it hard?_",
    "",
    "Result: _What changed or what was learned?_",
)


def fenced_flags(lines: list[str]) -> list[bool]:
    flags: list[bool] = []
    in_fence = False
    marker = ""
    for line in lines:
        match = FENCE_RE.match(line)
        if match:
            current = match.group(1)[0]
            if not in_fence:
                in_fence = True
                marker = current
            elif current == marker:
                in_fence = False
                marker = ""
            flags.append(True)
        else:
            flags.append(in_fence)
    return flags


def has_heading(text: str, heading: str) -> bool:
    lines = text.splitlines()
    return any(
        line.strip() == heading
        for line, fenced in zip(lines, fenced_flags(lines))
        if not fenced
    )


def insert_case_study(text: str) -> str:
    from .frontmatter import split_frontmatter

    body, frontmatter = split_frontmatter(text)
    body = body.lstrip("\n")
    prefix = f"---\n{frontmatter}\n---\n\n" if frontmatter else ""
    lines = body.splitlines()
    flags = fenced_flags(lines)
    insert_at = len(lines)
    title_seen = False
    for index, (line, fenced) in enumerate(zip(lines, flags)):
        if fenced:
            continue
        if not title_seen and line.startswith("# "):
            title_seen = True
            continue
        if title_seen and line.startswith("## "):
            insert_at = index
            break
    before = lines[:insert_at]
    after = lines[insert_at:]
    if before and before[-1].strip():
        before.append("")
    result = before + list(CASE_STUDY_BLOCK) + [""] + after
    return prefix + "\n".join(result).rstrip() + "\n"


def placeholders(text: str) -> list[str]:
    return sorted(set(PLACEHOLDER_RE.findall(text)))


def strip_anchor(target: str) -> str:
    return target.split("#", 1)[0].strip()
