# AquaSense Sentinel — Runbook

Quick-start guide for bringing up the full two-tier system: backend + node
(real hardware or simulator).

---

## 1. Backend setup

```bash
cd aquasense_backend

# Create and activate a virtual environment
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure secrets (copy example, fill in your Gemini key)
cp .env.example .env
# edit .env — set GEMINI_API_KEY

# Start the backend (auto-creates SQLite tables on first run)
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API docs available at [http://localhost:8000/docs](http://localhost:8000/docs) once running.

---

## 2. Simulate a Sentinel node (no hardware needed)

Run the simulator in a second terminal:

```bash
# Normal healthy pond
python hardware/tools/simulate_node.py --scenario normal --interval 10

# pH drifting, DO sinking — agent should respond
python hardware/tools/simulate_node.py --scenario stress --interval 5

# DO crash below floor + turbidity spike — interlock fires, refusal escalates
python hardware/tools/simulate_node.py --scenario alert  --interval 5
```

What to watch:
- Backend terminal logs show `telemetry.ingest`, `command.queued`, `command.refused / ESCALATE`
- `/docs` → `GET /api/v1/nodes/sentinel-demo01` shows live node status
- `alert` scenario: simulator returns `"refused: local DO interlock active"` on aerator-off commands

---

## 3. iOS app secrets setup

1. Copy `IOS/aqua/Secrets.xcconfig.example` → `IOS/aqua/Secrets.xcconfig`
2. Fill in `GEMINI_API_KEY = <your-key>`
3. In Xcode: **Project → Info → Configurations** — set Debug + Release to use `Secrets.xcconfig`
4. Add `GEMINI_API_KEY` to `Info.plist` as `$(GEMINI_API_KEY)`

---

## 4. Flash real firmware (ESP32-S3)

```bash
cd hardware/firmware

# Install PlatformIO CLI
pip install platformio

# Copy secrets
cp include/secrets.h.example include/secrets.h
# edit secrets.h — set SoftAP credentials and BACKEND_URL

# Build and flash (USB)
pio run -e sentinel_s3 -t upload

# Monitor serial output
pio device monitor --baud 115200 --filter esp32_exception_decoder
```

OTA update (node already running, on SoftAP):
```bash
pio run -e sentinel_s3_ota -t upload
```

---

## 5. Verify the control loop end-to-end

```
Node boots → POST /nodes/register
           → POST /nodes/{id}/telemetry  (every 30 s)
           → GET  /nodes/{id}/commands   (every 5 s)
           → POST /nodes/{id}/ack        (for each command)
           → POST /nodes/{id}/heartbeat  (every 60 s)
```

Manual command injection (curl):
```bash
# Queue an aerator command
curl -X POST "http://localhost:8000/api/v1/nodes/sentinel-demo01/commands" \
  -H "Content-Type: application/json" \
  -d '{"actuator":"aerator","action":"set","params":{"on":true},"reason":"manual test","safety_critical":false}'

# Queue a dose command (12 mL — within the 15 mL single-dose cap)
curl -X POST "http://localhost:8000/api/v1/nodes/sentinel-demo01/commands" \
  -H "Content-Type: application/json" \
  -d '{"actuator":"ph_doser","action":"dose","params":{"ml":12.0},"reason":"pH low","safety_critical":true}'
```

---

## 6. Safety contract quick-reference

| Rule | Where enforced |
|------|---------------|
| DO < 4.0 mg/L → aerator forced ON | Firmware `safety.cpp` + backend logs interlock state |
| Refused safety-critical command → escalate, no retry | Backend `node_service.py:process_ack()` |
| Single dose ≤ 15 mL | Backend API layer + firmware `actuators.cpp` |
| Min 600 s between doses | Backend `_assert_dose_within_bounds()` + firmware |
| Rolling ≤ 40 mL/hr | Backend + firmware |
| E-stop → all actuators off | Firmware GPIO0 (BOOT button), active-LOW |

---

## 7. Troubleshooting

| Symptom | Check |
|---------|-------|
| Node shows `stale` after 90 s | Heartbeat / telemetry not reaching backend — check SoftAP IP in `secrets.h` / `simulate_node.py --url` |
| `422 Unprocessable Entity` on telemetry | `node_id` in body doesn't match URL path param |
| Dose command returns 400 | Dose limit exceeded server-side — wait 600 s or check rolling cap |
| `command.refused` + `ESCALATE` in logs | Expected when DO interlock is active — human action required |
| iOS `assertionFailure: GEMINI_API_KEY not set` | `Secrets.xcconfig` not linked in Xcode scheme |
