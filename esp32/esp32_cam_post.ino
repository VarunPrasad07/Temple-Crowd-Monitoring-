// ESP32-CAM Crowd Counter
// Board: "AI Thinker ESP32-CAM" (or any standard ESP32)
//
// HOW IT SENDS COUNTS:
// 1. PULL Mode (Recommended): The ESP32 runs a local WebServer on Port 80.
//    Your PC / Dashboard requests: http://<ESP32_IP>/count
//    The ESP32 returns JSON: {"device_id":"CAM-01","gate_name":"Main Gate","direction":"entry","count":4}
//    and resets its counter.
//
// 2. PUSH Mode (Optional): If SERVER_URL is provided below, the ESP32 will also
//    periodically post its counts directly to your PC.

#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>

// ==================== [EDIT THESE SETTINGS] ====================
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

const char* DEVICE_ID = "CAM-01";       // Unique ID per camera
const char* GATE_NAME = "Main Gate";    // Gate name displayed on dashboard
const char* DIRECTION = "entry";        // "entry" or "exit"

// If you want ESP32 to also push to your computer, set your computer LAN IP here.
// Leave as empty string "" if you only want your computer to fetch by Camera IP.
const char* SERVER_URL = ""; 

const unsigned long PUSH_INTERVAL_MS = 10000;  // Push interval (if SERVER_URL is set)
#define SIMULATE_COUNT true                    // true = simulate people detection for testing
// ===============================================================

WebServer server(80);
volatile int pendingCount = 0;
unsigned long lastPush = 0;

// Call this function whenever your camera vision / sensor detects a person
void onPersonDetected() {
  pendingCount++;
}

// Handler: GET /count -> Returns JSON count & resets counter
void handleGetCount() {
  int countToSend = pendingCount;
  pendingCount = 0; // reset for next query

  String json = "{";
  json += "\"device_id\":\"" + String(DEVICE_ID) + "\",";
  json += "\"gate_name\":\""  + String(GATE_NAME) + "\",";
  json += "\"direction\":\""  + String(DIRECTION) + "\",";
  json += "\"count\":"        + String(countToSend) + ",";
  json += "\"ip\":\""         + WiFi.localIP().toString() + "\"";
  json += "}";

  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);

  Serial.printf("[HTTP GET /count] Responded with count: %d\n", countToSend);
}

// Handler: GET /status -> Health check
void handleStatus() {
  String json = "{";
  json += "\"device_id\":\"" + String(DEVICE_ID) + "\",";
  json += "\"online\":true,";
  json += "\"pending_count\":" + String(pendingCount) + ",";
  json += "\"ip\":\"" + WiFi.localIP().toString() + "\"";
  json += "}";

  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

// Handler: GET / -> Camera info
void handleRoot() {
  String html = "Temple Crowd Camera: " + String(DEVICE_ID) + " (" + String(GATE_NAME) + ")\n";
  html += "Status: Online\n";
  html += "Camera IP: " + WiFi.localIP().toString() + "\n";
  html += "Count Endpoint: http://" + WiFi.localIP().toString() + "/count\n";
  server.send(200, "text/plain", html);
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.println("====================================================");
  Serial.print("WiFi Connected! Camera IP Address: ");
  Serial.println(WiFi.localIP());
  Serial.print("Fetch live counts at: http://");
  Serial.print(WiFi.localIP());
  Serial.println("/count");
  Serial.println("====================================================");
}

// Optional Push to Server
bool sendPush(int count) {
  if (strlen(SERVER_URL) == 0 || WiFi.status() != WL_CONNECTED) return false;

  String body = "{\"device_id\":\"" + String(DEVICE_ID) + "\"," +
                "\"gate_name\":\""  + String(GATE_NAME) + "\"," +
                "\"direction\":\""  + String(DIRECTION) + "\"," +
                "\"ip\":\""         + WiFi.localIP().toString() + "\"," +
                "\"count\":"        + String(count) + "}";

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  Serial.printf("[PUSH to Server] POST %s -> HTTP %d\n", body.c_str(), code);
  http.end();

  return code == 200;
}

void setup() {
  Serial.begin(115200);
  connectWiFi();

  // Setup WebServer routes on Camera IP
  server.on("/", HTTP_GET, handleRoot);
  server.on("/count", HTTP_GET, handleGetCount);
  server.on("/status", HTTP_GET, handleStatus);
  server.begin();
  Serial.println("Camera HTTP Server started on port 80.");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();

  // Handle incoming HTTP requests from PC / Dashboard to Camera IP
  server.handleClient();

#if SIMULATE_COUNT
  // Generates occasional simulated count for testing
  if (random(0, 100) < 15) onPersonDetected();
#endif

  // Optional: Push to server if SERVER_URL is provided
  if (strlen(SERVER_URL) > 0 && millis() - lastPush >= PUSH_INTERVAL_MS) {
    lastPush = millis();
    if (sendPush(pendingCount)) {
      pendingCount = 0;
    }
  }

  delay(50);
}
