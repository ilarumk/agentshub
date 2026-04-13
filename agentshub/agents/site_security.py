"""
Site Security Agent — scans public websites for common security issues.

Checks via public HTTP requests only — no authentication, no exploitation,
no intrusive testing. Identifies misconfigurations that are visible to
anyone visiting the site.

Checks:
  - SSL certificate validity and expiration
  - Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
  - WordPress detection + version exposure
  - Exposed wp-admin login page
  - XML-RPC enabled (common attack vector for WordPress)
  - REST API user enumeration (wp-json/wp/v2/users)
  - robots.txt analysis (sensitive paths disclosed)
  - Common exposed files (debug.log, wp-config backups, .env)
  - HTTP to HTTPS redirect
  - Server header information leakage
"""

import os
import re
import ssl
import socket
import urllib.request
import urllib.error
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from agentshub.base import result, timer

NAME = "site_security"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SecurityScanner/1.0; +https://github.com/ilarumk/agentshub)"
}

# Security headers to check
EXPECTED_HEADERS = {
    "Strict-Transport-Security": "Forces HTTPS — prevents downgrade attacks",
    "Content-Security-Policy": "Controls which resources can load — prevents XSS",
    "X-Frame-Options": "Prevents clickjacking via iframes",
    "X-Content-Type-Options": "Prevents MIME type sniffing",
    "X-XSS-Protection": "Legacy XSS filter (deprecated but still checked)",
    "Referrer-Policy": "Controls referrer information leakage",
    "Permissions-Policy": "Controls browser feature access (camera, mic, etc.)",
}

# Files that should never be publicly accessible
SENSITIVE_PATHS = [
    "/.env",
    "/wp-config.php.bak",
    "/wp-config.php.old",
    "/wp-config.php~",
    "/debug.log",
    "/wp-content/debug.log",
    "/error_log",
    "/.git/config",
    "/.htaccess",
    "/phpinfo.php",
    "/server-status",
    "/server-info",
    "/backup.sql",
    "/db.sql",
]

# WordPress specific paths
WP_PATHS = {
    "login":    "/wp-login.php",
    "admin":    "/wp-admin/",
    "xmlrpc":   "/xmlrpc.php",
    "users":    "/wp-json/wp/v2/users",
    "readme":   "/readme.html",
    "rss":      "/feed/",
}


def _log(msg):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] [site_security] {msg}", flush=True)


def _fetch(url: str, timeout: int = 10) -> dict:
    """Fetch URL and return status code, headers, body preview."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2000).decode("utf-8", errors="ignore")
            return {
                "status": resp.status,
                "headers": dict(resp.headers),
                "body": body,
                "url": resp.geturl(),
            }
    except urllib.error.HTTPError as e:
        return {"status": e.code, "headers": dict(e.headers) if e.headers else {}, "body": "", "url": url}
    except Exception as e:
        return {"status": 0, "headers": {}, "body": "", "url": url, "error": str(e)}


def _check_ssl(domain: str) -> dict:
    """Check SSL certificate validity and expiration."""
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
            s.settimeout(10)
            s.connect((domain, 443))
            cert = s.getpeercert()

        not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days_left = (not_after - datetime.now(timezone.utc)).days

        return {
            "valid": True,
            "issuer": dict(x[0] for x in cert.get("issuer", [])).get("organizationName", "Unknown"),
            "expires": not_after.strftime("%Y-%m-%d"),
            "days_left": days_left,
            "severity": "critical" if days_left < 7 else "warning" if days_left < 30 else "ok",
        }
    except Exception as e:
        return {"valid": False, "error": str(e), "severity": "critical"}


def _check_security_headers(headers: dict) -> list[dict]:
    """Check for missing security headers."""
    findings = []
    for header, description in EXPECTED_HEADERS.items():
        present = any(h.lower() == header.lower() for h in headers.keys())
        findings.append({
            "header": header,
            "present": present,
            "description": description,
            "severity": "warning" if not present else "ok",
        })
    return findings


def _check_wordpress(base_url: str) -> dict:
    """Detect WordPress and check WP-specific security issues."""
    wp_findings = {"is_wordpress": False, "issues": []}

    # Check for WP indicators
    main = _fetch(base_url)
    if "wp-content" in main.get("body", "") or "wp-includes" in main.get("body", ""):
        wp_findings["is_wordpress"] = True
        _log("  WordPress detected")

        # Version exposure via meta generator
        version_match = re.search(r'<meta[^>]+generator[^>]+WordPress\s*([\d.]+)', main.get("body", ""), re.I)
        if version_match:
            wp_findings["version"] = version_match.group(1)
            wp_findings["issues"].append({
                "issue": f"WordPress version exposed: {version_match.group(1)}",
                "severity": "warning",
                "fix": "Remove version from meta generator tag",
            })

        # Check WP paths in parallel
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_fetch, f"{base_url}{path}"): name for name, path in WP_PATHS.items()}
            for future in as_completed(futures):
                name = futures[future]
                resp = future.result()
                status = resp.get("status", 0)

                if name == "login" and status == 200:
                    wp_findings["issues"].append({
                        "issue": "wp-login.php is publicly accessible",
                        "severity": "info",
                        "fix": "Consider IP restriction or rename login URL",
                    })
                elif name == "xmlrpc" and status == 200:
                    if "XML-RPC server accepts POST requests" in resp.get("body", ""):
                        wp_findings["issues"].append({
                            "issue": "XML-RPC is enabled — common brute-force and DDoS vector",
                            "severity": "warning",
                            "fix": "Disable XML-RPC if not needed (plugin or .htaccess)",
                        })
                elif name == "users" and status == 200:
                    try:
                        import json
                        users = json.loads(resp.get("body", "[]"))
                        if isinstance(users, list) and users:
                            names = [u.get("name", "") for u in users[:5]]
                            wp_findings["issues"].append({
                                "issue": f"REST API exposes user list: {', '.join(names)}",
                                "severity": "warning",
                                "fix": "Disable user enumeration via REST API",
                            })
                    except Exception:
                        pass
                elif name == "readme" and status == 200:
                    wp_findings["issues"].append({
                        "issue": "readme.html accessible — may expose WordPress version",
                        "severity": "info",
                        "fix": "Delete or restrict access to readme.html",
                    })

    return wp_findings


def _check_exposed_files(base_url: str) -> list[dict]:
    """Check for sensitive files that shouldn't be publicly accessible."""
    findings = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch, f"{base_url}{path}"): path for path in SENSITIVE_PATHS}
        for future in as_completed(futures):
            path = futures[future]
            resp = future.result()
            if resp.get("status") == 200:
                findings.append({
                    "issue": f"Sensitive file accessible: {path}",
                    "severity": "critical" if any(s in path for s in [".env", "config", ".git", ".sql"]) else "warning",
                    "fix": f"Restrict access to {path}",
                })
                _log(f"  ⚠ EXPOSED: {path}")

    return findings


def _check_server_info(headers: dict) -> list[dict]:
    """Check for server information leakage."""
    findings = []
    server = headers.get("Server", headers.get("server", ""))
    if server:
        findings.append({
            "issue": f"Server header exposes: {server}",
            "severity": "info",
            "fix": "Consider hiding server version information",
        })

    powered_by = headers.get("X-Powered-By", headers.get("x-powered-by", ""))
    if powered_by:
        findings.append({
            "issue": f"X-Powered-By exposes: {powered_by}",
            "severity": "warning",
            "fix": "Remove X-Powered-By header",
        })

    return findings


def run(url: str = "", checks: str = "all") -> dict:
    """
    Scan a website for common security misconfigurations.
    Uses only public HTTP requests — no authentication or intrusive testing.

    Args:
        url: Website URL to scan (e.g. "https://example.com")
        checks: Comma-separated checks to run: ssl, headers, wordpress, files, server, all (default: all)
    """
    with timer() as t:
        if not url:
            return result(
                name=NAME, status="FAILED", mode="no URL",
                duration_s=t.elapsed, insights=[],
                error="url parameter is required",
            )

        # Normalize URL
        if not url.startswith("http"):
            url = f"https://{url}"
        url = url.rstrip("/")

        # Extract domain
        domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
        domain = domain_match.group(1) if domain_match else url

        _log(f"Scanning {url}")

        check_list = [c.strip() for c in checks.split(",")] if checks != "all" else ["ssl", "headers", "wordpress", "files", "server"]

        all_findings = []
        severity_counts = {"critical": 0, "warning": 0, "info": 0, "ok": 0}

        # SSL check
        if "ssl" in check_list:
            _log("Checking SSL certificate...")
            ssl_result = _check_ssl(domain)
            if ssl_result["valid"]:
                _log(f"  ✓ SSL valid, expires {ssl_result['expires']} ({ssl_result['days_left']} days)")
            else:
                _log(f"  ✗ SSL invalid: {ssl_result.get('error', 'unknown')}")
            all_findings.append({"check": "ssl", "result": ssl_result})
            severity_counts[ssl_result.get("severity", "info")] += 1

        # Main page fetch for headers
        _log("Fetching main page...")
        main_page = _fetch(url)

        # HTTPS redirect check
        if url.startswith("https"):
            http_url = url.replace("https://", "http://")
            http_resp = _fetch(http_url)
            redirects_to_https = http_resp.get("url", "").startswith("https")
            all_findings.append({
                "check": "https_redirect",
                "result": {
                    "redirects": redirects_to_https,
                    "severity": "ok" if redirects_to_https else "warning",
                },
            })

        # Security headers
        if "headers" in check_list:
            _log("Checking security headers...")
            header_findings = _check_security_headers(main_page.get("headers", {}))
            missing = [h for h in header_findings if not h["present"]]
            _log(f"  {len(header_findings) - len(missing)}/{len(header_findings)} headers present, {len(missing)} missing")
            all_findings.append({"check": "security_headers", "result": header_findings})
            for h in header_findings:
                severity_counts[h["severity"]] += 1

        # Server info leakage
        if "server" in check_list:
            _log("Checking server information leakage...")
            server_findings = _check_server_info(main_page.get("headers", {}))
            all_findings.append({"check": "server_info", "result": server_findings})
            for s in server_findings:
                severity_counts[s["severity"]] += 1

        # WordPress checks
        if "wordpress" in check_list:
            _log("Checking for WordPress...")
            wp = _check_wordpress(url)
            all_findings.append({"check": "wordpress", "result": wp})
            for issue in wp.get("issues", []):
                severity_counts[issue["severity"]] += 1

        # Exposed files
        if "files" in check_list:
            _log(f"Checking {len(SENSITIVE_PATHS)} sensitive file paths...")
            file_findings = _check_exposed_files(url)
            all_findings.append({"check": "exposed_files", "result": file_findings})
            for f in file_findings:
                severity_counts[f["severity"]] += 1
            if not file_findings:
                _log("  ✓ No sensitive files exposed")

        # Build insights
        total_issues = severity_counts["critical"] + severity_counts["warning"]
        grade = "A" if total_issues == 0 else "B" if severity_counts["critical"] == 0 and severity_counts["warning"] <= 2 else "C" if severity_counts["critical"] == 0 else "D" if severity_counts["critical"] <= 2 else "F"

        _log(f"Scan complete: {severity_counts['critical']} critical, {severity_counts['warning']} warnings, {severity_counts['info']} info")
        _log(f"Grade: {grade}")

        insights = [
            {
                "type": "security grade",
                "finding": f"Grade: {grade} — {severity_counts['critical']} critical, {severity_counts['warning']} warnings, {severity_counts['info']} info items",
            },
        ]

        # Add critical findings as insights
        for finding in all_findings:
            check_name = finding["check"]
            res = finding["result"]
            if isinstance(res, dict) and res.get("severity") == "critical":
                insights.append({"type": check_name, "finding": str(res), "severity": "critical"})
            elif isinstance(res, list):
                for item in res:
                    if isinstance(item, dict) and item.get("severity") == "critical":
                        insights.append({"type": check_name, "finding": item.get("issue", ""), "severity": "critical"})

        return result(
            name=NAME,
            status="SUCCESS",
            mode=f"LIVE — scanned {url}",
            duration_s=t.elapsed,
            insights=insights,
            findings=all_findings,
            severity_counts=severity_counts,
            grade=grade,
            url=url,
            domain=domain,
        )
