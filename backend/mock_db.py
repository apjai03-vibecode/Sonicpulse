"""
mock_db.py
----------
A lightweight in-memory "database" of acoustic incidents.

For a hackathon build this avoids the overhead of standing up a real
database while still giving /incidents a persistent, growing feed that
mirrors exactly what gets plotted on the frontend map. Swap this module
out for a real store (Postgres + PostGIS, SQLite, etc.) later without
touching main.py's route logic, since it only talks to this module
through get_incidents() / add_incident() / reset().
"""

from datetime import datetime, timezone
from itertools import count
from threading import Lock
from typing import Optional

_lock = Lock()
_id_counter = count(1)

# Seed data mirrors frontend/seed-hotspots.json so the map and the
# /incidents feed agree with each other the moment the server starts.
# Seed data tagged clearly as historical baseline sensors
_SEED_INCIDENTS = [
    {
        "id": "node-001",
        "name": "T. Nagar Commercial Core [Baseline]",
        "zone": "commercial",
        "lat": 13.0418,
        "lng": 80.2341,
        "soundClass": "Car Horn / Traffic",
        "confidence": 86.0,
        "peakDbfs": -18.2,
        "stressIndex": 71.4,
        "stressState": "SEVERE",
        "timestamp": "2026-08-14T08:12:00+05:30",
        "isBaseline": True,
        "source": "Historical Baseline Sensor",
    },
    {
        "id": "node-002",
        "name": "Guindy Industrial Estate [Baseline]",
        "zone": "industrial",
        "lat": 13.0067,
        "lng": 80.2206,
        "soundClass": "Jackhammer / Drilling",
        "confidence": 91.0,
        "peakDbfs": -9.7,
        "stressIndex": 88.9,
        "stressState": "CRITICAL",
        "timestamp": "2026-08-14T07:48:00+05:30",
        "isBaseline": True,
        "source": "Historical Baseline Sensor",
    },
    {
        "id": "node-003",
        "name": "Adyar Residential Block C [Baseline]",
        "zone": "residential",
        "lat": 13.0012,
        "lng": 80.2565,
        "soundClass": "Ambient / Speech",
        "confidence": 77.0,
        "peakDbfs": -34.5,
        "stressIndex": 22.1,
        "stressState": "CALM",
        "timestamp": "2026-08-14T06:30:00+05:30",
        "isBaseline": True,
        "source": "Historical Baseline Sensor",
    },
    {
        "id": "node-004",
        "name": "Anna Nagar Hospital Zone [Baseline]",
        "zone": "hospital",
        "lat": 13.0850,
        "lng": 80.2101,
        "soundClass": "Siren / Alarm",
        "confidence": 95.0,
        "peakDbfs": -6.4,
        "stressIndex": 94.2,
        "stressState": "CRITICAL",
        "timestamp": "2026-08-14T09:02:00+05:30",
        "isBaseline": True,
        "source": "Historical Baseline Sensor",
    },
    {
        "id": "node-005",
        "name": "Koyambedu Transit Corridor [Baseline]",
        "zone": "transit",
        "lat": 13.0694,
        "lng": 80.1948,
        "soundClass": "Bus / Diesel Engine",
        "confidence": 82.0,
        "peakDbfs": -20.1,
        "stressIndex": 63.5,
        "stressState": "MODERATE",
        "timestamp": "2026-08-14T08:55:00+05:30",
        "isBaseline": True,
        "source": "Historical Baseline Sensor",
    },
    {
        "id": "node-006",
        "name": "Velachery Residential Strip [Baseline]",
        "zone": "residential",
        "lat": 12.9791,
        "lng": 80.2212,
        "soundClass": "Dog Bark",
        "confidence": 71.0,
        "peakDbfs": -28.9,
        "stressIndex": 34.8,
        "stressState": "CALM",
        "timestamp": "2026-08-14T05:58:00+05:30",
        "isBaseline": True,
        "source": "Historical Baseline Sensor",
    },
    {
        "id": "node-007",
        "name": "Perungudi Industrial Fringe [Baseline]",
        "zone": "industrial",
        "lat": 12.9634,
        "lng": 80.2419,
        "soundClass": "Jackhammer / Drilling",
        "confidence": 88.0,
        "peakDbfs": -12.8,
        "stressIndex": 79.3,
        "stressState": "SEVERE",
        "timestamp": "2026-08-14T07:20:00+05:30",
        "isBaseline": True,
        "source": "Historical Baseline Sensor",
    },
    {
        "id": "node-008",
        "name": "Egmore Rail Corridor [Baseline]",
        "zone": "transit",
        "lat": 13.0778,
        "lng": 80.2609,
        "soundClass": "Bus / Diesel Engine",
        "confidence": 84.0,
        "peakDbfs": -16.3,
        "stressIndex": 68.0,
        "stressState": "SEVERE",
        "timestamp": "2026-08-14T08:31:00+05:30",
        "isBaseline": True,
        "source": "Historical Baseline Sensor",
    },
]

TELEMETRY_NODES = [
    {"name": "T. Nagar Commercial Core", "zone": "commercial", "lat": 13.0418, "lng": 80.2341},
    {"name": "Guindy Industrial Estate", "zone": "industrial", "lat": 13.0067, "lng": 80.2206},
    {"name": "Adyar Residential Block", "zone": "residential", "lat": 13.0012, "lng": 80.2565},
    {"name": "Anna Nagar Hospital Zone", "zone": "hospital", "lat": 13.0850, "lng": 80.2101},
    {"name": "Koyambedu Transit Corridor", "zone": "transit", "lat": 13.0694, "lng": 80.1948},
]

_incidents: list[dict] = []


def _next_id() -> str:
    return f"live-{next(_id_counter):04d}"


def seed() -> None:
    """Populate the store with the demo baseline dataset if empty."""
    with _lock:
        if not _incidents:
            _incidents.extend(_SEED_INCIDENTS)


def reset() -> None:
    """Clear back to the seed baseline dataset."""
    with _lock:
        _incidents.clear()
        _incidents.extend(_SEED_INCIDENTS)


def add_incident(incident: dict) -> dict:
    """Insert a newly analyzed incident and return it with assigned id and metadata."""
    with _lock:
        incident = dict(incident)
        incident.setdefault("id", _next_id())
        incident.setdefault("timestamp", datetime.now(timezone.utc).astimezone().isoformat())
        incident.setdefault("isBaseline", False)
        incident.setdefault("source", "Live User Detection")
        _incidents.insert(0, incident)
        return incident


def get_incidents(limit: Optional[int] = None) -> list[dict]:
    with _lock:
        ordered = sorted(_incidents, key=lambda i: i["timestamp"], reverse=True)
    return ordered[:limit] if limit else ordered


def node_count() -> int:
    with _lock:
        return len(_incidents)


seed()

