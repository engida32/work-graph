"""Allow ``python3 -m work_graph`` when the console script is not on PATH."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
