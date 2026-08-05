"""Vicon-vs-IMU comparison figures — built on top of :mod:`lvl_toolkit.vicon.merge`.

Three figures from one merged (IMU + Vicon) dataframe:

- :func:`gait_vicon_overlay` — IMU signal vs. a Vicon marker's position,
  time-aligned, so you can eyeball whether events (heel strikes, turns) line
  up between the two.
- :func:`sync_error_over_time` — how far off (ms) each IMU sample's match to
  its nearest Vicon frame was, across the trial.
- :func:`sync_error_distribution` — the same errors as a histogram, so you can
  see the overall alignment quality at a glance.

These are sync/alignment diagnostics, not biomechanical validation (comparing
an IK-derived foot position against Vicon ground truth) -- that's later work,
once the pipeline computes a comparable position/orientation signal.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def gait_vicon_overlay(merged: pd.DataFrame, marker: str, subject: str,
                       imu_channel: str = "accel_z", axis: str = "z_mm",
                       title: str = "") -> plt.Figure:
    """Two-panel time-aligned overlay: an IMU channel on top, a Vicon marker's
    position on the same axis on the bottom. Both share the merged dataframe's
    time origin, so visually-matching events (a heel-strike spike, a turn)
    should land at the same x position on both panels.

    ``marker``/``subject`` select a column via the merge's flattened naming:
    ``f"{subject}:{marker}:{axis}"`` (e.g. ``"jl_barefoot:R_ANKLE_LAT:z_mm"``).
    """
    col = f"{subject}:{marker}:{axis}"
    if col not in merged.columns:
        raise KeyError(f"{col!r} not in merged columns; available markers: "
                       f"{sorted({c.split(':')[1] for c in merged.columns if ':' in c})}")

    t0 = int(merged["viconpc_ts_ns"].iloc[0])
    t = (merged["viconpc_ts_ns"] - t0) / 1e9

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
    ax1.plot(t, merged[imu_channel], color="#1f77b4", lw=0.8)
    ax1.set_ylabel(f"IMU {imu_channel}")
    ax1.grid(True, alpha=0.3)

    ax2.plot(t, merged[col], color="#d62728", lw=0.8)
    ax2.set_ylabel(f"Vicon {marker} {axis}")
    ax2.set_xlabel("time (s)")
    ax2.grid(True, alpha=0.3)

    fig.suptitle(title or f"IMU {imu_channel} vs Vicon {marker} ({axis})")
    fig.tight_layout()
    return fig


def _sync_error_ms(merged: pd.DataFrame, vicon_df: pd.DataFrame) -> np.ndarray:
    """Per-row sync error (ms): how far each IMU sample's ``viconpc_ts_ns`` is
    from the nearest actual Vicon frame timestamp in ``vicon_df``. NaN where
    the merge found no match within tolerance (already NaN in ``merged``), and
    also NaN for IMU samples outside the Vicon recording's own time window --
    those aren't a sync error, they're "no Vicon frame existed yet/anymore"
    (e.g. the bridge's documented startup lag / early tail cut), and including
    them would show up as large false spikes at the start/end of the trial."""
    frame_times = np.sort(vicon_df["viconpc_ts_ns"].unique())
    imu_times = merged["viconpc_ts_ns"].to_numpy()
    idx = np.searchsorted(frame_times, imu_times)
    idx = np.clip(idx, 1, len(frame_times) - 1)
    left, right = frame_times[idx - 1], frame_times[idx]
    nearest = np.where(np.abs(imu_times - left) <= np.abs(right - imu_times), left, right)
    err_ms = (imu_times - nearest) / 1e6
    err_ms = err_ms.astype(float)

    # Rows the merge itself couldn't match at all (outside tolerance).
    unmatched = merged.filter(regex=":").isna().all(axis=1).to_numpy()
    # Rows before the first / after the last actual Vicon frame -- outside the
    # recording window entirely, not a sync error.
    outside_window = (imu_times < frame_times[0]) | (imu_times > frame_times[-1])

    err_ms[unmatched | outside_window] = np.nan
    return err_ms


def sync_error_over_time(merged: pd.DataFrame, vicon_df: pd.DataFrame,
                         title: str = "Sync error over time") -> plt.Figure:
    """Per-sample IMU-to-nearest-Vicon-frame timing error (ms), across the trial."""
    err_ms = _sync_error_ms(merged, vicon_df)
    t0 = int(merged["viconpc_ts_ns"].iloc[0])
    t = (merged["viconpc_ts_ns"] - t0) / 1e9

    fig, ax = plt.subplots(figsize=(14, 3.5))
    ax.plot(t, err_ms, color="#9467bd", lw=0.6)
    ax.axhline(0, color="black", lw=0.5, alpha=0.5)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("sync error (ms)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def sync_error_distribution(merged: pd.DataFrame, vicon_df: pd.DataFrame,
                            title: str = "Sync error distribution") -> plt.Figure:
    """Histogram of the per-sample sync errors (ms)."""
    err_ms = _sync_error_ms(merged, vicon_df)
    err_ms = err_ms[~np.isnan(err_ms)]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(err_ms, bins=50, color="#9467bd", alpha=0.8)
    ax.axvline(0, color="black", lw=0.8, alpha=0.6)
    ax.set_xlabel("sync error (ms)")
    ax.set_ylabel("count")
    ax.set_title(f"{title}  (n={len(err_ms)}, "
                f"median={np.median(err_ms):.2f} ms, std={np.std(err_ms):.2f} ms)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig