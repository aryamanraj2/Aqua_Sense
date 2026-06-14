#pragma once
/**
 * config.h — Sentinel node compile-time configuration
 *
 * Hardware constants mirror the safety contract in docs/hardware_contract.md.
 * Credentials are injected via build_flags in platformio.ini (never hard-coded
 * here). Override BACKEND_URL / AP credentials in a local secrets.h that is
 * listed in .gitignore.
 */

// ── Firmware identity ────────────────────────────────────────────────────────
#ifndef SENTINEL_FW_VERSION
#define SENTINEL_FW_VERSION "0.4.2"
#endif
#ifndef SENTINEL_HW_REVISION
#define SENTINEL_HW_REVISION "rev-C"
#endif

// ── I2C bus ──────────────────────────────────────────────────────────────────
#define I2C_SDA_PIN     8
#define I2C_SCL_PIN     9
#define I2C_FREQ_HZ     400000UL

// ── TCA9548A I2C multiplexer ─────────────────────────────────────────────────
#define MUX_ADDR        0x70   // ADDR pins tied LOW
#define MUX_CH_PH       0      // ADS1115 #0 — pH
#define MUX_CH_TURBIDITY 1     // ADS1115 #1 — turbidity
#define MUX_CH_DO       2      // ADS1115 #2 — dissolved oxygen (optional)

// ── ADS1115 ADCs ─────────────────────────────────────────────────────────────
#define ADS_ADDR_PH     0x48   // ADDR → GND
#define ADS_ADDR_TURB   0x49   // ADDR → VDD
#define ADS_ADDR_DO     0x4A   // ADDR → SDA
#define ADS_GAIN        GAIN_ONE   // ±4.096 V full-scale
#define ADS_CHANNEL     0          // single-ended A0 on each ADS

// ── DS18B20 temperature probe ────────────────────────────────────────────────
#define ONE_WIRE_PIN    10
#define DS18B20_RESOLUTION 12  // bits (0.0625 °C / LSB)

// ── Actuator GPIO (IRLZ44N low-side MOSFETs) ────────────────────────────────
#define PIN_AERATOR     4
#define PIN_DOSER       5

// ── LoRa SX1278 ──────────────────────────────────────────────────────────────
#define LORA_SCK        36
#define LORA_MISO       37
#define LORA_MOSI       35
#define LORA_CS         34
#define LORA_RST        33
#define LORA_DIO0       38
#define LORA_FREQ_HZ    433E6

// ── Safety thresholds (non-overridable by backend) ──────────────────────────
#ifndef DO_FLOOR_MG_L
#define DO_FLOOR_MG_L   4.0f   // force aerator ON below this DO
#endif
#ifndef MAX_SINGLE_DOSE_ML
#define MAX_SINGLE_DOSE_ML 15.0f
#endif
#ifndef MIN_DOSE_INTERVAL_MS
#define MIN_DOSE_INTERVAL_MS 600000UL  // 10 min
#endif
#define DOSE_ML_PER_MS  (1.0f / 600.0f)  // peristaltic pump calibration

// ── Telemetry / heartbeat timing ─────────────────────────────────────────────
#define TELEMETRY_INTERVAL_MS   30000UL   // 30 s between pushes
#define COMMAND_POLL_INTERVAL_MS 5000UL   // 5 s command poll
#define HEARTBEAT_INTERVAL_MS   60000UL   // 60 s heartbeat

// ── Backend API ──────────────────────────────────────────────────────────────
#ifndef BACKEND_URL
#define BACKEND_URL "http://192.168.4.2:8000/api/v1"
#endif
#define HTTP_TIMEOUT_MS 8000

// ── Node identity (set per-device via NVS at provisioning time) ──────────────
#define NODE_ID_NVS_KEY  "node_id"
#define DEFAULT_NODE_ID  "sentinel-000000"
