"""
clock_sync.py

Capture the offset between the Android phone clock and the Vicon PC
wallclock by asking the phone for its time via `adb shell date +%s%N` and
comparing to `time.time_ns()` on the PC.

Run once at the start of a recording session and once at the end:

    python clock_sync.py --start --session-id 2026-05-12_run01
    # ... record session ...
    python clock_sync.py --end   --session-id 2026-05-12_run01

Both runs update the same clock_offset.json so merge.py can do
linear-interp drift correction.

Default output (when --output not given):
    %USERPROFILE%\\Desktop\\lvl_vicon\\<session_id>\\clock_offset.json   (Windows)
    ~/Desktop/lvl_vicon/<session_id>/clock_offset.json                   (other)

JSON shape:
    {
      "start": {"phone_ts_ns": ..., "viconpc_ts_ns": ..., "offset_ns": ...},
      "end":   {"phone_ts_ns": ..., "viconpc_ts_ns": ..., "offset_ns": ...}
    }

offset_ns = viconpc_ts_ns - phone_ts_ns
(i.e. add offset_ns to a phone timestamp to get the PC equivalent.)
"""

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def auto_session_id() -> str:
    """YYYY-MM-DD_HH-MM-SS, matching the design doc convention."""
    return dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def default_output_for_session(session_id: str) -> Path:
    """Build the default clock_offset.json path for a session.

    Windows: %USERPROFILE%\\Desktop\\lvl_vicon\\<session>\\clock_offset.json
    Other:   ~/Desktop/lvl_vicon/<session>/clock_offset.json
    """
    if os.name == "nt":
        base = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "lvl_vicon"
    else:
        base = Path.home() / "Desktop" / "lvl_vicon"
    return base / session_id / "clock_offset.json"


def check_adb_available() -> None:
    """Exit if `adb` isn't on PATH."""
    if shutil.which("adb") is None:
        print(
            "ERROR: `adb` was not found on PATH. Install Android platform-tools "
            "and make sure `adb` is on your PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

def take_sample(n_samples: int = 30, settle: float = 0.05) -> dict:
    """Take N samples via a single persistent adb shell process.

    Opens one `adb shell` (paying the startup cost once), then sends N
    `date +%s%N` commands through stdin. Each command is bracketed by
    time.time_ns() reads on the PC side. Returns the sample with the
    lowest round-trip time, midpoint-corrected.

    On a USB connection the first sample after shell open is still slow
    (shell warmup); we discard a couple of leading samples via `settle`.
    """
    proc = subprocess.Popen(
        ["adb", "shell"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    samples = []
    try:
        # Warm up: send a couple of throwaway commands first so the shell
        # is fully initialized before we start timing.
        for _ in range(2):
            proc.stdin.write(b"date +%s%N\n")
            proc.stdin.flush()
            proc.stdout.readline()
        time.sleep(settle)

        for _ in range(n_samples):
            pc_before = time.time_ns()
            proc.stdin.write(b"date +%s%N\n")
            proc.stdin.flush()
            line = proc.stdout.readline().strip()
            pc_after = time.time_ns()
            if not line.isdigit():
                continue
            samples.append((int(line), pc_after, pc_after - pc_before))
    finally:
        try:
            proc.stdin.write(b"exit\n")
            proc.stdin.flush()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    if not samples:
        print("ERROR: no valid samples from adb shell.", file=sys.stderr)
        sys.exit(1)

    phone_ts_ns, pc_after_ns, best_rtt = min(samples, key=lambda s: s[2])
    pc_at_phone_read_ns = pc_after_ns - best_rtt // 2
    offset_ns = pc_at_phone_read_ns - phone_ts_ns

    print(f"  (took {len(samples)} samples, best RTT = {best_rtt / 1e6:.2f} ms, "
          f"median RTT = {sorted(s[2] for s in samples)[len(samples)//2] / 1e6:.2f} ms)")

    return {
        "phone_ts_ns": phone_ts_ns,
        "viconpc_ts_ns": pc_at_phone_read_ns,
        "offset_ns": offset_ns,
    }

def load_existing(output_path: Path) -> dict:
    if output_path.exists():
        with open(output_path, "r") as f:
            return json.load(f)
    return {}


def save(output_path: Path, data: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Record phone-vs-Vicon-PC clock offset via adb."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--start", action="store_true", help="Record start-of-session offset.")
    mode.add_argument("--end", action="store_true", help="Record end-of-session offset.")

    parser.add_argument(
        "--session-id",
        default=None,
        help="Session ID. Defaults to YYYY-MM-DD_HH-MM-SS for --start; "
             "required (or use --output) for --end so we hit the same file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to clock_offset.json. If omitted, defaults to "
             "<desktop>/lvl_vicon/<session_id>/clock_offset.json.",
    )
    args = parser.parse_args()

    check_adb_available()

    # Resolve session_id and output path.
    if args.session_id is None:
        if args.end and args.output is None:
            print(
                "ERROR: --end needs either --session-id or --output so it "
                "can find the file created by --start.",
                file=sys.stderr,
            )
            sys.exit(1)
        session_id = auto_session_id()
    else:
        session_id = args.session_id

    output_path = args.output if args.output is not None else default_output_for_session(session_id)

    which = "start" if args.start else "end"
    print(f"Session: {session_id}")
    print(f"Recording {which} offset...")

    sample = take_sample()
    print(f"phone_ts_ns:   {sample['phone_ts_ns']}")
    print(f"viconpc_ts_ns: {sample['viconpc_ts_ns']}")
    print(f"offset_ns:     {sample['offset_ns']}  ({sample['offset_ns'] / 1e9:+.6f} s)")

    # Merge into the existing file so --start and --end can be run separately.
    data = load_existing(output_path)
    data[which] = sample
    # Stash session_id in the file too so it's self-describing.
    data["session_id"] = session_id
    save(output_path, data)

    print(f"\nWrote {output_path}")
    if which == "start":
        print(f"At end of session, run: python clock_sync.py --end --session-id {session_id}")


if __name__ == "__main__":
    main()