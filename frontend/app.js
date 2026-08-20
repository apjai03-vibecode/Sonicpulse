/* ==========================================================================
   SonicPulse :: app.js
   Ingestion (mic + file), Web Audio waveform, API calls to the FastAPI
   backend (/record-audio, /upload-audio) with a graceful local-simulation
   fallback when the backend is unreachable, and diagnostic UI rendering.

   Expected backend response shape (see backend/main.py):
   {
     "soundClass": "Jackhammer / Drilling",
     "confidence": 94.2,
     "peakDbfs": -8.4,
     "stressIndex": 82,
     "stressState": "SEVERE",
     "probabilities": [ { "label": "Jackhammer", "value": 94.2 }, ... ],
     "incident": { id, name, zone, lat, lng, soundClass, confidence,
                    peakDbfs, stressIndex, stressState, timestamp }
   }
   ========================================================================== */

(function () {
  "use strict";

  const API_BASE = "http://localhost:8000";

  const SOUND_CLASSES = [
    { label: "Siren / Alarm", multiplier: 1.6 },
    { label: "Jackhammer / Drilling", multiplier: 1.5 },
    { label: "Car Horn / Traffic", multiplier: 1.3 },
    { label: "Bus / Diesel Engine", multiplier: 1.25 },
    { label: "Dog Bark", multiplier: 1.1 },
    { label: "Ambient / Speech", multiplier: 0.5 },
    { label: "Nature / Wind", multiplier: 0.2 },
  ];

  const CHENNAI_ZONES = [
    { name: "T. Nagar Commercial Core", zone: "commercial", lat: 13.0418, lng: 80.2341 },
    { name: "Guindy Industrial Estate", zone: "industrial", lat: 13.0067, lng: 80.2206 },
    { name: "Adyar Residential Block", zone: "residential", lat: 13.0012, lng: 80.2565 },
    { name: "Anna Nagar Hospital Zone", zone: "hospital", lat: 13.0850, lng: 80.2101 },
    { name: "Koyambedu Transit Corridor", zone: "transit", lat: 13.0694, lng: 80.1948 },
  ];

  let mode = "mic";
  let mediaStream = null;
  let mediaRecorder = null;
  let recordedChunks = [];
  let audioCtx = null;
  let analyser = null;
  let animationId = null;
  let isRecording = false;
  let recordStartTime = 0;
  let classChart = null;

  let userLiveGps = null; // { lat, lng, placeName }
  let selectedUploadLocation = null; // { lat, lng, placeName }

  // ---------------------------------------------------------------------
  // Geolocation & Location Picker
  // ---------------------------------------------------------------------
  function updateGpsPill(text, isError = false) {
    const el = document.getElementById("sp-gps-text");
    if (el) {
      el.textContent = text;
      el.parentElement.className = `w-full text-center font-mono text-[0.68rem] py-1 px-2.5 rounded-lg border flex items-center justify-center gap-1.5 ${
        isError
          ? "border-rose-800/50 bg-rose-950/50 text-rose-300"
          : "border-slate-700/50 bg-slate-900/60 text-cyan-400"
      }`;
    }
  }

  function acquireUserGps() {
    if (!navigator.geolocation) {
      updateGpsPill("GPS: Geolocation API not supported by browser", true);
      return;
    }
    updateGpsPill("GPS: Requesting coordinates from device...");
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        let placeName = `GPS (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
        if (window.SonicMap && window.SonicMap.reverseGeocodeClient) {
          placeName = await window.SonicMap.reverseGeocodeClient(lat, lng);
        }
        userLiveGps = { lat, lng, placeName };
        updateGpsPill(`GPS Active: ${placeName} (${lat.toFixed(3)}, ${lng.toFixed(3)})`);
      },
      (err) => {
        console.warn("SonicPulse: Geolocation error", err);
        updateGpsPill("GPS: Permission denied / Location unavailable (Default Chennai Grid)", true);
      },
      { enableHighAccuracy: true, timeout: 8000 }
    );
  }

  function wireLocationPickerControls() {
    const gpsBtn = document.getElementById("sp-loc-gps-btn");
    const mapBtn = document.getElementById("sp-loc-map-btn");
    const locText = document.getElementById("sp-file-location-text");

    if (gpsBtn) {
      gpsBtn.addEventListener("click", () => {
        if (!navigator.geolocation) {
          alert("Browser Geolocation is not supported.");
          return;
        }
        locText.textContent = "Location: Requesting GPS...";
        navigator.geolocation.getCurrentPosition(
          async (pos) => {
            const lat = pos.coords.latitude;
            const lng = pos.coords.longitude;
            let placeName = `GPS (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
            if (window.SonicMap && window.SonicMap.reverseGeocodeClient) {
              placeName = await window.SonicMap.reverseGeocodeClient(lat, lng);
            }
            selectedUploadLocation = { lat, lng, placeName };
            locText.textContent = `Location: ${placeName} (${lat.toFixed(3)}, ${lng.toFixed(3)})`;
          },
          (err) => {
            alert("Could not get current location: " + err.message);
            locText.textContent = "Location: Default (Chennai Core)";
          }
        );
      });
    }

    if (mapBtn) {
      mapBtn.addEventListener("click", () => {
        locText.textContent = "Location: CLICK ANYWHERE ON MAP TO PICK PIN...";
        if (window.SonicMap && window.SonicMap.enablePickMode) {
          window.SonicMap.enablePickMode(({ lat, lng, placeName }) => {
            selectedUploadLocation = { lat, lng, placeName };
            locText.textContent = `Location: ${placeName} (${lat.toFixed(3)}, ${lng.toFixed(3)})`;
            window.SonicMap.disablePickMode();
          });
        }
      });
    }

    const searchBtn = document.getElementById("sp-loc-search-btn");
    const searchInput = document.getElementById("sp-loc-input");

    async function performAreaSearch() {
      const query = searchInput ? searchInput.value.trim() : "";
      if (!query) return;
      locText.textContent = `Location: Searching '${query}'...`;
      try {
        const searchQuery = query.toLowerCase().includes("chennai") || query.toLowerCase().includes("india") ? query : `${query}, Chennai`;
        const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(searchQuery)}&limit=1`;
        const res = await fetch(url, { headers: { "User-Agent": "SonicPulse/1.0" } });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const results = await res.json();
        if (results && results.length > 0) {
          const lat = parseFloat(results[0].lat);
          const lng = parseFloat(results[0].lon);
          const placeName = query;
          selectedUploadLocation = { lat, lng, placeName };
          locText.textContent = `Location: ${placeName} (${lat.toFixed(3)}, ${lng.toFixed(3)})`;
          if (window.SonicMap && window.SonicMap.setTempPin) {
            window.SonicMap.setTempPin(lat, lng, placeName);
          }
        } else {
          locText.textContent = `Location: '${query}' not found. Using area name (${query}).`;
          selectedUploadLocation = { lat: 13.0339, lng: 80.2212, placeName: query };
        }
      } catch (err) {
        console.warn("Area search error", err);
        selectedUploadLocation = { lat: 13.0339, lng: 80.2212, placeName: query };
        locText.textContent = `Location: ${query} (Area set)`;
      }
    }

    if (searchBtn) searchBtn.addEventListener("click", performAreaSearch);
    if (searchInput) {
      searchInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          performAreaSearch();
        }
      });
    }
  }

  // ---------------------------------------------------------------------
  // Clock
  // ---------------------------------------------------------------------
  function tickClock() {
    const el = document.getElementById("sp-clock");
    if (el) {
      el.textContent = new Date().toLocaleTimeString("en-IN", { hour12: false });
    }
  }
  setInterval(tickClock, 1000);

  // ---------------------------------------------------------------------
  // Mode switcher
  // ---------------------------------------------------------------------
  function setMode(next) {
    mode = next;
    const micBtn = document.getElementById("sp-mode-mic");
    const fileBtn = document.getElementById("sp-mode-file");
    const micPanel = document.getElementById("sp-mic-panel");
    const filePanel = document.getElementById("sp-file-panel");

    if (next === "mic") {
      micBtn.classList.add("active");
      fileBtn.classList.remove("active");
      micPanel.classList.remove("hidden");
      micPanel.classList.add("flex");
      filePanel.classList.add("hidden");
      filePanel.classList.remove("flex");
      if (!userLiveGps) acquireUserGps();
    } else {
      fileBtn.classList.add("active");
      micBtn.classList.remove("active");
      filePanel.classList.remove("hidden");
      filePanel.classList.add("flex");
      micPanel.classList.add("hidden");
      micPanel.classList.remove("flex");
      stopRecording();
    }
  }

  // ---------------------------------------------------------------------
  // Waveform / spectrum visualizer
  // ---------------------------------------------------------------------
  function drawIdleWaveform() {
    const canvas = document.getElementById("sp-waveform-canvas");
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.strokeStyle = "rgba(0, 229, 255, 0.25)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    ctx.moveTo(0, h / 2);
    ctx.lineTo(w, h / 2);
    ctx.stroke();
  }

  function drawSpectrum() {
    const canvas = document.getElementById("sp-waveform-canvas");
    if (!canvas || !analyser) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function render() {
      animationId = requestAnimationFrame(render);
      analyser.getByteFrequencyData(dataArray);

      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);

      const barCount = 64;
      const step = Math.floor(bufferLength / barCount);
      const barWidth = w / barCount;

      for (let i = 0; i < barCount; i++) {
        const value = dataArray[i * step] || 0;
        const pct = value / 255;
        const barHeight = pct * h * 0.9;
        const hue = 190 - pct * 130;
        ctx.fillStyle = `hsla(${hue}, 95%, 60%, 0.85)`;
        ctx.shadowColor = `hsla(${hue}, 95%, 60%, 0.6)`;
        ctx.shadowBlur = 6;
        ctx.fillRect(i * barWidth + 1, h - barHeight, barWidth - 2, barHeight);
      }
    }
    render();
  }

  function computeRms(dataArray) {
    let sumSquares = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const norm = (dataArray[i] - 128) / 128;
      sumSquares += norm * norm;
    }
    return Math.sqrt(sumSquares / dataArray.length);
  }

  let micAudioProcessor = null;
  let micRawSamples = [];

  function encodeWavMono(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    function writeString(v, offset, str) {
      for (let i = 0; i < str.length; i++) {
        v.setUint8(offset + i, str.charCodeAt(i));
      }
    }

    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(view, 36, 'data');
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }

    return new Blob([view], { type: 'audio/wav' });
  }

  function computeRmsFromSamples(samples) {
    if (!samples || samples.length === 0) return 0.1;
    let sumSquares = 0;
    for (let i = 0; i < samples.length; i++) {
      sumSquares += samples[i] * samples[i];
    }
    return Math.sqrt(sumSquares / samples.length);
  }

  // ---------------------------------------------------------------------
  // Recording
  // ---------------------------------------------------------------------
  async function startRecording() {
    try {
      if (!userLiveGps) acquireUserGps();
    } catch (_) {}

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setBanner("severe", "MIC RECORDING UNSUPPORTED — MUST OPEN VIA HTTP://LOCALHOST");
      alert("Microphone recording requires a secure context. Please open http://localhost:5500 in your browser.");
      return;
    }

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      console.error("SonicPulse: mic access denied", err);
      setBanner("severe", "MICROPHONE ACCESS DENIED — ALLOW PERMISSION IN BROWSER");
      alert("Microphone access was denied. Please allow microphone permissions in your browser bar.");
      return;
    }

    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      const source = audioCtx.createMediaStreamSource(mediaStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;

      micRawSamples = [];
      micAudioProcessor = audioCtx.createScriptProcessor(4096, 1, 1);
      micAudioProcessor.onaudioprocess = (e) => {
        if (!isRecording) return;
        const inputData = e.inputBuffer.getChannelData(0);
        micRawSamples.push(new Float32Array(inputData));
      };

      source.connect(analyser);
      source.connect(micAudioProcessor);
      micAudioProcessor.connect(audioCtx.destination);

      isRecording = true;
      recordStartTime = performance.now();
      const recBtn = document.getElementById("sp-record-btn");
      if (recBtn) recBtn.classList.add("recording");
      const recState = document.getElementById("sp-record-state");
      if (recState) recState.textContent = "RECORDING…";
      setBanner("idle", "LISTENING TO LIVE ACOUSTIC STREAM…");
      drawSpectrum();
      tickTimer();
    } catch (err) {
      console.error("SonicPulse: mic init error", err);
      setBanner("severe", `RECORDER ERROR: ${err.message || "FAILED TO INITIALIZE"}`);
    }
  }

  function tickTimer() {
    if (!isRecording) return;
    const elapsed = (performance.now() - recordStartTime) / 1000;
    const mins = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const secs = (elapsed % 60).toFixed(1).padStart(4, "0");
    const el = document.getElementById("sp-record-timer");
    if (el) el.textContent = `${mins}:${secs}`;
    requestAnimationFrame(tickTimer);
  }

  function stopRecording() {
    if (!isRecording) return;
    isRecording = false;

    if (micAudioProcessor) {
      try { micAudioProcessor.disconnect(); } catch (_) {}
      micAudioProcessor = null;
    }
    if (mediaStream) mediaStream.getTracks().forEach((t) => t.stop());
    if (animationId) cancelAnimationFrame(animationId);

    const recBtn = document.getElementById("sp-record-btn");
    if (recBtn) recBtn.classList.remove("recording");
    const recState = document.getElementById("sp-record-state");
    if (recState) recState.textContent = "STANDBY";
    drawIdleWaveform();

    // Flatten mic raw samples into 16kHz PCM WAV
    let totalLength = 0;
    for (let i = 0; i < micRawSamples.length; i++) {
      totalLength += micRawSamples[i].length;
    }
    const mergedSamples = new Float32Array(totalLength);
    let offset = 0;
    for (let i = 0; i < micRawSamples.length; i++) {
      mergedSamples.set(micRawSamples[i], offset);
      offset += micRawSamples[i].length;
    }

    const wavBlob = encodeWavMono(mergedSamples, audioCtx ? audioCtx.sampleRate : 16000);
    wavBlob.name = "mic_clip.wav";

    const approxRms = computeRmsFromSamples(mergedSamples);
    analyzeAudio(wavBlob, "record-audio", approxRms, userLiveGps);

    if (audioCtx) {
      try { audioCtx.close(); } catch (_) {}
    }
  }

  // ---------------------------------------------------------------------
  // File ingestion
  // ---------------------------------------------------------------------
  function handleFile(file) {
    if (!file) return;
    document.getElementById("sp-file-name").textContent = `SELECTED: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    document.getElementById("sp-file-name").classList.remove("hidden");
    analyzeAudio(file, "upload-audio", null, selectedUploadLocation);
  }

  function wireDropzone() {
    const dz = document.getElementById("sp-dropzone");
    const input = document.getElementById("sp-file-input");
    dz.addEventListener("click", () => input.click());
    input.addEventListener("change", (e) => handleFile(e.target.files[0]));

    ["dragenter", "dragover"].forEach((evt) =>
      dz.addEventListener(evt, (e) => {
        e.preventDefault();
        dz.classList.add("drag-over");
      })
    );
    ["dragleave", "drop"].forEach((evt) =>
      dz.addEventListener(evt, (e) => {
        e.preventDefault();
        dz.classList.remove("drag-over");
      })
    );
    dz.addEventListener("drop", (e) => {
      const file = e.dataTransfer.files[0];
      handleFile(file);
    });
  }

  // ---------------------------------------------------------------------
  // API Call with Real YAMNet Classification & Coordinates
  // ---------------------------------------------------------------------
  async function analyzeAudio(blob, endpoint, approxRms, locationObj) {
    setBanner("idle", "RUNNING YAMNET ACOUSTIC INFERENCE & GEOLOCATION...");
    try {
      const formData = new FormData();
      formData.append("file", blob, blob.name || "clip.webm");
      if (locationObj && locationObj.lat && locationObj.lng) {
        formData.append("lat", locationObj.lat);
        formData.append("lng", locationObj.lng);
      }
      if (locationObj && locationObj.placeName) {
        formData.append("location_name", locationObj.placeName);
      }
      const res = await fetch(`${API_BASE}/${endpoint}`, { method: "POST", body: formData });
      if (!res.ok) {
        let errDetail = `HTTP ${res.status}`;
        try {
          const errData = await res.json();
          if (errData.detail) errDetail = errData.detail;
        } catch (_) {}
        throw new Error(errDetail);
      }
      const data = await res.json();
      renderResult(data);
    } catch (err) {
      console.warn("SonicPulse: backend error", err);
      setBanner("severe", `ANALYSIS NOTICE: ${err.message || "BACKEND UNREACHABLE — START SERVER.PY"}`);
    }
  }

  // ---------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------
  function toCssState(stressState) {
    return String(stressState || "CALM").toLowerCase();
  }

  function setBanner(cssState, text) {
    const banner = document.getElementById("sp-banner");
    const textEl = document.getElementById("sp-banner-text");
    banner.className = `sp-banner sp-banner-${cssState}`;
    textEl.textContent = text;
  }

  function renderResult(data) {
    const cssState = toCssState(data.stressState);
    const prefix = cssState === "critical" || cssState === "severe" ? "HIGH-STRESS: " : "YAMNET DETECTED: ";
    setBanner(cssState, `${prefix}${data.soundClass.toUpperCase()}`);

    document.getElementById("sp-dbfs").textContent = `${data.peakDbfs.toFixed(1)} dB`;

    const confBar = document.getElementById("sp-confidence-bar");
    const confVal = document.getElementById("sp-confidence-val");
    confBar.style.width = `${data.confidence}%`;
    confVal.textContent = `${data.confidence.toFixed(1)}%`;

    updateDial(data.stressIndex, cssState);
    updateClassChart(data.probabilities);

    if (data.incident && window.SonicMap) {
      window.SonicMap.addEvent(data.incident);
    }
  }

  function updateDial(score, cssState) {
    const circle = document.getElementById("sp-dial-value");
    const circumference = 452.4;
    const offset = circumference - (Math.min(100, score) / 100) * circumference;
    circle.style.strokeDashoffset = offset;
    const colorMap = {
      calm: "#22c55e",
      moderate: "#eab308",
      severe: "#ef4444",
      critical: "#c026d3",
    };
    circle.style.stroke = colorMap[cssState] || colorMap.calm;
    document.getElementById("sp-dial-score").textContent = score.toFixed(1);
    document.getElementById("sp-dial-score").style.color = colorMap[cssState] || colorMap.calm;
  }

  function updateClassChart(probabilities) {
    const ctx = document.getElementById("sp-class-chart").getContext("2d");
    const labels = probabilities.map((c) => c.label);
    const values = probabilities.map((c) => c.value);
    const colors = ["#00e5ff", "#7b8afe", "#c026d3"];

    if (classChart) {
      classChart.data.labels = labels;
      classChart.data.datasets[0].data = values;
      classChart.update();
      return;
    }

    classChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data: values,
            backgroundColor: colors,
            borderRadius: 6,
            barThickness: 18,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            min: 0,
            max: 100,
            grid: { color: "rgba(123,138,158,0.12)" },
            ticks: { color: "#7b8a9e", font: { family: "JetBrains Mono", size: 10 } },
          },
          y: {
            grid: { display: false },
            ticks: { color: "#e6edf5", font: { family: "Inter", size: 11 } },
          },
        },
      },
    });
  }

  // ---------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    tickClock();
    drawIdleWaveform();
    wireDropzone();
    wireLocationPickerControls();
    acquireUserGps();

    document.getElementById("sp-mode-mic").addEventListener("click", () => setMode("mic"));
    document.getElementById("sp-mode-file").addEventListener("click", () => setMode("file"));

    document.getElementById("sp-record-btn").addEventListener("click", () => {
      if (isRecording) {
        stopRecording();
      } else {
        startRecording();
      }
    });

    window.addEventListener("resize", () => {
      if (!isRecording) drawIdleWaveform();
    });
  });
})();

