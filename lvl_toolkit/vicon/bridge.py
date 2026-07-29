"""
bridge.py

Runs on the Vicon PC. Connects to the Vicon DataStream SDK (default
localhost:801, served by Nexus/Tracker/Shogun/Evoke), pulls per-frame
marker data, and writes a long-format CSV with a Vicon-PC wallclock
timestamp on every frame.

Output CSV columns:
    frame, viconpc_ts_ns, subject, marker_name, x_mm, y_mm, z_mm, occluded

Each frame becomes (num_subjects * num_markers) rows. Wide-vs-long: we
keep it long because marker sets can change session to session and a
fixed wide schema would be a pain to maintain. merge.py pivots wide as
needed.

Example:
    python bridge.py --session-id 2026-05-12_run01

Stop with Ctrl-C. The CSV is flushed every N frames (configurable) so
you don't lose data if the script is killed.

Requires the vicon_dssdk Python package (ships with the DataStream SDK
installer; see https://docs.vicon.com for install instructions).
"""

import argparse
import csv
import datetime as dt
import os
import signal
import sys
import time
from pathlib import Path

try:
    from vicon_dssdk import ViconDataStream
except ImportError:
    # We don't fail at import time so the file can still be linted / tested
    # on machines without the SDK installed. The check happens in main().
    ViconDataStream = None  # type: ignore


CSV_HEADER = [
    "frame",
    "viconpc_ts_ns",
    "subject",
    "marker_name",
    "x_mm",
    "y_mm",
    "z_mm",
    "occluded",
]


def auto_session_id() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def default_output_dir(session_id: str) -> Path:
    """Mirror clock_sync.py's convention: <desktop>/lvl_vicon/<session>/."""
    if os.name == "nt":
        base = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "lvl_vicon"
    else:
        base = Path.home() / "Desktop" / "lvl_vicon"
    return base / session_id


def connect(host: str) -> "ViconDataStream.Client":
    """Connect to the Vicon DataStream server and enable marker data."""
    client = ViconDataStream.Client()
    print(f"Connecting to {host}...", flush=True)
    # Connect is blocking and may fail; loop with a short backoff. Most
    # of the time it succeeds on the first try.
    for attempt in range(10):
        try:
            client.Connect(host)
            if client.IsConnected():
                break
        except ViconDataStream.DataStreamException as exc:
            print(f"  attempt {attempt + 1}: {exc}", flush=True)
        time.sleep(0.5)

    if not client.IsConnected():
        print(f"ERROR: could not connect to {host}.", file=sys.stderr)
        sys.exit(1)

    print("Connected.")

    # Enable labeled marker data. Segment/device data not needed for now;
    # turn them on here if downstream analysis ever requires them.
    client.EnableMarkerData()

    # ServerPush is the lowest-latency mode -- GetFrame blocks until the
    # next frame is available from the server. ClientPull would let us
    # poll, but we want every frame.
    client.SetStreamMode(ViconDataStream.Client.StreamMode.EServerPush)

    return client


def read_frame_rows(client: "ViconDataStream.Client", frame_num: int, ts_ns: int):
    """Yield one long-format row per (subject, marker) in the current frame."""
    for subject in client.GetSubjectNames():
        for marker in client.GetMarkerNames(subject):
            # GetMarkerNames returns a list of (name, parent_segment) tuples
            # in some SDK versions, and bare strings in others. Normalize.
            marker_name = marker[0] if isinstance(marker, (tuple, list)) else marker
            try:
                (x, y, z), occluded = client.GetMarkerGlobalTranslation(subject, marker_name)
            except ViconDataStream.DataStreamException as exc:
                # Marker temporarily not available -- log once, keep going.
                print(f"  warn: {subject}/{marker_name}: {exc}", file=sys.stderr)
                continue
            yield [
                frame_num,
                ts_ns,
                subject,
                marker_name,
                x,
                y,
                z,
                int(bool(occluded)),
            ]


def main():
    parser = argparse.ArgumentParser(description="Stream Vicon frames to a CSV.")
    parser.add_argument(
        "--host",
        default="localhost:801",
        help="DataStream server (default: localhost:801).",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Session ID. Defaults to YYYY-MM-DD_HH-MM-SS.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV path. Defaults to "
             "<desktop>/lvl_vicon/<session_id>/vicon_<session_id>.csv.",
    )
    parser.add_argument(
        "--flush-every",
        type=int,
        default=100,
        help="Flush CSV every N frames (default: 100).",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Stop after this many frames (default: run until Ctrl-C).",
    )
    args = parser.parse_args()

    if ViconDataStream is None:
        print(
            "ERROR: vicon_dssdk is not installed. Install it from the "
            "DataStream SDK Python directory (see Vicon docs).",
            file=sys.stderr,
        )
        sys.exit(1)

    session_id = args.session_id or auto_session_id()
    if args.output is None:
        out_dir = default_output_dir(session_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"vicon_{session_id}.csv"
    else:
        output_path = args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Session: {session_id}")
    print(f"Output:  {output_path}")

    client = connect(args.host)

    # Graceful shutdown on Ctrl-C: flag set by handler, loop checks it.
    stop = {"flag": False}

    def handle_sigint(signum, frame):
        print("\nCtrl-C received; finishing current frame and exiting...")
        stop["flag"] = True

    signal.signal(signal.SIGINT, handle_sigint)

    frames_written = 0
    rows_written = 0

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)

        # Discard the first frame because GetSubjectNames sometimes returns
        # empty until the stream is warm. Cheap insurance.
        try:
            client.GetFrame()
        except ViconDataStream.DataStreamException:
            pass

        while not stop["flag"]:
            try:
                got = client.GetFrame()
            except ViconDataStream.DataStreamException as exc:
                print(f"GetFrame failed: {exc}", file=sys.stderr)
                break
            if not got:
                continue

            # Timestamp the PC wallclock as close to receiving the frame as
            # possible. Per the design doc this is what merge.py joins on.
            ts_ns = time.time_ns()
            frame_num = client.GetFrameNumber()

            for row in read_frame_rows(client, frame_num, ts_ns):
                writer.writerow(row)
                rows_written += 1

            frames_written += 1

            if frames_written % args.flush_every == 0:
                f.flush()
                # Drop a progress line every flush so a running tail shows life.
                print(f"  frames={frames_written}, rows={rows_written}", flush=True)

            if args.max_frames is not None and frames_written >= args.max_frames:
                break

    try:
        client.Disconnect()
    except Exception:
        pass

    print(f"\nDone. Wrote {frames_written} frames / {rows_written} rows to {output_path}")


if __name__ == "__main__":
    main()