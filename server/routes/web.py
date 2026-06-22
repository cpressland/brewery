import pathlib
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Command, Host, Package

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
    all_hosts = db.query(Host).order_by(Host.hostname).all()
    return templates.TemplateResponse(request, "packages.html", {"packages": rows, "q": q, "all_hosts": all_hosts})


@router.post("/packages/install", response_class=HTMLResponse)
def packages_install(
    request: Request,
    package_name: str = Form(...),
    package_type: str = Form(...),
    action: str = Form(...),
    serials: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if package_type not in ("formula", "cask") or action not in ("install", "uninstall", "upgrade"):
        raise HTTPException(status_code=400, detail="Invalid action or package type")
    hosts = db.query(Host).filter(Host.serial_number.in_(serials)).all()
    cmds = [
        Command(host_id=h.id, action=action, package_name=package_name.strip(), package_type=package_type)
        for h in hosts
    ]
    db.add_all(cmds)
    db.commit()
    n = len(hosts)
    return HTMLResponse(
        f'<span class="queued-badge">Queued {action} of {package_name} for {n} host{"s" if n != 1 else ""}</span>'
    )


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

    installed_serials = {host.serial_number for _, host in installs}

    by_version: dict[str, list[dict]] = defaultdict(list)
    for pkg, host in installs:
        by_version[pkg.version or "unknown"].append(
            {"hostname": host.hostname, "serial_number": host.serial_number}
        )

    latest_version = _latest_version(list(by_version.keys()))
    outdated_serials = [
        h["serial_number"]
        for version, hosts in by_version.items()
        if version != latest_version
        for h in hosts
    ]

    versions = sorted(by_version.items(), key=lambda x: len(x[1]), reverse=True)
    total_hosts = len(installs)

    all_hosts = db.query(Host).order_by(Host.hostname).all()
    hosts_without = [h for h in all_hosts if h.serial_number not in installed_serials]

    return templates.TemplateResponse(
        request,
        "package.html",
        {
            "name": name,
            "pkg_type": pkg_type,
            "total_hosts": total_hosts,
            "versions": versions,
            "latest_version": latest_version,
            "outdated_serials": outdated_serials,
            "hosts_without": hosts_without,
        },
    )


@router.post("/packages/{pkg_type}/{name}/commands", response_class=HTMLResponse)
def package_queue_command(
    pkg_type: str,
    name: str,
    request: Request,
    action: str = Form(...),
    serials: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if pkg_type not in ("formula", "cask") or action not in ("install", "uninstall", "upgrade"):
        raise HTTPException(status_code=400, detail="Invalid action or package type")
    hosts = db.query(Host).filter(Host.serial_number.in_(serials)).all()
    cmds = [
        Command(host_id=h.id, action=action, package_name=name, package_type=pkg_type)
        for h in hosts
    ]
    db.add_all(cmds)
    db.commit()
    n = len(hosts)
    return HTMLResponse(
        f'<span class="queued-badge">Queued for {n} host{"s" if n != 1 else ""}</span>'
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
    commands = (
        db.query(Command)
        .filter(Command.host_id == host.id)
        .order_by(Command.created_at.desc())
        .limit(20)
        .all()
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
            "commands": commands,
            "q": q,
            "kind": kind,
        },
    )


@router.post("/hosts/{serial_number}/commands", response_class=HTMLResponse)
def host_queue_command(
    serial_number: str,
    request: Request,
    action: str = Form(...),
    package_name: str = Form(...),
    package_type: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    host = db.query(Host).filter(Host.serial_number == serial_number).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    if action not in ("install", "uninstall", "upgrade") or package_type not in ("formula", "cask"):
        raise HTTPException(status_code=400, detail="Invalid action or package type")
    cmd = Command(
        host_id=host.id,
        action=action,
        package_name=package_name.strip(),
        package_type=package_type,
    )
    db.add(cmd)
    db.commit()
    return templates.TemplateResponse(request, "partials/command_row.html", {"cmd": cmd})


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


def _latest_version(version_strs: list[str]) -> str | None:
    known = [v for v in version_strs if v != "unknown"]
    if not known:
        return None

    def sort_key(v: str) -> list:
        parts = v.lstrip("v").replace("-", ".").split(".")
        return [(0, int(p)) if p.isdigit() else (1, p) for p in parts]

    return max(known, key=sort_key)


def _package_rows(q: str, db: Session) -> list:
    query = db.query(
        Package.name,
        Package.type,
        func.count(Package.host_id).label("host_count"),
    ).group_by(Package.name, Package.type)
    if q:
        query = query.filter(Package.name.ilike(f"%{q}%"))
    return query.order_by(func.count(Package.host_id).desc(), Package.name).all()
