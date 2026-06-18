from abc import ABC, abstractmethod
from typing import Optional, Tuple


class BaseComm(ABC):
    """
    Abstract communication contract.
    Every comm class (USB, RS232, Simulator) must implement these methods.
    The UI and calibration logic never import USBComm directly —
    they only use this interface, so swapping protocols touches zero UI code.
    """

    @abstractmethod
    def connect(self, port: str, baud: int = 9600) -> bool:
        """Open the port. Returns True on success."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the port cleanly."""

    @abstractmethod
    def read_temperatures(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Read all three sensors in one call.
        Returns (dry_block_temp, master_rtd_temp, uut_temp).
        Any value is None if that read fails.
        """

    @abstractmethod
    def read_volatility(self, window_minutes: float) -> Optional[float]:
        """
        Fluctuation (max-min) of the dry block's own temperature over the
        most recent window_minutes. Returns None if not enough data yet.
        Drives the stabilization decision in CalibrationEngine.
        """

    @abstractmethod
    def send_setpoint(self, temperature: float) -> bool:
        """Send CMD 10 with target temperature. Returns True if acknowledged."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Current connection state."""
