"""
Queries OSV.dev for all Homebrew packages in the database and caches results.
Run via: brewery-osv-refresh

Two-phase approach:
  Phase 1 — POST /v1/querybatch with (name, version) to discover vuln IDs per package.
             The batch endpoint returns only {id, modified} summaries.
  Phase 2 — GET /v1/vulns/{id} for each unique vuln ID to fetch full details
             (CVSS vector, severity, aliases, summary).
"""
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from .database import SessionLocal
from .models import Package, Vulnerability

log = logging.getLogger(__name__)

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/{}"

# Only store upstream CVEs — exclude distro-packaging entries (Alpine, Debian, Fedora, etc.)
UPSTREAM_PREFIXES = ("CVE-", "GHSA-", "OSS-FUZZ-", "GSD-")

BATCH_SIZE = 500
INTER_BATCH_DELAY = 0.5
DETAIL_DELAY = 0.1  # ~10 req/s for individual vuln lookups
INITIAL_BACKOFF = 2.0
MAX_BACKOFF = 120.0
MAX_RETRIES = 7


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES):
        req = UrlRequest(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except HTTPError as exc:
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                sleep = float(retry_after) if retry_after else backoff
                log.warning("Rate limited (attempt %d/%d), sleeping %.1fs", attempt + 1, MAX_RETRIES, sleep)
                time.sleep(sleep)
                backoff = min(backoff * 2, MAX_BACKOFF)
            elif exc.code >= 500:
                log.warning("Server error %d (attempt %d/%d), retrying in %.1fs", exc.code, attempt + 1, MAX_RETRIES, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
            else:
                raise
    raise RuntimeError(f"Exhausted {MAX_RETRIES} retries for {url}")


def _get_vuln(osv_id: str) -> dict | None:
    url = OSV_VULN_URL.format(osv_id)
    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES):
        req = UrlRequest(url)
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                sleep = float(retry_after) if retry_after else backoff
                log.warning("Rate limited on %s (attempt %d/%d), sleeping %.1fs", osv_id, attempt + 1, MAX_RETRIES, sleep)
                time.sleep(sleep)
                backoff = min(backoff * 2, MAX_BACKOFF)
            elif exc.code >= 500:
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
            else:
                raise
    log.warning("Exhausted retries fetching %s, skipping", osv_id)
    return None


def _extract_severity(vuln: dict) -> tuple[str | None, float | None, str | None]:
    """Return (severity_label, cvss_score, cvss_vector) from an OSV vulnerability record."""
    db_specific = vuln.get("database_specific") or {}
    raw = db_specific.get("severity")
    severity_label: str | None = raw.upper() if raw else None

    cvss_score: float | None = None
    cvss_vector: str | None = None

    for sev in vuln.get("severity") or []:
        sev_type = sev.get("type", "")
        vector = sev.get("score", "")
        if sev_type in ("CVSS_V3", "CVSS_V4") and vector.startswith("CVSS:"):
            cvss_vector = vector
            try:
                if "CVSS:4" in vector:
                    from cvss import CVSS4
                    cvss_score = float(CVSS4(vector).base_score)
                else:
                    from cvss import CVSS3
                    cvss_score = float(CVSS3(vector).base_score)
                if not severity_label and cvss_score is not None:
                    if cvss_score >= 9.0:
                        severity_label = "CRITICAL"
                    elif cvss_score >= 7.0:
                        severity_label = "HIGH"
                    elif cvss_score >= 4.0:
                        severity_label = "MEDIUM"
                    elif cvss_score > 0:
                        severity_label = "LOW"
            except Exception:
                pass
            break

    return severity_label, cvss_score, cvss_vector


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def refresh() -> None:
    db = SessionLocal()
    try:
        rows = db.query(Package.name, Package.type, Package.version).distinct().all()

        # Group by (name, type) → set of known versions (skip NULL versions)
        pkg_versions: dict[tuple[str, str], set[str]] = {}
        for name, pkg_type, version in rows:
            if version:
                pkg_versions.setdefault((name, pkg_type), set()).add(version)

        # Deduplicate to unique (name, version) pairs for OSV queries
        # (OSV doesn't distinguish formula/cask, so one query covers both types)
        name_version_pairs: list[tuple[str, str]] = sorted(
            {(name, v) for (name, _), versions in pkg_versions.items() for v in versions}
        )

        log.info("Checking %d (name, version) pairs for %d packages", len(name_version_pairs), len(pkg_versions))

        # ── Phase 1: batch discovery ──────────────────────────────────────────
        # /v1/querybatch returns only {id, modified} summaries
        name_to_osv_ids: dict[str, set[str]] = {}
        num_batches = max(1, (len(name_version_pairs) + BATCH_SIZE - 1) // BATCH_SIZE)

        for batch_idx in range(num_batches):
            batch = name_version_pairs[batch_idx * BATCH_SIZE:(batch_idx + 1) * BATCH_SIZE]
            log.info("Discovery batch %d/%d (%d queries)", batch_idx + 1, num_batches, len(batch))
            payload = {
                "queries": [
                    {"version": version, "package": {"name": name}}
                    for name, version in batch
                ]
            }
            response = _post_json(OSV_BATCH_URL, payload)
            for (name, _version), result in zip(batch, response.get("results", [])):
                for vuln in result.get("vulns") or []:
                    osv_id = vuln.get("id")
                    if osv_id and osv_id.startswith(UPSTREAM_PREFIXES):
                        name_to_osv_ids.setdefault(name, set()).add(osv_id)

            if batch_idx < num_batches - 1:
                time.sleep(INTER_BATCH_DELAY)

        all_osv_ids = sorted({osv_id for ids in name_to_osv_ids.values() for osv_id in ids})
        log.info("Fetching details for %d unique vulnerabilities", len(all_osv_ids))

        # ── Phase 2: fetch full vuln details ──────────────────────────────────
        vuln_details: dict[str, dict] = {}
        for i, osv_id in enumerate(all_osv_ids):
            if i > 0 and i % 100 == 0:
                log.info("  %d/%d vuln details fetched", i, len(all_osv_ids))
            details = _get_vuln(osv_id)
            if details:
                vuln_details[osv_id] = details
            if i < len(all_osv_ids) - 1:
                time.sleep(DETAIL_DELAY)

        # ── Phase 3: store in DB ──────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        total_vulns = 0

        for (name, pkg_type) in pkg_versions:
            osv_ids = name_to_osv_ids.get(name, set())

            # Preserve ignore status so it survives re-runs
            ignored_map = {
                v.osv_id: (v.ignored_at, v.ignored_reason)
                for v in db.query(Vulnerability).filter(
                    Vulnerability.package_name == name,
                    Vulnerability.package_type == pkg_type,
                    Vulnerability.ignored.is_(True),
                ).all()
            }

            db.query(Vulnerability).filter(
                Vulnerability.package_name == name,
                Vulnerability.package_type == pkg_type,
            ).delete(synchronize_session=False)

            for osv_id in osv_ids:
                details = vuln_details.get(osv_id, {})
                # OSV uses 'aliases' for GHSA/NVD entries, 'upstream' for distro entries
                aliases = details.get("aliases") or details.get("upstream") or []
                severity_label, cvss_score, cvss_vector = _extract_severity(details)
                was_ignored = osv_id in ignored_map
                db.add(Vulnerability(
                    id=uuid.uuid4(),
                    package_name=name,
                    package_type=pkg_type,
                    osv_id=osv_id,
                    aliases=",".join(aliases) if aliases else None,
                    summary=details.get("summary"),
                    severity=severity_label or "UNKNOWN",
                    cvss_score=cvss_score,
                    cvss_vector=cvss_vector,
                    published=_parse_dt(details.get("published")),
                    modified=_parse_dt(details.get("modified")),
                    refreshed_at=now,
                    ignored=was_ignored,
                    ignored_at=ignored_map[osv_id][0] if was_ignored else None,
                    ignored_reason=ignored_map[osv_id][1] if was_ignored else None,
                ))
                total_vulns += 1

        db.commit()

        # Remove vulns for packages no longer in the database
        current_names = {name for name, _ in pkg_versions}
        if current_names:
            db.query(Vulnerability).filter(
                Vulnerability.package_name.notin_(current_names)
            ).delete(synchronize_session=False)
        else:
            db.query(Vulnerability).delete(synchronize_session=False)
        db.commit()

        log.info("Done: %d vulnerabilities stored across %d packages", total_vulns, len(pkg_versions))
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    try:
        refresh()
    except Exception:
        log.exception("OSV refresh failed")
        sys.exit(1)
