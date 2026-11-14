"""Small, dependency-free YAML frontmatter helpers."""

from __future__ import annotations

import re

_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(body, frontmatter)``; frontmatter is empty when absent."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :], text[4:end]
    return text, ""


def frontmatter_value(frontmatter: str, key: str) -> str:
    for line in frontmatter.splitlines():
        match = _KEY_RE.match(line)
        if match and match.group(1) == key:
            return match.group(2).strip().strip('"').strip("'")
    return ""


def set_frontmatter_value(text: str, key: str, value: str) -> str:
    line = f"{key}: {value}"
    body, frontmatter = split_frontmatter(text)
    if frontmatter:
        lines = frontmatter.splitlines()
        for index, current in enumerate(lines):
            match = _KEY_RE.match(current)
            if match and match.group(1) == key:
                lines[index] = line
                break
        else:
            lines.append(line)
        return f"---\n{chr(10).join(lines)}\n---\n{body}"
    return f"---\n{line}\n---\n{body}"


def project_stem(value: str) -> str:
    value = value.strip().strip('"').strip("'")
    match = re.search(r"\[\[Projects/([^\]|#]+)", value)
    if match:
        return match.group(1).strip()
    if value.startswith("Projects/"):
        return value.removeprefix("Projects/").strip()
    return value.replace("[[", "").replace("]]", "").strip()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "session"


def validate_slug(value: str, label: str = "slug") -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label} cannot be empty")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"{label} cannot contain path separators: {value!r}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
        raise ValueError(
            f"{label} must use lowercase letters, digits, and hyphens: {value!r}"
        )
    return value


def is_agent_session(text: str) -> bool:
    _, frontmatter = split_frontmatter(text)
    return frontmatter_value(frontmatter, "type") == "agent-session"
