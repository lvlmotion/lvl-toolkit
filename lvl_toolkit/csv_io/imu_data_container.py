"""
Time-series IMU data container (accel + gyro).
Mirror of the Level KMP ImuDataContainer.
"""

import math
from typing import List

import numpy as np

from .data_container_base import DataContainerBase
from .models import ImuPacket


class ImuDataContainer(DataContainerBase):
    def __init__(self):
        super().__init__()
        self.norm_accel: List[float] = []
        self.norm_gyro: List[float] = []
        self.header = ["time", "accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z"]

    def add(self, packet: ImuPacket, timestamp_us: int):
        self.time_list.append(timestamp_us)
        self.data_list.append(packet)
        self.norm_accel.append(packet.norm_accel)
        self.norm_gyro.append(packet.norm_gyro)

    def avg_gyro_norm(self, latest_n: int) -> float:
        packets = self.data_list[-latest_n:]
        if not packets:
            return 0.0
        return sum(p.norm_gyro for p in packets) / len(packets)

    def get_latest_accel(self) -> List[float]:
        p = self.data_list[-1]
        return [p.accel_x, p.accel_y, p.accel_z]

    def _format_row(self, index: int) -> List[str]:
        t = self.time_list[index]
        p = self.data_list[index]
        return [
            str(t),
            f"{p.accel_x:.6f}", f"{p.accel_y:.6f}", f"{p.accel_z:.6f}",
            f"{p.gyro_x:.6f}", f"{p.gyro_y:.6f}", f"{p.gyro_z:.6f}",
        ]

    def _parse_row(self, row: List[str]):
        t = int(row[0])
        packet = ImuPacket(
            accel_x=float(row[1]), accel_y=float(row[2]), accel_z=float(row[3]),
            gyro_x=float(row[4]), gyro_y=float(row[5]), gyro_z=float(row[6]),
        )
        self.add(packet, t)

    def reset(self):
        super().reset()
        self.norm_accel.clear()
        self.norm_gyro.clear()

    # --- Numpy conversion ---

    def to_numpy(self):
        """Convert to numpy arrays: (time_us, accel, gyro)."""
        n = self.size()
        time_us = np.array(self.time_list, dtype=np.int64)
        accel = np.zeros((n, 3))
        gyro = np.zeros((n, 3))
        for i, pkt in enumerate(self.data_list):
            accel[i] = [pkt.accel_x, pkt.accel_y, pkt.accel_z]
            gyro[i] = [pkt.gyro_x, pkt.gyro_y, pkt.gyro_z]
        return time_us, accel, gyro

    @staticmethod
    def from_numpy(time_us, accel, gyro):
        """Create ImuDataContainer from numpy arrays."""
        dc = ImuDataContainer()
        for i in range(len(time_us)):
            pkt = ImuPacket(
                accel_x=float(accel[i, 0]), accel_y=float(accel[i, 1]), accel_z=float(accel[i, 2]),
                gyro_x=float(gyro[i, 0]), gyro_y=float(gyro[i, 1]), gyro_z=float(gyro[i, 2]),
            )
            dc.add(pkt, int(time_us[i]))
        return dc
