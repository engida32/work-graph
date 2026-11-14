from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path

from work_graph import builder, checker
from work_graph.cli import main
from work_graph.config import Config
from work_graph.frontmatter import (
    frontmatter_value,
    set_frontmatter_value,
    split_frontmatter,
    validate_slug,
)
from work_graph.store import (
    NoteIndex,
    atomic_write,
    find_session,
    session_template,
    strict_issues,
    validate_project,
)


PROJECT = """---
type: project
status: active
updated: 2026-01-01
---

# Test Project

## Case Study

Problem: test

## Sessions
"""

ACTIVE = """---
type: index
status: active
tags: [index, sessions]
---

# Sessions

## Running

No running sessions right now.

## Recently closed

No closed sessions yet.
"""


def make_vault(root: Path) -> Path:
    for name in ("Projects", "Sessions", "Decisions", "Research", "Agents", "Maps"):
        (root / name).mkdir(parents=True)
    (root / "Projects" / "test.md").write_text(PROJECT, encoding="utf-8")
    (root / "Sessions" / "Active.md").write_text(ACTIVE, encoding="utf-8")
    return root


def make_config(root: Path) -> Config:
    view = root.parent / "view" / "Knowledge.md"
    return Config(
        vault=root,
        view=view,
        state=root.parent / "state",
        home=view.with_name("Home.md"),
        autostart=root.parent / "autostart.desktop",
    )


def write_session(config: Config, stem: str, *, status: str = "running", project: str = "test", text: str | None = None) -> Path:
    path = config.sessions / f"{stem}.md"
    path.write_text(
        text
        or f"""---
type: agent-session
status: {status}
date: {date.today().isoformat()}
project: "[[Projects/{project}]]"
tags: [agent/session]
---

# {stem}

## Case Study

Problem: test
Approach: test
Challenges: test
Result: test

## Architecture

## Important Notes

## High-Level Plan

## Tech Stack and Reasons

## Outcome

Done.

## Evidence

Tests pass.
""",
        encoding="utf-8",
    )
    return path


def run_cli(config: Config, *args: str) -> tuple[int, str, str]:
    argv = [
        "--vault",
        str(config.vault),
        "--view",
        str(config.view),
        "--state",
        str(config.state),
        "--home",
        str(config.home),
        *args,
    ]
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class FrontmatterTests(unittest.TestCase):
    def test_set_and_read(self) -> None:
        text = "---\ntype: agent-session\n---\n\n# Title\n"
        updated = set_frontmatter_value(text, "status", "done")
        _, frontmatter = split_frontmatter(updated)
        self.assertEqual(frontmatter_value(frontmatter, "status"), "done")

    def test_project_name_validation(self) -> None:
        for bad in ("../evil", "Foo/Bar", "..", "UPPER", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_slug(bad, "project")


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_vault(Path(self.tmp.name) / "vault")
        self.config = make_config(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_active_is_never_a_session(self) -> None:
        match, candidates = find_session(self.config, "Active")
        self.assertIsNone(match)
        self.assertEqual(candidates, [])
        match, candidates = find_session(self.config, "Sessions/Active.md")
        self.assertIsNone(match)
        self.assertEqual(candidates, [])

    def test_ambiguous_session_returns_candidates(self) -> None:
        write_session(self.config, "2026-01-01-alpha")
        write_session(self.config, "2026-01-02-alpha-two")
        match, candidates = find_session(self.config, "alpha")
        self.assertIsNone(match)
        self.assertEqual(len(candidates), 2)

    def test_template_has_documented_sections(self) -> None:
        text = session_template("test", "Test")
        for heading in ("## Decisions", "## Open questions", "## Artifacts", "## Outcome", "## Evidence"):
            self.assertIn(heading, text)

    def test_strict_issues_detect_placeholders(self) -> None:
        issues = strict_issues(session_template("test", "Test"))
        self.assertTrue(any("Pending" in issue for issue in issues))
        self.assertTrue(any("placeholder" in issue for issue in issues))

    def test_atomic_write_leaves_no_temp_files(self) -> None:
        path = self.root / "Projects" / "atomic.md"
        atomic_write(path, "hello\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "hello\n")
        self.assertEqual(list(path.parent.glob(".atomic.md.*.tmp")), [])


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_vault(Path(self.tmp.name) / "vault")
        self.config = make_config(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_start_creates_session_and_enforces_one_running(self) -> None:
        code, out, _ = run_cli(self.config, "start", "first-task", "--project", "test", "--no-build")
        self.assertEqual(code, 0, out)
        sessions = list(self.config.sessions.glob("*-first-task.md"))
        self.assertEqual(len(sessions), 1)
        text = sessions[0].read_text(encoding="utf-8")
        self.assertIn("## Decisions", text)
        self.assertIn("## Open questions", text)
        self.assertIn("## Artifacts", text)
        active = self.config.active.read_text(encoding="utf-8")
        self.assertIn("[[Sessions/", active)

        code, _, err = run_cli(self.config, "start", "second-task", "--project", "test", "--no-build")
        self.assertEqual(code, 1)
        self.assertIn("already has a running session", err)

        code, _, _ = run_cli(
            self.config,
            "start",
            "second-task",
            "--project",
            "test",
            "--force",
            "--no-build",
        )
        self.assertEqual(code, 0)

    def test_start_rejects_path_traversal(self) -> None:
        code, _, err = run_cli(self.config, "start", "task", "--project", "../evil", "--no-build")
        self.assertEqual(code, 1)
        self.assertIn("path separators", err)

    def test_close_refuses_incomplete_and_force_closes(self) -> None:
        path = write_session(self.config, "2026-01-01-incomplete", text=session_template("test", "Incomplete"))
        code, _, err = run_cli(self.config, "close", "2026-01-01-incomplete", "--no-build")
        self.assertEqual(code, 1)
        self.assertIn("refusing to close", err)
        code, _, _ = run_cli(self.config, "close", "2026-01-01-incomplete", "--force", "--no-build")
        self.assertEqual(code, 0)
        text = path.read_text(encoding="utf-8")
        self.assertIn("status: done", text)
        active = self.config.active.read_text(encoding="utf-8")
        self.assertIn("[[Sessions/2026-01-01-incomplete]] done", active)

    def test_abandon_marks_status(self) -> None:
        path = write_session(self.config, "2026-01-01-abandoned")
        code, _, _ = run_cli(self.config, "abandon", "2026-01-01-abandoned", "--no-build")
        self.assertEqual(code, 0)
        self.assertIn("status: abandoned", path.read_text(encoding="utf-8"))


class CheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_vault(Path(self.tmp.name) / "vault")
        self.config = make_config(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fix_adds_missing_project_links(self) -> None:
        write_session(self.config, "2026-01-01-linked")
        result = checker.check(self.config, fix=True)
        project = (self.config.projects / "test.md").read_text(encoding="utf-8")
        self.assertIn("[[Sessions/2026-01-01-linked]]", project)
        self.assertTrue(any("session links" in item for item in result.fixed))

    def test_duplicate_questions_and_stale_running_warn(self) -> None:
        old = (date.today() - timedelta(days=10)).isoformat()
        body = f"""---
type: agent-session
status: running
date: {old}
project: "[[Projects/test]]"
tags: [agent/session]
---

# Old

## Case Study

Problem: test

## Architecture

## Important Notes

## High-Level Plan

## Tech Stack and Reasons

## Outcome

Done.

## Evidence

Tests pass.

- [ ] Same question?
"""
        write_session(self.config, "2026-01-01-old-one", text=body)
        write_session(self.config, "2026-01-02-old-two", text=body)
        builder.build(self.config)
        result = checker.check(self.config)
        messages = "\n".join(result.warnings)
        self.assertIn("duplicate open question", messages)
        self.assertIn("has been running for", messages)

    def test_json_shape(self) -> None:
        builder.build(self.config)
        result = checker.check(self.config)
        payload = result.as_dict()
        self.assertIn("ok", payload)
        self.assertIn("counts", payload)
        self.assertEqual(payload["counts"]["errors"], len(result.errors))


class BuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_vault(Path(self.tmp.name) / "vault")
        self.config = make_config(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_writes_full_view_and_compact_home(self) -> None:
        write_session(self.config, "2026-01-01-built")
        output = builder.build(self.config)
        self.assertEqual(output, self.config.view)
        self.assertTrue(self.config.view.is_file())
        self.assertTrue(self.config.home.is_file())
        self.assertGreater(self.config.view.stat().st_size, 0)
        self.assertLess(self.config.home.stat().st_size, 50_000)

    def test_compact_build_is_small(self) -> None:
        write_session(self.config, "2026-01-01-compact")
        builder.build(self.config, compact=True)
        self.assertLess(self.config.view.stat().st_size, 50_000)
        text = self.config.view.read_text(encoding="utf-8")
        self.assertIn("# Work Graph Home", text)


if __name__ == "__main__":
    unittest.main()
