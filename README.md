# AquaSense — Autonomous Aquaculture Intelligence

> **Perceive → Reason → Act → Observe → Escalate**
> A two-tier autonomous control system for smart fish farming.

AquaSense closes the loop between physical pond sensors and an LLM-powered
cognition engine. The **Sentinel node** (ESP32-S3) reads water quality in
real time and drives actuators. The **AquaSense backend** runs a Gemini agent
that reasons over the data and issues actuator commands — which the node may
refuse if a local safety interlock is active.

---

## Architecture

```
┌──────────────────────────────────┐   HTTP/JSON (SoftAP)   ┌────────────────────────────────┐
│  REFLEX TIER — Sentinel Node     │ ─────────────────────► │ COGNITION TIER — AquaSense     │
│  ESP32-S3 · hardware/firmware/   │  POST /telemetry        │ Backend · aquasense_backend/   │
│                                  │ ◄───────────────────── │                                │
│  Sensors                         │  GET  /commands (poll)  │  FastAPI + SQLite              │
│  ├─ pH        (ADS1115 + BNC)    │  POST /ack              │  Gemini AI agent               │
│  ├─ Turbidity (ADS1115)          │  POST /heartbeat        │  RandomForest water-quality ML │
│  ├─ DO        (ADS1115, optional)│                         │  WebSocket voice agent         │
│  └─ Temp      (DS18B20)          │                         │                                │
│                                  │                         │  iOS app  ·  IOS/              │
│  Actuators                       │                         │  Android  ·  app/              │
│  ├─ Aerator   (IRLZ44N MOSFET)   │                         └────────────────────────────────┘
│  └─ pH doser  (peristaltic pump) │
│                                  │
│  LOCAL SAFETY INTERLOCKS         │
│  (non-overridable by backend)    │
└──────────────────────────────────┘
```

**Golden rule:** commands from the cognition tier are **requests, not orders**.
The Sentinel node owns safety. It can refuse any command that would violate a
local interlock — and that refusal is authoritative and final.

---

## Repo structure

```
Aqua_Sense/
├── hardware/                   # Sentinel node firmware + docs
│   ├── firmware/
│   │   ├── platformio.ini      # ESP32-S3 PlatformIO build config
│   │   ├── include/
│   │   │   ├── config.h        # Pin assignments, safety thresholds
│   │   │   └── secrets.h.example
│   │   └── src/
│   │       ├── main.cpp        # Firmware entry point (setup/loop)
│   │       ├── sensors.h/cpp   # ADS1115 + TCA9548A mux + DS18B20
│   │       ├── actuators.h/cpp # Aerator + doser MOSFET control
│   │       ├── safety.h/cpp    # Local interlock manager
│   │       └── transport.h/cpp # HTTP/JSON ↔ backend (swappable)
│   ├── tools/
│   │   └── simulate_node.py    # Fake Sentinel node for demo/testing
│   └── docs/
│       ├── BOM.md              # Bill of materials (~$161/node)
│       ├── wiring.md           # ASCII wiring diagram
│       └── runbook.md          # Full bring-up + demo guide
│
├── aquasense_backend/          # Python cognition-tier backend
│   ├── main.py                 # FastAPI app entry point
│   ├── api/v1/endpoints/
│   │   ├── nodes.py            # Sentinel node API (telemetry/commands/ack)
│   │   ├── tanks.py            # Tank management
│   │   ├── analysis.py         # AI water analysis
│   │   └── voice_agent.py      # Gemini voice agent
│   ├── services/
│   │   ├── node_service.py     # Node registration, heartbeat, command pipeline
│   │   └── tank_service.py
│   ├── models/
│   │   ├── node.py             # Node, Telemetry, Command, CommandAck ORM
│   │   └── tank.py / water_quality.py / ...
│   ├── schemas/
│   │   └── node.py             # Pydantic v2 wire schemas
│   ├── ml/
│   │   └── water_quality_predictor.py
│   ├── ai/
│   │   └── gemini_client.py
│   ├── .env.example
│   └── requirements.txt
│
├── IOS/aqua/                   # SwiftUI iOS app
├── app/                        # Kotlin/Jetpack Compose Android app
└── docs/
    └── hardware_contract.md    # Authoritative hardware ↔ backend protocol spec
```

---

## Quickstart

### 1. Backend

```bash
cd aquasense_backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your GEMINI_API_KEY
uvicorn main:app --reload
# → http://localhost:8000/docs
```

### 2. Simulate a Sentinel node (no hardware required)

```bash
# Normal healthy pond
python hardware/tools/simulate_node.py --scenario normal --interval 10

# DO crashing — interlock fires, refusal escalates to human
python hardware/tools/simulate_node.py --scenario alert --interval 5
```

### 3. Flash real firmware

```bash
cd hardware/firmware
cp include/secrets.h.example include/secrets.h   # fill in credentials
pip install platformio
pio run -e sentinel_s3 -t upload
pio device monitor --baud 115200
```

See [hardware/docs/runbook.md](hardware/docs/runbook.md) for the full guide.

---

## Hardware — Sentinel Node

| Component | Part | Purpose |
| --------- | ---- | ------- |
| MCU | ESP32-S3-WROOM-1-N16R8 | Main controller + SoftAP |
| ADC | ADS1115 ×3 via TCA9548A mux | 16-bit analog reads |
| pH sensor | DFRobot SEN0169 | pH electrode |
| Turbidity | DFRobot SEN0189 | Turbidity (NTU) |
| DO sensor | DFRobot SEN0237-A | Dissolved oxygen (optional) |
| Temperature | DS18B20 waterproof | Temp compensation |
| Aerator driver | IRLZ44N MOSFET | Air pump control |
| Doser driver | IRLZ44N MOSFET | Peristaltic pump control |
| LoRa | Ra-02 SX1278 | Long-range telemetry |

Full BOM + wiring: [hardware/docs/BOM.md](hardware/docs/BOM.md) · [hardware/docs/wiring.md](hardware/docs/wiring.md)

---

## Safety contract

Encoded in firmware (`safety.cpp`) and backend (`node_service.py`):

| Rule | Enforcement |
| ---- | ---------- |
| DO < 4.0 mg/L → aerator forced ON | Firmware interlock, non-overridable |
| Refused safety-critical command → escalate, no retry | `NodeService.process_ack()` |
| Single dose ≤ 15 mL | Backend API + firmware |
| Min 600 s between doses per node | Backend + firmware |
| Rolling ≤ 40 mL / hr per node | Backend + firmware |
| E-stop (GPIO0) → all actuators off | Firmware hardware pin |

Full protocol: [docs/hardware_contract.md](docs/hardware_contract.md)

---

## Backend API

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `/api/v1/nodes/register` | Node registration |
| POST | `/api/v1/nodes/{id}/heartbeat` | Liveness + interlock snapshot |
| POST | `/api/v1/nodes/{id}/telemetry` | Sensor batch ingestion |
| GET | `/api/v1/nodes/{id}/commands` | Node polls for actuator commands |
| POST | `/api/v1/nodes/{id}/ack` | Command result (incl. refusals) |
| GET | `/api/v1/tanks/` | Tank management |
| POST | `/api/v1/analysis/` | AI water quality analysis |
| WS | `/ws/voice` | Gemini voice agent |

Interactive docs at `http://localhost:8000/docs` when backend is running.

---

## Stack

**Firmware:** C++ · Arduino framework · PlatformIO · ArduinoJson · ArduinoHttpClient

**Backend:** Python 3.11 · FastAPI · SQLAlchemy · Pydantic v2 · Google Gemini · scikit-learn

**iOS:** Swift · SwiftUI

**Android:** Kotlin · Jetpack Compose · Retrofit
