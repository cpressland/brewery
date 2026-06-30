import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


host_tags = Table(
    "host_tags",
    Base.metadata,
    Column("host_id", UUID(as_uuid=True), ForeignKey("hosts.id"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id"), primary_key=True),
)


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
    tags: Mapped[list["Tag"]] = relationship(
        "Tag", secondary=host_tags, back_populates="hosts"
    )
    installed_taps: Mapped[list["InstalledTap"]] = relationship(
        "InstalledTap", back_populates="host", cascade="all, delete-orphan"
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


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    hosts: Mapped[list["Host"]] = relationship("Host", secondary=host_tags, back_populates="tags")
    packages: Mapped[list["TagPackage"]] = relationship(
        "TagPackage", back_populates="tag", cascade="all, delete-orphan"
    )


class TagPackage(Base):
    __tablename__ = "tag_packages"
    __table_args__ = (UniqueConstraint("tag_id", "name", "type"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tags.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # formula, cask, tap
    policy: Mapped[str] = mapped_column(String, nullable=False)  # required, banned
    tag: Mapped["Tag"] = relationship("Tag", back_populates="packages")


class InstalledTap(Base):
    __tablename__ = "installed_taps"
    __table_args__ = (UniqueConstraint("host_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hosts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    host: Mapped["Host"] = relationship("Host", back_populates="installed_taps")
