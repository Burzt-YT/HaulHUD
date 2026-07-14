from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any

def default_config_dir() -> str:
    appdata = os.environ.get("APPDATA")
    if appdata:
        path = os.path.join(appdata, "HaulHUD")
    else:
        path = os.path.join(os.path.expanduser("~"), ".haulhud")
    os.makedirs(path, exist_ok=True)
    return path

SETTINGS_PATH = os.path.join(default_config_dir(), "settings.json")

DEFAULT_FIELDS_VISIBLE = {
    "delivery_countdown": True,
    "delivery_eta": True,
    "nav_distance": True,
    "nav_time": True,
    "nav_eta": True,
    "rest_stop": True,
    "breaks_needed": True,
    "truck_speed": False,
    "speed_limit": False,
    "cargo_damage": True,
    "cargo_info": True,
    "job_route": True,
    "income": False,
}

INCOME_CURRENCIES: dict[str, tuple[str, float]] = {
    "EUR": ("€", 1.0),
    "CHF": ("CHF", 1.0595),
    "CZK": ("Kč", 28.3309),
    "GBP": ("£", 0.8678),
    "PLN": ("zł", 4.9427),
    "HUF": ("Ft", 387.68),
    "DKK": ("kr", 7.4692),
    "SEK": ("kr", 10.864),
    "NOK": ("kr", 11.161),
    "RUB": ("₽", 93.991),
    "BGN*": ("лв", 1.9558),
    "RON": ("lei", 5.0966),
    "TRY": ("₺", 51.195),
    "ALL": ("L", 96.086),
    "BAM*": ("KM", 1.9558),
    "MKD": ("ден", 61.616),
    "RSD": ("DIN", 117.45),
}

@dataclass
class OverlaySettings:
    pos_x: int = 60
    pos_y: int = 60
    width: int = 300
    opacity: float = 0.88
    scale: float = 1.0
    always_on_top: bool = True

    click_through: bool = False
    toggle_interactive_hotkey: str = "f9"

    theme: str = "dark"
    accent_color: str = "#4FC3F7"
    background_color: str = "#101418"
    text_color: str = "#F2F2F2"
    urgent_color: str = "#FF5252"
    font_family: str = "Segoe UI"
    font_size: int = 12
    corner_radius: int = 10

    poll_interval_ms: int = 150
    rest_urgent_threshold_min: float = 10.0
    hide_when_no_job: bool = False
    hide_when_game_not_running: bool = False

    break_duration_min: float = 2.0

    income_currency_code: str = "EUR"
    income_currency_multiplier: float = 1.0
    cargo_damage_cost: float = 5.0
    cargo_damage_cost_factor: float = 0.04

    fields_visible: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_FIELDS_VISIBLE))
    field_order: list[str] = field(default_factory=lambda: list(DEFAULT_FIELDS_VISIBLE.keys()))

    @staticmethod
    def load(path: str = SETTINGS_PATH) -> "OverlaySettings":
        if not os.path.exists(path):
            s = OverlaySettings()
            s.save(path)
            return s
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw: dict[str, Any] = json.load(f)
            defaults = asdict(OverlaySettings())
            defaults.update(raw)
            return OverlaySettings(**{k: v for k, v in defaults.items() if k in defaults})
        except (json.JSONDecodeError, TypeError, ValueError):
            s = OverlaySettings()
            s.save(path)
            return s

    def save(self, path: str = SETTINGS_PATH) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
