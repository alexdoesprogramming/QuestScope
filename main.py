"""QuestScope: live Meta Quest monitoring dashboard."""
from __future__ import annotations

import sys
from collections import deque

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QMainWindow, QMessageBox, QPushButton, QSizePolicy, QStackedWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from questscope.adb import AdbClient, AdbError, Device
from questscope.metrics import cpu_percent, parse_battery, parse_cpu_stat, parse_meminfo

STYLE = """
QWidget { background: #0b0e14; color: #e8ebf4; font-family: 'Segoe UI'; font-size: 10pt; }
QMainWindow { background: #0b0e14; }
QFrame#Sidebar { background: #111620; border: 1px solid #222b3a; border-radius: 16px; }
QLabel#Brand { font-size: 21pt; font-weight: 800; color: #f6f7ff; }
QLabel#Eyebrow { color: #929cb1; font-size: 8pt; font-weight: 700; letter-spacing: 2px; }
QLabel#Muted { color: #929cb1; }
QLabel#Metric { font-size: 22pt; font-weight: 750; }
QFrame#Panel { background: #111620; border: 1px solid #222b3a; border-radius: 14px; }
QPushButton { background: #1b2432; border: 1px solid #2a3547; border-radius: 9px; padding: 10px 14px; font-weight: 600; }
QPushButton:hover { background: #273449; border-color: #7568ff; }
QPushButton#Primary { background: #a99cff; color: #11101b; font-weight: 800; border: none; }
QPushButton#Primary:hover { background: #bcb2ff; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 13px 12px; border-radius: 9px; color: #aeb8ca; }
QListWidget::item:selected { background: #282541; color: #d1c9ff; }
QTextEdit { background: #090c11; border: 1px solid #273143; border-radius: 10px; padding: 10px; font-family: Consolas; selection-background-color: #6257b8; }
QScrollBar:vertical { background: #10151e; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #303b4d; border-radius: 5px; min-height: 24px; }
"""

def make_panel(title: str, eyebrow: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(9)
    if eyebrow:
        small = QLabel(eyebrow.upper())
        small.setObjectName("Eyebrow")
        layout.addWidget(small)
    heading = QLabel(title)
    heading.setStyleSheet("font-weight: 700; font-size: 11pt;")
    layout.addWidget(heading)
    return frame, layout


class MetricChart(QWidget):
    """Small dependency-free rolling line chart painted with QPainter."""

    def __init__(self, title: str, color: str, suffix: str = "%", scale_max: float = 100, parent=None):
        super().__init__(parent)
        self.title = title
        self.color = QColor(color)
        self.suffix = suffix
        self.scale_max = scale_max
        self.values: deque[float | None] = deque(maxlen=30)
        self.current: float | None = None
        self.setMinimumHeight(175)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def add_value(self, value: float | None) -> None:
        self.current = value
        self.values.append(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.rect().adjusted(4, 8, -4, -4)
        left, top, right, bottom = area.left() + 26, area.top() + 12, area.right() - 5, area.bottom() - 22
        width, height = max(1, right - left), max(1, bottom - top)
        painter.setPen(QColor("#293244"))
        for fraction in (0, 0.25, 0.5, 0.75, 1):
            y = bottom - int(height * fraction)
            painter.drawLine(left, y, right, y)
        painter.setPen(QColor("#78849a"))
        painter.drawText(0, top + 5, 22, 16, Qt.AlignmentFlag.AlignRight, str(int(self.scale_max)))
        painter.drawText(0, bottom, 22, 16, Qt.AlignmentFlag.AlignRight, "0")
        if not any(v is not None for v in self.values):
            painter.setPen(QColor("#7f8ba0"))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "Waiting for device telemetry…")
            return
        points = list(self.values)
        count = len(points)
        path = QPainterPath()
        started = False
        for index, value in enumerate(points):
            if value is None:
                started = False
                continue
            x = left + (width * index / max(1, count - 1))
            y = bottom - (height * max(0, min(self.scale_max, value)) / self.scale_max)
            if not started:
                path.moveTo(x, y)
                started = True
            else:
                path.lineTo(x, y)
        pen = QPen(self.color, 2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        if points and points[-1] is not None:
            x = right
            y = bottom - (height * max(0, min(self.scale_max, points[-1])) / self.scale_max)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.color)
            painter.drawEllipse(int(x) - 4, int(y) - 4, 8, 8)
        painter.setPen(QColor("#78849a"))
        painter.drawText(left, area.bottom() + 14, "90s history")
        painter.drawText(right - 34, area.bottom() + 14, "LIVE")


class PollWorker(QThread):
    """Run ADB away from the GUI thread; a slow headset cannot freeze the UI."""
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, adb: AdbClient, previous_cpu: tuple[int, int] | None):
        super().__init__()
        self.adb = adb
        self.previous_cpu = previous_cpu

    def run(self):
        try:
            devices = self.adb.devices()
            device = next((item for item in devices if item.ready), None)
            result = {"devices": devices, "device": device, "metrics": None, "properties": {}}
            if device is None:
                result["unauthorized"] = any(item.state == "unauthorized" for item in devices)
                self.completed.emit(result)
                return
            serial = device.serial
            result["properties"] = self.adb.properties(serial)
            metrics = {"cpu": None, "ram": None, "battery": None, "temperature": None}
            try:
                counters = parse_cpu_stat(self.adb.shell(serial, "cat", "/proc/stat", timeout=4))
                if counters is not None:
                    metrics["cpu"] = cpu_percent(self.previous_cpu, counters)
                    result["cpu_counters"] = counters
            except (AdbError, ValueError):
                pass
            try:
                memory = parse_meminfo(self.adb.shell(serial, "cat", "/proc/meminfo", timeout=4))
                if memory:
                    metrics["ram"] = memory.get("used_percent")
                    result["memory"] = memory
            except (AdbError, ValueError):
                pass
            try:
                battery = parse_battery(self.adb.shell(serial, "dumpsys", "battery", timeout=5))
                metrics["battery"] = battery.get("level")
                metrics["temperature"] = battery.get("temperature_c")
            except (AdbError, ValueError):
                pass
            result["metrics"] = metrics
            self.completed.emit(result)
        except AdbError as exc:
            self.failed.emit(str(exc))


class LogWorker(QThread):
    completed = Signal(tuple)

    def __init__(self, adb: AdbClient, serial: str):
        super().__init__()
        self.adb = adb
        self.serial = serial

    def run(self):
        try:
            output = self.adb.run(["-s", self.serial, "logcat", "-d", "-t", "500"], timeout=25)
            self.completed.emit((True, output or "No log entries returned."))
        except AdbError as exc:
            self.completed.emit((False, str(exc)))


class QuestScopeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QuestScope | Quest telemetry")
        self.resize(1280, 820)
        self.setMinimumSize(1000, 680)
        self.adb = AdbClient()
        self.devices: list[Device] = []
        self.selected_serial: str | None = None
        self.cpu_previous: tuple[int, int] | None = None
        self.worker: PollWorker | None = None
        self.log_worker: LogWorker | None = None

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(16)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(218)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(15, 20, 15, 15)
        brand = QLabel("QuestScope")
        brand.setObjectName("Brand")
        side.addWidget(brand)
        eyebrow = QLabel("QUEST PERFORMANCE SUITE")
        eyebrow.setObjectName("Eyebrow")
        side.addWidget(eyebrow)
        side.addSpacing(18)
        self.navigation = QListWidget()
        self.navigation.addItems(["◈  Overview", "≋  Logcat"])
        self.navigation.setCurrentRow(0)
        side.addWidget(self.navigation, 1)
        footer = QFrame()
        footer.setStyleSheet("background:#0b0e14; border:1px solid #273143; border-radius:10px;")
        foot_layout = QVBoxLayout(footer)
        foot_layout.setContentsMargins(12, 12, 12, 12)
        self.connection_label = QLabel("●  Initializing ADB")
        self.connection_label.setStyleSheet("font-weight:700; color:#b5aaff;")
        self.connection_label.setWordWrap(True)
        foot_layout.addWidget(self.connection_label)
        self.poll_label = QLabel("Polling every 3 seconds")
        self.poll_label.setObjectName("Muted")
        foot_layout.addWidget(self.poll_label)
        side.addWidget(footer)

        content = QVBoxLayout()
        content.setSpacing(14)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Live telemetry")
        title.setStyleSheet("font-size:25pt; font-weight:800;")
        self.subtitle = QLabel("Connect your Quest to start the telemetry stream.")
        self.subtitle.setObjectName("Muted")
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.refresh_button = QPushButton("↻  Refresh now")
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
        self.timer.start(3000)
        self.refresh_devices()

    def build_dashboard(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        cards = QGridLayout()
        cards.setSpacing(12)
        self.device_value = QLabel("Not connected")
        self.android_value = QLabel("—")
        self.battery_value = QLabel("—")
        self.temp_value = QLabel("—")
        for col, (name, value, sub) in enumerate([
            ("CONNECTED HEADSET", self.device_value, "DEVICE"),
            ("ANDROID VERSION", self.android_value, "PLATFORM"),
            ("BATTERY LEVEL", self.battery_value, "POWER"),
            ("BATTERY TEMP", self.temp_value, "THERMAL"),
        ]):
            frame, box = make_panel(name, sub)
            value.setObjectName("Metric")
            value.setWordWrap(True)
            box.addSpacing(4)
            box.addWidget(value)
            box.addStretch()
            cards.addWidget(frame, 0, col)
        layout.addLayout(cards)

        charts = QGridLayout()
        charts.setSpacing(12)
        self.cpu_chart = MetricChart("CPU activity", "#aa9cff")
        self.ram_chart = MetricChart("Memory pressure", "#52d6c7")
        self.battery_chart = MetricChart("Battery history", "#8fda7b")
        self.temp_chart = MetricChart("Battery temperature", "#ffb86b", "°C", scale_max=60)
        self.cpu_value = QLabel("—")
        self.ram_value = QLabel("—")
        self.battery_chart_value = QLabel("—")
        self.temp_chart_value = QLabel("—")
        specs = [
            (self.cpu_chart, self.cpu_value, "CPU LOAD", "Sampled from /proc/stat", 0, 0),
            (self.ram_chart, self.ram_value, "MEMORY", "Used RAM estimate", 0, 1),
            (self.battery_chart, self.battery_chart_value, "BATTERY", "Reported by Android", 1, 0),
            (self.temp_chart, self.temp_chart_value, "TEMPERATURE", "Battery sensor, if exposed", 1, 1),
        ]
        for chart, value_label, label, note, row, col in specs:
            frame, box = make_panel(label, "LIVE CHART")
            top = QHBoxLayout()
            value_label.setStyleSheet(f"font-size:17pt; font-weight:800; color:{chart.color.name()};")
            top.addWidget(value_label)
            top.addStretch()
            note_label = QLabel(note)
            note_label.setObjectName("Muted")
            note_label.setStyleSheet("font-size:8pt;")
            top.addWidget(note_label)
            box.addLayout(top)
            box.addWidget(chart, 1)
            charts.addWidget(frame, row, col)
        layout.addLayout(charts, 1)
        self.status_panel, status_box = make_panel("Device status", "CONNECTION")
        self.status_detail = QLabel("Waiting for an authorized Quest. Connect USB, enable Developer Mode and USB debugging, and accept the prompt inside the headset.")
        self.status_detail.setObjectName("Muted")
        self.status_detail.setWordWrap(True)
        status_box.addWidget(self.status_detail)
        layout.addWidget(self.status_panel)
        return page

    def build_logs(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        frame, box = make_panel("Android logcat", "DIAGNOSTICS")
        description = QLabel("Capture the latest 500 log entries from the selected authorized headset.")
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
            self.connection_label.setStyleSheet("font-weight:700; color:#ff8585;")
            self.subtitle.setText("Install Android Platform Tools and add adb.exe to PATH.")
            self.status_detail.setText("QuestScope could not find ADB. Add the folder containing adb.exe to PATH, then restart QuestScope.")
            self.refresh_button.setEnabled(False)
            return
        self.refresh_button.setEnabled(True)
        if self.worker is not None and self.worker.isRunning():
            return
        self.refresh_button.setText("◌  Sampling…")
        self.worker = PollWorker(self.adb, self.cpu_previous)
        self.worker.completed.connect(self.apply_snapshot)
        self.worker.failed.connect(self.poll_failed)
        self.worker.finished.connect(self.poll_finished)
        self.worker.start()

    def poll_finished(self) -> None:
        self.refresh_button.setText("↻  Refresh now")

    def poll_failed(self, message: str) -> None:
        self.connection_label.setText("●  ADB error")
        self.connection_label.setStyleSheet("font-weight:700; color:#ff8585;")
        self.status_detail.setText(message)

    def apply_snapshot(self, snapshot: dict) -> None:
        self.devices = snapshot.get("devices", [])
        device = snapshot.get("device")
        if not device:
            self.selected_serial = None
            self.cpu_previous = None
            unauthorized = snapshot.get("unauthorized", False)
            self.connection_label.setText("●  Needs authorization" if unauthorized else "●  No headset connected")
            self.connection_label.setStyleSheet("font-weight:700; color:#ffbd72;" if unauthorized else "font-weight:700; color:#929cb1;")
            self.device_value.setText("Unauthorized" if unauthorized else "Not connected")
            self.android_value.setText("—")
            self.battery_value.setText("—")
            self.temp_value.setText("—")
            self.subtitle.setText("Waiting for an authorized Quest device.")
            self.status_detail.setText("Unlock the headset and accept the USB debugging prompt, then refresh." if unauthorized else "No authorized device found. Connect by USB (or configure wireless ADB), enable USB debugging, and accept the prompt.")
            for chart in (self.cpu_chart, self.ram_chart, self.battery_chart, self.temp_chart):
                chart.add_value(None)
            for label in (self.cpu_value, self.ram_value, self.battery_chart_value, self.temp_chart_value):
                label.setText("—")
            return

        self.selected_serial = device.serial
        self.connection_label.setText("●  Quest connected")
        self.connection_label.setStyleSheet("font-weight:700; color:#73e0b0;")
        props = snapshot.get("properties", {})
        model = props.get("Model", device.serial)
        self.device_value.setText(model)
        self.android_value.setText(props.get("Android version", "—"))
        metrics = snapshot.get("metrics") or {}
        battery, temperature = metrics.get("battery"), metrics.get("temperature")
        ram, cpu = metrics.get("ram"), metrics.get("cpu")
        self.battery_value.setText("—" if battery is None else f"{battery:.0f}%")
        self.temp_value.setText("—" if temperature is None else f"{temperature:.1f}°C")
        self.cpu_chart.add_value(cpu)
        self.ram_chart.add_value(ram)
        self.battery_chart.add_value(battery)
        self.temp_chart.add_value(temperature)
        self.cpu_value.setText("—" if cpu is None else f"{cpu:.0f}%")
        self.ram_value.setText("—" if ram is None else f"{ram:.0f}%")
        self.battery_chart_value.setText("—" if battery is None else f"{battery:.0f}%")
        self.temp_chart_value.setText("—" if temperature is None else f"{temperature:.1f}°C")
        self.subtitle.setText(f"{model}  •  {props.get('Android version', 'Android version unavailable')}  •  Sampling every 3 seconds")
        memory = snapshot.get("memory", {})
        mem_detail = f"  |  RAM {memory.get('used_mb', '—')} / {memory.get('total_mb', '—')} MB" if memory else ""
        self.status_detail.setText(f"Authorized ADB connection • Serial {device.serial}{mem_detail}")
        if snapshot.get("cpu_counters") is not None:
            self.cpu_previous = snapshot["cpu_counters"]

    def capture_logs(self) -> None:
        if not self.selected_serial:
            QMessageBox.information(self, "No headset", "Connect and authorize a Quest headset first.")
            return
        if self.log_worker is not None and self.log_worker.isRunning():
            return
        self.logs_button.setEnabled(False)
        self.logs_button.setText("Capturing…")
        self.log_worker = LogWorker(self.adb, self.selected_serial)
        self.log_worker.completed.connect(self.show_logs)
        self.log_worker.finished.connect(lambda: self.logs_button.setEnabled(True))
        self.log_worker.finished.connect(lambda: self.logs_button.setText("Capture recent logs"))
        self.log_worker.start()

    def show_logs(self, result: tuple[bool, str]) -> None:
        ok, output = result
        self.log_text.setPlainText(output if ok else f"Could not capture logs:\n{output}")


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = QuestScopeWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
