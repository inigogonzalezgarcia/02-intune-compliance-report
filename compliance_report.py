"""Build a device compliance report from an Intune managed-device export.

Input: JSON in Microsoft Graph `managedDevices` shape - either a plain list of
devices or a Graph response object with a "value" list. Produce it with
scripts/Export-IntuneDevices.ps1 or generate_sample_data.py.

Output: a self-contained HTML report and a CSV action list.

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Issue labels, most urgent first. Order drives sorting in the action list.
ISSUES = {
    "noncompliant": "Non-compliant",
    "not_encrypted": "Not encrypted",
    "stale": "No recent sync",
    "grace_period": "In grace period",
    "unknown_state": "Unknown state",
}
ISSUE_RANK = {key: rank for rank, key in enumerate(ISSUES)}


@dataclass
class Finding:
    device: dict
    issues: list[str]
    days_since_sync: int | None


@dataclass
class Summary:
    as_of: datetime
    stale_days: int
    total: int = 0
    compliant: int = 0
    counts: Counter = field(default_factory=Counter)
    by_os: dict = field(default_factory=dict)
    os_versions: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    @property
    def compliance_rate(self) -> float:
        return (self.compliant / self.total * 100) if self.total else 0.0


def load_devices(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("value", [])
    if isinstance(data, dict):  # a single device exported by ConvertTo-Json
        data = [data]
    if not isinstance(data, list):
        raise ValueError("Expected a list of devices or a Graph response with a 'value' list.")
    return data


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def device_issues(device: dict, as_of: datetime, stale_days: int) -> tuple[list[str], int | None]:
    """Return the issue keys that apply to one device, and days since its last sync."""
    issues = []
    state = str(device.get("complianceState", "unknown"))
    if state in ("noncompliant", "conflict", "error"):
        issues.append("noncompliant")
    elif state == "inGracePeriod":
        issues.append("grace_period")
    elif state not in ("compliant",):
        issues.append("unknown_state")

    if device.get("isEncrypted") is False:
        issues.append("not_encrypted")

    last_sync = _parse_dt(device.get("lastSyncDateTime"))
    days = None
    if last_sync is not None:
        days = max(0, (as_of - last_sync).days)
        if days > stale_days:
            issues.append("stale")
    else:
        issues.append("stale")

    issues.sort(key=ISSUE_RANK.get)
    return issues, days


def analyse(devices: list[dict], as_of: datetime | None = None, stale_days: int = 14) -> Summary:
    as_of = as_of or datetime.now(timezone.utc)
    summary = Summary(as_of=as_of, stale_days=stale_days, total=len(devices))
    os_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [total, compliant]
    versions: dict[str, Counter] = defaultdict(Counter)

    for device in devices:
        os_name = device.get("operatingSystem") or "Unknown"
        os_totals[os_name][0] += 1
        versions[os_name][device.get("osVersion") or "Unknown"] += 1

        issues, days = device_issues(device, as_of, stale_days)
        if device.get("complianceState") == "compliant":
            summary.compliant += 1
            os_totals[os_name][1] += 1
        summary.counts.update(issues)
        if issues:
            summary.findings.append(Finding(device, issues, days))

    summary.by_os = dict(sorted(os_totals.items(), key=lambda kv: -kv[1][0]))
    summary.os_versions = {os_name: dict(c.most_common()) for os_name, c in versions.items()}
    summary.findings.sort(key=lambda f: (ISSUE_RANK[f.issues[0]], -(f.days_since_sync or 0)))
    return summary


def write_action_csv(summary: Summary, path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["deviceName", "userPrincipalName", "operatingSystem", "osVersion",
                         "complianceState", "isEncrypted", "daysSinceLastSync", "issues"])
        for f in summary.findings:
            d = f.device
            writer.writerow([d.get("deviceName"), d.get("userPrincipalName"), d.get("operatingSystem"),
                             d.get("osVersion"), d.get("complianceState"), d.get("isEncrypted"),
                             "" if f.days_since_sync is None else f.days_since_sync,
                             "; ".join(ISSUES[i] for i in f.issues)])


# --------------------------------------------------------------------------- HTML

CSS = """
:root{--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--border:rgba(11,11,11,.10);--bar:#2a78d6;
--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b}
@media (prefers-color-scheme:dark){:root{--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;
--grid:#2c2c2a;--border:rgba(255,255,255,.10);--bar:#3987e5}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 16px 48px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 12px}
.meta{color:var(--ink2);margin:0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:24px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.tile .label{color:var(--ink2);font-size:13px}.tile .value{font-size:28px;font-weight:600;font-variant-numeric:tabular-nums}
.tile .note{color:var(--muted);font-size:12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:4px 16px;overflow-x:auto}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--grid);white-space:nowrap}
th.num{text-align:right}
th{color:var(--ink2);font-weight:500;font-size:13px}tr:last-child td{border-bottom:0}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.bar{height:8px;background:var(--grid);border-radius:4px;min-width:120px}
.bar span{display:block;height:8px;background:var(--bar);border-radius:4px}
.badge{display:inline-flex;align-items:center;gap:4px;margin:0 6px 2px 0;font-size:12px;color:var(--ink)}
.badge i{width:8px;height:8px;border-radius:50%;display:inline-block}
.critical i{background:var(--critical)}.serious i{background:var(--serious)}.warning i{background:var(--warning)}
.badge b{font-weight:600}
footer{color:var(--muted);font-size:12px;margin-top:32px}
"""

# status role + icon per issue, so colour never carries meaning alone
ISSUE_STYLE = {
    "noncompliant": ("critical", "&#10005;"),
    "not_encrypted": ("critical", "&#10005;"),
    "stale": ("serious", "!"),
    "grace_period": ("warning", "!"),
    "unknown_state": ("warning", "?"),
}


def _badge(issue: str) -> str:
    role, icon = ISSUE_STYLE[issue]
    return f'<span class="badge {role}"><i></i><b>{icon}</b>{ISSUES[issue]}</span>'


def render_html(summary: Summary, title: str = "Device Compliance Report") -> str:
    e = html.escape
    rate = summary.compliance_rate
    tiles = [
        ("Managed devices", f"{summary.total:,}", "in this export"),
        ("Compliance rate", f"{rate:.1f}%", f"{summary.compliant:,} compliant"),
        ("Non-compliant", f"{summary.counts['noncompliant']:,}", "policy failures"),
        ("Not encrypted", f"{summary.counts['not_encrypted']:,}", "disk encryption off"),
        ("No recent sync", f"{summary.counts['stale']:,}", f"over {summary.stale_days} days"),
    ]
    tiles_html = "".join(
        f'<div class="tile"><div class="label">{e(l)}</div><div class="value">{v}</div>'
        f'<div class="note">{e(n)}</div></div>' for l, v, n in tiles)

    os_rows = []
    for os_name, (total, compliant) in summary.by_os.items():
        pct = compliant / total * 100 if total else 0
        os_rows.append(
            f"<tr><td>{e(os_name)}</td><td class='num'>{total}</td><td class='num'>{compliant}</td>"
            f"<td class='num'>{pct:.1f}%</td><td title='{e(os_name)}: {pct:.1f}% compliant'>"
            f"<div class='bar'><span style='width:{pct:.1f}%'></span></div></td></tr>")

    version_rows = []
    for os_name, versions in summary.os_versions.items():
        total = sum(versions.values())
        for version, n in versions.items():
            version_rows.append(f"<tr><td>{e(os_name)}</td><td>{e(version)}</td>"
                                f"<td class='num'>{n}</td><td class='num'>{n / total * 100:.0f}%</td></tr>")

    finding_rows = []
    for f in summary.findings:
        d = f.device
        days = "never" if f.days_since_sync is None else f"{f.days_since_sync} d"
        finding_rows.append(
            f"<tr><td>{e(str(d.get('deviceName', '')))}</td><td>{e(str(d.get('userPrincipalName', '')))}</td>"
            f"<td>{e(str(d.get('operatingSystem', '')))} {e(str(d.get('osVersion', '')))}</td>"
            f"<td class='num'>{days}</td><td>{''.join(_badge(i) for i in f.issues)}</td></tr>")
    if not finding_rows:
        finding_rows.append("<tr><td colspan='5'>No devices need action.</td></tr>")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head>
<body><main>
<h1>{e(title)}</h1>
<p class="meta">Data as of {summary.as_of:%d %b %Y %H:%M} UTC &middot; stale threshold {summary.stale_days} days</p>
<section class="tiles">{tiles_html}</section>
<h2>Compliance by operating system</h2>
<div class="card"><table><thead><tr><th>OS</th><th class='num'>Devices</th><th class='num'>Compliant</th><th class='num'>Rate</th><th></th></tr></thead>
<tbody>{''.join(os_rows)}</tbody></table></div>
<h2>Devices that need action ({len(summary.findings)})</h2>
<div class="card"><table><thead><tr><th>Device</th><th>User</th><th>OS</th><th class='num'>Last sync</th><th>Issues</th></tr></thead>
<tbody>{''.join(finding_rows)}</tbody></table></div>
<h2>OS versions in use</h2>
<div class="card"><table><thead><tr><th>OS</th><th>Version</th><th class='num'>Devices</th><th class='num'>Share</th></tr></thead>
<tbody>{''.join(version_rows)}</tbody></table></div>
<footer>Generated by intune-compliance-report.</footer>
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a device compliance report from an Intune export.")
    parser.add_argument("input", help="JSON export of managed devices")
    parser.add_argument("--out-dir", default="output", help="folder for report.html and action_list.csv")
    parser.add_argument("--stale-days", type=int, default=14, help="days without sync before a device is flagged")
    parser.add_argument("--title", default="Device Compliance Report", help="report title")
    args = parser.parse_args()

    summary = analyse(load_devices(args.input), stale_days=args.stale_days)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(render_html(summary, args.title), encoding="utf-8")
    write_action_csv(summary, out / "action_list.csv")

    print(f"{summary.total} devices, {summary.compliance_rate:.1f}% compliant, "
          f"{len(summary.findings)} need action.")
    print(f"Report: {out / 'report.html'}\nAction list: {out / 'action_list.csv'}")


if __name__ == "__main__":
    main()
