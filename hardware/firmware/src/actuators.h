#pragma once
/**
 * actuators.h — ActuatorHub: GPIO control for aerator and peristaltic doser.
 *
 * Both actuators are driven by IRLZ44N low-side MOSFETs:
 *   HIGH → MOSFET ON  → load energised
 *   LOW  → MOSFET OFF → load de-energised
 *
 * Dose tracking is maintained here for local rate-limit enforcement (the
 * backend enforces the same limits server-side — defense in depth).
 */

#include <stdint.h>

class ActuatorHub {
public:
    void begin();

    // Aerator
    void setAerator(bool on);
    bool aeratorOn() const { return _aeratorOn; }

    // Doser — returns false if local rate-limit would be exceeded
    bool dose(float ml);
    float rollingDoseLastHour() const;

private:
    bool          _aeratorOn   = false;
    unsigned long _lastDoseMs  = 0;
    float         _rollingDose = 0.0f;        // mL dosed in the past hour
    unsigned long _rollingWindowStart = 0;    // millis() of window open
};
