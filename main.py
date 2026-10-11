"""QuestScope desktop entry point."""
from __future__ import annotations

import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QMainWindow, QMessageBox, QPushButton, QStackedWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from questscope.adb import AdbClient, AdbError, Device

STYLE = """
QWidget { background: #101318; color: #e7eaf0; font-family: 'Segoe UI'; font-size: 10pt; }
QMainWindow { background: #101318; }
QFrame#Sidebar { background: #171b22; border: 1px solid #282e39; border-radius: 12px; }
QLabel#Brand { font-size: 20pt; font-weight: 700; color: #f5f7fb; }
QLabel#Muted { color: #9aa5b5; }
QLabel#Metric { font-size: 19pt; font-weight: 650; }
QFrame#Panel { background: #171b22; border: 1px solid #282e39; border-radius: 12px; }
QPushButton { background: #242b37; border: 1px solid #343d4b; border-radius: 8px; padding: 9px 13px; }
QPushButton:hover { background: #303949; }
QPushButton#Primary { background: #8b7bff; color: #101018; font-weight: 700; border: none; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 12px; border-radius: 7px; }
QListWidget::item:selected { background: #2b3044; color: #c5bcff; }
QTextEdit { background: #0c0f13; border: 1px solid #2b313b; border-radius: 8px; padding: 8px; font-family: Consolas; }
"""


def panel(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    heading = QLabel(title)
    heading.setStyleSheet("font-weight: 650; font-size: 11pt;")
    layout.addWidget(heading)
    return frame, layout


class QuestScopeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QuestScope")
        self.resize(1100, 720)
        self.adb = AdbClient()
        self.devices: list[Device] = []
        self.selected_serial: str | None = None
        self.log_process = None

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(16)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 20, 14, 14)
        brand = QLabel("QuestScope")
        brand.setObjectName("Brand")
        side.addWidget(brand)
        subtitle = QLabel("QUEST DIAGNOSTICS")
        subtitle.setObjectName("Muted")
        side.addWidget(subtitle)
        side.addSpacing(22)
        self.navigation = QListWidget()
        self.navigation.addItems(["Dashboard", "Live logs"])
        self.navigation.setCurrentRow(0)
        side.addWidget(self.navigation)
        side.addStretch()
        self.connection_label = QLabel("●  Checking ADB…")
        self.connection_label.setObjectName("Muted")
        self.connection_label.setWordWrap(True)
        side.addWidget(self.connection_label)

        content = QVBoxLayout()
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Device overview")
        title.setStyleSheet("font-size: 22pt; font-weight: 700;")
        self.subtitle = QLabel("Connect a Quest headset to get started.")
        self.subtitle.setObjectName("Muted")
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("Primary")
        self.refresh_button.clicked.connect(self.refresh_devices)
        header.addWidget(self.refresh_button)
        content.addLayout(header)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_dashboard())
        self.pages.addWidget(self.build_logs())
        content.addWidget(self.pages, 1)
        root_layout.addWidget(sidebar)
        root_layout.addLayout(content, 1)
        self.setCentralWidget(root)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_devices)
        self.timer.start(5000)
        self.refresh_devices()

    def build_dashboard(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        metrics = QGridLayout()
        metrics.setSpacing(12)
        self.device_value = QLabel("Not connected")
        self.android_value = QLabel("—")
        self.battery_value = QLabel("—")
        self.build_value = QLabel("—")
        for col, (name, value) in enumerate([
            ("HEADSET", self.device_value),
            ("ANDROID", self.android_value),
            ("BATTERY", self.battery_value),
            ("BUILD", self.build_value),
        ]):
            frame, box = panel(name)
            value.setObjectName("Metric")
            value.setWordWrap(True)
            box.addSpacing(10)
            box.addWidget(value)
            box.addStretch()
            metrics.addWidget(frame, 0, col)
        layout.addLayout(metrics)

        self.device_panel, device_box = panel("Connection status")
        self.status_detail = QLabel("Waiting for a device. Connect by USB, enable Developer Mode and USB debugging, then accept the authorization prompt in the headset.")
        self.status_detail.setObjectName("Muted")
        self.status_detail.setWordWrap(True)
        device_box.addWidget(self.status_detail)
        device_box.addStretch()
        layout.addWidget(self.device_panel)
        self.info_panel, info_box = panel("Device information")
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(190)
        self.info_text.setPlainText("Device properties will appear here when a headset is connected.")
        info_box.addWidget(self.info_text)
        layout.addWidget(self.info_panel)
        layout.addStretch()
        return page

    def build_logs(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        frame, box = panel("Logcat")
        description = QLabel("Capture Android system logs from the selected authorized device.")
        description.setObjectName("Muted")
        box.addWidget(description)
        actions = QHBoxLayout()
        self.logs_button = QPushButton("Capture recent logs")
        self.logs_button.clicked.connect(self.capture_logs)
        actions.addWidget(self.logs_button)
        actions.addStretch()
        box.addLayout(actions)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        box.addWidget(self.log_text, 1)
        layout.addWidget(frame, 1)
        return page

    def refresh_devices(self) -> None:
        if not self.adb.available:
            self.connection_label.setText("●  ADB not found")
            self.subtitle.setText("Install Android Platform Tools and add adb.exe to PATH.")
            self.status_detail.setText("QuestScope could not find ADB. Install Android Platform Tools, add its folder to PATH, and restart QuestScope.")
            self.refresh_button.setEnabled(False)
            return
        self.refresh_button.setEnabled(True)
        try:
            self.devices = self.adb.devices()
        except AdbError as exc:
            self.connection_label.setText("●  ADB error")
            self.status_detail.setText(str(exc))
            return
        ready = next((device for device in self.devices if device.ready), None)
        if not ready:
            self.selected_serial = None
            unauthorized = any(device.state == "unauthorized" for device in self.devices)
            self.connection_label.setText("●  Needs authorization" if unauthorized else "●  No headset connected")
            self.device_value.setText("Unauthorized" if unauthorized else "Not connected")
            self.android_value.setText("—")
            self.battery_value.setText("—")
            self.build_value.setText("—")
            self.info_text.setPlainText("No authorized headset is available.")
            self.status_detail.setText(
                "Unlock the headset and accept the USB debugging prompt, then press Refresh."
                if unauthorized else
                "Connect the headset by USB, enable USB debugging, and accept the authorization prompt. Wireless ADB can be added in a later milestone."
            )
            self.subtitle.setText("Waiting for an authorized Quest device.")
            return
        self.selected_serial = ready.serial
        self.connection_label.setText("●  Quest connected")
        self.device_value.setText(ready.serial)
        self.status_detail.setText(f"Connected and authorized. Serial: {ready.serial}\n{ready.details}")
        props = self.adb.properties(ready.serial)
        self.android_value.setText(props.get("Android version", "—"))
        self.build_value.setText(props.get("Build", "—"))
        try:
            self.battery_value.setText(self.adb.battery(ready.serial))
        except AdbError:
            self.battery_value.setText("Unavailable")
        self.info_text.setPlainText("\n".join(f"{key}: {value}" for key, value in props.items()))
        self.subtitle.setText(f"Connected to {props.get('Model', ready.serial)}")

    def capture_logs(self) -> None:
        if not self.selected_serial:
            QMessageBox.information(self, "No headset", "Connect and authorize a Quest headset first.")
            return
        self.logs_button.setEnabled(False)
        self.log_text.setPlainText("Capturing recent logs…")
        QApplication.processEvents()
        try:
            output = self.adb.run(["-s", self.selected_serial, "logcat", "-d", "-t", "500"], timeout=20)
            self.log_text.setPlainText(output or "No log entries returned.")
        except AdbError as exc:
            self.log_text.setPlainText(f"Could not capture logs:\n{exc}")
        finally:
            self.logs_button.setEnabled(True)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = QuestScopeWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
