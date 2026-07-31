"""CLI entry point for the desktop app's "Plot Session" button.

Usage: python plot_session.py <session_dir> [output_dir]
Prints one output PNG path per line on success.
"""
import sys
from pathlib import Path

from lvl_toolkit import load_session
from lvl_toolkit.graphing import save_session_figures


def main():
    if len(sys.argv) < 2:
        print("usage: plot_session.py <session_dir> [output_dir]", file=sys.stderr)
        sys.exit(1)

    session_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else session_dir / "plots"

    session = load_session(session_dir)
    paths = save_session_figures(session, output_dir)
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()