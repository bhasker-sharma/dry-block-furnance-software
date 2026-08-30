"""
Main Window — the application shell and controller.
Owns all services (comm, store) and wires all screen signals.
"""
import sys
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget,
    QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QIcon

from ui.styles import APP_QSS
from ui.live_screen      import LiveScreen
from ui.setup_screen     import SetupScreen
from ui.exec_screen      import ExecScreen
from ui.reports_screen   import ReportsScreen
from ui.report_view      import ReportView
from ui.settings_screen  import SettingsScreen
from ui.connect_worker   import ConnectWorker

from comm.usb_comm  import USBComm, list_com_ports

from calibration.engine import CalibrationEngine, Phase
from db.report_store    import ReportStore
from db.settings_store  import SettingsStore, clamp_stability_limit
from report_gen         import generate_pdf
from models             import CalibrationSession
from models.calibration_point import CalibrationPoint

_IDX_LIVE     = 0
_IDX_SETUP    = 1
_IDX_EXEC     = 2
_IDX_REPORTS  = 3
_IDX_REPORT   = 4
_IDX_SETTINGS = 5


def _icon_path() -> Path:
    """Same resolution as main.py's _icon_path() — bundled read-only
    resources live under sys._MEIPASS when frozen (PyInstaller --onefile
    extracts them there at startup), unlike writable data which anchors to
    the exe's own folder instead (see db/settings_store.py's _app_root())."""
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent.parent
    return base / 'asset' / 'logo.ico'


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Dry Block Calibrator — TIPL')
        self.resize(1150, 720)
        self.setMinimumSize(920, 620)
        icon_path = _icon_path()
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._settings  = SettingsStore()
        self._store     = ReportStore()
        self._comm      = USBComm()
        self._engine: CalibrationEngine | None = None
        self._current_session: CalibrationSession | None = None
        self._connect_worker: ConnectWorker | None = None
        self._connect_cancelled = False

        self._live_fur    = None
        self._live_master = None
        self._live_uut    = None

        self.setStyleSheet(APP_QSS)
        self._build_ui()

        self._read_timer = QTimer(self)
        self._read_timer.setInterval(1000)
        self._read_timer.timeout.connect(self._on_read_tick)

    # ------------------------------------------------------------------
    # UI assembly
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName('centralWidget')
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())

        self._stack = QStackedWidget()
        self._stack.setObjectName('contentStack')

        # Always offer the TCP simulator target too, alongside whatever real
        # COM ports Windows currently sees — no virtual COM driver (com0com)
        # needed to test against `simulator.py --transport tcp`.
        ports = (list_com_ports() or ['COM3', 'COM4']) + ['TCP:127.0.0.1:5025']
        self._live_scr     = LiveScreen(ports)
        self._setup_scr    = SetupScreen()
        self._exec_scr     = ExecScreen()
        self._reports_scr  = ReportsScreen()
        self._report_view  = ReportView()
        self._settings_scr = SettingsScreen()

        for scr in (self._live_scr, self._setup_scr, self._exec_scr,
                    self._reports_scr, self._report_view, self._settings_scr):
            self._stack.addWidget(scr)

        self._settings_scr.set_comm(self._comm)
        root.addWidget(self._stack)
        self._wire_signals()

        # Live Monitor's port field starts out on whatever was last saved
        # in Settings — still editable/overridable there before Connect.
        saved_port = self._settings.load().get('serial', {}).get('port')
        if saved_port:
            self._live_scr.set_port(saved_port)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(200)

        v = QVBoxLayout(sidebar)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        brand = QLabel('Dry Block')
        brand.setObjectName('brand_label')
        sub = QLabel('Calibrator')
        sub.setObjectName('brand_sub')
        v.addWidget(brand)
        v.addWidget(sub)

        nav_lbl = QLabel('WORKSPACE')
        nav_lbl.setStyleSheet(
            'color:#4a5568;font-size:10px;font-weight:700;'
            'padding:12px 16px 4px 16px;letter-spacing:1px;'
        )
        v.addWidget(nav_lbl)

        self._nav_btns: dict[str, QPushButton] = {}
        for key, label in [('live','Live Monitor'), ('reports','Reports'), ('settings','Settings')]:
            btn = QPushButton(label)
            self._nav_btns[key] = btn
            btn.clicked.connect(lambda _, k=key: self._nav_to(k))
            v.addWidget(btn)

        v.addStretch()

        self._conn_chip = QLabel('● Disconnected')
        self._conn_chip.setStyleSheet(
            'background:#2a1a1a;color:#ef4444;border-radius:20px;'
            'padding:6px 14px;font-size:12px;font-weight:600;margin:10px;'
        )
        v.addWidget(self._conn_chip)
        return sidebar

    # ------------------------------------------------------------------
    def _wire_signals(self) -> None:
        self._live_scr.connect_requested.connect(self._on_connect)
        self._live_scr.cancel_connect_requested.connect(self._on_cancel_connect)
        self._live_scr.disconnect_requested.connect(self._on_disconnect)
        self._live_scr.start_cal_requested.connect(lambda: self._nav_to('setup'))
        self._live_scr.exit_btn.clicked.connect(self.close)

        self._settings_scr.save_requested.connect(self._on_settings_saved)

        self._setup_scr.start_requested.connect(self._on_start_calibration)
        self._setup_scr.cancel_requested.connect(lambda: self._nav_to('live'))

        self._exec_scr.stop_requested.connect(self._on_stop_calibration)
        self._exec_scr.view_report_btn.clicked.connect(
            lambda: self._show_report(self._current_session)
        )

        self._reports_scr.search_requested.connect(self._on_search_reports)
        self._reports_scr.view_requested.connect(self._show_report)
        self._reports_scr.pdf_requested.connect(self._on_export_pdf)

        self._report_view.back_requested.connect(lambda: self._nav_to('reports'))
        self._report_view.export_pdf.connect(self._on_export_pdf)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _nav_to(self, key: str) -> None:
        mapping = {
            'live': _IDX_LIVE, 'setup': _IDX_SETUP, 'exec': _IDX_EXEC,
            'reports': _IDX_REPORTS, 'report': _IDX_REPORT, 'settings': _IDX_SETTINGS,
        }
        self._stack.setCurrentIndex(mapping[key])

        active = key if key in ('live','reports','settings') else \
                 ('live' if key in ('setup','exec') else 'reports')
        for k, btn in self._nav_btns.items():
            btn.setProperty('active', 'true' if k == active else 'false')
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if key == 'reports':
            self._reports_scr.load_sessions(self._store.list_all())

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    @pyqtSlot(dict)
    def _on_settings_saved(self, settings: dict) -> None:
        saved_port = settings.get('serial', {}).get('port')
        if saved_port:
            self._live_scr.set_port(saved_port)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    @pyqtSlot(str)
    def _on_connect(self, port: str) -> None:
        if not self._settings.is_ready_for_connection():
            QMessageBox.warning(
                self, 'Settings Incomplete',
                'Before connecting, configure the calibrator range and at least '
                'one setpoint in Settings (and CMC points, if CMC is ON).'
            )
            self._live_scr.set_connected(False)
            return
        if self._connect_worker is not None:
            return  # a connection attempt is already in flight — ignore the extra click

        serial_cfg = self._settings.load().get('serial', {})
        baud      = int(serial_cfg.get('baud', 9600))
        timeout_s = int(serial_cfg.get('timeout_ms', 1000)) / 1000.0
        retries   = int(serial_cfg.get('retry', 3))

        # Run the (possibly slow, retries * timeout_s) connect attempt on a
        # worker thread so the GUI — including this screen's Cancel button
        # and every other screen — stays responsive while it's in progress.
        self._connect_cancelled = False
        self._live_scr.set_connecting()
        self._live_scr.log('info', f'Connecting to {port} @ {baud} baud…')

        worker = ConnectWorker(self._comm, port, baud, timeout_s, retries, parent=self)
        worker.finished_ok.connect(lambda ok, p=port, b=baud: self._on_connect_finished(ok, p, b))
        self._connect_worker = worker
        worker.start()

    @pyqtSlot()
    def _on_cancel_connect(self) -> None:
        if self._connect_worker is not None:
            self._connect_cancelled = True
            self._connect_worker.cancel()
            self._live_scr.log('warn', 'Cancelling — the in-flight attempt will still finish first…')

    def _on_connect_finished(self, ok: bool, port: str, baud: int) -> None:
        cancelled = self._connect_cancelled
        self._connect_cancelled = False
        worker, self._connect_worker = self._connect_worker, None
        if worker is not None:
            worker.wait()

        self._live_scr.set_connected(ok, port)
        if ok:
            self._read_timer.start()
            self._conn_chip.setText('● Connected')
            self._conn_chip.setStyleSheet(
                'background:#1a3a2a;color:#22c55e;border-radius:20px;'
                'padding:6px 14px;font-size:12px;font-weight:600;margin:10px;'
            )
            self._live_scr.log('ok', f'Connected to {port} @ {baud} 8N1')

            # Push the lab's configured stability tolerance (SOUR:STAB:LIM)
            # so SOUR:STAB:TEST? judges against our value, not whatever was
            # last set on the instrument's own front panel. Clamped here —
            # settings.json is hand-editable and may predate this field, so
            # this boundary can't assume the value is already in range.
            raw_limit = float(
                self._settings.load().get('manufacturer', {}).get('stability_limit_c', 0.05)
            )
            stab_limit = clamp_stability_limit(raw_limit)
            if stab_limit != raw_limit:
                self._live_scr.log('warn',
                    f'Stability tolerance {raw_limit:g} °C in settings is out of range '
                    f'(0.01-9.99) — clamped to {stab_limit:.2f} °C')
            if self._comm.set_stability_limit(stab_limit):
                self._live_scr.log('info', f'Stability tolerance set to {stab_limit:.2f} °C')
            else:
                self._live_scr.log('warn',
                    f'Could not confirm stability tolerance ({stab_limit:.2f} °C) on the instrument')
        elif cancelled:
            self._live_scr.log('warn', 'Connection attempt cancelled')
        else:
            reason = self._comm.last_error
            if reason:
                self._live_scr.log('err', reason)
                QMessageBox.warning(self, 'Connection Failed', reason)
            else:
                self._live_scr.log('err', f'Failed to open {port}')
                QMessageBox.warning(self, 'Connection Failed',
                                    f'Could not open {port}.\nCheck the cable and port.')

    @pyqtSlot()
    def _on_disconnect(self) -> None:
        self._read_timer.stop()
        self._comm.disconnect()
        self._live_scr.set_connected(False)
        self._conn_chip.setText('● Disconnected')
        self._conn_chip.setStyleSheet(
            'background:#2a1a1a;color:#ef4444;border-radius:20px;'
            'padding:6px 14px;font-size:12px;font-weight:600;margin:10px;'
        )
        self._live_scr.log('warn', 'Port closed — live read loop stopped')

    # ------------------------------------------------------------------
    # Live read tick
    # ------------------------------------------------------------------
    @pyqtSlot()
    def _on_read_tick(self) -> None:
        fur, master, uut = self._comm.read_temperatures()
        self._live_fur    = fur
        self._live_master = master
        self._live_uut    = uut
        self._live_scr.update_temperatures(fur, master, uut)

        if self._engine and self._stack.currentIndex() == _IDX_EXEC:
            self._exec_scr.update_temperatures(fur, master, uut)
            if None not in (fur, master, uut):
                self._engine.tick(fur, master, uut)

    # ------------------------------------------------------------------
    # Calibration flow
    # ------------------------------------------------------------------
    @pyqtSlot(object)
    def _on_start_calibration(self, session: CalibrationSession) -> None:
        self._current_session = session

        self._exec_scr.start(session.cert_no, session.customer, len(session.setpoints))
        self._exec_scr.set_setpoint(session.setpoints[0], 0, len(session.setpoints))

        self._engine = CalibrationEngine(
            session=session,
            comm=self._comm,
            on_phase_change=self._on_phase_change,
            on_point_ready=self._on_point_ready,
            on_complete=self._on_calibration_complete,
        )
        self._nav_to('exec')
        self._live_scr.log('info',
            f'Calibration started · {len(session.setpoints)} setpoints · {session.cert_no}')

    def _on_phase_change(self, phase: Phase) -> None:
        self._exec_scr.set_phase(phase)

    def _on_point_ready(self, point: CalibrationPoint) -> None:
        time_str = point.timestamp.strftime('%H:%M:%S')
        self._exec_scr.add_saved_point(
            point.setpoint, point.dry_block_temp, point.master_rtd, point.uut, time_str
        )
        if self._engine and self._engine.phase != Phase.COMPLETED:
            idx = self._engine.current_index
            sps = self._engine.session.setpoints
            self._exec_scr.set_setpoint(sps[idx], idx, len(sps))

    def _on_calibration_complete(self) -> None:
        saved_path = self._store.save(self._current_session)
        self._live_scr.log('ok',
            f'All setpoints complete — report saved to {saved_path.name}')

    @pyqtSlot()
    def _on_stop_calibration(self) -> None:
        reply = QMessageBox.question(
            self, 'Stop Calibration',
            'Stop the calibration?\nPoints already saved will be kept.',
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._engine = None
            self._nav_to('live')
            self._live_scr.log('warn', 'Calibration stopped — saved data preserved')

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    @pyqtSlot(str)
    def _on_search_reports(self, serial_no: str) -> None:
        sessions = self._store.search(serial_no=serial_no)
        self._reports_scr.load_sessions(sessions)

    def _show_report(self, session: CalibrationSession | None) -> None:
        if session is None:
            return
        full = self._store.load(session.cert_no) or session
        self._report_view.load_session(full)
        self._nav_to('report')

    @pyqtSlot(object)
    def _on_export_pdf(self, session: CalibrationSession | None) -> None:
        if session is None:
            return
        default = session.cert_no.replace('/', '_') + '.pdf'
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save PDF Report', default, 'PDF Files (*.pdf)'
        )
        if not path:
            return
        try:
            out = generate_pdf(session, Path(path))
            QMessageBox.information(self, 'PDF Exported', f'Saved to:\n{out}')
        except Exception as exc:
            QMessageBox.critical(self, 'PDF Error',
                                 f'Could not generate PDF:\n{exc}')

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        # Don't let a connection attempt in flight turn into a dangling
        # thread (or a Qt "destroyed while running" crash) on exit.
        if self._connect_worker is not None:
            self._connect_worker.cancel()
            self._connect_worker.wait(2000)
        super().closeEvent(event)
