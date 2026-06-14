#pragma once
/**
 * sensors.h — SensorHub: reads all analog sensors via TCA9548A + ADS1115,
 * and the DS18B20 temperature probe on OneWire.
 *
 * Calibration curves:
 *   pH        : linear 2-point (pH 4.0 / pH 7.0 buffer solutions)
 *   Turbidity : inverse linear (higher voltage → lower NTU for DFRobot SEN0189)
 *   DO        : temperature-compensated Winkler-derived curve (mg/L)
 */

#include <stdint.h>

struct SensorReading {
    float   ph;
    bool    ph_valid;

    float   turbidity_ntu;
    bool    turbidity_valid;

    float   do_mg_l;
    bool    do_mg_l_valid;      // false when DO module not fitted

    float   temperature_c;
    bool    temperature_valid;

    uint32_t sampled_at_ms;     // millis() at time of read
};

struct NodeCapabilities {
    bool has_ph;
    bool has_turbidity;
    bool has_do;
    bool has_temperature;
    bool has_lora;
};

class SensorHub {
public:
    void begin();
    SensorReading    read();
    NodeCapabilities capabilities() const;

private:
    bool _doPresent = false;

    void    _selectMuxChannel(uint8_t ch);
    float   _readAdsVoltage(uint8_t muxCh, uint8_t adsAddr);
    float   _voltsToPh(float v);
    float   _voltsToTurbidityNtu(float v);
    float   _voltsToDo(float v, float tempC);
};
