# Dry Block Calibrator

A PyQt5 Windows desktop application for calibrating a dry block temperature
calibrator against a Master RTD reference, capturing readings automatically
once the temperature stabilizes, and generating calibration certificates.

## Features

- Live monitoring of the dry block, Master RTD, and UUT temperatures over the
  instrument's RS-232 serial interface (the 9144 has no USB port).
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
- A standalone simulator process (`simulator.py`) that answers over a real
  serial port (or TCP) using the same Fluke 9144 SCPI protocol as the
  physical dry block, so the full workflow can be exercised without
  hardware — see "Running" below.

## Project layout

```
main.py                 Application entry point
simulator.py             Standalone dry block simulator — a separate process,
                          not imported by the app; see "Running" below
ui/                      PyQt5 screens (Live Monitor, Setup, Execution,
                          Reports, Report View, Settings) and shared widgets
calibration/             CalibrationEngine (stabilization state machine)
                          and the CMC interpolation helper
comm/                     Hardware communication layer — BaseComm interface
                          and USBComm, the only comm class the app uses
                          (talks to real hardware or to simulator.py
                          identically, since both speak the same wire protocol)
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
python main.py
```

The app always connects over a real serial port — there is no built-in
simulator mode or `--real` flag anymore. Pick whichever COM port you want
to connect to in the Live Monitor screen.

**With the physical dry block:** plug it in, connect to its COM port.

**Without hardware (development/testing):** run `simulator.py` as its own
process and point the app at it. Two ways to do that:

**Option A — virtual COM port pair (most hardware-realistic):**
```
1. Install com0com (free virtual null-modem driver) and create a pair,
   e.g. COM8 <-> COM9.
2. Run the simulator against one end:
       python simulator.py --transport serial --port COM9
3. Run the app (python main.py) and connect to the other end (COM8) in
   the Live Monitor screen.
```

**Option B — TCP, no virtual driver needed (use this if com0com is being
uncooperative):**
```
1. Run the simulator with the TCP transport instead:
       python simulator.py --transport tcp --host 127.0.0.1 --tcp-port 5025
2. Run the app (python main.py) and in the Live Monitor screen's COM Port
   field, type   TCP:127.0.0.1:5025   instead of picking a COM port, then
   Connect.
```

Both options run the exact same SCPI command set — `USBComm`
(see comm/usb_comm.py) speaks the real Fluke 9144 Field Metrology Well
protocol (internal_reference/fluke furnance/9144 protocal (1).pdf), which
is what simulator.py answers with, so the app cannot tell them apart.
When the real dry block arrives, stop simulator.py and connect to the
hardware's real COM port instead — no app code changes.

You can also sanity-check the simulator on its own, with no COM port or
app involved: `python simulator.py --selftest` runs a scripted ramp/settle
demo against the SCPI engine directly.

On first run, go to **Settings** and configure the calibrator range, CMC
status (and CMC points, if enabled), setpoints, and Master RTD details —
the app won't allow connecting to the calibrator until these are set.

## Building a Windows executable

```
pyinstaller --onefile --windowed --name "DryBlockCalibrator" main.py
```

## Notes

- The wire protocol between `comm/usb_comm.py` and `simulator.py` is the
  real Fluke 9144 Field Metrology Well SCPI command set (see
  `internal_reference/fluke furnance/9144 protocal (1).pdf`), not a
  placeholder — both files implement it consistently. Everything else in
  the app only talks to the `BaseComm` interface and is unaffected by
  protocol details.
- `data/` and `reports/` are created automatically on first run and are
  git-ignored since they hold machine-local settings and customer
  calibration data, not source code.
