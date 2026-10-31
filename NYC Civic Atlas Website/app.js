const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];

const API_BASE = new URLSearchParams(location.search).get("api")
  || window.MAMDANI_API_BASE
  || "http://127.0.0.1:8000/api/v1";
const PARK_ACREAGE_INDICATOR = "public_parks.acreage_per_1000";
const MAP_CENTER = [40.715, -73.94];
const MAP_ZOOM = 10.15;
const SCORE_COLORS = ["#bd2635", "#d94b3d", "#ee8741", "#f5c943", "#c3cc54", "#3973c7"];

let map;
let mapReady = false;
let featureLayerRef;
let atlasGeojson;
let activeDistrictId = null;
let labelsVisible = true;
let selectedPhoto = null;
let selectedPosition = null;
let toastTimer;
const geographies = new Map();
const scores = new Map();
const districtLayers = new Map();

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3000);
}

async function request(path, options) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (response.ok) return response.status === 204 ? null : response.json();
  let detail = `Request failed (${response.status}).`;
  try {
    detail = (await response.json()).detail || detail;
  } catch {
    // Preserve the HTTP status if an intermediary did not return JSON.
  }
  throw new Error(detail);
}

function colorFor(value) {
  if (value?.status !== "ok" || typeof value.score !== "number") return "#b7bfcb";
  return SCORE_COLORS[Math.min(SCORE_COLORS.length - 1, Math.floor(value.score / 100 * SCORE_COLORS.length))];
}

function districtCode(geoId) {
  return geoId.replace("cd:", "");
}

function mapStyle(feature) {
  const geoId = feature.properties.geo_id;
  const score = scores.get(geoId);
  const selected = activeDistrictId === geoId;
  const dimmed = Boolean(feature.properties.searchDim);
  return {
    color: selected ? "#ffe04a" : "#ffffff",
    weight: selected ? 4 : 1.5,
    opacity: dimmed ? 0.18 : 0.95,
    fillColor: selected ? "#ffe04a" : colorFor(score),
    fillOpacity: dimmed ? 0.06 : selected ? 0.55 : 0.48,
  };
}

function featureLayer() {
  districtLayers.clear();
  return L.geoJSON(atlasGeojson, {
    style: mapStyle,
    onEachFeature(feature, layer) {
      const geoId = feature.properties.geo_id;
      districtLayers.set(geoId, layer);
      const geography = geographies.get(geoId);
      if (labelsVisible) bindDistrictLabel(layer, geoId);
      layer.on("mouseover", () => {
        $("#selectionName").textContent = geography
          ? `${geography.name} · ${geography.borough}`
          : `CD ${districtCode(geoId)}`;
        if (activeDistrictId !== geoId) layer.setStyle({ fillOpacity: 0.65, weight: 2.5 });
      });
      layer.on("mouseout", () => {
        layer.setStyle(mapStyle(feature));
        if (!activeDistrictId) $("#selectionName").textContent = "Select a district";
      });
      layer.on("click", event => selectDistrict(geoId, event.latlng));
    },
  });
}

function bindDistrictLabel(layer, geoId) {
  layer.bindTooltip(`CD ${districtCode(geoId)}`, {
    permanent: true,
    direction: "center",
    className: "district-map-label",
  });
}

function refreshLayerStyles() {
  for (const layer of districtLayers.values()) layer.setStyle(mapStyle(layer.feature));
}

function syncLabels() {
  for (const [geoId, layer] of districtLayers) {
    if (labelsVisible && !layer.getTooltip()) bindDistrictLabel(layer, geoId);
    if (!labelsVisible) layer.unbindTooltip();
  }
}

function makeMap() {
  if (typeof L === "undefined") {
    showToast("The map library did not load. Check your internet connection, then refresh.");
    return;
  }
  map = L.map("nycMap", {
    center: MAP_CENTER,
    zoom: MAP_ZOOM,
    zoomControl: false,
    minZoom: 9,
    maxZoom: 18,
    maxBounds: [[40.40, -74.38], [41.04, -73.54]],
    maxBoundsViscosity: 0.6,
    scrollWheelZoom: true,
  });
  let tileErrorNotified = false;
  L.tileLayer(
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "Tiles © Esri, Maxar, Earthstar Geographics, and the GIS User Community" },
  ).on("tileerror", () => {
    if (!tileErrorNotified) {
      tileErrorNotified = true;
      showToast("Satellite imagery did not load. Check your internet connection.");
    }
  }).addTo(map);
  map.whenReady(() => {
    mapReady = true;
    setTimeout(() => map.invalidateSize(), 120);
  });
}

function scoreLabel(score) {
  return score?.status === "ok" && typeof score.score === "number"
    ? `${Math.round(score.score)}/100`
    : "Unavailable";
}

function rawValueLabel(score) {
  return typeof score?.raw_value === "number"
    ? `${score.raw_value.toFixed(2)} acres per 1,000 residents`
    : "Unavailable";
}

function renderMapList() {
  const list = $("#mapList");
  list.replaceChildren();
  for (const geography of [...geographies.values()].sort((a, b) => a.name.localeCompare(b.name))) {
    const score = scores.get(geography.geo_id);
    const button = document.createElement("button");
    if (activeDistrictId === geography.geo_id) button.classList.add("selected");
    const title = document.createElement("b");
    title.textContent = geography.name;
    button.append(title, document.createTextNode(`${geography.borough} · ${scoreLabel(score)}`));
    button.addEventListener("click", () => {
      selectDistrict(geography.geo_id);
      $("#viewToggle").click();
    });
    list.append(button);
  }
}

async function selectDistrict(geoId, center) {
  const geography = geographies.get(geoId);
  if (!geography) return;
  activeDistrictId = geoId;
  refreshLayerStyles();
  renderMapList();
  if (map && mapReady) {
    if (center) map.flyTo([center.lat, center.lng], Math.max(map.getZoom(), 11.4), { duration: 0.7 });
    else {
      const bounds = districtLayers.get(geoId)?.getBounds();
      if (bounds) map.flyTo(bounds.getCenter(), Math.max(map.getZoom(), 11.4), { duration: 0.7 });
    }
  }
  $("#selectionName").textContent = `${geography.name} · CD ${districtCode(geoId)}`;
  $("#districtInsight .district-placeholder").hidden = true;
  const detail = $("#districtInsight .district-details");
  const score = scores.get(geoId);
  detail.hidden = false;
  detail.innerHTML = `
    <div class="district-score">${score?.status === "ok" ? Math.round(score.score) : "—"}<span style="font-size:11px"> /100</span></div>
    <div><span class="section-kicker">${geography.borough.toUpperCase()} · COMMUNITY DISTRICT ${districtCode(geoId)}</span><h4>${geography.name}</h4><p id="districtNarrative">${rawValueLabel(score)} · ${score?.reference_period || "Reference period unavailable"}</p></div>
    <div class="district-metric"><b>${rawValueLabel(score)}</b><span>public park acreage measure</span></div>
    <div class="district-metric"><b>${score?.coverage === 1 ? "Available" : "Unavailable"}</b><span>measure coverage</span></div>
    <button class="icon-button" id="clearDistrict" title="Clear selected district" aria-label="Clear selected district">×</button>`;
  $("#clearDistrict").addEventListener("click", clearDistrict);
  await addInsightNarrative(geoId);
}

async function addInsightNarrative(geoId) {
  try {
    const insight = await request(
      `/geographies/${encodeURIComponent(geoId)}/insight?node_type=indicator&node_id=${PARK_ACREAGE_INDICATOR}`,
    );
    if (activeDistrictId !== geoId) return;
    const narrative = $("#districtNarrative");
    if (narrative) narrative.textContent = `${insight.headline}: ${insight.explanation}`;
  } catch {
    // Gemini interpretations are optional; the measured value remains useful without one.
  }
}

function clearDistrict() {
  activeDistrictId = null;
  refreshLayerStyles();
  renderMapList();
  $("#selectionName").textContent = "Select a district";
  $("#districtInsight .district-placeholder").hidden = false;
  $("#districtInsight .district-details").hidden = true;
}

async function loadAtlas() {
  try {
    const [geographyResponse, geometry, scoreResponse] = await Promise.all([
      request("/geographies?level=cd"),
      request("/geo/cd.geojson"),
      request(`/scores?level=cd&node_type=indicator&node_id=${PARK_ACREAGE_INDICATOR}`),
    ]);
    for (const item of geographyResponse.items) geographies.set(item.geo_id, item);
    for (const item of scoreResponse.values) scores.set(item.geo_id, item);
    if (!Array.isArray(geometry.features) || !geometry.features.length) {
      throw new Error("The local API has no community-district geometry. Run `nycp data sync`.");
    }
    atlasGeojson = geometry;
    if (featureLayerRef) map.removeLayer(featureLayerRef);
    featureLayerRef = featureLayer().addTo(map);
    map.fitBounds(featureLayerRef.getBounds(), { padding: [18, 18] });
    $("#mapSubtitle").innerHTML = `Parks &amp; green space <b>·</b> ${geographies.size} community districts`;
    renderMapList();
  } catch (error) {
    showToast(`${error.message} Start the local API and reload this page.`);
    $("#selectionName").textContent = "Local data unavailable";
  }
}

function openReport() {
  const drawer = $("#reportDrawer");
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  $("#drawerBackdrop").classList.add("open");
  document.body.style.overflow = "hidden";
  setTimeout(() => $("#reportText").focus(), 250);
}

function closeReport() {
  const drawer = $("#reportDrawer");
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  $("#drawerBackdrop").classList.remove("open");
  document.body.style.overflow = "";
}

function appendMessage(text, who = "user", imageUrl = null) {
  const thread = $("#chatThread");
  const message = document.createElement("div");
  message.className = `chat-message ${who === "user" ? "user-message" : "assistant-message"}`;
  if (who !== "user") {
    const avatar = document.createElement("span");
    avatar.className = "assistant-avatar";
    avatar.textContent = "✦";
    message.append(avatar);
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  bubble.append(paragraph);
  if (imageUrl) {
    const image = document.createElement("img");
    image.src = imageUrl;
    image.alt = "Photo attached to your report";
    image.style.cssText = "display:block;width:150px;max-height:120px;object-fit:cover;border-radius:6px;margin-top:8px";
    bubble.append(image);
  }
  const label = document.createElement("small");
  label.textContent = who === "user" ? "You · local submission" : "Report assistant";
  bubble.append(label);
  message.append(bubble);
  thread.append(message);
  thread.scrollTop = thread.scrollHeight;
  return message;
}

function setPhoto(file) {
  if (!file) return;
  if (!new Set(["image/jpeg", "image/png", "image/webp"]).has(file.type)) {
    showToast("Choose a JPEG, PNG, or WebP image.");
    return;
  }
  selectedPhoto = file;
  const reader = new FileReader();
  reader.onload = () => {
    $("#uploadImage").src = reader.result;
    $("#uploadName").textContent = file.name;
    $("#uploadPreview").hidden = false;
  };
  reader.readAsDataURL(file);
}

async function uploadPhoto(file) {
  const upload = await request("/uploads/presign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, content_type: file.type, size_bytes: file.size }),
  });
  const response = await fetch(upload.upload_url, {
    method: upload.method,
    headers: { "Content-Type": file.type },
    body: file,
  });
  if (!response.ok) throw new Error("The photo could not be saved locally.");
  return upload.key;
}

async function pollSubmission(pollUrl) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const response = await fetch(`${new URL(API_BASE).origin}${pollUrl}`);
    if (!response.ok) throw new Error("The submission status could not be read.");
    const body = await response.json();
    if (body.status !== "processing") return body;
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error("Classification is taking longer than expected. Check the local API log.");
}

function submissionMessage(result) {
  if (result.status === "failed") return result.error || "Classification could not be completed.";
  const classification = result.classification;
  if (!classification) return "The local service accepted the observation.";
  const parts = [classification.summary || "The observation was classified locally."];
  if (classification.domain) parts.push(`Topic: ${classification.domain.replaceAll("_", " ")}.`);
  if (classification.policy_note) parts.push(classification.policy_note);
  return parts.join(" ");
}

function bindPageEvents() {
  $$("[data-scroll]").forEach(button => button.addEventListener("click", () => {
    document.getElementById(button.dataset.scroll)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  $$("[data-open-report]").forEach(button => button.addEventListener("click", openReport));
  $("#reportFab").addEventListener("click", openReport);
  $("#closeDrawer").addEventListener("click", closeReport);
  $("#drawerBackdrop").addEventListener("click", closeReport);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeReport();
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      $("#search").focus();
    }
  });
  $$(".priority").forEach(button => button.addEventListener("click", () => {
    showToast("Public parks is the currently available local data slice.");
  }));
  $("#viewToggle").addEventListener("click", () => {
    const list = $("#mapList");
    const show = list.hidden;
    list.hidden = !show;
    $("#nycMap").style.visibility = show ? "hidden" : "visible";
    if (!show && map) map.invalidateSize();
    $$("#viewToggle span").forEach(span => {
      span.classList.toggle("toggle-active", (span.dataset.view === "list") === show);
    });
  });
  $("#labelsToggle").addEventListener("click", () => {
    labelsVisible = !labelsVisible;
    syncLabels();
  });
  $("#zoomIn").addEventListener("click", () => map?.zoomIn(1, { animate: true }));
  $("#zoomOut").addEventListener("click", () => map?.zoomOut(1, { animate: true }));
  $("#locate").addEventListener("click", () => {
    if (!navigator.geolocation) return showToast("Location is not available in this browser.");
    navigator.geolocation.getCurrentPosition(
      position => map?.flyTo([position.coords.latitude, position.coords.longitude], 13),
      () => showToast("Location permission was not granted."),
      { timeout: 7000 },
    );
  });
  $("#resetMap").addEventListener("click", () => {
    if (featureLayerRef) map?.fitBounds(featureLayerRef.getBounds(), { padding: [18, 18] });
    $("#search").value = "";
    for (const layer of districtLayers.values()) layer.feature.properties.searchDim = false;
    clearDistrict();
    showToast("Map view reset.");
  });
  $("#shareButton").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(location.href.split("#")[0]);
      showToast("Map link copied to clipboard.");
    } catch {
      showToast("Share this page using your browser address bar.");
    }
  });
  $$("[data-toast]").forEach(button => button.addEventListener("click", () => showToast(button.dataset.toast)));
  $("#search").addEventListener("input", event => {
    const query = event.target.value.trim().toLowerCase();
    for (const layer of districtLayers.values()) {
      const geography = geographies.get(layer.feature.properties.geo_id);
      const haystack = `${geography?.name || ""} ${geography?.borough || ""} ${districtCode(layer.feature.properties.geo_id)}`.toLowerCase();
      layer.feature.properties.searchDim = Boolean(query) && !haystack.includes(query);
    }
    refreshLayerStyles();
  });
  $(".mobile-menu").addEventListener("click", () => $("#explore").scrollIntoView({ behavior: "smooth" }));
  $(".avatar").addEventListener("click", () => showToast("No account is required for the local service."));
  $("#photoInput").addEventListener("change", event => setPhoto(event.target.files?.[0]));
  $("#removeUpload").addEventListener("click", () => {
    selectedPhoto = null;
    $("#photoInput").value = "";
    $("#uploadPreview").hidden = true;
  });
  $("#locationButton").addEventListener("click", () => {
    if (!navigator.geolocation) return showToast("Location is not available in this browser.");
    $("#locationButton").textContent = "Requesting…";
    navigator.geolocation.getCurrentPosition(
      position => {
        selectedPosition = { lat: position.coords.latitude, lng: position.coords.longitude };
        $("#locationButton").textContent = "Location added";
        showToast("Location added to this local submission.");
      },
      () => {
        $("#locationButton").textContent = "Add location";
        showToast("Location permission was not granted.");
      },
      { timeout: 7000 },
    );
  });
  $("#reportText").addEventListener("input", event => {
    $("#charCount").textContent = `${event.target.value.length} / 500`;
  });
  $$("[data-starter]").forEach(button => button.addEventListener("click", () => {
    $("#reportText").value = button.dataset.starter;
    $("#charCount").textContent = `${button.dataset.starter.length} / 500`;
    $("#reportText").focus();
  }));
  $("#chatForm").addEventListener("submit", submitReport);
}

async function submitReport(event) {
  event.preventDefault();
  const text = $("#reportText").value.trim();
  if (text.length < 3) return showToast("Add a description of at least three characters.");
  if (!selectedPosition) return showToast("Add a location before submitting the observation.");
  const photo = selectedPhoto;
  const imageUrl = photo ? $("#uploadImage").src : null;
  appendMessage(text, "user", imageUrl);
  $("#reportText").value = "";
  $("#charCount").textContent = "0 / 500";
  $("#uploadPreview").hidden = true;
  $("#photoInput").value = "";
  selectedPhoto = null;
  const waiting = appendMessage("Saving the observation and requesting local classification…", "assistant");
  try {
    const photoKeys = photo ? [await uploadPhoto(photo)] : [];
    const submitted = await request("/submissions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description: text,
        photo_keys: photoKeys,
        lat: selectedPosition.lat,
        lng: selectedPosition.lng,
        observed_at: new Date().toISOString(),
      }),
    });
    const result = await pollSubmission(submitted.poll_url);
    waiting.remove();
    appendMessage(submissionMessage(result), "assistant");
  } catch (error) {
    waiting.remove();
    appendMessage(`The observation could not be submitted: ${error.message}`, "assistant");
  }
}

makeMap();
bindPageEvents();
if (map) loadAtlas();
