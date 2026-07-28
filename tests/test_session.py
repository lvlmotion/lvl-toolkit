from pathlib import Path

import pytest

from lvl_toolkit import load_session

# Sample sessions live under examples/ (single source, also runnable by users);
# the tests load them directly rather than keeping a duplicate fixtures copy.
EXAMPLES = Path(__file__).parent.parent / "examples"
FIXTURE = EXAMPLES / "app_gait_walk"                 # synthetic app-gait (accel_gyro- prefix)
# Real app-sensor capture (``imu-`` prefix, labels only in the manifest's
# top-level ``sensors`` list): two feet + a "Back" (trunk) sensor.
RAW_SAMPLE = EXAMPLES / "app_sensor_raw_3sensor"

IMU_COLUMNS = ["time", "accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z"]


def test_load_session_metadata():
    s = load_session(FIXTURE)
    assert s.activity_code == "WALK_10_METRE"
    assert s.sensor_placement == "BT_IMU"        # manifest uses sensorPlacement here
    assert len(s.sensors) == 3
    assert s.settings["sample_rate"] == "100"
    # all five manifest entries are surfaced (3 IMU + gait_segments + meta)
    assert len(s.files) == 5


def test_imu_files_loaded_as_dataframes():
    s = load_session(FIXTURE)
    imu = s.imu()
    assert len(imu) == 3
    # labels are kept verbatim (this sample carries them on the file entries)
    assert {f.sensor_label for f in imu} == {"Left Foot", "Right Foot", "Back"}

    left = next(f for f in imu if f.sensor_label == "Left Foot")
    # the base IMU columns are present (real files also carry a trailing frame_number)
    assert list(left.data.columns)[:len(IMU_COLUMNS)] == IMU_COLUMNS
    assert len(left.data) > 1000
    assert left.modality_label == "FILTERED"
    assert left.short_mac == "78B3"


def test_imu_typed_container():
    s = load_session(FIXTURE)
    left = next(f for f in s.imu() if f.sensor_label == "Left Foot")
    dc = left.imu_container()
    assert dc.size() == len(left.data)
    assert dc.data_list[0].accel_y == pytest.approx(5.918339)


def test_gait_segments_generic_dataframe():
    s = load_session(FIXTURE)
    seg = s.by_modality("GAIT_SEGMENTS")[0]
    # custom schema not matching any typed container -> loaded as a DataFrame
    assert "phase" in seg.data.columns
    assert len(seg.data) == 4


def test_meta_entry_listed_without_dataframe():
    s = load_session(FIXTURE)
    meta = s.by_modality("META")[0]
    assert meta.data is None
    assert meta.path is not None  # the json file exists on disk


def test_missing_manifest_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_session(tmp_path)


# --------------------------------------------------------------------------- #
# Raw app-sensor capture (imu- prefix). Labels live only in the top-level
# ``sensors`` list; file entries carry shortMac but no sensorLabel.
# --------------------------------------------------------------------------- #

def test_raw_imu_sensor_placement_from_sensor_type():
    s = load_session(RAW_SAMPLE)
    assert s.activity_code == "BTIMU_RAW"
    assert s.sensor_placement == "BT_IMU"   # manifest uses sensorType, not sensorPlacement
    assert s.source == "app-sensor"


def test_raw_imu_labels_joined_from_sensors_list_verbatim():
    s = load_session(RAW_SAMPLE)
    imu = s.imu()
    assert len(imu) == 3
    # Each file inherits its label from the top-level sensors list (the file
    # entry omits it), and the label is kept exactly as the capture named it --
    # "Back" stays "Back", not remapped to "LUMBAR".
    labels = {f.sensor_label for f in imu}
    assert labels == {"Left Foot", "Right Foot", "Back"}


def test_raw_imu_typed_container_ignores_extra_columns():
    s = load_session(RAW_SAMPLE)
    f = next(iter(s.imu()))
    # raw imu CSVs carry an extra trailing frame_number column; the DataFrame
    # keeps it, the typed container ignores it.
    assert "frame_number" in f.data.columns
    dc = f.imu_container()
    assert dc.size() == len(f.data)


def test_manifest_listed_but_missing_file_is_graceful():
    s = load_session(RAW_SAMPLE)
    # meta-data_records.csv is listed in the manifest but not present on disk
    missing = next(f for f in s.files if f.name == "meta-data_records.csv")
    assert missing.paths == []
    assert missing.data is None
    assert missing.path is None


def test_file_without_a_label_is_blank_not_mac():
    s = load_session(RAW_SAMPLE)
    # the META files carry no sensor label -> blank, never a shortMac substitute
    meta = next(f for f in s.files if f.modality == "META")
    assert meta.sensor_label == ""
