from pathlib import Path

import pytest

pytest.importorskip("matplotlib")
import matplotlib
matplotlib.use("Agg")                       # headless: never open a window
import matplotlib.pyplot as plt

from lvl_toolkit import load_session
from lvl_toolkit.graphing_schema import FigureSpec, RAW_IMU_MODALITIES
from lvl_toolkit.graphing import render_session, segment_color, sensor_color

EXAMPLES = Path(__file__).parent.parent / "examples"
RAW_SAMPLE = EXAMPLES / "app_sensor_raw_3sensor"
GAIT_SAMPLE = EXAMPLES / "app_gait_walk"


def _close(results):
    for _, fig in results:
        plt.close(fig)


def test_raw_session_renders_one_figure():
    results = render_session(load_session(RAW_SAMPLE))
    roles = [spec.role for spec, _ in results]
    assert roles == ["raw_all"]             # raw capture -> just raw_all
    _close(results)


def test_processed_session_renders_three_figures():
    results = render_session(load_session(GAIT_SAMPLE))
    roles = [spec.role for spec, _ in results]
    assert roles == ["raw_all", "feet", "lumbar"]
    _close(results)


def test_schema_is_swappable():
    # A custom schema is just a session -> list[FigureSpec] callable; the
    # renderer reuses everything and only the figure set changes.
    def only_raw(session):
        return [FigureSpec("raw_all", "Raw", RAW_IMU_MODALITIES)]

    results = render_session(load_session(GAIT_SAMPLE), schema=only_raw)
    assert [spec.role for spec, _ in results] == ["raw_all"]
    _close(results)


def test_color_helpers():
    assert sensor_color("Left Foot") == "#1f77b4"
    assert sensor_color("Right Foot") == "#228B22"
    assert segment_color("swing") == "#ffd27f"
    assert segment_color("discarded:terminal") == segment_color("discarded")  # suffix dropped
    assert segment_color("something-unknown") == "#cccccc"                     # graceful default
