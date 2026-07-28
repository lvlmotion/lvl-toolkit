"""
Segment (rep / phase) boundary data container.
Mirror of the Level KMP SegmentDataContainer.
"""

from dataclasses import dataclass
from typing import List, Optional
from .data_container_base import DataContainerBase


@dataclass
class Segment:
    start_time: int = 0
    end_time: int = 0
    start_ind: int = 0
    end_ind: int = 0
    segment_type: str = ""
    notes: str = ""


class SegmentDataContainer(DataContainerBase):
    def __init__(self):
        super().__init__()
        self.header = ["start_time", "end_time", "start_ind", "end_ind", "type", "notes"]

    def add(self, segment: Segment):
        self.time_list.append(segment.start_time)
        self.data_list.append(segment)

    def get_last_segment(self) -> Optional[Segment]:
        return self.data_list[-1] if self.data_list else None

    def get_seg_count(self) -> int:
        return len(self.data_list)

    def get_rep_count(self) -> int:
        return len(self.data_list) // 2

    def apply_delay(self, delay_us: int):
        for i in range(len(self.time_list)):
            self.time_list[i] += delay_us
        for seg in self.data_list:
            seg.start_time += delay_us
            seg.end_time += delay_us

    def _format_row(self, index: int) -> List[str]:
        s = self.data_list[index]
        return [
            str(s.start_time), str(s.end_time),
            str(s.start_ind), str(s.end_ind),
            s.segment_type, s.notes,
        ]

    def _parse_row(self, row: List[str]):
        seg = Segment(
            start_time=int(row[0]),
            end_time=int(row[1]),
            start_ind=int(row[2]),
            end_ind=int(row[3]),
            segment_type=row[4] if len(row) > 4 else "",
            notes=row[5] if len(row) > 5 else "",
        )
        self.add(seg)
