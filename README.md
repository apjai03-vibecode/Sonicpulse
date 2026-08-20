# 🔊 SonicPulse — Urban Acoustic Intelligence Platform

> Real-time urban noise monitoring, classification, and stress mapping for Smart Cities.

**Hackathon Project · Smart Cities / AI · 2026**

---

## 🌐 Live Demo Setup

| Server | URL |
|--------|-----|
| Frontend | `http://localhost:5500` |
| Backend API | `http://localhost:8000` |

---

## ✨ What It Does

SonicPulse turns your microphone or an uploaded audio clip into a live **Urban Acoustic Stress Index** — it:

1. **Records or uploads** audio directly from the browser
2. **Classifies** the sound using a spectral feature engine (YAMNet AudioSet vocabulary: Siren, Dog Bark, Jackhammer/Drilling, Car Horn/Traffic, Engine/Heavy Machinery, Speech, Wind)
3. **Geolocates** the incident using the browser's Geolocation API, a map pin-drop, or a typed area name (e.g. "West Mambalam", "T. Nagar")
4. **Reverse-geocodes** coordinates to place names using OpenStreetMap Nominatim
5. **Plots** a live radar marker on a dark-mode Leaflet + OpenStreetMap map of Chennai with heatmap overlay, zone filters, and a live incident feed

---

## 🏗️ Project Layout

```
sonicpulse/
├── frontend/
│   ├── index.html          # Main dashboard UI
│   ├── styles.css          # Dark-mode premium design system
│   ├── app.js              # Audio capture, WAV encoder, API calls
│   └── map.js              # Leaflet map, heatmap, incident markers
└── backend/
    ├── server.py           # Flask API server (port 8000)
    ├── audio_engine.py     # Audio decoding + spectral classification engine
    ├── stress_calculator.py# Urban Stress Index (0–100 score)
    ├── mock_db.py          # In-memory incident store + baseline sensors
    ├── yamnet_class_map.csv# YAMNet AudioSet 521-class vocabulary
    └── requirements.txt    # Python dependencies
```

---

## 🧠 Architecture

```
Browser
  │
  ├── 🎙️ Mic Mode: AudioContext → ScriptProcessor → Float32Array PCM
  │                             → encodeWavMono() → 16kHz WAV Blob
  │
  └── 📁 File Mode: Drag & drop audio file
  │
  ├── 📍 Location: GPS (Geolocation API) | Map pin | Typed area name
  │
  └──── POST /record-audio  ──────────────────────────────────────────┐
        POST /upload-audio                                             │
                                                                       ▼
                                                              Flask server.py
                                                                       │
                                                         audio_engine.py
                                                         ├── _decode_wav_native()   (stdlib, no ffmpeg)
                                                         ├── extract_features()     (STFT, ZCR, centroid)
                                                         └── classify_yamnet()      (7-class scoring)
                                                                       │
                                                         stress_calculator.py
                                                         └── Urban Stress Index (0–100)
                                                                       │
                                                         Nominatim reverse geocoding
                                                         └── (lat,lng) → place name
                                                                       │
                                                              mock_db.py
                                                              └── store incident
                                                                       │
                                                         JSON response ←──────────────┘
                                                                       │
                                              app.js renders dial / banner / chart
                                              map.js  plots radar marker + heatmap
```

---

## 🔬 Classifier: Spectral Feature Engine

`audio_engine.py` classifies sounds using a **discriminative spectral feature engine** inspired by the YAMNet AudioSet vocabulary (521 classes):

| Feature | Description |
|---------|-------------|
| **Spectral centroid** | Frequency "centre of gravity" — speech: 600–3000 Hz |
| **Zero-crossing rate** | Rate of sign changes — speech: 0.03–0.30 |
| **Crest factor** | Peak-to-RMS ratio — speech: 3–10, dog bark: 10–30 |
| **Band energies** | Low/mid/high/air energy ratios |
| **Spectral flatness** | Tone (low flatness) vs noise (high flatness) |
| **RMS & peak dBFS** | Loudness level |

**No ffmpeg required** — WAV audio from the browser is decoded natively using Python's built-in `wave` module.

### Sound Classes

| Class | AudioSet Index | Key Features |
|-------|---------------|-------------|
| Siren | 318 | High freq, low ZCR, sustained tone |
| Jackhammer / Drilling | 358 | High ZCR, broadband, impulsive |
| Car Horn / Traffic | 322 | Mid-range, sustained, loud |
| Engine / Heavy Machinery | 367 | Low-frequency rumble |
| Dog Bark | 74 | Very high crest factor (impulsive) |
| Speech / Human Voice | 0 | Mid centroid, speech ZCR, smooth envelope |
| Wind / Environmental | 500 | High spectral flatness, wideband |

---

## 📍 Location Modes

| Mode | How It Works |
|------|-------------|
| **📡 GPS** | Browser Geolocation API → real lat/lng |
| **🗺️ Map Pin** | Click anywhere on Leaflet map to drop a pin |
| **🔍 Area Name** | Type "West Mambalam", "T. Nagar" etc. → Nominatim forward geocoding |

Coordinates are reverse-geocoded to human-readable place names using [OpenStreetMap Nominatim](https://nominatim.org/).

---

## 🚀 Running Locally

### Prerequisites

- **Python 3.10+**
- No ffmpeg required for microphone recordings (WAV decoded natively)
- ffmpeg optional for uploaded mp3/ogg/webm files

### 1. Start the Backend

```bash
cd backend
pip install -r requirements.txt
python server.py
```

Backend runs at `http://localhost:8000`. Verify: `curl http://localhost:8000/health`

### 2. Serve the Frontend

Open a second terminal:

```bash
cd frontend
python -m http.server 5500
```

Visit **`http://localhost:5500`** in your browser.

> ⚠️ Must open via `http://localhost:5500`, NOT `file://`. The Microphone API requires a secure HTTP context.

### One-shot (Linux/macOS)

```bash
chmod +x run.sh && ./run.sh
```

---

## 🗂️ API Reference

### `POST /upload-audio`
Upload an audio file for classification.

**Form fields:**
| Field | Type | Description |
|-------|------|-------------|
| `file` | Binary | Audio file (WAV, MP3, OGG, WebM) |
| `lat` | Float | Optional latitude |
| `lng` | Float | Optional longitude |
| `location_name` | String | Optional area name override (e.g. "West Mambalam") |

### `POST /record-audio`
Same as `/upload-audio` — accepts microphone WAV blob.

### `GET /incidents`
Returns all logged incidents + telemetry node count.

### `GET /health`
System health check.

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | HTML5, Vanilla CSS, JavaScript (ES2020) |
| Map | Leaflet.js + OpenStreetMap + leaflet.heat |
| Charts | Chart.js |
| Backend | Python 3 + Flask |
| Audio decode | Python `wave` stdlib (native, no ffmpeg) |
| Geocoding | OpenStreetMap Nominatim (free, no API key) |
| Icons | Lucide Icons |
| Fonts | Space Grotesk, JetBrains Mono, Inter |

---

## 📝 Notes

- `mock_db.py` is **in-memory** — incidents reset when the server restarts. Swap in SQLite / PostgreSQL for persistence.
- CORS is open (`*`) for local development — restrict to your deployed frontend origin before shipping.
- The 10 baseline telemetry nodes in `mock_db.py` are pre-seeded historical sensors tagged `isBaseline: true`.
- Live user incidents are tagged `isBaseline: false` with `"source": "Live User Detection"`.
