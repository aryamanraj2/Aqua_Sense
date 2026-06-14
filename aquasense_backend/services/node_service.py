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
    # Commands (queue, dispatch, ack)
    # ------------------------------------------------------------------ #
    def queue_command(
        self,
        node_id: str,
        actuator: str,
        action: str,
        params: dict,
        reason: Optional[str] = None,
        safety_critical: bool = False,
    ) -> Command:
        """Validate and enqueue an actuator command for a node.

        Dosing commands are checked against server-side bounds before queuing
        (defense in depth — the node also enforces limits locally).
        """
        if actuator == "ph_doser" and action == "dose":
            ml = float(params.get("ml", 0))
            self._assert_dose_within_bounds(node_id, ml)

        cmd = Command(
            node_id=node_id,
            actuator=actuator,
            action=action,
            params=params,
            reason=reason,
            safety_critical=safety_critical,
            status="pending",
        )
        self.db.add(cmd)
        self.db.commit()
        self.db.refresh(cmd)
        logger.info(
            "command.queued node_id=%s command_id=%s actuator=%s action=%s reason=%r",
            node_id, cmd.id, actuator, action, reason,
        )
        return cmd

    def get_pending_commands(self, node_id: str) -> List[Command]:
        """Return pending commands for a node and mark them dispatched."""
        cmds = (
            self.db.query(Command)
            .filter(Command.node_id == node_id, Command.status == "pending")
            .order_by(Command.issued_at)
            .all()
        )
        now = datetime.utcnow()
        for cmd in cmds:
            cmd.status = "dispatched"
            cmd.dispatched_at = now
        self.db.commit()
        return cmds

    def process_ack(self, node_id: str, ack_payload: "CommandAckSchema") -> Command:
        """Record a command ack (including authoritative refusals).

        A refused safety-critical command is never retried — the backend flags
        it for human escalation instead.
        """
        cmd = (
            self.db.query(Command)
            .filter(Command.id == ack_payload.command_id, Command.node_id == node_id)
            .first()
        )
        if cmd is None:
            raise ValueError(f"Unknown command_id={ack_payload.command_id} for node {node_id}")

        ack = CommandAck(
            command_id=cmd.id,
            status=ack_payload.status,
            detail=ack_payload.detail,
            completed_at=ack_payload.completed_at,
        )
        self.db.add(ack)
        cmd.status = ack_payload.status

        if ack_payload.status == "refused":
            logger.warning(
                "command.refused node_id=%s command_id=%s safety_critical=%s detail=%r",
                node_id, cmd.id, cmd.safety_critical, ack_payload.detail,
            )
            if cmd.safety_critical:
                # Safety contract: refused safety-critical commands escalate to
                # a human. Auto-retry is explicitly forbidden.
                logger.error(
                    "ESCALATE node_id=%s command_id=%s — safety-critical refusal, "
                    "human intervention required",
                    node_id, cmd.id,
                )
        else:
            logger.info(
                "command.ack node_id=%s command_id=%s status=%s",
                node_id, cmd.id, ack_payload.status,
            )

        self.db.commit()
        return cmd

    # ------------------------------------------------------------------ #
    # Dose bounding (private)
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
