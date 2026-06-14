/**
 * main.cpp — AquaSense Sentinel Node firmware entry point
 *
 * Two-tier architecture: this node is the REFLEX tier. It reads sensors,
 * enforces local safety interlocks, and communicates with the AquaSense
 * backend (cognition tier) over HTTP/JSON on the node's SoftAP.
 *
 * Loop cadence:
 *   • Every TELEMETRY_INTERVAL_MS  → read all sensors, push telemetry
 *   • Every COMMAND_POLL_INTERVAL_MS → poll backend for actuator commands
 *   • Every HEARTBEAT_INTERVAL_MS  → push heartbeat + interlock snapshot
 *
 * Safety interlocks run on EVERY loop iteration regardless of network state.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>

#include "config.h"
#include "sensors.h"
#include "actuators.h"
#include "safety.h"
#include "transport.h"

// ── Node identity ─────────────────────────────────────────────────────────────
static char g_nodeId[32] = DEFAULT_NODE_ID;

// ── Subsystem instances ───────────────────────────────────────────────────────
static SensorHub   g_sensors;
static ActuatorHub g_actuators;
static SafetyMgr   g_safety;
static Transport   g_transport;

// ── Timing state ─────────────────────────────────────────────────────────────
static unsigned long g_lastTelemetry   = 0;
static unsigned long g_lastCommandPoll = 0;
static unsigned long g_lastHeartbeat   = 0;

// ── Prototypes ────────────────────────────────────────────────────────────────
static void loadNodeId();
static void startSoftAP();
static void runSafetyInterlocks(const SensorReading& r);
static void pushTelemetry(const SensorReading& r);
static void pollAndExecuteCommands();
static void pushHeartbeat();

// ─────────────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.printf("\n[SENTINEL] AquaSense Sentinel %s (%s) booting...\n",
                  SENTINEL_FW_VERSION, SENTINEL_HW_REVISION);

    loadNodeId();
    Serial.printf("[SENTINEL] Node ID: %s\n", g_nodeId);

    // Peripheral init
    g_sensors.begin();
    g_actuators.begin();
    g_safety.begin(&g_actuators);

    // Network
    startSoftAP();
    g_transport.begin(g_nodeId, BACKEND_URL);

    // Register with backend
    g_transport.registerNode(SENTINEL_FW_VERSION, SENTINEL_HW_REVISION,
                             g_sensors.capabilities());

    Serial.println("[SENTINEL] Boot complete — entering control loop");
}

void loop() {
    unsigned long now = millis();

    // ── 1. Read sensors (always) ─────────────────────────────────────────────
    SensorReading reading = g_sensors.read();

    // ── 2. Safety interlocks (always, before any network IO) ─────────────────
    runSafetyInterlocks(reading);

    // ── 3. Telemetry push ────────────────────────────────────────────────────
    if (now - g_lastTelemetry >= TELEMETRY_INTERVAL_MS) {
        pushTelemetry(reading);
        g_lastTelemetry = now;
    }

    // ── 4. Command poll ──────────────────────────────────────────────────────
    if (now - g_lastCommandPoll >= COMMAND_POLL_INTERVAL_MS) {
        pollAndExecuteCommands();
        g_lastCommandPoll = now;
    }

    // ── 5. Heartbeat ─────────────────────────────────────────────────────────
    if (now - g_lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
        pushHeartbeat();
        g_lastHeartbeat = now;
    }

    delay(100);
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

static void loadNodeId() {
    Preferences prefs;
    prefs.begin("sentinel", true);
    String id = prefs.getString(NODE_ID_NVS_KEY, DEFAULT_NODE_ID);
    prefs.end();
    id.toCharArray(g_nodeId, sizeof(g_nodeId));
}

static void startSoftAP() {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(SOFTAP_SSID, SOFTAP_PASS);
    Serial.printf("[NET] SoftAP up — SSID=%s  IP=%s\n",
                  SOFTAP_SSID, WiFi.softAPIP().toString().c_str());
}

static void runSafetyInterlocks(const SensorReading& r) {
    // DO floor interlock — aerator is forced ON below threshold
    if (r.do_mg_l_valid && r.do_mg_l < DO_FLOOR_MG_L) {
        if (!g_actuators.aeratorOn()) {
            g_actuators.setAerator(true);
            Serial.printf("[SAFETY] DO floor %.2f < %.2f mg/L — aerator FORCED ON\n",
                          r.do_mg_l, DO_FLOOR_MG_L);
        }
        g_safety.setDoFloorActive(true);
    } else {
        g_safety.setDoFloorActive(false);
    }

    // E-stop check (hardware pin / watchdog)
    g_safety.checkEstop();
}

static void pushTelemetry(const SensorReading& r) {
    InterlockState interlocks = g_safety.snapshot();
    bool ok = g_transport.postTelemetry(r, interlocks);
    if (!ok) {
        Serial.println("[NET] telemetry push failed — will retry next interval");
    }
}

static void pollAndExecuteCommands() {
    CommandList cmds = g_transport.pollCommands();
    for (const Command& cmd : cmds) {
        AckStatus result = g_safety.tryExecute(cmd, g_actuators);
        g_transport.postAck(cmd.id, result);
    }
}

static void pushHeartbeat() {
    InterlockState interlocks = g_safety.snapshot();
    g_transport.postHeartbeat(SENTINEL_FW_VERSION, interlocks);
}
