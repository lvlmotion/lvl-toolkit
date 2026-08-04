"""lvl-toolkit: load and process Level capture files from Python.

Primary entry point is :func:`load_session`, which reads a session folder's
``meta-summary.json`` manifest and returns a :class:`Session` with each file's
parsed metadata and contents. Typed CSV containers live in ``lvl_toolkit.csv_io``.
"""

from .session import (
    Session,
    LoadedFile,
    load_session,
    find_manifest,
    iter_sessions,
)
from .csv_io import (
    DataContainerBase,
    ImuDataContainer,
    AngleDataContainer,
    JointEstimatorMode,
    SegmentDataContainer,
    Segment,
)
from .graphing_schema import (
    FigureSpec,
    figures_for,
    PLOT_ROLES,
    sensor_role,
)

__all__ = [
    "Session",
    "LoadedFile",
    "load_session",
    "find_manifest",
    "iter_sessions",
    "DataContainerBase",
    "ImuDataContainer",
    "AngleDataContainer",
    "JointEstimatorMode",
    "SegmentDataContainer",
    "Segment",
    "FigureSpec",
    "figures_for",
    "PLOT_ROLES",
    "sensor_role",
]
