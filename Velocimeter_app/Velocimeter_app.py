from PyQt6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
import os
import json


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(589, 535)
        self.centralwidget = QtWidgets.QWidget(parent=MainWindow)
        self.centralwidget.setObjectName("centralwidget")

        # Main vertical layout
        self.mainLayout = QtWidgets.QVBoxLayout(self.centralwidget)

        # Top: Connection controls
        self.pushButton = QtWidgets.QPushButton(
            "Connect ESP32", parent=self.centralwidget
        )

        # Connection status label
        self.connectionStatusLabel = QtWidgets.QLabel(
            "Disconnected", parent=self.centralwidget
        )
        self.connectionStatusLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.connectionStatusLabel.setStyleSheet(
            "color: red;"
        )  # Set initial color to red for "Disconnected"

        self.topLayout = QtWidgets.QHBoxLayout()
        self.topLayout.addWidget(self.pushButton)
        self.topLayout.addWidget(self.connectionStatusLabel)
        self.mainLayout.addLayout(self.topLayout)

        # USB / Serial connection row
        self.usbLayout = QtWidgets.QHBoxLayout()

        self.usbPortCombo = QtWidgets.QComboBox(parent=self.centralwidget)
        self.usbPortCombo.setMinimumWidth(120)
        self.usbPortCombo.setToolTip("Select the COM port for USB connection")

        self.usbRefreshButton = QtWidgets.QPushButton("Refresh", parent=self.centralwidget)
        self.usbRefreshButton.setToolTip("Scan for available serial ports")

        self.usbConnectButton = QtWidgets.QPushButton("Connect USB", parent=self.centralwidget)
        self.usbConnectButton.setToolTip("Connect to ESP32 via USB serial cable")

        self.usbLayout.addWidget(QtWidgets.QLabel("USB:", parent=self.centralwidget))
        self.usbLayout.addWidget(self.usbPortCombo)
        self.usbLayout.addWidget(self.usbRefreshButton)
        self.usbLayout.addWidget(self.usbConnectButton)
        self.usbLayout.addStretch()
        self.mainLayout.addLayout(self.usbLayout)

        # Sensor settings row
        self.settingsLayout = QtWidgets.QHBoxLayout()

        self.intervalLabel = QtWidgets.QLabel("Interval (s):", parent=self.centralwidget)
        self.intervalSpinBox = QtWidgets.QDoubleSpinBox(parent=self.centralwidget)
        self.intervalSpinBox.setRange(0.1, 30.0)
        self.intervalSpinBox.setSingleStep(0.1)
        self.intervalSpinBox.setDecimals(1)
        self.intervalSpinBox.setValue(1.0)
        self.intervalSpinBox.setFixedWidth(70)
        self.intervalSpinBox.setToolTip("Reporting interval in seconds (0.1 – 30)")

        self.modeLabel = QtWidgets.QLabel("Mode:", parent=self.centralwidget)
        self.modeCombo = QtWidgets.QComboBox(parent=self.centralwidget)
        self.modeCombo.addItems(["Count / ΔT", "Period avg. (ΔT)"])
        self.modeCombo.setToolTip(
            "Count/ΔT: revolutions counted in window divided by interval\n"
            "Period avg.: 1 / mean inter-pulse period (better at low speeds)"
        )

        self.applySettingsButton = QtWidgets.QPushButton("Apply to ESP", parent=self.centralwidget)
        self.applySettingsButton.setToolTip("Send interval and mode settings to the ESP32 (USB only)")

        self.settingsLayout.addWidget(self.intervalLabel)
        self.settingsLayout.addWidget(self.intervalSpinBox)
        self.settingsLayout.addSpacing(12)
        self.settingsLayout.addWidget(self.modeLabel)
        self.settingsLayout.addWidget(self.modeCombo)
        self.settingsLayout.addSpacing(12)
        self.settingsLayout.addWidget(self.applySettingsButton)
        self.settingsLayout.addStretch()
        self.mainLayout.addLayout(self.settingsLayout)

        # Plot
        self.plotWidget = pg.PlotWidget(parent=self.centralwidget)
        self.mainLayout.addWidget(self.plotWidget)

        # Bottom: QGridLayout
        self.gridLayout = QtWidgets.QGridLayout()

        # TextEdit
        self.textEdit = QtWidgets.QTextEdit(parent=self.centralwidget)
        self.gridLayout.addWidget(self.textEdit, 0, 0, 2, 1)  # Span 2 rows

        # Circle Label
        self.circleLabel = QtWidgets.QLabel(parent=self.centralwidget)
        pixmap = self.create_circle_pixmap(QtCore.Qt.GlobalColor.black)
        self.circleLabel.setPixmap(pixmap)
        self.gridLayout.addWidget(self.circleLabel, 0, 1)

        # Record Name Label
        self.recordNameLabel = QtWidgets.QLabel("", parent=self.centralwidget)
        self.gridLayout.addWidget(self.recordNameLabel, 0, 2)

        # User Entry for Record Name
        self.recordEntry = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.recordEntry.setToolTip(
            "Enter additional text to be appended to the record filename."
        )
        self.gridLayout.addWidget(self.recordEntry, 1, 1, 1, 2)  # Span 2 columns

        # Record Button
        self.recordButton = QtWidgets.QPushButton(
            "Start Recording", parent=self.centralwidget
        )
        self.gridLayout.addWidget(self.recordButton, 2, 1, 1, 2)  # Span 2 columns

        self.mainLayout.addLayout(self.gridLayout)
        self.centralwidget.setLayout(self.mainLayout)
        MainWindow.setCentralWidget(self.centralwidget)

        self.menubar = QtWidgets.QMenuBar(parent=MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 589, 22))
        self.menuVelocimeter_ESP32_v1 = QtWidgets.QMenu(parent=self.menubar)
        self.menuVelocimeter_ESP32_v1.setTitle("Velocimeter_ESP32_v1")
        self.menubar.addAction(self.menuVelocimeter_ESP32_v1.menuAction())
        MainWindow.setMenuBar(self.menubar)

        self.statusbar = QtWidgets.QStatusBar(parent=MainWindow)
        MainWindow.setStatusBar(self.statusbar)

        ### UPLOAD CALIBRATION FILE:
        # Calibration Rule Widgets
        self.calibrationEntry = QtWidgets.QLineEdit(parent=self.centralwidget)
        self.calibrationEntry.setPlaceholderText("Enter calibration file path...")
        self.gridLayout.addWidget(self.calibrationEntry, 3, 0, 1, 2)  # Span 2 columns

        self.calibrationButton = QtWidgets.QPushButton(
            "Upload Calibration", parent=self.centralwidget
        )
        self.gridLayout.addWidget(self.calibrationButton, 3, 2)

        self.calibrationButton.clicked.connect(self.toggle_calibration)

        ## Display the calibration
        self.calibrationFunctionLabel = QtWidgets.QLabel("", parent=self.centralwidget)
        self.gridLayout.addWidget(
            self.calibrationFunctionLabel, 4, 0, 1, 3
        )  # Span 3 columns

        ## Prepare calibration directory
        self.calibration_dir = os.path.join(os.getcwd(), "calibrationfiles")
        if not os.path.exists(self.calibration_dir):
            os.makedirs(self.calibration_dir)

    def create_circle_pixmap(self, color):
        pixmap = QtGui.QPixmap(20, 20)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setBrush(color)
        painter.drawEllipse(0, 0, 20, 20)
        painter.end()
        return pixmap


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow)
    MainWindow.show()
    sys.exit(app.exec())
