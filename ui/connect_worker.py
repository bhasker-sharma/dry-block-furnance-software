"""
Background worker for BaseComm.connect().

connect() can block for up to retries * timeout_s seconds (each retry opens
a real serial port or socket and waits for it to respond). Calling it
directly from a Qt slot freezes the whole GUI for that entire span — the
window won't repaint, buttons won't respond, and Windows may flag it as
"Not Responding". Running it here on a QThread keeps the GUI thread free,
so the rest of the app stays usable while a connection attempt is in
flight, and the user can cancel it instead of waiting it out.
"""
from PyQt5.QtCore import QThread, pyqtSignal

from comm.base_comm import BaseComm


class ConnectWorker(QThread):
    """Runs comm.connect(...) off the GUI thread. Emits finished_ok(bool)
    once the attempt (all retries) completes, fails, or is cancelled."""

    finished_ok = pyqtSignal(bool)

    def __init__(self, comm: BaseComm, port: str, baud: int,
                 timeout_s: float, retries: int, parent=None):
        super().__init__(parent)
        self._comm = comm
        self._port = port
        self._baud = baud
        self._timeout_s = timeout_s
        self._retries = retries
        self._cancelled = False

    def cancel(self) -> None:
        """
        Best-effort cancel: stops any further retry attempts. The attempt
        already in flight isn't interrupted mid-syscall (not safely
        possible) — it still finishes, bounded by the port's own timeout.
        """
        self._cancelled = True

    def run(self) -> None:
        ok = self._comm.connect(
            self._port, baud=self._baud,
            timeout_s=self._timeout_s, retries=self._retries,
            should_abort=lambda: self._cancelled,
        )
        if ok and self._cancelled:
            # Connected right as cancel came in — honor the cancel, not the race.
            self._comm.disconnect()
            ok = False
        self.finished_ok.emit(ok)
