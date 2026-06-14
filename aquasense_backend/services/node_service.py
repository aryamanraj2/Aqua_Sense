"""
Node Service - Business logic for Sentinel hardware nodes

Handles registration, heartbeat/freshness, telemetry ingestion, the command
queue, and ack/refusal processing. Encodes the server-side half of the safety
contract documented in docs/hardware_contract.md.
"""
import logging
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta

from models.node import Node, Telemetry, Command, CommandAck
from schemas.node import (
    NodeRegistration,
    HeartbeatRequest,
    TelemetryBatch,
    CommandAck as CommandAckSchema,
)

logger = logging.getLogger("aquasense.nodes")

# Freshness windows (seconds) -- see hardware_contract.md §5
HEARTBEAT_TIMEOUT = 90
OFFLINE_TIMEOUT = 300

# Server-side dose bounds (defense in depth) -- see hardware_contract.md §4
MAX_SINGLE_DOSE_ML = 15.0
MIN_DOSE_INTERVAL_S = 600
ROLLING_DOSE_CAP_ML = 40.0
ROLLING_DOSE_WINDOW_S = 3600


class DoseLimitExceeded(Exception):
    """Raised when a dosing request violates server-side bounds."""


class NodeService:
    """Service class for Sentinel node operations."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ #
    # Registration & freshness
    # ------------------------------------------------------------------ #
    def register(self, payload: NodeRegistration) -> Node:
        """Register a node or update its capabilities on re-registration."""
        node = self.db.query(Node).filter(Node.id == payload.node_id).first()
        now = datetime.utcnow()
        if node is None:
            node = Node(id=payload.node_id, registered_at=now)
            self.db.add(node)
            logger.info("node.register node_id=%s NEW", payload.node_id)
        else:
            logger.info("node.register node_id=%s RE-REGISTER", payload.node_id)
        node.firmware_version = payload.firmware_version
        node.hardware_revision = payload.hardware_revision
        node.capabilities = payload.capabilities.model_dump()
        node.softap_ip = payload.softap_ip
        node.status = "online"
        node.last_seen_at = now
        self.db.commit()
        self.db.refresh(node)
        return node

    def heartbeat(self, node_id: str, payload: HeartbeatRequest) -> Optional[Node]:
        """Record a heartbeat and refresh liveness."""
        node = self.get_node(node_id)
        if node is None:
            return None
        node.firmware_version = payload.firmware_version
        node.status = "online"
        node.last_seen_at = datetime.utcnow()
        self.db.commit()
        logger.info(
            "node.heartbeat node_id=%s interlocks=%s",
            node_id, payload.interlock_state.model_dump(),
        )
        return node

    def get_node(self, node_id: str) -> Optional[Node]:
        return self.db.query(Node).filter(Node.id == node_id).first()

    def list_nodes(self) -> List[Node]:
        nodes = self.db.query(Node).all()
        for node in nodes:
            self._refresh_freshness(node)
        return nodes

    def _refresh_freshness(self, node: Node) -> None:
        """Recompute online/stale/offline from last_seen_at."""
        age = (datetime.utcnow() - node.last_seen_at).total_seconds()
        if age > OFFLINE_TIMEOUT:
            node.status = "offline"
        elif age > HEARTBEAT_TIMEOUT:
            node.status = "stale"
        else:
            node.status = "online"

    # ------------------------------------------------------------------ #
    # Telemetry
    # ------------------------------------------------------------------ #
    def ingest_telemetry(self, batch: TelemetryBatch) -> Telemetry:
        """Persist a telemetry batch and refresh node liveness."""
        node = self.get_node(batch.node_id)
        now = datetime.utcnow()
        if node is None:
            # Auto-register minimally so we never drop data from a known sensor.
            node = Node(
                id=batch.node_id,
                firmware_version=batch.firmware_version,
                capabilities={},
                registered_at=now,
            )
            self.db.add(node)
            logger.warning("telemetry.auto_register node_id=%s", batch.node_id)
        node.status = "online"
        node.last_seen_at = now

        record = Telemetry(
            node_id=batch.node_id,
            firmware_version=batch.firmware_version,
            sampled_at=batch.sampled_at,
            interlock_state=batch.interlock_state.model_dump(),
            readings=[r.model_dump() for r in batch.readings],
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        logger.info(
            "telemetry.ingest node_id=%s n_readings=%d sampled_at=%s",
            batch.node_id, len(batch.readings), batch.sampled_at.isoformat(),
        )
        return record

    def latest_telemetry(self, node_id: str) -> Optional[Telemetry]:
        return (
            self.db.query(Telemetry)
            .filter(Telemetry.node_id == node_id)
            .order_by(Telemetry.received_at.desc())
            .first()
        )

    # ------------------------------------------------------------------ #
    # Commands (queue, dispatch, ack) -- implemented in batch 4
    # ------------------------------------------------------------------ #
    def _assert_dose_within_bounds(self, node_id: str, ml: float) -> None:
        """Server-side dose bounding (defense in depth)."""
        if ml <= 0 or ml > MAX_SINGLE_DOSE_ML:
            raise DoseLimitExceeded(
                f"single dose {ml} mL out of bounds (0, {MAX_SINGLE_DOSE_ML}]"
            )
        window_start = datetime.utcnow() - timedelta(seconds=ROLLING_DOSE_WINDOW_S)
        recent = (
            self.db.query(Command)
            .filter(
                Command.node_id == node_id,
                Command.actuator == "ph_doser",
                Command.issued_at >= window_start,
            )
            .all()
        )
        if recent:
            last = max(recent, key=lambda c: c.issued_at)
            since_last = (datetime.utcnow() - last.issued_at).total_seconds()
            if since_last < MIN_DOSE_INTERVAL_S:
                raise DoseLimitExceeded(
                    f"dose interval {since_last:.0f}s < {MIN_DOSE_INTERVAL_S}s"
                )
        rolling = sum(float(c.params.get("ml", 0)) for c in recent) + ml
        if rolling > ROLLING_DOSE_CAP_ML:
            raise DoseLimitExceeded(
                f"rolling dose {rolling} mL > {ROLLING_DOSE_CAP_ML} mL/hr cap"
            )
