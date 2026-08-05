# lvl-toolkit

A public companion library for loading and processing Level capture files in Python.

A Level capture **session** is a folder containing a self-describing
`meta-summary.json` manifest plus the data files it lists (IMU CSVs, gait
segments, computed metrics, etc.). `lvl-toolkit` reads that manifest and loads
each file, so you never have to parse the filename grammar yourself.

## Install

```bash
pip install -e .          # from a checkout
# or, once published:
# pip install lvl-toolkit
```

Requires Python 3.9+, `numpy`, `pandas`, and `matplotlib` (graphing).

## Quick start

Two ready-to-load sessions ship under [`examples/`](examples/), one per grammar:

| folder | grammar | contents |
|---|---|---|
| `examples/app_sensor_raw_3sensor/` | `imu-*.csv` | Real app-sensor capture — 3 BT-IMU sensors (both feet + trunk "Back"), raw ACCEL_GYRO |
| `examples/app_gait_walk/` | `accel_gyro-*.csv` | Real 10-metre-walk capture recast to the app-gait file grammar (FILTERED), plus a `GAIT_SEGMENTS` file of swing phases derived from the real foot gyro |

> `app_gait_walk` is a real 3-sensor capture renamed to the `accel_gyro-` grammar
> to exercise that path. Its `gait_segments` file holds swing phases detected from
> the real foot gyro by a simple heuristic (so the band timestamps line up with
> the IMU streams) — illustrative, not the production gait pipeline's output.

Run the bundled demo to see what the toolkit parses out of each (loads both,
prints the session summary and a per-file table of modality / label / role):

```bash
python examples/run.py                       # both bundled samples
python examples/run.py path/to/some_session  # your own session folder
```

## Usage

```python
from lvl_toolkit import load_session

session = load_session("path/to/2026-06-27-..._walk_free")

print(session.activity_code)        # e.g. "WALK_FREE_BTIMU_DUAL_FOOT"
print(session.sensors)              # [{"shortMac": "3484", "sensorLabel": "LEFT_FOOT"}, ...]

# Raw/filtered IMU streams, one per sensor:
for f in session.imu():
    print(f.sensor_label, f.data.shape)   # f.data is a pandas DataFrame
    container = f.imu_container()          # or a typed ImuDataContainer

# Any modality by name:
for seg in session.by_modality("GAIT_SEGMENTS"):
    print(seg.data.head())
```

### What you get

`load_session(folder)` returns a `Session` with:

- `activity_code`, `sensor_placement`, `session_info`, `sensors`, `settings`
- `files`: a list of `LoadedFile`, each with its parsed manifest slots
  (`modality`, `modality_label`, `short_mac`, `sensor_label`, `note`,
  `rotation_count`), the resolved on-disk `path`(s), and the file contents as a
  pandas `DataFrame` (`data`). CSV files are loaded as DataFrames; `ACCEL_GYRO`
  files can also be loaded as a typed `ImuDataContainer` via
  `LoadedFile.imu_container()`.

Files written across multiple rotation segments (`name.001.csv`, `name.002.csv`,
...) are concatenated transparently.

### Batch loading + session shape

Point at a folder that holds many session folders and iterate the ones that are
sessions (one level down; non-session folders are skipped):

```python
from lvl_toolkit import iter_sessions

for session in iter_sessions("~/lvloutput"):
    print(session.activity_code, session.source, session.sensor_labels())
```

- `session.source` → `"app-sensor"` (raw capture) or `"app-gait"` (has processed output files)
- `session.sensor_labels()` → distinct sensor labels present, e.g. `["LEFT_FOOT", "RIGHT_FOOT", "LUMBAR"]`

### Both capture grammars load the same way

The loader is manifest-driven, so it handles both file-naming grammars Level
produces without you caring which is which:

- **`imu-*.csv`** — raw captures from **app-sensor** / **app-sandbox** (modality
  `ACCEL_GYRO`, label `RAW`). These label sensors free-form (`"Left Foot"`,
  `"Back"`) and only in the manifest's top-level `sensors` list — the toolkit
  joins that label onto each file by `shortMac`, so `LoadedFile.sensor_label`
  is populated either way.
- **`accel_gyro-*.csv`** — processed **app-gait** output (often `FILTERED`),
  alongside computed files like `gait_segments-*.csv`.

`LoadedFile.sensor_label` is whatever the capture named the sensor, kept
verbatim (`"Left Foot"`, `"Back"`, `"LEFT_FOOT"`, ...) — or `""` if it was never
named. It is never a `shortMac` substitute; an address is not a location.

## Graphing

Load a session and graph it in two lines — the "run a collection, see your data"
path:

```python
from lvl_toolkit import load_session
from lvl_toolkit.graphing import render_session

session = load_session("path/to/session")
for spec, fig in render_session(session):     # figures chosen by the default schema
    fig.savefig(f"{spec.role}.png")
```

`render_session` draws the figures a **schema** asks for. The default schema
(`lvl_toolkit.activity_map.figures_for`) gives sensible defaults out of the box:
raw IMU for every sensor, a feet stride/swing view for walking-gait sessions, and
a lumbar subplot when present.

### Bring your own schema

A schema is just a `session -> list[FigureSpec]` callable, so you reuse the whole
renderer (colors, overlays, layout) and only decide *which* figures appear. Copy
`activity_map.py`, change the rules, and pass it in:

```python
from lvl_toolkit.activity_map import FigureSpec, RAW_IMU_MODALITIES
from lvl_toolkit.graphing import render_session

def my_figures_for(session):
    return [FigureSpec("raw_all", "Raw IMU", RAW_IMU_MODALITIES)]

render_session(session, schema=my_figures_for)
```

See `activity_map.py` for the field-by-field walkthrough and a worked custom
example. `examples/run.py` graphs the two bundled samples end-to-end.

## Typed CSV containers

`lvl_toolkit.csv_io` provides typed readers (each subclasses `DataContainerBase`)
that mirror the Level app / KMP CLI column schema — reach for one when you want
row objects or numpy arrays instead of the pandas `DataFrame` `load_session`
already puts on `LoadedFile.data`:

- **`ImuDataContainer`** — accel + gyro (`ACCEL_GYRO`); `to_numpy()` → `(time_us, accel, gyro)`. Extra trailing columns (e.g. `frame_number` on raw `imu-` files) are ignored.
- **`AngleDataContainer`** — computed joint angles (`JOINT_ANGLE`); pass the `JointEstimatorMode` the file was written with.
- **`SegmentDataContainer`** — rep/phase boundaries (`GAIT_SEGMENTS`, `STATE_CHANGES`, ...); each row a `Segment(start_time, end_time, start_ind, end_ind, segment_type, notes)`.

```python
from lvl_toolkit.csv_io import ImuDataContainer

dc = ImuDataContainer()
dc.load_from_csv("imu-left foot-78b3.csv")   # or accel_gyro-filtered-3484-left_foot.csv
time_us, accel, gyro = dc.to_numpy()         # each accel/gyro is (n, 3)
```

## Vicon sync

`lvl_toolkit.vicon` aligns a Level IMU capture with Vicon Nexus motion capture.
It installs four console scripts:

| command | what it does |
|---|---|
| `lvl-vicon-bridge` | Log Vicon DataStream frames to a long-format CSV (one row per frame·marker) with a PC-wallclock timestamp. Runs on the Vicon PC. |
| `lvl-vicon-merge` | Join a Level IMU session with a Vicon CSV into one merged dataset. |
| `lvl-vicon-pull` | Pull an IMU session off an Android device over `adb` (the phone path). |
| `lvl-vicon-clocksync` | Record the phone↔PC clock offset for the phone path. |

Two capture topologies, and `merge` handles both:

- **Desktop rig** (`--shared-clock`): the IMU recorder and `lvl-vicon-bridge`
  run on the *same* Vicon PC, so IMU microseconds and Vicon frame stamps are
  already one wallclock — no clock correction needed.
- **Phone path**: phone and Vicon PC are two clocks. `lvl-vicon-clocksync`
  measures the offset (via `adb`) at the start and end of a session, and
  `merge` linearly interpolates it across the recording.

```bash
# Desktop rig: IMU is a Level session folder, Vicon is bridge.py's CSV.
lvl-vicon-merge --shared-clock \
    --imu-session path/to/2026-05-12_10-03-40-BTIMU_RAW-run01 \
    --sensor-label "Right Foot" \
    --vicon vicon_run01.csv \
    --output merged/run01.csv
```

The IMU side is read through `load_session`, so the manifest, rotations and
sensor labels are handled for you. `merge` also runs a heel-strike
cross-correlation as an independent check on the alignment and flags the session
if it disagrees with the clock estimate by more than 50 ms.

`lvl-vicon-bridge` additionally requires `vicon_dssdk`, which ships with the
Vicon DataStream SDK installer (not on PyPI); the other three tools don't.

## Scope

This version is **manifest-first**: it loads sessions that contain a
`meta-summary.json`. Folders without a manifest are not supported.

## Development

```bash
pip install -e ".[dev]"
pytest
```
