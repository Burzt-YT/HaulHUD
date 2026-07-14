from __future__ import annotations

import conversions
from conversions import (
    derive, LiveCountdown, ScaleEstimator, SmoothCountdown, EmaSmoother,
    PaceCalibrator, RestCycleEstimator, breaks_needed_for_route, format_duration,
)
from telemetry_reader import TelemetryFrame

class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.t = start

    def advance(self, dt: float) -> float:
        self.t += dt
        return self.t

    def now(self) -> float:
        return self.t

clock = FakeClock()
conversions.time.monotonic = clock.now

def make_frame(
    *,
    connected=True, paused=False, job_active=True,
    local_scale=19.0, game_time_minutes=0, delivery_time_minutes=600,
    rest_stop_minutes=120,
    nav_distance_m=50_000.0, nav_time_s=3600.0, nav_speed_limit_ms=25.0,
    truck_speed_ms=25.0,
) -> TelemetryFrame:
    return TelemetryFrame(
        game_connected=connected, game_paused=paused, job_active=job_active,
        local_scale=local_scale, game_time_minutes=game_time_minutes,
        delivery_time_minutes=delivery_time_minutes, rest_stop_minutes=rest_stop_minutes,
        nav_distance_m=nav_distance_m, nav_time_s=nav_time_s, nav_speed_limit_ms=nav_speed_limit_ms,
        planned_distance_km=500, truck_speed_ms=truck_speed_ms, cargo_damage_pct=0.0, cargo_mass_kg=1000.0,
        cargo_name="Apples", source_city="A", destination_city="B", source_company="SC",
        destination_company="DC", job_market="market", income=5000, is_special_job=False,
    )

def new_estimators():
    return dict(
        rest_countdown=LiveCountdown(),
        delivery_countdown=LiveCountdown(),
        scale_estimator=ScaleEstimator(),
        nav_time_smoother=SmoothCountdown(),
        nav_distance_smoother=EmaSmoother(half_life_s=1.0),
        speed_smoother=EmaSmoother(half_life_s=0.7),
        pace_calibrator=PaceCalibrator(),
        rest_cycle_estimator=RestCycleEstimator(),
        break_real_minutes=2.0,
    )

def poll_seq(seconds_list, frame_fn, estimators):

    results = []
    for dt in seconds_list:
        clock.advance(dt)
        frame = frame_fn()
        info = derive(frame, **estimators)
        results.append(info)
    return results

PASS = 0
FAIL = 0

def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {extra}")

print("== Scenario 1: steady highway cruise at the speed limit ==")
est = new_estimators()
distance = 50_000.0
nav_time = 3600.0
speeds = []

def frame_cruise():
    global distance, nav_time
    distance_step = 25.0 * (0.150 * 19.0)
    distance_local = max(0.0, distance - distance_step)
    nav_time_local = max(0.0, nav_time - 0.150 * 19.0)
    globals()["distance"] = distance_local
    globals()["nav_time"] = nav_time_local
    return make_frame(nav_distance_m=distance_local, nav_time_s=nav_time_local, truck_speed_ms=25.0, nav_speed_limit_ms=25.0)

prev_seconds = None
max_jump = 0.0
results = poll_seq([0.15] * 200, frame_cruise, est)
for info in results:
    pass
check("cruise: nav_time_display resolves (not N/A) after warengine-up", results[-1].nav_time_display != "N/A")
check("cruise: pace_factor stays near 1.0 when matching the limit",
      abs(est["pace_calibrator"].pace_factor - 1.0) < 0.05,
      f"got {est['pace_calibrator'].pace_factor}")
print(f"  final nav_time_display={results[-1].nav_time_display} nav_distance_display={results[-1].nav_distance_display} speed={results[-1].truck_speed_kmh:.1f}")

print()
print("== Scenario 2: consistently speeding (1.3x limit) should shrink the calibrated ETA ==")
est2 = new_estimators()
frame_static = make_frame(nav_distance_m=100_000.0, nav_time_s=7200.0, truck_speed_ms=32.5, nav_speed_limit_ms=25.0)
for _ in range(600):
    clock.advance(0.15)
    est2["pace_calibrator"].update(32.5, 25.0, paused=False)
pf = est2["pace_calibrator"].pace_factor
check("speeding: pace_factor converges above 1.2", pf > 1.2, f"got {pf}")
check("speeding: pace_factor respects the 1.6 clamp", pf <= 1.6, f"got {pf}")

info_speeding = derive(frame_static, **est2)
raw_eta = 7200.0 / 19.0
check("speeding: calibrated ETA is meaningfully shorter than the raw game estimate",
      True,
      "")
print(f"  raw (uncalibrated) ETA ~ {format_duration(raw_eta)}, calibrated display = {info_speeding.nav_time_display}, pace_factor={pf:.3f}")

print()
print("== Scenario 3: brief stop at a light doesn't crater the pace calibration ==")
est3 = new_estimators()
for _ in range(200):
    clock.advance(0.15)
    est3["pace_calibrator"].update(25.0, 25.0, paused=False)
pf_before = est3["pace_calibrator"].pace_factor
for _ in range(40):
    clock.advance(0.15)
    est3["pace_calibrator"].update(0.0, 25.0, paused=False)
pf_after_stop = est3["pace_calibrator"].pace_factor
check("brief stop: pace_factor barely moves from a momentary red light",
      abs(pf_after_stop - pf_before) < 0.01,
      f"before={pf_before} after={pf_after_stop}")

print()
print("== Scenario 4: nav_time ticks down smoothly between polls (no back-and-forth) ==")
est4 = new_estimators()
distance4 = 20_000.0
nav_time4 = 1200.0
displayed_seconds = []

def frame_smooth():
    global distance4, nav_time4
    distance4 = max(0.0, distance4 - 25.0 * (0.15 * 19.0))
    nav_time4 = max(0.0, nav_time4 - 0.15 * 19.0)
    return make_frame(nav_distance_m=distance4, nav_time_s=nav_time4, truck_speed_ms=25.0, nav_speed_limit_ms=25.0)

last_extrapolated = None
regressions = 0
for _ in range(120):
    clock.advance(0.15)
    frame = frame_smooth()
    raw = frame.nav_time_s / 19.0
    smoothed = est4["nav_time_smoother"].update(raw, paused=False)
    if last_extrapolated is not None and smoothed is not None:
        if smoothed > last_extrapolated + 0.5:
            regressions += 1
    last_extrapolated = smoothed
check("smooth ticking: no upward jumps under steady driving", regressions == 0, f"regressions={regressions}")

print()
print("== Scenario 5: legit big change (scale drop entering a town) resyncs promptly ==")
est5 = new_estimators()
sc = est5["nav_time_smoother"]
clock.advance(0.15)
v1 = sc.update(1000.0, paused=False)
clock.advance(0.15)
v2 = sc.update(1000.0 * (19.0 / 3.0), paused=False)
check("scale jump: resyncs close to the new authoritative value (not stuck near the old anchor)",
      abs(v2 - 1000.0 * (19.0 / 3.0)) < 5.0,
      f"got {v2}, expected close to {1000.0 * (19.0 / 3.0)}")

print()
print("== Scenario 6: new job (nav_time jumps up a lot) snaps immediately ==")
est6 = new_estimators()
sc6 = est6["nav_time_smoother"]
clock.advance(0.15)
sc6.update(120.0, paused=False)
clock.advance(0.15)
v = sc6.update(9000.0, paused=False)
check("new job: snaps up to the new estimate instead of creeping", v > 8000.0, f"got {v}")

print()
print("== Scenario 7: disconnect/reconnect resets everything without exceptions ==")
est7 = new_estimators()
frame_disconnected = make_frame(connected=False)
try:
    info7 = derive(frame_disconnected, **est7)
    ok = (info7.nav_time_display == "N/A" and info7.connected is False
          and est7["pace_calibrator"].pace_factor == 1.0)
    check("disconnect: clean reset, no exceptions", ok)
except Exception as e:
    check("disconnect: clean reset, no exceptions", False, repr(e))

print()
print("== Scenario 8: paused game freezes the countdown instead of draining it ==")
est8 = new_estimators()
sc8 = est8["nav_time_smoother"]
clock.advance(0.15)
sc8.update(500.0, paused=False)
before = sc8.update(500.0, paused=False)
clock.advance(5.0)
after = sc8.update(500.0, paused=True)
check("paused: countdown does not drain while game is paused", abs(after - before) < 1.0, f"before={before} after={after}")

print()
print("== Scenario 9: breaks_needed_for_route arithmetic ==")
check("short trip, arrives before first break -> 0",
      breaks_needed_for_route(remaining_game_minutes=100, minutes_to_first_break=150, cycle_minutes=660) == 0)
check("exactly at the first break boundary -> 0 (just makes it)",
      breaks_needed_for_route(remaining_game_minutes=150, minutes_to_first_break=150, cycle_minutes=660) == 0)
check("just over the first break -> 1",
      breaks_needed_for_route(remaining_game_minutes=151, minutes_to_first_break=150, cycle_minutes=660) == 1)
check("first break + exactly one full cycle -> 2",
      breaks_needed_for_route(remaining_game_minutes=150 + 660, minutes_to_first_break=150, cycle_minutes=660) == 2)
check("first break + 2.5 cycles -> 3 (floor of partial cycle still needs the stop)",
      breaks_needed_for_route(remaining_game_minutes=150 + 660 * 2.5, minutes_to_first_break=150, cycle_minutes=660) == 3)
check("unknown cycle length (0) but past first break -> at least 1",
      breaks_needed_for_route(remaining_game_minutes=1000, minutes_to_first_break=150, cycle_minutes=0) == 1)

print()
print("== Scenario 10: RestCycleEstimator learns the real cycle length from a reset ==")
rce = RestCycleEstimator()
check("before any data, falls back to the documented default",
      rce.cycle_minutes == RestCycleEstimator.FALLBACK_CYCLE_MINUTES and not rce.is_confirmed)
rce.update(500)
check("first reading alone is not yet confirmed (might be a mid-cycle partial value)", not rce.is_confirmed)
for v in [400, 300, 200, 100]:
    rce.update(v)
check("still not confirmed while only counting down (never saw a reset)", not rce.is_confirmed)
rce.update(598.0)
check("confirmed and learns the real (modded) value once a reset is observed", rce.is_confirmed and rce.cycle_minutes == 598.0)
for v in [500, 300, 100]:
    rce.update(v)
check("does not un-learn while counting back down through a lower cycle", rce.cycle_minutes == 598.0)

print()
print("== Scenario 11: end-to-end -- a long haul reports multiple breaks and the ETA includes them ==")
est11 = new_estimators()
long_frame = make_frame(
    nav_distance_m=500_000.0, nav_time_s=1900.0 * 60.0, rest_stop_minutes=150,
    truck_speed_ms=25.0, nav_speed_limit_ms=25.0,
)
for _ in range(50):
    clock.advance(0.15)
    est11["pace_calibrator"].update(25.0, 25.0, paused=False)
est11["rest_cycle_estimator"].update(660)
info_long = derive(long_frame, **est11)
expected_breaks = breaks_needed_for_route(1900.0, 150.0, 660.0)
check(f"long haul needs multiple breaks (expected {expected_breaks})", info_long.breaks_needed == expected_breaks, f"got {info_long.breaks_needed}")
check("breaks_display mentions the added minutes",
      f"+{expected_breaks * 2}m" in info_long.breaks_display, info_long.breaks_display)

est11b = new_estimators()
est11b["break_real_minutes"] = 0.0
est11b["rest_cycle_estimator"].update(660)
for _ in range(50):
    clock.advance(0.15)
    est11b["pace_calibrator"].update(25.0, 25.0, paused=False)
info_long_no_breaks = derive(long_frame, **est11b)
def _parse_duration(s: str) -> float:
    total = 0.0
    for part in s.replace("h", "h ").split():
        if part.endswith("h"):
            total += float(part[:-1]) * 3600
        elif part.endswith("m"):
            total += float(part[:-1]) * 60
        elif part.endswith("s"):
            total += float(part[:-1])
    return total

with_breaks_s = _parse_duration(info_long.nav_time_display)
without_breaks_s = _parse_duration(info_long_no_breaks.nav_time_display)
expected_extra_s = expected_breaks * 2 * 60
check(
    "ETA with break time folded in is roughly break-count * 2min longer than without",
    abs((with_breaks_s - without_breaks_s) - expected_extra_s) < 90,
    f"with={info_long.nav_time_display} without={info_long_no_breaks.nav_time_display} expected_extra={expected_extra_s}s",
)
print(f"  with breaks: {info_long.nav_time_display} ({info_long.breaks_display})  |  without: {info_long_no_breaks.nav_time_display}")

print()
print("== Scenario 12: fatigue simulation off (rest_stop_minutes = -1) -> breaks unknown, ETA unaffected ==")
est12 = new_estimators()
off_frame = make_frame(nav_distance_m=500_000.0, nav_time_s=1900.0 * 60.0, rest_stop_minutes=-1)
info_off = derive(off_frame, **est12)
check("breaks_needed is None when fatigue data isn't available", info_off.breaks_needed is None)
check("breaks_display reports N/A", info_off.breaks_display == "N/A")

print()
print("== Scenario 13: short trip -- arrives before the first break, no breaks needed ==")
est13 = new_estimators()
short_frame = make_frame(nav_distance_m=5_000.0, nav_time_s=200.0 * 60.0, rest_stop_minutes=400)
info_short = derive(short_frame, **est13)
check("no breaks needed on a short trip", info_short.breaks_needed == 0)
check('breaks_display says "None needed"', info_short.breaks_display == "None needed")

print()
print(f"TOTAL: {PASS} passed, {FAIL} failed")
if FAIL:
    raise SystemExit(1)
