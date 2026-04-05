#include <Arduino.h>
#include <WiFi.h>

const char* ssid     = "TomBombadil";
const char* password = "0987654321";
const char* serverIP = "192.168.99.65";
const int   serverPort = 8080;

WiFiClient client;
bool wifiConnected = false;

// ── Propeller pins ────────────────────────────────────────────────────────────
const int fanPin = 17;
const int ledPin = 2;

// ── Interrupt state ───────────────────────────────────────────────────────────
// All times in microseconds for sub-millisecond period measurement.
const unsigned long DEBOUNCE_US = 15000;  // 15 ms

volatile unsigned long lastPulseTime_us = 0;
volatile int           fanCounter       = 0;

// Period-mode accumulators (reset each reporting window)
volatile unsigned long sumPeriods_us = 0;
volatile int           periodCount   = 0;

void IRAM_ATTR handleFanInterrupt() {
  unsigned long now = micros();
  if (now - lastPulseTime_us > DEBOUNCE_US) {
    if (lastPulseTime_us > 0) {
      // Accumulate inter-pulse period
      sumPeriods_us += (now - lastPulseTime_us);
      periodCount++;
    }
    fanCounter++;
    lastPulseTime_us = now;
  }
}

// ── Reporting configuration ───────────────────────────────────────────────────
// MODE 0 – count mode:  rev/s = fanCounter / interval_s
// MODE 1 – period mode: rev/s = 1 / mean_inter_pulse_period_s
unsigned long reportInterval_ms = 1000;  // default 1 s
int           reportMode        = 0;     // default count mode

unsigned long lastReportTime_ms = 0;

// ── LED ───────────────────────────────────────────────────────────────────────
unsigned long lastBlinkTime = 0;
bool          ledState      = LOW;

void nonBlockingLedBlink() {
  unsigned long now = millis();
  // Blink rate tracks reporting interval for visual feedback
  unsigned long blinkInterval = reportInterval_ms / 2;
  if (blinkInterval < 100) blinkInterval = 100;
  if (now - lastBlinkTime >= blinkInterval) {
    lastBlinkTime = now;
    ledState = !ledState;
    digitalWrite(ledPin, ledState);
  }
}

// ── Serial command parser ─────────────────────────────────────────────────────
// Accepted commands (newline-terminated):
//   INTERVAL:x.x   – set reporting interval in seconds (0.1 – 30)
//   MODE:0          – switch to count mode
//   MODE:1          – switch to period mode
void checkSerialCommands() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd.startsWith("INTERVAL:")) {
    float secs = cmd.substring(9).toFloat();
    if (secs >= 0.1f && secs <= 30.0f) {
      reportInterval_ms = (unsigned long)(secs * 1000.0f);
      Serial.print("OK INTERVAL:");
      Serial.println(secs, 3);
    }
  } else if (cmd.startsWith("MODE:")) {
    int mode = cmd.substring(5).toInt();
    if (mode == 0 || mode == 1) {
      reportMode = mode;
      Serial.print("OK MODE:");
      Serial.println(mode);
    }
  }
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // Connect to Wi-Fi (10 s timeout, then continue in serial-only mode)
  WiFi.begin(ssid, password);
  unsigned long wifiStart = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - wifiStart < 10000) {
    delay(500);
    Serial.println("Connecting to WiFi...");
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiConnected = true;
    Serial.println("Connected to WiFi");
  } else {
    Serial.println("WiFi not available, running in serial-only mode");
  }

  Serial.println("Setting Measurement...");

  pinMode(fanPin, INPUT_PULLUP);
  pinMode(ledPin, OUTPUT);
  attachInterrupt(digitalPinToInterrupt(fanPin), handleFanInterrupt, FALLING);

  lastReportTime_ms = millis();
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
  checkSerialCommands();
  nonBlockingLedBlink();

  unsigned long now = millis();
  if (now - lastReportTime_ms < reportInterval_ms) return;
  lastReportTime_ms = now;

  // Snapshot and reset accumulators (briefly disable interrupt for atomicity)
  noInterrupts();
  int   count     = fanCounter;
  unsigned long sumP = sumPeriods_us;
  int   nPeriods  = periodCount;
  fanCounter    = 0;
  sumPeriods_us = 0;
  periodCount   = 0;
  interrupts();

  float interval_s = reportInterval_ms / 1000.0f;
  float rps = 0.0f;

  if (reportMode == 0) {
    // Count mode
    rps = count / interval_s;
  } else {
    // Period mode: use mean inter-pulse interval
    if (nPeriods > 0) {
      float meanPeriod_s = (sumP / (float)nPeriods) / 1e6f;
      rps = 1.0f / meanPeriod_s;
    }
    // rps stays 0 if no pulses arrived this window
  }

  Serial.println(rps, 3);

  if (wifiConnected && client.connect(serverIP, serverPort)) {
    client.println(rps, 3);
    client.stop();
  }
}
