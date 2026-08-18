from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QGroupBox, QFormLayout, QScrollArea, QFrame,
    QMessageBox, QPushButton, QDoubleSpinBox, QDialog,
    QDialogButtonBox, QInputDialog, QSizePolicy, QFileDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer

from ui.widgets import make_button
from db.settings_store import (
    SettingsStore, STABILITY_LIMIT_MIN, STABILITY_LIMIT_MAX, clamp_stability_limit,
)

MANUFACTURER_PIN = '1234'


class SettingsScreen(QWidget):
    save_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = SettingsStore()
        self._comm = None   # set via set_comm() once MainWindow creates the comm object
        self._cmc_rows: list[tuple] = []
        self._sp_widgets: list[QDoubleSpinBox] = []
        self._sp_rows: list[tuple] = []
        self._build_ui()
        self._load_into_ui()

    def set_comm(self, comm) -> None:
        self._comm = comm

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
        vt = QVBoxLayout()
        title = QLabel('Communication & Settings')
        title.setObjectName('screen_title')
        sub = QLabel('Serial port, calibrator range, CMC, setpoints and Master RTD')
        sub.setObjectName('screen_sub')
        vt.addWidget(title)
        vt.addWidget(sub)
        tb.addLayout(vt)
        tb.addStretch()
        save_btn = make_button('✓  Save', 'primary')
        save_btn.clicked.connect(self._on_save)
        tb.addWidget(save_btn)
        root.addWidget(topbar)

        # ── scrollable content ────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(20, 16, 20, 16)
        cv.setSpacing(16)
        cv.setAlignment(Qt.AlignTop)

        cv.addWidget(self._build_serial_card())

        row2 = QHBoxLayout()
        row2.setSpacing(16)
        row2.addWidget(self._build_range_card(), 1)
        row2.addWidget(self._build_cmc_card(), 1)
        cv.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(16)
        row3.addWidget(self._build_setpoints_card(), 1)
        row3.addWidget(self._build_master_card(), 1)
        cv.addLayout(row3)

        cv.addWidget(self._build_reports_card())
        cv.addWidget(self._build_manufacturer_card())

        scroll.setWidget(content)
        root.addWidget(scroll)

    # ------------------------------------------------------------------
    def _build_serial_card(self) -> QGroupBox:
        box = QGroupBox('Serial Port Configuration')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        form = QFormLayout(box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)

        self._iface  = QComboBox()
        self._iface.addItems(['RS-232'])
        self._iface.setEnabled(False)
        self._iface.setToolTip(
            'The 9144 has a single RS-232 (DB-9) interface — no USB. If your PC '
            'connects via a USB-to-serial adapter cable, Windows still presents '
            'it as a COM port below, so nothing else changes.'
        )

        self._port   = QComboBox()
        self._port.setEditable(True)
        self._port.addItems(['COM1','COM2','COM3','COM4','COM5','COM6','COM7','COM8'])
        self._port.setCurrentText('COM3')
        self._port.lineEdit().setPlaceholderText('COM3 or TCP:127.0.0.1:5025')

        self._baud   = QComboBox()
        self._baud.addItems(['1200','2400','4800','9600','19200','38400'])
        self._baud.setCurrentText('9600')
        self._baud.setToolTip(
            'Must match the baud rate set on the instrument itself '
            '(MENU|SYSTEM MENU|SYSTEM SETUP|COMM SETUP). Range fixed by the 9144.'
        )

        self._timeout = QLineEdit('1000')
        self._timeout.setPlaceholderText('milliseconds')

        self._retry   = QLineEdit('3')
        self._retry.setPlaceholderText('number of retries')

        form.addRow('Interface',     self._iface)
        form.addRow('COM Port',      self._port)
        form.addRow('Baud Rate',     self._baud)
        form.addRow('Timeout (ms)',  self._timeout)
        form.addRow('Retry Count',   self._retry)

        fixed = QLabel(
            '8 data bits · no parity · 1 stop bit — fixed by the 9144, not '
            'user-configurable. Baud rate above is the only thing that must match '
            'the instrument\'s COMM SETUP menu.'
        )
        fixed.setStyleSheet('font-size:11px;color:#a0aec0;padding:4px 0;')
        fixed.setWordWrap(True)
        form.addRow('', fixed)

        return box

    def _build_range_card(self) -> QGroupBox:
        box = QGroupBox('Dry Block Calibrator Range')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        form = QFormLayout(box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)

        self._range_min = QDoubleSpinBox()
        self._range_min.setRange(-200, 1200)
        self._range_min.setSuffix(' °C')
        self._range_max = QDoubleSpinBox()
        self._range_max.setRange(-200, 1200)
        self._range_max.setSuffix(' °C')
        self._range_max.setValue(300)

        form.addRow('Minimum', self._range_min)
        form.addRow('Maximum', self._range_max)

        note = QLabel('Setpoints and CMC points must stay within this range.')
        note.setStyleSheet('font-size:11px;color:#a0aec0;padding-top:4px;')
        note.setWordWrap(True)
        form.addRow('', note)

        return box

    def _build_cmc_card(self) -> QGroupBox:
        box = QGroupBox('CMC — Calibration & Measurement Capability')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        v = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel('CMC Status'))
        self._cmc_status = QComboBox()
        self._cmc_status.addItems(['OFF', 'ON'])
        self._cmc_status.currentTextChanged.connect(self._on_cmc_toggle)
        row.addWidget(self._cmc_status)
        row.addStretch()
        v.addLayout(row)

        self._cmc_count_label = QLabel('0 CMC points')
        self._cmc_count_label.setStyleSheet('font-size:11px;color:#6b7a90;')
        v.addWidget(self._cmc_count_label)

        self._cmc_container = QVBoxLayout()
        self._cmc_container.setSpacing(5)
        v.addLayout(self._cmc_container)

        self._cmc_add_btn = make_button('+ Add CMC point', 'ghost')
        self._cmc_add_btn.clicked.connect(lambda: self._add_cmc_row(0.0, 0.0))
        v.addWidget(self._cmc_add_btn)

        note = QLabel(
            'CMC points are entered at temperatures that are multiples of 100. '
            'When CMC is ON, at least one CMC point is required before setpoints can be added.'
        )
        note.setStyleSheet('font-size:11px;color:#a0aec0;margin-top:6px;')
        note.setWordWrap(True)
        v.addWidget(note)

        return box

    def _build_setpoints_card(self) -> QGroupBox:
        box = QGroupBox('Setpoints  (ascending °C)')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        v = QVBoxLayout(box)

        self._sp_count_label = QLabel('0 / 10')
        self._sp_count_label.setStyleSheet('font-size:11px;color:#6b7a90;')
        v.addWidget(self._sp_count_label)

        order_note = QLabel('Setpoint Order: Ascending always — setpoints are always sent in ascending temperature order.')
        order_note.setStyleSheet(
            'color:#6b7a90;font-size:11px;background:#f7f9fc;'
            'border-radius:5px;padding:4px 8px;'
        )
        order_note.setWordWrap(True)
        v.addWidget(order_note)

        self._sp_container = QVBoxLayout()
        self._sp_container.setSpacing(5)
        v.addLayout(self._sp_container)

        self._sp_add_btn = make_button('+ Add setpoint', 'ghost')
        self._sp_add_btn.clicked.connect(lambda: self._add_sp_row(0.0))
        v.addWidget(self._sp_add_btn)

        self._sp_lock_note = QLabel('Add CMC points first — CMC is ON.')
        self._sp_lock_note.setStyleSheet('font-size:11px;color:#f59e0b;margin-top:6px;')
        self._sp_lock_note.setWordWrap(True)
        self._sp_lock_note.setVisible(False)
        v.addWidget(self._sp_lock_note)

        v.addStretch()
        return box

    def _build_master_card(self) -> QGroupBox:
        """Master RTD (Standard Reference Sensor) — lab-wide, set once here."""
        box = QGroupBox('Master RTD  —  Standard Reference Sensor')
        box.setObjectName('card')
        box.setStyleSheet(
            'QGroupBox{border:1px solid #3d7fff;}'
            'QGroupBox::title{background:#ffffff;}'
        )
        form = QFormLayout(box)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(12)

        self._m_type   = QLineEdit(); self._m_type.setPlaceholderText('e.g. Platinum RTD')
        self._m_make   = QLineEdit(); self._m_make.setPlaceholderText('Manufacturer name')
        self._m_model  = QLineEdit(); self._m_model.setPlaceholderText('Model number')
        self._m_serial = QLineEdit(); self._m_serial.setPlaceholderText('Serial number')
        self._m_cert   = QLineEdit(); self._m_cert.setPlaceholderText('Calibration cert no')

        form.addRow('Instrument Type', self._m_type)
        form.addRow('Make',            self._m_make)
        form.addRow('Model',           self._m_model)
        form.addRow('Serial No',       self._m_serial)
        form.addRow('Certificate No',  self._m_cert)

        return box

    def _build_reports_card(self) -> QGroupBox:
        box = QGroupBox('Reports Storage Location')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        v = QVBoxLayout(box)

        row = QHBoxLayout()
        self._reports_dir_field = QLineEdit()
        self._reports_dir_field.setReadOnly(True)
        self._reports_dir_field.setPlaceholderText(
            'Not configured — choose a folder before starting a calibration'
        )
        row.addWidget(self._reports_dir_field, 1)
        browse_btn = make_button('Browse…', 'ghost')
        browse_btn.clicked.connect(self._on_browse_reports_dir)
        row.addWidget(browse_btn)
        v.addLayout(row)

        note = QLabel(
            'Saved calibration certificates (JSON, plus PDFs you export) are written '
            'here — pick any folder on this PC, e.g. a backed-up or shared drive. '
            'Required before a calibration can be started.'
        )
        note.setStyleSheet('font-size:11px;color:#a0aec0;margin-top:6px;')
        note.setWordWrap(True)
        v.addWidget(note)

        return box

    def _on_browse_reports_dir(self) -> None:
        start_dir = self._reports_dir_field.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, 'Choose Reports Storage Folder', start_dir
        )
        if chosen:
            self._reports_dir_field.setText(chosen)

    def _build_manufacturer_card(self) -> QGroupBox:
        box = QGroupBox('Manufacturer Settings')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        h = QHBoxLayout(box)
        lbl = QLabel('PIN-protected: live instrument stability status.')
        lbl.setStyleSheet('font-size:11px;color:#6b7a90;')
        lbl.setWordWrap(True)
        h.addWidget(lbl, 1)
        btn = make_button('Manufacturer Settings', 'ghost')
        btn.clicked.connect(self._open_manufacturer_settings)
        h.addWidget(btn)
        return box

    # ------------------------------------------------------------------
    # CMC point rows
    # ------------------------------------------------------------------
    def _add_cmc_row(self, temperature: float, cmc: float) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)

        temp_spin = QDoubleSpinBox()
        temp_spin.setRange(self._range_min.value(), self._range_max.value())
        temp_spin.setDecimals(0)
        temp_spin.setSingleStep(100)
        temp_spin.setSuffix(' °C')
        temp_spin.setValue(temperature)

        cmc_spin = QDoubleSpinBox()
        cmc_spin.setRange(0, 100)
        cmc_spin.setDecimals(3)
        cmc_spin.setSuffix(' ±')
        cmc_spin.setValue(cmc)

        del_btn = QPushButton('✕')
        del_btn.setFixedWidth(28)
        del_btn.setStyleSheet(
            'QPushButton{border:none;color:#ef4444;background:transparent;font-size:13px;}'
            'QPushButton:hover{background:#fef2f2;border-radius:4px;}'
        )

        entry = (temp_spin, cmc_spin, row)
        self._cmc_rows.append(entry)
        del_btn.clicked.connect(lambda: self._remove_cmc_row(entry))

        row.addWidget(QLabel('Temp'))
        row.addWidget(temp_spin)
        row.addWidget(QLabel('CMC'))
        row.addWidget(cmc_spin)
        row.addWidget(del_btn)
        self._cmc_container.addLayout(row)
        self._update_cmc_count()

    def _remove_cmc_row(self, entry: tuple) -> None:
        if entry in self._cmc_rows:
            self._cmc_rows.remove(entry)
            _, _, row = entry
            while row.count():
                item = row.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            self._cmc_container.removeItem(row)
            self._update_cmc_count()

    def _update_cmc_count(self) -> None:
        self._cmc_count_label.setText(f'{len(self._cmc_rows)} CMC points')
        self._update_setpoints_lock()

    def _on_cmc_toggle(self, status: str) -> None:
        self._cmc_add_btn.setEnabled(status == 'ON')
        self._update_setpoints_lock()

    def _update_setpoints_lock(self) -> None:
        cmc_on = self._cmc_status.currentText() == 'ON'
        locked = cmc_on and len(self._cmc_rows) == 0
        self._sp_add_btn.setEnabled(not locked)
        self._sp_lock_note.setVisible(locked)

    # ------------------------------------------------------------------
    # Setpoint rows (same pattern previously on the Setup screen)
    # ------------------------------------------------------------------
    def _add_sp_row(self, value: float) -> None:
        if len(self._sp_widgets) >= 10:
            return
        row = QHBoxLayout()
        row.setSpacing(6)

        idx_lbl = QLabel(str(len(self._sp_widgets) + 1))
        idx_lbl.setFixedWidth(20)
        idx_lbl.setStyleSheet('color:#6b7a90;font-size:12px;')

        spin = QDoubleSpinBox()
        spin.setRange(self._range_min.value(), self._range_max.value())
        spin.setDecimals(1)
        spin.setValue(value)
        spin.setSuffix(' °C')
        spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        del_btn = QPushButton('✕')
        del_btn.setFixedWidth(28)
        del_btn.setStyleSheet(
            'QPushButton{border:none;color:#ef4444;background:transparent;font-size:13px;}'
            'QPushButton:hover{background:#fef2f2;border-radius:4px;}'
        )

        entry = (spin, idx_lbl, del_btn, row)
        self._sp_widgets.append(spin)
        self._sp_rows.append(entry)
        del_btn.clicked.connect(lambda: self._remove_sp(entry))

        row.addWidget(idx_lbl)
        row.addWidget(spin)
        row.addWidget(del_btn)
        self._sp_container.addLayout(row)
        self._update_sp_count()

    def _remove_sp(self, entry: tuple) -> None:
        if entry not in self._sp_rows:
            return
        spin, idx_lbl, del_btn, row = entry
        self._sp_rows.remove(entry)
        self._sp_widgets.remove(spin)

        for w in (idx_lbl, spin, del_btn):
            w.setParent(None)
        self._sp_container.removeItem(row)

        self._renumber_sp_rows()
        self._update_sp_count()

    def _renumber_sp_rows(self) -> None:
        for i, (_, idx_lbl, _, _) in enumerate(self._sp_rows):
            idx_lbl.setText(str(i + 1))

    def _update_sp_count(self) -> None:
        self._sp_count_label.setText(f'{len(self._sp_widgets)} / 10')

    # ------------------------------------------------------------------
    # Manufacturer settings (PIN-gated)
    # ------------------------------------------------------------------
    def _open_manufacturer_settings(self) -> None:
        pin, ok = QInputDialog.getText(
            self, 'Manufacturer Settings', 'Enter 4-digit PIN:',
            QLineEdit.Password
        )
        if not ok:
            return
        if pin != MANUFACTURER_PIN:
            QMessageBox.warning(self, 'Incorrect PIN', 'The PIN you entered is incorrect.')
            return
        self._show_manufacturer_dialog()

    def _show_manufacturer_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle('Manufacturer Settings')
        dlg.setMinimumWidth(380)
        form = QFormLayout(dlg)

        mfg = self._store.load().get('manufacturer', {})
        current_limit = clamp_stability_limit(float(mfg.get('stability_limit_c', 0.05)))

        limit_spin = QDoubleSpinBox()
        limit_spin.setRange(STABILITY_LIMIT_MIN, STABILITY_LIMIT_MAX)
        limit_spin.setDecimals(2)
        limit_spin.setSingleStep(0.01)
        limit_spin.setSuffix(' °C')
        limit_spin.setValue(current_limit)
        form.addRow('Stability Tolerance', limit_spin)

        note = QLabel(
            'Sent to the instrument as SOUR:STAB:LIM — the band SOUR:STAB:TEST? '
            'must stay within to report stable. Per the 9144 datasheet its own '
            'stability spec is ~0.03°C at 50°C to ~0.05°C at 660°C — a tolerance '
            'tighter than that may never be satisfied.'
        )
        note.setWordWrap(True)
        note.setStyleSheet('font-size:11px;color:#a0aec0;')
        form.addRow(note)

        on_instrument = QLabel('—')
        on_instrument.setStyleSheet('color:#6b7a90;')
        form.addRow('Currently on instrument (SOUR:STAB:LIM?)', on_instrument)

        stable_now = QLabel('—')
        stable_now.setStyleSheet('color:#6b7a90;')
        form.addRow('Stable (SOUR:STAB:TEST?)', stable_now)

        status = QLabel('')
        status.setWordWrap(True)
        form.addRow(status)

        timer = QTimer(dlg)
        def _refresh():
            if self._comm is not None and getattr(self._comm, 'is_connected', False):
                readback = self._comm.get_stability_limit()
                on_instrument.setText(f'{readback:.2f} °C' if readback is not None else 'unknown')
                stable_now.setText('Yes' if self._comm.read_stable() else 'No')
            else:
                on_instrument.setText('not connected')
                stable_now.setText('not connected')
        timer.timeout.connect(_refresh)
        timer.start(1000)
        _refresh()

        def _on_save():
            value = limit_spin.value()
            settings = self._store.load()
            settings['manufacturer'] = {'stability_limit_c': value}
            self._store.save(settings)
            if self._comm is not None and getattr(self._comm, 'is_connected', False):
                ok = self._comm.set_stability_limit(value)
                status.setText(
                    f'Saved and pushed to instrument ({value:.2f} °C).' if ok else
                    'Saved, but the instrument did not acknowledge the new value.'
                )
                status.setStyleSheet(f'font-size:11px;color:{"#22c55e" if ok else "#ef4444"};')
            else:
                status.setText('Saved. Will be pushed to the instrument on next connect.')
                status.setStyleSheet('font-size:11px;color:#6b7a90;')

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Save).clicked.connect(_on_save)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        dlg.exec_()
        timer.stop()

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------
    def _load_into_ui(self) -> None:
        s = self._store.load()

        serial = s.get('serial', {})
        self._iface.setCurrentText(serial.get('iface', 'RS-232'))
        self._port.setCurrentText(serial.get('port', 'COM3'))
        self._baud.setCurrentText(str(serial.get('baud', 9600)))
        self._timeout.setText(str(serial.get('timeout_ms', 1000)))
        self._retry.setText(str(serial.get('retry', 3)))

        rng = s.get('calibrator_range', {})
        if rng.get('min') is not None:
            self._range_min.setValue(rng['min'])
        if rng.get('max') is not None:
            self._range_max.setValue(rng['max'])

        self._cmc_status.setCurrentText('ON' if s.get('cmc_enabled') else 'OFF')
        for pt in s.get('cmc_points', []):
            self._add_cmc_row(pt.get('temperature', 0.0), pt.get('cmc', 0.0))

        for sp in s.get('setpoints', []):
            self._add_sp_row(sp)

        master = s.get('master_rtd', {})
        self._m_type.setText(master.get('instrument_type', ''))
        self._m_make.setText(master.get('make', ''))
        self._m_model.setText(master.get('model', ''))
        self._m_serial.setText(master.get('serial_no', ''))
        self._m_cert.setText(master.get('cert_number', ''))

        self._reports_dir_field.setText(s.get('reports_dir') or '')

        self._cmc_add_btn.setEnabled(self._cmc_status.currentText() == 'ON')
        self._update_setpoints_lock()

    def _on_save(self) -> None:
        if self._range_min.value() >= self._range_max.value():
            QMessageBox.warning(self, 'Invalid Range', 'Calibrator minimum must be less than maximum.')
            return

        cmc_enabled = self._cmc_status.currentText() == 'ON'
        cmc_points = []
        for temp_spin, cmc_spin, _ in self._cmc_rows:
            if temp_spin.value() % 100 != 0:
                QMessageBox.warning(self, 'Invalid CMC Point',
                                     'CMC point temperatures must be multiples of 100.')
                return
            cmc_points.append({'temperature': temp_spin.value(), 'cmc': cmc_spin.value()})

        if cmc_enabled and not cmc_points:
            QMessageBox.warning(self, 'CMC Points Required',
                                 'CMC is ON — enter at least one CMC point before saving.')
            return

        setpoints = sorted(s.value() for s in self._sp_widgets if s.value() > 0)
        rmin, rmax = self._range_min.value(), self._range_max.value()
        if any(sp < rmin or sp > rmax for sp in setpoints):
            QMessageBox.warning(self, 'Setpoint Out of Range',
                                 'All setpoints must stay within the calibrator range.')
            return

        existing = self._store.load()
        settings = {
            **existing,
            'serial': {
                'iface': self._iface.currentText(),
                'port': self._port.currentText(),
                'baud': int(self._baud.currentText()),
                'timeout_ms': int(self._timeout.text() or '1000'),
                'retry': int(self._retry.text() or '3'),
            },
            'calibrator_range': {'min': rmin, 'max': rmax},
            'cmc_enabled': cmc_enabled,
            'cmc_points': cmc_points,
            'setpoints': setpoints,
            'reports_dir': self._reports_dir_field.text().strip() or None,
            'master_rtd': {
                'instrument_type': self._m_type.text().strip(),
                'make':            self._m_make.text().strip(),
                'model':           self._m_model.text().strip(),
                'serial_no':       self._m_serial.text().strip(),
                'cert_number':     self._m_cert.text().strip(),
                'tag_number':      '',
            },
        }
        self._store.save(settings)
        self.save_requested.emit(settings)
        QMessageBox.information(self, 'Saved', 'Settings saved successfully.')

    def get_port(self) -> str:
        return self._port.currentText()
