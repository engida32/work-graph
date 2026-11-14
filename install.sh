#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-}"
AGENTS_HOME="${AGENTS_HOME:-$HOME/.agents}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

INSTALL_PACKAGE=1
INSTALL_SKILL=0
UNINSTALL=0

info() { printf '%s\n' "$*"; }
die() { printf '[error] %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage: install.sh [options]

Options:
  --package     Install the Python package and the work-graph command (default).
  --hermes      Install the package and link the skill into ~/.agents and ~/.hermes.
  --all         Alias for --hermes.
  --uninstall   Remove the command and only the skill links this script created.
  -h, --help    Show this help.

Environment:
  PYTHON        Python interpreter with pip (default: first of python3, /usr/bin/python3)
  AGENTS_HOME   Shared skills root (default: ~/.agents)
  HERMES_HOME   Hermes home (default: ~/.hermes)
EOF
}

find_python() {
    local candidates=()
    if [ -n "$PYTHON" ]; then
        candidates+=("$PYTHON")
    fi
    candidates+=("python3" "/usr/bin/python3")
    local candidate
    for candidate in "${candidates[@]}"; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        if "$candidate" -m pip --version >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

install_package() {
    local python
    python="$(find_python)" || die "no Python with pip found; set PYTHON=/path/to/python"
    "$python" -m pip install --user --editable "$ROOT"
    info "Installed work-graph with $python. Run: work-graph doctor"
}

link_skill() {
    local source="$ROOT/skills/work-graph"
    local agents_link="$AGENTS_HOME/skills/work-graph"
    local hermes_link="$HERMES_HOME/skills/work-graph"
    local stamp
    stamp="$(date +%Y%m%d%H%M%S)"

    [ -f "$source/SKILL.md" ] || die "missing $source/SKILL.md"
    mkdir -p "$AGENTS_HOME/skills" "$HERMES_HOME/skills"

    if [ -e "$agents_link" ] && [ ! -L "$agents_link" ]; then
        mv "$agents_link" "$agents_link.bak.$stamp"
        info "Backed up existing $agents_link"
    fi
    ln -sfn "$source" "$agents_link"

    if [ -e "$hermes_link" ] && [ ! -L "$hermes_link" ]; then
        mv "$hermes_link" "$hermes_link.bak.$stamp"
        info "Backed up existing $hermes_link"
    fi
    ln -sfn "$agents_link" "$hermes_link"

    info "Linked skill: $hermes_link -> $agents_link"
    info "Restart Hermes or run 'hermes skills list' to confirm it loads."
}

uninstall_all() {
    local python
    python="$(find_python || true)"
    if [ -n "$python" ]; then
        "$python" -m pip uninstall -y work-graph >/dev/null 2>&1 || true
        info "Removed the work-graph Python package."
    fi

    local hermes_link="$HERMES_HOME/skills/work-graph"
    local agents_link="$AGENTS_HOME/skills/work-graph"
    if [ -L "$hermes_link" ]; then
        rm -f "$hermes_link"
        info "Removed $hermes_link"
    fi
    if [ -L "$agents_link" ]; then
        rm -f "$agents_link"
        info "Removed $agents_link"
    fi
    info "Kept any real (non-symlink) skill directories and all vault data."
}

while [ $# -gt 0 ]; do
    case "$1" in
        --package) INSTALL_PACKAGE=1; INSTALL_SKILL=0 ;;
        --hermes|--all) INSTALL_PACKAGE=1; INSTALL_SKILL=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
    shift
done

if [ "$UNINSTALL" -eq 1 ]; then
    uninstall_all
    exit 0
fi

if [ "$INSTALL_PACKAGE" -eq 1 ]; then
    install_package
fi
if [ "$INSTALL_SKILL" -eq 1 ]; then
    link_skill
fi
