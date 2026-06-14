#pragma once
/**
 * safety.h — SafetyMgr: local non-overridable interlocks
 *
 * The cognition tier (backend + agent) issues REQUESTS. SafetyMgr decides
 * whether to honour them. Its decisions are final and are never retried by
 * the backend (see hardware_contract.md §4).
 *
 * Interlocks enforced here:
 *   DO_FLOOR   — aerator forced ON when DO < DO_FLOOR_MG_L
 *   DOSE_RATE  — dosing blocked by ActuatorHub rate-limits
 *   ESTOP      — GPIO-triggered or watchdog: all actuators disabled
 */

#include "actuators.h"
#include "sensors.h"

// ── Wire types shared with transport.h ───────────────────────────────────────
struct InterlockState {
    bool do_floor_active;
    bool dose_rate_limited;
    bool estop;
};

struct Command {
    char    id[24];
    char    actuator[16];   // "aerator" | "ph_doser"
    char    action[8];      // "set"     | "dose"
    float   param_on;       // aerator: 1=on 0=off
    float   param_ml;       // doser: mL to dose
    char    reason[128];
    bool    safety_critical;
};

struct AckStatus {
    char    command_id[24];
    char    status[12];     // "completed" | "failed" | "refused"
    char    detail[128];
};

// ── SafetyMgr ─────────────────────────────────────────────────────────────────
class SafetyMgr {
public:
    void begin(ActuatorHub* actuators);

    // Called every loop iteration regardless of network state
    void checkEstop();

    // Interlock flag setters (called from main.cpp after sensor read)
    void setDoFloorActive(bool active) { _state.do_floor_active = active; }

    // Try to execute a backend command; returns ack with status
    AckStatus tryExecute(const Command& cmd, ActuatorHub& actuators);

    // Snapshot for telemetry/heartbeat payloads
    InterlockState snapshot() const { return _state; }

private:
    ActuatorHub*   _actuators = nullptr;
    InterlockState _state     = {};

    static constexpr int ESTOP_PIN = 0;   // BOOT button doubles as e-stop
};
