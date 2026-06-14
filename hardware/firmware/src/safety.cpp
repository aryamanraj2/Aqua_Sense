/**
 * safety.cpp — SafetyMgr implementation
 *
 * tryExecute() is the single gate every backend command passes through.
 * Refusals are authoritative: the return status propagates back to the backend
 * via Transport::postAck(), which marks the command "refused" and escalates
 * safety-critical ones for human intervention. Auto-retry never happens.
 */

#include <Arduino.h>
#include <string.h>
#include "safety.h"
#include "config.h"

void SafetyMgr::begin(ActuatorHub* actuators) {
    _actuators = actuators;
    pinMode(ESTOP_PIN, INPUT_PULLUP);
    Serial.println("[SAFETY] SafetyMgr online");
}

void SafetyMgr::checkEstop() {
    // Active-low: BOOT button pulled LOW = e-stop triggered
    bool triggered = (digitalRead(ESTOP_PIN) == LOW);
    if (triggered && !_state.estop) {
        Serial.println("[SAFETY] E-STOP TRIGGERED — all actuators disabled");
        _actuators->setAerator(false);
    }
    _state.estop = triggered;
}

AckStatus SafetyMgr::tryExecute(const Command& cmd, ActuatorHub& actuators) {
    AckStatus ack{};
    strncpy(ack.command_id, cmd.id, sizeof(ack.command_id) - 1);

    // ── Global e-stop blocks everything ──────────────────────────────────────
    if (_state.estop) {
        snprintf(ack.detail, sizeof(ack.detail),
                 "refused: e-stop active");
        strncpy(ack.status, "refused", sizeof(ack.status) - 1);
        Serial.printf("[SAFETY] cmd %s refused (e-stop)\n", cmd.id);
        return ack;
    }

    // ── Aerator command ───────────────────────────────────────────────────────
    if (strncmp(cmd.actuator, "aerator", 7) == 0) {
        bool wantOn = (cmd.param_on > 0.5f);

        // DO floor overrides "turn aerator off" when DO is critical
        if (!wantOn && _state.do_floor_active) {
            snprintf(ack.detail, sizeof(ack.detail),
                     "refused: local DO interlock active");
            strncpy(ack.status, "refused", sizeof(ack.status) - 1);
            Serial.printf("[SAFETY] cmd %s refused (DO floor active)\n", cmd.id);
            return ack;
        }

        actuators.setAerator(wantOn);
        snprintf(ack.detail, sizeof(ack.detail),
                 "aerator %s", wantOn ? "energised" : "de-energised");
        strncpy(ack.status, "completed", sizeof(ack.status) - 1);
        return ack;
    }

    // ── Doser command ─────────────────────────────────────────────────────────
    if (strncmp(cmd.actuator, "ph_doser", 8) == 0) {
        if (_state.dose_rate_limited) {
            snprintf(ack.detail, sizeof(ack.detail),
                     "refused: dose_rate_limited interlock active");
            strncpy(ack.status, "refused", sizeof(ack.status) - 1);
            return ack;
        }

        bool ok = actuators.dose(cmd.param_ml);
        if (ok) {
            snprintf(ack.detail, sizeof(ack.detail),
                     "dosed %.1f mL", cmd.param_ml);
            strncpy(ack.status, "completed", sizeof(ack.status) - 1);
        } else {
            snprintf(ack.detail, sizeof(ack.detail),
                     "refused: local dose rate-limit exceeded");
            strncpy(ack.status, "refused", sizeof(ack.status) - 1);
            _state.dose_rate_limited = true;
        }
        return ack;
    }

    // ── Unknown actuator ──────────────────────────────────────────────────────
    snprintf(ack.detail, sizeof(ack.detail),
             "failed: unknown actuator '%s'", cmd.actuator);
    strncpy(ack.status, "failed", sizeof(ack.status) - 1);
    return ack;
}
