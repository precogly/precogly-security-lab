"""Entry point for lab."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Run the application and return a process exit code."""
    args = sys.argv[1:] if argv is None else argv
    print("Hello from lab!")
    print(f"args: {args}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
