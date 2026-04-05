import sys
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QFileDialog
from PyQt6.QtCore import QTimer, QThread, pyqtSignal
import pyqtgraph as pg
import socket
import serial
import serial.tools.list_ports
from Velocimeter_app import Ui_MainWindow
import json
import time
import numpy as np

TCP_PORT = 8080

class SocketThread(QThread):
    data_received = pyqtSignal(str)
    connected_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, esp_ip, port=TCP_PORT):
        super().__init__()
        self.esp_ip = esp_ip
        self.port = port
        self.running = False

    def run(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((self.esp_ip, self.port))
            s.settimeout(5)
            self.running = True
            self.connected_signal.emit()
            buf = ""
            while self.running:
                try:
                    chunk = s.recv(1024).decode("utf-8", errors="ignore")
                    if not chunk:
                        break
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        self.data_received.emit(line.strip())
                except socket.timeout:
                    continue
            s.close()
        except socket.error as e:
            self.error_signal.emit(str(e))

    def stop(self):
        self.running = False


class SerialThread(QThread):
    data_received = pyqtSignal(str)
    connected_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, port, baud=115200):
        super().__init__()
        self.port = port
        self.baud = baud
        self.running = False
        self.ser = None

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=2)
            self.running = True
            self.connected_signal.emit()
            while self.running:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    self.data_received.emit(line)
        except serial.SerialException as e:
            self.error_signal.emit(str(e))

    def send_command(self, cmd: str):
        """Send a newline-terminated command to the ESP32. Thread-safe."""
        if self.ser and self.ser.is_open:
            self.ser.write((cmd + "\n").encode("utf-8"))

    def stop(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()


class ESP32Monitor(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # Initialize pyqtgraph
        self.plot_widget = pg.PlotWidget()
        self.layout = QVBoxLayout(self.centralwidget)
        self.layout.addWidget(self.plot_widget)

        self.plotWidget.setObjectName("Velocimeter counts")
        self.plotWidget.setLabel("left", "Counts/s")
        self.plotWidget.setLabel("bottom", "Seconds")

        self.data = []
        self.data_raw = []
        self.time_data = []  # elapsed seconds matching each data point

        # Connect signals and slots
        self.pushButton.clicked.connect(self.toggle_connection)
        self.usbConnectButton.clicked.connect(self.toggle_usb_connection)
        self.usbRefreshButton.clicked.connect(self.refresh_ports)
        self.applySettingsButton.clicked.connect(self.apply_settings)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_graph)

        self.serial_thread = None
        self.start_time = None
        self.refresh_ports()

        self.recording = False
        self.recording_pending = False
        self.record_file = None
        self.record_folder = None
        self.record_count = 0

        # Connect the new button to the toggle recording function
        self.recordButton.clicked.connect(self.toggle_recording)

        ## Prepare calibration data
        self.calibration_data = None
        self.calibrationFunctionLabel.setText(
            "INSTRUMENT NON CALIBRATED, showing rev per second"
        )

    def create_circle_pixmap(self, color):
        pixmap = QtGui.QPixmap(20, 20)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setBrush(color)
        painter.drawEllipse(0, 0, 20, 20)
        painter.end()
        return pixmap

    def convert_rpm_to_mps(self, value):
        if self.calibration_data:
            self.calibration_data["params_val"]["v"] = value
            mps = eval(
                self.calibration_data["function"],
                {},
                self.calibration_data["params_val"],
            )
        else:
            mps = value
        return mps

    def toggle_connection(self):
        if not hasattr(self, "socket_thread") or not self.socket_thread.running:
            ip = self.espIPEdit.text().strip()
            if not ip:
                self.textEdit.append("Enter the ESP32 IP address first (connect via USB to auto-fill).")
                return
            self.socket_thread = SocketThread(ip)
            self.socket_thread.data_received.connect(self.handle_data)
            self.socket_thread.start()
            self.start_time = time.time()
            self.pushButton.setText("Disconnect ESP32")
            self.connectionStatusLabel.setText("Connected (WiFi)")
            self.connectionStatusLabel.setStyleSheet("color: green;")
            self.usbConnectButton.setEnabled(False)
        else:
            self.socket_thread.stop()
            self.start_time = None
            self.pushButton.setText("Connect ESP32")
            self.connectionStatusLabel.setText("Disconnected")
            self.connectionStatusLabel.setStyleSheet("color: red;")
            self.usbConnectButton.setEnabled(True)

    def refresh_ports(self):
        self.usbPortCombo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.usbPortCombo.addItems(ports if ports else ["No ports found"])

    def toggle_usb_connection(self):
        if self.serial_thread is None or not self.serial_thread.running:
            port = self.usbPortCombo.currentText()
            if not port or port == "No ports found":
                self.textEdit.append("No serial port selected.")
                return
            self.serial_thread = SerialThread(port)
            self.serial_thread.data_received.connect(self.handle_data)
            self.serial_thread.connected_signal.connect(self._on_usb_connected)
            self.serial_thread.error_signal.connect(self._on_usb_error)
            self.serial_thread.start()
            # Disable WiFi button while USB is active
            self.pushButton.setEnabled(False)
        else:
            self.serial_thread.stop()
            self.serial_thread = None
            self.start_time = None
            self.usbConnectButton.setText("Connect USB")
            self.connectionStatusLabel.setText("Disconnected")
            self.connectionStatusLabel.setStyleSheet("color: red;")
            self.pushButton.setEnabled(True)

    def _on_usb_connected(self):
        # start_time is set when READY is received, not here
        self.usbConnectButton.setText("Disconnect USB")
        self.connectionStatusLabel.setText("Connected (USB)")
        self.connectionStatusLabel.setStyleSheet("color: green;")

    def apply_settings(self):
        if self.serial_thread is None or not self.serial_thread.running:
            self.textEdit.append("Connect via USB first to apply settings.")
            return
        interval_s = self.intervalSpinBox.value()
        mode = self.modeCombo.currentIndex()  # 0 = count, 1 = period
        self.serial_thread.send_command(f"INTERVAL:{interval_s:.1f}")
        self.serial_thread.send_command(f"MODE:{mode}")
        self.textEdit.append(f"Settings applied — interval: {interval_s}s, mode: {self.modeCombo.currentText()}")

        if self.recording or self.recording_pending:
            self._close_record_file()
            self.recording = False
            self.recording_pending = True
            self.recordNameLabel.setText("Waiting for next second...")
            self.textEdit.append("Settings applied — recording will restart at next whole second.")

    def _on_usb_error(self, msg):
        self.usbConnectButton.setText("Connect USB")
        self.connectionStatusLabel.setText("USB Error")
        self.connectionStatusLabel.setStyleSheet("color: red;")
        self.textEdit.append(f"Serial error: {msg}")
        self.serial_thread = None
        self.pushButton.setEnabled(True)

    def handle_data(self, data):
        line = data.strip()

        # ESP reports its IP — auto-fill the WiFi connect field
        if line.startswith("IP:"):
            ip = line[3:].strip()
            self.espIPEdit.setText(ip)
            self.textEdit.append(f"ESP32 IP: {ip}")
            return

        # READY signal: ESP finished init — start the elapsed timer now
        if line == "READY":
            self.start_time = time.time()
            self.textEdit.append("── ESP32 ready ──")
            return

        # ESP acknowledgement / status lines — log but don't plot
        if line.startswith("OK ") or line.startswith("ERR ") or not line:
            self.textEdit.append(line)
            return

        try:
            raw = float(line)
            # WiFi path: start_time set on first data (no READY signal over TCP)
            if self.start_time is None:
                self.start_time = time.time()
            elapsed_s = time.time() - self.start_time

            self.data_raw.append(raw)
            self.data_raw = self.data_raw[-100:]

            value = self.convert_rpm_to_mps(raw)
            self.data.append(value)
            self.data = self.data[-100:]
            self.time_data.append(elapsed_s)
            self.time_data = self.time_data[-100:]

            self.plotWidget.clear()
            self.plotWidget.plot(self.time_data, self.data)

            # Pending: wait for a sample that lands on (or nearest to) a whole second
            if self.recording_pending:
                interval_s = self.intervalSpinBox.value()
                if abs(elapsed_s - round(elapsed_s)) <= interval_s / 2:
                    self.recording_pending = False
                    self.recording = True
                    self._open_record_file()
                    pixmap = self.create_circle_pixmap(QtCore.Qt.GlobalColor.red)
                    self.circleLabel.setPixmap(pixmap)

            if self.recording and self.record_file:
                timestamp = QtCore.QDateTime.currentDateTime().toString(
                    "yyyy-MM-dd HH:mm:ss"
                )
                self.record_file.write(f"{timestamp},{elapsed_s:.1f},{value}\n")

            self.textEdit.append(f"t={elapsed_s:6.1f}s  |  {value:.3f}")

        except ValueError:
            self.textEdit.append(line)

    def _open_record_file(self):
        """Open a new uniquely-named file, write a metadata header, update UI labels."""
        full_record_path = QtCore.QDir(self.record_folder).filePath("records")
        QtCore.QDir().mkpath(full_record_path)

        while True:
            date_str = QtCore.QDate.currentDate().toString("dd_MM_yyyy")
            file_name = f"record_{self.recordEntry.text()}ID_{self.record_count}_{date_str}.txt"
            full_file_path = QtCore.QDir(full_record_path).filePath(file_name)
            if not QtCore.QFileInfo(full_file_path).exists():
                break
            self.record_count += 1

        f = open(full_file_path, "w", encoding="utf-8")

        # ── Metadata header ───────────────────────────────────────────────────
        now_str = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        f.write(f"# OTT Velocimeter ESP32 — Recording\n")
        f.write(f"# Date: {now_str}\n")
        f.write(f"# Interval (s): {self.intervalSpinBox.value():.1f}\n")
        f.write(f"# Mode: {self.modeCombo.currentText()}\n")
        if self.calibration_data:
            cal_text = self.function_to_text(
                self.calibration_data["function"],
                self.calibration_data["params_val"],
            )
            impeler = self.calibration_data.get("impeler", "unknown")
            f.write(f"# Calibration: propeller={impeler}, function={cal_text}\n")
        else:
            f.write(f"# Calibration: UNCALIBRATED (values in rev/s)\n")
        f.write(f"# ---\n")
        f.write(f"timestamp,elapsed_s,value\n")

        self.record_file = f
        self.recordNameLabel.setText(file_name)

    def _close_record_file(self):
        if self.record_file:
            self.record_file.flush()
            self.record_file.close()
            self.record_file = None

    def toggle_recording(self):
        if not self.recording and not self.recording_pending:
            if self.record_folder is None:
                folder = QFileDialog.getExistingDirectory(
                    self, "Select Folder to Save Records"
                )
                if not folder:
                    return
                self.record_folder = folder

            self.recording_pending = True
            self.recordButton.setText("Stop Recording")
            self.recordNameLabel.setText("Waiting for next second...")
        else:
            self.recording = False
            self.recording_pending = False
            self._close_record_file()
            self.recordButton.setText("Start Recording")
            self.recordNameLabel.setText("")
            pixmap = self.create_circle_pixmap(QtCore.Qt.GlobalColor.black)
            self.circleLabel.setPixmap(pixmap)

    def update_graph(self):
        self.plotWidget.clear()
        if self.time_data and self.data:
            self.plotWidget.plot(self.time_data, self.data)

        # Maintain the scroll bar to the lowest part
        scrollbar = self.textEdit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def toggle_calibration(self):
        current_text = self.calibrationButton.text()
        if current_text == "Upload Calibration":
            # Show a file dialog to select the calibration file from the "calibration" directory
            filePath, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Select Calibration File",
                self.calibration_dir,  # This sets the initial directory to "calibrationfiles"
                "Calibration Files (*.json);;All Files (*)",
            )
            if filePath:
                self.calibrationEntry.setText(filePath)
                # Load the calibration data
                with open(filePath, "r") as file:
                    self.calibration_data = json.load(file)
                # Display the function text
                function_text = self.function_to_text(
                    self.calibration_data["function"],
                    self.calibration_data["params_val"],
                )
                self.calibrationFunctionLabel.setText(
                    "INSTRUMENT CALIBRATED for Propeller {}, Function: ".format(
                        self.calibration_data["impeler"]
                    )
                    + function_text
                )
                self.calibrationButton.setText("Remove Calibration")

            # Update Graph label:
            self.plotWidget.setLabel("left", "Velocity [m/s]")

            # Update all previous data with the new calibration function.
            def eval_func(x_value):
                params_with_value = self.calibration_data["params_val"].copy()
                params_with_value["v"] = x_value
                return eval(self.calibration_data["function"], {}, params_with_value)

            vectorized_func = np.vectorize(eval_func)
            newdata_np = vectorized_func(self.data)
            self.data = newdata_np.tolist()

        else:
            self.calibrationButton.setText("Upload Calibration")
            self.calibrationEntry.clear()
            self.calibrationFunctionLabel.clear()
            self.calibration_data = None
            self.data = self.data_raw
            # Update Graph label:
            self.plotWidget.setLabel("left", "Counts/s")
            self.calibrationFunctionLabel.setText(
                "INSTRUMENT NON CALIBRATED, showing rev per second"
            )

    def function_to_text(self, function_str, params_val):
        for param, value in params_val.items():
            function_str = function_str.replace(param, str(value))
        return function_str


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ESP32Monitor()
    window.show()
    sys.exit(app.exec())
