"""
Main Window — the application shell and controller.
Owns all services (comm, store) and wires all screen signals.
"""
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget,
    QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot

from ui.styles import APP_QSS
from ui.live_screen      import LiveScreen
from ui.setup_screen     import SetupScreen
from ui.exec_screen      import ExecScreen
from ui.reports_screen   import ReportsScreen
from ui.report_view      import ReportView
from ui.settings_screen  import SettingsScreen

from comm.simulator import SimulatorComm
from comm.usb_comm  import USBComm, list_com_ports

from calibration.engine import CalibrationEngine, Phase
from db.report_store    import ReportStore
from db.settings_store  import SettingsStore
from report_gen         import generate_pdf
from models             import CalibrationSession
from models.calibration_point import CalibrationPoint

_IDX_LIVE     = 0
_IDX_SETUP    = 1
_IDX_EXEC     = 2
_IDX_REPORTS  = 3
_IDX_REPORT   = 4
_IDX_SETTINGS = 5


class MainWindow(QMainWindow):

    def __init__(self, use_simulator: bool = True):
        super().__init__()
        self.setWindowTitle('Dry Block Calibrator — TIPL')
        self.resize(1150, 720)
        self.setMinimumSize(920, 620)

        self._store     = ReportStore()
        self._settings  = SettingsStore()
        self._comm      = SimulatorComm() if use_simulator else USBComm()
        self._engine: CalibrationEngine | None = None
        self._current_session: CalibrationSession | None = None

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

        ports = list_com_ports() or ['COM3', 'COM4']
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
        self._live_scr.disconnect_requested.connect(self._on_disconnect)
        self._live_scr.start_cal_requested.connect(lambda: self._nav_to('setup'))
        self._live_scr.exit_btn.clicked.connect(self.close)

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
        ok = self._comm.connect(port)
        self._live_scr.set_connected(ok, port)
        if ok:
            self._read_timer.start()
            self._conn_chip.setText('● Connected')
            self._conn_chip.setStyleSheet(
                'background:#1a3a2a;color:#22c55e;border-radius:20px;'
                'padding:6px 14px;font-size:12px;font-weight:600;margin:10px;'
            )
            self._live_scr.log('ok', f'Connected to {port} @ 9600 8N1')
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
        settings = self._settings.load()
        mfg = settings.get('manufacturer', {})
        max_seconds = int(mfg.get('max_stabilization_min', 10.0) * 60)
        volatility_window = mfg.get('volatility_time_min', 3.0)
        volatility_limit  = mfg.get('volatility_limit', 0.1)
        self._max_stab_seconds = max_seconds

        self._exec_scr.start(session.cert_no, session.customer, len(session.setpoints), max_seconds)
        self._exec_scr.set_setpoint(session.setpoints[0], 0, len(session.setpoints))

        self._engine = CalibrationEngine(
            session=session,
            comm=self._comm,
            max_stabilization_seconds=max_seconds,
            volatility_window_minutes=volatility_window,
            volatility_limit=volatility_limit,
            on_phase_change=self._on_phase_change,
            on_tick=self._on_timer_tick,
            on_point_ready=self._on_point_ready,
            on_complete=self._on_calibration_complete,
        )
        self._nav_to('exec')
        self._live_scr.log('info',
            f'Calibration started · {len(session.setpoints)} setpoints · {session.cert_no}')

    def _on_phase_change(self, phase: Phase) -> None:
        self._exec_scr.set_phase(phase)
        if phase == Phase.STABILIZING:
            self._exec_scr.set_remaining(self._max_stab_seconds)

    def _on_timer_tick(self, remaining: int) -> None:
        self._exec_scr.set_remaining(remaining)

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
    @pyqtSlot(str, str, str)
    def _on_search_reports(self, cert_no: str, tag_number: str, serial_no: str) -> None:
        sessions = self._store.search(
            cert_no=cert_no,
            tag_number=tag_number,
            serial_no=serial_no,
        )
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
