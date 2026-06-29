from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Command, Host, Package, Tag, TagPackage
from ..schemas import CommandOut, SyncRequest, SyncResponse
from ..settings import settings

router = APIRouter(prefix="/api/v1")


def verify_api_key(authorization: Annotated[str | None, Header()] = None) -> None:
    if not settings.api_key:
        return
    if authorization != f"Bearer {settings.api_key}":
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post("/sync", response_model=SyncResponse)
def sync(
    request: SyncRequest,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
) -> SyncResponse:
    host = db.query(Host).filter(Host.serial_number == request.serial_number).first()
    if not host:
        host = Host(serial_number=request.serial_number, hostname=request.hostname)
        db.add(host)
        db.flush()

    host.hostname = request.hostname
    host.agent_version = request.agent_version
    host.last_seen = datetime.now(timezone.utc)

    db.query(Package).filter(Package.host_id == host.id).delete()
    db.flush()

    new_packages = [
        Package(host_id=host.id, name=p.name, version=p.version, type="formula")
        for p in request.formulas
    ] + [
        Package(host_id=host.id, name=p.name, version=p.version, type="cask")
        for p in request.casks
    ]
    db.add_all(new_packages)
    db.commit()

    # Apply tag policies: queue installs for required packages not present,
    # and uninstalls for banned packages that are present.
    tag_pkgs = (
        db.query(TagPackage)
        .join(TagPackage.tag)
        .join(Tag.hosts)
        .filter(Host.id == host.id)
        .all()
    )
    if tag_pkgs:
        installed = {(p.name, p.type) for p in new_packages}
        existing_pending = {
            (c.action, c.package_name, c.package_type)
            for c in db.query(Command).filter(
                Command.host_id == host.id, Command.status == "pending"
            ).all()
        }
        policy_cmds = []
        seen = set()
        for tp in tag_pkgs:
            if tp.policy == "required":
                key = ("install", tp.name, tp.type)
                if (tp.name, tp.type) not in installed and key not in existing_pending and key not in seen:
                    policy_cmds.append(Command(host_id=host.id, action="install", package_name=tp.name, package_type=tp.type))
                    seen.add(key)
            elif tp.policy == "banned":
                key = ("uninstall", tp.name, tp.type)
                if (tp.name, tp.type) in installed and key not in existing_pending and key not in seen:
                    policy_cmds.append(Command(host_id=host.id, action="uninstall", package_name=tp.name, package_type=tp.type))
                    seen.add(key)
        if policy_cmds:
            db.add_all(policy_cmds)
            db.commit()

    pending = (
        db.query(Command)
        .filter(Command.host_id == host.id, Command.status == "pending")
        .all()
    )
    now = datetime.now(timezone.utc)
    for cmd in pending:
        cmd.status = "dispatched"
        cmd.dispatched_at = now
    db.commit()

    return SyncResponse(
        status="ok",
        packages_updated=len(new_packages),
        commands=[
            CommandOut(
                id=str(cmd.id),
                action=cmd.action,
                package_name=cmd.package_name,
                package_type=cmd.package_type,
            )
            for cmd in pending
        ],
    )
