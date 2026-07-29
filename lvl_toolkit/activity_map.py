"""Declarative graphing schema for Level capture sessions.

The loaders in :mod:`lvl_toolkit.session` decide *what data a session contains*.
This module decides *which figures to draw* from a loaded session -- and nothing
more. The caller owns the actual rendering: matplotlib, styling, colors, the
shared-t0 time alignment, and the segment shading (in rd-python that lives in
``graphing/_helpers.py`` -- ``LIMB_COLORS`` / ``SEGMENT_COLORS`` /
``add_segment_overlays``). The schema only names which sensors and modalities
belong on which figure, so plotting code stays generic instead of hardcoding
per-activity logic. It deliberately owns **no colors** -- coloring is a
rendering choice and already has a home in the consumer.

The decision is **presence-driven**: :func:`figures_for` inspects the modalities
and sensor labels the manifest surfaced (via ``session.files`` and
``session.sensor_labels()``), *not* ``session.activity_code``. A session that is
missing a sensor, or has an odd label, still plots whatever it can rather than
falling off an activity-code lookup.

Current scope is deliberately small -- **raw + stride/swing only**:

- ``raw_all`` (always): raw IMU for every sensor, one subplot per sensor. A raw
  app-sensor capture gets only this figure.
- ``feet`` (a walking-gait session with both feet): the two foot IMUs plus a
  stride/swing overlay from ``GAIT_SEGMENTS`` -- two subplots (L, R).
- ``lumbar`` (a processed session with a lumbar/trunk sensor): the raw lumbar
  IMU, one subplot.

So a TUG feet+lumbar session -> ``raw_all`` + ``feet`` + ``lumbar`` (3 figures);
a raw app-sensor folder -> ``raw_all`` (1 figure). No straight/turn overlay and
no lumbar-sway view yet -- those are intentionally out of scope for this version.

Typical use (default schema, out of the box)::

    from lvl_toolkit import load_session
    from lvl_toolkit.graphing import render_session

    session = load_session(folder)
    render_session(session)             # uses figures_for below -- just works


Write your own schema
---------------------
This file is meant to be **copied and modified**. A schema is nothing but a
function ``session -> list[FigureSpec]``; the renderer takes any such function
via ``schema=``, so you reuse the whole grapher (colors, overlays, layout) and
only decide *which* figures appear. To make a custom view, copy
:func:`figures_for`, change the rules, and pass it in::

    from lvl_toolkit.activity_map import FigureSpec, RAW_IMU_MODALITIES
    from lvl_toolkit.graphing import render_session

    def my_figures_for(session):
        # Always show raw IMU for every sensor...
        figs = [FigureSpec("raw_all", "Raw IMU (all sensors)", RAW_IMU_MODALITIES)]
        # ...plus a lumbar subplot for *any* session that has one (my rule).
        lumbar = next((l for l in session.sensor_labels() if _is_lumbar(l)), None)
        if lumbar:
            figs.append(FigureSpec("lumbar", "Lumbar", RAW_IMU_MODALITIES, sensors=[lumbar]))
        return figs

    render_session(session, schema=my_figures_for)

A ``FigureSpec`` has five fields (see the class) -- ``role``, ``title``,
``signal_modalities`` (drawn as time-series), and the optional ``overlay_modalities``
(drawn as bands), ``sensors`` (which labels; ``None`` = all), ``layout``. That's
the whole contract. Add a figure by appending one ``FigureSpec``; remove one by
not appending it. No renderer changes needed.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:                       # avoid a runtime import cycle with session
    from .session import Session


# --------------------------------------------------------------------------- #
# Modalities
# --------------------------------------------------------------------------- #

# Raw IMU streams that a "raw" subplot draws as a time-series. The loader tags
# most captures ``ACCEL_GYRO``; the others cover mag-bearing / partial streams.
RAW_IMU_MODALITIES: Tuple[str, ...] = ("ACCEL_GYRO", "ACCEL_GYRO_MAG", "GYRO", "MAG")

# The per-stride gait segmentation overlay (drawn as bands, not a time-series).
GAIT_SEGMENTS_MODALITY = "GAIT_SEGMENTS"


# --------------------------------------------------------------------------- #
# Figure roles
# --------------------------------------------------------------------------- #

ROLE_RAW_ALL = "raw_all"
ROLE_FEET = "feet"
ROLE_LUMBAR = "lumbar"

# The catalog of figure roles this schema can emit, in draw order, each with a
# one-line description. Callers can use this to title/group figures generically.
PLOT_ROLES: Dict[str, str] = {
    ROLE_RAW_ALL: "Raw IMU for every sensor -- one subplot per sensor.",
    ROLE_FEET: "The two foot IMUs with a stride/swing overlay (walking gait).",
    ROLE_LUMBAR: "The lumbar / trunk IMU -- one subplot.",
}


# --------------------------------------------------------------------------- #
# Figure specification
# --------------------------------------------------------------------------- #

@dataclass
class FigureSpec:
    """One figure to draw, described declaratively.

    The caller renders this: for each file in the session whose ``modality`` is
    in :attr:`signal_modalities` (and, if :attr:`sensors` is set, whose
    ``sensor_label`` is in it), draw a time-series; for each file whose
    ``modality`` is in :attr:`overlay_modalities`, draw bands over it. The
    schema names *what* to draw; it never touches an axis or picks a color.
    """
    role: str                                       # one of PLOT_ROLES
    title: str                                      # human-facing figure title
    signal_modalities: Tuple[str, ...]              # drawn as time-series
    overlay_modalities: Tuple[str, ...] = ()        # drawn as bands
    # Sensor labels (verbatim, as the capture named them) to include. ``None``
    # means "every sensor in the session".
    sensors: Optional[List[str]] = None
    # How subplots are arranged. ``"per_sensor"`` = one subplot per sensor.
    layout: str = "per_sensor"


# --------------------------------------------------------------------------- #
# Sensor-label classification (drives figure selection, not coloring)
# --------------------------------------------------------------------------- #

# Sensor labels are kept verbatim by the loader and can be free-form ("Left
# Foot", "Back") or canonical ("LEFT_FOOT", "LUMBAR"). Classify by normalized
# substring so both grammars land on the same placement role. This is used only
# to decide which sensors go on the feet / lumbar figures -- it is not a color
# lookup (that belongs to the renderer).

_LUMBAR_HINTS = ("lumbar", "l5", "sacrum", "sacral", "pelvis", "trunk", "back", "waist", "spine")


def _norm(label: str) -> str:
    return label.lower().replace("_", " ").strip()


def _is_left_foot(label: str) -> bool:
    n = _norm(label)
    return "foot" in n and "left" in n


def _is_right_foot(label: str) -> bool:
    n = _norm(label)
    return "foot" in n and "right" in n


def _is_lumbar(label: str) -> bool:
    n = _norm(label)
    if "foot" in n:                     # a foot is never a trunk sensor
        return False
    return any(hint in n for hint in _LUMBAR_HINTS)


def sensor_role(label: str) -> Optional[str]:
    """Canonical placement role for a verbatim sensor label, or ``None`` if it
    can't be placed. One of ``"LEFT_FOOT"`` / ``"RIGHT_FOOT"`` / ``"LUMBAR"``.

    Exposed because a renderer often wants to key its own color/layout choices
    off placement -- but the color map itself stays with the renderer."""
    if _is_left_foot(label):
        return "LEFT_FOOT"
    if _is_right_foot(label):
        return "RIGHT_FOOT"
    if _is_lumbar(label):
        return "LUMBAR"
    return None


# --------------------------------------------------------------------------- #
# The schema entry point
# --------------------------------------------------------------------------- #

def _first_label(labels: List[str], predicate) -> Optional[str]:
    for label in labels:
        if predicate(label):
            return label
    return None


def figures_for(session: "Session") -> List[FigureSpec]:
    """Return the figures to draw for ``session``, in draw order.

    Presence-driven: looks at which modalities and sensors the session actually
    has. ``raw_all`` is always emitted. ``feet`` is added when the session
    carries a ``GAIT_SEGMENTS`` overlay and both feet. ``lumbar`` is added when a
    processed (app-gait) session has a lumbar/trunk sensor.

    Note on the ``lumbar`` gate: it is scoped to processed sessions on purpose,
    so a raw app-sensor capture returns exactly ``[raw_all]`` even when it has a
    "Back" sensor (that sensor already appears in ``raw_all``). Flip the
    ``is_processed`` guard below to ``True`` if you want a lumbar subplot for raw
    captures too.
    """
    # Facts about this session that the rules below switch on. Add your own
    # here (e.g. a sensor count, a settings flag) if a custom figure needs it.
    labels = session.sensor_labels()
    is_processed = session.source == "app-gait"
    has_gait_segments = any(f.modality == GAIT_SEGMENTS_MODALITY for f in session.files)
    left = _first_label(labels, _is_left_foot)
    right = _first_label(labels, _is_right_foot)
    lumbar = _first_label(labels, _is_lumbar)

    figures: List[FigureSpec] = []

    # --- Figure: raw_all (always) --------------------------------------------
    # Raw IMU for every sensor, one subplot each. sensors=None means "all".
    figures.append(FigureSpec(
        role=ROLE_RAW_ALL,
        title="Raw IMU (all sensors)",
        signal_modalities=RAW_IMU_MODALITIES,
        sensors=None,
    ))

    # --- Figure: feet (walking gait with both feet) --------------------------
    # Two foot subplots with the stride/swing bands overlaid. Only when the
    # session actually has a GAIT_SEGMENTS file and both feet.
    if has_gait_segments and left and right:
        figures.append(FigureSpec(
            role=ROLE_FEET,
            title="Feet -- stride / swing",
            signal_modalities=RAW_IMU_MODALITIES,
            overlay_modalities=(GAIT_SEGMENTS_MODALITY,),
            sensors=[left, right],
        ))

    # --- Figure: lumbar (processed session with a trunk sensor) --------------
    # A dedicated lumbar subplot. Scoped to processed sessions so a raw
    # app-sensor capture returns just [raw_all] (its "Back" sensor already
    # shows in raw_all). Change `is_processed and lumbar` to `lumbar` to always
    # add it.
    if is_processed and lumbar:
        figures.append(FigureSpec(
            role=ROLE_LUMBAR,
            title="Lumbar",
            signal_modalities=RAW_IMU_MODALITIES,
            sensors=[lumbar],
        ))

    # --- Add your own figure here --------------------------------------------
    # figures.append(FigureSpec("my_view", "My view", RAW_IMU_MODALITIES,
    #                           sensors=[some_label]))

    return figures


__all__ = [
    "FigureSpec",
    "figures_for",
    "PLOT_ROLES",
    "RAW_IMU_MODALITIES",
    "GAIT_SEGMENTS_MODALITY",
    "ROLE_RAW_ALL",
    "ROLE_FEET",
    "ROLE_LUMBAR",
    "sensor_role",
]
