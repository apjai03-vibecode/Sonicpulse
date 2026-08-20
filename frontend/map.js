/* ==========================================================================
   SonicPulse :: map.js
   Leaflet + CartoDB Dark Matter geospatial acoustic map.

   Incident schema (shared with backend and app.js):
   {
     id, name, zone, lat, lng,
     soundClass, confidence, peakDbfs,
     stressIndex, stressState, timestamp
   }

   Exposes window.SonicMap with addEvent() / setIncidents() for app.js.
   ========================================================================== */

(function () {
  "use strict";

  const CHENNAI_CENTER = [13.0400, 80.2350];
  const API_BASE = "http://localhost:8000";

  const STRESS_COLORS = {
    CALM: "#22c55e",
    MODERATE: "#eab308",
    SEVERE: "#ef4444",
    CRITICAL: "#c026d3",
  };

  function stressStateFromScore(score) {
    if (score >= 85) return "CRITICAL";
    if (score >= 65) return "SEVERE";
    if (score >= 35) return "MODERATE";
    return "CALM";
  }

  function stressColor(incident) {
    const state = incident.stressState || stressStateFromScore(incident.stressIndex);
    return STRESS_COLORS[state] || STRESS_COLORS.CALM;
  }

  const ZONE_META = {
    hospital: { icon: "🏥", label: "Hospital Zone" },
    residential: { icon: "🏘️", label: "Residential" },
    industrial: { icon: "🏭", label: "Industrial" },
    transit: { icon: "🚌", label: "Transit Corridor" },
    commercial: { icon: "🏬", label: "Commercial" },
  };

  let map, heatLayer, markerLayer, zoningLayer, pickMarkerLayer;
  let allIncidents = [];
  let activeZone = "all";
  let activeView = "heatmap";
  let isPickMode = false;
  let pickCallback = null;
  let activeTempPin = null;

  function initMap() {
    map = L.map("sp-map", {
      center: CHENNAI_CENTER,
      zoom: 12,
      zoomControl: true,
      attributionControl: true,
      preferCanvas: true,
    });

    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: "abcd",
      maxZoom: 19,
    }).addTo(map);

    markerLayer = L.layerGroup().addTo(map);
    pickMarkerLayer = L.layerGroup().addTo(map);
    heatLayer = L.heatLayer([], {
      radius: 32,
      blur: 28,
      maxZoom: 15,
      gradient: { 0.2: "#22c55e", 0.45: "#eab308", 0.7: "#ef4444", 1.0: "#c026d3" },
    });

    zoningLayer = L.layerGroup();

    map.on("click", onMapClick);

    setView("heatmap");
  }

  async function reverseGeocodeClient(lat, lng) {
    try {
      const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}`;
      const res = await fetch(url, { headers: { "User-Agent": "SonicPulse/1.0" } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const addr = data.address || {};
      const place = addr.road || addr.suburb || addr.neighbourhood || addr.city_district || addr.city || data.name;
      const city = addr.city || addr.town || addr.state || "";
      if (place && city && place !== city) return `${place}, ${city}`;
      if (place) return place;
      return `Site (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
    } catch (e) {
      return `Coordinates (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
    }
  }

  function enablePickMode(callback) {
    isPickMode = true;
    pickCallback = callback;
    const container = map.getContainer();
    container.style.cursor = "crosshair";
  }

  function disablePickMode() {
    isPickMode = false;
    pickCallback = null;
    const container = map.getContainer();
    container.style.cursor = "";
  }

  async function onMapClick(e) {
    if (!isPickMode) return;
    const lat = e.latlng.lat;
    const lng = e.latlng.lng;

    pickMarkerLayer.clearLayers();

    const pinIcon = L.divIcon({
      html: `<div style="color:#00e5ff; font-size:22px; filter:drop-shadow(0 0 6px rgba(0,229,255,0.8));">📍</div>`,
      className: "",
      iconSize: [24, 24],
      iconAnchor: [12, 24],
    });

    activeTempPin = L.marker([lat, lng], { icon: pinIcon })
      .bindPopup(`<div class="font-mono text-xs"><b style="color:#00e5ff;">Selected Location</b><br>Fetching place name...</div>`)
      .addTo(pickMarkerLayer)
      .openPopup();

    const placeName = await reverseGeocodeClient(lat, lng);
    activeTempPin.setPopupContent(`<div class="font-mono text-xs"><b style="color:#00e5ff;">Selected Location</b><br>${placeName}<br><span style="color:#7b8a9e;">${lat.toFixed(4)}, ${lng.toFixed(4)}</span></div>`);

    if (pickCallback) {
      pickCallback({ lat, lng, placeName });
    }
  }

  function setTempPin(lat, lng, placeName) {
    if (!map) return;
    pickMarkerLayer.clearLayers();

    const pinIcon = L.divIcon({
      html: `<div style="color:#00e5ff; font-size:24px; filter:drop-shadow(0 0 8px rgba(0,229,255,0.9));">📍</div>`,
      className: "",
      iconSize: [26, 26],
      iconAnchor: [13, 26],
    });

    activeTempPin = L.marker([lat, lng], { icon: pinIcon })
      .bindPopup(`<div class="font-mono text-xs"><b style="color:#00e5ff;">Specified Area</b><br>${placeName}<br><span style="color:#7b8a9e;">${lat.toFixed(4)}, ${lng.toFixed(4)}</span></div>`)
      .addTo(pickMarkerLayer)
      .openPopup();

    map.flyTo([lat, lng], 14, { duration: 1.0 });
  }

  function radarIcon(incident) {
    const color = stressColor(incident);
    const html = `
      <div class="sp-radar-marker" style="color:${color};">
        <div class="sp-radar-ring"></div>
        <div class="sp-radar-ring ring-2"></div>
        <div class="sp-radar-ring ring-3"></div>
        <div class="sp-radar-core" style="background:${color};"></div>
      </div>`;
    return L.divIcon({
      html,
      className: "",
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
  }

  function popupHtml(incident) {
    const state = incident.stressState || stressStateFromScore(incident.stressIndex);
    const color = stressColor(incident);
    const isBaseline = incident.isBaseline || incident.source === "Historical Baseline Sensor";
    const tagLabel = isBaseline
      ? `<span style="background:rgba(123,138,158,0.2); color:#94a3b8; padding:1px 4px; border-radius:4px; font-size:0.6rem;">BASELINE SENSOR</span>`
      : `<span style="background:rgba(16,185,129,0.2); color:#34d399; padding:1px 4px; border-radius:4px; font-size:0.6rem;">LIVE USER DETECTION</span>`;

    return `
      <div class="font-mono">
        <div style="font-weight:700; font-size:0.8rem; margin-bottom:2px;">${incident.name}</div>
        <div style="margin-bottom:6px;">${tagLabel}</div>
        <div style="color:#7b8a9e; font-size:0.68rem; margin-bottom:6px;">${ZONE_META[incident.zone] ? ZONE_META[incident.zone].label : incident.zone}</div>
        <div style="font-size:0.72rem; margin-bottom:2px;">Class: <span style="color:#00e5ff;">${incident.soundClass}</span></div>
        <div style="font-size:0.72rem; margin-bottom:2px;">Peak dBFS: ${incident.peakDbfs}</div>
        <div style="font-size:0.72rem;">Stress Index: <span style="color:${color}; font-weight:700;">${incident.stressIndex} (${state})</span></div>
      </div>`;
  }

  function renderZoningLayer() {
    zoningLayer.clearLayers();
    const zoneGroups = {};
    allIncidents.forEach((n) => {
      if (!zoneGroups[n.zone]) zoneGroups[n.zone] = [];
      zoneGroups[n.zone].push([n.lat, n.lng]);
    });
    Object.keys(zoneGroups).forEach((zone) => {
      const pts = zoneGroups[zone];
      const lats = pts.map((p) => p[0]);
      const lngs = pts.map((p) => p[1]);
      const centerLat = lats.reduce((a, b) => a + b, 0) / lats.length;
      const centerLng = lngs.reduce((a, b) => a + b, 0) / lngs.length;
      const radius = 900 + pts.length * 120;
      const zoneColor = {
        hospital: "#00e5ff",
        residential: "#22c55e",
        industrial: "#ef4444",
        transit: "#ffb020",
        commercial: "#c026d3",
      }[zone] || "#7b8a9e";
      L.circle([centerLat, centerLng], {
        radius,
        color: zoneColor,
        weight: 1.5,
        fillColor: zoneColor,
        fillOpacity: 0.06,
        dashArray: "4 6",
      }).bindTooltip(`${ZONE_META[zone] ? ZONE_META[zone].icon + " " + ZONE_META[zone].label : zone}`, { direction: "center", className: "font-mono" })
        .addTo(zoningLayer);
    });
  }

  function filteredIncidents() {
    if (activeZone === "all") return allIncidents;
    return allIncidents.filter((n) => n.zone === activeZone);
  }

  function refreshMarkers() {
    markerLayer.clearLayers();
    filteredIncidents().forEach((incident) => {
      L.marker([incident.lat, incident.lng], { icon: radarIcon(incident) })
        .bindPopup(popupHtml(incident))
        .addTo(markerLayer);
    });
  }

  function refreshHeat() {
    const points = filteredIncidents().map((n) => [n.lat, n.lng, Math.min(1, n.stressIndex / 100)]);
    heatLayer.setLatLngs(points);
  }

  function setView(view) {
    activeView = view;
    [markerLayer, heatLayer, zoningLayer].forEach((layer) => map.removeLayer(layer));

    if (view === "heatmap") {
      refreshHeat();
      heatLayer.addTo(map);
      refreshMarkers();
      markerLayer.addTo(map);
    } else if (view === "cluster") {
      refreshMarkers();
      markerLayer.addTo(map);
    } else if (view === "zoning") {
      renderZoningLayer();
      zoningLayer.addTo(map);
      refreshMarkers();
      markerLayer.addTo(map);
    }
  }

  function setZone(zone) {
    activeZone = zone;
    refreshMarkers();
    refreshHeat();
    if (activeView === "zoning") renderZoningLayer();
  }

  function updateNodeCount() {
    const el = document.getElementById("sp-node-count");
    if (el) el.textContent = String(allIncidents.length).padStart(2, "0");
  }

  function setIncidents(incidents) {
    allIncidents = incidents.slice().sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    updateNodeCount();
    refreshMarkers();
    refreshHeat();
    renderIncidentFeed();
  }

  function addEvent(incident) {
    allIncidents.unshift(incident);
    updateNodeCount();
    refreshMarkers();
    refreshHeat();
    map.flyTo([incident.lat, incident.lng], Math.max(map.getZoom(), 13), { duration: 1.1 });
    renderIncidentFeed();
  }

  function renderIncidentFeed() {
    const feed = document.getElementById("sp-incident-feed");
    if (!feed) return;
    const countEl = document.getElementById("sp-feed-count");
    if (countEl) countEl.textContent = `${allIncidents.length} EVENTS`;

    feed.innerHTML = allIncidents
      .slice(0, 25)
      .map((n) => {
        const state = (n.stressState || stressStateFromScore(n.stressIndex)).toLowerCase();
        const time = new Date(n.timestamp);
        const timeStr = isNaN(time.getTime())
          ? "--:--:--"
          : time.toLocaleTimeString("en-IN", { hour12: false });
        const isBaseline = n.isBaseline || n.source === "Historical Baseline Sensor";
        const tag = isBaseline ? `<span style="color:#64748b; font-size:0.6rem;">[BASELINE]</span>` : `<span style="color:#34d399; font-size:0.6rem;">[LIVE]</span>`;

        return `
          <div class="sp-feed-row">
            <span class="font-mono" style="color:var(--sp-muted);">${timeStr}</span>
            <span class="truncate">
              <span style="color:var(--sp-text); font-weight:600;">${n.soundClass}</span>
              <span style="color:var(--sp-muted);"> · ${n.name} ${tag}</span>
            </span>
            <span class="font-mono" style="color:var(--sp-muted); font-size:0.7rem;">${n.lat.toFixed(3)}, ${n.lng.toFixed(3)}</span>
            <span class="sp-badge sp-badge-${state}">${n.stressIndex.toFixed(1)}</span>
          </div>`;
      })
      .join("");
  }

  function wireControls() {
    document.querySelectorAll(".sp-view-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".sp-view-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        setView(btn.dataset.view);
      });
    });

    document.querySelectorAll(".sp-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        document.querySelectorAll(".sp-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        setZone(chip.dataset.zone);
      });
    });
  }

  async function loadIncidents() {
    try {
      const res = await fetch(`${API_BASE}/incidents`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setIncidents(data.incidents || []);
      return;
    } catch (err) {
      console.warn("SonicPulse: /incidents unreachable, loading local seed data.", err);
    }
    try {
      const res = await fetch("seed-hotspots.json");
      const data = await res.json();
      setIncidents(data.incidents || []);
    } catch (err) {
      console.error("SonicPulse: failed to load seed hotspots", err);
      setIncidents([]);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    initMap();
    wireControls();
    loadIncidents();
  });

  window.SonicMap = {
    addEvent,
    setIncidents,
    stressColor,
    stressStateFromScore,
    enablePickMode,
    disablePickMode,
    reverseGeocodeClient,
    setTempPin,
  };
})();

