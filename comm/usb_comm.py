import re
import socket
import time
from typing import Callable, Optional, Tuple

import serial
import serial.tools.list_ports

from comm.base_comm import BaseComm

_NUM_RE = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')


class USBComm(BaseComm):
    """
    Serial communication with the dry block controller (Fluke 9144 Field
    Metrology Well). The 9144 has a single RS-232 DB-9 interface — no USB
    — wired 8 data bits / no parity / 1 stop bit, always (see internal_
    reference/fluke furnance/9144 protocal (1).pdf, §6.1.2); baud is the
    only serial parameter that's actually configurable, from the fixed set
    {1200, 2400, 4800, 9600, 19200, 38400} (§SYST:COMM:SER:BAUD). If your
    PC has no COM port and you're using a USB-to-serial adapter cable,
    Windows still presents it as a COM port — the app talks to it exactly
    the same way.

    ASCII SCPI commands terminated with CR — this is the exact command set
    `simulator.py` (repo root) answers, so from here the app cannot tell
    simulator and real hardware apart. Point `connect()` at the
    simulator's serial port during development and at the real
    instrument's port once it arrives — nothing else changes.

    If com0com isn't cooperating, `simulator.py --transport tcp` exposes
    the same protocol over a TCP socket instead of a virtual COM port —
    pass a port string of the form "TCP:host:port" (e.g. "TCP:127.0.0.1:5025")
    to connect() to use it, no virtual serial driver required.
    """

    def __init__(self):
        self._serial: Optional[serial.Serial] = None
        self._socket: Optional[socket.socket] = None
        self._timeout_s: float = 1.0
        self.last_error: Optional[str] = None

    def connect(self, port: str, baud: int = 9600,
                timeout_s: float = 1.0, retries: int = 1,
                should_abort: Optional[Callable[[], bool]] = None) -> bool:
        tcp_target = self._parse_tcp_target(port)
        attempts = max(1, retries)
        self._timeout_s = timeout_s
        self.last_error = None
        for attempt in range(attempts):
            if should_abort is not None and should_abort():
                return False
            try:
                if tcp_target:
                    host, tcp_port = tcp_target
                    sock = socket.create_connection((host, tcp_port), timeout=max(timeout_s, 2.0))
                    sock.settimeout(timeout_s)
                    self._socket = sock
                    self._serial = None
                else:
                    # 8N1 — the 9144 has no other option (see 9144 protocal PDF §6.1.2),
                    # so this is not user-configurable.
                    self._serial = serial.Serial(
                        port=port, baudrate=baud,
                        bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE, timeout=timeout_s,
                    )
                    self._socket = None
                    # Discard anything already sitting in the pipe before we
                    # send a single command. A prior aborted attempt's
                    # response can still be queued here (closing our handle
                    # doesn't clear a virtual null-modem pair's buffer), and
                    # reading it as the answer to *this* attempt's *IDN?
                    # desyncs every request/response pair from here on.
                    self._serial.reset_input_buffer()
            except (serial.SerialException, OSError):
                self._serial = None
                self._socket = None
                if attempt + 1 < attempts:
                    if should_abort is not None and should_abort():
                        return False
                    time.sleep(0.3)
                continue

            if not self.is_connected:
                continue

            # Port opened — now verify it's actually a HART/9144 (-P model)
            # before handing it to the rest of the app. There's no
            # stabilization timeout anymore (see CalibrationEngine), so a
            # wrong or non-responsive instrument would otherwise poll
            # forever with no way out except Stop — this check is what
            # catches that case up front instead.
            if self._verify_instrument():
                return True
            self.disconnect()
            return False  # a bad handshake won't fix itself on retry
        return False

    def _verify_instrument(self) -> bool:
        idn = self._query_str('*IDN?')
        if not idn or 'HART' not in idn.upper() or '9144' not in idn:
            self.last_error = (
                f"Unrecognized instrument (*IDN? -> {idn!r}). "
                "Expected a HART 9144."
            )
            return False

        model = self._query_str('SYST:CONF:MOD?')
        if model is None or model.strip() != '1':
            self.last_error = (
                f"Connected instrument is not a -P model (SYST:CONF:MOD? -> {model!r}). "
                "Reference/UUT channels are required."
            )
            return False

        self._write('UNIT:TEMP C')
        return True

    def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        self._serial = None
        self._socket = None

    def read_temperatures(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        dry_block = self._query_float('SOUR:SENS:DATA?')
        master    = self._query_float('CALC1:DATA?')
        uut       = self._query_float('CALC2:DATA?')
        return dry_block, master, uut

    def read_stable(self) -> bool:
        """True once the instrument's own SOUR:STAB:TEST? reports settled (1)."""
        reply = self._query_str('SOUR:STAB:TEST?')
        return reply is not None and reply.strip() == '1'

    def send_setpoint(self, temperature: float) -> bool:
        if not self.is_connected:
            return False
        try:
            self._write(f'SOUR:SPO {temperature:.3f}')
            readback = self._query_float('SOUR:SPO?')
            return readback is not None and abs(readback - temperature) < 0.05
        except (serial.SerialException, OSError):
            return False

    def set_stability_limit(self, limit_c: float) -> bool:
        """Push the stability tolerance (SOUR:STAB:LIM, °C — 0.01 to 9.99
        per the 9144 protocol) so SOUR:STAB:TEST? judges against it."""
        if not self.is_connected:
            return False
        try:
            self._write(f'SOUR:STAB:LIM {limit_c:.2f}')
            readback = self._query_float('SOUR:STAB:LIM?')
            return readback is not None and abs(readback - limit_c) < 0.005
        except (serial.SerialException, OSError):
            return False

    def get_stability_limit(self) -> Optional[float]:
        """Read the stability tolerance currently set on the instrument."""
        return self._query_float('SOUR:STAB:LIM?')

    @property
    def is_connected(self) -> bool:
        return (self._serial is not None and self._serial.is_open) or self._socket is not None

    # ------------------------------------------------------------------
    # Internal — wire framing (SCPI: ASCII command + CR, ASCII reply + CR)
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_tcp_target(port: str) -> Optional[Tuple[str, int]]:
        """"TCP:host:port" -> (host, port); anything else -> None (real serial port)."""
        if not port.upper().startswith('TCP:'):
            return None
        host, _, p = port[4:].rpartition(':')
        if host and p.isdigit():
            return host, int(p)
        return None

    def _write(self, command: str) -> None:
        payload = command.encode('ascii') + b'\r'
        if self._serial is not None:
            self._serial.write(payload)
        else:
            self._socket.sendall(payload)

    def _read_byte(self) -> Optional[bytes]:
        """One byte, b'' on a timeout tick (keep waiting), None if the connection closed."""
        if self._serial is not None:
            return self._serial.read(1)
        try:
            data = self._socket.recv(1)
        except socket.timeout:
            return b''
        except OSError:
            return None
        return data if data else None

    def _read_line(self, overall_timeout: Optional[float] = None) -> Optional[str]:
        """Accumulate bytes until CR or LF, bounded by overall_timeout seconds."""
        buf = bytearray()
        deadline = time.monotonic() + (overall_timeout if overall_timeout is not None else self._timeout_s)
        while time.monotonic() < deadline:
            b = self._read_byte()
            if b is None:
                return None
            if not b:
                continue
            if b in (b'\r', b'\n'):
                if buf:
                    return buf.decode('ascii', errors='replace')
                continue
            buf.extend(b)
        return buf.decode('ascii', errors='replace') if buf else None

    def _query_float(self, command: str) -> Optional[float]:
        if not self.is_connected:
            return None
        try:
            self._write(command)
            line = self._read_line()
            if not line:
                return None
            m = _NUM_RE.search(line)
            return round(float(m.group()), 3) if m else None
        except (serial.SerialException, OSError):
            return None

    def _query_str(self, command: str) -> Optional[str]:
        if not self.is_connected:
            return None
        try:
            self._write(command)
            return self._read_line()
        except (serial.SerialException, OSError):
            return None


def list_com_ports() -> list:
    """Return available COM port names on this PC."""
    return [p.device for p in serial.tools.list_ports.comports()]
