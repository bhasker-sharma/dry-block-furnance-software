import random
import time
from typing import Optional, Tuple
from comm.base_comm import BaseComm


class SimulatorComm(BaseComm):
    """
    Software-only dry block simulator for development and testing.
    Behaves identically to real hardware from the app's perspective.
    Swap this with USBComm when the real device is ready — nothing else changes.
    """

    def __init__(self):
        self._connected = False
        self._base_temp = 24.0      # current simulated temperature
        self._target = 24.0         # setpoint the dry block is driving toward
        self._uut_offset = 0.15     # UUT reads slightly higher than master
        self._history: list = []    # (timestamp, dry_block_temp) for volatility

    def connect(self, port: str, baud: int = 9600) -> bool:
        self._connected = True
        self._base_temp = 24.0
        self._target = 24.0
        self._history.clear()
        return True

    def disconnect(self) -> None:
        self._connected = False

    def read_temperatures(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        if not self._connected:
            return None, None, None

        # Simulate thermal lag: base creeps 8% toward target per tick + small noise
        self._base_temp += (self._target - self._base_temp) * 0.08

        def noise() -> float:
            return (random.random() - 0.5) * 0.06

        dry_block = round(self._base_temp + 0.55 + noise(), 2)   # dry block runs slightly hot
        master    = round(self._base_temp + noise(), 2)
        uut       = round(self._base_temp + self._uut_offset + noise(), 2)

        self._history.append((time.monotonic(), dry_block))
        return dry_block, master, uut

    def read_volatility(self, window_minutes: float) -> Optional[float]:
        if not self._connected:
            return None
        cutoff = time.monotonic() - window_minutes * 60.0
        window = [v for ts, v in self._history if ts >= cutoff]
        if len(window) < 2:
            return None
        return round(max(window) - min(window), 3)

    def send_setpoint(self, temperature: float) -> bool:
        self._target = temperature
        self._uut_offset = 0.10 + random.random() * 0.25  # vary per setpoint
        self._history.clear()
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected
