from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSlider,
    QDoubleSpinBox, QSpinBox, QLineEdit, QPushButton, QGroupBox, QFormLayout,
    QComboBox, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

from settings import OverlaySettings, DEFAULT_FIELDS_VISIBLE, INCOME_CURRENCIES
from theme import THEME_PRESETS
from version import __version__ as APP_VERSION

class SettingsDialog(QDialog):
    def __init__(self, settings: OverlaySettings, on_apply, on_check_updates=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("HaulHUD Settings")
        self.setMinimumWidth(380)
        self.settings = settings
        self.on_apply = on_apply
        # Callback into HaulHUDApp's existing update-check machinery
        # (UpdateCheckWorker / check_for_update) rather than duplicating
        # networking/threading here. Signature:
        #   on_check_updates(on_result, on_error) -> None
        # where on_result(info: UpdateInfo | None) and on_error(msg: str).
        self.on_check_updates = on_check_updates
        self._checking_updates = False
        self._closed = False

        layout = QVBoxLayout(self)

        appearance_box = QGroupBox("Appearance")
        form = QFormLayout(appearance_box)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEME_PRESETS.keys()) + ["custom"])
        self.theme_combo.setCurrentText(settings.theme)
        form.addRow("Theme", self.theme_combo)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(20, 100)
        self.opacity_slider.setValue(int(settings.opacity * 100))
        form.addRow("Opacity", self.opacity_slider)

        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.6, 2.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(settings.scale)
        form.addRow("UI scale", self.scale_spin)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        self.font_size_spin.setValue(settings.font_size)
        form.addRow("Font size", self.font_size_spin)

        layout.addWidget(appearance_box)

        behavior_box = QGroupBox("Behavior")
        bform = QFormLayout(behavior_box)

        self.hotkey_edit = QLineEdit(settings.toggle_interactive_hotkey)
        self.hotkey_edit.setPlaceholderText("e.g. f9 or ctrl+o")
        bform.addRow("Toggle edit-mode hotkey", self.hotkey_edit)

        self.click_through_check = QCheckBox("Start click-through (locked)")
        self.click_through_check.setChecked(settings.click_through)
        bform.addRow(self.click_through_check)

        self.rest_threshold_spin = QDoubleSpinBox()
        self.rest_threshold_spin.setRange(1, 60)
        self.rest_threshold_spin.setValue(settings.rest_urgent_threshold_min)
        bform.addRow("Break warning threshold (real min)", self.rest_threshold_spin)

        self.break_duration_spin = QDoubleSpinBox()
        self.break_duration_spin.setRange(0.0, 30.0)
        self.break_duration_spin.setSingleStep(0.5)
        self.break_duration_spin.setValue(settings.break_duration_min)
        self.break_duration_spin.setSuffix(" min")
        self.break_duration_spin.setToolTip(
            "Real minutes added to the route ETA for each mandatory rest "
            "the remaining trip will need -- covers the time to notice "
            "the warning, find a rest stop, and park, since the in-game "
            "sleep itself is a near-instant time skip rather than a real "
            "wait."
        )
        bform.addRow("Time cost per break", self.break_duration_spin)

        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setRange(50, 2000)
        self.poll_interval_spin.setSingleStep(50)
        self.poll_interval_spin.setValue(settings.poll_interval_ms)
        self.poll_interval_spin.setSuffix(" ms")
        self.poll_interval_spin.setToolTip(
            "How often the overlay re-reads live telemetry. Lower is more "
            "responsive but uses more CPU; it can't be fresher than "
            "however often the game plugin itself updates its data."
        )
        bform.addRow("Telemetry poll interval", self.poll_interval_spin)

        self.hide_no_job_check = QCheckBox("Hide overlay when no job active")
        self.hide_no_job_check.setChecked(settings.hide_when_no_job)
        bform.addRow(self.hide_no_job_check)

        self.hide_not_running_check = QCheckBox("Hide overlay when game not running")
        self.hide_not_running_check.setChecked(settings.hide_when_game_not_running)
        bform.addRow(self.hide_not_running_check)

        self.currency_combo = QComboBox()
        self.currency_combo.addItems(list(INCOME_CURRENCIES.keys()))
        if settings.income_currency_code in INCOME_CURRENCIES:
            self.currency_combo.setCurrentText(settings.income_currency_code)
        self.currency_combo.currentTextChanged.connect(self._on_currency_changed)
        bform.addRow("Income currency", self.currency_combo)

        self.currency_multiplier_spin = QDoubleSpinBox()
        self.currency_multiplier_spin.setRange(0.0001, 1000.0)
        self.currency_multiplier_spin.setDecimals(4)
        self.currency_multiplier_spin.setSingleStep(0.01)
        self.currency_multiplier_spin.setValue(settings.income_currency_multiplier)
        self.currency_multiplier_spin.setToolTip(
            "Rate applied to the game's EUR income figure (the SDK only "
            "ever reports EUR, regardless of the game's display currency "
            "setting). Prefilled from the game's own exchange rate table "
            "when you pick a currency above, but not fetched live -- edit "
            "it if the in-game rate has since changed."
        )
        bform.addRow("Income currency multiplier", self.currency_multiplier_spin)

        layout.addWidget(behavior_box)

        updates_box = QGroupBox("Updates")
        updates_layout = QVBoxLayout(updates_box)

        updates_row = QHBoxLayout()
        self.version_label = QLabel(f"Current version: v{APP_VERSION}")
        self.version_label.setProperty("role", "fieldLabel")
        updates_row.addWidget(self.version_label)
        updates_row.addStretch()

        self.check_updates_btn = QPushButton("Check for Updates")
        self.check_updates_btn.clicked.connect(self._check_for_updates_clicked)
        self.check_updates_btn.setEnabled(self.on_check_updates is not None)
        updates_row.addWidget(self.check_updates_btn)
        updates_layout.addLayout(updates_row)

        self.update_status_label = QLabel("")
        self.update_status_label.setWordWrap(True)
        updates_layout.addWidget(self.update_status_label)

        self._pending_release_url: str | None = None
        self.view_release_btn = QPushButton("View Release")
        self.view_release_btn.clicked.connect(self._open_pending_release)
        self.view_release_btn.setVisible(False)
        updates_layout.addWidget(self.view_release_btn)

        layout.addWidget(updates_box)

        fields_box = QGroupBox("Fields shown")
        fields_layout = QVBoxLayout(fields_box)
        self.field_checks: dict[str, QCheckBox] = {}
        labels = {
            "delivery_countdown": "Delivery due in",
            "delivery_eta": "Delivery ETA (real clock time)",
            "nav_distance": "Route distance remaining",
            "nav_time": "Route time remaining",
            "nav_eta": "Arrival ETA (real clock time)",
            "rest_stop": "Break needed in",
            "breaks_needed": "Breaks needed on route",
            "truck_speed": "Truck speed",
            "speed_limit": "Speed limit (current road)",
            "cargo_damage": "Cargo damage %",
            "cargo_info": "Cargo name",
            "job_route": "Source -> destination",
            "income": "Expected income",
        }
        for key in DEFAULT_FIELDS_VISIBLE.keys():
            cb = QCheckBox(labels.get(key, key))
            cb.setChecked(settings.fields_visible.get(key, True))
            self.field_checks[key] = cb
            fields_layout.addWidget(cb)
        layout.addWidget(fields_box)

        button_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addStretch()
        button_row.addWidget(cancel_btn)
        button_row.addWidget(save_btn)
        layout.addLayout(button_row)

    def _check_for_updates_clicked(self) -> None:
        if self.on_check_updates is None or self._checking_updates:
            return
        self._checking_updates = True
        self.check_updates_btn.setEnabled(False)
        self.check_updates_btn.setText("Checking...")
        self.update_status_label.setText("")
        self.on_check_updates(self._on_update_result, self._on_update_error)

    def _reset_check_button(self) -> None:
        self._checking_updates = False
        self.check_updates_btn.setEnabled(True)
        self.check_updates_btn.setText("Check for Updates")

    def _on_update_result(self, info) -> None:
        if self._closed:
            return
        self._reset_check_button()
        if info is None:
            self.update_status_label.setText(f"You're up to date (v{APP_VERSION}).")
            self.view_release_btn.setVisible(False)
            self._pending_release_url = None
            return
        self.update_status_label.setText(
            f"v{info.latest_version} is available (you have v{APP_VERSION})."
        )
        self._pending_release_url = info.release_url
        self.view_release_btn.setVisible(True)

    def _open_pending_release(self) -> None:
        if not self._pending_release_url:
            return
        QDesktopServices.openUrl(QUrl(self._pending_release_url))

    def _on_update_error(self, message: str) -> None:
        if self._closed:
            return
        self._reset_check_button()
        self.update_status_label.setText(f"Update check failed: {message}")
        self.view_release_btn.setVisible(False)
        self._pending_release_url = None

    def _on_currency_changed(self, code: str) -> None:
        if code in INCOME_CURRENCIES:
            _, rate = INCOME_CURRENCIES[code]
            self.currency_multiplier_spin.setValue(rate)

    def _save(self) -> None:
        s = self.settings
        s.theme = self.theme_combo.currentText()
        if s.theme in THEME_PRESETS:
            preset = THEME_PRESETS[s.theme]
            s.background_color = preset["background_color"]
            s.text_color = preset["text_color"]
            s.accent_color = preset["accent_color"]
        s.opacity = self.opacity_slider.value() / 100.0
        s.scale = self.scale_spin.value()
        s.font_size = self.font_size_spin.value()
        s.toggle_interactive_hotkey = self.hotkey_edit.text().strip() or "f9"
        s.click_through = self.click_through_check.isChecked()
        s.rest_urgent_threshold_min = self.rest_threshold_spin.value()
        s.break_duration_min = self.break_duration_spin.value()
        s.poll_interval_ms = self.poll_interval_spin.value()
        s.hide_when_no_job = self.hide_no_job_check.isChecked()
        s.hide_when_game_not_running = self.hide_not_running_check.isChecked()
        s.income_currency_code = self.currency_combo.currentText()
        s.income_currency_multiplier = self.currency_multiplier_spin.value()
        for key, cb in self.field_checks.items():
            s.fields_visible[key] = cb.isChecked()

        s.save()
        self.on_apply()
        self.accept()

    def reject(self) -> None:
        self._closed = True
        super().reject()

    def accept(self) -> None:
        self._closed = True
        super().accept()
