# Sentinel Node — Bill of Materials (rev-C)

> Quantities are per node. Prices are approximate retail (Mouser/LCSC/AliExpress, June 2026).

## Microcontroller

| Qty | Part | Manufacturer | MPN | ~Cost |
|-----|------|-------------|-----|-------|
| 1 | ESP32-S3-WROOM-1-N16R8 | Espressif | ESP32-S3-WROOM-1-N16R8 | $4.50 |

## Analog front-end

| Qty | Part | Description | MPN | ~Cost |
|-----|------|-------------|-----|-------|
| 3 | ADS1115 | 16-bit ADC, I2C, 4-ch | TI ADS1115IDGSR | $2.10 ea |
| 1 | TCA9548A | 8-ch I2C multiplexer | TI TCA9548APWR | $1.80 |

## Sensors

| Qty | Part | Description | ~Cost |
|-----|------|-------------|-------|
| 1 | DFRobot SEN0169 | Analog pH electrode + BNC adapter | $29.00 |
| 1 | DFRobot SEN0189 | Analog turbidity sensor | $9.90 |
| 1 | DFRobot SEN0237-A | Analog dissolved oxygen probe + board | $69.00 |
| 1 | DS18B20 (waterproof) | OneWire temperature probe, stainless | $3.50 |

> The DO sensor (SEN0237-A) is **modular** — the firmware and backend handle
> its absence gracefully (`do_sensor_present: false` in capabilities).

## Actuators & drivers

| Qty | Part | Description | MPN | ~Cost |
|-----|------|-------------|-----|-------|
| 2 | IRLZ44N | Logic-level N-MOSFET (low-side switch) | Infineon IRLZ44NPBF | $0.85 ea |
| 2 | 1N4007 | Flyback diode (relay/pump protection) | — | $0.05 ea |
| 2 | 10 kΩ | Gate pull-down resistor | — | $0.01 ea |
| 1 | Air pump (6 V, 2 W) | Aerator — aquarium-grade, pond size | — | $6.00 |
| 1 | Peristaltic pump (12 V) | pH buffer doser, ~60 mL/min | DF Robot FIT0138 | $18.00 |

## Wireless

| Qty | Part | Description | MPN | ~Cost |
|-----|------|-------------|-----|-------|
| 1 | Ra-02 SX1278 | 433 MHz LoRa module (SPI) | AI-Thinker Ra-02 | $4.20 |

## Power

| Qty | Part | Description | ~Cost |
|-----|------|-------------|-------|
| 1 | LM2596 step-down | 12 V → 5 V / 3 A for MCU + sensors | $1.50 |
| 1 | 12 V / 2 A barrel jack adapter | Powers pumps + regulator | $3.00 |
| 1 | 100 µF / 25 V electrolytic | Bulk decoupling on 12 V rail | $0.20 |
| 2 | 10 µF / 10 V ceramic | Decoupling on 3.3 V and 5 V rails | $0.10 ea |

## Passives & connectors

| Qty | Part | ~Cost |
|-----|------|-------|
| 1 | 4.7 kΩ resistor | DS18B20 OneWire pull-up | $0.01 |
| 1 | 2-pin screw terminal (3.5 mm) ×4 | Aerator, doser, power in, spare | $0.40 |
| 1 | BNC panel socket ×2 | pH + DO probe connections | $1.20 |
| 1 | IP65 enclosure (120×80×50 mm) | Weatherproofing | $6.00 |

## Total estimated BOM cost (per node)

| Section | Subtotal |
|---------|----------|
| MCU | $4.50 |
| Analog front-end | $7.80 |
| Sensors | $111.40 |
| Actuators & drivers | $26.82 |
| Wireless | $4.20 |
| Power | $4.90 |
| Passives & connectors | $1.62 |
| **Total** | **~$161** |
