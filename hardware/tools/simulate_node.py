#!/usr/bin/env python3
"""
simulate_node.py — AquaSense Sentinel Node Simulator

Fakes a Sentinel ESP32-S3 node posting realistic telemetry to the AquaSense
backend over HTTP. Use this to demo the live data pipeline without hardware.

Usage:
    python simulate_node.py [--url http://localhost:8000/api/v1] [--node sentinel-demo01]
                            [--interval 30] [--scenario normal|stress|alert]

Scenarios:
    normal  — healthy pond, readings within safe ranges
    stress  — pH drifting low, DO dropping toward floor (triggers aerator command)
    alert   — DO crashes below floor, turbidity spike (triggers escalation)
"""

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timezone
from typing import Optional
import urllib.request
import urllib.error

# ── Defaults (mirror hardware_contract.md) ────────────────────────────────────
DEFAULT_URL      = "http://localhost:8000/api/v1"
DEFAULT_NODE_ID  = "sentinel-demo01"
DEFAULT_INTERVAL = 30   # seconds between telemetry pushes
FW_VERSION       = "0.4.2"
HW_REVISION      = "rev-C"

# ── Scenario parameter envelopes ──────────────────────────────────────────────
SCENARIOS = {
    "normal": {
        "ph_base": 7.2,       "ph_drift": 0.05,
        "temp_base": 27.0,    "temp_drift": 0.3,
        "do_base": 7.5,       "do_drift": 0.3,
        "turb_base": 8.0,     "turb_drift": 2.0,
    },
    "stress": {
        "ph_base": 6.4,       "ph_drift": 0.15,   # drifting acidic
        "temp_base": 29.5,    "temp_drift": 0.5,  # warming reduces DO
        "do_base": 5.2,       "do_drift": 0.6,    # getting close to floor
        "turb_base": 25.0,    "turb_drift": 5.0,
    },
    "alert": {
        "ph_base": 5.8,       "ph_drift": 0.2,
        "temp_base": 31.0,    "temp_drift": 0.4,
        "do_base": 3.2,       "do_drift": 0.4,    # below DO_FLOOR_MG_L=4.0
        "turb_base": 80.0,    "turb_drift": 15.0, # algae bloom
    },
}

# ─────────────────────────────────────────────────────────────────────────────
class SentinelSimulator:
    def __init__(self, base_url: str, node_id: str, scenario: str, interval: int):
        self.base_url  = base_url.rstrip("/")
        self.node_id   = node_id
        self.scenario  = SCENARIOS[scenario]
        self.interval  = interval
        self.tick      = 0

        # Simulated interlock state
        self._do_floor_active   = False
        self._dose_rate_limited = False
        self._estop             = False

    # ── HTTP helpers ──────────────────────────────────────────────────────────
    def _post(self, path: str, payload: dict) -> Optional[dict]:
        url  = f"{self.base_url}{path}"
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "X-Node-ID": self.node_id},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = resp.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            print(f"  [HTTP {e.code}] POST {path}: {e.read().decode()[:120]}")
            return None
        except Exception as e:
            print(f"  [ERR] POST {path}: {e}")
            return None

    def _get(self, path: str) -> Optional[dict]:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(
            url,
            headers={"X-Node-ID": self.node_id},
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = resp.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            print(f"  [HTTP {e.code}] GET {path}: {e.read().decode()[:120]}")
            return None
        except Exception as e:
            print(f"  [ERR] GET {path}: {e}")
            return None

    # ── Sensor simulation ─────────────────────────────────────────────────────
    def _sensor_value(self, base: float, drift: float) -> float:
        """Smooth random walk around base ± drift."""
        noise = math.sin(self.tick * 0.3) * drift * 0.6 + random.gauss(0, drift * 0.4)
        return round(base + noise, 3)

    def _build_telemetry(self) -> dict:
        s = self.scenario
        ph   = self._sensor_value(s["ph_base"],   s["ph_drift"])
        temp = self._sensor_value(s["temp_base"],  s["temp_drift"])
        do   = self._sensor_value(s["do_base"],    s["do_drift"])
        turb = max(0.0, self._sensor_value(s["turb_base"], s["turb_drift"]))

        # Update local DO floor interlock (mirrors firmware logic)
        self._do_floor_active = do < 4.0

        readings = [
            {"channel": "ph",          "value": ph,   "unit": "pH",   "quality": "ok"},
            {"channel": "temperature", "value": temp, "unit": "C",    "quality": "ok"},
            {"channel": "dissolved_oxygen", "value": do, "unit": "mg/L", "quality": "ok"},
            {"channel": "turbidity",   "value": turb, "unit": "NTU",  "quality": "ok"},
        ]
        return {
            "node_id": self.node_id,
            "firmware_version": FW_VERSION,
            "sampled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "interlock_state": {
                "do_floor_active":   self._do_floor_active,
                "dose_rate_limited": self._dose_rate_limited,
                "estop":             self._estop,
            },
            "readings": readings,
        }

    # ── Command handling ──────────────────────────────────────────────────────
    def _handle_commands(self, commands: list) -> None:
        for cmd in commands:
            cid      = cmd.get("command_id", cmd.get("id", "?"))
            actuator = cmd.get("actuator", "")
            action   = cmd.get("action", "")
            params   = cmd.get("params", {})
            sc       = cmd.get("safety_critical", False)

            print(f"  [CMD] {cid}  {actuator}.{action}  params={params}  safety_critical={sc}")

            # Simulate local interlock decisions
            if self._estop:
                status, detail = "refused", "refused: e-stop active"
            elif actuator == "aerator" and not params.get("on") and self._do_floor_active:
                status, detail = "refused", "refused: local DO interlock active"
            elif actuator == "ph_doser" and self._dose_rate_limited:
                status, detail = "refused", "refused: dose_rate_limited interlock active"
            else:
                status, detail = "completed", f"{actuator} command executed"

            ack = {
                "command_id": cid,
                "status":     status,
                "detail":     detail,
                "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            result = self._post(f"/nodes/{self.node_id}/ack", ack)
            tag = "REFUSED" if status == "refused" else "ACK"
            print(f"  [{tag}] {cid} → {status}  backend={result}")

    # ── Main loop ─────────────────────────────────────────────────────────────
    def register(self) -> bool:
        print(f"[SIM] Registering node {self.node_id} ...")
        payload = {
            "node_id":          self.node_id,
            "firmware_version": FW_VERSION,
            "hardware_revision": HW_REVISION,
            "capabilities": {
                "sensors":          ["ph", "turbidity", "dissolved_oxygen", "temperature"],
                "actuators":        ["aerator", "ph_doser"],
                "lora":             True,
                "do_sensor_present": True,
            },
            "softap_ip": "192.168.4.1",
        }
        result = self._post("/nodes/register", payload)
        if result is not None:
            print(f"[SIM] Registered ✓  status={result.get('status', '?')}")
            return True
        print("[SIM] Registration failed — backend unreachable?")
        return False

    def run(self) -> None:
        print(f"[SIM] Starting simulation  node={self.node_id}  interval={self.interval}s")
        print(f"[SIM] Scenario: {args.scenario}  backend: {self.base_url}")
        print("[SIM] Press Ctrl-C to stop\n")

        while True:
            self.tick += 1
            now = datetime.now().strftime("%H:%M:%S")

            # Heartbeat every 3rd tick
            if self.tick % 3 == 0:
                hb = {
                    "firmware_version": FW_VERSION,
                    "uptime_s": self.tick * self.interval,
                    "interlock_state": {
                        "do_floor_active":   self._do_floor_active,
                        "dose_rate_limited": self._dose_rate_limited,
                        "estop":             self._estop,
                    },
                }
                self._post(f"/nodes/{self.node_id}/heartbeat", hb)
                print(f"[{now}] ♡ heartbeat sent")

            # Telemetry push
            batch = self._build_telemetry()
            r     = self._post(f"/nodes/{self.node_id}/telemetry", batch)

            readings_summary = "  ".join(
                f"{rd['channel']}={rd['value']}" for rd in batch["readings"]
            )
            flag = "⚠ DO FLOOR" if self._do_floor_active else ""
            print(f"[{now}] tick={self.tick:04d}  {readings_summary}  {flag}")
            if r:
                print(f"         → accepted={r.get('accepted')}  id={r.get('telemetry_id','?')[:8]}")

            # Poll for commands
            cmds_resp = self._get(f"/nodes/{self.node_id}/commands")
            if cmds_resp:
                cmds = cmds_resp.get("commands", [])
                if cmds:
                    print(f"  [POLL] {len(cmds)} command(s) received")
                    self._handle_commands(cmds)

            time.sleep(self.interval)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AquaSense Sentinel node simulator")
    parser.add_argument("--url",      default=DEFAULT_URL,      help="Backend base URL")
    parser.add_argument("--node",     default=DEFAULT_NODE_ID,  help="Node ID")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, type=int,
                        help="Telemetry push interval in seconds")
    parser.add_argument("--scenario", default="normal",
                        choices=list(SCENARIOS.keys()),
                        help="Simulation scenario (normal / stress / alert)")
    args = parser.parse_args()

    sim = SentinelSimulator(
        base_url=args.url,
        node_id=args.node,
        scenario=args.scenario,
        interval=args.interval,
    )
    if not sim.register():
        sys.exit(1)
    try:
        sim.run()
    except KeyboardInterrupt:
        print("\n[SIM] Stopped.")
