#!/usr/bin/env python3
"""
Fluke 9144 Field Metrology Well - Software Development Simulator
================================================================

A stand-alone process that behaves like a real Fluke 9144 (-P model) on the
serial wire: same SCPI commands, same response formats (including the trailing
unit suffix), same 8N1 / CR-or-LF framing, plus a physically plausible thermal
model so setpoints ramp, overshoot, settle and stabilise like a real block.

Run this in one terminal, run the calibrator software (main.py) in another, and
point the software at the paired COM port. When the real 9144 arrives, nothing
in the software changes - you just point it at the real port.

    # com0com (Windows, most hardware-realistic): sim opens one end, software the other
    python simulator.py --transport serial --port COM9

    # TCP (no driver needed, good for quick tests / CI):
    python simulator.py --transport tcp --host 127.0.0.1 --tcp-port 5025

    # Prove it works with no hardware and no client:
    python simulator.py --selftest

All tuning lives in the CONFIG block below.
"""

import argparse
import math
import random
import socket
import sys
import threading
import time
from dataclasses import dataclass, field


# =============================================================================
# CONFIG  -  everything tunable lives here
# =============================================================================
@dataclass
class Config:
    # ---- Transport ----------------------------------------------------------
    transport: str = "serial"          # "serial" (com0com) or "tcp"
    port: str = "COM11" \
    ""                 # serial port the SIMULATOR opens
    baud: int = 9600                   # 1200/2400/4800/9600/19200/38400
    tcp_host: str = "127.0.0.1"
    tcp_port: int = 5025               # standard SCPI raw-socket port

    # ---- Identity -----------------------------------------------------------
    manufacturer: str = "HART"
    model: str = "9144"
    serial_number: str = "A79002"
    firmware: str = "1.00"
    is_p_model: bool = True            # -P present? gates CALC1/CALC2/reference

    # ---- Time ---------------------------------------------------------------
    # Simulated seconds per real second. 1.0 = real-time (most hardware-like).
    # Bump to 10-60 for fast development iteration (timing then unrealistic).
    time_scale: float = 1.0
    tick_real_s: float = 0.1           # how often the thermal model updates

    # ---- Thermal model ------------------------------------------------------
    ambient_c: float = 23.0            # starting block temperature
    start_setpoint_c: float = 23.0
    tau_heat_s: float = 150.0          # time constant heating (smaller = faster)
    tau_cool_s: float = 250.0          # cooling is slower than heating
    damping: float = 0.95              # < 1 gives overshoot/ringing (zeta)
    sp_min_c: float = 25.0             # 9144 setpoint range
    sp_max_c: float = 660.0
    hard_cutout_c: float = 670.0

    # ---- Sensors / noise ----------------------------------------------------
    block_noise_sd: float = 0.003      # control sensor noise (keep < stab_limit)
    master_noise_sd: float = 0.010     # reference RTD read noise
    uut_noise_sd: float = 0.010        # UUT read noise
    reference_offset_c: float = 0.02   # master vs control-sensor bias
    # UUT error injected as offset + slope*setpoint (the point of calibration):
    #   ~ +0.30 C at 100 C,  ~ +0.80 C at 400 C
    uut_error_offset_c: float = 0.133
    uut_error_slope: float = 0.001667

    # ---- Heater duty --------------------------------------------------------
    heater_kp: float = 0.6             # % duty per degree of positive error
    heater_hold_coeff: float = 0.10    # steady % to hold temp above ambient

    # ---- Stability ----------------------------------------------------------
    stab_window_s: float = 30.0        # trailing window that must stay in-band
    stab_limit_c: float = 0.05         # default fluctuation limit (0.01-9.99)

    # ---- Realism / fault injection -----------------------------------------
    latency_ms: float = 25.0           # processing delay before each response
    chaos_enabled: bool = False        # master switch for fault injection
    chaos_drop_prob: float = 0.02      # drop a response entirely
    chaos_garble_prob: float = 0.02    # corrupt a byte in a response
    chaos_delay_prob: float = 0.02     # add a long (>timeout) delay
    chaos_delay_s: float = 5.0
    chaos_cutout_prob: float = 0.0     # spontaneously trip the cutout

    # ---- Logging ------------------------------------------------------------
    verbose: bool = True               # log every command / response


CONFIG = Config()
CR = 0x0D
LF = 0x0A


# =============================================================================
# THERMAL MODEL  -  the physics (runs in its own thread)
# =============================================================================
class ThermalModel:
    """Second-order block dynamics: ramps toward setpoint with slight overshoot
    and settling, asymmetric heat/cool rates, measurement noise, coherent
    master/UUT sensors and a heater duty cycle."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self.setpoint_c = cfg.start_setpoint_c
        self.block_c = cfg.ambient_c        # true physical block temperature
        self._velocity = 0.0                # dT/dt for the 2nd-order model
        self.heater_pct = 0.0
        self.cutout_tripped = False
        self.heat_enabled = True

        # stability buffer: list of (sim_time, measured_block_c)
        self._stab_buf = []
        self._sim_time = 0.0

    # ---- lifecycle ----------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        last = time.monotonic()
        # keep at least this many samples across the stability window, even when
        # time is accelerated, so is_stable() has enough points to judge
        max_sim_dt = max(0.05, self.cfg.stab_window_s / 12.0)
        while not self._stop.is_set():
            time.sleep(self.cfg.tick_real_s)
            now = time.monotonic()
            real_dt = now - last
            last = now
            sim_dt = real_dt * self.cfg.time_scale
            # advance in bounded chunks so the stability buffer stays dense
            while sim_dt > 0:
                step = min(sim_dt, max_sim_dt)
                self._advance(step)
                sim_dt -= step

    # ---- integration --------------------------------------------------------
    def _advance(self, sim_dt: float):
        cfg = self.cfg
        # sub-step so large accelerated dt stays numerically stable
        max_h = 0.5
        n = max(1, int(math.ceil(sim_dt / max_h)))
        h = sim_dt / n
        with self._lock:
            for _ in range(n):
                if self.cutout_tripped or not self.heat_enabled:
                    # no active drive: drift slowly toward ambient
                    self.block_c += (cfg.ambient_c - self.block_c) * h / (cfg.tau_cool_s * 3)
                    self._velocity = 0.0
                else:
                    target = self.setpoint_c
                    heating = target >= self.block_c
                    tau = cfg.tau_heat_s if heating else cfg.tau_cool_s
                    wn = 1.0 / tau
                    accel = wn * wn * (target - self.block_c) - 2 * cfg.damping * wn * self._velocity
                    self._velocity += accel * h
                    self.block_c += self._velocity * h
                self._sim_time += h

            # spontaneous cutout if we somehow exceed the hard limit
            if self.block_c >= cfg.hard_cutout_c:
                self.cutout_tripped = True

            # heater duty
            err = self.setpoint_c - self.block_c
            hold = max(0.0, (self.setpoint_c - cfg.ambient_c) * cfg.heater_hold_coeff)
            duty = hold + cfg.heater_kp * max(0.0, err)
            if self.cutout_tripped or not self.heat_enabled:
                duty = 0.0
            self.heater_pct = max(0.0, min(100.0, duty))

            # append a noisy sample to the stability buffer and trim to window
            measured = self.block_c + random.gauss(0, cfg.block_noise_sd)
            self._stab_buf.append((self._sim_time, measured))
            # keep one sample OLDER than the window edge so the retained span
            # genuinely covers the full window (prevents the span from always
            # sitting just under stab_window_s after trimming)
            cutoff = self._sim_time - cfg.stab_window_s
            while len(self._stab_buf) > 2 and self._stab_buf[1][0] < cutoff:
                self._stab_buf.pop(0)

    # ---- reads (thread-safe) ------------------------------------------------
    def read_block_c(self) -> float:
        with self._lock:
            return self.block_c + random.gauss(0, self.cfg.block_noise_sd)

    def read_master_c(self) -> float:
        with self._lock:
            return (self.block_c + self.cfg.reference_offset_c
                    + random.gauss(0, self.cfg.master_noise_sd))

    def read_uut_c(self) -> float:
        cfg = self.cfg
        with self._lock:
            master = self.block_c + cfg.reference_offset_c
            uut_err = cfg.uut_error_offset_c + cfg.uut_error_slope * self.setpoint_c
            return master + uut_err + random.gauss(0, cfg.uut_noise_sd)

    def stability_c(self) -> float:
        """Current fluctuation = peak-to-peak of the trailing window."""
        with self._lock:
            if len(self._stab_buf) < 2:
                return 9.99
            vals = [v for _, v in self._stab_buf]
            return max(vals) - min(vals)

    def is_stable(self, limit_c: float) -> bool:
        """Stable only if the buffer spans the FULL window in real elapsed
        (simulated) seconds AND stayed within the limit the whole time."""
        with self._lock:
            # need enough samples AND enough real elapsed span to judge
            if len(self._stab_buf) < 4:
                return False
            span = self._stab_buf[-1][0] - self._stab_buf[0][0]
            if span < self.cfg.stab_window_s:
                return False
            vals = [v for _, v in self._stab_buf]
            return (max(vals) - min(vals)) <= limit_c

    # ---- writes -------------------------------------------------------------
    def set_setpoint_c(self, value_c: float):
        with self._lock:
            self.setpoint_c = value_c
            # Stability is "at the current set-point" (9144 protocol §6.4),
            # so a setpoint change must invalidate old history — otherwise a
            # block that was already flat at the previous setpoint reports
            # stable instantly at the new one too, before it's even started
            # moving. Real hardware doesn't carry stale flatness across a
            # setpoint change; this model shouldn't either.
            self._stab_buf = []

    def clear_cutout(self):
        with self._lock:
            self.cutout_tripped = False

    def trip_cutout(self):
        with self._lock:
            self.cutout_tripped = True


# =============================================================================
# SCPI ENGINE  -  parse a command line, return the response string (or None)
# =============================================================================
class ScpiEngine:
    def __init__(self, cfg: Config, model: ThermalModel):
        self.cfg = cfg
        self.model = model
        self.units = "C"                 # display units, C or F
        self.stab_limit_c = cfg.stab_limit_c
        self.scan_rate = 100.0
        self.error_queue = []

    # ---- unit helpers -------------------------------------------------------
    def _c_to_disp(self, c: float) -> float:
        return c if self.units == "C" else c * 9.0 / 5.0 + 32.0

    def _disp_to_c(self, d: float) -> float:
        return d if self.units == "C" else (d - 32.0) * 5.0 / 9.0

    def _delta_to_disp(self, c: float) -> float:      # for stability figures
        return c if self.units == "C" else c * 9.0 / 5.0

    def _push_err(self, msg: str):
        self.error_queue.append(msg)

    # ---- main entry ---------------------------------------------------------
    def process(self, line: str):
        """Return response string for a query, or None for a set/action."""
        line = line.strip()
        if not line:
            return None

        header, _, arg = line.partition(" ")
        h = header.upper()
        arg = arg.strip()
        is_query = h.endswith("?")

        # ---- IEEE-488 common commands --------------------------------------
        if h == "*IDN?":
            c = self.cfg
            return f"{c.manufacturer},{c.model},{c.serial_number},{c.firmware}"
        if h == "*OPT?":
            return "1" if self.cfg.is_p_model else "0"
        if h == "*CLS":
            self.error_queue.clear()
            return None
        if h == "*RST":
            self.model.set_setpoint_c(self.cfg.ambient_c)
            return None

        # ---- system ---------------------------------------------------------
        if h == "SYST:CONF:MOD?":
            return "1" if self.cfg.is_p_model else "0"
        if h == "SYST:ERR?":
            return self.error_queue.pop(0) if self.error_queue else "No Error"

        # ---- live temperature reads ----------------------------------------
        if h == "SOUR:SENS:DATA?":
            if arg.upper() == "RES":
                # crude resistance proxy for a PT100-ish control sensor
                return f"{100.0 + self.model.read_block_c() * 0.385:.2f}"
            val = self._c_to_disp(self.model.read_block_c())
            return f"{val:.3f}{self.units}"          # NOTE the unit suffix
        if h in ("CALC1:DATA?", "READ?", "MEAS?", "FETC?"):
            if not self.cfg.is_p_model:
                self._push_err("Reference not installed")
                return "0.0"
            return f"{self._c_to_disp(self.model.read_master_c()):.3f}"
        if h == "CALC2:DATA?":
            if not self.cfg.is_p_model:
                self._push_err("UUT not installed")
                return "0.0"
            return f"{self._c_to_disp(self.model.read_uut_c()):.3f}"

        # ---- heater / output ------------------------------------------------
        if h == "OUTP1:DATA?":
            return f"{self.model.heater_pct:.1f}"
        if h == "OUTP2:DATA?":
            return f"{min(100.0, self.model.heater_pct * 1.1):.1f}"
        if h == "OUTP1:STAT?" or h == "OUTP:STAT?":
            return "1" if self.model.heat_enabled else "0"
        if h in ("OUTP1:STAT", "OUTP:STAT"):
            self.model.heat_enabled = arg.strip() in ("1", "ON", "on")
            return None

        # ---- setpoint -------------------------------------------------------
        if h == "SOUR:SPO?":
            return f"{self._c_to_disp(self.model.setpoint_c):.3f}"
        if h == "SOUR:SPO":
            self._set_setpoint(arg)
            return None

        # ---- stability ------------------------------------------------------
        if h == "SOUR:STAB:DAT?":
            return f"{self._delta_to_disp(self.model.stability_c()):.3f}"
        if h == "SOUR:STAB:TEST?":
            return "1" if self.model.is_stable(self.stab_limit_c) else "0"
        if h == "SOUR:STAB:LIM?":
            return f"{self._delta_to_disp(self.stab_limit_c):.2f}"
        if h == "SOUR:STAB:LIM":
            self._set_stab_limit(arg)
            return None

        # ---- protection / safety -------------------------------------------
        if h == "SOUR:PROT:TRIP?":
            return "1" if self.model.cutout_tripped else "0"
        if h == "SOUR:PROT:HCUT?":
            return f"{self._c_to_disp(self.cfg.hard_cutout_c):.0f}"
        if h == "SOUR:PROT:CLEA":
            self.model.clear_cutout()
            return None

        # ---- rate & units ---------------------------------------------------
        if h == "SOUR:RATE?":
            return f"{self.scan_rate:.3f}"
        if h == "SOUR:RATE":
            try:
                self.scan_rate = float(arg)
            except ValueError:
                self._push_err("Invalid parameter")
            return None
        if h == "UNIT:TEMP?":
            return self.units
        if h == "UNIT:TEMP":
            u = arg.strip().upper()
            if u in ("C", "F"):
                self.units = u
            else:
                self._push_err("Invalid unit")
            return None

        # ---- unknown --------------------------------------------------------
        self._push_err(f"Unknown command: {header}")
        if is_query:
            return ""            # a real box would leave the buffer empty
        return None

    # ---- setters with validation -------------------------------------------
    def _set_setpoint(self, arg: str):
        try:
            disp = float(arg)
        except ValueError:
            self._push_err("Invalid setpoint")
            return
        c = self._disp_to_c(disp)
        if c < self.cfg.sp_min_c:
            self._push_err("Setpoint below minimum")
            c = self.cfg.sp_min_c
        elif c > self.cfg.sp_max_c:
            self._push_err("Setpoint above maximum")
            c = self.cfg.sp_max_c
        self.model.set_setpoint_c(c)

    def _set_stab_limit(self, arg: str):
        try:
            lim = float(arg)
        except ValueError:
            self._push_err("Invalid limit")
            return
        lim_c = lim if self.units == "C" else lim * 5.0 / 9.0
        if 0.01 <= lim_c <= 9.99:
            self.stab_limit_c = lim_c
        else:
            self._push_err("Limit out of range")


# =============================================================================
# RESPONSE PIPELINE  -  latency + optional fault injection
# =============================================================================
def apply_realism(cfg: Config, response: str):
    """Return (maybe-modified response or None-to-drop). Also applies latency."""
    # processing latency, scaled with the clock
    delay = cfg.latency_ms / 1000.0
    if cfg.chaos_enabled and random.random() < cfg.chaos_delay_prob:
        delay += cfg.chaos_delay_s
    if delay > 0:
        time.sleep(delay)

    if response is None:
        return None
    if cfg.chaos_enabled:
        if random.random() < cfg.chaos_drop_prob:
            return None                          # response silently lost
        if random.random() < cfg.chaos_garble_prob and response:
            i = random.randrange(len(response))
            response = response[:i] + chr(random.randint(33, 126)) + response[i + 1:]
    return response


def log(cfg: Config, msg: str):
    if cfg.verbose:
        print(msg, flush=True)


# =============================================================================
# TRANSPORTS
# =============================================================================
def _line_terminator(cfg: Config) -> bytes:
    return b"\r"        # CR; software should accept either. LF also accepted on input.


def handle_stream_bytes(cfg, engine, model, read_fn, write_fn):
    """Shared framing loop: accumulate bytes until CR or LF, dispatch each line."""
    buffer = bytearray()
    while True:
        chunk = read_fn()
        if chunk is None:                # connection closed
            return
        if not chunk:
            continue
        for b in chunk:
            if b in (CR, LF):
                if buffer:
                    line = buffer.decode("ascii", errors="replace")
                    buffer.clear()
                    _dispatch_line(cfg, engine, model, line, write_fn)
                # ignore empty lines / bare terminators
            else:
                buffer.append(b)


def _dispatch_line(cfg, engine, model, line, write_fn):
    log(cfg, f"  <- {line!r}")
    if cfg.chaos_enabled and random.random() < cfg.chaos_cutout_prob:
        model.trip_cutout()
        log(cfg, "  !! chaos: cutout tripped")
    response = engine.process(line)
    response = apply_realism(cfg, response)
    if response is None:
        log(cfg, "  -> (no response)")
        return
    payload = response.encode("ascii", errors="replace") + _line_terminator(cfg)
    write_fn(payload)
    log(cfg, f"  -> {response!r}")


def run_serial(cfg: Config, engine: ScpiEngine, model: ThermalModel):
    try:
        import serial          # pyserial
    except ImportError:
        print("ERROR: pyserial is required for serial transport.\n"
              "       pip install pyserial   (and install com0com on Windows)",
              file=sys.stderr)
        sys.exit(2)

    ser = serial.Serial(
        port=cfg.port, baudrate=cfg.baud,
        bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE, timeout=0.1,
    )
    log(cfg, f"Serial simulator on {cfg.port} @ {cfg.baud} 8N1. Ctrl-C to stop.")

    def read_fn():
        try:
            data = ser.read(256)      # returns b'' on timeout
            return data
        except Exception as e:
            log(cfg, f"  serial read error: {e}")
            return None

    def write_fn(payload):
        ser.write(payload)

    try:
        handle_stream_bytes(cfg, engine, model, read_fn, write_fn)
    finally:
        ser.close()


def run_tcp(cfg: Config, engine: ScpiEngine, model: ThermalModel):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((cfg.tcp_host, cfg.tcp_port))
    srv.listen(1)
    log(cfg, f"TCP simulator on {cfg.tcp_host}:{cfg.tcp_port}. Ctrl-C to stop.")

    while True:
        conn, addr = srv.accept()
        log(cfg, f"Client connected: {addr}")
        conn.settimeout(0.1)

        def read_fn():
            try:
                data = conn.recv(256)
                if data == b"":
                    return None       # closed
                return data
            except socket.timeout:
                return b""
            except OSError:
                return None

        def write_fn(payload):
            try:
                conn.sendall(payload)
            except OSError:
                pass

        try:
            handle_stream_bytes(cfg, engine, model, read_fn, write_fn)
        finally:
            conn.close()
            log(cfg, "Client disconnected.")


# =============================================================================
# SELF-TEST  -  drive the engine directly, no transport, accelerated time
# =============================================================================
def run_selftest(cfg: Config):
    cfg.time_scale = 90.0         # 90 s of physics per real second
    cfg.verbose = False
    model = ThermalModel(cfg)
    engine = ScpiEngine(cfg, model)
    model.start()

    def cmd(line):
        r = engine.process(line)
        return r

    print("Fluke 9144 simulator - self test (accelerated time)\n")
    print(f"*IDN?            -> {cmd('*IDN?')}")
    print(f"SYST:CONF:MOD?   -> {cmd('SYST:CONF:MOD?')}")
    print(f"*OPT?            -> {cmd('*OPT?')}")
    print(f"UNIT:TEMP?       -> {cmd('UNIT:TEMP?')}")
    print(f"SOUR:SENS:DATA?  -> {cmd('SOUR:SENS:DATA?')}   (note the C suffix)")
    print()

    target = 200.0
    print(f"Sending SOUR:SPO {target} and watching it ramp & stabilise...\n")
    cmd(f"SOUR:SPO {target}")
    print(f"{'elapsed':>8} {'block':>9} {'master':>9} {'uut':>9} "
          f"{'error':>8} {'heat%':>7} {'stab':>7} {'stable':>7}")
    t0 = time.monotonic()
    stable_seen = False
    for _ in range(80):
        time.sleep(0.25)
        block = cmd("SOUR:SENS:DATA?")
        master = cmd("CALC1:DATA?")
        uut = cmd("CALC2:DATA?")
        heat = cmd("OUTP1:DATA?")
        stab = cmd("SOUR:STAB:DAT?")
        stable = cmd("SOUR:STAB:TEST?")
        b = float(block.rstrip("CF"))
        m = float(master)
        u = float(uut)
        err = u - m
        elapsed = time.monotonic() - t0
        print(f"{elapsed:8.1f} {b:9.3f} {m:9.3f} {u:9.3f} "
              f"{err:8.3f} {float(heat):7.1f} {float(stab):7.3f} {stable:>7}")
        if stable == "1" and not stable_seen:
            stable_seen = True
            print(f"   --> reached STABLE at setpoint {target}\n")
            break

    print("\nRange / error handling checks:")
    cmd("SOUR:SPO 900")                      # over max
    print(f"  SOUR:SPO 900 then SYST:ERR? -> {cmd('SYST:ERR?')}")
    print(f"  SOUR:SPO?                    -> {cmd('SOUR:SPO?')}  (clamped to 660)")
    cmd("BOGUS:CMD?")
    print(f"  BOGUS:CMD? then SYST:ERR?    -> {cmd('SYST:ERR?')}")

    print("\nUUT error injection (offset+slope) at a few setpoints:")
    for sp in (100.0, 400.0):
        cfg.time_scale = 100000.0            # jump essentially instantly
        cmd(f"SOUR:SPO {sp}")
        time.sleep(0.4)
        m = float(cmd("CALC1:DATA?"))
        u = float(cmd("CALC2:DATA?"))
        print(f"  setpoint {sp:6.1f}  master {m:8.3f}  uut {u:8.3f}  "
              f"injected error {u - m:+.3f} C")

    model.stop()
    print("\nSelf-test complete.")


# =============================================================================
# ENTRY POINT
# =============================================================================
def parse_args():
    p = argparse.ArgumentParser(description="Fluke 9144 simulator")
    p.add_argument("--transport", choices=["serial", "tcp"], default=CONFIG.transport)
    p.add_argument("--port", default=CONFIG.port, help="serial port (com0com end)")
    p.add_argument("--baud", type=int, default=CONFIG.baud)
    p.add_argument("--host", default=CONFIG.tcp_host)
    p.add_argument("--tcp-port", type=int, default=CONFIG.tcp_port)
    p.add_argument("--time-scale", type=float, default=CONFIG.time_scale,
                   help="simulated seconds per real second (1.0 = realtime)")
    p.add_argument("--non-p", action="store_true",
                   help="simulate a non-P unit (no reference/UUT)")
    p.add_argument("--chaos", action="store_true", help="enable fault injection")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--selftest", action="store_true",
                   help="run a scripted demo with no transport, then exit")
    return p.parse_args()


def main():
    args = parse_args()
    CONFIG.transport = args.transport
    CONFIG.port = args.port
    CONFIG.baud = args.baud
    CONFIG.tcp_host = args.host
    CONFIG.tcp_port = args.tcp_port
    CONFIG.time_scale = args.time_scale
    CONFIG.is_p_model = not args.non_p
    CONFIG.chaos_enabled = args.chaos
    CONFIG.verbose = not args.quiet

    if args.selftest:
        run_selftest(CONFIG)
        return

    model = ThermalModel(CONFIG)
    engine = ScpiEngine(CONFIG, model)
    model.start()
    try:
        if CONFIG.transport == "serial":
            run_serial(CONFIG, engine, model)
        else:
            run_tcp(CONFIG, engine, model)
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        model.stop()


if __name__ == "__main__":
    main()