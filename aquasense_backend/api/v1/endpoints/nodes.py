"""
Node Endpoints - Sentinel hardware cognition-tier API

Implements the server side of docs/hardware_contract.md: registration,
heartbeat, telemetry ingestion, command dispatch, and ack/refusal handling.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from config.database import get_db
from schemas.node import (
    NodeRegistration,
    HeartbeatRequest,
    TelemetryBatch,
    NodeStatus,
    CommandQueueResponse,
    ActuatorCommand,
    CommandAck,
)
from services.node_service import NodeService, DoseLimitExceeded

router = APIRouter()


@router.post("/register", response_model=NodeStatus, status_code=status.HTTP_201_CREATED)
async def register_node(payload: NodeRegistration, db: Session = Depends(get_db)):
    """Register a Sentinel node or refresh its capabilities."""
    service = NodeService(db)
    node = service.register(payload)
    return node


@router.get("/", response_model=List[NodeStatus])
async def list_nodes(db: Session = Depends(get_db)):
    """List all known nodes with freshness-derived status."""
    service = NodeService(db)
    return service.list_nodes()


@router.get("/{node_id}", response_model=NodeStatus)
async def get_node(node_id: str, db: Session = Depends(get_db)):
    """Get a single node's status."""
    service = NodeService(db)
    node = service.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Unknown node: {node_id}")
    service._refresh_freshness(node)
    return node


@router.post("/{node_id}/heartbeat", response_model=NodeStatus)
async def heartbeat(node_id: str, payload: HeartbeatRequest, db: Session = Depends(get_db)):
    """Record a node heartbeat + interlock snapshot."""
    service = NodeService(db)
    node = service.heartbeat(node_id, payload)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Unknown node: {node_id}")
    return node


@router.post("/{node_id}/telemetry", status_code=status.HTTP_202_ACCEPTED)
async def ingest_telemetry(node_id: str, batch: TelemetryBatch, db: Session = Depends(get_db)):
    """Ingest a batch of sensor readings pushed by a node."""
    if batch.node_id != node_id:
        raise HTTPException(
            status_code=400,
            detail=f"node_id mismatch: path={node_id} body={batch.node_id}",
        )
    service = NodeService(db)
    record = service.ingest_telemetry(batch)
    return {"accepted": True, "telemetry_id": record.id, "n_readings": len(batch.readings)}


@router.get("/{node_id}/commands", response_model=CommandQueueResponse)
async def poll_commands(node_id: str, db: Session = Depends(get_db)):
    """Node polls for pending actuator commands.

    Returns the current queue and marks commands as dispatched. Designed so
    a push transport (MQTT) can replace polling without changing the schemas.
    """
    service = NodeService(db)
    if service.get_node(node_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown node: {node_id}")
    cmds = service.get_pending_commands(node_id)
    return CommandQueueResponse(
        node_id=node_id,
        commands=[
            ActuatorCommand.model_validate(cmd, from_attributes=True) for cmd in cmds
        ],
    )


@router.post("/{node_id}/commands", status_code=status.HTTP_201_CREATED)
async def issue_command(
    node_id: str,
    actuator: str,
    action: str,
    params: dict,
    reason: str = "",
    safety_critical: bool = False,
    db: Session = Depends(get_db),
):
    """Queue an actuator command for a node (called by the agent, not the node).

    Dosing commands are validated against server-side rate/volume limits before
    queuing. Exceeding the limits returns 400 — the command is never stored.
    """
    service = NodeService(db)
    if service.get_node(node_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown node: {node_id}")
    try:
        cmd = service.queue_command(
            node_id=node_id,
            actuator=actuator,
            action=action,
            params=params,
            reason=reason or None,
            safety_critical=safety_critical,
        )
    except DoseLimitExceeded as exc:
        raise HTTPException(status_code=400, detail=f"Dose limit exceeded: {exc}")
    return {"command_id": cmd.id, "status": cmd.status}


@router.post("/{node_id}/ack")
async def command_ack(node_id: str, ack: CommandAck, db: Session = Depends(get_db)):
    """Node reports the result of a command, including authoritative refusals.

    Refused safety-critical commands are escalated (logged for human action) and
    never auto-retried — this is enforced in NodeService.process_ack().
    """
    service = NodeService(db)
    try:
        cmd = service.process_ack(node_id, ack)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "command_id": cmd.id,
        "final_status": cmd.status,
        "escalated": cmd.safety_critical and cmd.status == "refused",
    }
