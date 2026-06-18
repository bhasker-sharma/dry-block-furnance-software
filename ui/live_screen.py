"""
Live Monitor Screen — first screen the user sees.
Shows 3 temperature readouts, connection controls, and the status log.
Matches screens_a.jsx : LiveScreen component.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QScrollArea, QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.widgets import ReadoutWidget, ConsoleWidget, make_button
from comm.base_comm import BaseComm


class LiveScreen(QWidget):
    """
    Why signals?
    Screens communicate upward via Qt signals — they never directly call
    methods on other screens or the main window. This keeps each screen
    self-contained and testable.
    """
    connect_requested    = pyqtSignal(str)   # emits port name
    disconnect_requested = pyqtSignal()
    start_cal_requested  = pyqtSignal()

    def __init__(self, available_ports: list[str], parent=None):
        super().__init__(parent)
        self._build_ui(available_ports)

    # ------------------------------------------------------------------
    def _build_ui(self, ports: list[str]) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── top bar ──────────────────────────────────────────────────
        topbar = QWidget()
        topbar.setObjectName('topbar')
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 12, 20, 12)
        title = QLabel('Live Monitor')
        title.setObjectName('screen_title')
        sub   = QLabel('Real-time dry block & sensor temperatures')
        sub.setObjectName('screen_sub')
        vt = QVBoxLayout()
        vt.addWidget(title)
        vt.addWidget(sub)
        tb.addLayout(vt)
        tb.addStretch()
        self._status_pill = QLabel('● Disconnected')
        self._status_pill.setStyleSheet(
            'background:#2a1a1a;color:#ef4444;border-radius:12px;'
            'padding:4px 12px;font-size:12px;font-weight:600;'
        )
        tb.addWidget(self._status_pill)
        root.addWidget(topbar)

        # ── scrollable content ───────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(20, 16, 20, 16)
        cv.setSpacing(16)

        # readout row
        readout_row = QHBoxLayout()
        readout_row.setSpacing(12)
        self._ro_furnace = ReadoutWidget('Dry Block Internal', 'Dry Block', '#6366f1')
        self._ro_master  = ReadoutWidget('Standard RTD',    'Reference', '#3d7fff')
        self._ro_uut     = ReadoutWidget('Unit Under Test', 'UUT',       '#f59e0b')
        for r in (self._ro_furnace, self._ro_master, self._ro_uut):
            r.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            readout_row.addWidget(r)
        cv.addLayout(readout_row)

        # connection card + start-cal card (side by side)
        mid_row = QHBoxLayout()
        mid_row.setSpacing(12)
        mid_row.addWidget(self._build_conn_card(ports), 3)
        mid_row.addWidget(self._build_start_card(),     2)
        cv.addLayout(mid_row)

        # status console
        console_box = QGroupBox('Status & Messages')
        console_box.setObjectName('card')
        console_box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        cb = QVBoxLayout(console_box)
        self._console = ConsoleWidget()
        self._console.setMinimumHeight(130)
        cb.addWidget(self._console)
        cv.addWidget(console_box)

        # exit button
        exit_row = QHBoxLayout()
        exit_row.addStretch()
        self._exit_btn = make_button('Exit Application', 'ghost')
        exit_row.addWidget(self._exit_btn)
        cv.addLayout(exit_row)
        cv.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll)

    def _build_conn_card(self, ports: list[str]) -> QGroupBox:
        box = QGroupBox('Connection')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        h = QHBoxLayout(box)

        # interface (fixed USB for now, RS232 later)
        iface_col = QVBoxLayout()
        iface_col.addWidget(QLabel('Interface'))
        self._iface_combo = QComboBox()
        self._iface_combo.addItems(['USB', 'RS232'])
        self._iface_combo.setEnabled(False)
        iface_col.addWidget(self._iface_combo)
        h.addLayout(iface_col)

        # port selector
        port_col = QVBoxLayout()
        port_col.addWidget(QLabel('COM Port'))
        self._port_combo = QComboBox()
        self._port_combo.addItems(ports if ports else ['COM3'])
        port_col.addWidget(self._port_combo)
        h.addLayout(port_col)

        h.addStretch()

        # connect/disconnect
        btn_col = QVBoxLayout()
        btn_col.addStretch()
        self._conn_btn = make_button('Connect', 'primary')
        self._conn_btn.clicked.connect(self._on_conn_click)
        btn_col.addWidget(self._conn_btn)
        h.addLayout(btn_col)

        return box

    def _build_start_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName('card')
        card.setStyleSheet(
            '#card{background:#3d7fff;border-radius:10px;}'
        )
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 16, 18, 16)
        lbl = QLabel('Start Calibration')
        lbl.setStyleSheet('color:#fff;font-size:15px;font-weight:700;')
        sub = QLabel('Enter certificate details and up to 10 setpoints.')
        sub.setStyleSheet('color:#c7d8ff;font-size:12px;')
        sub.setWordWrap(True)
        v.addWidget(lbl)
        v.addWidget(sub)
        v.addStretch()
        self._start_btn = QPushButton('▶  Begin')
        self._start_btn.setEnabled(False)
        self._start_btn.setStyleSheet(
            'QPushButton{background:#fff;color:#3d7fff;border:none;'
            'border-radius:6px;padding:9px 18px;font-weight:700;}'
            'QPushButton:hover{background:#ebf2ff;}'
            'QPushButton:disabled{background:#7faeff;color:#c7d8ff;}'
        )
        self._start_btn.clicked.connect(self.start_cal_requested)
        v.addWidget(self._start_btn)
        return card

    # ------------------------------------------------------------------
    # Public API called by MainWindow
    # ------------------------------------------------------------------
    def update_temperatures(self, fur, master, uut) -> None:
        self._ro_furnace.set_value(fur)
        self._ro_master.set_value(master)
        self._ro_uut.set_value(uut)

    def set_connected(self, connected: bool, port: str = '') -> None:
        self._port_combo.setEnabled(not connected)
        self._start_btn.setEnabled(connected)
        if connected:
            self._conn_btn.setText('Disconnect')
            self._conn_btn.setProperty('role', 'danger')
            self._status_pill.setText('● Connected')
            self._status_pill.setStyleSheet(
                'background:#1a3a2a;color:#22c55e;border-radius:12px;'
                'padding:4px 12px;font-size:12px;font-weight:600;'
            )
        else:
            self._conn_btn.setText('Connect')
            self._conn_btn.setProperty('role', 'primary')
            self._status_pill.setText('● Disconnected')
            self._status_pill.setStyleSheet(
                'background:#2a1a1a;color:#ef4444;border-radius:12px;'
                'padding:4px 12px;font-size:12px;font-weight:600;'
            )
            self.update_temperatures(None, None, None)
        # refresh dynamic property style
        self._conn_btn.style().unpolish(self._conn_btn)
        self._conn_btn.style().polish(self._conn_btn)

    def log(self, kind: str, message: str) -> None:
        self._console.append(kind, message)

    @property
    def exit_btn(self) -> QPushButton:
        return self._exit_btn

    # ------------------------------------------------------------------
    def _on_conn_click(self) -> None:
        if self._conn_btn.text().startswith('Connect'):
            self.connect_requested.emit(self._port_combo.currentText())
        else:
            self.disconnect_requested.emit()
