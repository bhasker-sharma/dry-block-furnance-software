# Dry Block Calibrator

A PyQt5 Windows desktop application for calibrating a dry block temperature
calibrator against a Master RTD reference, capturing readings automatically
once the temperature stabilizes, and generating calibration certificates.

## Features

- Live monitoring of the dry block, Master RTD, and UUT temperatures over USB.
- Fully automatic stabilization and capture — no manual Pass/Fail step. A
  reading is captured once its fluctuation over a configurable time window
  settles within a configurable limit, or once a maximum stabilization time
  elapses, whichever comes first.
- Lab-level settings (configured once, reused for every calibration):
  calibrator range, CMC (Calibration & Measurement Capability) points,
  setpoints, and Master RTD details.
- PIN-gated Manufacturer Settings for tuning stabilization timing and
  fluctuation thresholds.
- PDF calibration certificates, with an optional CMC column when CMC is
  enabled, generated via ReportLab.
- A software simulator so the full workflow can be exercised without the
  physical hardware connected.

## Project layout

```
main.py                 Application entry point
ui/                      PyQt5 screens (Live Monitor, Setup, Execution,
                          Reports, Report View, Settings) and shared widgets
calibration/             CalibrationEngine (stabilization state machine)
                          and the CMC interpolation helper
comm/                     Hardware communication layer — BaseComm interface,
                          USBComm (real hardware), SimulatorComm (no hardware)
models/                   CalibrationSession / CalibrationPoint / InstrumentInfo
db/                       JSON-backed persistence — ReportStore (saved
                          certificates) and SettingsStore (lab settings)
report_gen/               PDF certificate generation (ReportLab)
data/                     Generated at runtime — settings.json, local DB
                          (git-ignored, lab-specific)
reports/                  Generated at runtime — saved calibration sessions
                          as JSON, one file per certificate (git-ignored,
                          contains customer data)
```

## Setup

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Running

```
python main.py              # simulator mode — no hardware needed
python main.py --real        # real USB hardware
```

On first run, go to **Settings** and configure the calibrator range, CMC
status (and CMC points, if enabled), setpoints, and Master RTD details —
the app won't allow connecting to the calibrator until these are set.

## Building a Windows executable

```
pyinstaller --onefile --windowed --name "DryBlockCalibrator" main.py
```

## Notes

- USB protocol command codes in `comm/usb_comm.py` are placeholders pending
  confirmation of the hardware's communication protocol — see the `TODO`
  comments in that file.
- `data/` and `reports/` are created automatically on first run and are
  git-ignored since they hold machine-local settings and customer
  calibration data, not source code.
