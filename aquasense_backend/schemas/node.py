"""
Sentinel Node Schemas - Pydantic v2 request/response models

These are the authoritative wire schemas for the hardware contract documented
in docs/hardware_contract.md. Payloads are validated strictly; malformed bodies
are rejected with 422.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime


# ---------------------------------------------------------------------------
# Registration & heartbeat
# ---------------------------------------------------------------------------
class NodeCapabilities(BaseModel):
    """Sensors/actuators a node reports it can drive."""
    sensors: List[str] = Field(default_factory=list)
    actuators: List[str] = Field(default_factory=list)
    lora: bool = False
    do_sensor_present: bool = Field(
        True, description="Dissolved-oxygen sensor is modular/optional"
    )


class NodeRegistration(BaseModel):
    """Body for POST /nodes/register."""
    node_id: str = Field(..., min_length=3, max_length=64)
    firmware_version: str = Field(..., max_length=32)
    hardware_revision: Optional[str] = Field(None, max_length=32)
    capabilities: NodeCapabilities
    softap_ip: Optional[str] = Field(None, max_length=64)


class InterlockState(BaseModel):
    """Snapshot of the node's local (non-overridable) safety interlocks."""
    do_floor_active: bool = False
    dose_rate_limited: bool = False
    estop: bool = False


class HeartbeatRequest(BaseModel):
    """Body for POST /nodes/{node_id}/heartbeat."""
    firmware_version: str = Field(..., max_length=32)
    interlock_state: InterlockState
    uptime_s: Optional[int] = Field(None, ge=0)


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
class SensorReading(BaseModel):
    """One sensor sample within a telemetry batch."""
    channel: Literal[
        "ph", "turbidity", "dissolved_oxygen", "temperature"
    ]
    value: float
    unit: str = Field(..., max_length=16)
    quality: Literal["ok", "stale", "fault", "out_of_range"] = "ok"


class TelemetryBatch(BaseModel):
    """Body for POST /nodes/{node_id}/telemetry."""
    node_id: str
    firmware_version: str = Field(..., max_length=32)
    sampled_at: datetime
    interlock_state: InterlockState
    readings: List[SensorReading] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Commands & acks
# ---------------------------------------------------------------------------
class ActuatorCommand(BaseModel):
    """An actuator command request (returned by GET /nodes/{node_id}/commands)."""
    model_config = ConfigDict(from_attributes=True)

    command_id: str = Field(..., alias="id")
    actuator: Literal["aerator", "ph_doser"]
    action: Literal["set", "dose"]
    params: Dict[str, Any]
    reason: Optional[str] = None
    safety_critical: bool = False
    issued_at: datetime


class CommandAck(BaseModel):
    """Body for POST /nodes/{node_id}/ack."""
    command_id: str
    status: Literal["completed", "failed", "refused"]
    detail: Optional[str] = None
    completed_at: datetime


# ---------------------------------------------------------------------------
# Status / responses
# ---------------------------------------------------------------------------
class NodeStatus(BaseModel):
    """Backend view of a node's current state."""
    model_config = ConfigDict(from_attributes=True)

    node_id: str = Field(..., alias="id")
    tank_id: Optional[str] = None
    firmware_version: str
    status: str
    last_seen_at: datetime
    capabilities: NodeCapabilities


class CommandQueueResponse(BaseModel):
    """Response for GET /nodes/{node_id}/commands."""
    node_id: str
    commands: List[ActuatorCommand] = Field(default_factory=list)
