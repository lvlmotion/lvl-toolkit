"""Drivers -- WHICH data to plot.

Two convenience entry points over the loader + renderer: :func:`plot_session`
(one session folder) and :func:`plot_all_sessions` (every session under a
root). Each just wires :mod:`lvl_toolkit.session` (the loader) to
:mod:`lvl_toolkit.graphing` (the renderer), driven by a schema (a
``session -> list[FigureSpec]`` callable, default
:func:`lvl_toolkit.graphing_schema.figures_for`).

Thin scripts sit on top of these -- see ``examples/run.py`` (calls
:func:`plot_all_sessions` on the bundled example folder) and
``lvl_toolkit/vicon/run_receiver.py`` (calls :func:`plot_session` on the one
folder app-sensor-desktop hands it).
"""

from typing import Callable, List

from .graphing import save_session_figures
from .graphing_schema import figures_for
from .session import iter_sessions, load_session


def plot_session(folder, schema: Callable = figures_for) -> List[str]:
    """Load and graph ONE session folder. Figures are saved next to the
    session (see :func:`~lvl_toolkit.graphing.save_session_figures`).
    Returns the list of PNG paths written."""
    session = load_session(folder)
    return save_session_figures(session, session.folder, schema=schema)


def plot_all_sessions(root, schema: Callable = figures_for) -> List[str]:
    """Load and graph EVERY session found under ``root`` (one level down;
    see :func:`~lvl_toolkit.session.iter_sessions`). Returns the combined
    list of PNG paths written across all sessions."""
    paths: List[str] = []
    for session in iter_sessions(root):
        paths += save_session_figures(session, session.folder, schema=schema)
    return paths