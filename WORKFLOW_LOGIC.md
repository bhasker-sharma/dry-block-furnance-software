# Dry Block Calibrator — Workflow & Logic Reference

This document walks through the software exactly as an operator experiences it,
step by step, and for every step says **which file/function the logic lives in
today**, or **where it needs to be written** if it doesn't exist yet.

Use this as the master checklist: read a section, open the referenced file,
confirm it matches, and note what's left.

---

## 0. One-time Lab Setup — `ui/settings_screen.py`

Before anyone can connect to the dry block, the lab configures settings that
apply to *every* calibration (not re-entered per session).

| Parameter | Where entered | Notes |
|---|---|---|
| Interface / COM Port / Baud / Data bits / Parity / Stop bits / Timeout / Retry | `_build_serial_card()` | Fixed 8N1; only Interface/Port/Baud/Timeout/Retry are actually used today |
| Calibrator Range (min/max °C) | `_build_range_card()` | Every setpoint and CMC point must fall inside this range |
| CMC Status (ON/OFF) + CMC points (temperature, ± value) | `_build_cmc_card()` | Points must be multiples of 100°C. If CMC is ON, at least one point is required before Setpoints can be added — enforced in `_update_setpoints_lock()` |
| Setpoints (up to 10, °C) | `_build_setpoints_card()` | Always sorted ascending on save (`sorted(...)` in `_on_save()`) |
| Master RTD details (type, make, model, serial no, cert no) | `_build_master_card()` | Lab-wide — same reference standard for every job until physically changed |
| Manufacturer Settings (PIN `1234`) — Max Stabilization Time, Volatility Time, Volatility Fluctuation Limit | `_open_manufacturer_settings()` → `_show_manufacturer_dialog()` | The three numbers that actually drive stabilization logic (see §3) |

All of this is persisted as one JSON file: `data/settings.json`, read/written by
`db/settings_store.py` (`SettingsStore.load()` / `.save()`). Defaults live in
`DEFAULTS` at the top of that file.

**Gate:** `SettingsStore.is_ready_for_connection()` (`db/settings_store.py:60`)
requires a calibrator range **and** at least one setpoint before the app will
let you connect. This is checked in `MainWindow._on_connect()`
(`ui/main_window.py:184`).

---

## 1. Connecting to the Dry Block — `ui/live_screen.py` + `ui/main_window.py`

1. Operator opens the app — lands on **Live Monitor** (`ui/live_screen.py`).
2. Picks a COM port, clicks **Connect**.
3. `LiveScreen` emits `connect_requested(port)` → `MainWindow._on_connect()`
   (`ui/main_window.py:182`):
   - Checks `is_ready_for_connection()` — refuses with a warning dialog if
     range/setpoints aren't configured (§0).
   - Calls `self._comm.connect(port)` — `self._comm` is either
     `SimulatorComm` (`comm/simulator.py`) or `USBComm` (`comm/usb_comm.py`),
     chosen once at startup in `MainWindow.__init__` based on `use_simulator`
     (`main.py` passes `--real` to flip this).
   - On success, starts a 1-second `QTimer` (`self._read_timer`) that drives
     everything else.

**Live readout loop** — `MainWindow._on_read_tick()` (`ui/main_window.py:222`),
fires every second while connected:
```
fur, master, uut = self._comm.read_temperatures()
```
Updates the Live Monitor readouts always; if a calibration is running (see
§2) and the Execution screen is active, also feeds the engine (`self._engine.tick(...)`).

---

## 2. Starting a Calibration — `ui/setup_screen.py`

Operator clicks **Start Calibration** → navigates to Setup screen.
Parameters entered **per session** (everything else comes from Settings):

| Field | Widget | Required to enable Start? |
|---|---|---|
| Certificate No | `_cert_input` | ✅ |
| Date | `_date_input` | auto-filled, read-only |
| Customer | `_cust_input` | ✅ |
| Address | `_addr_input` | optional |
| Test Performed By | `_by_input` | ✅ |
| Verified By | `_verif_input` | optional |
| UUT: Instrument Type / Make / Model / Serial No / Tag Number | `_build_uut_card()` | Serial No + Tag Number ✅ |

Validation logic: `_check_valid()` (`ui/setup_screen.py:188`) — Start button
only enables once cert no, customer, performed-by, UUT serial, UUT tag, and at
least one setpoint (from Settings) are all present.

On **Start**, `_on_start()` (`ui/setup_screen.py:201`) builds a
`CalibrationSession` (`models/calibration_session.py`) with the sorted
setpoints pulled from Settings, and emits `start_requested(session)`.

`MainWindow._on_start_calibration()` (`ui/main_window.py:239`) receives it,
reads the three Manufacturer Settings numbers, and constructs the
`CalibrationEngine` — this is where stabilization begins.

---

## 3. Stabilization Logic — `calibration/engine.py`

This is the core of the software. One `CalibrationEngine` instance runs one
calibration session, one setpoint at a time.

### 3.1 States (`Phase` enum, `calibration/engine.py:10`)
```
STABILIZING → SAVING → (next setpoint, back to STABILIZING) → ... → COMPLETED
```
There is **no manual Pass/Fail step and no operator confirmation anywhere** —
capture is fully automatic.

### 3.2 What happens per setpoint
1. **Setpoint sent** — `CalibrationEngine.__init__` (line 68) or
   `_capture()` (line 104) calls `self._comm.send_setpoint(target)`
   immediately, and the phase is `STABILIZING`. The elapsed timer resets to 0
   **at this moment** — i.e. counting starts the instant the setpoint is
   sent, not from when the block physically reaches the target.
2. **Every second**, `MainWindow._on_read_tick()` calls `engine.tick(fur, master, uut)`
   (`calibration/engine.py:73`):
   - `elapsed += 1`, UI countdown updated via `on_tick`.
   - Asks the comm layer: `fluctuation = self._comm.read_volatility(volatility_window_minutes)`.
   - `stabilized = fluctuation is not None and fluctuation <= volatility_limit`
   - `timed_out = elapsed >= max_stabilization_seconds`
   - **If either is true → capture the point now.**
3. **Capture** — `_capture()` (line 90): builds a `CalibrationPoint`
   (`models/calibration_point.py`) from whatever `dry_block/master/uut` values
   were just read, appends it to the session, flashes `SAVING` phase, then:
   - If more setpoints remain: advance index, send next setpoint, reset
     elapsed to 0, back to `STABILIZING`.
   - Otherwise: phase → `COMPLETED`, `on_complete()` fires →
     `MainWindow._on_calibration_complete()` (`ui/main_window.py:284`) saves
     the session via `ReportStore.save()`.

### 3.3 The three tunable numbers (Manufacturer Settings → `db/settings_store.py` → `manufacturer` dict)

| Setting | Meaning | Used in |
|---|---|---|
| `max_stabilization_min` | Hard ceiling — capture no matter what once reached | `engine.py` `timed_out` check |
| `volatility_time_min` | Size of the rolling window to check fluctuation over | passed as `read_volatility(window)` |
| `volatility_limit` | Max allowed fluctuation (°C) within that window to call it "stable" | `engine.py` `stabilized` check |

### 3.4 **If stabilization fails** (never settles within the window/limit)

There is no failure dialog, no retry, no pass/fail judgement. The rule is
purely: **whichever happens first wins.**
- If fluctuation drops to/under `volatility_limit` within the window → capture,
  labeled as a normal stabilized point.
- If `max_stabilization_min` elapses first (the block never settled) →
  capture **anyway**, with whatever readings exist at that moment. The point
  is recorded identically either way — there's no flag in `CalibrationPoint`
  or the report distinguishing "stabilized" vs "timed out." The operator sees
  it happen live (countdown hits zero, phase flashes `SAVING`) but the PDF
  report doesn't call it out.
- Calibration then moves straight to the next setpoint. The whole run can only
  be stopped early by the operator hitting **Stop**
  (`MainWindow._on_stop_calibration`, `ui/main_window.py:290`), which keeps
  whatever points were already captured.

---

## 4. Report Generation — `report_gen/pdf_report.py` + `db/report_store.py`

- On completion, the full session (header + all points) is saved as one JSON
  file per certificate in `reports/` via `ReportStore.save()`
  (`db/report_store.py:41`) — filename = sanitized certificate number.
- **Reports screen** (`ui/reports_screen.py`) lists/searches saved sessions
  (`ReportStore.search()` by cert no / tag no / serial no).
- **Report View** (`ui/report_view.py`) shows one session read-only, with an
  Export PDF button.
- **PDF export** — `MainWindow._on_export_pdf()` → `generate_pdf()`
  (`report_gen/pdf_report.py:27`) builds: header, certificate/date/customer
  meta, Master RTD + UUT instrument cards, the readings table (Setpoint,
  Master RTD, UUT, Error, and CMC column *only if CMC is enabled in
  Settings*), a point-count summary, and signature blocks. Furnace/dry-block
  reading and any Pass/Fail column are intentionally absent.

---

## 5. File Map — where every piece of logic lives

| Concern | File | Status |
|---|---|---|
| Lab settings storage/defaults | `db/settings_store.py` | ✅ done |
| Settings UI (range, CMC, setpoints, Master RTD, Manufacturer PIN dialog) | `ui/settings_screen.py` | ✅ done |
| Per-session form (cert, customer, UUT) | `ui/setup_screen.py` | ✅ done |
| Connection gating | `db/settings_store.py:is_ready_for_connection`, used in `ui/main_window.py:_on_connect` | ✅ done |
| Live temperature polling | `ui/main_window.py:_on_read_tick` | ✅ done |
| Stabilization state machine | `calibration/engine.py` | ✅ implemented, ⚠️ see gaps below |
| CMC interpolation for reports | `calibration/cmc.py` | ✅ done |
| Data models | `models/calibration_point.py`, `models/calibration_session.py` | ✅ done |
| Session persistence (JSON) | `db/report_store.py` | ✅ done |
| PDF certificate | `report_gen/pdf_report.py` | ✅ done |
| Communication contract | `comm/base_comm.py` | ✅ done (interface only) |
| Simulator (dev/testing) | `comm/simulator.py` | ✅ works, ⚠️ one bug (below) |
| **Real hardware (SCPI over USB)** | `comm/usb_comm.py` | ❌ **placeholder only — not implemented** |

---

## 6. Known gaps — what still needs to be written/fixed

1. **`comm/usb_comm.py` — real protocol not implemented.**
   `CMD_SET_TEMP` / `CMD_READ_FUR` / `CMD_READ_MASTER` / `CMD_READ_UUT` /
   `CMD_READ_VOLATILITY` are guessed numbers, `_read_one()` never parses a
   real response (always returns `None`), `send_setpoint()` is a stub that
   returns `True` without sending anything. The real protocol is documented
   in `internal_reference/communication protocall SCPI ET3820 DRY BLOCK
   TEMPERATURE CALIBRATOR.pdf` and needs to be translated into this file.
   Nothing else in the app needs to change once this is done — everything
   upstream only talks to the `BaseComm` interface.

2. **`comm/simulator.py:read_volatility()` — window check is too weak.**
   It only requires **2 samples that fall within the window**, not that the
   *history actually spans the full window*. In practice this means the
   simulator can report "stabilized" after ~30–60 seconds instead of after a
   genuine multi-minute fluctuation window, because two consecutive 1-second
   samples near the end of the heating ramp can already read below the
   fluctuation limit. Fix: also require the oldest sample in history to
   predate `now - window_minutes*60` (i.e. you actually have a full window
   of data) before returning a real number — return `None` until then.
   This only affects the simulator; real hardware will presumably report
   volatility over its own true window once `usb_comm.py` implements
   `CMD_READ_VOLATILITY` for real.

3. **`calibration/engine.py` — max-stabilization clock starts at setpoint-send, not at target-reached.**
   Per the requirement notes (`internal_reference/changes in software.txt`),
   the max stabilization budget is meant to apply *after* the block reaches
   the setpoint, not to the heating ramp-up time itself. Currently `elapsed`
   starts counting the moment `send_setpoint()` is called (`engine.py:67-68`,
   `104-105`), so a large setpoint jump could burn most/all of the budget
   just heating up, and the timeout could fire while the block is still
   mid-ramp rather than merely "unable to settle." If this matters for your
   process, `engine.py` needs a way to know when the block has substantively
   reached target before starting the stabilization clock (or the max time
   needs to be generous enough to always cover worst-case heating + settling).

4. **SRS document is stale.** `internal_reference/dry block callibrated
   software - SRS.md` still describes the old Pass/Fail workflow and target
   tolerance — it no longer matches the implementation and should be
   updated or retired in favor of this document + `changes in software.txt`.

---

## 7. Suggested order of work

1. Fix #2 (simulator window check) — quick, makes testing trustworthy.
2. Decide on #3 (heating vs. stabilization timing) — needs your call on
   whether it's actually a problem for your process, then a small engine change.
3. Implement #1 (`usb_comm.py` against the SCPI PDF) — the big one, unlocks
   testing against real hardware.
4. Update/retire the stale SRS.
