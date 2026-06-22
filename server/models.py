import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    serial_number: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    hostname: Mapped[str] = mapped_column(String, nullable=False)
    agent_version: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    packages: Mapped[list["Package"]] = relationship(
        "Package", back_populates="host", cascade="all, delete-orphan"
    )
    commands: Mapped[list["Command"]] = relationship(
        "Command", back_populates="host", cascade="all, delete-orphan"
    )


class Command(Base):
    __tablename__ = "commands"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hosts.id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)  # install, uninstall, upgrade
    package_name: Mapped[str] = mapped_column(String, nullable=False)
    package_type: Mapped[str] = mapped_column(String, nullable=False)  # formula, cask
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending, dispatched
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    host: Mapped["Host"] = relationship("Host", back_populates="commands")


class Package(Base):
    __tablename__ = "packages"
    __table_args__ = (UniqueConstraint("host_id", "name", "type"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hosts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # 'formula' or 'cask'
    version: Mapped[str | None] = mapped_column(String, nullable=True)
    host: Mapped["Host"] = relationship("Host", back_populates="packages")
