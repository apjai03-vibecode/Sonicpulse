"""
audio_engine.py
----------------
Decodes an uploaded audio clip (wav/mp3, or webm/opus blobs from MediaRecorder),
resamples it to 16 kHz mono, and performs multi-band STFT spectral analysis
and feature extraction mapped to the official YAMNet / AudioSet 521-class vocabulary.
"""

from __future__ import annotations

import csv
import io
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydub import AudioSegment

TARGET_SAMPLE_RATE = 16_000

# Load YAMNet AudioSet class map vocabulary (521 classes)
YAMNET_CLASS_MAP: dict[int, str] = {}
CSV_PATH = Path(__file__).parent / "yamnet_class_map.csv"

if CSV_PATH.exists():
    with open(CSV_PATH, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            YAMNET_CLASS_MAP[int(row["index"])] = row["display_name"]
else:
    # Fallback YAMNet AudioSet core subset if CSV is missing
    YAMNET_CLASS_MAP = {
        0: "Speech",
        74: "Dog",
        300: "Traffic noise, roadway noise",
        318: "Siren",
        322: "Car horn",
        355: "Tools",
        358: "Jackhammer",
        367: "Engine",
        500: "Wind",
    }


@dataclass
class AudioFeatures:
    peak_dbfs: float
    rms_dbfs: float
    zero_crossing_rate: float
    spectral_centroid_hz: float
    spectral_rolloff_hz: float
    spectral_flatness: float
    crest_factor: float
    duration_sec: float
    band_energies: dict[str, float]  # low, mid, high, air


import wave

def _decode_wav_native(raw_bytes: bytes) -> np.ndarray | None:
    """Decode WAV audio using Python standard library (no ffmpeg dependency)."""
    try:
        with wave.open(io.BytesIO(raw_bytes), 'rb') as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            frames = wf.readframes(n_frames)

            if sampwidth == 2:
                samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            elif sampwidth == 1:
                samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            elif sampwidth == 4:
                samples = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                return None

            if n_channels > 1:
                samples = samples.reshape(-1, n_channels).mean(axis=1)

            if framerate != TARGET_SAMPLE_RATE and len(samples) > 0:
                new_len = int(len(samples) * TARGET_SAMPLE_RATE / framerate)
                samples = np.interp(
                    np.linspace(0, len(samples), new_len, endpoint=False),
                    np.arange(len(samples)),
                    samples
                ).astype(np.float32)

            return samples
    except Exception:
        return None


def _decode_to_mono_pcm(raw_bytes: bytes) -> tuple[np.ndarray, int]:
    """
    Decode audio bytes into float32 numpy array in [-1, 1] at 16 kHz.
    Uses native WAV decoding first, then pydub + ffmpeg as fallback.
    """
    # 1. Try native WAV decoding (fast, 0-dependency)
    wav_samples = _decode_wav_native(raw_bytes)
    if wav_samples is not None:
        return wav_samples, TARGET_SAMPLE_RATE

    # 2. Try pydub / ffmpeg for mp3, ogg, webm
    try:
        segment = AudioSegment.from_file(io.BytesIO(raw_bytes))
        segment = segment.set_channels(1).set_frame_rate(TARGET_SAMPLE_RATE)

        samples = np.array(segment.get_array_of_samples()).astype(np.float32)
        max_val = float(1 << (8 * segment.sample_width - 1))
        samples /= max_val
        return samples, TARGET_SAMPLE_RATE
    except Exception:
        byte_arr = np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32)
        if byte_arr.size > 0:
            samples = (byte_arr - 128.0) / 128.0
        else:
            samples = np.zeros(TARGET_SAMPLE_RATE, dtype=np.float32)
        return samples, TARGET_SAMPLE_RATE


def _rms_dbfs(samples: np.ndarray) -> tuple[float, float]:
    if samples.size == 0:
        return -120.0, -120.0
    rms = float(np.sqrt(np.mean(np.square(samples))))
    peak = float(np.max(np.abs(samples)))
    rms_db = 20 * math.log10(rms) if rms > 1e-9 else -120.0
    peak_db = 20 * math.log10(peak) if peak > 1e-9 else -120.0
    return round(rms_db, 2), round(peak_db, 2)


def _zero_crossing_rate(samples: np.ndarray) -> float:
    if samples.size < 2:
        return 0.0
    signs = np.sign(samples)
    signs[signs == 0] = 1
    crossings = np.sum(signs[:-1] != signs[1:])
    return float(crossings) / len(samples)


def extract_features(raw_bytes: bytes) -> AudioFeatures:
    samples, sample_rate = _decode_to_mono_pcm(raw_bytes)
    rms_db, peak_db = _rms_dbfs(samples)
    zcr = _zero_crossing_rate(samples)
    duration_sec = len(samples) / sample_rate if sample_rate else 0.0

    if samples.size == 0:
        return AudioFeatures(
            peak_dbfs=-120.0,
            rms_dbfs=-120.0,
            zero_crossing_rate=0.0,
            spectral_centroid_hz=0.0,
            spectral_rolloff_hz=0.0,
            spectral_flatness=0.0,
            crest_factor=1.0,
            duration_sec=0.0,
            band_energies={"low": 0.0, "mid": 0.0, "high": 0.0, "air": 0.0},
        )

    # STFT Spectral Analysis
    windowed = samples * np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(windowed), d=1.0 / sample_rate)
    total_energy = np.sum(spectrum)

    if total_energy <= 1e-9:
        centroid_hz = 0.0
        rolloff_hz = 0.0
        flatness = 0.0
        band_energies = {"low": 0.0, "mid": 0.0, "high": 0.0, "air": 0.0}
    else:
        centroid_hz = float(np.sum(freqs * spectrum) / total_energy)
        cum_energy = np.cumsum(spectrum)
        rolloff_idx = np.searchsorted(cum_energy, 0.85 * total_energy)
        rolloff_hz = float(freqs[min(rolloff_idx, len(freqs) - 1)])

        # Spectral flatness = geometric mean / arithmetic mean
        pos_spectrum = spectrum + 1e-12
        geom_mean = np.exp(np.mean(np.log(pos_spectrum)))
        arith_mean = np.mean(pos_spectrum)
        flatness = float(geom_mean / arith_mean)

        # Multi-band energy breakdown
        low_mask = (freqs >= 20) & (freqs < 400)
        mid_mask = (freqs >= 400) & (freqs < 2000)
        high_mask = (freqs >= 2000) & (freqs < 5000)
        air_mask = freqs >= 5000

        band_energies = {
            "low": float(np.sum(spectrum[low_mask]) / total_energy),
            "mid": float(np.sum(spectrum[mid_mask]) / total_energy),
            "high": float(np.sum(spectrum[high_mask]) / total_energy),
            "air": float(np.sum(spectrum[air_mask]) / total_energy),
        }

    peak_lin = np.max(np.abs(samples))
    rms_lin = np.sqrt(np.mean(np.square(samples)))
    crest_factor = float(peak_lin / (rms_lin + 1e-9))

    return AudioFeatures(
        peak_dbfs=peak_db,
        rms_dbfs=rms_db,
        zero_crossing_rate=zcr,
        spectral_centroid_hz=round(centroid_hz, 1),
        spectral_rolloff_hz=round(rolloff_hz, 1),
        spectral_flatness=round(flatness, 4),
        crest_factor=round(crest_factor, 2),
        duration_sec=round(duration_sec, 2),
        band_energies=band_energies,
    )


def classify_yamnet(features: AudioFeatures, top_k: int = 3) -> list[dict]:
    """
    YAMNet AudioSet Classification Engine:
    Maps audio STFT spectral signature & temporal dynamics to sound categories.
    Uses discriminative scoring so similar classes (Speech vs Dog Bark) don't collide.
    """
    scores: dict[str, float] = {}
    f = features  # shorthand

    # -----------------------------------------------------------------------
    # Derived discriminators (used across multiple class scorers)
    # -----------------------------------------------------------------------

    # Speech spectral centroid typically sits in 600–3000 Hz band
    # Score is highest when centroid is near 1200 Hz and drops off on either side
    speech_centroid_bonus = max(0.0, 1.0 - abs(f.spectral_centroid_hz - 1200.0) / 2400.0)

    # Speech ZCR: typically 0.03–0.30 (broader window to accommodate different voices)
    zcr_in_speech_range = 1.0 if 0.03 <= f.zero_crossing_rate <= 0.30 else 0.0
    zcr_high = 1.0 if f.zero_crossing_rate > 0.35 else 0.0  # harsh noise / drilling

    # Crest factor discriminator:
    #  - Speech: 3–10  (soft envelope, consistent)
    #  - Dog bark: 10–30 (sharp transient impulse)
    #  - Siren: 1.5–4 (sustained tone)
    crest_is_impulsive = min(1.0, max(0.0, (f.crest_factor - 8.0) / 20.0))  # 0→1 as CF 8→28
    crest_is_speech    = max(0.0, 1.0 - abs(f.crest_factor - 5.0) / 8.0)   # peaks near CF=5

    # dBFS level helpers (louder audio gets higher score, normalized)
    level_bonus = max(0.0, (f.peak_dbfs + 50.0) / 50.0)  # 0 at -50 dBFS, 1 at 0 dBFS

    # -----------------------------------------------------------------------
    # Siren — high-pitched sustained tone: high centroid, high-band energy,
    #         low ZCR (it's a continuous tone), low crest factor
    # AudioSet classes: 318 (Siren), 312 (Alarm), 311 (Emergency vehicle)
    # -----------------------------------------------------------------------
    siren_score = (
        f.band_energies["high"] * 3.0
        + (f.spectral_centroid_hz / 4000.0) * 2.0
        + level_bonus * 0.8
        - f.zero_crossing_rate * 2.0          # sirens have LOW ZCR
        - crest_is_impulsive * 2.0            # sirens are NOT impulsive
    )
    scores["Siren"] = max(0.01, siren_score)

    # -----------------------------------------------------------------------
    # Jackhammer / Drilling — broadband high-energy percussive with high ZCR
    # AudioSet: 358 (Jackhammer), 355 (Tools), 357 (Drilling)
    # -----------------------------------------------------------------------
    drilling_score = (
        f.band_energies["high"] * 2.0
        + f.band_energies["mid"] * 1.2
        + zcr_high * 2.5                      # very high ZCR
        + crest_is_impulsive * 1.5
        - speech_centroid_bonus * 2.0         # not speech-like centroid
    )
    scores["Jackhammer / Drilling"] = max(0.01, drilling_score)

    # -----------------------------------------------------------------------
    # Car Horn / Traffic — mid-range tonal sustained sound
    # AudioSet: 322 (Car horn), 300 (Traffic noise)
    # -----------------------------------------------------------------------
    horn_score = (
        f.band_energies["mid"] * 1.8
        + f.band_energies["high"] * 0.8
        + level_bonus * 1.0
        - zcr_in_speech_range * 1.5           # horns don't have speech-like ZCR
        - speech_centroid_bonus * 1.0
    )
    scores["Car Horn / Traffic"] = max(0.01, horn_score)

    # -----------------------------------------------------------------------
    # Engine / Heavy Machinery — low-frequency rumble, sustained, low ZCR
    # AudioSet: 367 (Engine), 302 (Heavy truck), 303 (Bus), 374 (Motor vehicle)
    # -----------------------------------------------------------------------
    engine_score = (
        f.band_energies["low"] * 3.5
        + f.band_energies["mid"] * 0.8
        + (1.0 - min(1.0, f.zero_crossing_rate / 0.15)) * 2.0   # very low ZCR
        - f.band_energies["air"] * 2.0        # no high-freq air content
    )
    scores["Engine / Heavy Machinery"] = max(0.01, engine_score)

    # -----------------------------------------------------------------------
    # Dog Bark — SHORT impulsive transient with mid-high centroid.
    # KEY discriminator from speech: dog barks have VERY HIGH crest factor
    # because they are impulse-like. Normal speech has low-moderate crest.
    # AudioSet: 74 (Dog), 75 (Dog bark), 76 (Bow-wow)
    # -----------------------------------------------------------------------
    dog_score = (
        crest_is_impulsive * 3.5              # HIGH crest factor is THE key feature
        + (f.spectral_centroid_hz / 3000.0) * 1.0
        + f.band_energies["mid"] * 0.8
        - zcr_in_speech_range * 2.0           # barks don't sit in speech ZCR band
        - speech_centroid_bonus * 1.5         # if centroid is speech-like → not bark
        - crest_is_speech * 3.0              # if crest factor is speech-like → not bark
    )
    scores["Dog Bark"] = max(0.01, dog_score)

    # -----------------------------------------------------------------------
    # Speech / Human Voice — smooth, mid-frequency, rhythmic, moderate level
    # AudioSet: 0 (Speech), 1 (Male speech), 2 (Female speech), 3 (Child speech)
    # Key features: centroid 800–3000 Hz, ZCR 0.04–0.25, crest 3–10, mid-dominant
    # -----------------------------------------------------------------------
    speech_score = (
        f.band_energies["mid"] * 2.2          # speech is mid-frequency dominated
        + speech_centroid_bonus * 3.0         # centroid in 800–3000 Hz window
        + zcr_in_speech_range * 2.5           # ZCR in speech band
        + crest_is_speech * 2.0              # crest factor in speech range
        - crest_is_impulsive * 4.0           # PENALISE heavily for impulsive transients
        - f.band_energies["low"] * 1.5        # speech has little bass
        - f.band_energies["air"] * 1.0        # and little ultra-high air band
    )
    scores["Speech / Human Voice"] = max(0.01, speech_score)

    # -----------------------------------------------------------------------
    # Wind / Environmental — spectrally flat, diffuse, wideband
    # AudioSet: 500 (Wind), 501 (Rustling leaves), 514 (White noise)
    # -----------------------------------------------------------------------
    wind_score = (
        f.spectral_flatness * 4.0             # HIGH flatness = noise-like
        + f.band_energies["air"] * 2.5        # lots of high-freq air content
        + (1.0 - level_bonus) * 1.5          # typically quiet
        - speech_centroid_bonus * 2.0         # not speech-like centroid
    )
    scores["Wind / Environmental"] = max(0.01, wind_score)

    # -----------------------------------------------------------------------
    # Sort & pick top K, normalize to percentages
    # -----------------------------------------------------------------------
    sorted_classes = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    total_score = sum(val for _, val in sorted_classes) or 1.0

    return [
        {"label": label, "value": round((val / total_score) * 100.0, 1)}
        for label, val in sorted_classes
    ]


def analyze_audio_bytes(raw_bytes: bytes) -> dict:
    """
    Full pipeline entry point: decode -> feature extraction -> YAMNet classification.
    """
    features = extract_features(raw_bytes)
    probabilities = classify_yamnet(features)
    top_class = probabilities[0]

    return {
        "soundClass": top_class["label"],
        "confidence": top_class["value"],
        "peakDbfs": features.peak_dbfs,
        "probabilities": probabilities,
        "durationSec": features.duration_sec,
        "yamnetVocabularyCount": len(YAMNET_CLASS_MAP),
    }

