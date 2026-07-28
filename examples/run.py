"""Load the bundled sample sessions and print what lvl-toolkit sees.

Runs with no arguments against the two sessions shipped in this folder, or
against a session folder you pass on the command line::

    python examples/run.py                       # both bundled samples
    python examples/run.py path/to/some_session  # your own session folder

The two bundled samples cover both filename grammars the toolkit loads:

  - ``app_sensor_raw_3sensor/`` -- a real app-sensor capture (``imu-`` prefix,
    3 BT-IMU sensors: two feet + trunk). Modality ACCEL_GYRO / label RAW.
  - ``app_gait_walk/``          -- a processed app-gait session (``accel_gyro-``
    prefix) with a GAIT_SEGMENTS overlay file. (Minimal synthetic sample.)

If matplotlib is installed, each IMU stream is also drawn with the basic
``plot()`` below and saved to ``lvl_plots/``. That plot is a generic placeholder
-- a real plotting layer (figure selection, overlays, styling) is coming
separately; this just shows the loader handing data straight to a plot call.
"""

import sys
from pathlib import Path

from lvl_toolkit import load_session

HERE = Path(__file__).parent
BUNDLED = ["app_sensor_raw_3sensor", "app_gait_walk"]


def plot(imu):
    """Very basic time-series plot of one IMU file: accel + gyro vs time.

    ``imu`` is a ``LoadedFile`` (``imu.data`` is a pandas DataFrame with the
    columns ``time, accel_x/y/z, gyro_x/y/z``). Returns a matplotlib Figure.
    Deliberately generic and un-styled -- a placeholder for the real plotting
    layer.
    """
    import matplotlib.pyplot as plt

    df = imu.data
    t = (df["time"] - df["time"].iloc[0]) / 1e6          # microseconds -> seconds
    fig, (ax_a, ax_g) = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
    for axis in ("x", "y", "z"):
        ax_a.plot(t, df[f"accel_{axis}"], label=f"accel_{axis}", linewidth=0.8)
        ax_g.plot(t, df[f"gyro_{axis}"], label=f"gyro_{axis}", linewidth=0.8)
    ax_a.set_ylabel("accel (m/s^2)")
    ax_g.set_ylabel("gyro (rad/s)")
    ax_g.set_xlabel("time (s)")
    ax_a.legend(loc="upper right", fontsize=8)
    ax_g.legend(loc="upper right", fontsize=8)
    ax_a.set_title(imu.sensor_label or imu.name)
    fig.tight_layout()
    return fig


def _rows(f) -> str:
    """Row count of a loaded file, or why it has no DataFrame."""
    if f.data is not None:
        return str(len(f.data))
    return "-" if f.paths else "(missing)"


def summarize(session) -> None:
    print(f"  activity_code   : {session.activity_code}")
    print(f"  sensor_placement: {session.sensor_placement}")
    print(f"  source          : {session.source}")
    print(f"  sensors         : {session.sensor_labels()}")

    # Every file the manifest lists, with the fields a downstream layer keys on:
    # MODALITY (what it is), LABEL (variant), SENSOR, and row count.
    print("  files:")
    print(f"    {'MODALITY':16} {'LABEL':12} {'SENSOR':11} {'ROWS':>9}  NAME")
    for f in session.files:
        print(f"    {f.modality:16} {f.modality_label or '-':12} "
              f"{f.sensor_label or '':11} {_rows(f):>9}  {f.name}")


def make_plots(session, outdir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")            # headless: write files, don't open a window
    except ImportError:
        print("  (matplotlib not installed -- skipping plots)")
        return
    import matplotlib.pyplot as plt

    outdir.mkdir(exist_ok=True)
    for f in session.imu():
        fig = plot(f)
        # Name the PNG after the source file (already unique per sensor).
        path = outdir / f"{session.folder.name}__{Path(f.name).stem}.png"
        fig.savefig(path, dpi=100)
        plt.close(fig)
        print(f"  wrote {path}")


def main(argv) -> None:
    targets = [Path(a) for a in argv[1:]] or [HERE / name for name in BUNDLED]
    for folder in targets:
        # Print the header first so a failure is clearly tied to its folder, then
        # skip a bad folder rather than crashing the whole run.
        print(f"\n=== {folder.name} ===")
        try:
            session = load_session(folder)
        except (FileNotFoundError, NotADirectoryError) as e:
            print(f"  skipped: {e}")
            continue
        summarize(session)
        make_plots(session, outdir=Path("lvl_plots"))


if __name__ == "__main__":
    main(sys.argv)
