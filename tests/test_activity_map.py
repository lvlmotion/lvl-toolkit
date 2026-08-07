"""Schema tests -- the figure-selection policy, no matplotlib needed.

Rendering is checked by eye (look at the PNG); what's worth asserting is that the
default schema picks the right figures for a session, and that a custom schema is
just a plain callable.
"""
from pathlib import Path

from lvl_toolkit import load_session
from lvl_toolkit.activity_map import figures_for, FigureSpec, sensor_role, GAIT_SEGMENTS_MODALITY

EXAMPLES = Path(__file__).parent.parent / "examples"
RAW = EXAMPLES / "app_sensor_raw_3sensor"
GAIT = EXAMPLES / "app_gait_walk"


def test_raw_capture_yields_raw_all_only():
    assert [s.role for s in figures_for(load_session(RAW))] == ["raw_all"]


def test_processed_walk_yields_raw_feet_lumbar():
    specs = figures_for(load_session(GAIT))
    assert [s.role for s in specs] == ["raw_all", "feet", "lumbar"]
    feet = next(s for s in specs if s.role == "feet")
    assert feet.sensors == ["Left Foot", "Right Foot"]
    assert GAIT_SEGMENTS_MODALITY in feet.overlay_modalities


def test_sensor_role_classifies_verbatim_labels():
    assert sensor_role("Left Foot") == "LEFT_FOOT"
    assert sensor_role("Back") == "LUMBAR"
    assert sensor_role("nose") is None


def test_a_custom_schema_is_just_a_callable():
    def only_raw(session):
        return [FigureSpec("raw_all", "Raw", ("ACCEL_GYRO",))]
    assert [s.role for s in only_raw(load_session(GAIT))] == ["raw_all"]
