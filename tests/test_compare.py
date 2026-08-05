"""Tests for lvl_toolkit.vicon.compare -- built against a small synthetic
merged dataframe so these don't depend on the (large, external) pilot dataset."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from lvl_toolkit.vicon.compare import (
    gait_vicon_overlay,
    sync_error_distribution,
    sync_error_over_time,
    _sync_error_ms,
)


def _make_merged_and_vicon(n=200, hz=200, frame_hz=100):
    """A small synthetic IMU+Vicon merge: a shared-clock trial with a known,
    small, roughly-uniform timing jitter -- close to a real shared-clock rig,
    without needing the real pilot data."""
    dt_ns = int(1e9 / hz)
    t0 = 1_000_000_000_000
    imu_ts = t0 + np.arange(n) * dt_ns

    frame_dt_ns = int(1e9 / frame_hz)
    n_frames = int(n * dt_ns / frame_dt_ns) + 2
    frame_ts = t0 + np.arange(n_frames) * frame_dt_ns

    merged = pd.DataFrame({
        "viconpc_ts_ns": imu_ts,
        "accel_z": np.sin(np.linspace(0, 10, n)) * 10 + 9.8,
        "jl_barefoot:R_ANKLE_LAT:z_mm": np.sin(np.linspace(0, 10, n)) * 100 + 100,
    })
    vicon_df = pd.DataFrame({
        "viconpc_ts_ns": frame_ts,
        "marker_name": ["R_ANKLE_LAT"] * n_frames,
    })
    return merged, vicon_df


def test_gait_vicon_overlay_renders():
    merged, _ = _make_merged_and_vicon()
    fig = gait_vicon_overlay(merged, marker="R_ANKLE_LAT", subject="jl_barefoot")
    assert fig is not None
    plt.close(fig)


def test_gait_vicon_overlay_missing_column_raises():
    merged, _ = _make_merged_and_vicon()
    with pytest.raises(KeyError):
        gait_vicon_overlay(merged, marker="NOT_A_MARKER", subject="jl_barefoot")


def test_sync_error_over_time_renders():
    merged, vicon_df = _make_merged_and_vicon()
    fig = sync_error_over_time(merged, vicon_df)
    assert fig is not None
    plt.close(fig)


def test_sync_error_distribution_renders():
    merged, vicon_df = _make_merged_and_vicon()
    fig = sync_error_distribution(merged, vicon_df)
    assert fig is not None
    plt.close(fig)


def test_sync_error_is_small_for_shared_clock():
    """Every IMU sample sits inside the Vicon window and should be within
    half a Vicon frame interval (5 ms at 100 Hz) of its nearest frame."""
    merged, vicon_df = _make_merged_and_vicon()
    err_ms = _sync_error_ms(merged, vicon_df)
    assert not np.any(np.isnan(err_ms))
    assert np.nanmax(np.abs(err_ms)) <= 5.5


def test_sync_error_excludes_outside_recording_window():
    """IMU samples before the first / after the last Vicon frame are NaN, not
    a large spurious error (the edge-of-recording bug this test guards)."""
    merged, vicon_df = _make_merged_and_vicon()
    # Push the last two IMU rows outside the Vicon window entirely.
    merged = merged.copy()
    merged.loc[merged.index[-2:], "viconpc_ts_ns"] += 10_000_000_000  # +10s, way outside
    err_ms = _sync_error_ms(merged, vicon_df)
    assert np.isnan(err_ms[-2:]).all()
    assert np.nanmax(np.abs(err_ms[:-2])) <= 5.5