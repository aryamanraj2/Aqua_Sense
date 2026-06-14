# Sentinel Node — Wiring Diagram (rev-C)

All signal lines are 3.3 V logic. The 12 V rail powers pumps only.
Pull-up/pull-down resistors are omitted from the ASCII diagram for clarity —
see the BOM for values.

```
                        ┌─────────────────────────────┐
          12V IN ───────┤ LM2596 step-down             ├──── 5V rail
                        │ (12V → 5V / 3A)              │
                        └──────────────┬──────────────┘
                                       │ 5V → 3.3V (ESP32-S3 onboard LDO)
                                       │
                    ┌──────────────────▼───────────────────────┐
                    │           ESP32-S3-WROOM-1                │
                    │                                           │
                    │  GPIO8  (SDA) ──────────────────────────► I2C bus
                    │  GPIO9  (SCL) ──────────────────────────► I2C bus
                    │  GPIO10 (OneWire) ──────────────────────► DS18B20
                    │  GPIO4  (AERATOR_PWM) ──────────────────► MOSFET #1 gate
                    │  GPIO5  (DOSER_PWM)  ──────────────────► MOSFET #2 gate
                    │  GPIO0  (ESTOP — active LOW, pull-up)    │
                    │                                           │
                    │  SPI bus (LoRa SX1278):                   │
                    │  GPIO36 (SCK)  GPIO37 (MISO)             │
                    │  GPIO35 (MOSI) GPIO34 (CS)               │
                    │  GPIO33 (RST)  GPIO38 (DIO0)             │
                    └───────────────────────────────────────────┘

── I2C bus (SDA/SCL) ────────────────────────────────────────────────────────

  I2C bus
    │
    ├──► TCA9548A (addr 0x70)  ← 8-channel I2C mux
    │       │
    │       ├── CH0 ──► ADS1115 #0 (addr 0x48)  ← pH electrode via BNC
    │       ├── CH1 ──► ADS1115 #1 (addr 0x49)  ← turbidity sensor
    │       └── CH2 ──► ADS1115 #2 (addr 0x4A)  ← DO probe (optional)
    │
    └── (direct) TCA9548A itself is on the main I2C bus

── Analog sensors → ADS1115 (each on its own mux channel) ──────────────────

  pH electrode (BNC)  ──► pH board signal out ──► ADS1115 #0  A0
  Turbidity sensor    ──► signal out (0–4.5V)  ──► ADS1115 #1  A0
  DO probe (BNC)      ──► DO board signal out  ──► ADS1115 #2  A0

  All sensor boards powered from 5V rail.
  ADS1115 ADDR pin wiring:
    #0 (pH)       → GND  = 0x48
    #1 (turbidity)→ VDD  = 0x49
    #2 (DO)       → SDA  = 0x4A

── Temperature ───────────────────────────────────────────────────────────────

  DS18B20 (waterproof) ──► GPIO10 (OneWire)
  4.7kΩ pull-up between DQ and 3.3V

── Actuators (low-side MOSFET switch) ───────────────────────────────────────

  GPIO4 ──[10kΩ pull-down]──► IRLZ44N #1 gate
                               IRLZ44N #1 drain ──► Air pump (–) terminal
                               Air pump (+)      ──► 12V rail
                               1N4007 flyback across pump terminals

  GPIO5 ──[10kΩ pull-down]──► IRLZ44N #2 gate
                               IRLZ44N #2 drain ──► Peristaltic pump (–)
                               Pump (+)          ──► 12V rail
                               1N4007 flyback across pump terminals

  Both MOSFET sources → GND (common ground with 12V supply)

── LoRa SX1278 (Ra-02 module) ────────────────────────────────────────────────

  Ra-02 VCC  → 3.3V
  Ra-02 GND  → GND
  Ra-02 SCK  → GPIO36
  Ra-02 MISO → GPIO37
  Ra-02 MOSI → GPIO35
  Ra-02 NSS  → GPIO34
  Ra-02 RST  → GPIO33
  Ra-02 DIO0 → GPIO38

── Power rail summary ────────────────────────────────────────────────────────

  12V (barrel jack)
   ├── LM2596 in  → 5V rail
   │     ├── ESP32-S3 5V pin  (onboard LDO → 3.3V for MCU + I2C peripherals)
   │     ├── pH board VCC
   │     ├── Turbidity board VCC
   │     └── DO board VCC
   ├── Air pump 12V+
   └── Peristaltic pump 12V+
```

## Notes

- Keep analog sensor signal wires short (<15 cm) and away from pump leads to
  minimise EMI on the ADC inputs.
- The DO probe requires a 5–10 min warm-up after power-on before readings
  stabilise — the firmware discards readings tagged `quality: stale` during
  this window.
- The e-stop input (GPIO0 / BOOT button) is active-LOW with internal pull-up.
  Connecting a normally-closed emergency button here gives hardware-level
  actuator cutoff independent of firmware state.
