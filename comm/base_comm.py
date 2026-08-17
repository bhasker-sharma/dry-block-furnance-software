from abc import ABC, abstractmethod
from typing import Callable, Optional, Tuple


class BaseComm(ABC):
    """
    Abstract communication contract.
    Every comm class (USB, RS232, Simulator) must implement these methods.
    The UI and calibration logic never import USBComm directly —
    they only use this interface, so swapping protocols touches zero UI code.
    """

    @abstractmethod
    def connect(self, port: str, baud: int = 9600,
                timeout_s: float = 1.0, retries: int = 1,
                should_abort: Optional[Callable[[], bool]] = None) -> bool:
        """
        Open the port, retrying up to `retries` times. Returns True on success.

        This can block for up to retries * timeout_s seconds — callers on a
        GUI thread should run it on a worker thread (see ui/connect_worker.py)
        rather than call it directly from a slot. `should_abort`, if given, is
        checked between attempts (not mid-syscall) so a caller can stop
        further retries once the in-flight attempt returns.
        """

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
    def read_stable(self) -> bool:
        """
        True once the instrument's own SOUR:STAB:TEST? reports the block has
        settled at the current setpoint. Drives capture in CalibrationEngine.
        """

    @abstractmethod
    def send_setpoint(self, temperature: float) -> bool:
        """Send CMD 10 with target temperature. Returns True if acknowledged."""

    @abstractmethod
    def set_stability_limit(self, limit_c: float) -> bool:
        """
        Write the instrument's own stability tolerance (SOUR:STAB:LIM) — the
        band SOUR:STAB:TEST? must stay within before it reports stable.
        Returns True if the instrument acknowledged the value (read-back
        matches what was sent).
        """

    @abstractmethod
    def get_stability_limit(self) -> Optional[float]:
        """Read the stability tolerance (SOUR:STAB:LIM?) currently set on
        the instrument, in °C. None if the read fails."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Current connection state."""
