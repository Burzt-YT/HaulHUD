from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from telemetry_reader import TelemetryFrame

UNAVAILABLE = None

REAL_SCALE = 20.0

MAP_DISTANCE_SCALE = 19.0

def ingame_minutes_to_real_seconds(ingame_minutes: float, local_scale: float = REAL_SCALE) -> float:
    if local_scale <= 0:
        local_scale = REAL_SCALE
    ingame_seconds = ingame_minutes * 60.0
    return ingame_seconds / local_scale

def format_duration(total_seconds: float) -> str:
    if total_seconds is None:
        return "N/A"
    total_seconds = max(0, int(total_seconds))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"

class ScaleEstimator:

    def __init__(self, initial_scale: float = REAL_SCALE) -> None:
        self._current_scale = initial_scale

    def update(self, local_scale: float | None, paused: bool = False) -> float:
        if local_scale is None or local_scale <= 0:
            return self._current_scale
        if paused:
            return self._current_scale
        self._current_scale = local_scale
        return self._current_scale

    def reset(self) -> None:
        self._current_scale = REAL_SCALE

class EmaSmoother:

    def __init__(self, half_life_s: float = 3.0) -> None:
        self._half_life_s = half_life_s
        self._value: float | None = None
        self._last_time: float | None = None

    def update(self, value: float | None, paused: bool = False) -> float | None:
        if value is None:
            self._value = None
            self._last_time = None
            return None

        now = time.monotonic()

        if self._value is None or self._last_time is None:
            self._value = value
            self._last_time = now
            return self._value

        elapsed = now - self._last_time
        self._last_time = now

        if paused or elapsed <= 0:
            return self._value

        if elapsed > 30.0:
            self._value = value
            return self._value

        alpha = 1.0 - 0.5 ** (elapsed / self._half_life_s)
        self._value += (value - self._value) * alpha
        return self._value

    def reset(self) -> None:
        self._value = None
        self._last_time = None

class PaceCalibrator:

    def __init__(self, half_life_s: float = 25.0) -> None:
        self._half_life_s = half_life_s
        self._ratio_ema: float | None = None
        self._last_time: float | None = None

    def update(self, truck_speed_ms: float, speed_limit_ms: float | None, paused: bool = False) -> None:
        if paused:
            return
        if speed_limit_ms is None or speed_limit_ms < 3.0:
            return
        if truck_speed_ms < 3.0:
            return

        sample = min(truck_speed_ms / speed_limit_ms, 2.0)
        now = time.monotonic()

        if self._ratio_ema is None or self._last_time is None:
            self._ratio_ema = sample
            self._last_time = now
            return

        elapsed = now - self._last_time
        self._last_time = now
        if elapsed <= 0:
            return
        if elapsed > 30.0:
            self._ratio_ema = sample
            return

        alpha = 1.0 - 0.5 ** (elapsed / self._half_life_s)
        self._ratio_ema += (sample - self._ratio_ema) * alpha

    @property
    def pace_factor(self) -> float:
        if self._ratio_ema is None:
            return 1.0
        return max(0.5, min(1.6, self._ratio_ema))

    def reset(self) -> None:
        self._ratio_ema = None
        self._last_time = None

class SmoothCountdown:

    def __init__(self, correction_half_life_s: float = 6.0) -> None:
        self._correction_half_life_s = correction_half_life_s
        self._anchor_seconds: float | None = None
        self._anchor_time: float | None = None

    def update(self, authoritative_seconds: float | None, paused: bool = False) -> float | None:
        if authoritative_seconds is None:
            self.reset()
            return None

        now = time.monotonic()

        if self._anchor_seconds is None or self._anchor_time is None:
            self._anchor_seconds = authoritative_seconds
            self._anchor_time = now
            return authoritative_seconds

        elapsed = max(0.0, now - self._anchor_time)
        extrapolated = self._anchor_seconds - (0.0 if paused else elapsed)

        drift = authoritative_seconds - extrapolated
        tolerance = max(6.0, extrapolated * 0.10)

        if abs(drift) > tolerance or extrapolated < -2.0:
            self._anchor_seconds = authoritative_seconds
            self._anchor_time = now
            return max(0.0, authoritative_seconds)

        correction = 1.0 - 0.5 ** (max(elapsed, 0.05) / self._correction_half_life_s)
        corrected = extrapolated + drift * correction
        self._anchor_seconds = corrected
        self._anchor_time = now
        return max(0.0, corrected)

    def reset(self) -> None:
        self._anchor_seconds = None
        self._anchor_time = None

class RestCycleEstimator:

    FALLBACK_CYCLE_MINUTES = 660.0

    def __init__(self) -> None:
        self._observed_max: float | None = None
        self._last_value: float | None = None
        self._seen_decrease_since_max: bool = False
        self._confirmed: bool = False

    def update(self, rest_stop_minutes: float | None) -> None:
        if rest_stop_minutes is None or rest_stop_minutes < 0:
            return

        if self._observed_max is None:
            self._observed_max = rest_stop_minutes
            self._last_value = rest_stop_minutes
            return

        if rest_stop_minutes < self._last_value:
            self._seen_decrease_since_max = True

        if rest_stop_minutes > self._observed_max and self._seen_decrease_since_max:
            self._observed_max = rest_stop_minutes
            self._seen_decrease_since_max = False
            self._confirmed = True

        self._last_value = rest_stop_minutes

    @property
    def cycle_minutes(self) -> float:
        return self._observed_max if self._observed_max is not None else self.FALLBACK_CYCLE_MINUTES

    @property
    def is_confirmed(self) -> bool:

        return self._confirmed

    def reset(self) -> None:
        self._observed_max = None
        self._last_value = None
        self._seen_decrease_since_max = False
        self._confirmed = False

def breaks_needed_for_route(
    remaining_game_minutes: float,
    minutes_to_first_break: float,
    cycle_minutes: float,
) -> int:

    if remaining_game_minutes <= minutes_to_first_break:
        return 0
    if cycle_minutes <= 0:
        return 1
    extra = remaining_game_minutes - minutes_to_first_break
    return 1 + int(extra // cycle_minutes)

class LiveCountdown:

    def __init__(self) -> None:
        self._last_raw_key: object = None
        self._anchor_seconds: float | None = None
        self._anchor_time: float | None = None
        self._last_scale: float | None = None

    def _raw_key_increased(self, raw_key: object) -> bool:
        if self._last_raw_key is None:
            return False
        try:
            return raw_key > self._last_raw_key
        except TypeError:
            return False

    def update(
        self,
        raw_key: object,
        authoritative_seconds: float | None,
        paused: bool = False,
        scale: float | None = None,
    ) -> float | None:
        if authoritative_seconds is None:
            self._last_raw_key = None
            self._anchor_seconds = None
            self._anchor_time = None
            self._last_scale = None
            return None

        now = time.monotonic()

        scale_changed = (
            scale is not None
            and self._last_scale is not None
            and scale != self._last_scale
        )
        if scale is not None:
            self._last_scale = scale

        if scale_changed:
            self._last_raw_key = raw_key
            self._anchor_seconds = authoritative_seconds
            self._anchor_time = now
            return max(0.0, authoritative_seconds)

        if paused:
            if raw_key != self._last_raw_key or self._anchor_seconds is None:
                is_real_increase = self._raw_key_increased(raw_key)
                if (
                    not is_real_increase
                    and self._anchor_seconds is not None
                    and self._anchor_time is not None
                ):
                    prev_elapsed = now - self._anchor_time
                    prev_smoothed = self._anchor_seconds - prev_elapsed
                    if prev_smoothed >= 0 and authoritative_seconds > prev_smoothed:
                        authoritative_seconds = prev_smoothed
                self._anchor_seconds = authoritative_seconds
            self._last_raw_key = raw_key
            self._anchor_time = now
            return max(0.0, self._anchor_seconds)

        if raw_key != self._last_raw_key or self._anchor_seconds is None:
            is_real_increase = self._raw_key_increased(raw_key)
            if (
                not is_real_increase
                and self._anchor_seconds is not None
                and self._anchor_time is not None
            ):
                prev_elapsed = now - self._anchor_time
                prev_smoothed = self._anchor_seconds - prev_elapsed
                if prev_smoothed >= 0 and authoritative_seconds > prev_smoothed:
                    authoritative_seconds = prev_smoothed

            self._last_raw_key = raw_key
            self._anchor_seconds = authoritative_seconds
            self._anchor_time = now
            return authoritative_seconds

        elapsed = now - self._anchor_time
        smoothed = self._anchor_seconds - elapsed

        if smoothed < -1.0 or elapsed < 0 or elapsed > 30.0:
            if smoothed >= 0 and authoritative_seconds > smoothed:
                authoritative_seconds = smoothed
            self._anchor_seconds = authoritative_seconds
            self._anchor_time = now
            return authoritative_seconds

        return max(0.0, smoothed)

    def reset(self) -> None:
        self._last_raw_key = None
        self._anchor_seconds = None
        self._anchor_time = None
        self._last_scale = None

def format_distance_km(meters: float) -> str:
    if meters is None or meters < 0:
        return "N/A"
    km = meters / 1000.0
    if km < 10:
        return f"{km:.1f} km"
    return f"{km:.0f} km"

def estimate_income_after_damage(
    base_income: float,
    cargo_damage_fraction: float,
    cargo_damage_cost: float = 5.0,
    cargo_damage_cost_factor: float = 0.04,
) -> float:

    if base_income <= 0 or cargo_damage_fraction <= 0:
        return base_income
    damage_pct = cargo_damage_fraction * 100.0
    penalty = damage_pct * (cargo_damage_cost + base_income * cargo_damage_cost_factor)
    return max(0.0, base_income - penalty)

@dataclass
class DerivedInfo:
    connected: bool
    paused: bool
    job_active: bool

    delivery_seconds_left_real: float | None
    delivery_display: str
    delivery_eta_wallclock: str

    nav_distance_display: str
    nav_time_display: str
    nav_eta_wallclock: str
    nav_speed_limit_kmh: float | None

    rest_seconds_left_real: float | None
    rest_display: str
    rest_urgent: bool

    breaks_needed: int | None
    breaks_display: str

    truck_speed_kmh: float
    cargo_damage_pct: float
    planned_distance_km: int
    cargo_name: str
    source_city: str
    destination_city: str
    income: int
    income_after_damage: float
    job_market: str

def derive(
    frame: TelemetryFrame,
    rest_urgent_threshold_min_real: float = 10.0,
    rest_countdown: LiveCountdown | None = None,
    delivery_countdown: LiveCountdown | None = None,
    scale_estimator: "ScaleEstimator | None" = None,
    nav_time_smoother: "SmoothCountdown | None" = None,
    nav_distance_smoother: "EmaSmoother | None" = None,
    speed_smoother: "EmaSmoother | None" = None,
    pace_calibrator: "PaceCalibrator | None" = None,
    rest_cycle_estimator: "RestCycleEstimator | None" = None,
    break_real_minutes: float = 2.0,
    cargo_damage_cost: float = 5.0,
    cargo_damage_cost_factor: float = 0.04,
) -> DerivedInfo:
    if not frame.game_connected:
        if rest_countdown is not None:
            rest_countdown.reset()
        if delivery_countdown is not None:
            delivery_countdown.reset()
        if scale_estimator is not None:
            scale_estimator.reset()
        if nav_time_smoother is not None:
            nav_time_smoother.reset()
        if nav_distance_smoother is not None:
            nav_distance_smoother.reset()
        if speed_smoother is not None:
            speed_smoother.reset()
        if pace_calibrator is not None:
            pace_calibrator.reset()
        if rest_cycle_estimator is not None:
            rest_cycle_estimator.reset()
        return DerivedInfo(
            connected=False, paused=True, job_active=False,
            delivery_seconds_left_real=None, delivery_display="Game not running",
            delivery_eta_wallclock="--:--",
            nav_distance_display="N/A", nav_time_display="N/A", nav_eta_wallclock="--:--",
            nav_speed_limit_kmh=None,
            rest_seconds_left_real=None, rest_display="N/A", rest_urgent=False,
            breaks_needed=None, breaks_display="N/A",
            truck_speed_kmh=0.0, cargo_damage_pct=0.0, planned_distance_km=0,
            cargo_name="", source_city="", destination_city="", income=0,
            income_after_damage=0.0, job_market="",
        )

    if scale_estimator is not None:
        effective_scale = scale_estimator.update(frame.local_scale, paused=frame.game_paused)
    else:
        effective_scale = frame.local_scale if frame.local_scale > 0 else REAL_SCALE

    delivery_seconds_left = None
    delivery_display = "No active job"
    eta_wallclock = "--:--"
    if frame.job_active and frame.delivery_time_minutes > 0:
        minutes_left_ingame = frame.delivery_time_minutes - frame.game_time_minutes
        raw_seconds = ingame_minutes_to_real_seconds(minutes_left_ingame, effective_scale)
        if delivery_countdown is not None:
            delivery_seconds_left = delivery_countdown.update(
                minutes_left_ingame, raw_seconds, paused=frame.game_paused, scale=effective_scale
            )
        else:
            delivery_seconds_left = raw_seconds
        delivery_display = format_duration(delivery_seconds_left)
        if delivery_seconds_left is not None:
            eta = datetime.now() + timedelta(seconds=max(0, delivery_seconds_left))
            eta_wallclock = eta.strftime("%H:%M")
    else:
        if delivery_countdown is not None:
            delivery_countdown.reset()

    nav_distance_display = "N/A"
    nav_time_display = "N/A"
    nav_eta_wallclock = "--:--"
    nav_speed_limit_kmh = None
    if frame.nav_speed_limit_ms is not None and frame.nav_speed_limit_ms >= 0:
        nav_speed_limit_kmh = frame.nav_speed_limit_ms * 3.6

    if pace_calibrator is not None:
        current_limit_ms = frame.nav_speed_limit_ms if (frame.nav_speed_limit_ms and frame.nav_speed_limit_ms > 0) else None
        pace_calibrator.update(frame.truck_speed_ms, current_limit_ms, paused=frame.game_paused)
    pace_factor = pace_calibrator.pace_factor if pace_calibrator is not None else 1.0

    if rest_cycle_estimator is not None:
        rest_cycle_estimator.update(frame.rest_stop_minutes)

    calibrated_game_seconds_remaining = None
    if frame.nav_time_s is not None and frame.nav_time_s >= 0:
        calibrated_game_seconds_remaining = frame.nav_time_s / pace_factor

    breaks_needed: int | None = None
    breaks_display = "N/A"
    breaks_extra_real_seconds = 0.0
    if (
        calibrated_game_seconds_remaining is not None
        and frame.rest_stop_minutes is not None
        and frame.rest_stop_minutes >= 0
    ):
        remaining_game_minutes = calibrated_game_seconds_remaining / 60.0
        cycle_minutes = (
            rest_cycle_estimator.cycle_minutes if rest_cycle_estimator is not None
            else RestCycleEstimator.FALLBACK_CYCLE_MINUTES
        )
        breaks_needed = breaks_needed_for_route(remaining_game_minutes, frame.rest_stop_minutes, cycle_minutes)
        if breaks_needed <= 0:
            breaks_display = "None needed"
        else:
            breaks_extra_real_seconds = breaks_needed * break_real_minutes * 60.0
            unit = "break" if breaks_needed == 1 else "breaks"
            breaks_display = f"{breaks_needed} {unit} (+{breaks_needed * break_real_minutes:.0f}m)"

    if frame.nav_distance_m is not None and frame.nav_distance_m >= 0:
        display_distance_m = frame.nav_distance_m
        if nav_distance_smoother is not None:
            smoothed_distance = nav_distance_smoother.update(display_distance_m, paused=frame.game_paused)
            if smoothed_distance is not None:
                display_distance_m = smoothed_distance
        nav_distance_display = format_distance_km(display_distance_m / MAP_DISTANCE_SCALE)
    else:
        if nav_distance_smoother is not None:
            nav_distance_smoother.reset()

    if calibrated_game_seconds_remaining is not None:
        raw_nav_seconds = calibrated_game_seconds_remaining / effective_scale
        total_nav_seconds = raw_nav_seconds + breaks_extra_real_seconds
        if nav_time_smoother is not None:
            nav_time_real_seconds = nav_time_smoother.update(
                total_nav_seconds, paused=frame.game_paused
            )
        else:
            nav_time_real_seconds = total_nav_seconds
        nav_time_display = format_duration(nav_time_real_seconds)
        if nav_time_real_seconds is not None:
            nav_eta = datetime.now() + timedelta(seconds=max(0, nav_time_real_seconds))
            nav_eta_wallclock = nav_eta.strftime("%H:%M")
    else:
        if nav_time_smoother is not None:
            nav_time_smoother.reset()

    truck_speed_kmh_raw = max(0.0, frame.truck_speed_ms * 3.6)
    if speed_smoother is not None:
        smoothed_speed = speed_smoother.update(truck_speed_kmh_raw, paused=frame.game_paused)
        truck_speed_kmh = smoothed_speed if smoothed_speed is not None else truck_speed_kmh_raw
    else:
        truck_speed_kmh = truck_speed_kmh_raw

    rest_seconds_left = None
    rest_display = "N/A"
    rest_urgent = False
    if frame.rest_stop_minutes is not None and frame.rest_stop_minutes >= 0:
        raw_seconds = ingame_minutes_to_real_seconds(frame.rest_stop_minutes, effective_scale)
        if rest_countdown is not None:
            rest_seconds_left = rest_countdown.update(
                frame.rest_stop_minutes, raw_seconds, paused=frame.game_paused, scale=effective_scale
            )
        else:
            rest_seconds_left = raw_seconds
        rest_display = format_duration(rest_seconds_left)
        rest_urgent = rest_seconds_left <= (rest_urgent_threshold_min_real * 60.0)
    else:
        if rest_countdown is not None:
            rest_countdown.reset()

    return DerivedInfo(
        connected=True,
        paused=frame.game_paused,
        job_active=frame.job_active,
        delivery_seconds_left_real=delivery_seconds_left,
        delivery_display=delivery_display,
        delivery_eta_wallclock=eta_wallclock,
        nav_distance_display=nav_distance_display,
        nav_time_display=nav_time_display,
        nav_eta_wallclock=nav_eta_wallclock,
        nav_speed_limit_kmh=nav_speed_limit_kmh,
        rest_seconds_left_real=rest_seconds_left,
        rest_display=rest_display,
        rest_urgent=rest_urgent,
        breaks_needed=breaks_needed,
        breaks_display=breaks_display,
        truck_speed_kmh=truck_speed_kmh,
        cargo_damage_pct=frame.cargo_damage_pct * 100.0,
        planned_distance_km=frame.planned_distance_km,
        cargo_name=frame.cargo_name,
        source_city=frame.source_city,
        destination_city=frame.destination_city,
        income=frame.income,
        income_after_damage=estimate_income_after_damage(
            frame.income, frame.cargo_damage_pct, cargo_damage_cost, cargo_damage_cost_factor
        ),
        job_market=frame.job_market,
    )
