"""
Sentinel Node Models

SQLAlchemy models for the hardware cognition tier: physical Sentinel nodes,
their telemetry readings, queued actuator commands, and command acks.

See docs/hardware_contract.md for the wire protocol these models persist.
"""
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from config.database import Base
import uuid


class Node(Base):
    """A registered Sentinel hardware node (ESP32-S3 reflex tier)."""

    __tablename__ = "nodes"

    id = Column(String, primary_key=True)  # node_id, e.g. "sentinel-a1b2c3"
    tank_id = Column(String, ForeignKey("tanks.id"), nullable=True)
    firmware_version = Column(String(32), nullable=False)
    hardware_revision = Column(String(32), nullable=True)
    capabilities = Column(JSON, nullable=False, default=dict)
    softap_ip = Column(String(64), nullable=True)
    status = Column(String(16), default="online")  # online, stale, offline
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    registered_at = Column(DateTime, default=datetime.utcnow)

    telemetry = relationship(
        "Telemetry", back_populates="node", cascade="all, delete-orphan"
    )
    commands = relationship(
        "Command", back_populates="node", cascade="all, delete-orphan"
    )


class Telemetry(Base):
    """A single telemetry batch persisted from a node push."""

    __tablename__ = "node_telemetry"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    node_id = Column(String, ForeignKey("nodes.id"), nullable=False)
    firmware_version = Column(String(32), nullable=True)
    sampled_at = Column(DateTime, nullable=False)
    interlock_state = Column(JSON, nullable=False, default=dict)
    readings = Column(JSON, nullable=False, default=list)  # list[SensorReading]
    received_at = Column(DateTime, default=datetime.utcnow)

    node = relationship("Node", back_populates="telemetry")


class Command(Base):
    """An actuator command request issued by the cognition tier."""

    __tablename__ = "node_commands"

    id = Column(String, primary_key=True, default=lambda: f"cmd-{uuid.uuid4().hex[:8]}")
    node_id = Column(String, ForeignKey("nodes.id"), nullable=False)
    actuator = Column(String(32), nullable=False)  # aerator, ph_doser
    action = Column(String(32), nullable=False)  # set, dose
    params = Column(JSON, nullable=False, default=dict)
    reason = Column(String, nullable=True)
    safety_critical = Column(Boolean, default=False)
    # pending -> dispatched -> completed | failed | refused
    status = Column(String(16), default="pending")
    issued_at = Column(DateTime, default=datetime.utcnow)
    dispatched_at = Column(DateTime, nullable=True)

    node = relationship("Node", back_populates="commands")
    ack = relationship(
        "CommandAck", back_populates="command", uselist=False,
        cascade="all, delete-orphan"
    )


class CommandAck(Base):
    """The node's result for a command, including authoritative refusals."""

    __tablename__ = "node_command_acks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    command_id = Column(String, ForeignKey("node_commands.id"), nullable=False)
    status = Column(String(16), nullable=False)  # completed, failed, refused
    detail = Column(String, nullable=True)
    completed_at = Column(DateTime, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow)

    command = relationship("Command", back_populates="ack")
