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
| Interface (fixed RS-232 — the 9144 has no USB) / COM Port / Baud / Timeout / Retry | `_build_serial_card()` | Data bits/parity/stop bits removed from this screen — the 9144 fixes them at 8N1, not user-configurable. Baud/Timeout/Retry are read from settings and passed to `USBComm.connect()` in `MainWindow._on_connect()`; baud must match the instrument's own COMM SETUP menu. **The "COM Port" field here is saved but not actually used to connect** — see §1, the Live Monitor screen has its own independent port picker, which is what's actually used every session |
| Calibrator Range (min/max °C) | `_build_range_card()` | Every setpoint and CMC point must fall inside this range |
| CMC Status (ON/OFF) + CMC points (temperature, ± value) | `_build_cmc_card()` | Points must be multiples of 100°C. If CMC is ON, at least one point is required before Setpoints can be added — enforced in `_update_setpoints_lock()` |
| Setpoints (up to 10, °C) | `_build_setpoints_card()` | Always sorted ascending on save (`sorted(...)` in `_on_save()`) |
| Master RTD details (type, make, model, serial no, cert no) | `_build_master_card()` | Lab-wide — same reference standard for every job until physically changed |
| Manufacturer Settings (PIN `1234`) — Stability Tolerance (°C) | `_open_manufacturer_settings()` → `_show_manufacturer_dialog()` | Single number, stored as `manufacturer.stability_limit_c`. Pushed to the instrument as `SOUR:STAB:LIM` on every connect — see §3.3. Not a software-computed threshold; the 9144 judges stability onboard |

All of this is persisted as one JSON file: `data/settings.json`, read/written by
`db/settings_store.py` (`SettingsStore.load()` / `.save()`). Defaults live in
`DEFAULTS` at the top of that file.

**Gate:** `SettingsStore.is_ready_for_connection()` (`db/settings_store.py:60`)
requires a calibrator range **and** at least one setpoint before the app will
let you connect. This is checked in `MainWindow._on_connect()`
(`ui/main_window.py:190`).

---

## 1. Connecting to the Dry Block — `ui/live_screen.py` + `ui/main_window.py` + `ui/connect_worker.py`

1. Operator opens the app — lands on **Live Monitor** (`ui/live_screen.py`).
   The port dropdown is built once in `MainWindow._build_ui()`
   (`ui/main_window.py:83-87`) as `list_com_ports()` (real ports Windows
   currently sees) **plus a hardcoded `TCP:127.0.0.1:5025` entry** — so
   `simulator.py --transport tcp` is always selectable with no com0com
   setup. The box is editable, so any `COMx` or `TCP:host:port` string can
   be typed in directly too.
2. Picks a port, clicks **Connect**.
3. `LiveScreen` emits `connect_requested(port)` → `MainWindow._on_connect()`
   (`ui/main_window.py:189`):
   - Checks `is_ready_for_connection()` — refuses with a warning dialog if
     range/setpoints aren't configured (§0).
   - **Runs the connect attempt on a background thread, not inline.**
     `self._comm.connect(...)` can block for up to `retries * timeout_s`
     seconds (each retry opens the port and waits for a response), so
     `_on_connect` hands it to a `ConnectWorker` QThread
     (`ui/connect_worker.py`) instead of calling it directly — otherwise
     the whole GUI would freeze (and Windows would flag it "Not
     Responding") for that whole span. The baud/timeout/retry values come
     from `SettingsStore`; `self._comm` is always `USBComm`
     (`comm/usb_comm.py`), created once in `MainWindow.__init__`.
   - While connecting, `LiveScreen.set_connecting()` disables the port
     box and turns the **Connect** button into **Cancel**
     (`ui/live_screen.py:181-194`). Clicking it emits
     `cancel_connect_requested` → `MainWindow._on_cancel_connect()`
     (`ui/main_window.py:219`), which sets a flag the worker checks
     between retries (`should_abort`) — the in-flight attempt itself
     isn't interrupted mid-syscall, it just won't retry again.
   - The worker emits `finished_ok(bool)` → `MainWindow._on_connect_finished()`
     (`ui/main_window.py:225`). On success, starts the 1-second `QTimer`
     (`self._read_timer`) that drives everything else and updates the
     sidebar connection chip; on failure, shows a warning dialog (unless
     it was a cancel, which just logs).
   - There is no in-process simulator anymore; to test without physical
     hardware, run `simulator.py` (repo root) as its own process against a
     virtual COM port pair (e.g. com0com) or over TCP — see the docstring
     at the top of `simulator.py`.
   - **`USBComm.connect()` flushes the input buffer right after opening the
     port**, before sending `*IDN?`. Without this, a virtual null-modem
     pair (com0com) can still be holding a response from a previous
     aborted attempt — reading that as the answer to a fresh query
     desyncs every subsequent request/response pair by one, which surfaces
     as `*IDN?`/`SYST:CONF:MOD?` returning nonsense values that alternate
     on every retry. If this ever recurs against the simulator, restart
     `simulator.py` too — it holds its COM port open for its whole process
     lifetime, so a long enough backlog of unanswered commands from
     repeated failed attempts persists there, not just in the app.

**Live readout loop** — `MainWindow._on_read_tick()` (`ui/main_window.py:264`),
fires every second while connected:
```
fur, master, uut = self._comm.read_temperatures()
```
Updates the Live Monitor readouts always; if a calibration is running (see
§2) and the Execution screen is active, also feeds the engine (`self._engine.tick(...)`).

**Copy Logs** — the Status & Messages panel on Live Monitor
(`ui/live_screen.py`) has a *Copy Logs* button that copies the visible log
(`ConsoleWidget.to_plain_text()`, `ui/widgets.py`) to the clipboard as
plain text, for pasting into a bug report.

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

`MainWindow._on_start_calibration()` (`ui/main_window.py:280`) receives it
and constructs the `CalibrationEngine` — this is where stabilization begins.
(The Manufacturer Settings stability tolerance is not read here — it's
pushed to the instrument once, at connect time; see §3.3.)

---

## 3. Stabilization Logic — `calibration/engine.py` + `comm/usb_comm.py`

This is the core of the software. One `CalibrationEngine` instance runs one
calibration session, one setpoint at a time. **Stabilization is judged by the
instrument itself, not computed in software** — see §3.3 for why.

### 3.1 States (`Phase` enum, `calibration/engine.py:10`)
```
STABILIZING → SAVING → (next setpoint, back to STABILIZING) → ... → COMPLETED
```
There is **no manual Pass/Fail step and no operator confirmation anywhere** —
capture is fully automatic.

### 3.2 What happens per setpoint
1. **Setpoint sent** — `CalibrationEngine.__init__` or `_capture()` calls
   `self._comm.send_setpoint(target)` (`SOUR:SPO <value>`), and the phase
   becomes `STABILIZING`.
2. **Every second**, `MainWindow._on_read_tick()` calls `engine.tick(fur, master, uut)`
   (`calibration/engine.py:62`):
   - Asks the comm layer: `self._comm.read_stable()`, which queries
     `SOUR:STAB:TEST?` on the instrument.
   - The Fluke 9144 tracks its own fluctuation over its own internal window
     and answers `1` (stable) or `0` (not yet) — the app does no
     stabilization math of its own, and there is no elapsed-time countdown.
   - **If the instrument reports stable → capture the point now.**
3. **Capture** — `_capture()`: builds a `CalibrationPoint`
   (`models/calibration_point.py`) from whatever `dry_block/master/uut` values
   were just read, appends it to the session, flashes `SAVING` phase, then:
   - If more setpoints remain: advance index, send next setpoint, back to
     `STABILIZING`.
   - Otherwise: phase → `COMPLETED`, `on_complete()` fires →
     `MainWindow._on_calibration_complete()` (`ui/main_window.py`) saves
     the session via `ReportStore.save()`.

### 3.3 Where the tolerance comes from — `SOUR:STAB:LIM`

Cross-checked against `internal_reference/fluke furnance/9144 protocal (1).pdf`
§6.4: the 9144 has no wire command for the stability *window* duration — only
the *limit* (tolerance/wobble allowance), `SOUR:STAB:LIM`, is exposed, and it
**is** read/write (range `0.01`–`9.99 °C`, protocol default `0.05 °C`). That's
a real onboard feature, not a placeholder, so software correctly delegates the
window-tracking math to the instrument and only configures the tolerance:

- Entered once, lab-wide, in **Settings → Manufacturer Settings** (PIN `1234`)
  → *Stability Tolerance*. Stored as `manufacturer.stability_limit_c` in
  `data/settings.json` (`db/settings_store.py`).
- Pushed to the instrument via `USBComm.set_stability_limit()`
  (`SOUR:STAB:LIM <value>`, then read back to confirm) on **every successful
  connect** — `MainWindow._on_connect_finished()` (`ui/main_window.py`) — so
  the app's Settings value wins over whatever was last set on the
  instrument's own front-panel menu.
- Clamped to `[0.01, 9.99]` (`db/settings_store.clamp_stability_limit`)
  before being sent, since `settings.json` is a plain file an operator (or an
  older version of this app) could have put an out-of-range or stale value
  into — that boundary can't assume the file is already valid.
- The Manufacturer Settings dialog also live-polls `SOUR:STAB:LIM?` and
  `SOUR:STAB:TEST?` once a second while open, so a technician can see the
  tolerance actually active on the instrument and whether it's currently
  reporting stable.
- Per the 9144 datasheet, the instrument's own achievable stability is
  ~`0.03°C` at 50°C to ~`0.05°C` at 660°C — a configured tolerance tighter
  than that may never be satisfied (`SOUR:STAB:TEST?` would just stay `0`
  forever). The dialog shows this as a note; it isn't enforced in code, since
  the safe floor depends on where in the calibrator's range the lab
  operates.

Two different Fluke commands, not to be confused: `SOUR:SPO` is the *target
temperature* (written every setpoint); `SOUR:STAB:LIM` is the *stability
tolerance* used internally by the instrument's own stable/unstable judgement
(written once per connection). Setpoints have always worked correctly —
tolerance is what was missing until this update.

### 3.4 No maximum-stabilization timeout — deliberate, not a gap

Earlier notes for this project (`internal_reference/changes in software.txt`)
described a software-side "capture anyway once max time elapses" fallback on
top of the volatility check. That has been **deliberately removed, not
forgotten**:

- The 9144 protocol has no command for a stabilization timeout at all — a
  timeout was only ever something software could add on top, never something
  the hardware itself does.
- Decision: if a setpoint never reports stable, that means the instrument
  itself couldn't settle — a hardware/maintenance condition, not something
  the software should paper over by capturing a reading anyway. So `tick()`
  just keeps polling `SOUR:STAB:TEST?` indefinitely; there is no elapsed
  counter and no automatic capture-on-timeout.
- The only way to end a run that's stuck is the operator hitting **Stop**
  (`MainWindow._on_stop_calibration`, `ui/main_window.py`), which keeps
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
| Background/cancellable connect | `ui/connect_worker.py` (`ConnectWorker` QThread) | ✅ done |
| Live temperature polling | `ui/main_window.py:_on_read_tick` | ✅ done |
| Stabilization state machine | `calibration/engine.py` | ✅ done — delegates to instrument `SOUR:STAB:TEST?`, no software timeout (see §3.4) |
| CMC interpolation for reports | `calibration/cmc.py` | ✅ done |
| Data models | `models/calibration_point.py`, `models/calibration_session.py` | ✅ done |
| Session persistence (JSON) | `db/report_store.py` | ✅ done |
| PDF certificate | `report_gen/pdf_report.py` | ✅ done |
| Communication contract | `comm/base_comm.py` | ✅ done (interface only) |
| Serial comm — real hardware or simulator, same code path | `comm/usb_comm.py` | ✅ done — real Fluke 9144 SCPI protocol |
| Stability tolerance read/write (`SOUR:STAB:LIM`) | `comm/usb_comm.py` (`set_stability_limit`/`get_stability_limit`), pushed on connect in `ui/main_window.py`, entered in `ui/settings_screen.py` Manufacturer Settings | ✅ done |
| Standalone simulator process (dev/testing, separate from the app) | `simulator.py` (repo root) | ✅ done — talks to the app over a virtual COM port pair (e.g. com0com) or over TCP (no virtual driver needed) |

---

## 6. Known gaps — what still needs to be written/fixed

1. ~~`comm/usb_comm.py` — placeholder wire protocol, not the real SCPI
   protocol.~~ **Fixed.** `usb_comm.py` now speaks the real Fluke 9144
   Field Metrology Well SCPI command set (`SOUR:SENS:DATA?`, `CALC1:DATA?`,
   `CALC2:DATA?`, `SOUR:SPO`, `SOUR:STAB:TEST?`, `SOUR:STAB:LIM`, ASCII over
   CR-terminated lines), per
   `internal_reference/fluke furnance/9144 protocal (1).pdf` — the same set
   `simulator.py`'s `ScpiEngine` answers. One protocol limitation is
   permanent, not a bug: the 9144 has no wire command to set the stability
   *window* duration, only the *limit* (`SOUR:STAB:LIM`, which the app now
   reads/writes — see §3.3) — the instrument's internal window is fixed and
   not software-configurable.

2. **Simulator is now a separate process, not in-process.**
   `comm/simulator.py` (the old in-process `SimulatorComm`) has been
   removed. `main.py` always uses `USBComm` — there's no `--real` flag or
   `use_simulator` switch anymore. To develop without hardware, run
   `simulator.py` (repo root) as its own process, either against a virtual
   COM port pair (e.g. com0com's `COM8<->COM9`) or, if com0com is being
   uncooperative, over plain TCP (`--transport tcp`, then connect the app
   to `TCP:127.0.0.1:5025`) — no virtual driver needed either way. See the
   docstring at the top of `simulator.py` and the README's "Running"
   section.

3. ~~`calibration/engine.py` — software volatility-window/max-time
   stabilization logic.~~ **Superseded by a deliberate redesign, not a
   gap.** Stabilization is now delegated entirely to the instrument's own
   `SOUR:STAB:TEST?` (judged against `SOUR:STAB:LIM`, which the app now
   configures — see §3.3), with no software-side elapsed timer or timeout
   fallback (§3.4). This intentionally drops the "capture anyway once max
   time elapses" behavior described in the original requirement notes — a
   setpoint that never stabilizes now requires the operator to hit Stop,
   on the reasoning that a non-stabilizing block indicates a hardware
   condition, not something software should mask.

4. ~~SRS document is stale.~~ Updated (`internal_reference/dry block
   callibrated software - SRS.md`, V2.0.0) to match this document and
   `changes in software.txt` — no longer describes Pass/Fail or target
   tolerance. (Still references the old volatility/max-time design for
   stabilization — due for another pass to match §3 above.)

---

## 7. Suggested order of work

1. ~~Fix simulator window check~~ — done as part of the simulator/process split.
2. ~~Decide on heating vs. stabilization timing~~ — resolved: stabilization
   is fully delegated to the instrument (`SOUR:STAB:TEST?`), no software
   timeout exists or is planned — see §3.4.
3. ~~Implement the real protocol in #1 (`usb_comm.py` + `simulator.py`
   against the SCPI PDF)~~ — done; `usb_comm.py` and `simulator.py` now
   implement the same Fluke 9144 SCPI command set.
4. ~~Update/retire the stale SRS.~~ Done (though see the note in §6, item 4 —
   it still needs a pass to match the finalized stabilization design).
5. ~~Add stability tolerance (`SOUR:STAB:LIM`) read/write, surfaced in
   Manufacturer Settings~~ — done, this update.

No open items remain in this document as of this pass.
