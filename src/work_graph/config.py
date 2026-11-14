"""Resolve vault, view, and state paths from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default.expanduser().resolve()


@dataclass(frozen=True)
class Config:
    vault: Path
    view: Path
    state: Path
    home: Path
    autostart: Path
    questions: Path | None = None

    @classmethod
    def from_env(cls) -> "Config":
        vault = _path("WORK_GRAPH_VAULT", Path.home() / "work-graph-source")
        view = _path("WORK_GRAPH_VIEW", Path.home() / "work-graph" / "Knowledge.md")
        state = _path(
            "WORK_GRAPH_STATE",
            Path.home() / ".local" / "state" / "work-graph-knowledge",
        )
        home = _path("WORK_GRAPH_HOME", vault / "Home.md")
        autostart = _path(
            "WORK_GRAPH_AUTOSTART",
            Path.home()
            / ".config"
            / "autostart"
            / "work-graph-knowledge.desktop",
        )
        questions = _path("WORK_GRAPH_QUESTIONS", vault / "Open Questions.md")
        return cls(
            vault=vault,
            view=view,
            state=state,
            home=home,
            autostart=autostart,
            questions=questions,
        )

    @property
    def sessions(self) -> Path:
        return self.vault / "Sessions"

    @property
    def projects(self) -> Path:
        return self.vault / "Projects"

    @property
    def questions_path(self) -> Path:
        return self.questions or (self.vault / "Open Questions.md")

    @property
    def active(self) -> Path:
        return self.sessions / "Active.md"

    @property
    def pid_file(self) -> Path:
        return self.state / "watcher.pid"

    @property
    def log_file(self) -> Path:
        return self.state / "watcher.log"

    @property
    def validation_file(self) -> Path:
        return self.state / "validation.json"

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.vault))
        except ValueError:
            return str(path)
