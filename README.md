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

Or create a conda environment (installs the deps and the package in editable mode):

```bash
conda env create -f environment.yml
conda activate lvl-toolkit
```

Requires Python 3.9+, `numpy`, and `pandas`.

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

## Scope

This version is **manifest-first**: it loads sessions that contain a
`meta-summary.json`. Folders without a manifest are not supported.

## Development

```bash
pip install -e ".[dev]"
pytest
```
