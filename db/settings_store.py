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

# Where the uploaded company logo is stored. Kept alongside settings.json
# (not inside it) since it's binary — settings.json only stores the path.
ASSETS_DIR = SETTINGS_PATH.parent / 'assets'
_LOGO_BASENAME = 'company_logo'

# The logo must be exactly this size so future report layouts can place it
# without per-file scaling logic. Enforced in the UI (QImage dimension
# check) before save_logo() is ever called.
REQUIRED_LOGO_SIZE = (300, 150)  # (width, height) in px

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
    # Lab/company identity — set once in Settings, used by report_gen in
    # future to brand the certificate header. logo_path points at the copy
    # SettingsStore.save_logo() makes under ASSETS_DIR, not the original
    # file the user picked.
    'user_profile': {
        'company_name': '',
        'company_address': '',
        'certificate_prefix': '',
        'logo_path': None,
    },
    # stability_limit_c is pushed to the instrument as SOUR:STAB:LIM on
    # connect — the tolerance SOUR:STAB:TEST? judges against. 9144 range
    # is 0.01-9.99 C; its own datasheet stability spec is ~0.03 C (50 C)
    # to ~0.05 C (660 C), so 0.05 is a safe default across the full range.
    # reference_equipment / model_no / serial_no describe the reference
    # standard used to calibrate/verify this instrument itself — PIN-gated
    # in the UI along with stability_limit_c.
    'manufacturer': {
        'stability_limit_c': 0.05,
        'reference_equipment': '',
        'model_no': '',
        'serial_no': '',
    },
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

    def save_logo(self, source_path: str) -> str:
        """Copy an already dimension-validated logo image into ASSETS_DIR,
        replacing any previous logo (even one with a different extension),
        and return the stored path to save into user_profile.logo_path.

        Dimension checking happens in the UI (QImage), not here — this
        store has no Qt/Pillow dependency and just moves bytes."""
        src = Path(source_path)
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        for old in ASSETS_DIR.glob(f'{_LOGO_BASENAME}.*'):
            old.unlink(missing_ok=True)
        dest = ASSETS_DIR / f'{_LOGO_BASENAME}{src.suffix.lower()}'
        dest.write_bytes(src.read_bytes())
        return str(dest)

    def remove_logo(self) -> None:
        """Delete the stored logo file, if any."""
        for old in ASSETS_DIR.glob(f'{_LOGO_BASENAME}.*'):
            old.unlink(missing_ok=True)
