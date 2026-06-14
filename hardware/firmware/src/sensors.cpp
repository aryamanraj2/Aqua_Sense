/**
 * sensors.cpp — SensorHub implementation
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <OneWire.h>
#include <DallasTemperature.h>

#include "sensors.h"
#include "config.h"

// ── Calibration constants ────────────────────────────────────────────────────
// pH: two-point calibration (update after field calibration)
static constexpr float PH_CAL_V_LOW  = 2.032f;  // ~pH 7.0 at 25 °C
static constexpr float PH_CAL_V_HIGH = 2.782f;  // ~pH 4.0 at 25 °C
static constexpr float PH_CAL_PH_LOW = 7.0f;
static constexpr float PH_CAL_PH_HIGH= 4.0f;

// Turbidity: DFRobot SEN0189 curve (V → NTU, valid 0–3000 NTU)
static constexpr float TURB_A = -1120.4f;
static constexpr float TURB_B =  5742.3f;
static constexpr float TURB_C = -4352.9f;

// DO: simplified Benson-Krause saturation curve coefficients
static constexpr float DO_SAT_A =  14.62f;
static constexpr float DO_SAT_B = -0.3947f;
static constexpr float DO_SAT_T_REF = 25.0f;

static Adafruit_ADS1115 s_adsPh;
static Adafruit_ADS1115 s_adsTurb;
static Adafruit_ADS1115 s_adsDo;

static OneWire           s_oneWire(ONE_WIRE_PIN);
static DallasTemperature s_tempSensor(&s_oneWire);

// ─────────────────────────────────────────────────────────────────────────────
void SensorHub::begin() {
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, I2C_FREQ_HZ);

    _selectMuxChannel(MUX_CH_PH);
    s_adsPh.setGain(ADS_GAIN);
    if (!s_adsPh.begin(ADS_ADDR_PH)) {
        Serial.println("[SENSOR] WARN: ADS1115 pH not found");
    }

    _selectMuxChannel(MUX_CH_TURBIDITY);
    s_adsTurb.setGain(ADS_GAIN);
    if (!s_adsTurb.begin(ADS_ADDR_TURB)) {
        Serial.println("[SENSOR] WARN: ADS1115 turbidity not found");
    }

    _selectMuxChannel(MUX_CH_DO);
    s_adsDo.setGain(ADS_GAIN);
    _doPresent = s_adsDo.begin(ADS_ADDR_DO);
    if (!_doPresent) {
        Serial.println("[SENSOR] INFO: DO module not fitted — readings omitted");
    }

    s_tempSensor.begin();
    s_tempSensor.setResolution(DS18B20_RESOLUTION);

    Serial.printf("[SENSOR] Init complete — DO module: %s\n",
                  _doPresent ? "present" : "absent");
}

SensorReading SensorHub::read() {
    SensorReading r{};
    r.sampled_at_ms = millis();

    // Temperature first (needed for DO compensation)
    s_tempSensor.requestTemperatures();
    float temp = s_tempSensor.getTempCByIndex(0);
    r.temperature_valid = (temp != DEVICE_DISCONNECTED_C);
    r.temperature_c     = r.temperature_valid ? temp : 25.0f;  // fallback for DO calc

    // pH
    float vPh = _readAdsVoltage(MUX_CH_PH, ADS_ADDR_PH);
    r.ph_valid = (vPh > 0.1f && vPh < 4.0f);
    r.ph       = r.ph_valid ? _voltsToPh(vPh) : 0.0f;

    // Turbidity
    float vTurb = _readAdsVoltage(MUX_CH_TURBIDITY, ADS_ADDR_TURB);
    r.turbidity_valid = (vTurb > 0.1f && vTurb < 4.5f);
    r.turbidity_ntu   = r.turbidity_valid ? _voltsToTurbidityNtu(vTurb) : 0.0f;

    // DO (optional)
    r.do_mg_l_valid = _doPresent;
    if (_doPresent) {
        float vDo = _readAdsVoltage(MUX_CH_DO, ADS_ADDR_DO);
        r.do_mg_l = _voltsToDo(vDo, r.temperature_c);
    }

    return r;
}

NodeCapabilities SensorHub::capabilities() const {
    return {
        .has_ph          = true,
        .has_turbidity   = true,
        .has_do          = _doPresent,
        .has_temperature = true,
        .has_lora        = true,
    };
}

// ── Private helpers ───────────────────────────────────────────────────────────
void SensorHub::_selectMuxChannel(uint8_t ch) {
    Wire.beginTransmission(MUX_ADDR);
    Wire.write(1 << ch);
    Wire.endTransmission();
    delayMicroseconds(200);
}

float SensorHub::_readAdsVoltage(uint8_t muxCh, uint8_t adsAddr) {
    _selectMuxChannel(muxCh);
    // Reuse the appropriate ADS instance based on address
    Adafruit_ADS1115* ads = (adsAddr == ADS_ADDR_PH)   ? &s_adsPh
                          : (adsAddr == ADS_ADDR_TURB)  ? &s_adsTurb
                                                         : &s_adsDo;
    int16_t raw = ads->readADC_SingleEnded(ADS_CHANNEL);
    return ads->computeVolts(raw);
}

float SensorHub::_voltsToPh(float v) {
    float slope = (PH_CAL_PH_HIGH - PH_CAL_PH_LOW) /
                  (PH_CAL_V_HIGH  - PH_CAL_V_LOW);
    return PH_CAL_PH_LOW + slope * (v - PH_CAL_V_LOW);
}

float SensorHub::_voltsToTurbidityNtu(float v) {
    // Quadratic fit: NTU = A*v^2 + B*v + C  (DFRobot datasheet)
    float ntu = TURB_A * v * v + TURB_B * v + TURB_C;
    return ntu < 0.0f ? 0.0f : ntu;
}

float SensorHub::_voltsToDo(float v, float tempC) {
    // DO saturation at tempC (simplified linear approximation)
    float sat = DO_SAT_A + DO_SAT_B * (tempC - DO_SAT_T_REF);
    // Assume 0 V = 0 mg/L, ~1.0 V = saturation (probe-specific)
    float fraction = v / 1.0f;
    float mg_l = sat * fraction;
    return mg_l < 0.0f ? 0.0f : mg_l;
}
