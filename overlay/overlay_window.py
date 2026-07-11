from __future__ import annotations

import sys
import ctypes

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPoint
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QApplication, QSizePolicy,
    QPushButton
)

from settings import OverlaySettings, INCOME_CURRENCIES
from telemetry_reader import TelemetryReader
from conversions import (
    derive, DerivedInfo, LiveCountdown, ScaleEstimator, EmaSmoother,
    SmoothCountdown, PaceCalibrator, RestCycleEstimator,
)
from theme import build_qss, status_for_rest, status_for_damage
from global_hotkey import GlobalHotkeyListener

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

def _set_windows_click_through(hwnd: int, enabled: bool) -> None:
    if not sys.platform.startswith("win"):
        return
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enabled:
        style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
    else:
        style &= ~WS_EX_TRANSPARENT
        style |= WS_EX_LAYERED
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

class _HotkeyBridge(QObject):
    triggered = Signal()

def _field_row(label_text: str) -> tuple[QWidget, QLabel, QLabel]:
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(1)

    label = QLabel(label_text)
    label.setProperty("role", "fieldLabel")

    value = QLabel("--")
    value.setProperty("role", "fieldValue")

    layout.addWidget(label)
    layout.addWidget(value)
    return row, label, value

class OverlayWindow(QWidget):
    def __init__(self, settings: OverlaySettings, on_open_settings=None) -> None:
        super().__init__()
        self.settings = settings
        self.reader = TelemetryReader()
        self.on_open_settings = on_open_settings

        self._drag_offset: QPoint | None = None
        self._rows: dict[str, tuple[QWidget, QLabel, QLabel]] = {}

        self._rest_countdown = LiveCountdown()
        self._delivery_countdown = LiveCountdown()

        self._nav_scale_estimator = ScaleEstimator()

        # The game's own route-time estimate is the best source we have
        # (it knows the actual road ahead; we don't), but it's reported
        # in game-seconds through a local time-scale that swings hard
        # between open road and towns. SmoothCountdown keeps the
        # on-screen number ticking steadily instead of hopping on every
        # poll, PaceCalibrator nudges the estimate to match how this
        # player actually drives relative to the speed limit, and the
        # two short EmaSmoothers just take the edge off ordinary sensor
        # jitter in distance/speed so digits don't flicker.
        self._nav_time_smoother = SmoothCountdown()
        self._nav_distance_smoother = EmaSmoother(half_life_s=1.0)
        self._speed_smoother = EmaSmoother(half_life_s=0.7)
        self._pace_calibrator = PaceCalibrator()
        self._rest_cycle_estimator = RestCycleEstimator()

        self._setup_window_flags()
        self._build_ui()
        self.apply_theme()
        self._apply_geometry()
        self._apply_interaction_mode()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start(self.settings.poll_interval_ms)

        self._hotkey_bridge = _HotkeyBridge()
        self._hotkey_bridge.triggered.connect(self.toggle_interactive_mode)
        self._hotkey_listener = GlobalHotkeyListener(
            self.settings.toggle_interactive_hotkey,
            on_trigger=lambda: self._hotkey_bridge.triggered.emit(),
        )
        self._hotkey_listener.start()

    def _setup_window_flags(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def _apply_geometry(self) -> None:
        self.move(self.settings.pos_x, self.settings.pos_y)
        self.setFixedWidth(int(self.settings.width * self.settings.scale))
        self.setWindowOpacity(self.settings.opacity)

    def _apply_interaction_mode(self) -> None:
        self._update_mode_badge()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, self.settings.click_through)
        self.show()
        hwnd = int(self.winId())
        _set_windows_click_through(hwnd, self.settings.click_through)
        self.settings_button.setVisible(not self.settings.click_through)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.root_panel = QFrame(self)
        self.root_panel.setObjectName("RootPanel")
        outer.addWidget(self.root_panel)

        panel_layout = QVBoxLayout(self.root_panel)
        panel_layout.setContentsMargins(14, 10, 14, 12)
        panel_layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("HAULHUD")
        title.setProperty("role", "titleBar")
        header.addWidget(title)
        header.addStretch()

        self.mode_badge = QFrame()
        self.mode_badge.setProperty("role", "modeBadge")
        badge_layout = QHBoxLayout(self.mode_badge)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        self.mode_badge_text = QLabel("")
        self.mode_badge_text.setProperty("role", "modeBadgeText")
        badge_layout.addWidget(self.mode_badge_text)
        header.addWidget(self.mode_badge)

        self.settings_button = QPushButton("\u2699")
        self.settings_button.setObjectName("SettingsButton")
        self.settings_button.setFixedSize(20, 20)
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setToolTip("Settings")
        self.settings_button.clicked.connect(self._open_settings_clicked)
        header.addWidget(self.settings_button)

        panel_layout.addLayout(header)
        panel_layout.addWidget(self._divider())

        field_defs = [
            ("delivery_countdown", "Delivery due in"),
            ("delivery_eta", "Delivery ETA"),
            ("nav_distance", "Route distance"),
            ("nav_time", "Route time"),
            ("nav_eta", "Arrival ETA"),
            ("rest_stop", "Break needed in"),
            ("breaks_needed", "Breaks needed"),
            ("truck_speed", "Speed"),
            ("speed_limit", "Speed limit"),
            ("cargo_damage", "Cargo damage"),
            ("cargo_info", "Cargo"),
            ("job_route", "Route"),
            ("income", "Expected income"),
        ]
        for key, label_text in field_defs:
            row, label, value = _field_row(label_text)
            self._rows[key] = (row, label, value)
            panel_layout.addWidget(row)
            row.setVisible(self.settings.fields_visible.get(key, True))

        self.status_label = QLabel("Waiting for game...")
        self.status_label.setProperty("role", "fieldLabel")
        panel_layout.addWidget(self.status_label)

    def _divider(self) -> QFrame:
        d = QFrame()
        d.setProperty("role", "divider")
        d.setFrameShape(QFrame.Shape.NoFrame)
        return d

    def apply_theme(self) -> None:
        self.setStyleSheet(build_qss(self.settings))

    def _update_mode_badge(self) -> None:
        if self.settings.click_through:
            self.mode_badge_text.setText("LOCKED")
            self.mode_badge.setStyleSheet("background-color: rgba(255,255,255,20);")
        else:
            self.mode_badge_text.setText("EDIT")
            self.mode_badge.setStyleSheet(f"background-color: {self.settings.accent_color};")

    def _open_settings_clicked(self) -> None:
        if self.on_open_settings is not None:
            self.on_open_settings()

    def toggle_interactive_mode(self) -> None:
        self.settings.click_through = not self.settings.click_through
        self.settings.save()
        self._apply_interaction_mode()
        self._update_mode_badge()

    def mousePressEvent(self, event) -> None:
        if not self.settings.click_through and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:
        if not self.settings.click_through and self._drag_offset is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(new_pos)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.settings.pos_x = self.x()
            self.settings.pos_y = self.y()
            self.settings.save()

    def _on_poll(self) -> None:
        frame = self.reader.read()
        info = derive(
            frame,
            rest_urgent_threshold_min_real=self.settings.rest_urgent_threshold_min,
            rest_countdown=self._rest_countdown,
            delivery_countdown=self._delivery_countdown,
            scale_estimator=self._nav_scale_estimator,
            nav_time_smoother=self._nav_time_smoother,
            nav_distance_smoother=self._nav_distance_smoother,
            speed_smoother=self._speed_smoother,
            pace_calibrator=self._pace_calibrator,
            rest_cycle_estimator=self._rest_cycle_estimator,
            break_real_minutes=self.settings.break_duration_min,
        )
        self._render(info)

    def _render(self, info: DerivedInfo) -> None:
        if self.settings.hide_when_game_not_running and not info.connected:
            self.setVisible(False)
            return
        if self.settings.hide_when_no_job and info.connected and not info.job_active:
            self.setVisible(False)
            return
        if not self.isVisible():
            self.setVisible(True)

        if not info.connected:
            self.status_label.setText("Game not running")
            self.status_label.setVisible(True)
        elif info.paused:
            self.status_label.setText("Game paused")
            self.status_label.setVisible(True)
        elif not info.job_active:
            self.status_label.setText("No active job")
            self.status_label.setVisible(True)
        else:
            self.status_label.setVisible(False)

        self._set_value("delivery_countdown", info.delivery_display)
        self._set_value("delivery_eta", info.delivery_eta_wallclock)
        self._set_value("nav_distance", info.nav_distance_display)
        self._set_value("nav_time", info.nav_time_display)
        self._set_value("nav_eta", info.nav_eta_wallclock)

        rest_status = status_for_rest(info.rest_urgent, info.rest_seconds_left_real)
        self._set_value("rest_stop", info.rest_display, status=rest_status)

        self._set_value("breaks_needed", info.breaks_display)

        self._set_value("truck_speed", f"{info.truck_speed_kmh:.0f} km/h")

        if info.nav_speed_limit_kmh is not None:
            self._set_value("speed_limit", f"{info.nav_speed_limit_kmh:.0f} km/h")
        else:
            self._set_value("speed_limit", "--")

        damage_status = status_for_damage(info.cargo_damage_pct)
        self._set_value("cargo_damage", f"{info.cargo_damage_pct:.1f}%", status=damage_status)

        cargo_text = info.cargo_name if info.cargo_name else "--"
        self._set_value("cargo_info", cargo_text)

        route_text = f"{info.source_city} -> {info.destination_city}" if info.destination_city else "--"
        self._set_value("job_route", route_text)

        converted_income = info.income * self.settings.income_currency_multiplier
        symbol, _ = INCOME_CURRENCIES.get(self.settings.income_currency_code, ("", 1.0))
        self._set_value("income", f"{symbol}{converted_income:,.0f}")

    def _set_value(self, key: str, text: str, status: str = "") -> None:
        if key not in self._rows:
            return
        _, _, value_label = self._rows[key]
        value_label.setText(text)
        current_status = value_label.property("status")
        if current_status != status:
            value_label.setProperty("status", status)
            value_label.style().unpolish(value_label)
            value_label.style().polish(value_label)

    def apply_settings_changed(self) -> None:
        self.apply_theme()
        self._apply_geometry()
        self._apply_interaction_mode()
        self._poll_timer.setInterval(self.settings.poll_interval_ms)
        for key, (row, _, _) in self._rows.items():
            row.setVisible(self.settings.fields_visible.get(key, True))
        self._hotkey_listener.update_hotkey(self.settings.toggle_interactive_hotkey)

    def closeEvent(self, event) -> None:
        self._hotkey_listener.stop()
        self.reader.close()
        super().closeEvent(event)

def run() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    settings = OverlaySettings.load()
    window = OverlayWindow(settings)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run()
