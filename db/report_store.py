"""
Report storage using JSON files in a local 'reports/' folder.

Why JSON files instead of SQLite?
- Each session is self-contained — one file, one calibration.
- No database engine to maintain or migrate.
- Files are human-readable and can be opened in Notepad.
- Backups = copy the folder. No export step needed.
- Certificate numbers are unique, so filenames are unique.
- Searching 200-300 files is instantaneous on any modern PC.

File naming:
  Certificate "TIPL/CAL/2026/0001"  →  TIPL_CAL_2026_0001.json
  Slashes are replaced with underscores to make valid filenames.
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from models.calibration_point import CalibrationPoint
from models.calibration_session import CalibrationSession, InstrumentInfo


def _app_root() -> Path:
    # Frozen (PyInstaller --onefile): __file__ would resolve inside the
    # temp folder the exe extracts itself into and deletes on exit, so
    # settings/reports would vanish every time the app closes. Anchor to
    # the folder containing the actual .exe instead, which is permanent.
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


REPORTS_DIR = _app_root() / 'reports'


class ReportStore:
    """
    Save, load, and search calibration sessions stored as JSON files.
    One file = one session. Filename = sanitized certificate number.
    """

    def __init__(self, reports_dir: Path = REPORTS_DIR):
        self._dir = reports_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Certificate numbering
    # ------------------------------------------------------------------
    def next_sequence(self) -> int:
        """
        Next 1-based certificate sequence number for this reports folder.

        Derived from the highest sequence found in existing filenames
        rather than a separate counter file, so it can never drift out of
        sync with what's actually been saved (e.g. after a deleted report
        or a folder copied in from elsewhere).
        """
        max_seq = 0
        for path in self._dir.glob('*.json'):
            seq = self._extract_sequence(path.stem)
            if seq is not None:
                max_seq = max(max_seq, seq)
        return max_seq + 1

    @staticmethod
    def _extract_sequence(stem: str) -> Optional[int]:
        """The last '_'-separated token of a cert filename is the 4-digit
        sequence (see build_cert_no) — anything else is ignored."""
        tail = stem.rsplit('_', 1)[-1]
        return int(tail) if tail.isdigit() else None

    @staticmethod
    def build_cert_no(prefix: str, uut_serial: str, cal_date: date, seq: int) -> str:
        """
        Certificate number format: PREFIX_UUTSERIAL_DDMMYYYY_0001
        Prefix is optional (Settings > certificate prefix); UUT serial and
        date are always present. Sequence is zero-padded to 4 digits.
        """
        parts = [p for p in (prefix.strip(), uut_serial.strip()) if p]
        parts.append(cal_date.strftime('%d%m%Y'))
        parts.append(f'{seq:04d}')
        return '_'.join(parts)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def save(self, session: CalibrationSession) -> Path:
        """
        Write the session to a JSON file.
        Returns the path of the created/updated file.
        If the cert_no already exists, it overwrites — cert numbers are unique.
        """
        path = self._dir / f'{self._safe_name(session.cert_no)}.json'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self._to_dict(session), f, indent=2, ensure_ascii=False)
        return path

    # ------------------------------------------------------------------
    # Load one
    # ------------------------------------------------------------------
    def load(self, cert_no: str) -> Optional[CalibrationSession]:
        """Load a specific session by its certificate number."""
        path = self._dir / f'{self._safe_name(cert_no)}.json'
        if not path.exists():
            return None
        return self._from_file(path)

    # ------------------------------------------------------------------
    # Search / list
    # ------------------------------------------------------------------
    def search(
        self,
        cert_no:   str = '',
        tag_number: str = '',
        serial_no:  str = '',
    ) -> List[CalibrationSession]:
        """
        Return all sessions matching the given filters.
        All filters are case-insensitive substring matches.
        Empty string = no filter on that field.
        Results are ordered newest first (by file modification time).
        """
        results: List[CalibrationSession] = []
        files = sorted(
            self._dir.glob('*.json'),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in files:
            try:
                data = self._read_json(path)

                # cert_no filter: matches against the stored cert_no value
                if cert_no and cert_no.lower() not in data.get('cert_no', '').lower():
                    continue

                # tag_number filter: UUT's tag number
                uut = data.get('uut_info', {})
                if tag_number and tag_number.lower() not in uut.get('tag_number', '').lower():
                    continue

                # serial_no filter: UUT's serial number
                if serial_no and serial_no.lower() not in uut.get('serial_no', '').lower():
                    continue

                results.append(self._from_dict(data))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue   # skip corrupted files silently
        return results

    def list_all(self) -> List[CalibrationSession]:
        """Return all sessions, newest first. Used to populate the Reports screen on open."""
        return self.search()

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_name(cert_no: str) -> str:
        """
        Convert a certificate number to a safe Windows filename.
        "TIPL/CAL/2026/001" → "TIPL_CAL_2026_001"
        """
        safe = cert_no
        for ch in r'/\:*?"<>|':
            safe = safe.replace(ch, '_')
        return safe.strip('_') or 'UNKNOWN'

    def _from_file(self, path: Path) -> CalibrationSession:
        data = self._read_json(path)
        return self._from_dict(data)

    @staticmethod
    def _read_json(path: Path) -> dict:
        with open(path, encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def _to_dict(session: CalibrationSession) -> dict:
        return {
            'cert_no':      session.cert_no,
            'customer':     session.customer,
            'address':      session.address,
            'performed_by': session.performed_by,
            'verified_by':  session.verified_by,
            'setpoints':    session.setpoints,
            'date':         session.date.isoformat(),
            'master_info':  session.master_info.to_dict(),
            'uut_info':     session.uut_info.to_dict(),
            'points': [pt.to_dict() for pt in session.points],
        }

    @staticmethod
    def _from_dict(d: dict) -> CalibrationSession:
        session = CalibrationSession(
            cert_no=d['cert_no'],
            customer=d.get('customer', ''),
            address=d.get('address', ''),
            performed_by=d.get('performed_by', ''),
            verified_by=d.get('verified_by', ''),
            setpoints=d.get('setpoints', []),
            date=date.fromisoformat(d['date']),
            master_info=InstrumentInfo.from_dict(d.get('master_info', {})),
            uut_info=InstrumentInfo.from_dict(d.get('uut_info', {})),
        )
        for pt in d.get('points', []):
            session.points.append(CalibrationPoint(
                setpoint=pt['setpoint'],
                dry_block_temp=pt.get('dry_block_temp', pt.get('furnace', 0.0)),
                master_rtd=pt['master_rtd'],
                uut=pt['uut'],
                timestamp=datetime.fromisoformat(pt['timestamp']),
            ))
        return session
