"""
main.py
-------
SonicPulse FastAPI backend.

Endpoints:
    POST /upload-audio   - analyze an uploaded .wav/.mp3 file
    POST /record-audio   - analyze a browser-recorded mic blob (webm/opus)
    GET  /incidents       - recent incidents feed, same shape the map renders
    GET  /health          - liveness check

Both /upload-audio and /record-audio return the exact same response
shape, so the browser never has to know whether analysis came from a
real classifier or (on error) a fallback — see audio_engine.py for the
classification pipeline and stress_calculator.py for the scoring.
"""

from __future__ import annotations

import json
import random
import urllib.request

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import mock_db
from audio_engine import analyze_audio_bytes
from stress_calculator import compute_stress_index

app = FastAPI(
    title="SonicPulse API",
    description="Acoustic Intelligence & Urban Noise Pollution Stress Mapper",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProbabilityItem(BaseModel):
    label: str
    value: float


class AnalysisResponse(BaseModel):
    soundClass: str
    confidence: float
    peakDbfs: float
    stressIndex: float
    stressState: str
    probabilities: list[ProbabilityItem]
    incident: dict


def _reverse_geocode(lat: float, lng: float) -> tuple[str, str]:
    """
    Convert (lat, lng) into human-readable place name using OpenStreetMap Nominatim API.
    """
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lng}"
        req = urllib.request.Request(url, headers={"User-Agent": "SonicPulse/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            address = data.get("address", {})
            place = (
                address.get("road")
                or address.get("suburb")
                or address.get("neighbourhood")
                or address.get("city_district")
                or address.get("city")
                or address.get("town")
                or data.get("name")
            )
            city = address.get("city") or address.get("town") or address.get("state") or ""
            if place and city and place != city:
                location_name = f"{place}, {city}"
            elif place:
                location_name = place
            else:
                location_name = f"Location ({lat:.4f}, {lng:.4f})"

            category = data.get("category", "")
            zone = "commercial"
            if "hospital" in category or "medical" in category:
                zone = "hospital"
            elif "residential" in category or "house" in category:
                zone = "residential"
            elif "industrial" in category or "factory" in category:
                zone = "industrial"
            elif "railway" in category or "highway" in category or "transport" in category:
                zone = "transit"
            return location_name, zone
    except Exception:
        return f"Telemetry Node ({lat:.4f}, {lng:.4f})", "commercial"


def _place_incident(analysis: dict, stress: dict, lat: float | None = None, lng: float | None = None) -> dict:
    if lat is not None and lng is not None:
        real_lat = round(float(lat), 6)
        real_lng = round(float(lng), 6)
        place_name, zone = _reverse_geocode(real_lat, real_lng)
        incident_name = f"{place_name} [Live User Detection]"
    else:
        site = random.choice(mock_db.TELEMETRY_NODES)
        jitter_lat = (random.random() - 0.5) * 0.006
        jitter_lng = (random.random() - 0.5) * 0.006
        real_lat = round(site["lat"] + jitter_lat, 6)
        real_lng = round(site["lng"] + jitter_lng, 6)
        zone = site["zone"]
        incident_name = f"{site['name']} [User Incident]"

    incident = {
        "name": incident_name,
        "zone": zone,
        "lat": real_lat,
        "lng": real_lng,
        "soundClass": analysis["soundClass"],
        "confidence": analysis["confidence"],
        "peakDbfs": analysis["peakDbfs"],
        "stressIndex": stress["stressIndex"],
        "stressState": stress["stressState"],
        "isBaseline": False,
        "source": "Live User Detection",
    }
    return mock_db.add_incident(incident)


async def _handle_audio_upload(
    file: UploadFile,
    lat: float | None = None,
    lng: float | None = None,
) -> AnalysisResponse:
    if file is None:
        raise HTTPException(status_code=400, detail="No audio file was provided.")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

    try:
        analysis = analyze_audio_bytes(raw_bytes)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not decode audio ({exc}). Ensure ffmpeg is installed and valid audio clip.",
        ) from exc

    stress = compute_stress_index(
        peak_dbfs=analysis["peakDbfs"],
        sound_class=analysis["soundClass"],
        confidence_pct=analysis["confidence"],
    )

    incident = _place_incident(analysis, stress, lat=lat, lng=lng)

    return AnalysisResponse(
        soundClass=analysis["soundClass"],
        confidence=analysis["confidence"],
        peakDbfs=analysis["peakDbfs"],
        stressIndex=stress["stressIndex"],
        stressState=stress["stressState"],
        probabilities=[ProbabilityItem(**p) for p in analysis["probabilities"]],
        incident=incident,
    )


@app.post("/upload-audio", response_model=AnalysisResponse)
async def upload_audio(
    file: UploadFile = File(...),
    lat: float | None = Form(None),
    lng: float | None = Form(None),
) -> AnalysisResponse:
    """Analyze a user-uploaded file with optional user latitude/longitude."""
    return await _handle_audio_upload(file, lat=lat, lng=lng)


@app.post("/record-audio", response_model=AnalysisResponse)
async def record_audio(
    file: UploadFile = File(...),
    lat: float | None = Form(None),
    lng: float | None = Form(None),
) -> AnalysisResponse:
    """Analyze a browser-recorded mic clip tagged with user's Geolocation API coordinates."""
    return await _handle_audio_upload(file, lat=lat, lng=lng)



@app.get("/incidents")
async def get_incidents(limit: int | None = None) -> dict:
    """Recent acoustic incidents, most recent first — powers the map and feed."""
    return {"incidents": mock_db.get_incidents(limit=limit), "nodeCount": mock_db.node_count()}


@app.get("/health")
async def health() -> dict:
    return {"status": "SYSTEM ACTIVE", "nodeCount": mock_db.node_count()}


@app.get("/")
async def root() -> dict:
    return {
        "service": "SonicPulse API",
        "endpoints": ["/upload-audio", "/record-audio", "/incidents", "/health"],
    }
