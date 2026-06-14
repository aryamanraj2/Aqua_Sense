/**
 * transport.cpp — Transport implementation (HTTP/JSON over SoftAP)
 *
 * Uses ArduinoHttpClient. Every method serialises its payload with
 * ArduinoJson, POSTs/GETs to the backend, and deserialises the response.
 * A future MQTT transport replaces only this file; all callers stay unchanged.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoHttpClient.h>
#include <ArduinoJson.h>
#include <string.h>
#include <stdio.h>
#include <time.h>

#include "transport.h"
#include "config.h"

// ── Internal helpers ──────────────────────────────────────────────────────────
static WiFiClient s_wifiClient;

static void isoTimestamp(char* buf, size_t len) {
    // Use NTP time if available; fall back to uptime string
    struct tm ti;
    if (getLocalTime(&ti, 100)) {
        strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", &ti);
    } else {
        snprintf(buf, len, "1970-01-01T00:00:%02luZ", millis() / 1000 % 60);
    }
}

// ── Public API ────────────────────────────────────────────────────────────────
void Transport::begin(const char* nodeId, const char* backendUrl) {
    strncpy(_nodeId,   nodeId,     sizeof(_nodeId)   - 1);
    strncpy(_baseUrl,  backendUrl, sizeof(_baseUrl)  - 1);
    Serial.printf("[TRANSPORT] Init — node=%s  backend=%s\n", _nodeId, _baseUrl);
}

bool Transport::registerNode(const char* fwVersion,
                              const char* hwRevision,
                              const NodeCapabilities& caps) {
    JsonDocument doc;
    doc["node_id"]           = _nodeId;
    doc["firmware_version"]  = fwVersion;
    doc["hardware_revision"] = hwRevision;

    JsonObject c = doc["capabilities"].to<JsonObject>();
    JsonArray  sensors = c["sensors"].to<JsonArray>();
    if (caps.has_ph)          sensors.add("ph");
    if (caps.has_turbidity)   sensors.add("turbidity");
    if (caps.has_do)          sensors.add("dissolved_oxygen");
    if (caps.has_temperature) sensors.add("temperature");

    JsonArray actuators = c["actuators"].to<JsonArray>();
    actuators.add("aerator");
    actuators.add("ph_doser");
    c["lora"]             = caps.has_lora;
    c["do_sensor_present"]= caps.has_do;

    char body[512];
    serializeJson(doc, body, sizeof(body));

    char resp[256];
    int code = _post("/nodes/register", body, resp, sizeof(resp));
    Serial.printf("[TRANSPORT] register → HTTP %d\n", code);
    return (code == 200 || code == 201);
}

bool Transport::postHeartbeat(const char* fwVersion,
                               const InterlockState& interlocks) {
    JsonDocument doc;
    doc["firmware_version"]             = fwVersion;
    doc["uptime_s"]                     = millis() / 1000;
    doc["interlock_state"]["do_floor_active"]   = interlocks.do_floor_active;
    doc["interlock_state"]["dose_rate_limited"] = interlocks.dose_rate_limited;
    doc["interlock_state"]["estop"]             = interlocks.estop;

    char body[256];
    serializeJson(doc, body, sizeof(body));

    char path[64];
    snprintf(path, sizeof(path), "/nodes/%s/heartbeat", _nodeId);

    char resp[128];
    int code = _post(path, body, resp, sizeof(resp));
    return (code == 200);
}

bool Transport::postTelemetry(const SensorReading& r,
                               const InterlockState& interlocks) {
    JsonDocument doc;
    doc["node_id"]          = _nodeId;
    doc["firmware_version"] = SENTINEL_FW_VERSION;

    char ts[32];
    isoTimestamp(ts, sizeof(ts));
    doc["sampled_at"] = ts;

    doc["interlock_state"]["do_floor_active"]   = interlocks.do_floor_active;
    doc["interlock_state"]["dose_rate_limited"] = interlocks.dose_rate_limited;
    doc["interlock_state"]["estop"]             = interlocks.estop;

    JsonArray readings = doc["readings"].to<JsonArray>();
    if (r.ph_valid) {
        JsonObject o = readings.add<JsonObject>();
        o["channel"] = "ph";  o["value"] = r.ph;
        o["unit"] = "pH";     o["quality"] = "ok";
    }
    if (r.temperature_valid) {
        JsonObject o = readings.add<JsonObject>();
        o["channel"] = "temperature"; o["value"] = r.temperature_c;
        o["unit"] = "C";              o["quality"] = "ok";
    }
    if (r.turbidity_valid) {
        JsonObject o = readings.add<JsonObject>();
        o["channel"] = "turbidity"; o["value"] = r.turbidity_ntu;
        o["unit"] = "NTU";          o["quality"] = "ok";
    }
    if (r.do_mg_l_valid) {
        JsonObject o = readings.add<JsonObject>();
        o["channel"] = "dissolved_oxygen"; o["value"] = r.do_mg_l;
        o["unit"] = "mg/L";               o["quality"] = "ok";
    }

    char body[1024];
    serializeJson(doc, body, sizeof(body));

    char path[64];
    snprintf(path, sizeof(path), "/nodes/%s/telemetry", _nodeId);

    char resp[128];
    int code = _post(path, body, resp, sizeof(resp));
    return (code == 200 || code == 202);
}

CommandList Transport::pollCommands() {
    CommandList list{};
    char path[64];
    snprintf(path, sizeof(path), "/nodes/%s/commands", _nodeId);

    char resp[2048];
    int code = _get(path, resp, sizeof(resp));
    if (code != 200) return list;

    JsonDocument doc;
    if (deserializeJson(doc, resp) != DeserializationError::Ok) return list;

    JsonArray cmds = doc["commands"].as<JsonArray>();
    for (JsonObject c : cmds) {
        if (list.count >= MAX_COMMANDS_PER_POLL) break;
        Command& cmd = list.items[list.count++];
        strncpy(cmd.id,       c["command_id"] | "", sizeof(cmd.id)       - 1);
        strncpy(cmd.actuator, c["actuator"]   | "", sizeof(cmd.actuator) - 1);
        strncpy(cmd.action,   c["action"]     | "", sizeof(cmd.action)   - 1);
        strncpy(cmd.reason,   c["reason"]     | "", sizeof(cmd.reason)   - 1);
        cmd.safety_critical = c["safety_critical"] | false;
        JsonObject p = c["params"].as<JsonObject>();
        cmd.param_on  = p["on"]  | 0.0f;
        cmd.param_ml  = p["ml"]  | 0.0f;
    }
    return list;
}

bool Transport::postAck(const char* commandId, const AckStatus& ack) {
    JsonDocument doc;
    doc["command_id"] = commandId;
    doc["status"]     = ack.status;
    doc["detail"]     = ack.detail;

    char ts[32];
    isoTimestamp(ts, sizeof(ts));
    doc["completed_at"] = ts;

    char body[256];
    serializeJson(doc, body, sizeof(body));

    char path[64];
    snprintf(path, sizeof(path), "/nodes/%s/ack", _nodeId);

    char resp[128];
    int code = _post(path, body, resp, sizeof(resp));
    return (code == 200);
}

// ── Low-level HTTP ────────────────────────────────────────────────────────────
void Transport::_buildNodeUrl(char* out, size_t len, const char* suffix) const {
    snprintf(out, len, "%s%s", _baseUrl, suffix);
}

int Transport::_post(const char* path, const char* body,
                     char* respBuf, size_t respLen) {
    // Parse host:port from _baseUrl (format: http://host:port/prefix)
    char host[64] = {};
    int  port     = 80;
    char prefix[64] = {};
    sscanf(_baseUrl, "http://%63[^:]:%d%63s", host, &port, prefix);

    char fullPath[128];
    snprintf(fullPath, sizeof(fullPath), "%s%s", prefix, path);

    HttpClient client(s_wifiClient, host, port);
    client.setTimeout(HTTP_TIMEOUT_MS);
    client.beginRequest();
    client.post(fullPath);
    client.sendHeader("Content-Type", "application/json");
    client.sendHeader("Content-Length", strlen(body));
    client.sendHeader("X-Node-ID", _nodeId);
    client.beginBody();
    client.print(body);
    client.endRequest();

    int code = client.responseStatusCode();
    String resp = client.responseBody();
    strncpy(respBuf, resp.c_str(), respLen - 1);
    client.stop();
    return code;
}

int Transport::_get(const char* path, char* respBuf, size_t respLen) {
    char host[64] = {};
    int  port     = 80;
    char prefix[64] = {};
    sscanf(_baseUrl, "http://%63[^:]:%d%63s", host, &port, prefix);

    char fullPath[128];
    snprintf(fullPath, sizeof(fullPath), "%s%s", prefix, path);

    HttpClient client(s_wifiClient, host, port);
    client.setTimeout(HTTP_TIMEOUT_MS);
    client.get(fullPath);

    int code = client.responseStatusCode();
    String resp = client.responseBody();
    strncpy(respBuf, resp.c_str(), respLen - 1);
    client.stop();
    return code;
}
