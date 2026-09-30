"""Generate a synthetic Intune device inventory for demos and tests.

The output mirrors the shape of the Microsoft Graph `managedDevices` resource
(the same fields that scripts/Export-IntuneDevices.ps1 exports), so the report
works the same way on sample data and on a real export.

All names, users and devices are fictional.
"""

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIRST_NAMES = ["alex", "maria", "jon", "laura", "david", "sara", "pablo", "elena",
               "marco", "julia", "omar", "ines", "lucas", "nora", "hugo", "clara"]
LAST_NAMES = ["garcia", "rossi", "martin", "dubois", "smith", "yilmaz", "silva",
              "jansen", "lopez", "moreau", "bianchi", "kaya", "novak", "fischer"]
DOMAIN = "contoso-demo.com"
SITES = ["MAD", "PAR", "AMS", "MIL", "IST"]

HARDWARE = {
    "Windows": [("Dell", "Latitude 7440"), ("Lenovo", "ThinkPad T14 Gen 4"),
                ("HP", "EliteBook 840 G10"), ("Microsoft", "Surface Laptop 5")],
    "macOS": [("Apple", "MacBook Pro 14"), ("Apple", "MacBook Air 13")],
    "iOS": [("Apple", "iPhone 14"), ("Apple", "iPhone 15")],
    "Android": [("Samsung", "Galaxy S23"), ("Google", "Pixel 8")],
}
OS_VERSIONS = {
    "Windows": ["10.0.22631.4317", "10.0.22631.3880", "10.0.26100.2033", "10.0.19045.4894"],
    "macOS": ["14.6.1", "15.0.1", "13.6.9"],
    "iOS": ["17.6.1", "18.0.1"],
    "Android": ["14", "13"],
}
OS_WEIGHTS = {"Windows": 0.62, "macOS": 0.12, "iOS": 0.16, "Android": 0.10}


def _pick_os(rng: random.Random) -> str:
    return rng.choices(list(OS_WEIGHTS), weights=list(OS_WEIGHTS.values()))[0]


def generate_devices(count: int = 180, seed: int = 7, as_of: datetime | None = None) -> list[dict]:
    """Return a list of fictional managed devices in Graph `managedDevices` shape."""
    rng = random.Random(seed)
    as_of = as_of or datetime.now(timezone.utc)
    devices = []

    for i in range(count):
        os_name = _pick_os(rng)
        manufacturer, model = rng.choice(HARDWARE[os_name])
        user = f"{rng.choice(FIRST_NAMES)}.{rng.choice(LAST_NAMES)}"
        site = rng.choice(SITES)

        # Most devices check in daily; a minority go quiet (lost, spare, off-network).
        if rng.random() < 0.12:
            days_since_sync = rng.randint(15, 120)
        else:
            days_since_sync = rng.randint(0, 6)
        last_sync = as_of - timedelta(days=days_since_sync, hours=rng.randint(0, 23))

        state = rng.choices(
            ["compliant", "noncompliant", "inGracePeriod", "unknown"],
            weights=[0.82, 0.10, 0.05, 0.03],
        )[0]
        encrypted = rng.random() > (0.02 if os_name in ("iOS", "Android") else 0.07)
        # An unencrypted laptop should not be reported as compliant.
        if not encrypted and state == "compliant":
            state = "noncompliant"

        prefix = {"Windows": "LT", "macOS": "MB", "iOS": "IP", "Android": "AN"}[os_name]
        devices.append({
            "id": f"demo-{i:05d}",
            "deviceName": f"{site}-{prefix}-{1000 + i}",
            "userPrincipalName": f"{user}@{DOMAIN}",
            "operatingSystem": os_name,
            "osVersion": rng.choice(OS_VERSIONS[os_name]),
            "complianceState": state,
            "isEncrypted": encrypted,
            "manufacturer": manufacturer,
            "model": model,
            "managedDeviceOwnerType": "company" if rng.random() > 0.08 else "personal",
            "enrolledDateTime": (last_sync - timedelta(days=rng.randint(30, 900))).isoformat(),
            "lastSyncDateTime": last_sync.isoformat(),
        })
    return devices


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic Intune device inventory.")
    parser.add_argument("--count", type=int, default=180, help="number of devices (default: 180)")
    parser.add_argument("--seed", type=int, default=7, help="random seed for repeatable data")
    parser.add_argument("--output", default="sample_data/managed_devices.json", help="output JSON path")
    args = parser.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(generate_devices(args.count, args.seed), indent=2), encoding="utf-8")
    print(f"Wrote {args.count} fictional devices to {out}")


if __name__ == "__main__":
    main()
