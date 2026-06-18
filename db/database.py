import sqlite3
import json
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional

from models.calibration_point import CalibrationPoint
from models.calibration_session import CalibrationSession


# The DB file lives next to the EXE (or next to main.py during development).
DB_PATH = Path(__file__).parent.parent / 'data' / 'calibrations.db'


class Database:
    """
    Thin wrapper around SQLite.
    Two tables:
      - sessions  : one row per calibration run (header info)
      - points    : one row per setpoint reading, linked to session by cert_no
    """

    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._init_tables()

    # ------------------------------------------------------------------
    # Schema creation
    # ------------------------------------------------------------------
    def _init_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    cert_no      TEXT PRIMARY KEY,
                    customer     TEXT,
                    address      TEXT,
                    performed_by TEXT,
                    verified_by  TEXT,
                    setpoints    TEXT,   -- JSON array stored as text
                    date         TEXT,
                    time         TEXT
                );

                CREATE TABLE IF NOT EXISTS points (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    cert_no     TEXT REFERENCES sessions(cert_no),
                    setpoint    REAL,
                    furnace     REAL,
                    master_rtd  REAL,
                    uut         REAL,
                    error       REAL,
                    result      TEXT,
                    timestamp   TEXT
                );
            """)

    # ------------------------------------------------------------------
    # Save a completed session
    # ------------------------------------------------------------------
    def save_session(self, session: CalibrationSession) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (cert_no, customer, address, performed_by, verified_by, setpoints, date, time)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    session.cert_no,
                    session.customer,
                    session.address,
                    session.performed_by,
                    session.verified_by,
                    json.dumps(session.setpoints),
                    session.date.isoformat(),
                    session.time_str,
                )
            )
            for pt in session.points:
                conn.execute(
                    """INSERT INTO points
                       (cert_no, setpoint, furnace, master_rtd, uut, error, result, timestamp)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        session.cert_no,
                        pt.setpoint, pt.furnace, pt.master_rtd, pt.uut,
                        pt.error, pt.result, pt.timestamp.isoformat(),
                    )
                )

    # ------------------------------------------------------------------
    # Search sessions by date range and optional filters
    # ------------------------------------------------------------------
    def search_sessions(
        self,
        from_date: Optional[date] = None,
        to_date:   Optional[date] = None,
        cert_no:   str = '',
        customer:  str = '',
    ) -> List[CalibrationSession]:
        query = "SELECT * FROM sessions WHERE 1=1"
        params: list = []
        if from_date:
            query += " AND date >= ?"
            params.append(from_date.isoformat())
        if to_date:
            query += " AND date <= ?"
            params.append(to_date.isoformat())
        if cert_no:
            query += " AND cert_no LIKE ?"
            params.append(f'%{cert_no}%')
        if customer:
            query += " AND customer LIKE ?"
            params.append(f'%{customer}%')
        query += " ORDER BY date DESC, time DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_session(r) for r in rows]

    # ------------------------------------------------------------------
    # Load one session with all its points
    # ------------------------------------------------------------------
    def load_session(self, cert_no: str) -> Optional[CalibrationSession]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE cert_no = ?", (cert_no,)
            ).fetchone()
            if not row:
                return None
            session = self._row_to_session(row)
            pt_rows = conn.execute(
                "SELECT * FROM points WHERE cert_no = ? ORDER BY id", (cert_no,)
            ).fetchall()
            session.points = [self._pt_row_to_point(r) for r in pt_rows]
        return session

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row  # lets us access columns by name
        return conn

    def _row_to_session(self, row: sqlite3.Row) -> CalibrationSession:
        session = CalibrationSession(
            cert_no=row['cert_no'],
            customer=row['customer'],
            address=row['address'],
            performed_by=row['performed_by'],
            verified_by=row['verified_by'],
            setpoints=json.loads(row['setpoints']),
            date=date.fromisoformat(row['date']),
        )
        return session

    @staticmethod
    def _pt_row_to_point(row: sqlite3.Row) -> CalibrationPoint:
        return CalibrationPoint(
            setpoint=row['setpoint'],
            furnace=row['furnace'],
            master_rtd=row['master_rtd'],
            uut=row['uut'],
            result=row['result'],
            timestamp=datetime.fromisoformat(row['timestamp']),
        )
