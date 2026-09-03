"""
Calibration Setup Screen.

Layout (top to bottom, all in one scroll area):
  Row 1: Certificate Details card  |  Setpoints (read-only, from Settings)
  Row 2: UUT Details card

Why this layout?
The operator fills the certificate details once per session.
UUT details are physical — read from the instrument nameplate and change
per calibration, so they're entered here. Master RTD and setpoints are
lab-wide and configured once in Settings — this screen just shows them.
"""
from datetime import date
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit,
    QScrollArea, QFrame, QGroupBox, QFormLayout
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.widgets import make_button
from models.calibration_session import CalibrationSession, InstrumentInfo
from db.settings_store import SettingsStore
from db.report_store import ReportStore


def _form_card(title: str, color: str = '#d1d9e6') -> tuple[QGroupBox, QFormLayout]:
    box = QGroupBox(title)
    box.setObjectName('card')
    box.setStyleSheet(
        f'QGroupBox{{border:1px solid {color};}}'
        f'QGroupBox::title{{background:#ffffff;}}'
    )
    form = QFormLayout(box)
    form.setContentsMargins(8, 2, 8, 8)
    form.setVerticalSpacing(8)
    form.setHorizontalSpacing(12)
    form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    return box, form


class SetupScreen(QWidget):
    start_requested  = pyqtSignal(object)   # CalibrationSession
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = SettingsStore()
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── top bar ───────────────────────────────────────────────────
        topbar = QWidget()
        topbar.setObjectName('topbar')
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 12, 20, 12)

        back = make_button('← Back', 'ghost')
        back.clicked.connect(self.cancel_requested)
        tb.addWidget(back)

        vt = QVBoxLayout()
        title = QLabel('Calibration Setup')
        title.setObjectName('screen_title')
        sub   = QLabel('Certificate · UUT details')
        sub.setObjectName('screen_sub')
        vt.addWidget(title)
        vt.addWidget(sub)
        tb.addLayout(vt)
        tb.addStretch()

        cancel = make_button('Cancel', 'ghost')
        cancel.clicked.connect(self.cancel_requested)
        tb.addWidget(cancel)

        self._start_btn = make_button('▶  Start Calibration', 'primary')
        self._start_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._on_start)
        tb.addWidget(self._start_btn)
        root.addWidget(topbar)

        # ── scrollable content ────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(20, 16, 20, 20)
        cv.setSpacing(14)
        cv.setAlignment(Qt.AlignTop)

        row1 = QHBoxLayout()
        row1.setSpacing(14)
        row1.addWidget(self._build_cert_card(),       3, Qt.AlignTop)
        row1.addWidget(self._build_setpoints_card(),  2, Qt.AlignTop)
        cv.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(14)
        row2.addWidget(self._build_uut_card(), 1, Qt.AlignTop)
        cv.addLayout(row2)

        scroll.setWidget(content)
        root.addWidget(scroll)

    # ------------------------------------------------------------------
    # Card builders
    # ------------------------------------------------------------------
    def _build_cert_card(self) -> QGroupBox:
        box, form = _form_card('Certificate Details')

        self._cert_input  = QLineEdit()
        self._cert_input.setPlaceholderText('Fill UUT Serial No to generate')
        self._cert_input.setEnabled(False)
        self._cert_input.setStyleSheet('color:#a0aec0;')
        self._date_input  = QLineEdit(date.today().isoformat())
        self._date_input.setEnabled(False)
        self._date_input.setStyleSheet('color:#a0aec0;')
        self._cust_input  = QLineEdit()
        self._cust_input.setPlaceholderText('Company / organisation name')
        self._addr_input  = QTextEdit()
        self._addr_input.setPlaceholderText('Full address')
        self._addr_input.setFixedHeight(52)
        self._by_input    = QLineEdit()
        self._by_input.setPlaceholderText('Operator name')
        self._verif_input = QLineEdit()
        self._verif_input.setPlaceholderText('Supervisor name')

        form.addRow('Certificate No (auto)', self._cert_input)
        form.addRow('Date (auto-filled)',    self._date_input)
        form.addRow('Customer',              self._cust_input)
        form.addRow('Address',               self._addr_input)
        form.addRow('Test Performed By',     self._by_input)
        form.addRow('Verified By',           self._verif_input)

        for w in (self._cust_input, self._by_input):
            w.textChanged.connect(self._check_valid)

        return box

    def _build_setpoints_card(self) -> QGroupBox:
        box = QGroupBox('Setpoints  (configured in Settings)')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        v = QVBoxLayout(box)

        self._sp_list_label = QLabel('—')
        self._sp_list_label.setWordWrap(True)
        self._sp_list_label.setStyleSheet('font-size:13px;color:#1a2332;font-weight:600;')
        v.addWidget(self._sp_list_label)

        note = QLabel(
            'Setpoints, calibrator range, CMC and Master RTD are configured '
            'once in Settings and reused for every calibration.'
        )
        note.setStyleSheet('font-size:11px;color:#a0aec0;margin-top:6px;')
        note.setWordWrap(True)
        v.addWidget(note)

        self._config_note = QLabel('')
        self._config_note.setStyleSheet('font-size:11px;color:#f59e0b;margin-top:4px;')
        self._config_note.setWordWrap(True)
        v.addWidget(self._config_note)

        v.addStretch()
        return box

    def _build_uut_card(self) -> QGroupBox:
        """UUT (Unit Under Test) instrument details."""
        box, form = _form_card('UUT  —  Unit Under Test', '#f59e0b')

        self._u_type   = QLineEdit(); self._u_type.setPlaceholderText('e.g. Thermocouple')
        self._u_make   = QLineEdit(); self._u_make.setPlaceholderText('Manufacturer name')
        self._u_model  = QLineEdit(); self._u_model.setPlaceholderText('Model number')
        self._u_serial = QLineEdit(); self._u_serial.setPlaceholderText('Serial number')
        self._u_tag    = QLineEdit(); self._u_tag.setPlaceholderText('Plant / lab tag no')

        form.addRow('Instrument Type', self._u_type)
        form.addRow('Make',            self._u_make)
        form.addRow('Model',           self._u_model)
        form.addRow('Serial No',       self._u_serial)
        form.addRow('Tag Number',      self._u_tag)

        self._u_serial.textChanged.connect(self._on_uut_serial_changed)
        self._u_tag.textChanged.connect(self._check_valid)
        return box

    # ------------------------------------------------------------------
    # Certificate No — auto-generated as PREFIX_UUTSERIAL_DDMMYYYY_0001
    # ------------------------------------------------------------------
    def _on_uut_serial_changed(self) -> None:
        self._update_cert_preview()
        self._check_valid()

    def _compute_cert_no(self, settings: dict, u_ser: str) -> str:
        """Recomputed from current settings + the reports folder each time
        it's needed (preview and Start) so it always reflects the latest
        saved report count, not a value cached from when the screen opened.
        Reports always live in the fixed app-folder location (ReportStore's
        default) — not something the operator configures."""
        if not u_ser:
            return ''
        prefix = settings.get('user_profile', {}).get('certificate_prefix', '')
        seq = ReportStore().next_sequence()
        return ReportStore.build_cert_no(prefix, u_ser, date.today(), seq)

    def _update_cert_preview(self) -> None:
        settings = self._store.load()
        u_ser = self._u_serial.text().strip()
        cert_no = self._compute_cert_no(settings, u_ser)
        self._cert_input.setText(cert_no)
        if not cert_no:
            self._cert_input.setPlaceholderText('Fill UUT Serial No to generate')

    # ------------------------------------------------------------------
    # Validation — Start button enabled only when mandatory fields filled
    # ------------------------------------------------------------------
    @staticmethod
    def _missing_requirements(settings: dict) -> list[str]:
        """Config that must exist in Settings before a calibration can
        start — printed on every certificate, so a report can never go
        out without it. Reference equipment identifies which calibrator
        unit produced the report; the lab profile is what brands the
        certificate header (report_gen/pdf_report.py's _header())."""
        missing = []

        mfg = settings.get('manufacturer', {})
        if not (mfg.get('reference_equipment', '').strip()
                and mfg.get('model_no', '').strip()
                and mfg.get('serial_no', '').strip()):
            missing.append('Reference Equipment details (Settings → Manufacturer Settings)')

        profile = settings.get('user_profile', {})
        if not (profile.get('company_name', '').strip()
                and profile.get('company_address', '').strip()
                and profile.get('logo_path')):
            missing.append('Company logo, name and address (Settings → User Settings)')

        return missing

    def _check_valid(self) -> None:
        cert   = self._cert_input.text().strip()
        cust   = self._cust_input.text().strip()
        by     = self._by_input.text().strip()
        u_ser  = self._u_serial.text().strip()
        u_tag  = self._u_tag.text().strip()
        settings = self._store.load()
        sps = settings.get('setpoints', [])
        missing = self._missing_requirements(settings)
        ok = bool(cert and cust and by and u_ser and u_tag and sps and not missing)
        self._start_btn.setEnabled(ok)

    # ------------------------------------------------------------------
    # Build and emit session on Start
    # ------------------------------------------------------------------
    def _on_start(self) -> None:
        settings = self._store.load()
        # Not re-sorted: Settings allows an ascending-then-descending sweep
        # order (at most one peak), so the saved order is the run order.
        setpoints = settings.get('setpoints', [])
        master = settings.get('master_rtd', {})
        u_ser = self._u_serial.text().strip()
        # Recomputed rather than read from the preview label, so the
        # sequence number reflects reports saved after the screen opened.
        cert_no = self._compute_cert_no(settings, u_ser)

        session = CalibrationSession(
            cert_no=cert_no,
            customer=self._cust_input.text().strip(),
            address=self._addr_input.toPlainText().strip(),
            performed_by=self._by_input.text().strip(),
            verified_by=self._verif_input.text().strip(),
            setpoints=setpoints,
            date=date.today(),
            master_info=InstrumentInfo.from_dict(master),
            uut_info=InstrumentInfo(
                instrument_type=self._u_type.text().strip(),
                make=self._u_make.text().strip(),
                model=self._u_model.text().strip(),
                serial_no=u_ser,
                tag_number=self._u_tag.text().strip(),
            ),
        )
        self.start_requested.emit(session)

    def reset(self) -> None:
        for w in (self._cust_input, self._by_input, self._verif_input,
                  self._u_type, self._u_make, self._u_model, self._u_serial, self._u_tag):
            w.clear()
        self._addr_input.clear()
        self._date_input.setText(date.today().isoformat())
        self._refresh_setpoints_display()
        self._update_cert_preview()
        self._check_valid()

    def _refresh_setpoints_display(self) -> None:
        settings = self._store.load()
        sps = settings.get('setpoints', [])
        if sps:
            self._sp_list_label.setText('  ·  '.join(f'{sp:.0f} °C' for sp in sps))
        else:
            self._sp_list_label.setText('No setpoints configured — set them up in Settings.')

        missing = self._missing_requirements(settings)
        self._config_note.setText(
            'Required before starting: ' + '; '.join(missing) + '.' if missing else ''
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_setpoints_display()
        self._update_cert_preview()
        self._check_valid()
