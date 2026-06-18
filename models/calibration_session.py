from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List
from models.calibration_point import CalibrationPoint


@dataclass
class InstrumentInfo:
    """
    Physical details of one instrument — used for both the Master RTD
    and the UUT. Both have Type/Make/Model/SerialNo in common.
    Master RTD adds cert_number (its own calibration certificate).
    UUT adds tag_number (the plant/lab tag on the instrument body).
    Unused fields simply stay empty strings — no harm done.
    """
    instrument_type: str = ''
    make:            str = ''
    model:           str = ''
    serial_no:       str = ''
    cert_number:     str = ''   # filled for Master RTD only
    tag_number:      str = ''   # filled for UUT only

    def to_dict(self) -> dict:
        return {
            'instrument_type': self.instrument_type,
            'make':            self.make,
            'model':           self.model,
            'serial_no':       self.serial_no,
            'cert_number':     self.cert_number,
            'tag_number':      self.tag_number,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'InstrumentInfo':
        return cls(
            instrument_type=d.get('instrument_type', ''),
            make=d.get('make', ''),
            model=d.get('model', ''),
            serial_no=d.get('serial_no', ''),
            cert_number=d.get('cert_number', ''),
            tag_number=d.get('tag_number', ''),
        )


@dataclass
class CalibrationSession:
    """
    One complete calibration run.
    Header fields  → go on the certificate (SRS §8.1)
    master_info    → master RTD instrument details
    uut_info       → unit under test instrument details
    points         → one CalibrationPoint per setpoint (SRS §8.2)
    """
    cert_no:      str
    customer:     str
    address:      str
    performed_by: str
    verified_by:  str
    setpoints:    List[float]
    date:         date = field(default_factory=date.today)
    master_info:  InstrumentInfo = field(default_factory=InstrumentInfo)
    uut_info:     InstrumentInfo = field(default_factory=InstrumentInfo)
    points:       List[CalibrationPoint] = field(default_factory=list)

    @property
    def time_str(self) -> str:
        if self.points:
            return self.points[0].timestamp.strftime('%H:%M')
        return datetime.now().strftime('%H:%M')
