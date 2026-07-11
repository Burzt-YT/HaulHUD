from __future__ import annotations

import sys
import os

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QDesktopServices
from PySide6.QtCore import Qt, QThread, QUrl, Signal

from settings import OverlaySettings
from overlay_window import OverlayWindow
from settings_dialog import SettingsDialog
from update_checker import UpdateCheckError, UpdateInfo, check_for_update
from version import __version__ as APP_VERSION

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

class UpdateCheckWorker(QThread):
    checked_ok = Signal(object)  # UpdateInfo | None
    failed = Signal(str)

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self.current_version = current_version

    def run(self) -> None:
        try:
            info = check_for_update(self.current_version)
            self.checked_ok.emit(info)
        except UpdateCheckError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 - surface unexpected errors too
            self.failed.emit(f"Unexpected error: {e}")

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

        self.update_check_worker: UpdateCheckWorker | None = None
        self._dialog_update_worker: UpdateCheckWorker | None = None
        self._update_check_is_silent = True
        self._pending_update_info: UpdateInfo | None = None
        self.tray.messageClicked.connect(self._on_tray_message_clicked)

        # Silent check on launch: a balloon notification only appears if an
        # update is actually found -- a flaky connection or a rate-limited
        # GitHub API shouldn't interrupt startup with anything. The tray
        # menu's "Check for Updates..." runs the same check non-silently
        # for an explicit result either way.
        self._check_for_updates(silent=True)

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

        check_updates_action = QAction("Check for Updates...")
        check_updates_action.triggered.connect(lambda: self._check_for_updates(silent=False))
        menu.addAction(check_updates_action)

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
        dialog = SettingsDialog(
            self.settings,
            on_apply=self._on_settings_applied,
            on_check_updates=self._check_for_updates_for_dialog,
        )
        dialog.exec()

    def _check_for_updates_for_dialog(self, on_result, on_error) -> None:
        # Runs on its own worker instance so the Settings dialog's button
        # stays responsive regardless of whether a tray-triggered check
        # (silent startup check or "Check for Updates..." in the tray
        # menu) happens to be in flight at the same time -- that path's
        # single-worker "already running" guard is specifically about
        # not duplicating tray balloons/dialogs, not about this button.
        worker = UpdateCheckWorker(APP_VERSION)
        # Keep a reference so it isn't garbage-collected mid-check.
        self._dialog_update_worker = worker
        worker.checked_ok.connect(on_result)
        worker.failed.connect(on_error)
        worker.start()

    def _on_settings_applied(self) -> None:
        self.window.apply_settings_changed()
        self._sync_toggle_label()

    def _check_for_updates(self, silent: bool) -> None:
        if self.update_check_worker is not None and self.update_check_worker.isRunning():
            return
        self._update_check_is_silent = silent
        self.update_check_worker = UpdateCheckWorker(APP_VERSION)
        self.update_check_worker.checked_ok.connect(self._on_update_check_ok)
        self.update_check_worker.failed.connect(self._on_update_check_failed)
        self.update_check_worker.start()

    def _on_update_check_ok(self, info: object) -> None:
        if info is not None:
            self._pending_update_info = info
            if self._update_check_is_silent:
                # Balloon notification rather than a blocking dialog --
                # this can fire during a live drive with the game running,
                # so it needs to be glanceable and dismissible rather than
                # stealing focus. Clicking it opens the release page (see
                # _on_tray_message_clicked); "Check for Updates..." in the
                # tray menu re-shows this with a direct link either way.
                self.tray.showMessage(
                    "HaulHUD update available",
                    f"v{info.latest_version} is available (you have v{APP_VERSION}). "
                    "Click here, or use Check for Updates in the tray menu, to view it.",
                    QSystemTrayIcon.MessageIcon.Information,
                    8000,
                )
            else:
                box = QMessageBox()
                box.setWindowTitle("Update available")
                box.setIcon(QMessageBox.Icon.Information)
                box.setText(
                    f"A new version is available: v{info.latest_version}\n"
                    f"You have: v{APP_VERSION}"
                )
                view_btn = box.addButton("View Release", QMessageBox.ButtonRole.AcceptRole)
                box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
                box.exec()
                if box.clickedButton() is view_btn:
                    QDesktopServices.openUrl(QUrl(info.release_url))
        elif not self._update_check_is_silent:
            QMessageBox.information(
                None,
                "No updates available",
                f"You're running the latest version (v{APP_VERSION}).",
            )

    def _on_update_check_failed(self, message: str) -> None:
        # A silent startup check failing (no network, GitHub rate limit,
        # etc.) shouldn't interrupt or notify at all -- only a manually
        # triggered "Check for Updates..." surfaces the failure directly.
        if not self._update_check_is_silent:
            QMessageBox.warning(None, "Update check failed", message)

    def _on_tray_message_clicked(self) -> None:
        if self._pending_update_info is not None:
            QDesktopServices.openUrl(QUrl(self._pending_update_info.release_url))

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
