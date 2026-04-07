# OTT Moulinette ESP32 Velocimeter

**A. Moreno-Rodenas, 02/04/26 Deltares, Delft**

A digital interface for the **OTT velocimeter**, a classic mechanical water-velocity instrument (propeller-type current meter). An ESP32 microcontroller counts propeller-contact pulses and streams the data to a Python desktop application over WiFi or USB. The app plots, calibrates, and records measurements in real time.

---

## System Overview

```
Water flow
   │
   ▼
OTT propeller
   │  conductive/non-conductive half-cylinder contact
   │  2 electrical transitions per revolution
   ▼
ESP32 GPIO17  (INPUT_PULLUP, CHANGE interrupt, 15 ms debounce)
   │
   ├─ [WiFi AP mode]
   │   SSID: OTT_ESPvelocimeter  |  Pass: 12345678  |  IP: 192.168.4.1    
   │   ESP generates its own TCP server port 8080                         
   └─ [USB serial mode]  115200 baud, direct cable connection                 
   |                                                                       
   ▼                                                                      
Python GUI (PyQt6) 
   │  receives rev/s → applies calibration curve, plots + records
   ▼
Calibrated velocity [m/s]  |  Metadata-annotated CSV file
```

---

## Hardware

| Component | Detail |
|-----------|--------|
| Microcontroller | ESP32 AZ-Delivery DevKit V4 |
| Propeller input | GPIO 17, `INPUT_PULLUP`, `CHANGE` interrupt |
| Status LED | GPIO 2 (onboard, blinks at reporting rate) |
| Power | USB-C or 3.3 V external supply |

The OTT moulinette contact consists of a **rotating half-cylinder**: one half is electrically conductive, the other is not. This produces two transitions per full revolution (one RISING, one FALLING). To counting modes are available, single transition mode, and double count mode per revolution (default).

---

## Repository Structure

```
OTT_ESPvelocimeter/
├── README.md
├── pyproject.toml               ← Python environment (uv)
├── uv.lock
├── Velocimeter_ESP32/           ← ESP32 firmware (PlatformIO)
│   ├── platformio.ini
│   └── src/
│       └── main.cpp
├── Velocimeter_app/             ← Python desktop application
│   ├── main.py                  ← entry point + business logic
│   ├── Velocimeter_app.py       ← PyQt6 UI layout
│   └── calibrationfiles/        ← calibration JSON files
│       ├── calibration_example.json
│       └── calibration_IMP1_*.json
└── calibration/                 ← Jupyter calibration workflow
    ├── calibrate_propeller.ipynb
    ├── generate_synthetic_data.ipynb
    └── synthetic_data/          ← synthetic test runs (IMP1, 5 speeds)
```

---

## Getting Started

### 1. Python environment

The project uses [uv](https://github.com/astral-sh/uv) for dependency management.

```bash
# From the repository root:
uv sync                                    # create .venv and install all deps
uv run python Velocimeter_app/main.py      # launch the GUI
```

Dependencies: `PyQt6`, `pyqtgraph`, `numpy`, `pyserial`.

### 2. Flash the ESP32

Open `Velocimeter_ESP32/` in VS Code with the **PlatformIO IDE** extension installed.

- Click **→ Upload** in the status bar (or `pio run --target upload`)
- Open the serial monitor at **115200 baud** to verify startup

On boot you should see:
```
Initializing — starting WiFi Access Point...
AP started: OTT_ESPvelocimeter
IP:192.168.4.1
READY
0.000
0.000
...
```

### 3. Connect

**WiFi (recommended for field use)**
1. On your laptop, connect to WiFi network **`OTT_ESPvelocimeter`**, password **`12345678`**
2. In the app, the IP field should already show `192.168.4.1` (pre-filled)
3. Click **Connect ESP32 (WiFi)**

**USB / Serial (recommended for lab setup and configuration)**
1. Plug in the USB cable
2. In the app, click **Refresh** to scan COM ports, select the correct port
3. Click **Connect USB**

> Both modes can be active at the same time. WiFi transmits measurements; USB transmits the same measurements and allows sending configuration commands to the ESP.

---

## Firmware (`Velocimeter_ESP32/src/main.cpp`)

### Startup sequence

1. Start serial at 115200 baud, print `Initializing`
2. Start a WiFi **Access Point** (`OTT_ESPvelocimeter` / `12345678`) with a fixed IP (`192.168.4.1`)
3. Start a **TCP server** on port 8080
4. Configure GPIO17 interrupt (`CHANGE`, 15 ms debounce)
5. Print `READY` — this is the signal the Python app uses to start the elapsed-time counter

### Measurement loop (non-blocking)

Every `reportInterval_ms` (default 1000 ms):

1. Snapshot and reset the interrupt accumulators atomically (`noInterrupts` / `interrupts`)
2. Compute **rev/s** using the selected mode:
   - **Count mode**: `rps = transitions_counted / TRANSITIONS_PER_REV / interval_s`
   - **Period mode**: `rps = 1 / (mean_inter_transition_period_s × TRANSITIONS_PER_REV)`
3. Print `rps` to serial
4. If a WiFi client is connected, send the same value over TCP

### Interrupt handler

```
CHANGE edge on GPIO17
  → micros() since last edge > 15000 µs  (15 ms debounce to mitigate mechanical noise, < 33 rev/s>)
  → increment fanCounter
  → accumulate inter-transition period into sumPeriods_us / periodCount
```

### Runtime configuration (serial commands)

All commands are sent as newline-terminated ASCII strings from the Python app via USB.

| Command | Effect | Example |
|---------|--------|---------|
| `INTERVAL:x.x` | Set reporting interval in seconds (0.1–30) | `INTERVAL:0.5` |
| `MODE:0` | Count mode (counts / ΔT) | `MODE:0` |
| `MODE:1` | Period average mode (1 / mean ΔT between pulses) | `MODE:1` |
| `TRANSITIONS:1` | Count only FALLING edge (1 event/rev) | `TRANSITIONS:1` |
| `TRANSITIONS:2` | Count both edges (2 events/rev, default) | `TRANSITIONS:2` |
| `WIFI:ssid,pass` | Save secondary WiFi credentials to NVS | `WIFI:MyNet,pass123` |

The ESP acknowledges each command with `OK <COMMAND>` or `ERR <reason>`.

### Count mode vs. Period mode

| | Count mode | Period mode |
|--|-----------|-------------|
| **Computation** | `rps = count / interval` | `rps = 1 / mean_period` |
| **Best for** | High speeds (many pulses/window) | Low speeds (few pulses/window) |
| **Noise at low speed** | High (±1 count quantisation) | Low (microsecond timing resolution) |
| **Noise at high speed** | Low | Slightly higher (short periods) |

---

## Python Application (`Velocimeter_app/`)

### Architecture

```
main.py
├── SocketThread (QThread)         WiFi — TCP client connecting to ESP32:8080
├── SerialThread (QThread)         USB  — reads lines from COM port at 115200
│     └── send_command(str)        write config commands back to ESP (USB only)
└── ESP32Monitor (QMainWindow)
      ├── handle_data()            parse incoming line → plot → record
      ├── toggle_connection()      start/stop WiFi SocketThread
      ├── toggle_usb_connection()  start/stop USB SerialThread
      ├── apply_settings()         send INTERVAL / MODE / TRANSITIONS commands
      ├── save_wifi_credentials()  send WIFI:ssid,pass command
      ├── toggle_recording()       open/close recording file
      ├── toggle_calibration()     load/unload calibration JSON
      ├── _open_record_file()      create new file with metadata header
      └── convert_rpm_to_mps()     apply calibration function via eval()
```

### GUI layout (top to bottom)

| Row | Controls |
|-----|----------|
| WiFi | **Connect ESP32** button · ESP32 IP field (auto-filled from serial) · status label |
| USB | COM port dropdown · **Refresh** · **Connect USB** |
| Secondary WiFi | SSID field · Password field · **Save WiFi to ESP** *(enabled when USB connected)* |
| Sensor settings | Interval (s) · Mode · Transitions/rev · **Apply to ESP** |
| Plot | Live rev/s or m/s time series (last 100 samples, x-axis = real elapsed seconds) |
| Log | Timestamped value log: `t=  5.0s  |  3.142` |
| Recording | Circle indicator · filename · label entry · **Start/Stop Recording** |
| Calibration | File path · **Upload / Remove Calibration** · function label |

### Calibration system

Calibration converts **rev/s** to **m/s** using a user-defined formula.

**JSON format:** #Calibration data metadata.

```json
{
  "impeler": "IMP1",  ### asign to a pre-calibrated impeler geometry
  "function": "a + b * v",
  "params_val": { "a": 0.05, "b": 0.025 },
  "metadata": {
    "date": "2026-04-07",
    "user": "A. Moreno-Rodenas",
    "model": "linear",
    "r2": 0.9987,
    "n_points": 5,
    "velocities_mps": [0.3, 0.6, 0.9, 1.2, 1.5]
  }
}
```

- `function`: any Python math expression; `v` is rev/s
- Supported symbols: `v`, named params, `log` (natural), `exp`, `sqrt`
- `impeler`: propeller ID displayed in the GUI

**Supported calibration models (generated by `calibrate_propeller.ipynb`):**

| Key | Formula | Use case |
|-----|---------|----------|
| `linear` | `v = a + b·n` | Classic approach for propeller velocimeter |
| `poly2` | `v = a + b·n + c·n²` | Slight nonlinearity |
| `poly3` | `v = a + b·n + c·n² + d·n³` | Strong nonlinearity |
| `polyN` | degree-N polynomial | Arbitrary degree |
| `power` | `v = a·n^b` | Zero-offset sensors |
| `log` | `v = a + b·ln(n)` | Logarithmic response |

### Recording file format

Files are saved to `records/` inside the chosen folder.  
**Filename**: `record_{label}ID_{counter}_{DD_MM_YYYY}.txt`

```
# OTT Velocimeter ESP32 — Recording
# Date: 2026-04-07 14:32:11
# Interval (s): 1.0
# Mode: Count / ΔT
# Transitions/rev: 2
# Calibration: propeller=IMP1, function=0.05 + 0.025 * v
# ---
timestamp,elapsed_s,value
2026-04-07 14:32:12,1.0,0.525
2026-04-07 14:32:13,2.0,0.531
```

When settings change mid-session (**Apply to ESP** while recording), the current file is closed and a new one opened automatically with updated metadata.

---

## Calibration Workflow (`calibration/`)

### 1. Generate synthetic test data

Open `generate_synthetic_data.ipynb`. It creates five files for propeller IMP1:

```
synthetic_data/
├── Calibration_IMP1_0_3_mps.txt   (0.3 m/s)
├── Calibration_IMP1_0_6_mps.txt   (0.6 m/s)
├── Calibration_IMP1_0_9_mps.txt   (0.9 m/s)
├── Calibration_IMP1_1_2_mps.txt   (1.2 m/s)
└── Calibration_IMP1_1_5_mps.txt   (1.5 m/s)
```

Each file is a 30-second run with a ramp-up, constant-velocity plateau with noise, and ramp-down — matching the format produced by the app during a real flume calibration run.

### 2. Run the calibration notebook

Open `calibrate_propeller.ipynb`:

1. **Select files** — file picker or set `FILE_PATHS` manually
2. **Plateau detection** — trims the ramp fraction from each end, computes mean rev/s
3. **Fit models** — select which models to compare in `FIT_MODELS`, set `SELECTED_MODEL`
4. **Visual comparison** — calibration curves + residual bar chart for all models
5. **Export JSON** — writes `calibration_{PROP}_{MODEL}.json` to `Velocimeter_app/calibrationfiles/`

### Naming convention for calibration runs

```
Calibration_{PROPELLER_ID}_{V_integer}_{V_decimal}_mps.txt

Examples:
  Calibration_IMP1_0_3_mps.txt    →  0.3 m/s, propeller IMP1
  Calibration_IMP1_1_2_mps.txt    →  1.2 m/s, propeller IMP1
```

---

## Communication Protocol

### WiFi (TCP)

| Parameter | Value |
|-----------|-------|
| Architecture | ESP32 = TCP **server**; Python app = TCP **client** |
| ESP32 IP | `192.168.4.1` (fixed, AP mode) |
| Port | `8080` |
| Direction | ESP32 → Python (measurements); Python → ESP32 not supported over TCP |
| Format | ASCII float + `\r\n` per sample (e.g. `3.142\r\n`) |
| Rate | Configurable (default 1 sample/s) |

### USB Serial

| Parameter | Value |
|-----------|-------|
| Baud rate | 115200 |
| Direction | Bidirectional |
| ESP32 → Python | Same float format as TCP, plus status lines (`READY`, `OK ...`, `ERR ...`, `IP:...`) |
| Python → ESP32 | Config commands: `INTERVAL:x`, `MODE:x`, `TRANSITIONS:x`, `WIFI:ssid,pass` |

---

## Deployment Checklist

1. Flash the ESP32 with PlatformIO (**→ Upload**)
2. Connect laptop WiFi to **`OTT_ESPvelocimeter`** / `12345678`
3. Launch `uv run python Velocimeter_app/main.py`
4. Click **Connect ESP32 (WiFi)** — IP `192.168.4.1` should be pre-filled
5. Optionally: plug in USB, click **Connect USB**, then **Apply to ESP** to send custom settings
6. Load a calibration JSON for your propeller
7. Click **Start Recording** before each measurement run
