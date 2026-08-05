"""
tests/test_vicon_merge.py

Offline validation of lvl_toolkit.vicon.merge. No phone or Vicon required — the
IMU side uses the bundled example session; the Vicon side is synthetic.

Covers:
  - load_imu reads a Level session folder via the toolkit loader
  - apply_clock_offset endpoints / interpolation / extrapolation / degenerate
  - load_clock_offset rejects malformed JSON
  - merge_imu_with_vicon nearest-joins on viconpc_ts_ns
  - a shared-clock merge over the real example IMU + a synthetic Vicon CSV
  - estimate_offset_via_xcorr recovers an injected offset
"""

import json

import numpy as np
import pandas as pd
import pytest

from lvl_toolkit.vicon.merge import (
    apply_clock_offset,
    estimate_offset_via_xcorr,
    load_clock_offset,
    load_imu,
    merge_imu_with_vicon,
)

from pathlib import Path

EXAMPLE_SESSION = Path(__file__).resolve().parents[1] / "examples" / "app_sensor_raw_3sensor"


# ---------------------------------------------------------------------------
# load_imu (via the toolkit session loader)
# ---------------------------------------------------------------------------

def test_load_imu_from_session_picks_labeled_sensor():
    df = load_imu(EXAMPLE_SESSION, imu_csv=None, sensor_label="Right Foot")
    for col in ("phone_ts_us", "phone_ts_ns", "accel_x", "accel_z", "gyro_x"):
        assert col in df.columns
    assert len(df) > 0
    assert df["phone_ts_ns"].dtype == np.int64
    # Absolute microsecond timestamps -> ns is exactly x1000.
    assert df["phone_ts_ns"].iloc[0] == df["phone_ts_us"].iloc[0] * 1000
    assert df["phone_ts_ns"].is_monotonic_increasing


def test_load_imu_ambiguous_session_requires_label():
    # The example session has three sensors; no label -> explicit error.
    with pytest.raises(ValueError, match="pass --sensor-label"):
        load_imu(EXAMPLE_SESSION, imu_csv=None, sensor_label=None)


# ---------------------------------------------------------------------------
# apply_clock_offset
# ---------------------------------------------------------------------------

def _make_offset(t0, o0, t1, o1):
    return {
        "start": {"phone_ts_ns": t0, "viconpc_ts_ns": t0 + o0, "offset_ns": o0},
        "end":   {"phone_ts_ns": t1, "viconpc_ts_ns": t1 + o1, "offset_ns": o1},
    }


def test_apply_clock_offset_endpoints_exact():
    offset = _make_offset(t0=1_000_000_000, o0=100, t1=2_000_000_000, o1=200)
    result = apply_clock_offset([1_000_000_000, 2_000_000_000], offset)
    assert result[0] == 1_000_000_000 + 100
    assert result[1] == 2_000_000_000 + 200


def test_apply_clock_offset_interpolates_linearly():
    offset = _make_offset(t0=0, o0=0, t1=1_000_000_000, o1=1000)
    result = apply_clock_offset([500_000_000], offset)
    assert result[0] == 500_000_000 + 500


def test_apply_clock_offset_extrapolates_before_start():
    offset = _make_offset(t0=1_000_000_000, o0=100, t1=2_000_000_000, o1=200)
    result = apply_clock_offset([900_000_000], offset)
    assert result[0] == 900_000_000 + 90


def test_apply_clock_offset_constant_when_anchors_equal(capsys):
    offset = _make_offset(t0=1_000, o0=100, t1=1_000, o1=300)
    result = apply_clock_offset([1_000, 2_000], offset)
    assert result[0] == 1_000 + 200
    assert result[1] == 2_000 + 200
    assert "identical" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# load_clock_offset
# ---------------------------------------------------------------------------

def test_load_clock_offset_rejects_missing_end(tmp_path):
    path = tmp_path / "offset.json"
    path.write_text(json.dumps({
        "start": {"phone_ts_ns": 1, "viconpc_ts_ns": 2, "offset_ns": 1},
    }))
    with pytest.raises(ValueError, match="missing 'end'"):
        load_clock_offset(path)


def test_load_clock_offset_rejects_missing_field(tmp_path):
    path = tmp_path / "offset.json"
    path.write_text(json.dumps({
        "start": {"phone_ts_ns": 1, "viconpc_ts_ns": 2, "offset_ns": 1},
        "end":   {"phone_ts_ns": 3, "viconpc_ts_ns": 4},  # missing offset_ns
    }))
    with pytest.raises(ValueError, match="offset_ns"):
        load_clock_offset(path)


# ---------------------------------------------------------------------------
# merge_imu_with_vicon
# ---------------------------------------------------------------------------

def test_merge_imu_with_vicon_nearest_join():
    imu = pd.DataFrame({
        "phone_ts_ns": [100, 200, 300],
        "accel_x": [1.0, 2.0, 3.0], "accel_y": [0.0, 0.0, 0.0], "accel_z": [9.8, 9.8, 9.8],
        "gyro_x": [0.0, 0.0, 0.0], "gyro_y": [0.0, 0.0, 0.0], "gyro_z": [0.0, 0.0, 0.0],
        "viconpc_ts_ns": [100, 200, 300],
    })
    vicon = pd.DataFrame({
        "frame": [1, 2],
        "viconpc_ts_ns": [90, 290],
        "subject": ["S", "S"],
        "marker_name": ["RHEE", "RHEE"],
        "x_mm": [10.0, 20.0], "y_mm": [0.0, 0.0], "z_mm": [50.0, 55.0],
        "occluded": [0, 0],
    })
    merged = merge_imu_with_vicon(imu, vicon, tolerance_ns=50)
    z_col = "S:RHEE:z_mm"
    assert merged.loc[0, z_col] == 50.0
    assert pd.isna(merged.loc[1, z_col])
    assert merged.loc[2, z_col] == 55.0


def test_shared_clock_merge_over_example_session():
    """End-to-end shared-clock join: real example IMU + synthetic Vicon on the
    same clock. Every ~10th IMU sample gets a Vicon frame, so a good chunk of
    rows should match."""
    imu = load_imu(EXAMPLE_SESSION, imu_csv=None, sensor_label="Right Foot")
    # Shared-clock: Vicon frames live on the IMU's own microsecond->ns axis.
    imu["viconpc_ts_ns"] = imu["phone_ts_ns"]

    frame_ts = imu["viconpc_ts_ns"].to_numpy()[::10]
    vicon = pd.DataFrame({
        "frame": np.arange(len(frame_ts)),
        "viconpc_ts_ns": frame_ts,
        "subject": "S",
        "marker_name": "RHEE",
        "x_mm": 0.0, "y_mm": 0.0,
        "z_mm": np.sin(np.arange(len(frame_ts)) / 5.0) * 30.0,
        "occluded": 0,
    })
    merged = merge_imu_with_vicon(imu, vicon, tolerance_ns=5_000_000)
    matched = merged.filter(regex=":").notna().any(axis=1).sum()
    assert matched > 0


# ---------------------------------------------------------------------------
# estimate_offset_via_xcorr
# ---------------------------------------------------------------------------

def test_xcorr_recovers_injected_offset():
    rng = np.random.default_rng(1)
    n = 1000
    dt_ns = 10_000_000  # 10 ms
    t = np.arange(n) * dt_ns
    walk = np.sin(2 * np.pi * 2.0 * (t / 1e9))

    shift_steps = 5  # 50 ms ahead
    shifted_walk = np.roll(walk, shift_steps)

    imu_df = pd.DataFrame({"viconpc_ts_ns": t, "accel_z": shifted_walk + 0.05 * rng.standard_normal(n)})
    vicon_df = pd.DataFrame({
        "viconpc_ts_ns": t, "marker_name": ["RHEE"] * n,
        "z_mm": walk + 0.05 * rng.standard_normal(n),
    })

    lag_ns = estimate_offset_via_xcorr(imu_df, vicon_df, grid_dt_ns=dt_ns)
    assert lag_ns is not None
    assert abs(lag_ns - shift_steps * dt_ns) <= dt_ns
