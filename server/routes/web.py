import pathlib
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Host, Package

router = APIRouter()
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    hosts = db.query(Host).order_by(Host.hostname).all()
    host_data = [
        {
            "host": host,
            "formulas": db.query(Package)
            .filter(Package.host_id == host.id, Package.type == "formula")
            .count(),
            "casks": db.query(Package)
            .filter(Package.host_id == host.id, Package.type == "cask")
            .count(),
        }
        for host in hosts
    ]
    return templates.TemplateResponse(request, "index.html", {"hosts": host_data})


@router.get("/packages", response_class=HTMLResponse)
def packages_list(request: Request, q: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
    rows = _package_rows(q, db)
    return templates.TemplateResponse(request, "packages.html", {"packages": rows, "q": q})


@router.get("/packages/search", response_class=HTMLResponse)
def packages_search(request: Request, q: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
    rows = _package_rows(q, db)
    return templates.TemplateResponse(request, "partials/package_rows.html", {"packages": rows})


@router.get("/packages/{pkg_type}/{name:path}", response_class=HTMLResponse)
def package_detail(
    pkg_type: str, name: str, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    if pkg_type not in ("formula", "cask"):
        raise HTTPException(status_code=404, detail="Package not found")

    installs = (
        db.query(Package, Host)
        .join(Host, Package.host_id == Host.id)
        .filter(Package.name == name, Package.type == pkg_type)
        .order_by(Package.version, Host.hostname)
        .all()
    )
    if not installs:
        raise HTTPException(status_code=404, detail="Package not found")

    by_version: dict[str, list[dict]] = defaultdict(list)
    for pkg, host in installs:
        by_version[pkg.version or "unknown"].append(
            {"hostname": host.hostname, "serial_number": host.serial_number}
        )

    versions = sorted(by_version.items(), key=lambda x: len(x[1]), reverse=True)
    total_hosts = len(installs)

    return templates.TemplateResponse(
        request,
        "package.html",
        {
            "name": name,
            "pkg_type": pkg_type,
            "total_hosts": total_hosts,
            "versions": versions,
        },
    )


@router.get("/hosts/{serial_number}", response_class=HTMLResponse)
def host_detail(
    serial_number: str,
    request: Request,
    q: str = "",
    kind: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    host = db.query(Host).filter(Host.serial_number == serial_number).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    formula_count = (
        db.query(Package).filter(Package.host_id == host.id, Package.type == "formula").count()
    )
    cask_count = (
        db.query(Package).filter(Package.host_id == host.id, Package.type == "cask").count()
    )

    packages = _filter_packages(db, host.id, q, kind)

    return templates.TemplateResponse(
        request,
        "host.html",
        {
            "host": host,
            "packages": packages,
            "formula_count": formula_count,
            "cask_count": cask_count,
            "q": q,
            "kind": kind,
        },
    )


@router.get("/hosts/{serial_number}/packages", response_class=HTMLResponse)
def host_packages_partial(
    serial_number: str,
    request: Request,
    q: str = "",
    kind: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    host = db.query(Host).filter(Host.serial_number == serial_number).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    packages = _filter_packages(db, host.id, q, kind)
    return templates.TemplateResponse(request, "partials/packages.html", {"packages": packages})


def _filter_packages(db: Session, host_id, q: str, kind: str) -> list:
    query = db.query(Package).filter(Package.host_id == host_id)
    if kind in ("formula", "cask"):
        query = query.filter(Package.type == kind)
    if q:
        query = query.filter(Package.name.ilike(f"%{q}%"))
    return query.order_by(Package.type, Package.name).all()


def _package_rows(q: str, db: Session) -> list:
    query = db.query(
        Package.name,
        Package.type,
        func.count(Package.host_id).label("host_count"),
    ).group_by(Package.name, Package.type)
    if q:
        query = query.filter(Package.name.ilike(f"%{q}%"))
    return query.order_by(func.count(Package.host_id).desc(), Package.name).all()
