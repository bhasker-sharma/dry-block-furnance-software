"""
Lab settings storage — a single JSON file at data/settings.json.

Why JSON instead of SQLite (same reasoning as ReportStore)?
- One small, human-readable file, no schema migrations.
- Settings are read once at startup / calibration start, not queried.

This file holds everything that used to live only in memory, plus the
new lab-level configuration: serial port, calibrator range, CMC,
setpoints, Master RTD, and manufacturer settings.
"""
import json
import sys
from pathlib import Path
from typing import Any

from models.calibration_session import InstrumentInfo


def _app_root() -> Path:
    # Frozen (PyInstaller --onefile): __file__ would resolve inside the
    # temp folder the exe extracts itself into and deletes on exit, so
    # settings/reports would vanish every time the app closes. Anchor to
    # the folder containing the actual .exe instead, which is permanent.
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


SETTINGS_PATH = _app_root() / 'data' / 'settings.json'

# SOUR:STAB:LIM range per the 9144 protocol (Digital Interface §6.4) —
# values outside this go in the instrument's own error queue and are
# rejected, so anything from settings.json (hand-edited, stale, or from
# before this field existed) must be clamped into range before use.
STABILITY_LIMIT_MIN = 0.01
STABILITY_LIMIT_MAX = 9.99


def clamp_stability_limit(value: float) -> float:
    return min(max(value, STABILITY_LIMIT_MIN), STABILITY_LIMIT_MAX)


DEFAULTS: dict[str, Any] = {
    'serial': {
        'iface': 'RS-232', 'port': 'COM3', 'baud': 9600,
        'timeout_ms': 1000, 'retry': 3,
    },
    'calibrator_range': {'min': None, 'max': None},
    'cmc_enabled': False,
    'cmc_points': [],          # [{'temperature': float, 'cmc': float}, ...]
    'setpoints': [],           # [float, ...]
    'master_rtd': InstrumentInfo().to_dict(),
    # Where saved calibration certificates (reports/*.json) are written.
    # None until the operator picks a folder in Settings — required before
    # a calibration can be started (see is_reports_dir_configured()).
    'reports_dir': None,
    # stability_limit_c is pushed to the instrument as SOUR:STAB:LIM on
    # connect — the tolerance SOUR:STAB:TEST? judges against. 9144 range
    # is 0.01-9.99 C; its own datasheet stability spec is ~0.03 C (50 C)
    # to ~0.05 C (660 C), so 0.05 is a safe default across the full range.
    'manufacturer': {'stability_limit_c': 0.05},
}


class SettingsStore:
    """Load, save, and validate the lab's persistent settings."""

    def __init__(self, path: Path = SETTINGS_PATH):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self._path.exists():
            return json.loads(json.dumps(DEFAULTS))  # deep copy
        with open(self._path, encoding='utf-8') as f:
            data = json.load(f)
        merged = json.loads(json.dumps(DEFAULTS))
        merged.update(data)
        return merged

    def save(self, settings: dict) -> None:
        with open(self._path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)

    def is_ready_for_connection(self) -> bool:
        """
        Connection is only allowed once calibrator range and at least one
        setpoint are configured (CMC ON/OFF always has a value by default).
        """
        s = self.load()
        rng = s.get('calibrator_range', {})
        has_range = rng.get('min') is not None and rng.get('max') is not None
        has_setpoints = bool(s.get('setpoints'))
        return has_range and has_setpoints

    def is_reports_dir_configured(self) -> bool:
        """A calibration can't be started until the operator has picked
        where saved certificates go — see reports_dir in DEFAULTS."""
        return bool(self.load().get('reports_dir'))
