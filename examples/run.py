"""Load the bundled sample sessions and graph them out of the box.

Runs with no arguments against the two sessions shipped in this folder, or
against a session folder you pass on the command line::

    python examples/run.py                       # both bundled samples
    python examples/run.py path/to/some_session  # your own session folder

For each session it prints what the loader sees, then renders the figures the
default schema (:func:`lvl_toolkit.activity_map.figures_for`) asks for and writes
them to ``lvl_plots/`` -- the "download the app, run a collection, get graphs"
path, self-contained.

The two bundled samples cover both filename grammars the toolkit loads:

  - ``app_sensor_raw_3sensor/`` -- a real app-sensor capture (``imu-`` prefix,
    3 BT-IMU sensors: two feet + trunk). Raw only -> one ``raw_all`` figure.
  - ``app_gait_walk/``          -- a processed app-gait session (``accel_gyro-``
    prefix) with a GAIT_SEGMENTS overlay -> ``raw_all`` + ``feet`` + ``lumbar``.

Want a different set of figures? A schema is just a ``session -> list[FigureSpec]``
callable; write your own and pass it as ``schema=`` (see ``activity_map.py`` for a
worked example). The renderer, colors, and overlays are reused unchanged.
"""

import sys
from pathlib import Path

from lvl_toolkit import load_session
from lvl_toolkit.graphing import render_session, save_fig

HERE = Path(__file__).parent
BUNDLED = ["app_sensor_raw_3sensor", "app_gait_walk"]
OUTDIR = Path("lvl_plots")


def summarize(session) -> None:
    print(f"  activity_code   : {session.activity_code}")
    print(f"  source          : {session.source}")
    print(f"  sensors         : {session.sensor_labels()}")
    print("  files:")
    print(f"    {'MODALITY':16} {'LABEL':12} {'SENSOR':11}  NAME")
    for f in session.files:
        print(f"    {f.modality:16} {f.modality_label or '-':12} "
              f"{f.sensor_label or '':11}  {f.name}")


def graph(session) -> None:
    """Render the default-schema figures for a session and save one PNG each."""
    OUTDIR.mkdir(exist_ok=True)
    for spec, fig in render_session(session):        # schema=figures_for by default
        path = OUTDIR / f"{session.folder.name}__{spec.role}.png"
        save_fig(fig, path)
        print(f"  wrote {path}  ({spec.role})")


def main(argv) -> None:
    targets = [Path(a) for a in argv[1:]] or [HERE / name for name in BUNDLED]
    for folder in targets:
        # Header first, so a failure is clearly tied to its folder; then skip a
        # bad folder rather than crashing the whole run.
        print(f"\n=== {folder.name} ===")
        try:
            session = load_session(folder)
        except (FileNotFoundError, NotADirectoryError) as e:
            print(f"  skipped: {e}")
            continue
        summarize(session)
        graph(session)


if __name__ == "__main__":
    main(sys.argv)
