const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const API_BASE = (window.MAMDANI_API_BASE || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
const API_ORIGIN = new URL(API_BASE).origin;
const NYC_BOUNDS = { south: 40.4774, north: 40.9176, west: -74.2591, east: -73.7004 };
const START_CENTER = [40.715, -73.94];
const START_ZOOM = 10.15;
const DOMAIN_ICONS = ['↗', '✳', '⌂', '◌', '⌂', '⌁', '✦'];
const DOMAIN_COLORS = ['blue', 'green', 'coral', 'violet'];
const COLORS = ['#c62938', '#e76b4d', '#f2ce43', '#82a8df', '#2860b7'];

let map;
let mapReady = false;
let taxonomy;
let geographies = [];
let geographyById = new Map();
let geometry = { type: 'FeatureCollection', features: [] };
let scoreByGeography = new Map();
let activeDomain = null;
let activeIndicator = null;
let activeDistrict = null;
let selectedPhoto = null;
let reportLocation = null;
let boundaryLayer = null;
let boroughLabelLayer = null;
let labelsVisible = true;
let toastTimer;
let districtRequest = 0;

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.detail || body.title || message;
    } catch { /* Preserve the HTTP message when the API did not return JSON. */ }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 3200);
}

function setApiStatus(state, label) {
  const status = $('#apiStatus');
  status.dataset.state = state;
  status.querySelector('.live-dot').classList.toggle('offline', state === 'offline');
  status.querySelector('.status-label').textContent = label;
}

function indicatorList(domain) {
  const unique = new Map();
  for (const subcategory of domain?.subcategories || []) {
    for (const indicator of subcategory.indicators || []) unique.set(indicator.id, indicator);
  }
  return [...unique.values()];
}

function renderPriorities() {
  const list = $('#priorityList');
  list.replaceChildren();
  for (const [index, domain] of (taxonomy?.domains || []).entries()) {
    const button = document.createElement('button');
    button.className = `priority${activeDomain?.slug === domain.slug ? ' active' : ''}`;
    button.dataset.domain = domain.slug;
    button.setAttribute('role', 'option');
    button.setAttribute('aria-selected', String(activeDomain?.slug === domain.slug));
    const subcategories = (domain.subcategories || []).map((item) => item.name).join(' · ');
    button.innerHTML = `<span class="priority-icon ${DOMAIN_COLORS[index % DOMAIN_COLORS.length]}">${DOMAIN_ICONS[index % DOMAIN_ICONS.length]}</span><span><b>${escapeHtml(domain.name)}</b><small>${escapeHtml(subcategories || 'No measures published yet')}</small></span><span class="priority-arrow">↗</span>`;
    button.addEventListener('click', () => chooseDomain(domain));
    list.append(button);
  }
}

async function chooseDomain(domain, preferredIndicator = null) {
  activeDomain = domain;
  const indicators = indicatorList(domain);
  activeIndicator = indicators.find((item) => item.id === preferredIndicator) || indicators[0] || null;
  renderPriorities();
  renderMeasureMenu(indicators);
  if (activeIndicator) await loadScores();
  else {
    scoreByGeography = new Map();
    drawBoundaries();
    updateMapCopy();
    renderMapList();
    $('#legendSource').textContent = 'No published measure';
    $('.measure-description').textContent = 'This priority is in the local platform taxonomy; its measures will appear when data is added.';
    if (activeDistrict) selectDistrict(activeDistrict.geo_id, false);
  }
}

function renderMeasureMenu(indicators) {
  const menu = $('#measureMenu');
  const selector = $('#measureSelect');
  menu.replaceChildren();
  const label = activeIndicator?.name || 'No measures published yet';
  $('#measureName').textContent = label;
  selector.disabled = indicators.length < 2;
  for (const indicator of indicators) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = indicator.name;
    button.addEventListener('click', async () => {
      activeIndicator = indicator;
      $('#measureName').textContent = indicator.name;
      menu.hidden = true;
      selector.setAttribute('aria-expanded', 'false');
      await loadScores();
    });
    menu.append(button);
  }
  const chosen = activeIndicator;
  $('.measure-description').textContent = chosen
    ? `${chosen.formula || chosen.name}. ${chosen.limitations || ''}`.trim()
    : 'This priority is in the local platform taxonomy; its measures will appear when data is added.';
  $('#measureBadge').textContent = activeIndicator ? 'LOCAL API DATA' : 'NO MEASURES YET';
}

async function loadScores() {
  if (!activeDomain || !activeIndicator) return;
  $('#measureName').textContent = activeIndicator.name;
  $('#legendSource').textContent = 'Loading local scores…';
  try {
    const result = await api(`/scores?level=cd&node_type=indicator&node_id=${encodeURIComponent(activeIndicator.id)}`);
    scoreByGeography = new Map((result.values || []).map((value) => [value.geo_id, value]));
    drawBoundaries();
    updateMapCopy();
    renderMapList();
    $('#legendSource').textContent = `${activeIndicator.unit || 'score'} · ${result.data_version || 'local API'}`;
    if (activeDistrict) selectDistrict(activeDistrict.geo_id, false);
  } catch (error) {
    scoreByGeography = new Map();
    drawBoundaries();
    renderMapList();
    $('#legendSource').textContent = 'Scores unavailable';
    showToast(`Could not load this measure: ${error.message}`);
  }
}

function featureGeoId(feature) {
  const properties = feature?.properties || {};
  const candidates = [properties.geo_id, properties.geoId, properties.GEO_ID, properties.GEOID, feature?.id];
  for (const candidate of candidates) {
    if (candidate == null) continue;
    const value = String(candidate).trim();
    if (geographyById.has(value)) return value;
    const digits = value.match(/\d{3}$/)?.[0];
    if (digits && geographyById.has(`cd:${Number(digits)}`)) return `cd:${Number(digits)}`;
  }
  const code = properties.BoroCD ?? properties.BoroCd ?? properties.boro_cd ?? properties.boroCD ?? properties.CD;
  if (code != null) {
    const value = `cd:${Number(String(code).replace(/\D/g, ''))}`;
    if (geographyById.has(value)) return value;
  }
  return null;
}

function scoreColor(value) {
  if (!value || value.score == null || value.status !== 'ok') return '#d8dee8';
  let score = value.score;
  if (activeIndicator?.direction === 'lower_better') score = 100 - score;
  const index = Math.min(COLORS.length - 1, Math.floor(Math.max(0, score) / 100 * COLORS.length));
  return COLORS[index];
}

function styleFeature(feature) {
  const properties = feature.properties || {};
  const score = scoreByGeography.get(properties.geo_id);
  const selected = activeDistrict?.geo_id === properties.geo_id;
  const query = $('#search').value.trim().toLowerCase();
  const geography = geographyById.get(properties.geo_id);
  const searchText = `${geography?.name || ''} ${geography?.borough || properties.borough || ''} ${properties.geo_id || ''}`.toLowerCase();
  const dimmed = query && !searchText.includes(query);
  return {
    color: selected ? '#ffe04a' : '#fff',
    weight: selected ? 3 : 1.6,
    opacity: dimmed ? 0.18 : 0.9,
    fillColor: scoreColor(score),
    fillOpacity: dimmed ? 0.08 : score?.score == null ? 0.18 : selected ? 0.74 : 0.62
  };
}

function drawBoundaries() {
  if (!map) return;
  if (boundaryLayer) map.removeLayer(boundaryLayer);
  const features = (geometry.features || []).map((feature) => {
    const geoId = featureGeoId(feature);
    const geography = geoId ? geographyById.get(geoId) : null;
    return {
      ...feature,
      properties: {
        ...(feature.properties || {}),
        geo_id: geoId || feature.properties?.geo_id || String(feature.id || ''),
        display_name: geography?.name || feature.properties?.name || feature.properties?.Name || 'Community district',
        borough: geography?.borough || feature.properties?.BoroName || feature.properties?.borough || ''
      }
    };
  });
  boundaryLayer = L.geoJSON({ type: 'FeatureCollection', features }, {
    style: styleFeature,
    onEachFeature: (feature, layer) => {
      const properties = feature.properties;
      const value = scoreByGeography.get(properties.geo_id);
      const label = value?.score == null ? 'Evidence unavailable' : `Score ${Math.round(value.score)} / 100`;
      layer.bindTooltip(`${properties.display_name} · ${label}`, { sticky: !labelsVisible, permanent: labelsVisible, direction: 'center', className: 'district-map-label' });
      layer.on('click', () => {
        if (!geographyById.has(properties.geo_id)) {
          showToast('This district boundary is loaded, but its local details are not available yet.');
          return;
        }
        selectDistrict(properties.geo_id, true, layer.getBounds().getCenter());
      });
    }
  }).addTo(map);
  updateMapNotice(features.length === 0);
  if (boroughLabelLayer) {
    if (labelsVisible) boroughLabelLayer.addTo(map);
    else map.removeLayer(boroughLabelLayer);
  }
}

function updateMapNotice(empty) {
  const notice = $('#mapDataNotice');
  notice.hidden = !empty;
  notice.textContent = empty
    ? 'Satellite imagery is live. District boundaries will appear here when the local platform receives NYC boundary data.'
    : '';
}

function createBoroughLabels() {
  const labels = [
    ['MANHATTAN', 40.77, -73.97], ['THE BRONX', 40.86, -73.88], ['QUEENS', 40.73, -73.79],
    ['BROOKLYN', 40.65, -73.95], ['STATEN ISLAND', 40.58, -74.15]
  ];
  boroughLabelLayer = L.layerGroup(labels.map(([name, lat, lng]) => L.marker([lat, lng], {
    interactive: false,
    icon: L.divIcon({ className: 'borough-map-label', html: name, iconSize: [110, 22], iconAnchor: [55, 11] })
  })));
}

function makeMap() {
  if (typeof L === 'undefined') {
    showToast('The map library did not load. Check your internet connection, then refresh.');
    return;
  }
  map = L.map('nycMap', {
    center: START_CENTER,
    zoom: START_ZOOM,
    zoomControl: false,
    minZoom: 9,
    maxZoom: 18,
    maxBounds: [[40.40, -74.38], [41.04, -73.54]],
    maxBoundsViscosity: 0.6,
    scrollWheelZoom: true
  });
  let tileErrorShown = false;
  L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    attribution: 'Tiles © Esri, Maxar, Earthstar Geographics, and the GIS User Community'
  }).on('tileerror', () => {
    if (!tileErrorShown) {
      tileErrorShown = true;
      showToast('Satellite imagery did not load. Check your internet connection.');
    }
  }).addTo(map);
  createBoroughLabels();
  boroughLabelLayer.addTo(map);
  drawBoundaries();
  map.whenReady(() => {
    mapReady = true;
    setTimeout(() => map.invalidateSize(), 120);
  });
}

function updateMapCopy() {
  const districtCount = geographies.length;
  $('#mapSubtitle').textContent = `${activeDomain?.name || 'NYC priorities'} · ${districtCount} local district records`;
  $('#introDistrictCount').textContent = String(districtCount);
  $('#districtHint').textContent = `${districtCount} districts with local records`;
}

function formatMeasure(value) {
  if (value == null || value === '') return 'Not available';
  if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return String(value);
}

function renderMapList() {
  const list = $('#mapList');
  list.replaceChildren();
  const query = $('#search').value.trim().toLowerCase();
  const visible = geographies.filter((geography) => `${geography.name} ${geography.borough || ''} ${geography.geo_id}`.toLowerCase().includes(query));
  if (!visible.length) {
    const empty = document.createElement('p');
    empty.className = 'map-list-empty';
    empty.textContent = geographies.length ? 'No districts match your search.' : 'No district records are available from the local API yet.';
    list.append(empty);
    return;
  }
  for (const geography of visible) {
    const value = scoreByGeography.get(geography.geo_id);
    const button = document.createElement('button');
    button.className = activeDistrict?.geo_id === geography.geo_id ? 'selected' : '';
    const scoreLabel = value?.score == null ? 'Evidence unavailable' : `Score ${Math.round(value.score)} / 100`;
    button.innerHTML = `<b>${escapeHtml(geography.name)}</b>${escapeHtml(geography.borough || 'NYC')} · ${escapeHtml(scoreLabel)}`;
    button.addEventListener('click', () => {
      selectDistrict(geography.geo_id, true);
      if ($('#mapList').hidden === false) $('#viewToggle').click();
    });
    list.append(button);
  }
}

function renderGroup(group) {
  const measures = (group?.measures || []).map((measure) => {
    const value = `${formatMeasure(measure.value)}${measure.unit ? ` ${measure.unit}` : ''}`;
    return `<div class="district-metric"><b>${escapeHtml(value)}</b><span>${escapeHtml(measure.label)}${measure.year ? ` · ${escapeHtml(measure.year)}` : ''}</span></div>`;
  }).join('');
  return measures;
}

async function selectDistrict(geoId, flyTo = false, center = null) {
  const geography = geographyById.get(geoId);
  if (!geography) return;
  activeDistrict = geography;
  const requestId = ++districtRequest;
  if (boundaryLayer) boundaryLayer.setStyle(styleFeature);
  if (flyTo && map && mapReady) {
    const destination = center || [START_CENTER[0], START_CENTER[1]];
    map.flyTo(destination, Math.max(map.getZoom(), 11.2), { duration: 0.65 });
  }
  $('#selectionName').textContent = `${geography.name}${geography.borough ? ` · ${geography.borough}` : ''}`;
  $('.district-placeholder').hidden = true;
  const details = $('.district-details');
  details.hidden = false;
  details.innerHTML = `<div class="district-score">${scoreByGeography.get(geoId)?.score == null ? '—' : Math.round(scoreByGeography.get(geoId).score)}<span style="font-size:11px"> /100</span></div><div><span class="section-kicker">${escapeHtml(geography.borough || 'NEW YORK CITY')} · ${escapeHtml(geography.geo_id)}</span><h4>${escapeHtml(geography.name)}</h4><p>${escapeHtml(activeIndicator?.name || 'No measure selected')}</p></div><div class="district-metric"><b>Loading…</b><span>Local context and infrastructure</span></div><button class="icon-button" id="clearDistrict" title="Clear selected district" aria-label="Clear selected district">×</button>`;
  $('#clearDistrict').addEventListener('click', clearDistrict);
  renderMapList();
  try {
    const [scoreTree, context, infrastructure] = await Promise.all([
      api(`/geographies/${encodeURIComponent(geoId)}/score-tree?domain=${encodeURIComponent(activeDomain?.slug || 'public_amenities_spaces')}`),
      api(`/geographies/${encodeURIComponent(geoId)}/context`),
      api(`/geographies/${encodeURIComponent(geoId)}/infrastructure`)
    ]);
    if (requestId !== districtRequest) return;
    const scoreValue = scoreByGeography.get(geoId);
    const contextHtml = renderGroup(context.groups?.[0]);
    const infrastructureHtml = renderGroup(infrastructure.groups?.[0]);
    const evidence = (scoreTree.root?.children || []).map((child) => {
      const value = child.score == null ? 'Evidence unavailable' : `${Math.round(child.score)} / 100`;
      const raw = child.raw_value == null ? '' : ` · ${formatMeasure(child.raw_value)} ${child.unit || ''}`;
      return `<div class="district-metric"><b>${escapeHtml(value)}</b><span>${escapeHtml(child.name)}${escapeHtml(raw)}</span></div>`;
    }).join('');
    const nameParts = [geography.borough, geography.geo_id].filter(Boolean).map(escapeHtml).join(' · ');
    const metrics = [contextHtml, infrastructureHtml, evidence].filter(Boolean).join('')
      || '<div class="district-metric"><b>Evidence unavailable</b><span>The API has no measures for this district yet.</span></div>';
    details.innerHTML = `<div class="district-score">${scoreValue?.score == null ? '—' : Math.round(scoreValue.score)}<span style="font-size:11px"> /100</span></div><div><span class="section-kicker">${nameParts}</span><h4>${escapeHtml(geography.name)}</h4><p>${escapeHtml(activeIndicator?.name || 'No measure selected')}</p></div>${metrics}<button class="icon-button" id="clearDistrict" title="Clear selected district" aria-label="Clear selected district">×</button>`;
    $('#clearDistrict').addEventListener('click', clearDistrict);
  } catch (error) {
    if (requestId !== districtRequest) return;
    details.innerHTML += `<p class="district-error">Local detail could not be loaded: ${escapeHtml(error.message)}</p>`;
  }
}

function clearDistrict() {
  activeDistrict = null;
  districtRequest++;
  if (boundaryLayer) boundaryLayer.setStyle(styleFeature);
  $('#selectionName').textContent = 'Select a district';
  $('.district-placeholder').hidden = false;
  $('.district-details').hidden = true;
  renderMapList();
}

function openReport() {
  const drawer = $('#reportDrawer');
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden', 'false');
  $('#drawerBackdrop').classList.add('open');
  document.body.style.overflow = 'hidden';
  setTimeout(() => $('#reportText').focus(), 250);
}

function closeReport() {
  const drawer = $('#reportDrawer');
  drawer.classList.remove('open');
  drawer.setAttribute('aria-hidden', 'true');
  $('#drawerBackdrop').classList.remove('open');
  document.body.style.overflow = '';
}

function appendMessage(text, who = 'user', imageUrl = null) {
  const thread = $('#chatThread');
  const message = document.createElement('div');
  message.className = `chat-message ${who === 'user' ? 'user-message' : 'assistant-message'}`;
  if (who !== 'user') {
    const avatar = document.createElement('span');
    avatar.className = 'assistant-avatar';
    avatar.textContent = '✦';
    message.append(avatar);
  }
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  const paragraph = document.createElement('p');
  paragraph.textContent = text;
  paragraph.style.whiteSpace = 'pre-line';
  bubble.append(paragraph);
  if (imageUrl) {
    const image = document.createElement('img');
    image.src = imageUrl;
    image.alt = 'Photo attached to your report';
    image.style.cssText = 'display:block;width:150px;max-height:120px;object-fit:cover;border-radius:6px;margin-top:8px';
    bubble.append(image);
  }
  const stamp = document.createElement('small');
  stamp.textContent = who === 'user' ? 'You · local report' : 'Local report assistant';
  bubble.append(stamp);
  message.append(bubble);
  thread.append(message);
  thread.scrollTop = thread.scrollHeight;
}

function appendClassification(result) {
  const classification = result.classification;
  if (result.status === 'failed') {
    appendMessage(`Report ${result.id} could not be classified. ${result.error || 'Check that the local platform is configured, then try again.'}` , 'assistant');
    return;
  }
  if (result.status === 'processing' || !classification) {
    appendMessage(`Your report was saved locally with reference ${result.id}. Classification is still processing; you can keep this reference for follow-up.`, 'assistant');
    return;
  }
  const topic = [classification.domain, classification.subcategory].filter(Boolean).join(' · ') || 'Civic observation';
  const summary = classification.summary || 'The local platform received your observation.';
  appendMessage(`${summary}\n\nSuggested topic: ${topic}${classification.severity ? `\nSeverity estimate: ${classification.severity} of 5` : ''}\nReference: ${result.id}`, 'assistant');
  if (classification.policy_note) {
    const note = document.createElement('div');
    note.className = 'reference-card';
    note.innerHTML = `<span class="reference-kicker">RELATED CITY COMMITMENT</span><p>${escapeHtml(classification.policy_note)}</p><small>This is a possible connection, not a verified violation.</small>`;
    $('#chatThread').lastElementChild?.querySelector('.bubble')?.append(note);
  } else {
    const note = document.createElement('div');
    note.className = 'reference-card';
    note.innerHTML = '<span class="reference-kicker">REFERENCE STATUS</span><p>No reviewed city commitment is linked to this report yet.</p><small>Your report remains a resident observation, not a verified finding.</small>';
    $('#chatThread').lastElementChild?.querySelector('.bubble')?.append(note);
  }
}

function pollUrl(path) {
  return /^https?:\/\//i.test(path) ? path : `${API_ORIGIN}${path.startsWith('/') ? '' : '/'}${path}`;
}

async function waitForSubmission(initial) {
  let current = initial;
  for (let attempt = 0; current.status === 'processing' && attempt < 18; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 1800));
    const response = await fetch(pollUrl(current.poll_url));
    if (!response.ok) throw new Error('The report was received, but its status could not be checked.');
    current = await response.json();
  }
  return current;
}

function contentTypeFor(file) {
  const known = { 'image/jpeg': 'image/jpeg', 'image/png': 'image/png', 'image/webp': 'image/webp' };
  if (known[file.type]) return known[file.type];
  const extension = file.name.split('.').pop().toLowerCase();
  return ({ jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp' })[extension] || null;
}

function setPhoto(file) {
  if (!file) return;
  const contentType = contentTypeFor(file);
  if (!contentType) {
    showToast('Choose a JPEG, PNG, or WebP image.');
    $('#photoInput').value = '';
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    showToast('Images must be 10 MB or smaller.');
    $('#photoInput').value = '';
    return;
  }
  selectedPhoto = file;
  $('#uploadImage').src = URL.createObjectURL(file);
  $('#uploadName').textContent = file.name;
  $('#uploadPreview').hidden = false;
}

function resetReportDraft() {
  selectedPhoto = null;
  $('#photoInput').value = '';
  $('#uploadPreview').hidden = true;
  $('#reportText').value = '';
  $('#charCount').textContent = '0 / 500';
}

async function submitReport(event) {
  event.preventDefault();
  const description = $('#reportText').value.trim();
  if (description.length < 3) {
    showToast('Add at least 3 characters describing what you noticed.');
    $('#reportText').focus();
    return;
  }
  if (!reportLocation) {
    showToast('Add your location before sending the report.');
    return;
  }
  const submit = $('.send-button');
  submit.disabled = true;
  submit.textContent = '…';
  try {
    const photoKeys = [];
    if (selectedPhoto) {
      const contentType = contentTypeFor(selectedPhoto);
      const presigned = await api('/uploads/presign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: selectedPhoto.name, content_type: contentType, size_bytes: selectedPhoto.size })
      });
      const uploaded = await fetch(presigned.upload_url, {
        method: 'PUT',
        headers: { 'Content-Type': contentType },
        body: selectedPhoto
      });
      if (!uploaded.ok) throw new Error(`Photo upload failed (${uploaded.status}).`);
      photoKeys.push(presigned.key);
    }
    const created = await api('/submissions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        photo_keys: photoKeys,
        description,
        lat: reportLocation.lat,
        lng: reportLocation.lng,
        observed_at: new Date().toISOString(),
        category_hint: activeDomain?.slug || null
      })
    });
    const imageUrl = selectedPhoto ? $('#uploadImage').src : null;
    appendMessage(description, 'user', imageUrl);
    resetReportDraft();
    appendMessage(`Report received. Reference ${created.id}. Checking its local status…`, 'assistant');
    try {
      const statusMessage = await waitForSubmission(created);
      $('#chatThread').lastElementChild?.remove();
      appendClassification(statusMessage);
    } catch {
      $('#chatThread').lastElementChild?.remove();
      appendMessage(`Report ${created.id} was saved locally, but its classification status could not be checked.`, 'assistant');
    }
    if (selectedPhoto) URL.revokeObjectURL($('#uploadImage').src);
  } catch (error) {
    showToast(`Report could not be sent: ${error.message}`);
  } finally {
    submit.disabled = false;
    submit.textContent = '↑';
  }
}

function addReportLocation() {
  const button = $('#locationButton');
  if (!navigator.geolocation) {
    showToast('Location is not available in this browser.');
    return;
  }
  button.textContent = 'Finding location…';
  navigator.geolocation.getCurrentPosition((position) => {
    const { latitude: lat, longitude: lng } = position.coords;
    if (lat < NYC_BOUNDS.south || lat > NYC_BOUNDS.north || lng < NYC_BOUNDS.west || lng > NYC_BOUNDS.east) {
      button.textContent = 'Add location';
      showToast('Reports currently need a location within New York City.');
      return;
    }
    reportLocation = { lat, lng };
    button.textContent = `Location added (${lat.toFixed(3)}, ${lng.toFixed(3)})`;
    showToast('NYC location added to your local report.');
  }, () => {
    button.textContent = 'Add location';
    showToast('Location permission was not granted.');
  }, { timeout: 10000, enableHighAccuracy: false });
}

function setupControls() {
  $$('[data-scroll]').forEach((button) => button.addEventListener('click', () => {
    document.getElementById(button.dataset.scroll)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  $$('[data-open-report]').forEach((button) => button.addEventListener('click', openReport));
  $('#reportFab').addEventListener('click', openReport);
  $('#closeDrawer').addEventListener('click', closeReport);
  $('#drawerBackdrop').addEventListener('click', closeReport);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeReport();
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      $('#search').focus();
    }
  });
  $$('.nav-link').forEach((button) => button.addEventListener('click', () => {
    $$('.nav-link').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
  }));
  $('#measureSelect').addEventListener('click', () => {
    if ($('#measureSelect').disabled) return;
    const menu = $('#measureMenu');
    menu.hidden = !menu.hidden;
    $('#measureSelect').setAttribute('aria-expanded', String(!menu.hidden));
  });
  $('#viewToggle').addEventListener('click', () => {
    const list = $('#mapList');
    const showList = list.hidden;
    list.hidden = !showList;
    $('#nycMap').style.visibility = showList ? 'hidden' : 'visible';
    $$('#viewToggle span').forEach((span) => span.classList.toggle('toggle-active', (span.dataset.view === 'list') === showList));
    if (!showList && map) setTimeout(() => map.invalidateSize(), 60);
  });
  $('#labelsToggle').addEventListener('click', () => {
    labelsVisible = !labelsVisible;
    $('#labelsToggle').classList.toggle('active', !labelsVisible);
    if (boroughLabelLayer && map) {
      if (labelsVisible) boroughLabelLayer.addTo(map);
      else map.removeLayer(boroughLabelLayer);
    }
    if (boundaryLayer) {
      boundaryLayer.eachLayer((layer) => {
        const feature = layer.feature;
        const value = scoreByGeography.get(feature.properties.geo_id);
        const label = value?.score == null ? 'Evidence unavailable' : `Score ${Math.round(value.score)} / 100`;
        layer.unbindTooltip();
        layer.bindTooltip(`${feature.properties.display_name} · ${label}`, { sticky: !labelsVisible, permanent: labelsVisible, direction: 'center', className: 'district-map-label' });
      });
    }
  });
  $('#zoomIn').addEventListener('click', () => map?.zoomIn(1, { animate: true }));
  $('#zoomOut').addEventListener('click', () => map?.zoomOut(1, { animate: true }));
  $('#locate').addEventListener('click', () => {
    if (!navigator.geolocation) return showToast('Location is not available in this browser.');
    navigator.geolocation.getCurrentPosition((position) => map?.flyTo([position.coords.latitude, position.coords.longitude], 13), () => showToast('Location permission was not granted.'), { timeout: 8000 });
  });
  $('#resetMap').addEventListener('click', () => {
    map?.flyTo(START_CENTER, START_ZOOM, { duration: 0.5 });
    clearDistrict();
    $('#search').value = '';
    if (boundaryLayer) boundaryLayer.setStyle(styleFeature);
    renderMapList();
    showToast('Map view reset.');
  });
  $('#shareButton').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(location.href.split('#')[0]);
      showToast('Map link copied to clipboard.');
    } catch { showToast('Share this page using your browser address bar.'); }
  });
  $$('[data-toast]').forEach((button) => button.addEventListener('click', () => showToast(button.dataset.toast)));
  $('#search').addEventListener('input', () => {
    if (boundaryLayer) boundaryLayer.setStyle(styleFeature);
    renderMapList();
  });
  $('.mobile-menu').addEventListener('click', () => {
    $('#explore').scrollIntoView({ behavior: 'smooth' });
    showToast('Explore the map or open User report.');
  });
  $('.avatar').addEventListener('click', () => showToast('Accounts are not part of this local preview.'));
  $('#photoInput').addEventListener('change', (event) => setPhoto(event.target.files?.[0]));
  $('#removeUpload').addEventListener('click', () => {
    selectedPhoto = null;
    $('#photoInput').value = '';
    $('#uploadPreview').hidden = true;
  });
  $('#locationButton').addEventListener('click', addReportLocation);
  $('#reportText').addEventListener('input', (event) => { $('#charCount').textContent = `${event.target.value.length} / 500`; });
  $$('[data-starter]').forEach((button) => button.addEventListener('click', () => {
    $('#reportText').value = button.dataset.starter;
    $('#charCount').textContent = `${button.dataset.starter.length} / 500`;
    $('#reportText').focus();
  }));
  $('#chatForm').addEventListener('submit', submitReport);
}

async function start() {
  setupControls();
  makeMap();
  setApiStatus('connecting', 'Connecting to local API');
  try {
    const health = await fetch(`${API_ORIGIN}/health`);
    if (!health.ok) throw new Error('Local API health check failed');
    const [taxonomyData, geographyData, geometryData] = await Promise.all([
      api('/taxonomy'), api('/geographies?level=cd'), api('/geo/cd.geojson')
    ]);
    taxonomy = taxonomyData;
    geographies = geographyData.items || [];
    geographyById = new Map(geographies.map((geography) => [geography.geo_id, geography]));
    geometry = geometryData?.type === 'FeatureCollection' ? geometryData : { type: 'FeatureCollection', features: [] };
    const domain = taxonomy.domains?.find((item) => item.slug === 'public_amenities_spaces') || taxonomy.domains?.[0];
    if (!domain) throw new Error('The API returned no priority taxonomy.');
    activeDomain = domain;
    const indicators = indicatorList(domain);
    const defaultIndicator = indicators.find((item) => item.id === 'public_parks.walk_access_10min') || indicators[0] || null;
    activeIndicator = defaultIndicator;
    renderPriorities();
    renderMeasureMenu(indicators);
    updateMapCopy();
    drawBoundaries();
    renderMapList();
    setApiStatus('online', 'Local API connected');
    $('#measureBadge').textContent = 'LOCAL DEMO DATA';
    if (defaultIndicator) await loadScores();
    else $('#legendSource').textContent = 'No published measure';
    if (geometry.features?.length) $('#mapContext').textContent = 'NYC COMMUNITY DISTRICTS · SATELLITE VIEW · LOCAL SCORES';
    $('#chatDate').textContent = 'LOCAL REPORTS';
  } catch (error) {
    setApiStatus('offline', 'Local API offline');
    taxonomy = { domains: [] };
    geographies = [];
    geographyById = new Map();
    geometry = { type: 'FeatureCollection', features: [] };
    scoreByGeography = new Map();
    updateMapNotice(true);
    $('#mapSubtitle').textContent = 'Start the local platform API to load district data';
    $('#introDistrictCount').textContent = '—';
    $('#districtHint').textContent = 'Waiting for local district data';
    $('#legendSource').textContent = 'API not connected';
    $('#measureBadge').textContent = 'API OFFLINE';
    $('#measureName').textContent = 'Waiting for local API';
    $('.measure-description').textContent = 'Start the local platform API to load priorities, measures, districts, and scores.';
    $('#priorityList').innerHTML = '<p class="api-empty-state">No priority data loaded. Start the local API and refresh this page.</p>';
    renderMapList();
    showToast(`Local API is offline: ${error.message}. Start it from the project folder, then refresh.`);
  }
}

start();
