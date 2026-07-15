/*
 * ASNS - Ambient Space Notification System
 * ESP32-WROVER-IE Firmware Skeleton
 *
 * Handles:
 *   1. WiFi connection
 *   2. Keep-alive ping to Nova (Render free tier, prevents spin-down)
 *   3. Data ask to Nova (/sensor endpoint, AI-filtered categories)
 *   4. On-device satellite filter (N2YO visual passes, no Nova round-trip)
 *
 * NOT included yet: LED strip driving, LVGL display, touch buttons.
 * This is the networking + filtering skeleton to build those on top of.
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>   // install via Library Manager: "ArduinoJson" by Benoit Blanchon

// ==================== CONFIG ====================

// WiFi credentials
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Nova backend (Render, Singapore region)
const char* NOVA_BASE_URL   = "https://your-nova-url.onrender.com";
const char* NOVA_PING_PATH  = "/";         // existing lightweight status endpoint
const char* NOVA_SENSOR_PATH = "/sensor";  // to be built on Nova's side (POST)

// N2YO API (satellite tracking)
const char* N2YO_API_KEY = "YOUR_N2YO_API_KEY";
// Observer location — set to your desk's approximate lat/lon/alt(m)
const double OBSERVER_LAT = 0.0;   // TODO: fill in
const double OBSERVER_LNG = 0.0;   // TODO: fill in
const double OBSERVER_ALT = 0.0;   // meters above sea level

// Timers
const unsigned long PING_INTERVAL_MS = 10UL * 60UL * 1000UL;   // 10 min — keep Nova warm
const unsigned long ASK_INTERVAL_MS  = 5UL  * 60UL * 1000UL;   // 5 min  — real data poll
const unsigned long SAT_CHECK_INTERVAL_MS = 5UL * 60UL * 1000UL; // 5 min — satellite filter pass

unsigned long lastPingTime = 0;
unsigned long lastAskTime  = 0;
unsigned long lastSatCheckTime = 0;

// ==================== SATELLITE FILTER CONFIG ====================

// Fixed priority list — NORAD Catalog IDs (fill in real values)
// Priority order matters: used for tie-breaking when multiple passes qualify same day
struct TrackedSatellite {
  int noradId;
  const char* name;
  int priority; // lower = higher priority
};

TrackedSatellite trackedSats[] = {
  {25544, "ISS",      1},
  {48274, "Tiangong", 2},
  {20580, "Hubble",   3},
  // TODO: add remaining fixed-list satellites (Terra, Aqua, Envisat, etc.)
  // TODO: add Starlink launch-train dynamic slot separately (not a fixed NORAD ID)
};
const int NUM_TRACKED_SATS = sizeof(trackedSats) / sizeof(trackedSats[0]);

// Visual pass thresholds (see earlier filter design discussion)
const double MIN_ELEVATION_DEG = 40.0;
const double MAX_MAGNITUDE     = 3.0;
const int    MIN_DURATION_SEC  = 60;

// Daily satellite notification cap — SEPARATE budget from AI categories
const int MAX_SAT_NOTIFICATIONS_PER_DAY = 4;
int satNotificationsToday = 0;
// TODO: reset satNotificationsToday at local midnight (needs RTC or NTP time sync)

// ==================== SETUP ====================

void setup() {
  Serial.begin(115200);
  connectWiFi();
}

void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected. IP: " + WiFi.localIP().toString());
}

// ==================== MAIN LOOP ====================

void loop() {
  unsigned long now = millis();

  // Reconnect WiFi if dropped
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  // Timer 1: keep-alive ping
  if (now - lastPingTime >= PING_INTERVAL_MS) {
    lastPingTime = now;
    pingNova();
  }

  // Timer 2: ask Nova for AI-filtered category data
  if (now - lastAskTime >= ASK_INTERVAL_MS) {
    lastAskTime = now;
    askNova();
  }

  // Timer 3: on-device satellite filter check
  if (now - lastSatCheckTime >= SAT_CHECK_INTERVAL_MS) {
    lastSatCheckTime = now;
    checkSatellites();
  }

  // TODO: LED/display update logic goes here, driven by results of
  // askNova() and checkSatellites() — currently those just Serial.print()
}

// ==================== NOVA: PING (keep-alive) ====================

void pingNova() {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClientSecure client;
  client.setInsecure(); // TODO: replace with proper cert validation before shipping

  HTTPClient http;
  String url = String(NOVA_BASE_URL) + NOVA_PING_PATH;
  http.begin(client, url);
  http.setTimeout(15000); // ping should be fast; short timeout is fine

  int httpCode = http.GET();
  Serial.printf("[Ping] Nova status: %d\n", httpCode);
  http.end();
}

// ==================== NOVA: ASK (real data) ====================

void askNova() {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClientSecure client;
  client.setInsecure(); // TODO: replace with proper cert validation before shipping

  HTTPClient http;
  String url = String(NOVA_BASE_URL) + NOVA_SENSOR_PATH;
  http.begin(client, url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(90000); // generous — covers Render cold-start worst case

  // TODO: rotate/cycle which category is asked about, or ask Nova to
  // check all 5 AI categories (Sun/Earth/Mars/Moon/Saturn) in one call —
  // depends on how /sensor ends up structured on Nova's side
  String requestBody = "{\"query\": \"any new solar or earth activity?\"}";

  int httpCode = http.POST(requestBody);

  if (httpCode == 200) {
    String response = http.getString();
    Serial.println("[Ask] Nova response: " + response);

    // Parse expected shape: {"notify": bool, "priority": "...", "reason": "..."}
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, response);

    if (!err) {
      bool notify = doc["notify"] | false;
      const char* priority = doc["priority"] | "low";
      const char* reason = doc["reason"] | "";

      if (notify) {
        Serial.printf("[Ask] NOTIFY - priority: %s, reason: %s\n", priority, reason);
        // TODO: trigger LED/display notification here
      }
    } else {
      Serial.println("[Ask] JSON parse failed");
    }
  } else {
    Serial.printf("[Ask] Request failed, code: %d\n", httpCode);
  }

  http.end();
}

// ==================== SATELLITE FILTER (on-device, no Nova) ====================

void checkSatellites() {
  if (satNotificationsToday >= MAX_SAT_NOTIFICATIONS_PER_DAY) {
    Serial.println("[SatFilter] Daily satellite cap reached, skipping check");
    return;
  }

  if (WiFi.status() != WL_CONNECTED) return;

  // Loop through fixed priority list, checking N2YO visual pass data for each
  for (int i = 0; i < NUM_TRACKED_SATS; i++) {
    if (satNotificationsToday >= MAX_SAT_NOTIFICATIONS_PER_DAY) break;

    bool qualifies = checkSinglePass(trackedSats[i]);
    if (qualifies) {
      satNotificationsToday++;
      Serial.printf("[SatFilter] NOTIFY - %s pass qualifies (visible)\n", trackedSats[i].name);
      // TODO: trigger LED/display notification here
      // Priority order (trackedSats is already ordered by priority) means
      // ISS/Tiangong/Hubble get checked and would notify before lower-priority sats
    }
  }
}

// Checks N2YO's visual passes endpoint for a single satellite,
// applies elevation/magnitude/duration thresholds.
// Returns true if a qualifying visible pass is found.
bool checkSinglePass(TrackedSatellite sat) {
  WiFiClientSecure client;
  client.setInsecure(); // TODO: replace with proper cert validation before shipping

  HTTPClient http;
  // N2YO "visualpasses" endpoint: days=1, min visible pass duration threshold
  String url = "https://api.n2yo.com/rest/v1/satellite/visualpasses/"
               + String(sat.noradId) + "/"
               + String(OBSERVER_LAT, 6) + "/"
               + String(OBSERVER_LNG, 6) + "/"
               + String(OBSERVER_ALT, 1) + "/"
               + "1/" // days
               + String(MIN_DURATION_SEC) + "/"
               + "&apiKey=" + N2YO_API_KEY;

  http.begin(client, url);
  http.setTimeout(20000);
  int httpCode = http.GET();

  bool result = false;

  if (httpCode == 200) {
    String response = http.getString();

    // N2YO responses can be sizeable with multiple passes — adjust buffer if needed
    DynamicJsonDocument doc(4096);
    DeserializationError err = deserializeJson(doc, response);

    if (!err && doc.containsKey("passes")) {
      JsonArray passes = doc["passes"];
      for (JsonObject pass : passes) {
        double maxEl = pass["maxEl"] | 0.0;
        double mag   = pass["mag"]   | 99.0; // N2YO uses high number if no mag data
        int duration  = pass["duration"] | 0;

        if (maxEl >= MIN_ELEVATION_DEG && mag <= MAX_MAGNITUDE && duration >= MIN_DURATION_SEC) {
          result = true;
          break; // one qualifying pass is enough to notify for this satellite today
        }
      }
    }
  } else {
    Serial.printf("[SatFilter] N2YO request failed for %s, code: %d\n", sat.name, httpCode);
  }

  http.end();
  return result;
}

/*
 * TODO NEXT STEPS:
 * - Fill in WiFi/Nova URL/N2YO key/observer lat-lon placeholders
 * - Add remaining satellites to trackedSats[] (Terra, Aqua, Envisat, rocket bodies)
 * - Add Starlink launch-train dynamic detection (separate from fixed list)
 * - Add midnight reset for satNotificationsToday (needs NTP time sync via configTime())
 * - Wire LED strip (WS2812B, FastLED or Adafruit_NeoPixel library)
 * - Wire LVGL display + touch buttons
 * - Build /sensor endpoint on Nova's side to match expected request/response shape
 * - Replace client.setInsecure() with proper root CA validation before final build
 */
