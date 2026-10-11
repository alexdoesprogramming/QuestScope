"""QuestScope: a live, root-free Meta Quest diagnostics suite."""
from __future__ import annotations
import csv
import re
import subprocess
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QRegularExpression, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)
from questscope.adb import AdbClient, AdbError
from questscope.metrics import cpu_percent, parse_battery, parse_cpu_stat, parse_meminfo
from questscope.processes import parse_process_list, parse_total_pss_kb

APP_VERSION = "0.4.0"
STYLE = """
QWidget { background:#0a0d13; color:#e8ebf5; font-family:'Segoe UI'; font-size:10pt; }
QMainWindow { background:#0a0d13; }
QFrame#Sidebar { background:#10151f; border:1px solid #252d3b; border-radius:16px; }
QLabel#Brand { font-size:22pt; font-weight:850; color:#f8f7ff; }
QLabel#Eyebrow { color:#8d99ae; font-size:8pt; font-weight:800; letter-spacing:1.5px; }
QLabel#Muted { color:#8d99ae; }
QLabel#Metric { font-size:21pt; font-weight:800; }
QFrame#Panel { background:#10151f; border:1px solid #252d3b; border-radius:14px; }
QPushButton { background:#1a2331; border:1px solid #2b374a; border-radius:9px; padding:10px 14px; font-weight:650; }
QPushButton:hover { background:#27344a; border-color:#7867d9; }
QPushButton:disabled { color:#697487; background:#151b25; border-color:#202938; }
QPushButton#Primary { background:#b5a4ff; color:#13101e; border:none; font-weight:800; }
QPushButton#Primary:hover { background:#c8bcff; }
QPushButton#Danger { color:#ffaaaa; border-color:#63353c; }
QListWidget { background:transparent; border:none; outline:none; }
QListWidget::item { padding:13px 12px; border-radius:9px; color:#aeb8ca; }
QListWidget::item:selected { background:#292541; color:#ded7ff; }
QLineEdit { background:#090c12; border:1px solid #293446; border-radius:9px; padding:10px; selection-background-color:#6257b8; }
QTextEdit { background:#090c12; border:1px solid #293446; border-radius:10px; padding:10px; font-family:Consolas; selection-background-color:#6257b8; }
QTableWidget { background:#0c1018; alternate-background-color:#111824; border:1px solid #293446; border-radius:10px; gridline-color:#202a39; selection-background-color:#292541; selection-color:#f4f1ff; }
QHeaderView::section { background:#171e2a; color:#aeb8ca; border:none; border-bottom:1px solid #30394a; padding:10px; font-weight:700; }
QScrollBar:vertical { background:#10151e; width:10px; margin:2px; }
QScrollBar::handle:vertical { background:#303b4d; border-radius:5px; min-height:24px; }
"""

def panel(title: str, eyebrow: str | None = None):
    frame = QFrame()
    frame.setObjectName("Panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(10)
    if eyebrow:
        tag = QLabel(eyebrow.upper())
        tag.setObjectName("Eyebrow")
        layout.addWidget(tag)
    heading = QLabel(title)
    heading.setStyleSheet("font-size:11pt;font-weight:750;")
    layout.addWidget(heading)
    return frame, layout


class MetricChart(QWidget):
    def __init__(self, title: str, color: str, suffix: str = "%", scale_max: float = 100):
        super().__init__()
        self.title, self.color, self.suffix, self.scale_max = title, QColor(color), suffix, scale_max
        self.values: deque[float | None] = deque(maxlen=30)
        self.setMinimumHeight(145)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def add_value(self, value: float | None) -> None:
        self.values.append(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.rect().adjusted(4, 6, -4, -4)
        left, top, right, bottom = area.left() + 30, area.top() + 10, area.right() - 5, area.bottom() - 22
        width, height = max(1, right - left), max(1, bottom - top)
        painter.setPen(QPen(QColor("#273142"), 1))
        for fraction in (0, .25, .5, .75, 1):
            y = bottom - int(height * fraction)
            painter.drawLine(left, y, right, y)
        painter.setPen(QColor("#7d8aa0"))
        painter.drawText(0, top + 5, 25, 15, Qt.AlignmentFlag.AlignRight, f"{self.scale_max:g}")
        painter.drawText(0, bottom, 25, 15, Qt.AlignmentFlag.AlignRight, "0")
        points = list(self.values)
        if not any(value is not None for value in points):
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "Waiting for supported telemetry…")
            return
        path = QPainterPath()
        active = False
        for index, value in enumerate(points):
            if value is None:
                active = False
                continue
            x = left + width * index / max(1, len(points) - 1)
            y = bottom - height * max(0, min(self.scale_max, value)) / self.scale_max
            if active:
                path.lineTo(x, y)
            else:
                path.moveTo(x, y)
                active = True
        pen = QPen(self.color, 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        if points and points[-1] is not None:
            y = bottom - height * max(0, min(self.scale_max, points[-1])) / self.scale_max
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.color)
            painter.drawEllipse(int(right) - 4, int(y) - 4, 8, 8)
        painter.setPen(QColor("#7d8aa0"))
        painter.drawText(left, area.bottom() + 14, "90-second window")
        painter.drawText(right - 32, area.bottom() + 14, "LIVE")


class PollWorker(QThread):
    completed = Signal(dict)
    failed = Signal(str)
    def __init__(self, adb: AdbClient, previous_cpu, previous_serial):
        super().__init__()
        self.adb, self.previous_cpu, self.previous_serial = adb, previous_cpu, previous_serial
    def run(self):
        try:
            devices = self.adb.devices()
            device = next((item for item in devices if item.ready), None)
            result = {"devices": devices, "device": device, "properties": {}, "metrics": {}}
            if device is None:
                result["unauthorized"] = any(item.state == "unauthorized" for item in devices)
                self.completed.emit(result)
                return
            result["properties"] = self.adb.properties(device.serial)
            metrics = {"cpu": None, "ram": None, "battery": None, "temperature": None}
            try:
                counters = parse_cpu_stat(self.adb.shell(device.serial, "cat", "/proc/stat", timeout=4))
                if counters is not None:
                    metrics["cpu"] = cpu_percent(self.previous_cpu if device.serial == self.previous_serial else None, counters)
                    result["cpu_counters"] = counters
            except (AdbError, ValueError):
                pass
            try:
                memory = parse_meminfo(self.adb.shell(device.serial, "cat", "/proc/meminfo", timeout=4))
                if memory:
                    metrics["ram"] = memory.get("used_percent")
                    result["memory"] = memory
            except (AdbError, ValueError):
                pass
            try:
                battery = parse_battery(self.adb.shell(device.serial, "dumpsys", "battery", timeout=5))
                metrics["battery"] = battery.get("level")
                metrics["temperature"] = battery.get("temperature_c")
            except (AdbError, ValueError):
                pass
            result["metrics"] = metrics
            self.completed.emit(result)
        except AdbError as exc:
            self.failed.emit(str(exc))


class ProcessWorker(QThread):
    completed = Signal(list)
    failed = Signal(str)
    def __init__(self, adb: AdbClient, serial: str):
        super().__init__()
        self.adb, self.serial = adb, serial
    def run(self):
        try:
            self.completed.emit(parse_process_list(self.adb.shell(self.serial, "ps", "-A", timeout=12)))
        except (AdbError, ValueError) as exc:
            self.failed.emit(str(exc))


class LogWorker(QThread):
    completed = Signal(tuple)
    def __init__(self, adb: AdbClient, serial: str, lines: int = 1000):
        super().__init__()
        self.adb, self.serial, self.lines = adb, serial, lines
    def run(self):
        try:
            output = self.adb.run(["-s", self.serial, "logcat", "-d", "-t", str(self.lines)], timeout=30)
            self.completed.emit((True, output or "No log entries returned."))
        except AdbError as exc:
            self.completed.emit((False, str(exc)))


class LogHighlighter(QSyntaxHighlighter):
    """Colorize log severity and common crash/error markers."""
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        for pattern, color, bold in [
            (r"\b(E|F)/[^ ]+|\s+[EF]\s+[^ ]+", "#ff7d91", True),
            (r"\bW/[^ ]+|\s+W\s+[^ ]+", "#ffbd72", True),
            (r"(?i)fatal exception|fatal signal|process .* has died|\bcrash(ed)?\b|\banr\b", "#ff657a", True),
            (r"(?i)exception|traceback|segmentation fault|tombstone", "#ff8fbc", True),
        ]:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            fmt.setFontWeight(700 if bold else 400)
            self.rules.append((QRegularExpression(pattern), fmt))

    def highlightBlock(self, text):
        for expression, fmt in self.rules:
            matches = expression.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class LogStreamWorker(QThread):
    line_received = Signal(str)
    failed = Signal(str)
    ended = Signal()

    def __init__(self, executable: str, serial: str):
        super().__init__()
        self.executable, self.serial = executable, serial
        self.process = None
        self._stopping = False

    def run(self):
        try:
            self.process = subprocess.Popen(
                [self.executable, "-s", self.serial, "logcat", "-v", "threadtime"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
            )
            while not self._stopping and self.process.stdout is not None:
                line = self.process.stdout.readline()
                if not line:
                    if self.process.poll() is not None:
                        break
                    continue
                self.line_received.emit(line.rstrip("\r\n"))
            if not self._stopping and self.process.poll() not in (None, 0):
                self.failed.emit(f"Live logcat exited with code {self.process.returncode}.")
        except OSError as exc:
            self.failed.emit(f"Could not start live logcat: {exc}")
        finally:
            if self.process is not None:
                try:
                    if self.process.poll() is None:
                        self.process.terminate()
                        try:
                            self.process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            self.process.kill()
                    if self.process.stdout:
                        self.process.stdout.close()
                except OSError:
                    pass
            self.ended.emit()

    def stop(self):
        self._stopping = True
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass


class ProcessMemoryWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, adb: AdbClient, serial: str, pid: str, process_name: str):
        super().__init__()
        self.adb, self.serial, self.pid, self.process_name = adb, serial, pid, process_name

    def run(self):
        try:
            output = self.adb.shell(self.serial, "dumpsys", "meminfo", self.pid, timeout=20)
            pss = parse_total_pss_kb(output)
            self.completed.emit(self.pid, {"name": self.process_name, "pss_kb": pss})
        except (AdbError, ValueError) as exc:
            self.failed.emit(self.pid, str(exc))


class QuestScopeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"QuestScope {APP_VERSION} — Quest diagnostics")
        self.resize(1360, 900)
        self.setMinimumSize(1020, 720)
        self.adb = AdbClient()
        self.selected_serial = None
        self.cpu_previous = None
        self.poll_worker = self.process_worker = self.log_worker = self.log_stream_worker = self.memory_worker = None
        self.session_file = self.session_writer = self.session_path = None
        self.session_samples = 0
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(15, 15, 15, 15)
        root_layout.setSpacing(15)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(15, 20, 15, 15)
        brand = QLabel("QuestScope")
        brand.setObjectName("Brand")
        side.addWidget(brand)
        tagline = QLabel("QUEST PERFORMANCE SUITE")
        tagline.setObjectName("Eyebrow")
        side.addWidget(tagline)
        version = QLabel(f"BUILD {APP_VERSION}")
        version.setObjectName("Muted")
        version.setStyleSheet("font-size:8pt;")
        side.addWidget(version)
        side.addSpacing(20)
        self.navigation = QListWidget()
        self.navigation.addItems(["◈   Overview", "▦   Processes", "≋   Logcat", "◉   Sessions"])
        self.navigation.setCurrentRow(0)
        side.addWidget(self.navigation, 1)
        status_frame = QFrame()
        status_frame.setStyleSheet("background:#0a0d13;border:1px solid #293446;border-radius:10px;")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(12, 12, 12, 12)
        self.connection_label = QLabel("●  Initializing ADB")
        self.connection_label.setWordWrap(True)
        self.connection_label.setStyleSheet("font-weight:750;color:#b5a4ff;")
        status_layout.addWidget(self.connection_label)
        self.last_update = QLabel("Waiting for first sample")
        self.last_update.setObjectName("Muted")
        self.last_update.setWordWrap(True)
        status_layout.addWidget(self.last_update)
        side.addWidget(status_frame)

        content = QVBoxLayout()
        content.setSpacing(14)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        self.page_title = QLabel("Live telemetry")
        self.page_title.setStyleSheet("font-size:25pt;font-weight:850;")
        self.subtitle = QLabel("Connect an authorized Quest to start sampling.")
        self.subtitle.setObjectName("Muted")
        titles.addWidget(self.page_title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.addStretch()
        self.refresh_button = QPushButton("↻  Refresh now")
        self.refresh_button.setObjectName("Primary")
        self.refresh_button.clicked.connect(self.refresh_devices)
        header.addWidget(self.refresh_button)
        content.addLayout(header)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_dashboard())
        self.pages.addWidget(self.build_processes())
        self.pages.addWidget(self.build_logs())
        self.pages.addWidget(self.build_sessions())
        content.addWidget(self.pages, 1)
        root_layout.addWidget(sidebar)
        root_layout.addLayout(content, 1)
        self.setCentralWidget(root)
        self.navigation.currentRowChanged.connect(self.change_page)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_devices)
        self.timer.start(3000)
        self.refresh_devices()

    def change_page(self, index):
        self.pages.setCurrentIndex(index)
        titles = ["Live telemetry", "Process explorer", "Android logcat", "Session recorder"]
        descriptions = [
            "Live readings from metrics exposed by Android.",
            "Inspect the process list reported by the headset OS.",
            "Capture recent Android system logs for diagnostics.",
            "Record telemetry samples to a portable CSV file.",
        ]
        self.page_title.setText(titles[index])
        self.subtitle.setText(descriptions[index])
        if index == 1:
            self.refresh_processes()

    def build_dashboard(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 4, 4)
        layout.setSpacing(12)
        cards = QGridLayout()
        cards.setSpacing(12)
        self.device_value, self.android_value = QLabel("Not connected"), QLabel("—")
        self.battery_value, self.temp_value = QLabel("—"), QLabel("—")
        for col, (name, value, eyebrow) in enumerate([
            ("CONNECTED HEADSET", self.device_value, "DEVICE"),
            ("ANDROID VERSION", self.android_value, "PLATFORM"),
            ("BATTERY LEVEL", self.battery_value, "POWER"),
            ("BATTERY TEMPERATURE", self.temp_value, "THERMAL"),
        ]):
            frame, box = panel(name, eyebrow)
            value.setObjectName("Metric")
            value.setWordWrap(True)
            box.addSpacing(5)
            box.addWidget(value)
            box.addStretch()
            cards.addWidget(frame, 0, col)
        layout.addLayout(cards)
        charts = QGridLayout()
        charts.setSpacing(12)
        self.cpu_chart = MetricChart("CPU activity", "#b5a4ff")
        self.ram_chart = MetricChart("Memory pressure", "#55d8c6")
        self.battery_chart = MetricChart("Battery level", "#91dc83")
        self.temp_chart = MetricChart("Battery temperature", "#ffb86b", "°C", 60)
        self.cpu_value, self.ram_value = QLabel("—"), QLabel("—")
        self.battery_chart_value, self.temp_chart_value = QLabel("—"), QLabel("—")
        specs = [
            (self.cpu_chart, self.cpu_value, "CPU ACTIVITY", "System counters", 0, 0),
            (self.ram_chart, self.ram_value, "RAM PRESSURE", "OS memory estimate", 0, 1),
            (self.battery_chart, self.battery_chart_value, "BATTERY", "Android battery service", 1, 0),
            (self.temp_chart, self.temp_chart_value, "BATTERY TEMP", "Not CPU/GPU temperature", 1, 1),
        ]
        for chart, value, title, note, row, col in specs:
            frame, box = panel(title, "LIVE CHART")
            top = QHBoxLayout()
            value.setStyleSheet(f"font-size:18pt;font-weight:850;color:{chart.color.name()};")
            top.addWidget(value)
            top.addStretch()
            note_label = QLabel(note)
            note_label.setObjectName("Muted")
            note_label.setStyleSheet("font-size:8pt;")
            top.addWidget(note_label)
            box.addLayout(top)
            box.addWidget(chart, 1)
            charts.addWidget(frame, row, col)
        layout.addLayout(charts, 1)
        self.status_detail_frame, status_box = panel("Connection details", "DEVICE STATUS")
        self.status_detail = QLabel("Waiting for an authorized Quest. Enable Developer Mode and USB debugging, then accept the prompt in the headset.")
        self.status_detail.setObjectName("Muted")
        self.status_detail.setWordWrap(True)
        status_box.addWidget(self.status_detail)
        layout.addWidget(self.status_detail_frame)
        scroll.setWidget(page)
        return scroll

    def build_processes(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        frame, box = panel("Running processes", "ANDROID PROCESS LIST")
        description = QLabel("Read-only process metadata from Android ps. Per-app memory and CPU values are not invented.")
        description.setObjectName("Muted")
        description.setWordWrap(True)
        box.addWidget(description)
        row = QHBoxLayout()
        self.process_search = QLineEdit()
        self.process_search.setPlaceholderText("Filter process name, PID, user, or state…")
        self.process_search.textChanged.connect(self.filter_processes)
        row.addWidget(self.process_search, 1)
        self.process_refresh = QPushButton("Refresh list")
        self.process_refresh.clicked.connect(self.refresh_processes)
        row.addWidget(self.process_refresh)
        box.addLayout(row)
        self.process_summary = QLabel("No process snapshot yet.")
        self.process_summary.setObjectName("Muted")
        box.addWidget(self.process_summary)
        self.process_table = QTableWidget(0, 5)
        self.process_table.setHorizontalHeaderLabels(["PID", "PROCESS", "USER", "STATE", "PSS MEMORY"])
        self.process_table.setAlternatingRowColors(True)
        self.process_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.process_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.process_table.verticalHeader().setVisible(False)
        self.process_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4):
            self.process_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        memory_row = QHBoxLayout()
        self.inspect_memory_button = QPushButton("Inspect selected process memory")
        self.inspect_memory_button.clicked.connect(self.inspect_process_memory)
        memory_row.addWidget(self.inspect_memory_button)
        self.process_memory_status = QLabel("Select a process to inspect its reported PSS memory.")
        self.process_memory_status.setObjectName("Muted")
        self.process_memory_status.setWordWrap(True)
        memory_row.addWidget(self.process_memory_status, 1)
        box.addLayout(memory_row)
        box.addWidget(self.process_table, 1)
        layout.addWidget(frame, 1)
        return page

    def build_logs(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        frame, box = panel("Android logcat", "DIAGNOSTICS")
        description = QLabel("Capture the most recent 1,000 entries. Logs may contain personal or identifying data.")
        description.setObjectName("Muted")
        description.setWordWrap(True)
        box.addWidget(description)
        row = QHBoxLayout()
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText("Filter displayed logs…")
        self.log_search.textChanged.connect(self.filter_logs)
        row.addWidget(self.log_search, 1)
        self.logs_button = QPushButton("Capture recent logs")
        self.logs_button.clicked.connect(self.capture_logs)
        row.addWidget(self.logs_button)
        self.live_logs_button = QPushButton("Start live stream")
        self.live_logs_button.clicked.connect(self.toggle_live_logs)
        row.addWidget(self.live_logs_button)
        self.save_logs_button = QPushButton("Save logs…")
        self.save_logs_button.clicked.connect(self.save_logs)
        row.addWidget(self.save_logs_button)
        box.addLayout(row)
        self.log_status = QLabel("Connect a headset to capture logs.")
        self.log_status.setObjectName("Muted")
        box.addWidget(self.log_status)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_highlighter = LogHighlighter(self.log_text.document())
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        box.addWidget(self.log_text, 1)
        layout.addWidget(frame, 1)
        self.all_logs = ""
        self.live_log_lines = deque(maxlen=5000)
        return page

    def build_sessions(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        frame, box = panel("Performance session", "CSV RECORDER")
        description = QLabel("Record the live telemetry samples shown on Overview. Samples are written every successful three-second poll; unsupported values remain blank.")
        description.setObjectName("Muted")
        description.setWordWrap(True)
        box.addWidget(description)
        self.session_status = QLabel("No recording active.")
        self.session_status.setStyleSheet("font-size:13pt;font-weight:750;color:#b5a4ff;")
        self.session_status.setWordWrap(True)
        box.addWidget(self.session_status)
        row = QHBoxLayout()
        self.start_recording_button = QPushButton("●  Start recording")
        self.start_recording_button.setObjectName("Primary")
        self.start_recording_button.clicked.connect(self.start_recording)
        row.addWidget(self.start_recording_button)
        self.stop_recording_button = QPushButton("■  Stop recording")
        self.stop_recording_button.setObjectName("Danger")
        self.stop_recording_button.setEnabled(False)
        self.stop_recording_button.clicked.connect(self.stop_recording)
        row.addWidget(self.stop_recording_button)
        row.addStretch()
        box.addLayout(row)
        self.session_path_label = QLabel("Choose Start recording to select a CSV destination.")
        self.session_path_label.setObjectName("Muted")
        self.session_path_label.setWordWrap(True)
        box.addWidget(self.session_path_label)
        layout.addWidget(frame)
        info, info_box = panel("What's recorded", "DATA TRANSPARENCY")
        for line in [
            "Timestamp and connected device serial",
            "CPU activity percentage when counters are readable",
            "OS-level RAM estimate in MB and percent",
            "Battery level and reported battery temperature",
        ]:
            item = QLabel("•  " + line)
            item.setObjectName("Muted")
            item.setWordWrap(True)
            info_box.addWidget(item)
        warning = QLabel("No root or headset modification required.")
        warning.setStyleSheet("color:#7edeb2;font-weight:650;")
        info_box.addWidget(warning)
        layout.addWidget(info)
        layout.addStretch()
        return page

    def refresh_devices(self):
        if not self.adb.available:
            self.connection_label.setText("●  ADB not found")
            self.connection_label.setStyleSheet("font-weight:750;color:#ff8585;")
            self.subtitle.setText("Install Platform Tools and add adb.exe to PATH.")
            self.status_detail.setText("ADB was not found. Add the folder containing adb.exe to PATH, then restart QuestScope.")
            self.refresh_button.setEnabled(False)
            return
        self.refresh_button.setEnabled(True)
        if self.poll_worker is not None and self.poll_worker.isRunning():
            return
        self.refresh_button.setText("◌  Sampling…")
        self.poll_worker = PollWorker(self.adb, self.cpu_previous, self.selected_serial)
        self.poll_worker.completed.connect(self.apply_snapshot)
        self.poll_worker.failed.connect(self.poll_failed)
        self.poll_worker.finished.connect(lambda: self.refresh_button.setText("↻  Refresh now"))
        self.poll_worker.start()

    def poll_failed(self, message):
        self.connection_label.setText("●  ADB error")
        self.connection_label.setStyleSheet("font-weight:750;color:#ff8585;")
        self.status_detail.setText(message)
        self.last_update.setText("Sample failed")

    def apply_snapshot(self, snapshot):
        device = snapshot.get("device")
        if device is None:
            self.selected_serial = None
            self.cpu_previous = None
            unauthorized = snapshot.get("unauthorized", False)
            self.connection_label.setText("●  Needs authorization" if unauthorized else "●  No headset connected")
            self.connection_label.setStyleSheet("font-weight:750;color:#ffbd72;" if unauthorized else "font-weight:750;color:#929cb1;")
            self.device_value.setText("Unauthorized" if unauthorized else "Not connected")
            self.android_value.setText("—")
            self.battery_value.setText("—")
            self.temp_value.setText("—")
            self.status_detail.setText("Unlock the headset and accept the USB debugging prompt." if unauthorized else "No authorized device found. Connect by USB or configure wireless ADB, then authorize the computer.")
            self.subtitle.setText("Waiting for an authorized Quest device.")
            for chart in (self.cpu_chart, self.ram_chart, self.battery_chart, self.temp_chart):
                chart.add_value(None)
            for label in (self.cpu_value, self.ram_value, self.battery_chart_value, self.temp_chart_value):
                label.setText("—")
            return
        if self.selected_serial != device.serial:
            self.cpu_previous = None
        self.selected_serial = device.serial
        self.connection_label.setText("●  Quest connected")
        self.connection_label.setStyleSheet("font-weight:750;color:#7edeb2;")
        props = snapshot.get("properties", {})
        model = props.get("Model", "Quest device")
        metrics = snapshot.get("metrics", {})
        cpu, ram = metrics.get("cpu"), metrics.get("ram")
        battery, temperature = metrics.get("battery"), metrics.get("temperature")
        self.device_value.setText(model)
        self.android_value.setText(props.get("Android version", "—"))
        self.battery_value.setText("—" if battery is None else f"{battery:.0f}%")
        self.temp_value.setText("—" if temperature is None else f"{temperature:.1f}°C")
        for chart, value in ((self.cpu_chart, cpu), (self.ram_chart, ram), (self.battery_chart, battery), (self.temp_chart, temperature)):
            chart.add_value(value)
        self.cpu_value.setText("—" if cpu is None else f"{cpu:.0f}%")
        self.ram_value.setText("—" if ram is None else f"{ram:.0f}%")
        self.battery_chart_value.setText("—" if battery is None else f"{battery:.0f}%")
        self.temp_chart_value.setText("—" if temperature is None else f"{temperature:.1f}°C")
        self.subtitle.setText(f"{model}  •  Android {props.get('Android version', 'unavailable')}  •  3-second sampling")
        memory = snapshot.get("memory", {})
        ram_detail = f"RAM estimate: {memory.get('used_mb', '—')} / {memory.get('total_mb', '—')} MB" if memory else "RAM details unavailable"
        self.status_detail.setText(f"Authorized ADB connection • {device.serial} • {ram_detail}")
        self.last_update.setText("Last sample: " + datetime.now().strftime("%H:%M:%S"))
        if snapshot.get("cpu_counters") is not None:
            self.cpu_previous = snapshot["cpu_counters"]
        if self.session_writer:
            self.write_session_row(device.serial, metrics, memory)

    def refresh_processes(self):
        if not self.selected_serial:
            self.process_summary.setText("Connect and authorize a Quest first.")
            return
        if self.process_worker is not None and self.process_worker.isRunning():
            return
        self.process_refresh.setEnabled(False)
        self.process_refresh.setText("Loading…")
        self.process_worker = ProcessWorker(self.adb, self.selected_serial)
        self.process_worker.completed.connect(self.show_processes)
        self.process_worker.failed.connect(self.process_failed)
        self.process_worker.finished.connect(lambda: self.process_refresh.setEnabled(True))
        self.process_worker.finished.connect(lambda: self.process_refresh.setText("Refresh list"))
        self.process_worker.start()

    def show_processes(self, processes):
        self.process_table.setSortingEnabled(False)
        self.process_table.setRowCount(len(processes))
        for row, process in enumerate(processes):
            for col, key in enumerate(("pid", "name", "user", "state")):
                item = QTableWidgetItem(str(process.get(key, "")))
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.process_table.setItem(row, col, item)
        self.process_table.setSortingEnabled(True)
        self.process_summary.setText(f"{len(processes):,} process entries reported • read-only snapshot")
        self.filter_processes(self.process_search.text())

    def process_failed(self, message):
        self.process_summary.setText("Could not read the process list: " + message)

    def filter_processes(self, query):
        needle = query.casefold().strip()
        shown = 0
        for row in range(self.process_table.rowCount()):
            match = not needle or any(needle in (self.process_table.item(row, col).text().casefold() if self.process_table.item(row, col) else "") for col in range(self.process_table.columnCount()))
            self.process_table.setRowHidden(row, not match)
            shown += int(match)
        if self.process_table.rowCount():
            self.process_summary.setText(f"Showing {shown:,} of {self.process_table.rowCount():,} process entries")

    def inspect_process_memory(self):
        selected = self.process_table.selectionModel().selectedRows()
        if not selected:
            self.process_memory_status.setText("Select a process row first.")
            return
        row = selected[0].row()
        pid_item, name_item = self.process_table.item(row, 0), self.process_table.item(row, 1)
        if not pid_item or not name_item or not self.selected_serial:
            self.process_memory_status.setText("Connect a headset and select a process.")
            return
        if self.memory_worker is not None and self.memory_worker.isRunning():
            return
        pid, name = pid_item.text(), name_item.text()
        self.inspect_memory_button.setEnabled(False)
        self.process_memory_status.setText(f"Inspecting memory for {name} (PID {pid})…")
        self.memory_worker = ProcessMemoryWorker(self.adb, self.selected_serial, pid, name)
        self.memory_worker.completed.connect(self.show_process_memory)
        self.memory_worker.failed.connect(self.process_memory_failed)
        self.memory_worker.finished.connect(lambda: self.inspect_memory_button.setEnabled(True))
        self.memory_worker.start()

    def show_process_memory(self, pid, details):
        row = next((i for i in range(self.process_table.rowCount())
                    if self.process_table.item(i, 0) and self.process_table.item(i, 0).text() == pid), None)
        pss = details.get("pss_kb")
        value = f"{pss / 1024:.1f} MB PSS" if pss is not None else "Unavailable"
        if row is not None:
            self.process_table.setItem(row, 4, QTableWidgetItem(value))
        detail = value if pss is not None else "PSS total not reported by this Android build"
        self.process_memory_status.setText(f"{details.get('name', 'Process')} (PID {pid}): {detail}. Point-in-time Android PSS estimate.")

    def process_memory_failed(self, pid, message):
        self.process_memory_status.setText(f"Memory inspection failed for PID {pid}: {message}")

    def toggle_live_logs(self):
        if self.log_stream_worker is not None and self.log_stream_worker.isRunning():
            self.log_stream_worker.stop()
            self.live_logs_button.setEnabled(False)
            self.live_logs_button.setText("Stopping…")
            return
        if not self.selected_serial:
            self.log_status.setText("Connect and authorize a Quest first.")
            return
        if not self.adb.executable:
            self.log_status.setText("ADB executable is unavailable.")
            return
        self.live_log_lines.clear()
        self.all_logs = ""
        self.log_text.clear()
        self.log_stream_worker = LogStreamWorker(self.adb.executable, self.selected_serial)
        self.log_stream_worker.line_received.connect(self.receive_live_log_line)
        self.log_stream_worker.failed.connect(self.live_log_failed)
        self.log_stream_worker.ended.connect(self.live_log_ended)
        self.log_stream_worker.start()
        self.live_logs_button.setText("Stop live stream")
        self.log_status.setText("Live logcat connected • keeping the latest 5,000 lines.")
        self.logs_button.setEnabled(False)

    def receive_live_log_line(self, line):
        self.live_log_lines.append(line)
        self.all_logs = "\n".join(self.live_log_lines)
        self.filter_logs(self.log_search.text())
        self.log_status.setText(f"LIVE • {len(self.live_log_lines):,} lines buffered (max 5,000)")

    def live_log_failed(self, message):
        self.log_status.setText(message)

    def live_log_ended(self):
        self.live_logs_button.setEnabled(True)
        self.live_logs_button.setText("Start live stream")
        self.logs_button.setEnabled(True)
        if self.log_status.text().startswith("LIVE"):
            self.log_status.setText("Live stream stopped.")

    def capture_logs(self):
        if not self.selected_serial:
            self.log_status.setText("Connect and authorize a Quest first.")
            return
        if self.log_worker is not None and self.log_worker.isRunning():
            return
        self.logs_button.setEnabled(False)
        self.logs_button.setText("Capturing…")
        self.log_status.setText("Reading recent logcat output…")
        self.log_worker = LogWorker(self.adb, self.selected_serial)
        self.log_worker.completed.connect(self.show_logs)
        self.log_worker.finished.connect(lambda: self.logs_button.setEnabled(True))
        self.log_worker.finished.connect(lambda: self.logs_button.setText("Capture recent logs"))
        self.log_worker.start()

    def show_logs(self, result):
        ok, output = result
        self.all_logs = output if ok else ""
        self.log_text.setPlainText(output if ok else "Could not capture logs:\n" + output)
        self.log_status.setText(f"Captured {len(output.splitlines()):,} lines." if ok else "Log capture failed.")
        self.filter_logs(self.log_search.text())

    def filter_logs(self, query):
        if not self.all_logs:
            return
        needle = query.casefold().strip()
        lines = self.all_logs.splitlines()
        if needle:
            lines = [line for line in lines if needle in line.casefold()]
        self.log_text.setPlainText("\n".join(lines))
        self.log_status.setText(f"Showing {len(lines):,} matching lines.")

    def save_logs(self):
        text = self.log_text.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "No logs", "Capture logs before saving them.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save logcat", "questscope-logcat.txt", "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
            self.log_status.setText(f"Saved logs to {path}")
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def start_recording(self):
        if not self.selected_serial:
            QMessageBox.information(self, "No headset", "Connect and authorize a Quest before recording.")
            return
        default_name = "questscope-session-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".csv"
        path, _ = QFileDialog.getSaveFileName(self, "Record performance session", default_name, "CSV files (*.csv)")
        if not path:
            return
        try:
            self.session_file = open(path, "w", newline="", encoding="utf-8")
            self.session_writer = csv.writer(self.session_file)
            self.session_writer.writerow(["timestamp", "device_serial", "cpu_percent", "ram_used_mb", "ram_total_mb", "ram_used_percent", "battery_percent", "battery_temperature_c"])
            self.session_file.flush()
        except OSError as exc:
            self.session_file = self.session_writer = None
            QMessageBox.critical(self, "Could not start recording", str(exc))
            return
        self.session_path = Path(path)
        self.session_samples = 0
        self.session_path_label.setText(str(self.session_path))
        self.session_status.setText("●  RECORDING — waiting for the next successful sample.")
        self.session_status.setStyleSheet("font-size:13pt;font-weight:800;color:#ff8c9b;")
        self.start_recording_button.setEnabled(False)
        self.stop_recording_button.setEnabled(True)

    def write_session_row(self, serial, metrics, memory):
        if not self.session_writer:
            return
        self.session_writer.writerow([
            datetime.now().isoformat(timespec="seconds"), serial, metrics.get("cpu"),
            memory.get("used_mb"), memory.get("total_mb"), metrics.get("ram"),
            metrics.get("battery"), metrics.get("temperature"),
        ])
        self.session_file.flush()
        self.session_samples += 1
        self.session_status.setText(f"●  RECORDING — {self.session_samples:,} samples saved")
        self.session_path_label.setText(str(self.session_path))

    def stop_recording(self):
        if self.session_file:
            try:
                self.session_file.flush()
                self.session_file.close()
            except OSError:
                pass
        self.session_file = self.session_writer = None
        self.start_recording_button.setEnabled(True)
        self.stop_recording_button.setEnabled(False)
        self.session_status.setStyleSheet("font-size:13pt;font-weight:800;color:#7edeb2;")
        self.session_status.setText(f"Recording stopped • {self.session_samples:,} samples written.")
        if self.session_path:
            self.session_path_label.setText(f"Saved: {self.session_path}")

    def closeEvent(self, event):
        self.timer.stop()
        if self.session_file:
            self.stop_recording()
        if self.log_stream_worker is not None and self.log_stream_worker.isRunning():
            self.log_stream_worker.stop()
            self.log_stream_worker.wait(5000)
        for worker in (self.poll_worker, self.process_worker, self.log_worker, self.memory_worker):
            if worker is not None and worker.isRunning():
                worker.wait(35000)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = QuestScopeWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
