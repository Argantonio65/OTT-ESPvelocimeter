# OTT Moulinette ESP32 Velocimeter, 
###### A. Moreno-Rodenas. Delft, 05-06-2026

A digital interface for the **OTT moulinette**, a classic mechanical water-velocity sensor (propeller-type). An ESP32 microcontroller counts the propeller tip pulses and streams the data over WiFi to a Python desktop application that plots, calibrates, and records the measurements.

---

## Schema

```
Water flow
   │
   ▼
OTT Moulinette (propeller)
   │  reed switch / contact — one electrical pulse per revolution
   ▼
ESP32 GPIO17 (INPUT_PULLUP, FALLING interrupt)
   │  counts pulses for 1 second → sends integer over TCP
   ▼
WiFi / TCP port 8080
   │
   ▼
Python GUI (PyQt6)
   │  receives counts/s → applies calibration → plots + records
   ▼
Calibrated velocity [m/s]  |  Raw data file (CSV)
```

---

## Hardware

| Component | Detail |
|-----------|--------|
| Microcontroller | ESP32 AZ-Delivery DevKit V4 |
| Propeller input | GPIO 17, configured as `INPUT_PULLUP` |
| Status LED | GPIO 2 (onboard LED, blinks every second) |
| Power | USB or 3.3 V external supply |

The OTT moulinette produces one electrical contact closure (tip) per revolution of the propeller. The ESP32 detects each tip as a **FALLING edge** on GPIO17.

---

## Repository Structure

```
OTT_ESPvelocimeter/
├── README.md                          ← this file
├── Velocimeter_ESP32/                 ← ESP32 firmware (PlatformIO)
│   ├── platformio.ini
│   └── src/
│       └── main.cpp                   ← core firmware
└── Velocimeter_app/                   ← Python desktop GUI
    ├── main.py                        ← application entry point
    ├── Velocimeter_app.py             ← PyQt6 UI class
    ├── calibrationfiles/
    │   ├── calibration_example.json
    │   └── calibration_IMP_1.json
    └── records/                       ← saved measurement sessions
```

---

## Firmware (`Velocimeter_ESP32/src/main.cpp`)

1. On boot: connects to a WiFi network (credentials hardcoded).
2. Attaches an **interrupt** on GPIO17 that increments `fanCounter` on every FALLING edge.
3. Every **1 second** (via `delay(1000)`):
   - Reads `fanCounter` → `fanSpeed`
   - Resets `fanCounter = 0`
   - Opens a TCP connection to the PC server, sends `fanSpeed` as a text line, closes connection.
4. Blinks the onboard LED non-blocking at 1 Hz as a heartbeat.

### Key parameters (hardcoded in `main.cpp`)

| Parameter | Value |
|-----------|-------|
| WiFi SSID | `SSID` |
| WiFi Password | `Pass` |
| Server IP | `192.168.99.65` |
| Server Port | `8080` |
| Propeller pin | GPIO 17 |
| LED pin | GPIO 2 |
| Debounce time | `0` ms (disabled) |
| Sample window | `1000` ms |

### Known limitations / issues

| # | Issue | Impact |
|---|-------|--------|
| 1 | **Debounce = 0** — any mechanical contact bounce is counted as a real pulse | Possible overcounting at low speeds |
| 2 | **Race condition** — `fanCounter` is read/reset without disabling interrupts; a pulse arriving in that gap is lost | Very rare; 1-count error maximum |
| 3 | **New TCP connection every second** — high connection overhead; if the network is slow a second can be missed | Minor timing jitter |
| 4 | **Blocking WiFi setup** — `while(!connected) delay(1000)` freezes the device if the network is absent | Device unresponsive until network appears |
| 5 | **Credentials in source** — WiFi password is plaintext in `main.cpp` | Fine for a field prototype; move to `config.h` or SPIFFS for production |

**Recommended fix for issues 1 & 2** (drop-in replacement for the interrupt handler and counter read):

```cpp
// In main.cpp — safer counter read with debounce
const unsigned long debounceTime = 5;  // 5 ms debounce

void IRAM_ATTR handleFanInterrupt() {
  unsigned long t = millis();
  if (t - lastInterruptTime > debounceTime) {
    fanCounter++;
    lastInterruptTime = t;
  }
}

// In loop(), replace the three counter lines with:
portDISABLE_INTERRUPTS();
int fanSpeed = fanCounter;
fanCounter = 0;
portENABLE_INTERRUPTS();
```

---

## Python Application (`Velocimeter_app/`)

### Running

```bash
cd Velocimeter_app
pip install PyQt6 pyqtgraph numpy
python main.py
```

The app opens a GUI window. Click **Connect ESP32** to start the TCP server on port 8080.

### Application architecture

```
main.py
├── SocketThread (QThread)
│     └── TCP server on 0.0.0.0:8080
│           receives one integer/line per second from ESP32
│           emits data_received(str) signal
└── ESP32Monitor (QMainWindow + Ui_MainWindow)
      ├── handle_data()  — convert raw count → calibrated value → plot + record
      ├── toggle_connection()  — start/stop SocketThread
      ├── toggle_recording()   — open/close CSV file
      └── toggle_calibration() — load/remove calibration JSON
```

### GUI controls

| Control | Function |
|---------|----------|
| **Connect ESP32** | Starts the TCP server; button toggles to "Disconnect" |
| Connection status label | Green = server running, Red = stopped |
| Real-time plot | Last 100 samples; Y-axis label updates when calibration is applied |
| Text log | Appends each received value |
| Record name field | Optional prefix added to the filename |
| **Start Recording** | Opens a folder picker, then writes `timestamp,value` lines to a `.txt` file; red circle = active |
| Calibration file field | Shows path of loaded JSON |
| **Upload Calibration** | Opens file browser, loads JSON, converts all buffered data and updates plot |
| **Remove Calibration** | Reverts plot and buffer to raw counts/s |

### Calibration system

Calibration converts raw **counts/s** (propeller tips per second) to **velocity [m/s]**.

**JSON format:**

```json
{
  "function": "a + b*v",
  "params_val": { "a": 0.0, "b": 0.025 },
  "impeler": "IMP_1",
  "metadata": {
    "date": "28-08-23",
    "user": "A. Moreno-Rodenas",
    "description": "Linear calibration for propeller IMP_1"
  }
}
```

- `function`: any valid Python math expression; `v` is the raw counts/s value.
- `params_val`: named constants used in the expression (all except `v`).
- `impeler`: propeller identifier (shown in the GUI label).

**Supported function shapes:**

| Type | Example function string |
|------|------------------------|
| Linear | `"a + b*v"` |
| Polynomial | `"a + b*v + c*v**2"` |
| Power law | `"a * v**b"` |
| Any math | any expression using Python operators and `math` functions |

> **Note:** The calibration uses `eval()`. Only load JSON files you trust. Do not expose the calibration file path to untrusted users.

### Recording file format

Files are saved in a `records/` sub-folder of the directory you select.  
Filename pattern: `record_{prefix}ID_{counter}_{DD_MM_YYYY}.txt`

Contents (CSV, no header):
```
2023-08-27 19:17:44,2
2023-08-27 19:17:45,8
2023-08-27 19:17:46,8
```

The recorded value is the **calibrated** value (m/s) if a calibration is active, otherwise raw counts/s.

---

## Communication Protocol

| Parameter | Value |
|-----------|-------|
| Transport | TCP/IP over WiFi |
| Port | 8080 |
| Direction | ESP32 → PC |
| Format | ASCII integer followed by `\r\n` (Arduino `println`) |
| Rate | 1 message per second |
| Connection | New TCP connection per message (connect → send → close) |

The PC side runs a persistent `socket.listen()` loop; each incoming connection is accepted, the single data line is read, and the connection is closed.

---

## Deployment Checklist

1. **Edit `main.cpp`**: set `ssid`, `password`, and `serverIP` to match your field network.
2. **Flash** with PlatformIO: `pio run --target upload`
3. **Verify** serial output at 115200 baud: you should see `Connected to WiFi` then a number every second.
4. **Launch** `python main.py` on the PC connected to the same network.
5. Click **Connect ESP32** — the status label should turn green within a second.
6. Optionally load a calibration JSON for your specific propeller.
7. Click **Start Recording** to save a session.