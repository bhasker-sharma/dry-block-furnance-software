"""
Report / Certificate View Screen.
Shows the full calibration certificate including instrument details.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QFrame, QGroupBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor

from ui.widgets import make_button
from models.calibration_session import CalibrationSession, InstrumentInfo
from db.settings_store import SettingsStore
from calibration.cmc import interpolate_cmc


class ReportView(QWidget):
    back_requested  = pyqtSignal()
    export_pdf      = pyqtSignal(object)
    print_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session: CalibrationSession | None = None
        self._settings = SettingsStore()
        self._build_shell()

    # ------------------------------------------------------------------
    def _build_shell(self) -> None:
        """Build the fixed chrome (topbar + scroll area). Content is rebuilt per session."""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        topbar = QWidget()
        topbar.setObjectName('topbar')
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 12, 20, 12)

        back_btn = make_button('← Back', 'ghost')
        back_btn.clicked.connect(self.back_requested)
        tb.addWidget(back_btn)

        vt = QVBoxLayout()
        self._title_lbl = QLabel('Calibration Certificate')
        self._title_lbl.setObjectName('screen_title')
        self._cert_lbl = QLabel('—')
        self._cert_lbl.setObjectName('screen_sub')
        vt.addWidget(self._title_lbl)
        vt.addWidget(self._cert_lbl)
        tb.addLayout(vt)
        tb.addStretch()

        pdf_btn = make_button('⬇  Export PDF', '')
        pdf_btn.clicked.connect(lambda: self.export_pdf.emit(self._session))
        tb.addWidget(pdf_btn)

        root.addWidget(topbar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet('background:#f0f4fa;')
        root.addWidget(self._scroll)

    # ------------------------------------------------------------------
    def load_session(self, session: CalibrationSession) -> None:
        """Rebuild the certificate body for this session."""
        self._session = session
        self._cert_lbl.setText(session.cert_no)

        cert_widget = QWidget()
        cert_widget.setStyleSheet('background:#f0f4fa;')
        outer = QVBoxLayout(cert_widget)
        outer.setContentsMargins(40, 20, 40, 20)
        outer.setSpacing(0)

        # white certificate card
        card = QWidget()
        card.setStyleSheet('background:#ffffff;border-radius:12px;')
        cv = QVBoxLayout(card)
        cv.setContentsMargins(28, 24, 28, 28)
        cv.setSpacing(14)

        cv.addLayout(self._header_row(session))
        cv.addWidget(self._hr())
        cv.addWidget(self._meta_card(session))
        cv.addLayout(self._instrument_row(session))
        cv.addWidget(_section('Calibration Readings'))
        cv.addWidget(self._readings_table(session))
        cv.addLayout(self._summary_row(session))
        cv.addWidget(self._hr())
        cv.addLayout(self._signature_row(session))

        outer.addWidget(card)
        outer.addStretch()
        self._scroll.setWidget(cert_widget)

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------
    def _header_row(self, s: CalibrationSession) -> QHBoxLayout:
        h = QHBoxLayout()
        logo = QLabel('TIPL')
        logo.setStyleSheet('font-size:24px;font-weight:700;color:#3d7fff;')
        h.addWidget(logo)
        h.addSpacing(14)

        titles = QVBoxLayout()
        t = QLabel('Calibration Certificate')
        t.setStyleSheet('font-size:17px;font-weight:700;color:#1a2332;')
        sub = QLabel('Dry Block Temperature Calibrator  ·  TIPL Calibration Laboratory')
        sub.setStyleSheet('font-size:11px;color:#6b7a90;')
        titles.addWidget(t)
        titles.addWidget(sub)
        h.addLayout(titles)
        h.addStretch()
        return h

    def _meta_card(self, s: CalibrationSession) -> QWidget:
        """Certificate header details: cert no, date, customer, address."""
        w = QWidget()
        w.setStyleSheet('background:#f7f9fc;border-radius:8px;')
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(24)
        for lbl, val in [
            ('Certificate No', s.cert_no),
            ('Date / Time',    f'{s.date.isoformat()}  ·  {s.time_str}'),
            ('Customer',       s.customer),
            ('Address',        s.address or '—'),
        ]:
            col = QVBoxLayout()
            col.addWidget(_meta_lbl(lbl))
            col.addWidget(_meta_val(val))
            h.addLayout(col)
        return w

    def _instrument_row(self, s: CalibrationSession) -> QHBoxLayout:
        """Side-by-side instrument detail cards for Master RTD and UUT."""
        h = QHBoxLayout()
        h.setSpacing(12)
        h.addWidget(self._instrument_card('Master RTD  —  Standard Reference', s.master_info, '#3d7fff',
                                          extra_label='Certificate No', extra_value=s.master_info.cert_number))
        h.addWidget(self._instrument_card('UUT  —  Unit Under Test', s.uut_info, '#f59e0b',
                                          extra_label='Tag Number', extra_value=s.uut_info.tag_number))
        return h

    def _instrument_card(self, title: str, info: InstrumentInfo,
                          border: str, extra_label: str, extra_value: str) -> QGroupBox:
        box = QGroupBox(title)
        box.setStyleSheet(
            f'QGroupBox{{border:1px solid {border};}}'
            f'QGroupBox::title{{background:#ffffff;}}'
        )
        form_w = QWidget()
        grid = QHBoxLayout(form_w)
        grid.setContentsMargins(10, 6, 10, 6)
        grid.setSpacing(16)

        left_col = QVBoxLayout()
        right_col = QVBoxLayout()
        fields = [
            ('Instrument Type', info.instrument_type or '—'),
            ('Make',            info.make            or '—'),
            ('Model',           info.model           or '—'),
            ('Serial No',       info.serial_no       or '—'),
            (extra_label,       extra_value          or '—'),
        ]
        for i, (lbl, val) in enumerate(fields):
            col = left_col if i % 2 == 0 else right_col
            pair = QVBoxLayout()
            pair.addWidget(_meta_lbl(lbl))
            pair.addWidget(_meta_val(val))
            pair.addSpacing(4)
            col.addLayout(pair)

        grid.addLayout(left_col)
        grid.addLayout(right_col)
        v = QVBoxLayout(box)
        v.addWidget(form_w)
        return box

    def _readings_table(self, s: CalibrationSession) -> QTableWidget:
        settings = self._settings.load()
        cmc_enabled = bool(settings.get('cmc_enabled'))
        cmc_points  = settings.get('cmc_points', [])

        headers = ['#', 'Setpoint °C', 'Master RTD °C', 'UUT °C', 'Error °C']
        if cmc_enabled:
            headers.append('CMC')

        table = QTableWidget(len(s.points), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setMaximumHeight(40 + 32 * max(len(s.points), 1))

        for i, pt in enumerate(s.points):
            err  = pt.error
            sign = '+' if err >= 0 else ''
            cells = [
                str(i + 1), f'{pt.setpoint:.1f}',
                f'{pt.master_rtd:.2f}', f'{pt.uut:.2f}',
                f'{sign}{err:.3f}',
            ]
            if cmc_enabled:
                cmc_val = interpolate_cmc(cmc_points, pt.setpoint)
                cells.append(f'{cmc_val:.3f}' if cmc_val is not None else '—')
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if col == 4 and abs(err) > 1:
                    item.setForeground(QColor('#ef4444'))
                table.setItem(i, col, item)
        return table

    def _summary_row(self, s: CalibrationSession) -> QHBoxLayout:
        n = len(s.points)
        h = QHBoxLayout()
        h.setSpacing(10)
        for lbl, val, color in [
            ('Points', str(n), '#1a2332'),
        ]:
            chip = QWidget()
            chip.setStyleSheet('background:#f0f4fa;border-radius:8px;')
            cv = QVBoxLayout(chip)
            cv.setContentsMargins(12, 8, 12, 8)
            l = QLabel(lbl); l.setStyleSheet('font-size:10px;color:#6b7a90;')
            l.setAlignment(Qt.AlignCenter)
            v = QLabel(val)
            v.setStyleSheet(f'font-size:18px;font-weight:700;color:{color};')
            v.setAlignment(Qt.AlignCenter)
            cv.addWidget(l); cv.addWidget(v)
            h.addWidget(chip)
        return h

    def _signature_row(self, s: CalibrationSession) -> QHBoxLayout:
        h = QHBoxLayout()
        for name, role in [(s.performed_by, 'Test Performed By'), (s.verified_by, 'Verified By')]:
            col = QVBoxLayout()
            col.addWidget(_meta_val(name))
            col.addWidget(_meta_lbl(role))
            h.addLayout(col)
        h.addStretch()
        return h

    @staticmethod
    def _hr() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet('color:#e2e7ee;')
        return line


# ── small helpers ─────────────────────────────────────────────────────
def _section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet('font-size:10px;font-weight:700;color:#6b7a90;letter-spacing:0.8px;')
    return lbl

def _meta_lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet('font-size:10px;color:#6b7a90;')
    return lbl

def _meta_val(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet('font-size:12px;font-weight:600;color:#1a2332;')
    lbl.setWordWrap(True)
    return lbl
