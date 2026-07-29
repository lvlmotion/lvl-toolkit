# lvl_toolkit.vicon — Vicon ↔ IMU sync

Tools for aligning a Level IMU capture with Vicon Nexus motion capture. The
question this subpackage answers is *"which sample lines up with which mocap
frame?"* — and the answer depends on **how many clocks are in play**.

## The four tools

| command | role |
|---|---|
| `lvl-vicon-bridge` | Log Vicon DataStream frames to a long-format CSV (one row per frame·marker) with a PC-wallclock timestamp on each frame. Runs on the Vicon PC. |
| `lvl-vicon-merge` | Join a Level IMU session with a Vicon CSV into one merged dataset. Handles both sync modes below. |
| `lvl-vicon-clocksync` | Measure the phone↔PC clock offset over `adb` (two-clock mode only). |
| `lvl-vicon-pull` | Pull an IMU session off an Android device over `adb` (two-clock mode only). |

`lvl-vicon-bridge` needs `vicon_dssdk` (ships with the Vicon DataStream SDK
installer; not on PyPI). The other three don't.

---

## Two sync modes

The whole difference is **how many machines record**, and therefore how many
clocks the IMU and Vicon timestamps live on.

### 1. Desktop rig — one clock (`--shared-clock`)

The IMU recorder (`app-sensor-desktop`) **and** `lvl-vicon-bridge` run on the
**same Vicon PC**. The IMU's absolute-microsecond `time` and the Vicon frame
stamps (`time.time_ns()` on that PC) are therefore the *same wallclock* — there
is nothing to correct. `merge` joins them directly.

```
┌───────────────── Vicon PC ─────────────────┐
│  app-sensor-desktop  ──►  IMU session CSVs  │   one wallclock
│  lvl-vicon-bridge    ──►  vicon_run01.csv   │   shared by both
└─────────────────────────────────────────────┘
```

```bash
# capture, then merge on the shared clock (no offset):
lvl-vicon-bridge --session-id run01           # logs Vicon frames while you capture
lvl-vicon-merge --shared-clock \
    --imu-session path/to/2026-05-12_..._BTIMU_RAW-run01 \
    --sensor-label "Right Foot" \
    --vicon vicon_run01.csv \
    --output merged/run01.csv
```

This is the preferred mode: fewer moving parts, no clock estimation, and on a
single machine the Nexus UDP trigger can start/stop the IMU recorder per trial
so capture is hands-off.

### 2. Android phone — two clocks (`--offset`)

The IMU records on a **phone**, off-machine, while `lvl-vicon-bridge` records on
the Vicon PC. Now there are **two independent clocks** that drift relative to
each other, so the phone timestamps must be mapped onto the PC clock before the
join.

```
┌── phone ──┐          ┌──────── Vicon PC ────────┐
│ IMU CSVs  │  adb ──► │ lvl-vicon-bridge ► vicon  │   two clocks,
│ (clock A) │          │ clock B                   │   bridged by adb offset
└───────────┘          └───────────────────────────┘
```

`lvl-vicon-clocksync` measures the offset between the two clocks over `adb`
(a round-trip-timed `date +%s%N`), **once at the start and once at the end** of
the session, so `merge` can *linearly interpolate* the offset across the
recording (clocks drift, so a single measurement isn't enough).

```bash
# on the Vicon PC:
lvl-vicon-clocksync --start --session-id run01     # first offset anchor
lvl-vicon-bridge --session-id run01                # capture...
lvl-vicon-clocksync --end   --session-id run01     # second offset anchor

# pull the IMU session off the phone, then merge with the interpolated offset:
lvl-vicon-pull --remote-dir files/data/2026-05-12_..._BTIMU_RAW-run01 \
               --output-dir ./pulled/run01
lvl-vicon-merge \
    --imu-session ./pulled/run01 --sensor-label "Right Foot" \
    --vicon vicon_run01.csv --offset clock_offset.json \
    --output merged/run01.csv
```

Because there's no cross-machine trigger (a phone can't be counted on to receive
Nexus's UDP), the phone recording is **started manually and bracketed** around
each trial — the adb offset plus the heel-strike check below carry the sync,
rather than a frame-accurate trigger.

---

## Heel-strike cross-correlation (both modes)

Whichever mode you use, `merge` runs an **independent** alignment check: it
cross-correlates a vertical-acceleration signal (heel strikes spike in the IMU)
against a vertical foot-marker position (the same strikes spike in Vicon). The
peak lag is a second, physics-based estimate of the offset. If it disagrees with
the clock-based alignment by more than **50 ms**, the session is flagged for
review. Pass `--skip-xcorr` to turn it off.

This is the backstop: in the desktop mode it double-checks the shared clock; in
the phone mode it catches a bad adb offset.

---

## Which do I use?

- **Same machine for IMU + Vicon?** → desktop mode, `--shared-clock`. Simplest,
  most accurate.
- **IMU on a phone?** → two-clock mode: `clock_sync` (×2) + `pull` + `merge
  --offset`.

See the repo [`README.md`](../../README.md) for install and the rest of
lvl-toolkit.
