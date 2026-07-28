"""Manifest-first session loader for Level files.

A Level capture session is a folder containing a self-describing
``meta-summary.json`` manifest plus the CSV/JSON files it lists. This module
reads that manifest and loads each file, so callers never have to parse the
filename grammar themselves.

Usage::

    from lvl_toolkit import load_session
    session = load_session("path/to/2026-06-27-...-walk_free")
    for f in session.imu():
        print(f.sensor_label, f.data.shape)

Folders without a ``meta-summary.json`` are not supported in this version.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .csv_io import ImuDataContainer

SUMMARY_GLOB = "*meta-summary.json"


@dataclass
class LoadedFile:
    """One file listed in the manifest, with its parsed slots and contents."""
    name: str                          # canonical base name (rotation suffix stripped)
    modality: str                      # e.g. "ACCEL_GYRO"
    modality_label: Optional[str]      # e.g. "FILTERED"
    short_mac: Optional[str]
    sensor_label: str                  # whatever the capture named it, verbatim ("" if none)
    note: Optional[str]
    rotation_count: int
    paths: List[Path]                  # actual on-disk segment(s), in order
    data: Optional[pd.DataFrame]       # CSV contents (None for non-CSV / missing)

    @property
    def path(self) -> Optional[Path]:
        return self.paths[0] if self.paths else None

    def imu_container(self) -> ImuDataContainer:
        """Load this file as a typed ImuDataContainer (ACCEL_GYRO files)."""
        if not self.paths:
            raise FileNotFoundError(f"No file on disk for {self.name}")
        dc = ImuDataContainer()
        dc.load_from_csv(str(self.paths[0]))
        for extra in self.paths[1:]:
            tmp = ImuDataContainer()
            tmp.load_from_csv(str(extra))
            for pkt, t in zip(tmp.data_list, tmp.time_list):
                dc.add(pkt, t)
        return dc


@dataclass
class Session:
    """A loaded Level capture session."""
    folder: Path
    activity_code: str
    sensor_placement: str
    session_info: Dict
    sensors: List[Dict]
    settings: Dict
    files: List[LoadedFile]
    manifest: Dict = field(repr=False)

    def by_modality(self, modality: str) -> List[LoadedFile]:
        return [f for f in self.files if f.modality == modality]

    def imu(self) -> List[LoadedFile]:
        """All raw/filtered IMU files (modality ACCEL_GYRO)."""
        return self.by_modality("ACCEL_GYRO")

    def sensor_labels(self) -> List[str]:
        """Distinct sensor labels present in this session (e.g. LEFT_FOOT,
        RIGHT_FOOT, LUMBAR), in manifest order. Useful for deciding which
        graphs a session supports."""
        seen: List[str] = []
        for s in self.sensors:
            label = s.get("sensorLabel")
            if label and label not in seen:
                seen.append(label)
        return seen

    @property
    def source(self) -> str:
        """Best-effort origin: ``"app-gait"`` if the session carries processed
        output files (gait segments, metrics, state changes, ...), else
        ``"app-sensor"`` (raw sensor capture only). Heuristic, based on the file
        modalities the manifest lists."""
        raw_only = {"ACCEL_GYRO", "MAG", "META", "DEBUG", "UNDEFINED"}
        return "app-gait" if any(f.modality not in raw_only for f in self.files) else "app-sensor"


def _resolve_paths(folder: Path, name: str) -> List[Path]:
    """Resolve a manifest entry name to its on-disk file(s).

    Single-segment files are stored under the canonical name; rotated sessions
    write ``{stem}.NNN{ext}`` segments. Return whatever exists, in order.
    """
    exact = folder / name
    if exact.exists():
        return [exact]
    stem, ext = os.path.splitext(name)
    segments = sorted(folder.glob(f"{stem}.[0-9][0-9][0-9]{ext}"))
    return list(segments)


def find_manifest(folder: Path) -> Optional[Path]:
    """Locate the meta-summary.json in a session folder (non-recursive)."""
    matches = sorted(folder.glob(SUMMARY_GLOB))
    return matches[0] if matches else None


def load_session(folder) -> Session:
    """Load a Level session folder via its meta-summary.json manifest."""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder}")

    manifest_path = find_manifest(folder)
    if manifest_path is None:
        raise FileNotFoundError(
            f"No meta-summary.json in {folder}. Manifest-less folders are not "
            f"supported in this version."
        )

    manifest = json.loads(manifest_path.read_text())
    session_info = manifest.get("session", {})

    # Raw captures (app-sensor / app-sandbox) put the sensor label only in the
    # top-level ``sensors`` list, keyed by shortMac, not on each file entry.
    # Build a mac -> label map so file entries can inherit it.
    label_by_mac: Dict[str, str] = {}
    for sdef in manifest.get("sensors", []):
        mac = sdef.get("shortMac")
        if mac and sdef.get("sensorLabel"):
            label_by_mac[str(mac).upper()] = sdef["sensorLabel"]

    files: List[LoadedFile] = []
    for entry in manifest.get("files", []):
        name = entry["name"]
        paths = _resolve_paths(folder, name)
        data: Optional[pd.DataFrame] = None
        if paths and name.lower().endswith(".csv"):
            frames = [pd.read_csv(p) for p in paths]
            data = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
        # The label is whatever the capture named the sensor, taken verbatim.
        # Raw captures carry it only in the top-level ``sensors`` list, so a file
        # entry may inherit it by shortMac. If nothing named it, it stays blank
        # -- a shortMac is an address, not a location, so it is never used here.
        sensor_label = entry.get("sensorLabel")
        if sensor_label is None and entry.get("shortMac"):
            sensor_label = label_by_mac.get(str(entry["shortMac"]).upper())
        sensor_label = sensor_label or ""
        files.append(LoadedFile(
            name=name,
            modality=entry.get("modality", "UNDEFINED"),
            modality_label=entry.get("modalityLabel"),
            short_mac=entry.get("shortMac"),
            sensor_label=sensor_label,
            note=entry.get("note"),
            rotation_count=entry.get("rotationCount", 1),
            paths=paths,
            data=data,
        ))

    return Session(
        folder=folder,
        activity_code=session_info.get("activityCode", "UNDEFINED"),
        # Newer manifests name this ``sensorType``; older ones ``sensorPlacement``.
        sensor_placement=(session_info.get("sensorPlacement")
                          or session_info.get("sensorType", "UNDEFINED")),
        session_info=session_info,
        sensors=manifest.get("sensors", []),
        settings=manifest.get("settings", {}),
        files=files,
        manifest=manifest,
    )


def iter_sessions(root):
    """Yield a loaded :class:`Session` for each immediate child folder of
    ``root`` that is a session (contains a ``meta-summary.json``).

    One level down only; child folders without a manifest are skipped. Use this
    to batch-process a directory that holds many session folders::

        from lvl_toolkit import iter_sessions
        for session in iter_sessions("~/lvloutput"):
            ...  # graph each session
    """
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")
    for child in sorted(root.iterdir()):
        if child.is_dir() and find_manifest(child) is not None:
            yield load_session(child)
