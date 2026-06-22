from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Host, Package
from ..schemas import SyncRequest, SyncResponse
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

    return SyncResponse(status="ok", packages_updated=len(new_packages))
