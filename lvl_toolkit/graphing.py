"""Generic session grapher -- turns a loaded session into figures.

This is the public, generic rendering layer: give it a session and it draws the
figures a schema asks for. It is deliberately schema-*driven*, not
schema-*specific* -- :func:`render_session` takes the schema as an argument
(defaulting to :func:`lvl_toolkit.activity_map.figures_for`), so the same
renderer serves three audiences:

- **researchers** who just want graphs of a capture they collected -- call
  ``render_session(session)`` and get sensible defaults;
- **anyone with a custom view** -- write your own ``figures_for``-shaped callable
  (``session -> list[FigureSpec]``) and pass it as ``schema=``; the renderer,
  colors, and overlays are all reused;
- **internal debug** -- same mechanism, a richer private schema.

The renderer only understands :class:`~lvl_toolkit.activity_map.FigureSpec`, the
interchange format. It never hardcodes an activity. Colors live here (a rendering
choice), not in the schema.

Requires ``matplotlib`` (a declared dependency). Import this module explicitly
(``import lvl_toolkit.graphing``) -- it is intentionally kept out of the
top-level package import so the pure loader stays lightweight.
"""

from typing import Callable, List, Optional, Tuple

import matplotlib.pyplot as plt

from .activity_map import FigureSpec, figures_for, sensor_role


# --------------------------------------------------------------------------- #
# Colors  (a rendering choice -- lives here, not in the schema)
# --------------------------------------------------------------------------- #

# Per-sensor identity color, keyed by placement role (see activity_map.sensor_role).
# Left = blue, Right = forest green -- the house convention.
SENSOR_COLORS = {
    "LEFT_FOOT": "#1f77b4",     # blue
    "RIGHT_FOOT": "#228B22",    # forest green
    "LUMBAR": "#9467bd",        # purple
    "DEFAULT": "#555555",       # slate gray
}

# IMU channel colors (x / y / z), shared by accel (solid) and gyro (dashed).
AXIS_COLORS = {"x": "#d62728", "y": "#2ca02c", "z": "#1f77b4"}

# Overlay band color, keyed by (normalized) segment type. Light fill shades meant
# to sit under the signal at low alpha. Covers gait-cycle phase names (swing /
# stance / stride / gait / straight / turn) as well as TUG state-machine phases
# (up / walk / down); anything else falls back to DEFAULT so an unknown
# vocabulary still draws.
SEGMENT_COLORS = {
    "swing": "#ffd27f",         # light orange
    "stance": "#a6cee3",        # light blue
    "stride": "#c7e9c0",        # light green
    "gait": "#c7e9c0",
    "straight": "#c7e9c0",
    "turn": "#fdae6b",          # orange
    "turning": "#fdae6b",
    "discarded": "#e0e0e0",     # gray
    "up": "#FFA500",            # orange (TUG: stand-up phase)
    "walk": "#9370DB",          # medium purple (TUG: walking phase)
    "down": "#A0522D",          # sienna (TUG: sit-down phase)
    "other": "#B0B0B0",         # neutral gray (TUG: unclassified)
    "DEFAULT": "#cccccc",
}


def sensor_color(label: str) -> str:
    """Identity color for a sensor, by its placement role."""
    return SENSOR_COLORS.get(sensor_role(label) or "DEFAULT", SENSOR_COLORS["DEFAULT"])


def segment_color(segment_type: str) -> str:
    """Band color for a segment type. Normalizes case and drops any
    ``":detail"`` suffix (``"discarded:terminal"`` -> ``"discarded"``); unknown
    types get the neutral DEFAULT shade."""
    key = (segment_type or "").strip().lower().split(":", 1)[0]
    return SEGMENT_COLORS.get(key, SEGMENT_COLORS["DEFAULT"])


# --------------------------------------------------------------------------- #
# Figure + save helpers
# --------------------------------------------------------------------------- #

def time_series_grid(n: int, *, sharex: bool = True):
    """Standard stacked time-series grid: ``subplots(n, 1, figsize=(14, 3n))``."""
    n = max(n, 1)
    fig, axes = plt.subplots(n, 1, figsize=(14, 3 * n), sharex=sharex, squeeze=False)
    return fig, [ax[0] for ax in axes]      # flatten the (n, 1) axes array


def save_fig(fig, path, *, dpi: int = 300) -> None:
    """Tight-layout, save, and ALWAYS close the figure (no batch leaks)."""
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Shared y-axis limits (avoids a quiet/static trial looking like big movement)
# --------------------------------------------------------------------------- #

MIN_SPAN = {"accel": 30.0, "gyro": 4.0}  # m/s^2, rad/s


def _shared_ylim(signals, prefix):
    """One y-range across all sensors for a modality (accel or gyro), at
    least MIN_SPAN wide. A quiet/static trial otherwise autoscales to sensor
    noise and reads like large movement. Ignores NaN/Inf samples."""
    import numpy as np
    span = MIN_SPAN.get(prefix, 1.0)
    cols = [f"{prefix}_{axis}" for axis in ("x", "y", "z")]
    vals = []
    for f in signals:
        df = f.data
        present = [c for c in cols if c in df.columns]
        if present:
            vals.append(df[present].to_numpy().ravel())
    if not vals:
        return None
    vals = np.concatenate(vals)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return None
    lo, hi = vals.min(), vals.max()
    pad = 0.05 * (hi - lo)
    lo, hi = lo - pad, hi + pad
    if hi - lo < span:
        mid = 0.5 * (hi + lo)
        lo, hi = mid - span / 2, mid + span / 2
    return lo, hi


# --------------------------------------------------------------------------- #
# Segment overlays
# --------------------------------------------------------------------------- #

def _resolve_segment_columns(df) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Find the (start, end, type, notes) columns in a segment DataFrame,
    tolerating the naming variants segment files have used."""
    start_col = end_col = type_col = notes_col = None
    for col in df.columns:
        cl = col.lower()
        if start_col is None and "start" in cl and "time" in cl:
            start_col = col
        elif end_col is None and "end" in cl and "time" in cl:
            end_col = col
        elif type_col is None and ("type" in cl or "label" in cl or "phase" in cl):
            type_col = col
        elif notes_col is None and ("note" in cl or "foot" in cl or "sensor" in cl):
            notes_col = col
    return start_col, end_col, type_col, notes_col


def add_segment_overlays(ax, seg_df, t0: int, *, alpha: float = 0.25,
                         restrict_to_role: Optional[str] = None) -> None:
    """Shade segment rows as vertical background bands on ``ax``.

    Times are aligned to ``t0`` (the same shared origin the signals use). Colors
    come from :func:`segment_color`. If ``restrict_to_role`` is set (e.g.
    ``"LEFT_FOOT"``) and the segments carry a foot/notes column, only bands for
    that placement are drawn -- so a left-foot subplot shows only left swings.
    """
    if seg_df is None or len(seg_df) == 0:
        return
    start_col, end_col, type_col, notes_col = _resolve_segment_columns(seg_df)
    if start_col is None or end_col is None:
        return
    for _, seg in seg_df.iterrows():
        start, end = seg[start_col], seg[end_col]
        if start != start or end != end:            # NaN guard
            continue
        if restrict_to_role and notes_col is not None:
            if sensor_role(str(seg[notes_col])) not in (None, restrict_to_role):
                continue
        color = segment_color(str(seg[type_col])) if type_col is not None else SEGMENT_COLORS["DEFAULT"]
        ax.axvspan((start - t0) / 1e6, (end - t0) / 1e6, color=color, alpha=alpha, zorder=0)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def _signal_files(session, spec: FigureSpec) -> list:
    files = [f for f in session.files
             if f.modality in spec.signal_modalities and f.data is not None]
    if spec.sensors is not None:
        files = [f for f in files if f.sensor_label in spec.sensors]
    return files


def _overlay_files(session, spec: FigureSpec) -> list:
    return [f for f in session.files
            if f.modality in spec.overlay_modalities and f.data is not None]


def _ordered_sensors(spec: FigureSpec, files: list) -> List[str]:
    """Sensor labels to draw, one subplot each, in a stable order."""
    if spec.sensors is not None:
        present = {f.sensor_label for f in files}
        return [s for s in spec.sensors if s in present]     # spec order, only present
    seen: List[str] = []
    for f in files:                                          # manifest order
        if f.sensor_label not in seen:
            seen.append(f.sensor_label)
    return seen


def render_figure(spec: FigureSpec, session):
    """Render one :class:`FigureSpec` to a matplotlib ``Figure``.

    ``layout="per_sensor"`` draws one subplot per sensor: accel (solid) and gyro
    (dashed) x/y/z, on a shared t0 time axis, with any overlay modalities shaded
    behind. Sensors are colored by placement (subplot title); channels by axis.
    A shared y-axis range (with a minimum span) is applied across all subplots
    so a quiet/static trial doesn't get auto-scaled into looking like large
    movement.
    """
    signals = _signal_files(session, spec)
    overlays = _overlay_files(session, spec)
    sensors = _ordered_sensors(spec, signals)

    # Shared time origin across everything on this figure.
    firsts = [f.data["time"].iloc[0] for f in signals if "time" in f.data.columns and len(f.data)]
    t0 = int(min(firsts)) if firsts else 0

    # Shared y-limits across all sensors on this figure (accel + gyro combined
    # into one range per subplot, since both are plotted on the same axes).
    accel_lim = _shared_ylim(signals, "accel")
    gyro_lim = _shared_ylim(signals, "gyro")
    shared_lim = None
    if accel_lim and gyro_lim:
        shared_lim = (min(accel_lim[0], gyro_lim[0]), max(accel_lim[1], gyro_lim[1]))
    elif accel_lim:
        shared_lim = accel_lim
    elif gyro_lim:
        shared_lim = gyro_lim

    fig, axes = time_series_grid(len(sensors))
    for ax, label in zip(axes, sensors):
        role = sensor_role(label)
        for f in (f for f in signals if f.sensor_label == label):
            df = f.data
            t = (df["time"] - t0) / 1e6
            for axis, color in AXIS_COLORS.items():
                if f"accel_{axis}" in df.columns:
                    ax.plot(t, df[f"accel_{axis}"], color=color, lw=0.8, label=f"accel_{axis}")
                if f"gyro_{axis}" in df.columns:
                    ax.plot(t, df[f"gyro_{axis}"], color=color, lw=0.8, ls="--", label=f"gyro_{axis}")
        for f in overlays:
            add_segment_overlays(ax, f.data, t0, restrict_to_role=role)
        if shared_lim is not None:
            ax.set_ylim(*shared_lim)
        ax.set_ylabel("accel / gyro")
        ax.set_title(label or "(unlabeled)", color=sensor_color(label), fontsize=10, loc="left")
    axes[-1].set_xlabel("time (s)")
    axes[0].legend(loc="upper right", fontsize=7, ncol=2)
    fig.suptitle(f"{session.activity_code} -- {spec.title}", fontsize=12)
    return fig


def render_session(session, schema: Callable = figures_for) -> List[Tuple[FigureSpec, "plt.Figure"]]:
    """Render every figure the ``schema`` asks for, in order.

    ``schema`` is any ``session -> list[FigureSpec]`` callable; it defaults to the
    public :func:`~lvl_toolkit.activity_map.figures_for`. Pass your own to get a
    different set of figures out of the same renderer, colors, and overlays.

    Returns a list of ``(FigureSpec, Figure)`` -- the caller shows or saves them.
    """
    return [(spec, render_figure(spec, session)) for spec in schema(session)]


def save_session_figures(session, outdir, *, schema: Callable = figures_for,
                         dpi: int = 300) -> List[str]:
    """Render a session and write one PNG per figure to ``outdir``. Returns the
    paths written."""
    import os
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for spec, fig in render_session(session, schema=schema):
        path = os.path.join(outdir, f"{session.folder.name}__{spec.role}.png")
        save_fig(fig, path, dpi=dpi)
        paths.append(path)
    return paths


__all__ = [
    "SENSOR_COLORS",
    "AXIS_COLORS",
    "SEGMENT_COLORS",
    "sensor_color",
    "segment_color",
    "time_series_grid",
    "save_fig",
    "add_segment_overlays",
    "render_figure",
    "render_session",
    "save_session_figures",
]