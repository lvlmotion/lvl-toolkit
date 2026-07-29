"""
pull_imu.py

Helper that pulls IMU recordings out of the LVL app-sensor app's private
storage on the connected Android device (the android/phone capture path — the
desktop rig writes straight to the local FS and needs no pull).

We can't use plain `adb pull` for files inside an app's private dir (they
sit under /data/data/<pkg>/..., which is not world-readable). Instead we
go through `run-as`, which runs as the app's UID, and stream the bytes to
stdout with `cat`. `adb exec-out` is the right command for streaming
binary/raw output without the line-ending mangling that `adb shell` does.

app-sensor writes an FPB session folder (per-sensor CSVs + summary.json +
vicon-anchor.json), so --remote-dir pulls the whole trial folder in one go;
--remote-file still pulls a single file.

Examples:

    # Whole session folder (recommended for app-sensor).
    python pull_imu.py \\
        --remote-dir files/data/2026-05-12_10-03-40-BTIMU_RAW-run01 \\
        --output-dir ./pulled/run01

    # Single file.
    python pull_imu.py \\
        --remote-file files/data/2026-05-12_10-03-40-BTIMU_RAW-run01/accel_gyro-raw-left_foot-ae60.csv \\
        --output ./pulled/accel_gyro-raw-left_foot-ae60.csv
"""

from __future__ import annotations  # 3.9-safe `list[str]` annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


# app-sensor's Android package. Override with --package for a different build
# (e.g. a `.debug` suffix or a repackaged variant).
DEFAULT_PACKAGE = "com.lvlmotion.appsensor"


def check_adb_available() -> None:
    if shutil.which("adb") is None:
        print(
            "ERROR: `adb` was not found on PATH. Install Android platform-tools "
            "and make sure `adb` is on your PATH.",
            file=sys.stderr,
        )
        sys.exit(1)


def pull_file(remote_file: str, output_path: Path, package: str) -> None:
    """Stream a file from the app sandbox to a local path.

    `remote_file` is the path *relative to the app's private dir*, e.g.
    "files/data/<session>/accel_gyro-raw-left_foot-ae60.csv". `run-as` cd's
    into the app home before running, so we don't prepend /data/data/<pkg>/.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Using exec-out (not shell) keeps stdout as raw bytes -- important so
    # we don't accidentally corrupt the CSV with CRLF translation. We pass
    # `cat` to run-as so it executes under the app's UID.
    cmd = ["adb", "exec-out", "run-as", package, "cat", remote_file]

    try:
        with open(output_path, "wb") as out:
            result = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError:
        # Shouldn't hit this since we checked adb above, but just in case.
        print("ERROR: adb not found.", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        # Clean up the empty/partial file so we don't leave junk on disk.
        try:
            output_path.unlink()
        except OSError:
            pass

        # Common failure modes worth calling out clearly.
        lower = stderr.lower()
        if "no devices" in lower or "device not found" in lower:
            print("ERROR: No adb device connected.", file=sys.stderr)
        elif "unauthorized" in lower:
            print("ERROR: Device unauthorized. Accept the USB debugging prompt on the phone.",
                  file=sys.stderr)
        elif "run-as: package not debuggable" in lower or "not debuggable" in lower:
            print(
                f"ERROR: Package {package} is not debuggable, so run-as can't access it. "
                "Make sure you're using a debug build of the app.",
                file=sys.stderr,
            )
        elif "no such file" in lower:
            print(f"ERROR: Remote file not found: {remote_file}", file=sys.stderr)
        else:
            print(f"ERROR: adb command failed (exit {result.returncode}): {stderr}",
                  file=sys.stderr)
        sys.exit(1)

    size = output_path.stat().st_size
    if size == 0:
        # cat succeeded but produced nothing -- treat as an error so we
        # don't silently overwrite something with an empty file.
        print(f"ERROR: Pulled file is empty: {remote_file}", file=sys.stderr)
        output_path.unlink()
        sys.exit(1)

    print(f"Pulled {remote_file} -> {output_path} ({size} bytes)")


def list_dir(remote_dir: str, package: str) -> list[str]:
    """List the file names in a sandbox directory via `run-as ... ls -1`.

    Returns bare entry names (not full paths). Exits on failure so callers
    don't proceed with a partial/empty listing.
    """
    cmd = ["adb", "exec-out", "run-as", package, "ls", "-1", remote_dir]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        print(f"ERROR: could not list {remote_dir}: {stderr}", file=sys.stderr)
        sys.exit(1)
    names = [
        line.strip()
        for line in result.stdout.decode("utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    return names


def pull_dir(remote_dir: str, output_dir: Path, package: str) -> None:
    """Pull every file in a sandbox session folder into `output_dir`.

    Non-recursive (app-sensor session folders are flat — per-sensor CSVs plus
    summary.json / vicon-anchor.json). `run-as ls` doesn't distinguish files
    from subdirs cleanly across devices, so a `cat` on a subdir just fails that
    one entry and we keep going.
    """
    names = list_dir(remote_dir, package)
    if not names:
        print(f"ERROR: session folder is empty: {remote_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    pulled = 0
    for name in names:
        remote_file = f"{remote_dir.rstrip('/')}/{name}"
        cmd = ["adb", "exec-out", "run-as", package, "cat", remote_file]
        dest = output_dir / name
        with open(dest, "wb") as out:
            result = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0 or dest.stat().st_size == 0:
            # Likely a subdirectory or an unreadable entry — skip, don't abort.
            try:
                dest.unlink()
            except OSError:
                pass
            print(f"  skipped {name}", file=sys.stderr)
            continue
        pulled += 1
        print(f"  pulled {name} ({dest.stat().st_size} bytes)")

    if pulled == 0:
        print(f"ERROR: nothing pulled from {remote_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"Pulled {pulled} file(s) from {remote_dir} -> {output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Pull IMU recordings from the app-sensor app's private storage via adb run-as."
    )
    parser.add_argument(
        "--package",
        default=DEFAULT_PACKAGE,
        help=f"Android package to pull from (default: {DEFAULT_PACKAGE}).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--remote-file",
        help="Single file inside the sandbox, e.g. files/data/<session>/accel_gyro-raw-left_foot-ae60.csv",
    )
    mode.add_argument(
        "--remote-dir",
        help="Session folder inside the sandbox, e.g. files/data/<session> — pulls all files.",
    )
    parser.add_argument("--output", type=Path, help="Destination path (with --remote-file).")
    parser.add_argument("--output-dir", type=Path, help="Destination folder (with --remote-dir).")
    args = parser.parse_args()

    check_adb_available()

    if args.remote_file:
        if args.output is None:
            parser.error("--output is required with --remote-file.")
        pull_file(args.remote_file, args.output, args.package)
    else:
        if args.output_dir is None:
            parser.error("--output-dir is required with --remote-dir.")
        pull_dir(args.remote_dir, args.output_dir, args.package)


if __name__ == "__main__":
    main()