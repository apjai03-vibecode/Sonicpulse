"""
server.py
---------
SonicPulse Flask backend.

Endpoints:
    POST /upload-audio   - analyze an uploaded .wav/.mp3 file (with optional lat/lng)
    POST /record-audio   - analyze a browser-recorded mic blob (with lat/lng)
    GET  /incidents       - recent incidents feed
    GET  /health          - liveness check
"""

from __future__ import annotations

import json
import random
import urllib.request
from flask import Flask, request, jsonify

import mock_db
from audio_engine import analyze_audio_bytes
from stress_calculator import compute_stress_index

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

def _reverse_geocode(lat: float, lng: float) -> tuple[str, str]:
    """
    Convert (lat, lng) into place name & zone using OpenStreetMap Nominatim API.
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

def _place_incident(analysis: dict, stress: dict, lat: float | None = None, lng: float | None = None, custom_location_name: str | None = None) -> dict:
    if lat is not None and lng is not None:
        real_lat = round(float(lat), 6)
        real_lng = round(float(lng), 6)
        if custom_location_name and custom_location_name.strip():
            place_name = custom_location_name.strip()
            zone = "residential" if any(w in place_name.lower() for w in ["mambalam", "nagar", "colony", "street", "road"]) else "commercial"
        else:
            place_name, zone = _reverse_geocode(real_lat, real_lng)
        incident_name = f"{place_name} [Live User Detection]"
    elif custom_location_name and custom_location_name.strip():
        place_name = custom_location_name.strip()
        site = random.choice(mock_db.TELEMETRY_NODES)
        real_lat = site["lat"]
        real_lng = site["lng"]
        zone = site["zone"]
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

def _handle_audio_upload():
    if 'file' not in request.files:
        return jsonify({"detail": "No audio file was provided."}), 400
    
    file = request.files['file']
    raw_bytes = file.read()
    if not raw_bytes:
        return jsonify({"detail": "Uploaded audio file is empty."}), 400

    # Extract optional lat / lng & custom location_name
    lat_val = request.form.get("lat")
    lng_val = request.form.get("lng")
    custom_location_name = request.form.get("location_name")
    lat = float(lat_val) if lat_val is not None and lat_val != "" else None
    lng = float(lng_val) if lng_val is not None and lng_val != "" else None

    try:
        analysis = analyze_audio_bytes(raw_bytes)
    except Exception as exc:
        return jsonify({
            "detail": f"Could not decode audio ({exc}). Ensure ffmpeg is installed and the file is a valid audio clip."
        }), 422

    stress = compute_stress_index(
        peak_dbfs=analysis["peakDbfs"],
        sound_class=analysis["soundClass"],
        confidence_pct=analysis["confidence"],
    )

    incident = _place_incident(analysis, stress, lat=lat, lng=lng, custom_location_name=custom_location_name)

    return jsonify({
        "soundClass": analysis["soundClass"],
        "confidence": analysis["confidence"],
        "peakDbfs": analysis["peakDbfs"],
        "stressIndex": stress["stressIndex"],
        "stressState": stress["stressState"],
        "probabilities": analysis["probabilities"],
        "incident": incident,
    })

@app.route("/upload-audio", methods=["POST", "OPTIONS"])
def upload_audio():
    if request.method == "OPTIONS":
        return "", 200
    return _handle_audio_upload()

@app.route("/record-audio", methods=["POST", "OPTIONS"])
def record_audio():
    if request.method == "OPTIONS":
        return "", 200
    return _handle_audio_upload()

@app.route("/incidents", methods=["GET"])
def get_incidents():
    limit = request.args.get("limit", type=int)
    return jsonify({
        "incidents": mock_db.get_incidents(limit=limit),
        "nodeCount": mock_db.node_count()
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "SYSTEM ACTIVE",
        "nodeCount": mock_db.node_count()
    })

@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "service": "SonicPulse API",
        "endpoints": ["/upload-audio", "/record-audio", "/incidents", "/health"],
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)

