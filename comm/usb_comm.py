import serial
import serial.tools.list_ports
from typing import Optional, Tuple
from comm.base_comm import BaseComm


class USBComm(BaseComm):
    """
    Real USB/serial communication with the dry block controller.
    Command codes are placeholders — update when protocol is confirmed (SRS §11).
    """

    CMD_SET_TEMP        = 10   # send setpoint
    CMD_READ_FUR        = 11   # read dry block internal sensor
    CMD_READ_MASTER     = 12   # read standard RTD
    CMD_READ_UUT        = 13   # read UUT sensor
    CMD_READ_VOLATILITY = 14   # read fluctuation over a time window — placeholder

    def __init__(self):
        self._serial: Optional[serial.Serial] = None

    def connect(self, port: str, baud: int = 9600) -> bool:
        try:
            self._serial = serial.Serial(
                port=port, baudrate=baud,
                bytesize=8, parity='N', stopbits=1,
                timeout=1.0
            )
            return self._serial.is_open
        except serial.SerialException:
            self._serial = None
            return False

    def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    def read_temperatures(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        # TODO: implement actual read commands when protocol is confirmed
        # Example pattern:
        #   self._send_command(self.CMD_READ_FUR)
        #   response = self._serial.read(n)
        #   dry_block = self._parse_response(response)
        dry_block = self._read_one(self.CMD_READ_FUR)
        master    = self._read_one(self.CMD_READ_MASTER)
        uut       = self._read_one(self.CMD_READ_UUT)
        return dry_block, master, uut

    def read_volatility(self, window_minutes: float) -> Optional[float]:
        # TODO: implement once the dry block's volatility/fluctuation
        # protocol command is confirmed. The device is expected to report
        # this directly (see CMD_READ_VOLATILITY) rather than the app
        # computing it from raw readings.
        return self._read_one(self.CMD_READ_VOLATILITY)

    def send_setpoint(self, temperature: float) -> bool:
        # TODO: build and send the actual command packet
        return True

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def _read_one(self, cmd: int) -> Optional[float]:
        """Send a read command, receive response, parse temperature."""
        if not self.is_connected:
            return None
        try:
            # Placeholder: replace with real packet format
            self._serial.write(bytes([cmd]))
            raw = self._serial.read(4)
            if len(raw) < 4:
                return None
            # TODO: parse raw bytes into float per protocol spec
            return None
        except serial.SerialException:
            return None


def list_com_ports() -> list:
    """Return available COM port names on this PC."""
    return [p.device for p in serial.tools.list_ports.comports()]
