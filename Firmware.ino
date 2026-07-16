#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <time.h>
#include "secrets.h"

const char* WIFI_SSID     = WIFI_SSID_SECRET;
const char* WIFI_PASSWORD = WIFI_PASSWORD_SECRET;

const char* NOVA_BASE_URL   = NOVA_BASE_URL_SECRET;
const char* NOVA_PING_PATH  = "/";
const char* NOVA_SENSOR_PATH = "/sensor";

const char* N2YO_API_KEY = N2YO_API_KEY_SECRET;
const double OBSERVER_LAT = OBSERVER_LAT_SECRET;
const double OBSERVER_LNG = OBSERVER_LNG_SECRET;
const double OBSERVER_ALT = OBSERVER_ALT_SECRET;

const unsigned long PING_INTERVAL_MS = 10UL * 60UL * 1000UL;
const unsigned long ASK_INTERVAL_MS  = 5UL  * 60UL * 1000UL;
const unsigned long SAT_CHECK_INTERVAL_MS = 5UL * 60UL * 1000UL;

unsigned long lastPingTime = 0;
unsigned long lastAskTime  = 0;
unsigned long lastSatCheckTime = 0;

const char* SENSOR_CATEGORIES[] = { "sun", "earth", "mars", "moon", "saturn" };
const int NUM_SENSOR_CATEGORIES = sizeof(SENSOR_CATEGORIES) / sizeof(SENSOR_CATEGORIES[0]);
int nextCategoryIndex = 0;

struct TrackedSatellite {
  int noradId;
  const char* name;
  int priority;
};

TrackedSatellite trackedSats[] = {
  {25544, "ISS",         1},
  {48274, "Tiangong",    2},
  {20580, "Hubble",      3},
  {25994, "Terra",       4},
  {27424, "Aqua",        5},
  {27386, "Envisat",     6},
  {33591, "NOAA 19",     7},
  {28654, "NOAA 18",     8},
  {39084, "Landsat 8",   9},
  {49260, "Landsat 9",   10},
  {39634, "Sentinel-1A", 11},
  {40697, "Sentinel-2A", 12},
  {36585, "NAVSTAR 65 (USA 213)", 13},
  {44637, "TJS-4",       14},
  {22219, "Cosmos 2219", 15},
  {44932, "Starlink",    16},
};
const int NUM_TRACKED_SATS = sizeof(trackedSats) / sizeof(trackedSats[0]);

const double MIN_ELEVATION_DEG = 40.0;
const double MAX_MAGNITUDE     = 3.0;
const int    MIN_DURATION_SEC  = 60;

const int MAX_SAT_NOTIFICATIONS_PER_DAY = 4;
int satNotificationsToday = 0;
int lastResetDay = -1;

const long GMT_OFFSET_SEC = 5.5 * 3600;
const int DAYLIGHT_OFFSET_SEC = 0;
const char* NTP_SERVER = "pool.ntp.org";

// SETUP

void setup() {
  Serial.begin(115200);
  connectWiFi();
  configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET_SEC, NTP_SERVER);
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

  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  checkMidnightReset();

  if (now - lastPingTime >= PING_INTERVAL_MS) {
    lastPingTime = now;
    pingNova();
  }

  if (now - lastAskTime >= ASK_INTERVAL_MS) {
    lastAskTime = now;
    askNova();
  }

  if (now - lastSatCheckTime >= SAT_CHECK_INTERVAL_MS) {
    lastSatCheckTime = now;
    checkSatellites();
  }

  delay(100);
}

void checkMidnightReset() {
  time_t nowEpoch;
  time(&nowEpoch);
  struct tm timeinfo;

  if (!localtime_r(&nowEpoch, &timeinfo)) return;
  if (timeinfo.tm_year + 1900 < 2020) return;

  int today = timeinfo.tm_yday;

  if (lastResetDay == -1) {
    lastResetDay = today;
    return;
  }

  if (today != lastResetDay) {
    satNotificationsToday = 0;
    lastResetDay = today;
    Serial.println("[SatFilter] Midnight rollover — daily notification cap reset");
  }
}

// ==================== NOVA: PING (keep-alive) ====================

void pingNova() {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  String url = String(NOVA_BASE_URL) + NOVA_PING_PATH;
  http.begin(client, url);
  http.setTimeout(15000);

  int httpCode = http.GET();
  Serial.printf("[Ping] Nova status: %d\n", httpCode);
  http.end();
}

// ==================== NOVA: ASK (real data) ====================

void askNova() {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  String url = String(NOVA_BASE_URL) + NOVA_SENSOR_PATH;
  http.begin(client, url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(90000);

  const char* category = SENSOR_CATEGORIES[nextCategoryIndex];
  nextCategoryIndex = (nextCategoryIndex + 1) % NUM_SENSOR_CATEGORIES;

  String requestBody = "{\"category\": \"" + String(category) + "\"}";
  Serial.printf("[Ask] Requesting category: %s\n", category);

  int httpCode = http.POST(requestBody);

  if (httpCode == 200) {
    String response = http.getString();
    Serial.println("[Ask] Nova response: " + response);

    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, response);

    if (!err) {
      bool notify = doc["notify"] | false;
      const char* priority = doc["priority"] | "low";
      const char* reason = doc["reason"] | "";

      if (notify) {
        Serial.printf("[Ask] NOTIFY - priority: %s, reason: %s\n", priority, reason);
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

  for (int i = 0; i < NUM_TRACKED_SATS; i++) {
    if (satNotificationsToday >= MAX_SAT_NOTIFICATIONS_PER_DAY) break;

    bool qualifies = checkSinglePass(trackedSats[i]);
    if (qualifies) {
      satNotificationsToday++;
      Serial.printf("[SatFilter] NOTIFY - %s pass qualifies (visible)\n", trackedSats[i].name);
    }
  }
}

bool checkSinglePass(TrackedSatellite sat) {
  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  String url = "https://api.n2yo.com/rest/v1/satellite/visualpasses/"
               + String(sat.noradId) + "/"
               + String(OBSERVER_LAT, 6) + "/"
               + String(OBSERVER_LNG, 6) + "/"
               + String(OBSERVER_ALT, 1) + "/"
               + "1/"
               + String(MIN_DURATION_SEC)
               + "?apiKey=" + N2YO_API_KEY;

  http.begin(client, url);
  http.setTimeout(20000);
  int httpCode = http.GET();

  bool result = false;

  if (httpCode == 200) {
    String response = http.getString();

    DynamicJsonDocument doc(4096);
    DeserializationError err = deserializeJson(doc, response);

    if (!err && doc.containsKey("passes")) {
      JsonArray passes = doc["passes"];
      for (JsonObject pass : passes) {
        double maxEl = pass["maxEl"] | 0.0;
        double mag   = pass["mag"]   | 99.0;
        int duration  = pass["duration"] | 0;

        if (maxEl >= MIN_ELEVATION_DEG && mag <= MAX_MAGNITUDE && duration >= MIN_DURATION_SEC) {
          result = true;
          break;
        }
      }
    }
  } else {
    Serial.printf("[SatFilter] N2YO request failed for %s, code: %d\n", sat.name, httpCode);
  }

  http.end();
  return result;
}
