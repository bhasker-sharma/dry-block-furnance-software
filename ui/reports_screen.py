"""
Reports Screen — search and retrieve calibration records.

Filter strategy: UUT Serial No only.
Every UUT must have a serial number entered at calibration time (see
SetupScreen), and it's how the instrument is identified by its
manufacturer — a stable, always-present key. Certificate No and Tag
Number are shown in the results table but aren't separate search
filters; a substring serial-no search is enough to find a record.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QScrollArea, QGroupBox, QSizePolicy, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.widgets import make_button
from models.calibration_session import CalibrationSession


class ReportsScreen(QWidget):
    search_requested = pyqtSignal(str)   # serial_no
    view_requested   = pyqtSignal(object)
    pdf_requested    = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions: list[CalibrationSession] = []
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # top bar
        topbar = QWidget()
        topbar.setObjectName('topbar')
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 12, 20, 12)
        vt = QVBoxLayout()
        title = QLabel('Reports')
        title.setObjectName('screen_title')
        sub = QLabel('Search & retrieve calibration certificates')
        sub.setObjectName('screen_sub')
        vt.addWidget(title)
        vt.addWidget(sub)
        tb.addLayout(vt)
        tb.addStretch()
        root.addWidget(topbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(20, 16, 20, 16)
        cv.setSpacing(14)

        cv.addWidget(self._build_filter_card())
        cv.addWidget(self._build_results_card())
        cv.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll)

    # ------------------------------------------------------------------
    def _build_filter_card(self) -> QGroupBox:
        box = QGroupBox('Search')
        box.setObjectName('card')
        box.setStyleSheet(
            'QGroupBox{border:1px solid #d1d9e6;}'
        )
        h = QHBoxLayout(box)
        h.setSpacing(14)

        col = QVBoxLayout()
        lbl = QLabel('UUT Serial No (required)')
        lbl.setStyleSheet('font-size:11px;color:#6b7a90;font-weight:400;')
        self._f_serial = QLineEdit()
        self._f_serial.setPlaceholderText('e.g. SN-20240519')
        self._f_serial.returnPressed.connect(self._on_search)
        col.addWidget(lbl)
        col.addWidget(self._f_serial)
        h.addLayout(col, 1)

        btn_col = QVBoxLayout()
        btn_col.addStretch()
        search_btn = make_button('Search', 'primary')
        search_btn.clicked.connect(self._on_search)
        clear_btn = make_button('Clear', 'ghost')
        clear_btn.clicked.connect(self._on_clear)
        btn_col.addWidget(search_btn)
        btn_col.addWidget(clear_btn)
        h.addLayout(btn_col)

        return box

    def _build_results_card(self) -> QGroupBox:
        box = QGroupBox('Records')
        box.setObjectName('card')
        box.setStyleSheet(
            'QGroupBox{border:1px solid #d1d9e6;}'
        )
        v = QVBoxLayout(box)

        self._count_label = QLabel('0 records')
        self._count_label.setStyleSheet('font-size:11px;color:#6b7a90;font-weight:400;')
        v.addWidget(self._count_label)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels([
            'Certificate No', 'Date', 'Customer',
            'UUT Tag No', 'UUT Serial No', 'Points', 'Actions'
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setMinimumHeight(300)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        v.addWidget(self._table)

        return box

    # ------------------------------------------------------------------
    # Public API — MainWindow calls this after a search
    # ------------------------------------------------------------------
    def load_sessions(self, sessions: list[CalibrationSession]) -> None:
        self._sessions = sessions
        self._table.setRowCount(0)
        n = len(sessions)
        self._count_label.setText(f'{n} record{"s" if n != 1 else ""} found')

        for session in sessions:
            row = self._table.rowCount()
            self._table.insertRow(row)

            cells = [
                (session.cert_no,                     True),
                (session.date.isoformat(),             False),
                (session.customer,                     False),
                (session.uut_info.tag_number or '—',   False),
                (session.uut_info.serial_no  or '—',   False),
                (str(len(session.points)),             False),
            ]
            for col, (text, bold) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if bold:
                    from PyQt5.QtGui import QFont
                    f = item.font(); f.setBold(True); item.setFont(f)
                self._table.setItem(row, col, item)

            # Actions column
            btn_w = QWidget()
            bh = QHBoxLayout(btn_w)
            bh.setContentsMargins(4, 2, 4, 2)
            bh.setSpacing(4)
            for icon, sig in [('👁 View', self.view_requested), ('⬇ PDF', self.pdf_requested)]:
                b = QPushButton(icon)
                b.setFixedHeight(26)
                b.setStyleSheet(
                    'QPushButton{border:1px solid #d1d9e6;border-radius:4px;'
                    'background:#fff;font-size:11px;padding:0 6px;}'
                    'QPushButton:hover{background:#f0f4fa;}'
                )
                b.clicked.connect(lambda _, s=session, sg=sig: sg.emit(s))
                bh.addWidget(b)
            self._table.setCellWidget(row, 6, btn_w)

    # ------------------------------------------------------------------
    def _on_search(self) -> None:
        serial = self._f_serial.text().strip()
        if not serial:
            QMessageBox.warning(self, 'UUT Serial No required',
                                 'Enter a UUT Serial No to search.')
            return
        self.search_requested.emit(serial)

    def _on_clear(self) -> None:
        self._f_serial.clear()
        self.search_requested.emit('')

    def _on_double_click(self, row: int, _col: int) -> None:
        if row < len(self._sessions):
            self.view_requested.emit(self._sessions[row])
