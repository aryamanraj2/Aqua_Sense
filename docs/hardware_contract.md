# AquaSense — Hardware ↔ Backend Contract (v1)

> **Status:** Stable for the Sentinel firmware `v0.4.x` line.
> **Transport:** HTTP/JSON over the node's SoftAP (MQTT is a planned upgrade — the transport
> layer is abstracted so it can be swapped without touching application logic).
> **Base path:** all endpoints are versioned under `/api/v1`.

This document is the single source of truth for how the **Sentinel node** (ESP32-S3 reflex tier)
talks to the **AquaSense backend** (cognition tier). The firmware in [`hardware/`](../hardware)
implements the *node* side of this contract; the backend implements the *server* side under
[`aquasense_backend/api/v1/endpoints/nodes.py`](../aquasense_backend/api/v1/endpoints).

---

## 1. Two-tier model

```
┌──────────────────────────────┐        HTTP/JSON (SoftAP)        ┌──────────────────────────────┐
│  REFLEX TIER — Sentinel node │  ───────────────────────────▶   │ COGNITION TIER — AquaSense    │
│  ESP32-S3                    │   POST /telemetry                │ backend + ML + Gemini agent   │
│  • sensors (pH/turb/DO/temp) │  ◀───────────────────────────   │                               │
│  • actuators (aerator/dose)  │   GET  /commands (poll)          │ • reasons over telemetry      │
│  • LOCAL SAFETY INTERLOCKS   │   POST /ack                      │ • issues actuator REQUESTS    │
│    (NON-OVERRIDABLE)         │   POST /register, /heartbeat     │ • escalates on refusal        │
└──────────────────────────────┘                                  └──────────────────────────────┘
```

**Golden rule:** commands from the cognition tier are **requests, not orders**. The node owns
safety. It may refuse any command that would violate a local interlock, and that refusal is
**authoritative and final**.

---

## 2. Endpoints

| Method | Path                                   | Direction        | Purpose                              |
|--------|----------------------------------------|------------------|--------------------------------------|
| POST   | `/api/v1/nodes/register`               | node → backend   | Register node / announce capabilities |
| POST   | `/api/v1/nodes/{node_id}/heartbeat`    | node → backend   | Liveness + interlock snapshot        |
| POST   | `/api/v1/nodes/{node_id}/telemetry`    | node → backend   | Push a batch of sensor readings      |
| GET    | `/api/v1/nodes/{node_id}/commands`     | node → backend   | Poll for pending actuator commands   |
| POST   | `/api/v1/nodes/{node_id}/ack`          | node → backend   | Report command result (incl. refusal)|

> **Polling note:** `GET /commands` is poll-based for the HTTP transport. The command queue is
> modeled as a server-side queue so a push transport (MQTT `cmd/{node_id}`) can replace polling
> without changing the schemas.

---

## 3. Payload schemas (informative; authoritative = Pydantic v2 in `schemas/node.py`)

### 3.1 `NodeRegistration` — `POST /nodes/register`
```json
{
  "node_id": "sentinel-a1b2c3",
  "firmware_version": "0.4.2",
  "hardware_revision": "rev-C",
  "capabilities": {
    "sensors": ["ph", "turbidity", "dissolved_oxygen", "temperature"],
    "actuators": ["aerator", "ph_doser"],
    "lora": true,
    "do_sensor_present": true
  },
  "softap_ip": "192.168.4.1"
}
```
> `dissolved_oxygen` is a **modular/optional** sensor. If `do_sensor_present` is `false`, the node
> omits DO readings and the backend must not assume DO data.

### 3.2 `SensorReading`
```json
{ "channel": "ph", "value": 7.42, "unit": "pH", "quality": "ok" }
```
`quality ∈ {ok, stale, fault, out_of_range}`.

### 3.3 `TelemetryBatch` — `POST /nodes/{node_id}/telemetry`
```json
{
  "node_id": "sentinel-a1b2c3",
  "firmware_version": "0.4.2",
  "sampled_at": "2026-06-15T04:30:00Z",
  "interlock_state": {
    "do_floor_active": false,
    "dose_rate_limited": false,
    "estop": false
  },
  "readings": [
    { "channel": "ph", "value": 7.42, "unit": "pH", "quality": "ok" },
    { "channel": "temperature", "value": 27.8, "unit": "C", "quality": "ok" },
    { "channel": "dissolved_oxygen", "value": 5.9, "unit": "mg/L", "quality": "ok" },
    { "channel": "turbidity", "value": 12.3, "unit": "NTU", "quality": "ok" }
  ]
}
```

### 3.4 `ActuatorCommand` — returned by `GET /nodes/{node_id}/commands`
```json
{
  "command_id": "cmd-7f3a",
  "actuator": "aerator",
  "action": "set",
  "params": { "on": true },
  "reason": "DO forecast: pre-dawn crash predicted in 90 min",
  "issued_at": "2026-06-15T04:31:02Z",
  "safety_critical": true
}
```
For dosing: `actuator: "ph_doser"`, `action: "dose"`, `params: { "ml": 12.0 }`.

### 3.5 `CommandAck` — `POST /nodes/{node_id}/ack`
```json
{
  "command_id": "cmd-7f3a",
  "status": "completed",
  "detail": "aerator energized",
  "completed_at": "2026-06-15T04:31:03Z"
}
```
`status ∈ {completed, failed, refused}`. On refusal:
```json
{ "command_id": "cmd-9d1b", "status": "refused",
  "detail": "refused: local DO interlock active", "completed_at": "..." }
```

---

## 4. Safety contract (encoded, not just documented)

1. **Refusals are final.** When the node returns `status: "refused"` for a `safety_critical`
   command, the backend marks the command `refused` and **must not auto-retry**. It escalates to a
   human (alert/notification).
2. **Server-side dose bounding (defense in depth).** Even though the node enforces dose limits, the
   backend rate-limits and bounds dosing commands before they are queued:
   - max single dose: **15 mL**
   - min interval between doses for a node: **600 s**
   - rolling cap: **40 mL / hour**
   A command exceeding these is rejected at the API layer (never queued).
3. **Interlocks the node enforces locally (non-overridable):**
   - **DO floor:** if DO < `4.0 mg/L`, aerator is forced ON and any "aerator off" request is refused.
   - **Dose lockout:** dosing refused while `dose_rate_limited` or `estop` is active.
   - **E-stop:** physical/firmware estop disables all actuators; all commands refused.

---

## 5. Freshness / staleness

- A node is **online** if a heartbeat or telemetry batch was received within `HEARTBEAT_TIMEOUT`
  (default 90 s). Otherwise **stale**, then **offline** after `OFFLINE_TIMEOUT` (default 300 s).
- Readings older than `READING_MAX_AGE` (default 120 s) are tagged `stale` and excluded from agent
  reasoning unless explicitly requested.

---

## 6. Versioning

- Contract version is carried implicitly by the `/api/v1` path and explicitly by
  `firmware_version` in every payload. Backwards-incompatible changes bump the path to `/api/v2`.
