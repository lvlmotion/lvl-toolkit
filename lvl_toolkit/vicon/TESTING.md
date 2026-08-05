# Testing the Vicon sync (local / pre-lab)

Two things to prove before a lab visit:

1. **Trigger + record path** — the desktop app hears a Nexus capture trigger and
   starts/stops/discards recording correctly, tagging the session and (if
   present) spawning the mocap logger.
2. **Merge** — the IMU and Vicon streams line up.

You can validate **(1) entirely on your own machine with no Vicon hardware**,
using a tiny UDP simulator that impersonates Nexus's capture broadcast.

---

## 0. What you need

- **app-sensor-desktop** (the Kotlin desktop app) runnable — either the installed
  build, or from the repo: `gradlew.bat :app-sensor-desktop:run` (Windows) /
  `./gradlew :app-sensor-desktop:run` (Linux/macOS).
- **Python 3.9+** (for the simulator and the merge CLI).
- *Optional* — a dongle + at least one IMU sensor, to record real data. **Not
  needed** to prove the trigger plumbing.
- *Optional* — Nexus + the Vicon DataStream SDK, only for testing `bridge.py`
  against a real/replay Nexus (Section 2).

Port note: on **Windows** UDP port `30` works as-is. On **Linux**, port 30 is
privileged (<1024) — use a high port (e.g. `30030`) and set the same value in
the app's Vicon panel and the simulator.

---

## 1. Desk test — trigger + record, no Vicon needed

### 1a. Save the simulator

Save this as `simulate_trigger.py`:

```python
import socket, sys, time

PORT = 30                 # Windows: 30. Linux: use >1024 (e.g. 30030) and match the app.
HOST = "127.0.0.1"

def send(xml: str):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto((xml + "\x00").encode(), (HOST, PORT))   # Nexus packets are null-terminated
    s.close()
    print("sent:", xml[:48], "...")

name = sys.argv[1] if len(sys.argv) > 1 else "deskTest01"
result = sys.argv[2] if len(sys.argv) > 2 else "SUCCESS"   # SUCCESS | CANCEL | FAIL

send(f'<CaptureStart><Name VALUE="{name}"/><Delay VALUE="0"/><PacketID VALUE="1"/></CaptureStart>')
print("recording for 5s...")
time.sleep(5)
send(f'<CaptureStop RESULT="{result}"><Name VALUE="{name}"/><PacketID VALUE="2"/></CaptureStop>')
```

### 1b. Launch the app and arm

1. Start app-sensor-desktop.
2. *(To record real data)* **Scan** -> tick a sensor -> **Connect**.
3. In the **Vicon sync** row, set the port to `30` (Windows) and click **Arm**.
   The **Logs** box should show `Armed on udp:30 - waiting for Nexus`, and note
   whether a mocap logger is ready or it's `IMU-only (no bridge.py found)`.

### 1c. Fire a trigger

```
python simulate_trigger.py deskTest01 SUCCESS
```

Watch the **Logs** box:

- **No sensor connected** -> `Heard Vicon trigger 'deskTest01'` then
  `Ignored: no sensors connected`. This alone proves the UDP listener + XML
  parser work end-to-end.
- **Sensor connected** -> `Recording 'deskTest01' ...` -> (5s) ->
  `Finished 'deskTest01'`. A session folder `..._BTIMU_RAW-desttest01/` appears
  containing per-sensor CSVs and a `vicon-anchor.json`.
- **bridge.py present** next to the app -> an extra `... mocap logger started`
  line. **Absent** -> `Heard Vicon trigger ... but bridge.py was NOT found -
  expected at: <paths>` (this is the message you want to see so you know where
  to drop it later).

### 1d. Test the discard path

```
python simulate_trigger.py badTake01 CANCEL
```

Log shows `Discarded 'badTake01' (CANCEL)` and the partial session folder is
deleted. (This is why the mocap logger is stopped *before* the folder is removed
- a still-open file would block deletion on Windows.)

### What Section 1 proves

The UDP listener, the Nexus XML parsing, the per-trial folder naming, the anchor
write, the multi-trial start/stop lifecycle, the discard cleanup, and the
bridge-present/absent branch - all without any Vicon system.

---

## 2. (Optional) bridge.py against a local Nexus

Only if you've installed Nexus + the DataStream SDK locally.

1. Install the toolkit into the python that has `vicon_dssdk`:
   `pip install -e .` from the lvl-toolkit checkout.
2. Point the app at that interpreter: create `bridge-python.txt` next to the app
   (one line = the python executable path), or set `LVL_BRIDGE_PYTHON`.
3. Drop `bridge.py`'s location on the app's search path - next to the launcher.
   (Edit `DEFAULT_VICON_HOST` at the top of `bridge.py` if Nexus isn't on
   `localhost:801`.)
4. Start Nexus streaming (live or a replay). Sanity-check the logger directly:
   `lvl-vicon-bridge --max-frames 200` -> confirm it prints advancing frame
   counts and writes a CSV.
5. Now Arm the app and either fire the simulator (Section 1c) or use Nexus's own
   UDP trigger (Nexus Preferences -> UDP capture broadcast/trigger, Arm on,
   broadcast to loopback). Each trial should now also produce a
   `vicon_<name>.csv` inside the session folder.

---

## 3. Merge check

The merge logic is covered by the unit tests over the bundled example session:

```
pip install -e ".[dev]"
pytest tests/test_vicon_merge.py -v
```

A live CLI merge needs a real Vicon CSV from `bridge.py`; once you have a
desk/lab recording plus its `vicon_<name>.csv`:

```
lvl-vicon-merge --shared-clock \
    --imu-session path/to/..._BTIMU_RAW-run01 \
    --sensor-label "Right Foot" \
    --vicon path/to/..._BTIMU_RAW-run01/vicon_run01.csv \
    --output merged/run01.csv
```

Expected output ends with `Merged: N IMU rows, M matched a Vicon frame within
20.0 ms.` `M` should be a large fraction of `N`; if `M` is ~0, the two streams
aren't on the same clock (wrong mode, or the offset is off).

---

## 4. At the lab (bring-up order)

1. **Bridge connectivity** - `lvl-vicon-bridge --max-frames 200` against live
   Nexus; confirm frames log and frame numbers advance.
2. **Trigger path** - enable Nexus's UDP trigger, Arm the app, hit Capture in
   Nexus; confirm the app logs `Heard Vicon trigger ...` (not just the
   simulator).
3. **One throwaway trial** end-to-end -> `lvl-vicon-merge --shared-clock` ->
   eyeball the heel-strike alignment (walk with the foot marker + foot IMU).
4. **Real capture.** For the desktop rig keep `--shared-clock`; for a phone-based
   IMU use the two-clock path (`clock_sync` x2 -> `pull` -> `merge --offset`) -
   see [`README.md`](README.md).

---

## Troubleshooting

| symptom | cause / fix |
|---|---|
| Arm does nothing / `Arm failed` | Port already bound, or (Linux) port <1024 without privilege - use a high port in both app and simulator. |
| `Ignored: no sensors connected` | Trigger was heard, but no sensor is connected - Scan/Connect first, or ignore if you're only testing the trigger. |
| `bridge.py NOT found` | Expected until you drop `bridge.py` in one of the listed paths. Harmless - records IMU-only. |
| bridge spawns then dies immediately | `vicon_dssdk` not importable by the chosen python - fix `bridge-python.txt` / `LVL_BRIDGE_PYTHON`. |
| merge: `M` matched ~0 | Wrong sync mode or bad offset - desktop rig must use `--shared-clock`; phone path needs a valid `clock_offset.json`. |
