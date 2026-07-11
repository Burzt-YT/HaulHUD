from __future__ import annotations

import sys
import os

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt

from settings import OverlaySettings
from overlay_window import OverlayWindow
from settings_dialog import SettingsDialog

def _make_tray_icon(accent_hex: str) -> QIcon:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#12161B"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 14, 14)
    painter.setPen(QColor(accent_hex))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pen = painter.pen()
    pen.setWidth(5)
    painter.setPen(pen)
    painter.drawArc(12, 12, size - 24, size - 24, 45 * 16, 270 * 16)
    painter.end()
    return QIcon(pixmap)

class HaulHUDApp:
    def __init__(self) -> None:
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.settings = OverlaySettings.load()
        self.window = OverlayWindow(self.settings, on_open_settings=self._open_settings)

        self.tray = QSystemTrayIcon(_make_tray_icon(self.settings.accent_color))
        self.tray.setToolTip("HaulHUD")
        self._build_tray_menu()
        self.tray.show()

    def _build_tray_menu(self) -> None:
        menu = QMenu()

        self.toggle_action = QAction("Unlock overlay (edit mode)")
        self.toggle_action.triggered.connect(self._toggle_from_tray)
        menu.addAction(self.toggle_action)
        self._sync_toggle_label()

        settings_action = QAction("Settings...")
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("Quit HaulHUD")
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)

    def _sync_toggle_label(self) -> None:
        if self.settings.click_through:
            self.toggle_action.setText("Unlock overlay (edit mode)")
        else:
            self.toggle_action.setText("Lock overlay (click-through)")

    def _toggle_from_tray(self) -> None:
        self.window.toggle_interactive_mode()
        self._sync_toggle_label()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._open_settings()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, on_apply=self._on_settings_applied)
        dialog.exec()

    def _on_settings_applied(self) -> None:
        self.window.apply_settings_changed()
        self._sync_toggle_label()

    def _quit(self) -> None:
        self.window.close()
        self.tray.hide()
        self.app.quit()

    def run(self) -> int:
        self.window.show()
        return self.app.exec()

def main() -> None:
    if not sys.platform.startswith("win"):
        print(
            "WARNING: HaulHUD's click-through and global-hotkey features "
            "are Windows-only (matches ETS2's own platform for the SDK "
            "plugin). The UI will still run for development/preview, but "
            "click-through and the hotkey will be no-ops."
        )
    app = HaulHUDApp()
    sys.exit(app.run())

if __name__ == "__main__":
    main()
