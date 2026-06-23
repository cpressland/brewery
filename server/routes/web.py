import os
import pathlib
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Command, Host, Package

router = APIRouter()
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).parent.parent / "templates"))
templates.env.globals["show_logout"] = bool(os.environ.get("BREWERY_PASSWORD"))


# ── Auth ─────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request) -> HTMLResponse:
    if not os.environ.get("BREWERY_PASSWORD"):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
def login_post(request: Request, password: str = Form(...)) -> HTMLResponse:
    expected = os.environ.get("BREWERY_PASSWORD")
    if not expected or password == expected:
        request.session["logged_in"] = True
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": "Invalid password"})


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ── Index ─────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    sort: str = "hostname",
    dir: str = "asc",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    host_data = _host_data(sort, dir, db)
    return templates.TemplateResponse(
        request, "index.html", {"hosts": host_data, "sort": sort, "dir": dir}
    )


@router.get("/hosts-partial", response_class=HTMLResponse)
def hosts_partial(
    request: Request,
    sort: str = "hostname",
    dir: str = "asc",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    host_data = _host_data(sort, dir, db)
    return templates.TemplateResponse(
        request, "partials/host_rows.html", {"hosts": host_data}
    )


# ── Packages ──────────────────────────────────────────────────────────────────

@router.get("/packages", response_class=HTMLResponse)
def packages_list(
    request: Request,
    q: str = "",
    sort: str = "host_count",
    dir: str = "desc",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = _package_rows(q, sort, dir, db)
    all_hosts = db.query(Host).order_by(Host.hostname).all()
    return templates.TemplateResponse(
        request, "packages.html", {"packages": rows, "q": q, "all_hosts": all_hosts, "sort": sort, "dir": dir}
    )


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
def packages_search(
    request: Request,
    q: str = "",
    sort: str = "host_count",
    dir: str = "desc",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = _package_rows(q, sort, dir, db)
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


# ── Hosts ─────────────────────────────────────────────────────────────────────

@router.get("/hosts/{serial_number}", response_class=HTMLResponse)
def host_detail(
    serial_number: str,
    request: Request,
    q: str = "",
    kind: str = "",
    sort: str = "name",
    dir: str = "asc",
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
    packages = _filter_packages(db, host.id, q, kind, sort, dir)

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
            "sort": sort,
            "dir": dir,
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


@router.get("/hosts/{serial_number}/commands", response_class=HTMLResponse)
def host_commands_partial(
    serial_number: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    host = db.query(Host).filter(Host.serial_number == serial_number).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    commands = (
        db.query(Command)
        .filter(Command.host_id == host.id)
        .order_by(Command.created_at.desc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse(request, "partials/command_rows.html", {"commands": commands})


@router.get("/hosts/{serial_number}/packages", response_class=HTMLResponse)
def host_packages_partial(
    serial_number: str,
    request: Request,
    q: str = "",
    kind: str = "",
    sort: str = "name",
    dir: str = "asc",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    host = db.query(Host).filter(Host.serial_number == serial_number).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    packages = _filter_packages(db, host.id, q, kind, sort, dir)
    return templates.TemplateResponse(request, "partials/packages.html", {"packages": packages})


@router.delete("/hosts/{serial_number}", response_class=HTMLResponse)
def host_delete(
    serial_number: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    host = db.query(Host).filter(Host.serial_number == serial_number).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    db.delete(host)
    db.commit()
    return HTMLResponse("")


# ── Outdated ─────────────────────────────────────────────────────────────────

@router.get("/outdated", response_class=HTMLResponse)
def outdated_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    data = _outdated_packages(db)
    return templates.TemplateResponse(request, "outdated.html", {"outdated": data})


@router.get("/outdated-partial", response_class=HTMLResponse)
def outdated_partial(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    data = _outdated_packages(db)
    return templates.TemplateResponse(request, "partials/outdated_rows.html", {"outdated": data})


@router.post("/outdated/{pkg_type}/{name:path}/upgrade-all", response_class=HTMLResponse)
def outdated_upgrade_all(
    pkg_type: str,
    name: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if pkg_type not in ("formula", "cask"):
        raise HTTPException(status_code=400, detail="Invalid package type")
    data = _outdated_packages(db)
    pkg_data = next((p for p in data if p["name"] == name and p["type"] == pkg_type), None)
    if not pkg_data:
        return HTMLResponse('<span class="queued-badge">Already up to date</span>')
    serials = [h["serial_number"] for h in pkg_data["outdated_hosts"]]
    hosts = db.query(Host).filter(Host.serial_number.in_(serials)).all()
    cmds = [
        Command(host_id=h.id, action="upgrade", package_name=name, package_type=pkg_type)
        for h in hosts
    ]
    db.add_all(cmds)
    db.commit()
    n = len(hosts)
    return HTMLResponse(f'<span class="queued-badge">Queued upgrade for {n} host{"s" if n != 1 else ""}</span>')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _host_data(sort: str, dir: str, db: Session) -> list[dict]:
    hosts = db.query(Host).all()
    data = [
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

    from datetime import datetime, timezone

    def sort_key(item):
        h = item["host"]
        if sort == "formulas":
            return item["formulas"]
        if sort == "casks":
            return item["casks"]
        if sort == "agent_version":
            return (h.agent_version or "").lower()
        if sort == "last_seen":
            return h.last_seen or datetime.min.replace(tzinfo=timezone.utc)
        return h.hostname.lower()

    data.sort(key=sort_key, reverse=(dir == "desc"))
    return data


def _filter_packages(db: Session, host_id, q: str, kind: str, sort: str = "name", dir: str = "asc") -> list:
    query = db.query(Package).filter(Package.host_id == host_id)
    if kind in ("formula", "cask"):
        query = query.filter(Package.type == kind)
    if q:
        query = query.filter(Package.name.ilike(f"%{q}%"))
    col = {"name": Package.name, "type": Package.type, "version": Package.version}.get(sort, Package.name)
    query = query.order_by(col.desc() if dir == "desc" else col.asc())
    return query.all()


def _latest_version(version_strs: list[str]) -> str | None:
    known = [v for v in version_strs if v != "unknown"]
    if not known:
        return None

    def sort_key(v: str) -> list:
        parts = v.lstrip("v").replace("-", ".").split(".")
        return [(0, int(p)) if p.isdigit() else (1, p) for p in parts]

    return max(known, key=sort_key)


def _package_rows(q: str, sort: str, dir: str, db: Session) -> list:
    col = {
        "name": Package.name,
        "type": Package.type,
        "host_count": func.count(Package.host_id),
    }.get(sort, func.count(Package.host_id))

    query = db.query(
        Package.name,
        Package.type,
        func.count(Package.host_id).label("host_count"),
    ).group_by(Package.name, Package.type)
    if q:
        query = query.filter(Package.name.ilike(f"%{q}%"))
    query = query.order_by(col.desc() if dir == "desc" else col.asc())
    return query.all()


def _outdated_packages(db: Session) -> list[dict]:
    rows = (
        db.query(Package, Host)
        .join(Host, Package.host_id == Host.id)
        .order_by(Package.name, Package.type, Host.hostname)
        .all()
    )

    groups: dict[tuple, list] = defaultdict(list)
    for pkg, host in rows:
        groups[(pkg.name, pkg.type)].append((pkg, host))

    outdated = []
    for (name, pkg_type), group in groups.items():
        versions = [p.version or "unknown" for p, _ in group]
        latest = _latest_version(versions)
        if latest is None:
            continue
        outdated_group = [(p, h) for p, h in group if (p.version or "unknown") != latest]
        if not outdated_group:
            continue
        outdated.append({
            "name": name,
            "type": pkg_type,
            "latest_version": latest,
            "outdated_count": len(outdated_group),
            "outdated_hosts": [
                {"hostname": h.hostname, "serial_number": h.serial_number, "version": p.version or "unknown"}
                for p, h in outdated_group
            ],
        })

    outdated.sort(key=lambda x: x["name"])
    return outdated
