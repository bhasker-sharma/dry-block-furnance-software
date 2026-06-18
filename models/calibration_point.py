from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CalibrationPoint:
    """One row of data captured at a single setpoint."""
    setpoint:       float
    dry_block_temp: float   # dry block's own internal reading
    master_rtd:     float
    uut:            float
    timestamp:      datetime = field(default_factory=datetime.now)

    @property
    def error(self) -> float:
        """Error = UUT − Master RTD."""
        return round(self.uut - self.master_rtd, 3)

    def to_dict(self) -> dict:
        return {
            'setpoint':       self.setpoint,
            'dry_block_temp': self.dry_block_temp,
            'master_rtd':     self.master_rtd,
            'uut':            self.uut,
            'error':          self.error,
            'timestamp':      self.timestamp.isoformat(),
        }
