import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_report import analyse, device_issues, load_devices, render_html  # noqa: E402
from generate_sample_data import generate_devices  # noqa: E402

AS_OF = datetime(2026, 10, 1, tzinfo=timezone.utc)


def device(**overrides):
    base = {
        "deviceName": "MAD-LT-1000",
        "userPrincipalName": "demo.user@contoso-demo.com",
        "operatingSystem": "Windows",
        "osVersion": "10.0.22631.4317",
        "complianceState": "compliant",
        "isEncrypted": True,
        "lastSyncDateTime": (AS_OF - timedelta(days=1)).isoformat(),
    }
    base.update(overrides)
    return base


def test_healthy_device_has_no_issues():
    issues, days = device_issues(device(), AS_OF, stale_days=14)
    assert issues == []
    assert days == 1


def test_issues_are_detected_and_ordered_by_urgency():
    d = device(complianceState="noncompliant", isEncrypted=False,
               lastSyncDateTime=(AS_OF - timedelta(days=40)).isoformat())
    issues, days = device_issues(d, AS_OF, stale_days=14)
    assert issues == ["noncompliant", "not_encrypted", "stale"]
    assert days == 40


def test_missing_sync_date_counts_as_stale():
    issues, days = device_issues(device(lastSyncDateTime=None), AS_OF, stale_days=14)
    assert issues == ["stale"]
    assert days is None


def test_graph_zulu_timestamps_are_parsed():
    issues, days = device_issues(device(lastSyncDateTime="2026-09-30T08:00:00Z"), AS_OF, 14)
    assert issues == [] and days == 0


def test_summary_totals():
    devices = [device(), device(complianceState="inGracePeriod"), device(complianceState="noncompliant")]
    s = analyse(devices, as_of=AS_OF)
    assert s.total == 3 and s.compliant == 1
    assert round(s.compliance_rate, 1) == 33.3
    assert s.counts["grace_period"] == 1 and s.counts["noncompliant"] == 1
    assert s.findings[0].issues[0] == "noncompliant"


def test_loads_graph_response_shape(tmp_path):
    path = tmp_path / "export.json"
    path.write_text(json.dumps({"value": [device()]}), encoding="utf-8")
    assert len(load_devices(path)) == 1


def test_sample_data_renders_report():
    devices = generate_devices(count=50, seed=1, as_of=AS_OF)
    s = analyse(devices, as_of=AS_OF)
    page = render_html(s)
    assert "Device Compliance Report" in page
    assert s.total == 50
    # generator never marks an unencrypted device as compliant
    assert all(d["isEncrypted"] or d["complianceState"] != "compliant" for d in devices)
