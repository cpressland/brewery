import os
import pathlib
from collections import defaultdict
from typing import NamedTuple

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, literal
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Command, Host, InstalledTap, Package, Tag, TagPackage, Vulnerability


class PackageRow(NamedTuple):
    name: str
    type: str
    version: str | None

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


# ── Install script ────────────────────────────────────────────────────────────

@router.get("/install")
def install_script(request: Request) -> Response:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    server_url = f"{scheme}://{host}"
    api_key = os.environ.get("BREWERY_API_KEY", "")
    rendered = templates.get_template("install.sh").render(
        server_url=server_url,
        api_key=api_key,
    )
    return Response(content=rendered, media_type="text/plain; charset=utf-8")


def _install_url(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    password = os.environ.get("BREWERY_PASSWORD")
    credentials = f":{password}@" if password else ""
    return f"{scheme}://{credentials}{host}"


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
        request, "index.html", {"hosts": host_data, "sort": sort, "dir": dir, "install_url": _install_url(request)}
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
    kind: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = _package_rows(q, sort, dir, db, kind)
    all_hosts = db.query(Host).order_by(Host.hostname).all()
    return templates.TemplateResponse(
        request, "packages.html",
        {"packages": rows, "q": q, "all_hosts": all_hosts, "sort": sort, "dir": dir, "kind": kind},
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
    name = package_name.strip()
    hosts = db.query(Host).filter(Host.serial_number.in_(serials)).all()
    n = len(hosts)
    if package_type == "tap":
        if action not in ("tap", "untap"):
            raise HTTPException(status_code=400, detail="Invalid action for tap")
        cmds = []
        for h in hosts:
            cmds.append(Command(host_id=h.id, action=action, package_name=name, package_type=""))
            if action == "tap":
                cmds.append(Command(host_id=h.id, action="trust", package_name=name, package_type=""))
        db.add_all(cmds)
        db.commit()
        verb = "tap" if action == "tap" else "untap"
        return HTMLResponse(f'<span class="queued-badge">Queued {verb} of {name} for {n} host{"s" if n != 1 else ""}</span>')
    if package_type not in ("formula", "cask") or action not in ("install", "uninstall", "upgrade"):
        raise HTTPException(status_code=400, detail="Invalid action or package type")
    cmds = [
        Command(host_id=h.id, action=action, package_name=name, package_type=package_type)
        for h in hosts
    ]
    db.add_all(cmds)
    db.commit()
    return HTMLResponse(
        f'<span class="queued-badge">Queued {action} of {name} for {n} host{"s" if n != 1 else ""}</span>'
    )


@router.get("/packages/search", response_class=HTMLResponse)
def packages_search(
    request: Request,
    q: str = "",
    sort: str = "host_count",
    dir: str = "desc",
    kind: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = _package_rows(q, sort, dir, db, kind)
    return templates.TemplateResponse(request, "partials/package_rows.html", {"packages": rows, "kind": kind})


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

    all_tags = db.query(Tag).order_by(Tag.name).all()
    available_tags = [t for t in all_tags if t not in host.tags]
    tap_count = db.query(InstalledTap).filter(InstalledTap.host_id == host.id).count()

    return templates.TemplateResponse(
        request,
        "host.html",
        {
            "host": host,
            "packages": packages,
            "formula_count": formula_count,
            "cask_count": cask_count,
            "tap_count": tap_count,
            "commands": commands,
            "q": q,
            "kind": kind,
            "sort": sort,
            "dir": dir,
            "available_tags": available_tags,
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
    name = package_name.strip()
    if package_type == "tap":
        if action == "tap":
            tap_cmd = Command(host_id=host.id, action="tap", package_name=name, package_type="")
            trust_cmd = Command(host_id=host.id, action="trust", package_name=name, package_type="")
            db.add_all([tap_cmd, trust_cmd])
            db.commit()
            return templates.TemplateResponse(
                request, "partials/command_rows.html", {"commands": [tap_cmd, trust_cmd]}
            )
        elif action == "untap":
            cmd = Command(host_id=host.id, action="untap", package_name=name, package_type="")
            db.add(cmd)
            db.commit()
            return templates.TemplateResponse(request, "partials/command_row.html", {"cmd": cmd})
        else:
            raise HTTPException(status_code=400, detail="Invalid action for tap")
    elif package_type in ("formula", "cask") and action in ("install", "uninstall", "upgrade"):
        cmd = Command(host_id=host.id, action=action, package_name=name, package_type=package_type)
        db.add(cmd)
        db.commit()
        return templates.TemplateResponse(request, "partials/command_row.html", {"cmd": cmd})
    else:
        raise HTTPException(status_code=400, detail="Invalid action or package type")


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


@router.post("/hosts/{serial_number}/tags", response_class=HTMLResponse)
def host_add_tag(
    serial_number: str,
    request: Request,
    tag_id: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    host = db.query(Host).filter(Host.serial_number == serial_number).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if tag and tag not in host.tags:
        host.tags.append(tag)
        db.commit()
        db.refresh(host)
    all_tags = db.query(Tag).order_by(Tag.name).all()
    available = [t for t in all_tags if t not in host.tags]
    return templates.TemplateResponse(
        request, "partials/host_tags.html", {"host": host, "available_tags": available}
    )


@router.delete("/hosts/{serial_number}/tags/{tag_id}", response_class=HTMLResponse)
def host_remove_tag(
    serial_number: str,
    tag_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    host = db.query(Host).filter(Host.serial_number == serial_number).first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if tag and tag in host.tags:
        host.tags.remove(tag)
        db.commit()
        db.refresh(host)
    all_tags = db.query(Tag).order_by(Tag.name).all()
    available = [t for t in all_tags if t not in host.tags]
    return templates.TemplateResponse(
        request, "partials/host_tags.html", {"host": host, "available_tags": available}
    )


@router.delete("/commands/{command_id}", response_class=HTMLResponse)
def command_delete(command_id: str, db: Session = Depends(get_db)) -> HTMLResponse:
    cmd = db.query(Command).filter(Command.id == command_id, Command.status == "pending").first()
    if cmd:
        db.delete(cmd)
        db.commit()
    return HTMLResponse("")


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


# ── Tags ─────────────────────────────────────────────────────────────────────

@router.get("/tags", response_class=HTMLResponse)
def tags_list(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    tags = db.query(Tag).order_by(Tag.name).all()
    return templates.TemplateResponse(request, "tags.html", {"tags": tags})


@router.post("/tags", response_class=HTMLResponse)
def tags_create(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tag name required")
    if db.query(Tag).filter(Tag.name == name).first():
        raise HTTPException(status_code=400, detail="Tag already exists")
    tag = Tag(name=name)
    db.add(tag)
    db.commit()
    return RedirectResponse(url="/tags", status_code=303)


@router.get("/tags/{tag_id}", response_class=HTMLResponse)
def tag_detail(tag_id: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return templates.TemplateResponse(
        request, "tag.html", {"tag": tag, "available_host_data": _available_host_data(tag, db)}
    )


@router.post("/tags/{tag_id}/hosts", response_class=HTMLResponse)
def tag_add_hosts(
    tag_id: str,
    request: Request,
    serials: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if serials:
        hosts = db.query(Host).filter(Host.serial_number.in_(serials)).all()
        for host in hosts:
            if tag not in host.tags:
                host.tags.append(tag)
        db.commit()
        db.refresh(tag)
    return templates.TemplateResponse(
        request, "partials/tag_hosts.html", {"tag": tag, "available_host_data": _available_host_data(tag, db)}
    )


@router.post("/tags/{tag_id}/packages", response_class=HTMLResponse)
def tag_add_package(
    tag_id: str,
    request: Request,
    name: str = Form(...),
    pkg_type: str = Form(...),
    policy: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if pkg_type not in ("formula", "cask", "tap") or policy not in ("required", "banned"):
        raise HTTPException(status_code=400, detail="Invalid type or policy")
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Package name required")
    existing = db.query(TagPackage).filter(
        TagPackage.tag_id == tag.id, TagPackage.name == name, TagPackage.type == pkg_type
    ).first()
    if not existing:
        db.add(TagPackage(tag_id=tag.id, name=name, type=pkg_type, policy=policy))
        db.commit()
        db.refresh(tag)
    return templates.TemplateResponse(request, "partials/tag_packages.html", {"tag": tag})


@router.delete("/tags/{tag_id}/packages/{pkg_id}", response_class=HTMLResponse)
def tag_remove_package(
    tag_id: str,
    pkg_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tp = db.query(TagPackage).filter(TagPackage.id == pkg_id, TagPackage.tag_id == tag_id).first()
    if tp:
        db.delete(tp)
        db.commit()
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return templates.TemplateResponse(request, "partials/tag_packages.html", {"tag": tag})



@router.delete("/tags/{tag_id}/hosts/{serial_number}", response_class=HTMLResponse)
def tag_remove_host(
    tag_id: str,
    serial_number: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    host = db.query(Host).filter(Host.serial_number == serial_number).first()
    if host and host in tag.hosts:
        tag.hosts.remove(host)
        db.commit()
        db.refresh(tag)
    return templates.TemplateResponse(
        request, "partials/tag_hosts.html", {"tag": tag, "available_host_data": _available_host_data(tag, db)}
    )


@router.delete("/tags/{tag_id}", response_class=HTMLResponse)
def tag_delete(tag_id: str, db: Session = Depends(get_db)) -> HTMLResponse:
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.delete(tag)
    db.commit()
    return HTMLResponse("", headers={"HX-Redirect": "/tags"})


# ── Vulnerabilities ──────────────────────────────────────────────────────────

_SEVERITY_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}


@router.get("/vulnerabilities", response_class=HTMLResponse)
def vulnerabilities_page(
    request: Request,
    severity: str = "",
    sort: str = "cvss_score",
    dir: str = "desc",
    show_ignored: bool = False,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    query = db.query(Vulnerability).filter(Vulnerability.ignored.is_(show_ignored))
    if severity:
        query = query.filter(Vulnerability.severity == severity)
    vulns = query.all()

    host_counts_q = (
        db.query(Package.name, Package.type, func.count(Package.host_id).label("cnt"))
        .group_by(Package.name, Package.type)
        .all()
    )
    host_counts = {(r.name, r.type): r.cnt for r in host_counts_q}

    vuln_data = [
        {
            "vuln": v,
            "host_count": host_counts.get((v.package_name, v.package_type), 0),
            "aliases_list": v.aliases.split(",") if v.aliases else [],
        }
        for v in vulns
    ]

    def sort_key(item: dict):
        v = item["vuln"]
        if sort == "severity":
            return _SEVERITY_ORDER.get(v.severity or "", 0)
        if sort == "package":
            return v.package_name.lower()
        if sort == "host_count":
            return item["host_count"]
        return v.cvss_score or 0.0

    vuln_data.sort(key=sort_key, reverse=(dir == "desc"))

    active_vulns = db.query(Vulnerability).filter(Vulnerability.ignored.is_(False))
    severity_counts: dict[str, int] = {}
    for v in (active_vulns if not show_ignored else vulns):
        s = v.severity or "UNKNOWN"
        severity_counts[s] = severity_counts.get(s, 0) + 1

    all_vulns = db.query(Vulnerability).all()
    last_refreshed = max((v.refreshed_at for v in all_vulns), default=None)
    ignored_count = sum(1 for v in all_vulns if v.ignored)

    return templates.TemplateResponse(
        request,
        "vulnerabilities.html",
        {
            "vulns": vuln_data,
            "severity": severity,
            "sort": sort,
            "dir": dir,
            "show_ignored": show_ignored,
            "severity_counts": severity_counts,
            "last_refreshed": last_refreshed,
            "ignored_count": ignored_count,
        },
    )


@router.post("/vulnerabilities/{vuln_id}/ignore", response_class=HTMLResponse)
def vuln_ignore(
    vuln_id: str,
    reason: str = Form(default=""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    vuln = db.query(Vulnerability).filter(Vulnerability.id == vuln_id).first()
    if vuln:
        vuln.ignored = True
        vuln.ignored_at = datetime.now(timezone.utc)
        vuln.ignored_reason = reason.strip() or None
        db.commit()
    return HTMLResponse("")


@router.delete("/vulnerabilities/{vuln_id}/ignore", response_class=HTMLResponse)
def vuln_unignore(vuln_id: str, db: Session = Depends(get_db)) -> HTMLResponse:
    vuln = db.query(Vulnerability).filter(Vulnerability.id == vuln_id).first()
    if vuln:
        vuln.ignored = False
        vuln.ignored_at = None
        vuln.ignored_reason = None
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
            "taps": db.query(InstalledTap)
            .filter(InstalledTap.host_id == host.id)
            .count(),
        }
        for host in hosts
    ]


    def sort_key(item):
        h = item["host"]
        if sort == "formulas":
            return item["formulas"]
        if sort == "casks":
            return item["casks"]
        if sort == "taps":
            return item["taps"]
        if sort == "agent_version":
            return (h.agent_version or "").lower()
        if sort == "last_seen":
            return h.last_seen or datetime.min.replace(tzinfo=timezone.utc)
        return h.hostname.lower()

    data.sort(key=sort_key, reverse=(dir == "desc"))
    return data


def _filter_packages(db: Session, host_id, q: str, kind: str, sort: str = "name", dir: str = "asc") -> list:
    if kind == "tap":
        query = db.query(InstalledTap).filter(InstalledTap.host_id == host_id)
        if q:
            query = query.filter(InstalledTap.name.ilike(f"%{q}%"))
        col = InstalledTap.name.desc() if dir == "desc" else InstalledTap.name.asc()
        return [PackageRow(name=t.name, type="tap", version=None) for t in query.order_by(col).all()]
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


def _package_rows(q: str, sort: str, dir: str, db: Session, kind: str = "") -> list:
    if kind == "tap":
        tap_sort = func.count(InstalledTap.host_id) if sort == "host_count" else InstalledTap.name
        query = db.query(
            InstalledTap.name,
            literal("tap").label("type"),
            func.count(InstalledTap.host_id).label("host_count"),
        ).group_by(InstalledTap.name)
        if q:
            query = query.filter(InstalledTap.name.ilike(f"%{q}%"))
        return query.order_by(tap_sort.desc() if dir == "desc" else tap_sort.asc()).all()

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
    if kind in ("formula", "cask"):
        query = query.filter(Package.type == kind)
    if q:
        query = query.filter(Package.name.ilike(f"%{q}%"))
    query = query.order_by(col.desc() if dir == "desc" else col.asc())
    return query.all()


def _available_host_data(tag: Tag, db: Session) -> list[dict]:
    tag_host_ids = {h.id for h in tag.hosts}
    hosts = db.query(Host).order_by(Host.hostname).all()
    return [
        {
            "host": host,
            "formulas": db.query(Package).filter(Package.host_id == host.id, Package.type == "formula").count(),
            "casks": db.query(Package).filter(Package.host_id == host.id, Package.type == "cask").count(),
            "taps": db.query(InstalledTap).filter(InstalledTap.host_id == host.id).count(),
        }
        for host in hosts
        if host.id not in tag_host_ids
    ]


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
