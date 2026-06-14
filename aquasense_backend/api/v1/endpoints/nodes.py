"""
Node Endpoints - Sentinel hardware cognition-tier API

Implements the server side of docs/hardware_contract.md: registration,
heartbeat, telemetry ingestion. Command queue/ack endpoints are added in the
command pipeline phase.
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
)
from services.node_service import NodeService

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
