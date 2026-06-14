/**
 * actuators.cpp — ActuatorHub implementation
 */

#include <Arduino.h>
#include "actuators.h"
#include "config.h"

static constexpr unsigned long ROLLING_WINDOW_MS = 3600000UL;  // 1 hour
static constexpr float         ROLLING_CAP_ML    = 40.0f;

void ActuatorHub::begin() {
    pinMode(PIN_AERATOR, OUTPUT);
    pinMode(PIN_DOSER,   OUTPUT);
    digitalWrite(PIN_AERATOR, LOW);
    digitalWrite(PIN_DOSER,   LOW);
    _rollingWindowStart = millis();
    Serial.println("[ACTUATOR] Init complete — aerator OFF, doser OFF");
}

void ActuatorHub::setAerator(bool on) {
    if (_aeratorOn == on) return;
    _aeratorOn = on;
    digitalWrite(PIN_AERATOR, on ? HIGH : LOW);
    Serial.printf("[ACTUATOR] Aerator → %s\n", on ? "ON" : "OFF");
}

bool ActuatorHub::dose(float ml) {
    unsigned long now = millis();

    // Reset rolling window if expired
    if ((now - _rollingWindowStart) > ROLLING_WINDOW_MS) {
        _rollingDose        = 0.0f;
        _rollingWindowStart = now;
    }

    // Local rate-limit checks (mirror server-side bounds)
    if (ml <= 0.0f || ml > MAX_SINGLE_DOSE_ML) {
        Serial.printf("[ACTUATOR] Dose refused: %.1f mL out of bounds\n", ml);
        return false;
    }
    if ((now - _lastDoseMs) < MIN_DOSE_INTERVAL_MS && _lastDoseMs != 0) {
        Serial.printf("[ACTUATOR] Dose refused: interval %.0f s < %.0f s\n",
                      (now - _lastDoseMs) / 1000.0f,
                      MIN_DOSE_INTERVAL_MS / 1000.0f);
        return false;
    }
    if ((_rollingDose + ml) > ROLLING_CAP_ML) {
        Serial.printf("[ACTUATOR] Dose refused: rolling cap %.1f/%.1f mL\n",
                      _rollingDose, ROLLING_CAP_ML);
        return false;
    }

    // Run pump for the calculated duration
    unsigned long durationMs = (unsigned long)(ml / DOSE_ML_PER_MS);
    digitalWrite(PIN_DOSER, HIGH);
    delay(durationMs);
    digitalWrite(PIN_DOSER, LOW);

    _lastDoseMs    = now;
    _rollingDose  += ml;

    Serial.printf("[ACTUATOR] Dosed %.1f mL (rolling: %.1f/%.1f mL/hr)\n",
                  ml, _rollingDose, ROLLING_CAP_ML);
    return true;
}

float ActuatorHub::rollingDoseLastHour() const {
    return _rollingDose;
}
