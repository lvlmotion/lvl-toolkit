"""
merge.py

Align a Level IMU capture with Vicon PC data and emit a merged dataset. The IMU
side is read through lvl-toolkit's own loaders (``load_session`` /
``ImuDataContainer``), so it handles the manifest, rotations and sensor labels
for you. Two capture paths are supported:

  * DESKTOP single-machine rig (--shared-clock): app-sensor-desktop writes the
    IMU on the same PC that runs bridge.py, so the IMU's absolute microsecond
    ``time`` and bridge.py's ``time.time_ns()`` frame stamps are already one
    wallclock. No clock offset — join directly.
  * ANDROID phone path (default): phone and Vicon PC are two clocks, corrected
    via a linearly-interpolated offset from clock_offset.json (clock_sync.py).

Pipeline:
  1. Load the IMU. Point --imu-session at a Level session folder (recommended;
     --sensor-label picks one sensor when several are present), or --imu-csv at
     a single ACCEL_GYRO CSV. Timestamps become phone_ts_ns.
  2. Map onto the Vicon PC clock: identity under --shared-clock, else apply the
     interpolated clock offset.
  3. Load the Vicon CSV (long format from bridge.py) with viconpc_ts_ns/frame.
  4. Merge on viconpc_ts_ns using merge_asof (nearest-frame join).
  5. Optionally cross-correlate heel-strike spikes (vertical accel vs vertical
     foot-marker position) as an independent offset check, flagging the session
     if the two estimates disagree by > threshold.

Examples:
    # Desktop rig — one clock; IMU is a Level session folder.
    lvl-vicon-merge --shared-clock \\
        --imu-session ~/lvloutput/data/2026-05-12_10-03-40-BTIMU_RAW-run01 \\
        --sensor-label "Right Foot" \\
        --vicon vicon_run01.csv \\
        --output ~/lvloutput/vicon_merged/run01/merged.csv

    # Android phone path — two clocks, needs the ADB offset.
    lvl-vicon-merge \\
        --imu-session ./pulled/run01 --sensor-label "Right Foot" \\
        --vicon vicon_run01.csv --offset clock_offset.json \\
        --output ./merged/run01.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from lvl_toolkit.csv_io import ImuDataContainer
from lvl_toolkit.session import load_session

# Long-format columns produced by bridge.py.
VICON_COLUMNS = [
    "frame",
    "viconpc_ts_ns",
    "subject",
    "marker_name",
    "x_mm",
    "y_mm",
    "z_mm",
    "occluded",
]

# Design doc: flag the session if ADB and xcorr offsets disagree by > 50 ms.
CROSS_CORR_DISAGREEMENT_THRESHOLD_NS = 50_000_000  # 50 ms


# ---------------------------------------------------------------------------
# IMU loading (via lvl-toolkit's own readers)
# ---------------------------------------------------------------------------

def _imu_df_from_container(dc: ImuDataContainer) -> pd.DataFrame:
    """Flatten a typed ImuDataContainer into the DataFrame the merge expects.

    Produces phone_ts_us/phone_ts_ns plus accel_/gyro_ columns. (The name
    ``phone_ts`` is historical — for a desktop capture it's the PC wallclock;
    either way it's the IMU sample time in absolute microseconds.)
    """
    time_us, accel, gyro = dc.to_numpy()
    df = pd.DataFrame({
        "phone_ts_us": time_us.astype("int64"),
        "accel_x": accel[:, 0], "accel_y": accel[:, 1], "accel_z": accel[:, 2],
        "gyro_x": gyro[:, 0], "gyro_y": gyro[:, 1], "gyro_z": gyro[:, 2],
    })
    df["phone_ts_ns"] = df["phone_ts_us"] * 1000
    return df


def load_imu(
        imu_session: Path | None,
        imu_csv: Path | None,
        sensor_label: str | None,
) -> pd.DataFrame:
    """Load the IMU stream from a session folder or a single CSV.

    Session path (recommended): reads the manifest, concatenates rotations, and
    joins sensor labels. When the session has more than one IMU sensor,
    ``sensor_label`` selects one (matched case-insensitively against the
    capture's own label, e.g. ``"Right Foot"``).
    """
    if imu_session is not None:
        session = load_session(imu_session)
        imus = session.imu()
        if not imus:
            raise ValueError(f"No ACCEL_GYRO files in session {imu_session}")
        if sensor_label:
            want = sensor_label.strip().lower()
            imus = [f for f in imus if f.sensor_label.strip().lower() == want]
            if not imus:
                raise ValueError(f"No IMU file with sensor label {sensor_label!r}")
        if len(imus) > 1:
            labels = ", ".join(f.sensor_label or "(unnamed)" for f in imus)
            raise ValueError(
                f"{len(imus)} IMU sensors in session ({labels}); "
                f"pass --sensor-label to pick one."
            )
        return _imu_df_from_container(imus[0].imu_container())

    if imu_csv is not None:
        dc = ImuDataContainer()
        dc.load_from_csv(str(imu_csv))
        return _imu_df_from_container(dc)

    raise ValueError("Provide --imu-session or --imu-csv.")


def print_diagnostics(df: pd.DataFrame, label: str = "IMU") -> None:
    """Print row count, time range, duration, and approximate sampling rate."""
    n = len(df)
    if n == 0:
        print(f"WARNING: {label} dataframe is empty.")
        return

    start_ns = int(df["phone_ts_ns"].iloc[0])
    end_ns = int(df["phone_ts_ns"].iloc[-1])
    duration_s = (end_ns - start_ns) / 1e9
    approx_hz = (n - 1) / duration_s if duration_s > 0 else float("nan")

    # Median dt is a more robust rate estimate than total-range / n;
    # if there are gaps in the recording, mean and median diverge.
    dt_ns = np.diff(df["phone_ts_ns"].to_numpy())
    median_dt_ms = float(np.median(dt_ns)) / 1e6 if len(dt_ns) > 0 else float("nan")

    print(f"=== {label} diagnostics ===")
    print(f"Rows:                  {n}")
    print(f"Start phone_ts_ns:     {start_ns}")
    print(f"End   phone_ts_ns:     {end_ns}")
    print(f"Duration (s):          {duration_s:.3f}")
    print(f"Approx rate (Hz):      {approx_hz:.2f}")
    print(f"Median sample dt (ms): {median_dt_ms:.3f}")


# ---------------------------------------------------------------------------
# Clock offset application (linear interpolation between start and end)
# ---------------------------------------------------------------------------

def load_clock_offset(path: Path) -> dict:
    """Load and validate clock_offset.json. Must have 'start' and 'end'."""
    with open(path, "r") as f:
        data = json.load(f)

    for key in ("start", "end"):
        if key not in data:
            raise ValueError(
                f"clock_offset.json is missing '{key}' entry. "
                f"Run `clock_sync.py --{key}` before merging."
            )
        for field in ("phone_ts_ns", "viconpc_ts_ns", "offset_ns"):
            if field not in data[key]:
                raise ValueError(
                    f"clock_offset.json '{key}' entry is missing '{field}'."
                )
    return data


def apply_clock_offset(phone_ts_ns, clock_offset_json) -> np.ndarray:
    """Map phone timestamps onto the Vicon PC clock via linear interpolation.

    Uses the two anchor points in clock_offset.json (start and end ADB
    measurements) and linearly interpolates the offset across each
    phone_ts_ns sample. Samples outside the [start, end] window are
    extrapolated on the same line, which matters because the IMU
    recording usually starts a few seconds before or after the sync taps.
    """
    start = clock_offset_json["start"]
    end = clock_offset_json["end"]

    t0 = int(start["phone_ts_ns"])
    t1 = int(end["phone_ts_ns"])
    o0 = int(start["offset_ns"])
    o1 = int(end["offset_ns"])

    phone_ts_ns = np.asarray(phone_ts_ns, dtype=np.int64)

    if t1 == t0:
        # Degenerate case: both samples taken at the same instant. Probably
        # means somebody ran --start and --end back to back without a real
        # session in between. Fall back to constant offset and warn loudly.
        print(
            "WARNING: start and end phone_ts_ns are identical; "
            "using constant offset.",
            file=sys.stderr,
        )
        offsets = np.full_like(phone_ts_ns, (o0 + o1) // 2)
    else:
        # Math in float64 to avoid int overflow on the slope multiply,
        # then cast back to int64. With t spans of ~hours (~1e13 ns) and
        # offset deltas of ~tens of ms (~1e7 ns), float64 has way more
        # than enough precision.
        slope = (o1 - o0) / (t1 - t0)
        offsets = o0 + slope * (phone_ts_ns.astype(np.float64) - t0)
        offsets = np.round(offsets).astype(np.int64)

    return phone_ts_ns + offsets


# ---------------------------------------------------------------------------
# Vicon CSV loading + merge
# ---------------------------------------------------------------------------

def load_vicon_csv(csv_path: Path) -> pd.DataFrame:
    """Load the Vicon CSV (header row written by bridge.py)."""
    df = pd.read_csv(csv_path)
    missing = set(VICON_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Vicon CSV missing columns: {missing}")
    df["viconpc_ts_ns"] = df["viconpc_ts_ns"].astype("int64")
    return df


def merge_imu_with_vicon(
        imu_df: pd.DataFrame,
        vicon_df: pd.DataFrame,
        tolerance_ns: int = 20_000_000,  # 20 ms — Vicon runs at 100-200 Hz
) -> pd.DataFrame:
    """Nearest-neighbor merge of IMU samples onto Vicon frames.

    Vicon long-format has one row per (frame, marker). To merge against IMU
    (one row per sample), we pivot Vicon to one row per frame with marker
    columns flattened like `subject:marker:x_mm`. Simple first pass; a
    leaner version would only pivot the markers downstream analysis needs.
    """
    pivot = vicon_df.pivot_table(
        index=["frame", "viconpc_ts_ns"],
        columns=["subject", "marker_name"],
        values=["x_mm", "y_mm", "z_mm", "occluded"],
        aggfunc="first",
    )
    # Flatten MultiIndex columns: ('x_mm', 'subj', 'RHEE') -> 'subj:RHEE:x_mm'
    pivot.columns = [f"{subj}:{marker}:{axis}" for axis, subj, marker in pivot.columns]
    pivot = pivot.reset_index().sort_values("viconpc_ts_ns")

    # merge_asof requires both sides sorted on the join key.
    imu_sorted = imu_df.sort_values("viconpc_ts_ns").copy()

    merged = pd.merge_asof(
        imu_sorted,
        pivot,
        on="viconpc_ts_ns",
        direction="nearest",
        tolerance=tolerance_ns,
    )
    return merged


# ---------------------------------------------------------------------------
# Cross-correlation sanity check
# ---------------------------------------------------------------------------

def _resample_to_uniform(
        ts_ns: np.ndarray, values: np.ndarray, dt_ns: int
) -> tuple[np.ndarray, np.ndarray]:
    """Linear-interpolate a signal onto a uniform time grid."""
    if len(ts_ns) < 2:
        return ts_ns, values
    grid = np.arange(ts_ns[0], ts_ns[-1], dt_ns)
    interp = np.interp(grid, ts_ns, values)
    return grid, interp


def estimate_offset_via_xcorr(
        imu_df: pd.DataFrame,
        vicon_df: pd.DataFrame,
        foot_marker: str = "RHEE",
        grid_dt_ns: int = 10_000_000,  # 10 ms grid (100 Hz)
) -> int | None:
    """Estimate IMU->Vicon offset by cross-correlating walking signals.

    Heel-strikes appear as spikes in both:
      - vertical accel on the IMU (accel_z, assuming IMU-Z is roughly up;
        confirm axis/sign with a real recording)
      - vertical foot-marker position (z_mm of e.g. RHEE)

    Both are resampled onto a uniform grid, then cross-correlated. The peak
    lag is an independent estimate of the IMU-vs-Vicon offset, in nanoseconds.
    Returns None if there isn't enough overlap to compute.

    Note: this assumes the clock mapping has already been applied to imu_df so
    both signals share the viconpc_ts_ns axis. The residual lag we find here is
    the *remaining* sync error after that correction.
    """
    foot = vicon_df[vicon_df["marker_name"] == foot_marker]
    if foot.empty:
        print(
            f"NOTE: marker {foot_marker!r} not found; skipping xcorr check.",
            file=sys.stderr,
        )
        return None

    # Confirm Vicon Z is up in your lab calibration; some setups use Y.
    vicon_ts = foot["viconpc_ts_ns"].to_numpy(dtype=np.int64)
    vicon_z = foot["z_mm"].to_numpy(dtype=np.float64)

    imu_ts = imu_df["viconpc_ts_ns"].to_numpy(dtype=np.int64)
    # Confirm IMU axis; accel_z depends on sensor orientation.
    imu_az = imu_df["accel_z"].to_numpy(dtype=np.float64)

    # Restrict to the overlapping window so the xcorr isn't dominated by
    # non-overlapping tails.
    lo = max(vicon_ts[0], imu_ts[0])
    hi = min(vicon_ts[-1], imu_ts[-1])
    if hi - lo < 2 * grid_dt_ns:
        print("NOTE: not enough Vicon/IMU overlap for xcorr.", file=sys.stderr)
        return None

    vicon_mask = (vicon_ts >= lo) & (vicon_ts <= hi)
    imu_mask = (imu_ts >= lo) & (imu_ts <= hi)

    _, vicon_u = _resample_to_uniform(vicon_ts[vicon_mask], vicon_z[vicon_mask], grid_dt_ns)
    _, imu_u = _resample_to_uniform(imu_ts[imu_mask], imu_az[imu_mask], grid_dt_ns)

    # Zero-mean both so xcorr isn't dominated by DC offset (gravity in
    # accel, marker baseline height in z).
    vicon_u = vicon_u - vicon_u.mean()
    imu_u = imu_u - imu_u.mean()

    n = min(len(vicon_u), len(imu_u))
    if n < 10:
        return None
    vicon_u = vicon_u[:n]
    imu_u = imu_u[:n]

    # Full cross-correlation. Lag index = (argmax - (n-1)) in grid steps.
    xcorr = np.correlate(imu_u, vicon_u, mode="full")
    lag_steps = int(np.argmax(np.abs(xcorr)) - (n - 1))
    lag_ns = lag_steps * grid_dt_ns
    return lag_ns


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Merge a Level IMU capture with Vicon data.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--imu-session", type=Path, help="Level session folder (has meta-summary.json).")
    src.add_argument("--imu-csv", type=Path, help="A single ACCEL_GYRO CSV.")
    parser.add_argument("--sensor-label", default=None,
                        help="With --imu-session: which sensor to use when several are present, "
                             "e.g. \"Right Foot\".")
    parser.add_argument("--vicon", type=Path, required=True, help="Vicon frames CSV written during collection.")
    parser.add_argument("--offset", type=Path, required=False, default=None,
                        help="clock_offset.json (android two-clock path). "
                             "Required unless --shared-clock.")
    parser.add_argument("--shared-clock", action="store_true",
                        help="Desktop single-machine rig: IMU and Vicon already share the PC "
                             "wallclock, so no offset is applied (--offset is ignored).")
    parser.add_argument("--output", type=Path, required=True, help="Output merged CSV.")
    parser.add_argument("--skip-xcorr", action="store_true",
                        help="Skip the cross-correlation sanity check (faster, less safe).")
    parser.add_argument("--tolerance-ms", type=float, default=20.0,
                        help="merge_asof tolerance in milliseconds (default: 20 ms).")
    args = parser.parse_args()

    # 1. Load IMU and print diagnostics.
    imu_df = load_imu(args.imu_session, args.imu_csv, args.sensor_label)
    print_diagnostics(imu_df, label="IMU")

    # 2. Map IMU timestamps onto the Vicon PC clock.
    if args.shared_clock:
        # Desktop rig: the IMU recorder timestamps its samples off the same PC
        # wallclock that bridge.py's time.time_ns() reads, so IMU and Vicon are
        # already one clock. Join directly.
        imu_df["viconpc_ts_ns"] = imu_df["phone_ts_ns"]
        print("\nShared-clock mode: no offset applied (desktop single-machine rig).")
    else:
        if args.offset is None:
            parser.error("--offset is required unless --shared-clock is set.")
        offset_data = load_clock_offset(args.offset)
        imu_df["viconpc_ts_ns"] = apply_clock_offset(imu_df["phone_ts_ns"], offset_data)
        print(
            f"\nApplied clock offset (start={offset_data['start']['offset_ns']} ns, "
            f"end={offset_data['end']['offset_ns']} ns)."
        )

    # 3. Load Vicon.
    vicon_df = load_vicon_csv(args.vicon)
    print(
        f"\nLoaded Vicon CSV: {len(vicon_df)} rows, "
        f"{vicon_df['frame'].nunique()} frames, "
        f"{vicon_df['marker_name'].nunique()} unique markers."
    )

    # 4. Cross-correlation sanity check (independent offset estimate).
    if not args.skip_xcorr:
        xcorr_lag_ns = estimate_offset_via_xcorr(imu_df, vicon_df)
        if xcorr_lag_ns is not None:
            print(
                f"\nCross-correlation residual lag: {xcorr_lag_ns} ns "
                f"({xcorr_lag_ns / 1e6:+.2f} ms)"
            )
            if abs(xcorr_lag_ns) > CROSS_CORR_DISAGREEMENT_THRESHOLD_NS:
                print(
                    f"WARNING: xcorr residual exceeds "
                    f"{CROSS_CORR_DISAGREEMENT_THRESHOLD_NS / 1e6:.0f} ms threshold. "
                    "Session flagged for review.",
                    file=sys.stderr,
                )

    # 5. Merge.
    tolerance_ns = int(args.tolerance_ms * 1_000_000)
    merged = merge_imu_with_vicon(imu_df, vicon_df, tolerance_ns=tolerance_ns)
    matched = merged.filter(regex=":").notna().any(axis=1).sum()
    print(
        f"\nMerged: {len(merged)} IMU rows, {matched} matched a Vicon frame "
        f"within {args.tolerance_ms} ms."
    )

    # 6. Write out.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output, index=False)
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
