#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>

// ── WiFi ──────────────────────────────────────────────────────────────────────
// Primary network: the ESP32 creates or joins this by default.
// Secondary network: saved to NVS via serial command  WIFI:ssid,password
const char* PRIMARY_SSID = "OTT_ESPvelocimeter";
const char* PRIMARY_PASS = "12345678";

const int   serverPort = 8080;

WiFiServer  tcpServer(serverPort);
WiFiClient  tcpClient;
Preferences prefs;
bool        wifiConnected = false;

// Try to connect to a given network; returns true if successful within timeout.
bool tryConnect(const char* ssid, const char* pass, unsigned long timeout_ms) {
  WiFi.disconnect(true);
  WiFi.begin(ssid, pass);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeout_ms) {
    delay(200);
    Serial.print(".");
  }
  Serial.println();
  return WiFi.status() == WL_CONNECTED;
}

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
//   INTERVAL:x.x        – set reporting interval in seconds (0.1–30)
//   MODE:0 / MODE:1     – count mode / period mode
//   WIFI:ssid,password  – save secondary WiFi credentials to NVS
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

  } else if (cmd.startsWith("WIFI:")) {
    // Format: WIFI:ssid,password
    String args  = cmd.substring(5);
    int    comma = args.indexOf(',');
    if (comma > 0) {
      String newSSID = args.substring(0, comma);
      String newPass = args.substring(comma + 1);
      prefs.begin("wifi", false);
      prefs.putString("ssid", newSSID);
      prefs.putString("pass", newPass);
      prefs.end();
      Serial.println("OK WIFI saved — reboot to apply");
    } else {
      Serial.println("ERR WIFI format: WIFI:ssid,password");
    }
  }
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Serial.println("Initializing — searching for WiFi...");

  // Load secondary WiFi credentials from NVS (empty strings if never saved).
  // Open read-write so the namespace is created on first boot if it doesn't exist.
  prefs.begin("wifi", false);
  String secSSID = prefs.isKey("ssid") ? prefs.getString("ssid") : "";
  String secPass = prefs.isKey("pass") ? prefs.getString("pass") : "";
  prefs.end();

  bool hasSecondary = secSSID.length() > 0;

  // Split the 10 s budget: 5 s each if a secondary exists, 10 s if not
  unsigned long primaryTimeout_ms   = hasSecondary ? 5000 : 10000;

  Serial.print("Trying primary WiFi (OTT_ESPvelocimeter)");
  wifiConnected = tryConnect(PRIMARY_SSID, PRIMARY_PASS, primaryTimeout_ms);

  if (!wifiConnected && hasSecondary) {
    Serial.print("Trying secondary WiFi (" + secSSID + ")");
    wifiConnected = tryConnect(secSSID.c_str(), secPass.c_str(), 5000);
  }

  if (wifiConnected) {
    tcpServer.begin();
    Serial.println("Connected to: " + String(WiFi.SSID()));
    Serial.println("IP:" + WiFi.localIP().toString());
  } else {
    Serial.println("WiFi unavailable — serial-only mode");
  }

  pinMode(fanPin, INPUT_PULLUP);
  pinMode(ledPin, OUTPUT);
  attachInterrupt(digitalPinToInterrupt(fanPin), handleFanInterrupt, FALLING);

  lastReportTime_ms = millis();

  // Signal to Python app that initialisation is complete and the timer can start
  Serial.println("READY");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
  checkSerialCommands();
  nonBlockingLedBlink();

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

  if (wifiConnected) {
    // Accept a new client if none is currently connected
    if (!tcpClient.connected()) {
      tcpClient = tcpServer.accept();
    }
    if (tcpClient.connected()) {
      tcpClient.println(rps, 3);
    }
  }
}
