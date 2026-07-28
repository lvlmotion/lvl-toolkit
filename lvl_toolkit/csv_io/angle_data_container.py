"""
Time-series joint angle data container.
Mirror of the Level KMP AngleDataContainer.
"""

from enum import Enum
from typing import List
from .data_container_base import DataContainerBase
from .models import us2s


class JointEstimatorMode(Enum):
    SINGLE = "SINGLE"
    COSINE_LAW_2D = "COSINE_LAW_2D"
    COSINE_LAW_3D = "COSINE_LAW_3D"
    CROSS_3D = "CROSS_3D"


class AngleDataContainer(DataContainerBase):
    def __init__(self, mode: JointEstimatorMode = JointEstimatorMode.COSINE_LAW_2D, joint_set=None):
        super().__init__()
        self.mode = mode
        self.joint_set = joint_set
        self.velo_list: List[List[float]] = []

        if mode == JointEstimatorMode.SINGLE:
            self.header = ["time", "angle"]
        elif mode == JointEstimatorMode.COSINE_LAW_2D:
            if joint_set is not None:
                cols = [jl.name.lower() for jl in joint_set.joint_location_list]
            else:
                cols = []
            self.header = ["time"] + cols
        elif mode in (JointEstimatorMode.COSINE_LAW_3D, JointEstimatorMode.CROSS_3D):
            from .models import JointDirectionEnum
            if joint_set is not None:
                cols = []
                for jl in joint_set.joint_location_list:
                    for jd in JointDirectionEnum:
                        cols.append(f"{jl.name}_{jd.name}".lower())
            else:
                cols = []
            self.header = ["time"] + cols
        else:
            self.header = ["time"]

    def add(self, time_us: int, angles: List[float]):
        self.time_list.append(time_us)
        self.data_list.append(list(angles))

    def calc_velo(self):
        """Calculate angular velocity from angle data."""
        if not self.data_list or not self.data_list[-1]:
            return

        current = self.data_list[-1]

        if len(self.data_list) >= 2:
            prev = self.data_list[-2]
            dt = us2s(self.time_list[-1] - self.time_list[-2])
            if dt > 0:
                velo = [(c - p) / dt for c, p in zip(current, prev)]
            else:
                velo = [0.0] * len(current)
        else:
            velo = [0.0] * len(current)

        self.velo_list.append(velo)

    def get_pos_latest(self, joint_index: int) -> float:
        if self.data_list and joint_index < len(self.data_list[-1]):
            return self.data_list[-1][joint_index]
        return 0.0

    def get_velo_latest(self, joint_index: int) -> float:
        if self.velo_list and joint_index < len(self.velo_list[-1]):
            return self.velo_list[-1][joint_index]
        return 0.0

    def _format_row(self, index: int) -> List[str]:
        t = self.time_list[index]
        angles = self.data_list[index]
        return [str(t)] + [str(a) for a in angles]

    def _parse_row(self, row: List[str]):
        t = int(row[0])
        angles = [float(v) for v in row[1:]]
        self.add(t, angles)

    def reset(self):
        super().reset()
        self.velo_list.clear()
