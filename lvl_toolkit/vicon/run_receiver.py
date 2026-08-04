"""CLI entry point for app-sensor-desktop's "Plot last session" button.

Takes ONE session folder (the one the app hands it) and graphs it with the
default schema. Thin wrapper over :func:`lvl_toolkit.driver.plot_session` --
edit this file if you want a different schema for the button's output.

Usage: python run_receiver.py <session_dir>
Prints one output PNG path per line on success.
"""
import sys

from lvl_toolkit.driver import plot_session


def main():
    if len(sys.argv) < 2:
        print("usage: run_receiver.py <session_dir>", file=sys.stderr)
        sys.exit(1)

    for path in plot_session(sys.argv[1]):
        print(path)


if __name__ == "__main__":
    main()