"""Lightweight data models for CSV I/O containers.

Self-contained value types (Point3D, ImuPacket, pose-landmark and joint-direction
enums) used by the data containers. Pure stdlib; no external dependencies.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, TYPE_CHECKING


# ---------------------------------------------------------------------------
# Time utilities
# ---------------------------------------------------------------------------

def us2s(time_us) -> float:
    """Microseconds to seconds."""
    return time_us / 1_000_000.0


# ---------------------------------------------------------------------------
# Point3D
# ---------------------------------------------------------------------------

@dataclass
class Point3D:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    ZERO: 'Point3D' = None  # Set after class definition

    @staticmethod
    def from_coords(coords) -> 'Point3D':
        return Point3D(coords[0], coords[1], coords[2])

    @staticmethod
    def lerp(p1: 'Point3D', p2: 'Point3D', t: float) -> 'Point3D':
        return Point3D(
            x=p1.x + t * (p2.x - p1.x),
            y=p1.y + t * (p2.y - p1.y),
            z=p1.z + t * (p2.z - p1.z),
        )

    def to_coords(self) -> List[float]:
        return [self.x, self.y, self.z]

    def magnitude(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def is_zero(self) -> bool:
        return self.x == 0.0 and self.y == 0.0 and self.z == 0.0

    def is_valid(self) -> bool:
        return (not self.is_zero() and
                math.isfinite(self.x) and math.isfinite(self.y) and math.isfinite(self.z))

    def distance_to(self, other: 'Point3D') -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def __add__(self, other: 'Point3D') -> 'Point3D':
        return Point3D(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: 'Point3D') -> 'Point3D':
        return Point3D(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, factor: float) -> 'Point3D':
        return Point3D(self.x * factor, self.y * factor, self.z * factor)

    def __rmul__(self, factor: float) -> 'Point3D':
        return self.__mul__(factor)

    def __truediv__(self, factor: float) -> 'Point3D':
        return Point3D(self.x / factor, self.y / factor, self.z / factor)

    def __getitem__(self, index: int) -> float:
        if index == 0:
            return self.x
        elif index == 1:
            return self.y
        elif index == 2:
            return self.z
        raise IndexError("Point3D index must be 0, 1, or 2")

    def dot(self, other: 'Point3D') -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: 'Point3D') -> 'Point3D':
        return Point3D(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def normalize(self) -> 'Point3D':
        mag = self.magnitude()
        return self / mag if mag > 0.0 else Point3D(0.0, 0.0, 0.0)

    def angle_to(self, other: 'Point3D') -> float:
        mag1 = self.magnitude()
        mag2 = other.magnitude()
        if mag1 == 0.0 or mag2 == 0.0:
            return 0.0
        cos_angle = max(-1.0, min(1.0, self.dot(other) / (mag1 * mag2)))
        return math.acos(cos_angle) * 180.0 / math.pi

    def signed_angle_to(self, other: 'Point3D', axis: 'Point3D') -> float:
        angle = self.angle_to(other)
        cr = self.cross(other)
        sign = 1.0 if cr.dot(axis) >= 0 else -1.0
        return angle * sign

    def project_onto_plane(self, plane_point: 'Point3D', normal: 'Point3D') -> 'Point3D':
        n = normal.normalize()
        v = self - plane_point
        proj_len = v.dot(n)
        return self - n * proj_len

    def project_onto(self, other: 'Point3D') -> 'Point3D':
        other_mag_sq = other.dot(other)
        if other_mag_sq == 0.0:
            return Point3D(0.0, 0.0, 0.0)
        scalar = self.dot(other) / other_mag_sq
        return other * scalar

    def to_formatted_string(self, precision: int = 3) -> str:
        fmt = f".{precision}f"
        return f"({self.x:{fmt}}, {self.y:{fmt}}, {self.z:{fmt}})"


Point3D.ZERO = Point3D(0.0, 0.0, 0.0)


def filter_valid(points: List[Point3D]) -> List[Point3D]:
    return [p for p in points if p.is_valid()]


def center_of_mass(points: List[Point3D]) -> Point3D:
    valid = filter_valid(points)
    if not valid:
        return Point3D(0.0, 0.0, 0.0)
    s = valid[0]
    for p in valid[1:]:
        s = s + p
    return s / len(valid)


def landmarks_to_flat_coords(landmarks: List[Point3D]) -> List[float]:
    result = []
    for p in landmarks:
        result.extend([p.x, p.y, p.z])
    return result


def flat_coords_to_landmarks(coords: List[float]) -> List[Point3D]:
    return [Point3D(coords[i], coords[i + 1], coords[i + 2])
            for i in range(0, len(coords), 3)]


# ---------------------------------------------------------------------------
# ImuPacket
# ---------------------------------------------------------------------------

@dataclass
class ImuPacket:
    accel_x: float = float('nan')
    accel_y: float = float('nan')
    accel_z: float = float('nan')
    gyro_x: float = float('nan')
    gyro_y: float = float('nan')
    gyro_z: float = float('nan')

    @property
    def norm_accel(self) -> float:
        return math.sqrt(self.accel_x ** 2 + self.accel_y ** 2 + self.accel_z ** 2)

    @property
    def norm_gyro(self) -> float:
        return math.sqrt(self.gyro_x ** 2 + self.gyro_y ** 2 + self.gyro_z ** 2)

    def has_valid_accel(self) -> bool:
        return (math.isfinite(self.accel_x) and
                math.isfinite(self.accel_y) and
                math.isfinite(self.accel_z))

    def has_valid_gyro(self) -> bool:
        return (math.isfinite(self.gyro_x) and
                math.isfinite(self.gyro_y) and
                math.isfinite(self.gyro_z))


@dataclass
class ImuTimePacket:
    timestamp_us: int = 0
    imu_packet: ImuPacket = None

    def __post_init__(self):
        if self.imu_packet is None:
            self.imu_packet = ImuPacket()

    @staticmethod
    def from_accel(timestamp_us: int, ax: float, ay: float, az: float) -> 'ImuTimePacket':
        return ImuTimePacket(timestamp_us, ImuPacket(accel_x=ax, accel_y=ay, accel_z=az))

    @staticmethod
    def from_gyro(timestamp_us: int, gx: float, gy: float, gz: float) -> 'ImuTimePacket':
        return ImuTimePacket(timestamp_us, ImuPacket(gyro_x=gx, gyro_y=gy, gyro_z=gz))


# ---------------------------------------------------------------------------
# BlazeposeIndexEnum
# ---------------------------------------------------------------------------

class SourceType(Enum):
    FROM_BLAZEPOSE = "FROM_BLAZEPOSE"
    VIRTUAL_MARKER = "VIRTUAL_MARKER"


class BlazeposeIndexEnum(Enum):
    # Standard BlazePose landmarks (0-32)
    NOSE                = (0,  SourceType.FROM_BLAZEPOSE)
    LEFT_EYE_INNER      = (1,  SourceType.FROM_BLAZEPOSE)
    LEFT_EYE             = (2,  SourceType.FROM_BLAZEPOSE)
    LEFT_EYE_OUTER       = (3,  SourceType.FROM_BLAZEPOSE)
    RIGHT_EYE_INNER      = (4,  SourceType.FROM_BLAZEPOSE)
    RIGHT_EYE            = (5,  SourceType.FROM_BLAZEPOSE)
    RIGHT_EYE_OUTER      = (6,  SourceType.FROM_BLAZEPOSE)
    LEFT_EAR             = (7,  SourceType.FROM_BLAZEPOSE)
    RIGHT_EAR            = (8,  SourceType.FROM_BLAZEPOSE)
    MOUTH_LEFT           = (9,  SourceType.FROM_BLAZEPOSE)
    MOUTH_RIGHT          = (10, SourceType.FROM_BLAZEPOSE)
    LEFT_SHOULDER        = (11, SourceType.FROM_BLAZEPOSE)
    RIGHT_SHOULDER       = (12, SourceType.FROM_BLAZEPOSE)
    LEFT_ELBOW           = (13, SourceType.FROM_BLAZEPOSE)
    RIGHT_ELBOW          = (14, SourceType.FROM_BLAZEPOSE)
    LEFT_WRIST           = (15, SourceType.FROM_BLAZEPOSE)
    RIGHT_WRIST          = (16, SourceType.FROM_BLAZEPOSE)
    LEFT_PINKY           = (17, SourceType.FROM_BLAZEPOSE)
    RIGHT_PINKY          = (18, SourceType.FROM_BLAZEPOSE)
    LEFT_INDEX           = (19, SourceType.FROM_BLAZEPOSE)
    RIGHT_INDEX          = (20, SourceType.FROM_BLAZEPOSE)
    LEFT_THUMB           = (21, SourceType.FROM_BLAZEPOSE)
    RIGHT_THUMB          = (22, SourceType.FROM_BLAZEPOSE)
    LEFT_HIP             = (23, SourceType.FROM_BLAZEPOSE)
    RIGHT_HIP            = (24, SourceType.FROM_BLAZEPOSE)
    LEFT_KNEE            = (25, SourceType.FROM_BLAZEPOSE)
    RIGHT_KNEE           = (26, SourceType.FROM_BLAZEPOSE)
    LEFT_ANKLE           = (27, SourceType.FROM_BLAZEPOSE)
    RIGHT_ANKLE          = (28, SourceType.FROM_BLAZEPOSE)
    LEFT_HEEL            = (29, SourceType.FROM_BLAZEPOSE)
    RIGHT_HEEL           = (30, SourceType.FROM_BLAZEPOSE)
    LEFT_FOOT_INDEX      = (31, SourceType.FROM_BLAZEPOSE)
    RIGHT_FOOT_INDEX     = (32, SourceType.FROM_BLAZEPOSE)
    # Virtual markers (33+)
    NULL                 = (33, SourceType.VIRTUAL_MARKER)
    RIGHT_HIP_Y0        = (34, SourceType.VIRTUAL_MARKER)
    LEFT_HIP_Y0         = (35, SourceType.VIRTUAL_MARKER)
    RIGHT_KNEE_Y0       = (36, SourceType.VIRTUAL_MARKER)
    LEFT_KNEE_Y0        = (37, SourceType.VIRTUAL_MARKER)
    RIGHT_ANKLE_Y0      = (38, SourceType.VIRTUAL_MARKER)
    LEFT_ANKLE_Y0       = (39, SourceType.VIRTUAL_MARKER)
    SHOULDER_CENTRE      = (40, SourceType.VIRTUAL_MARKER)
    HIP_CENTRE           = (41, SourceType.VIRTUAL_MARKER)
    HIP_CENTRE_Y0       = (42, SourceType.VIRTUAL_MARKER)
    RIGHT_HIP_X0        = (43, SourceType.VIRTUAL_MARKER)
    LEFT_HIP_X0         = (44, SourceType.VIRTUAL_MARKER)
    RIGHT_KNEE_X0       = (45, SourceType.VIRTUAL_MARKER)
    LEFT_KNEE_X0        = (46, SourceType.VIRTUAL_MARKER)
    RIGHT_ANKLE_X0      = (47, SourceType.VIRTUAL_MARKER)
    LEFT_ANKLE_X0       = (48, SourceType.VIRTUAL_MARKER)

    def __init__(self, index: int, source_type: SourceType):
        self.index = index
        self.source_type = source_type

    @classmethod
    def from_index(cls, index: int) -> Optional['BlazeposeIndexEnum']:
        for member in cls:
            if member.index == index:
                return member
        return None

    @classmethod
    def get_blazepose_markers(cls) -> List['BlazeposeIndexEnum']:
        return [m for m in cls if m.source_type == SourceType.FROM_BLAZEPOSE]

    @classmethod
    def get_virtual_markers(cls) -> List['BlazeposeIndexEnum']:
        return [m for m in cls if m.source_type == SourceType.VIRTUAL_MARKER]

    def calculate_point3d(self, blazepose_array: list) -> 'Point3D':
        if self.source_type == SourceType.FROM_BLAZEPOSE:
            if self.index < len(blazepose_array):
                return blazepose_array[self.index]
            return Point3D()

        B = BlazeposeIndexEnum
        _y0_map = {
            B.RIGHT_HIP_Y0: B.RIGHT_HIP, B.LEFT_HIP_Y0: B.LEFT_HIP,
            B.RIGHT_KNEE_Y0: B.RIGHT_KNEE, B.LEFT_KNEE_Y0: B.LEFT_KNEE,
            B.RIGHT_ANKLE_Y0: B.RIGHT_ANKLE, B.LEFT_ANKLE_Y0: B.LEFT_ANKLE,
        }
        if self in _y0_map:
            p = blazepose_array[_y0_map[self].index]
            return Point3D(p.x, 0.0, p.z)

        _x0_map = {
            B.RIGHT_HIP_X0: B.RIGHT_HIP, B.LEFT_HIP_X0: B.LEFT_HIP,
            B.RIGHT_KNEE_X0: B.RIGHT_KNEE, B.LEFT_KNEE_X0: B.LEFT_KNEE,
            B.RIGHT_ANKLE_X0: B.RIGHT_ANKLE, B.LEFT_ANKLE_X0: B.LEFT_ANKLE,
        }
        if self in _x0_map:
            p = blazepose_array[_x0_map[self].index]
            return Point3D(0.0, p.y, p.z)

        if self == B.SHOULDER_CENTRE:
            r = blazepose_array[B.RIGHT_SHOULDER.index]
            l = blazepose_array[B.LEFT_SHOULDER.index]
            return Point3D((r.x + l.x) / 2.0, (r.y + l.y) / 2.0, (r.z + l.z) / 2.0)
        if self == B.HIP_CENTRE:
            r = blazepose_array[B.RIGHT_HIP.index]
            l = blazepose_array[B.LEFT_HIP.index]
            return Point3D((r.x + l.x) / 2.0, (r.y + l.y) / 2.0, (r.z + l.z) / 2.0)
        if self == B.HIP_CENTRE_Y0:
            r = blazepose_array[B.RIGHT_HIP.index]
            l = blazepose_array[B.LEFT_HIP.index]
            return Point3D((r.x + l.x) / 2.0, 0.0, (r.z + l.z) / 2.0)

        return Point3D()


NUM_BLAZEPOSE_LANDMARKS = 33


def landmark_column_names() -> List[str]:
    names = []
    for member in BlazeposeIndexEnum.get_blazepose_markers():
        base = member.name.lower()
        names.extend([f"{base}_x", f"{base}_y", f"{base}_z"])
    return names


# ---------------------------------------------------------------------------
# JointDirectionEnum
# ---------------------------------------------------------------------------

class JointDirectionEnum(Enum):
    FLEXION = "FLEXION"
    ABDUCTION = "ABDUCTION"
    ROTATION = "ROTATION"
    ANGLE = "ANGLE"
