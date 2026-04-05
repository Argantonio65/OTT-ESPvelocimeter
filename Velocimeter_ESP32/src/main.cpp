#include <Arduino.h>
#include <WiFi.h>

// ── WiFi Access Point ─────────────────────────────────────────────────────────
// The ESP32 creates its own WiFi network.
// Connect your laptop to this network, then use the Python app to connect.
const char* AP_SSID = "OTT_ESPvelocimeter";
const char* AP_PASS = "12345678";

// Static IP for the ESP32 on its own AP network (always the same)
IPAddress AP_IP     (192, 168,   4,   1);
IPAddress AP_SUBNET (255, 255, 255,   0);

const int serverPort = 8080;

WiFiServer tcpServer(serverPort);
WiFiClient tcpClient;

// ── Propeller pins ────────────────────────────────────────────────────────────
const int fanPin = 17;
const int ledPin = 2;

// ── Interrupt state ───────────────────────────────────────────────────────────
const unsigned long DEBOUNCE_US = 15000;  // 15 ms

volatile unsigned long lastPulseTime_us = 0;
volatile int           fanCounter       = 0;
volatile unsigned long sumPeriods_us    = 0;
volatile int           periodCount      = 0;

void IRAM_ATTR handleFanInterrupt() {
  unsigned long now = micros();
  if (now - lastPulseTime_us > DEBOUNCE_US) {
    if (lastPulseTime_us > 0) {
      sumPeriods_us += (now - lastPulseTime_us);
      periodCount++;
    }
    fanCounter++;
    lastPulseTime_us = now;
  }
}

// ── Reporting configuration ───────────────────────────────────────────────────
// MODE 0 – count:  rev/s = fanCounter / interval_s
// MODE 1 – period: rev/s = 1 / mean_inter_pulse_period_s
unsigned long reportInterval_ms = 1000;
int           reportMode        = 0;
unsigned long lastReportTime_ms = 0;

// ── LED ───────────────────────────────────────────────────────────────────────
unsigned long lastBlinkTime = 0;
bool          ledState      = LOW;

void nonBlockingLedBlink() {
  unsigned long blinkInterval = max(reportInterval_ms / 2, (unsigned long)100);
  unsigned long now = millis();
  if (now - lastBlinkTime >= blinkInterval) {
    lastBlinkTime = now;
    ledState = !ledState;
    digitalWrite(ledPin, ledState);
  }
}

// ── Serial command parser ─────────────────────────────────────────────────────
// Commands (newline-terminated):
//   INTERVAL:x.x    – set reporting interval in seconds (0.1–30)
//   MODE:0 / MODE:1 – count mode / period mode
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
  Serial.println("Initializing — starting WiFi Access Point...");

  WiFi.softAPConfig(AP_IP, AP_IP, AP_SUBNET);
  WiFi.softAP(AP_SSID, AP_PASS);

  Serial.println("AP started: " + String(AP_SSID));
  Serial.println("IP:" + WiFi.softAPIP().toString());

  tcpServer.begin();

  pinMode(fanPin, INPUT_PULLUP);
  pinMode(ledPin, OUTPUT);
  attachInterrupt(digitalPinToInterrupt(fanPin), handleFanInterrupt, FALLING);

  lastReportTime_ms = millis();
  Serial.println("READY");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
  checkSerialCommands();
  nonBlockingLedBlink();

  // Accept new TCP client if none is connected
  if (!tcpClient.connected()) {
    tcpClient = tcpServer.accept();
  }

  unsigned long now = millis();
  if (now - lastReportTime_ms < reportInterval_ms) return;
  lastReportTime_ms = now;

  noInterrupts();
  int           count    = fanCounter;
  unsigned long sumP     = sumPeriods_us;
  int           nPeriods = periodCount;
  fanCounter    = 0;
  sumPeriods_us = 0;
  periodCount   = 0;
  interrupts();

  float interval_s = reportInterval_ms / 1000.0f;
  float rps = 0.0f;

  if (reportMode == 0) {
    rps = count / interval_s;
  } else {
    if (nPeriods > 0) {
      float meanPeriod_s = (sumP / (float)nPeriods) / 1e6f;
      rps = 1.0f / meanPeriod_s;
    }
  }

  Serial.println(rps, 3);

  if (tcpClient.connected()) {
    tcpClient.println(rps, 3);
  }
}
