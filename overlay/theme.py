from __future__ import annotations

from settings import OverlaySettings

THEME_PRESETS = {
    "dark": dict(background_color="#12161B", text_color="#EDEFF2", accent_color="#4FC3F7"),
    "midnight_blue": dict(background_color="#0B1220", text_color="#E7ECF5", accent_color="#5B8DEF"),
    "light": dict(background_color="#F3F4F6", text_color="#15181C", accent_color="#0072CE"),
}

STATUS_GOOD = "#5FD98A"
STATUS_CAUTION = "#F5B94D"
STATUS_URGENT = "#FF5C5C"

def build_qss(settings: OverlaySettings) -> str:
    bg = settings.background_color
    fg = settings.text_color
    accent = settings.accent_color
    radius = settings.corner_radius
    font = settings.font_family
    size = settings.font_size

    return f"""
    QFrame#RootPanel {{
        background-color: {bg};
        border-radius: {radius}px;
        border: 1px solid rgba(255, 255, 255, 28);
    }}

    QLabel {{
        color: {fg};
        font-family: "{font}";
        background: transparent;
    }}

    QLabel[role="fieldLabel"] {{
        font-size: {max(8, size - 3)}px;
        font-weight: 600;
        letter-spacing: 1.5px;
        color: rgba(255,255,255,140);
        text-transform: uppercase;
    }}

    QLabel[role="fieldValue"] {{
        font-family: "Consolas", "Cascadia Mono", monospace;
        font-size: {size + 3}px;
        font-weight: 600;
        color: {fg};
    }}

    QLabel[role="fieldValue"][status="good"] {{ color: {STATUS_GOOD}; }}
    QLabel[role="fieldValue"][status="caution"] {{ color: {STATUS_CAUTION}; }}
    QLabel[role="fieldValue"][status="urgent"] {{ color: {STATUS_URGENT}; }}

    QLabel[role="titleBar"] {{
        color: {accent};
        font-size: {max(9, size - 2)}px;
        font-weight: 700;
        letter-spacing: 2px;
    }}

    QFrame[role="divider"] {{
        background-color: rgba(255,255,255,26);
        max-height: 1px;
        min-height: 1px;
        border: none;
    }}

    QFrame[role="modeBadge"] {{
        border-radius: 4px;
        padding: 2px 6px;
    }}

    QLabel[role="modeBadgeText"] {{
        font-size: {max(8, size - 4)}px;
        font-weight: 700;
        letter-spacing: 1px;
    }}

    QPushButton#SettingsButton {{
        background: transparent;
        border: none;
        border-radius: 4px;
        color: rgba(255,255,255,140);
        font-size: {size}px;
        padding: 0px;
    }}

    QPushButton#SettingsButton:hover {{
        background: rgba(255,255,255,24);
        color: {fg};
    }}

    QPushButton#SettingsButton:pressed {{
        background: rgba(255,255,255,40);
    }}
    """

def status_for_rest(urgent: bool, seconds_left: float | None) -> str:
    if seconds_left is None:
        return ""
    if urgent:
        return "urgent"
    if seconds_left <= 20 * 60:
        return "caution"
    return "good"

def status_for_damage(pct: float) -> str:
    if pct >= 50:
        return "urgent"
    if pct >= 15:
        return "caution"
    return "good"
