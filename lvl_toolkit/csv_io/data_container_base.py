"""
Base class for time-series data containers with CSV I/O.
Mirror of the Level KMP DataContainerBase (read + write).
"""

import csv
import os
from typing import List, TypeVar, Generic, Optional
from abc import ABC, abstractmethod

T = TypeVar('T')


class DataContainerBase(ABC):
    """Abstract base for all data containers."""

    def __init__(self):
        self.time_list: List[int] = []
        self.data_list: List = []
        self.header: List[str] = []

    def size(self) -> int:
        return len(self.time_list)

    def reset(self):
        self.time_list.clear()
        self.data_list.clear()

    # --- CSV writing ---

    def write_to_csv(self, file_path: str):
        """Write all data to CSV file."""
        os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else '.', exist_ok=True)
        with open(file_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(self.header)
            for i in range(self.size()):
                writer.writerow(self._format_row(i))

    @abstractmethod
    def _format_row(self, index: int) -> List[str]:
        """Format one data row for CSV output. Subclasses must implement."""
        ...

    # --- CSV reading ---

    def load_from_csv(self, file_path: str):
        """Load data from CSV file. Subclasses should override _parse_row()."""
        self.reset()
        with open(file_path, 'r') as f:
            reader = csv.reader(f)
            self.header = next(reader)  # Read header
            for row in reader:
                if row:  # Skip empty rows
                    self._parse_row(row)

    def _parse_row(self, row: List[str]):
        """Parse one CSV row into time_list/data_list. Override in subclasses."""
        raise NotImplementedError("Subclass must implement _parse_row()")
