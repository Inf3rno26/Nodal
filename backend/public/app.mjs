// NODAL frontend: MapLibre geographic view + Canvas graph-theory view, both driven by the same state (S).
const $ = (s, r = document) => r.querySelector(s);
const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
const api = async (path, opts) => {
  const r = await fetch('/api' + path, opts);
  if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail)); }
  return r.json();
};
const ek = (a, b) => (a < b ? a + '|' + b : b + '|' + a);
const f2 = (x, d = 2) => (x == null ? '—' : Number(x).toFixed(d));
const PAL = ['#00D4FF', '#FF5470', '#FFB84D', '#617CFF', '#32D69A', '#c084fc', '#f472b6', '#a3e635'];
const short = n => { const p = n.split(', '); return p.length > 1 ? p[p.length - 1] : n; };
const S = { st: [], by: {}, byName: {}, edges: [], adj: {}, lc: {}, intel: {}, rank: {}, sel: null, failed: new Set(), overlay: {}, onPick: null, timers: [], layerHooks: [], paintHooks: [], graphHooks: [], leaveHooks: [], sizeFn: null, clickHook: null, cut: new Set(), offLine: null, mode: 'geo', base: 'roadmap', wmode: 'km', mapReady: false, F: {}, rt: null, rtKey: '',
  layers: { lines: true, stations: true, interchange: true, names: true, route: true, alt: true, mst: true, crit: false, vuln: false, conn: false, proposed: false, terrain: false } };
const EMPTY = { type: 'FeatureCollection', features: [] };
const fc = f => ({ type: 'FeatureCollection', features: f });
const feat = (coords, props = {}) => ({ type: 'Feature', properties: props, geometry: { type: 'LineString', coordinates: coords } });
const hv = (a, b) => { const R = 6371.0088, r = Math.PI / 180, dl = (b[0] - a[0]) * r, dp = (b[1] - a[1]) * r; const h = Math.sin(dp / 2) ** 2 + Math.cos(a[1] * r) * Math.cos(b[1] * r) * Math.sin(dl / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(h)); };

// ---------------- boot ----------------
async function boot() {
  const net = await api('/network');
  S.st = net.stations; S.edges = net.edges; S.lc = net.line_colors; S.assume = net.assumptions; S.source = net.source;
  S.st.forEach(s => { S.by[s.id] = s; S.byName[s.name.toLowerCase()] = s.id; S.byName[short(s.name).toLowerCase()] = s.id; S.adj[s.id] = {}; });
  S.edges.forEach(e => { S.adj[e.u][e.v] = e; S.adj[e.v][e.u] = e; });
  const intel = await api('/intel'); intel.stations.forEach(r => S.intel[r.id] = r);
  S.bcRank = Object.values(S.intel).sort((a, b) => b.betweenness - a.betweenness).map(r => r.id);
  $('#stlist').innerHTML = S.st.map(s => `<option value="${s.name}">`).join('');
  S.F.lines = S.edges.map(e => feat(e.geometry, { c: '', k: ek(e.u, e.v), line: e.line }));
  S.F.st = S.st.map(s => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] }, properties: { id: s.id, name: short(s.name), c: '', r: 5, inter: s.lines.length > 1 ? 1 : 0, deg: Object.keys(S.adj[s.id]).length } }));
  const lat0 = S.st.reduce((a, s) => a + s.lat, 0) / S.st.length, lon0 = S.st.reduce((a, s) => a + s.lon, 0) / S.st.length;
  S.proj = s => [(s.lon - lon0) * 111.32 * Math.cos(lat0 * Math.PI / 180), -(s.lat - lat0) * 110.57];
  S.bounds = [[Math.min(...S.st.map(s => s.lon)), Math.min(...S.st.map(s => s.lat))], [Math.max(...S.st.map(s => s.lon)), Math.max(...S.st.map(s => s.lat))]];
  buildLegend(); initMap(); initGraph(); initUI();
  api('/failure/ranking').then(r => { r.forEach(x => S.rank[x.id] = x.connectivity_loss); paintMap(); }).catch(() => {});
  api('/proposed').then(p => { S.proposed = p; const cb = $('#ly-proposed'); if (cb) { cb.disabled = !p.available; cb.parentElement.classList.toggle('dis', !p.available); cb.parentElement.title = p.available ? '' : p.note; } if (S.mapReady) paintMap(); }).catch(() => {});
  go('cc');
}
const idOf = v => S.byName[(v || '').trim().toLowerCase()];
const stIn = (id, ph) => `<input id="${id}" list="stlist" placeholder="${ph}" autocomplete="off">`;
const lineChips = s => s.lines.map(l => `<span class="chip" style="background:${S.lc[l]};${l === 'Yellow' ? 'color:#222;text-shadow:none' : ''}">${l}</span>`).join('');
const baseColor = id => S.by[id].lines.length > 1 ? '#F1F5FC' : S.lc[S.by[id].lines[0]];
function buildLegend() { $('#legend').innerHTML = Object.entries(S.lc).map(([l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join('') + '<span><i style="background:#fff;border:1px solid #0b1220"></i>Interchange</span>'; }

// ---------------- shared styling (map + graph) ----------------
function nodeColor(id) {
  const o = S.overlay;
  if (o.nodes && o.nodes[id]) return o.nodes[id];
  if (S.failed.has(id)) return '#FF0000';
  if (id === S.sel) return '#00D4FF';
  return baseColor(id);
}
function edgeColor(e) {
  const o = S.overlay, k = ek(e.u, e.v);
  if (o.edges && o.edges[k]) return o.edges[k];
  if (S.failed.has(e.u) || S.failed.has(e.v) || S.cut.has(k) || S.offLine === e.line) return '#FF1A1A';
  if (S.sel && (e.u === S.sel || e.v === S.sel)) return '#00D4FF';
  return o.dim ? '#8892a6' : S.lc[e.line];
}
function paint() { paintMap(); drawGraph(); }
function setOverlay(o) { S.overlay = o || {}; paint(); const key = (S.overlay.route || []).join(); if (key !== S.rtKey) { S.rtKey = key; startRoute(S.overlay.route, S.overlay.fit !== false); } }
function pick(id) { if (S.onPick) S.onPick(id); else select(id); }
function select(id, fly) {
  S.sel = id; const s = S.by[id], i = S.intel[id], rank = S.bcRank.indexOf(id) + 1;
  const nb = Object.keys(S.adj[id]).map(n => { const e = S.adj[id][n]; return `<tr><td>${short(S.by[n].name)}</td><td>${e.line}</td><td>${f2(e.km)} km</td><td>${f2(e.min, 1)} min</td></tr>`; }).join('');
  $('#info').innerHTML = `<b style="font-size:14px">${s.name}</b><br>${lineChips(s)} ${s.lines.length > 1 ? '<span class="wn">Interchange</span>' : ''}<br>
  <span class="fm">${s.lat.toFixed(6)}, ${s.lon.toFixed(6)}</span> <span style="color:var(--tx2)">(BMRCL feed, OSM-derived)</span><br>
  <span class="ok">Operational</span> — in the current timetable feed${s.wheelchair === '1' ? ' · wheelchair accessible' : ''}
  <table><tr><th>Adjacent station</th><th>Line</th><th>Track</th><th>Time</th></tr>${nb}</table>
  <div class="note">degree ${i.degree} · C<sub>D</sub> ${f2(i.degree_centrality, 3)} · C<sub>B</sub> ${f2(i.betweenness, 3)} (rank ${rank}/${S.st.length}) · C<sub>C</sub> ${f2(i.closeness, 3)} · ${i.articulation ? '<span class="wn">articulation point</span>' : '<span class="ok">not an articulation point</span>'}${S.rank[id] != null ? ` · removal disconnects ${f2(100 * S.rank[id], 1)}% of station pairs` : ''}</div><div class="row"><button class="b" id="closeSt">⚠ Simulate closing this station</button></div>`;
  $('#closeSt').onclick = () => closeStation(id);
  if (fly && S.mapReady && S.mode !== 'graph') S.map.flyTo({ center: [s.lon, s.lat], zoom: Math.max(S.map.getZoom(), 14), pitch: 55, duration: RM ? 0 : 1600 });
  paint();
}

// ---------------- geometry helpers ----------------
function edgeGeom(a, b) { const e = S.adj[a] && S.adj[a][b]; if (!e) return [[S.by[a].lon, S.by[a].lat], [S.by[b].lon, S.by[b].lat]]; return e.u === a ? e.geometry : e.geometry.slice().reverse(); }
function routeCoords(ids) { const out = []; for (let i = 1; i < ids.length; i++) { const g = edgeGeom(ids[i - 1], ids[i]); out.push(...(out.length ? g.slice(1) : g)); } return out; }
function lineUpTo(coords, cum, d) { const out = [coords[0]]; for (let i = 1; i < coords.length; i++) { if (cum[i] <= d) out.push(coords[i]); else { const t = (d - cum[i - 1]) / ((cum[i] - cum[i - 1]) || 1); out.push([coords[i - 1][0] + t * (coords[i][0] - coords[i - 1][0]), coords[i - 1][1] + t * (coords[i][1] - coords[i - 1][1])]); break; } } return out; }
function posAt(coords, cum, d) { const l = lineUpTo(coords, cum, Math.max(0, Math.min(d, cum[cum.length - 1]))); return l[l.length - 1]; }

// ---------------- MAP ----------------
const GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';
function satStyle(labels) {
  return { version: 8, glyphs: GLYPHS, sources: { sat: { type: 'raster', tileSize: 256, maxzoom: 19, tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], attribution: 'Imagery © Esri, Maxar, Earthstar Geographics' },
    ...(labels ? { lab: { type: 'raster', tileSize: 256, tiles: ['a', 'b', 'c'].map(s => `https://${s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png`), attribution: 'Labels © OpenStreetMap contributors © CARTO' } } : {}) },
    layers: [{ id: 'sat', type: 'raster', source: 'sat' }, ...(labels ? [{ id: 'lab', type: 'raster', source: 'lab' }] : [])] };
}
const BASES = { roadmap: 'https://tiles.openfreemap.org/styles/liberty', light: 'https://tiles.openfreemap.org/styles/positron', satellite: () => satStyle(false), hybrid: () => satStyle(true) };
const LAY = { lines: ['lines-casing', 'lines'], stations: ['st'], interchange: ['st-inter', 'st-label-inter'], names: ['st-label'], route: ['route-casing', 'route', 'route-arrows', 'route-dots'], alt: ['alt'], mst: ['mst', 'mst-dash'], crit: ['halo-crit'], vuln: ['halo-vuln'], conn: ['st-deg'], proposed: ['proposed'] };
const LAYNAME = { lines: 'Metro lines (operational)', stations: 'Stations (operational)', interchange: 'Interchange stations', names: 'Station names', route: 'Shortest route', alt: 'Alternative routes', mst: 'Minimum spanning tree', crit: 'Critical stations', vuln: 'Network vulnerability', conn: 'Station connectivity (degree)', proposed: 'Proposed extensions', terrain: '3D terrain relief' };

function initMap() {
  const m = S.map = new maplibregl.Map({ container: 'map', style: BASES.roadmap, center: [77.5946, 12.9716], zoom: 11, pitch: 45, bearing: -12, maxPitch: 80, attributionControl: false });
  m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right');
  m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');
  m.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
  m.on('style.load', setupLayers);
  m.on('error', e => { const msg = e && e.error && e.error.message || ''; if (/Failed to fetch|NetworkError|tile|style|glyph/i.test(msg)) mapStatus(`Map data issue: ${msg.slice(0, 120)}. Check internet connection or switch basemap.`); });
  const pop = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
  m.on('mousemove', e => {
    if (!S.mapReady) return; const f = m.queryRenderedFeatures(e.point, { layers: ['st'] });
    m.getCanvas().style.cursor = f.length ? 'pointer' : ''; if (f.length) pop.setLngLat(f[0].geometry.coordinates).setHTML(f[0].properties.name).addTo(m); else pop.remove();
  });
  m.on('click', e => {
    if (!S.mapReady) return; if (S.clickHook && S.clickHook(e)) return; const f = m.queryRenderedFeatures(e.point, { layers: ['st'] });
    if (f.length) return pick(f[0].properties.id);
    const l = m.queryRenderedFeatures(e.point, { layers: ['lines'] })[0];
    if (l) { const ed = S.edges.find(x => ek(x.u, x.v) === l.properties.k); if (ed) new maplibregl.Popup({ offset: 6 }).setLngLat(e.lngLat).setHTML(`${short(S.by[ed.u].name)} – ${short(S.by[ed.v].name)}<br>${ed.line} Line · track ${f2(ed.km)} km · straight ${f2(ed.km_straight)} km · ${f2(ed.min, 1)} min<br><button class="b" onclick="cutEdge('${ed.u}','${ed.v}')">✂ Cut this connection</button>`).addTo(m); }
  });
  ['dragstart', 'wheel'].forEach(ev => m.on(ev, () => { if (S.fly) { clearInterval(S.fly); S.fly = null; } }));
}
function mapStatus(t) { let el = $('#mstat'); if (!el) { el = document.createElement('div'); el.id = 'mstat'; el.style.cssText = 'position:absolute;z-index:6;right:10px;top:10px;max-width:320px;background:#101827ee;border:1px solid var(--wn);color:var(--wn);padding:6px 10px;border-radius:6px;font-size:12px'; $('#stage').appendChild(el); } el.textContent = t; clearTimeout(el._t); el._t = setTimeout(() => el.remove(), 9000); }
function setBase(k) { S.base = k; S.mapReady = false; const st = BASES[k]; S.map.setStyle(typeof st === 'function' ? st() : st, { diff: false }); document.querySelectorAll('#bases button').forEach(b => b.classList.toggle('on', b.dataset.v === k)); }
function setupLayers() {
  const m = S.map, wz = (a, b) => ['interpolate', ['linear'], ['zoom'], 9, a, 15, b];
  m.addSource('dem', { type: 'raster-dem', tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'], encoding: 'terrarium', tileSize: 256, maxzoom: 13, attribution: 'Terrain: Mapzen / AWS Open Data' });
  ['proposed', 'lines', 'alt', 'mst', 'halo', 'route', 'rdots', 'st'].forEach(id => m.addSource(id, { type: 'geojson', data: EMPTY }));
  const L = (id, type, source, o) => m.addLayer({ id, type, source, ...o });
  const lc = { 'line-cap': 'round', 'line-join': 'round' };
  L('proposed', 'line', 'proposed', { layout: lc, paint: { 'line-color': '#ff8a3d', 'line-width': wz(2, 5), 'line-dasharray': [2, 2] } });
  L('lines-casing', 'line', 'lines', { layout: lc, paint: { 'line-color': '#0b1220', 'line-width': wz(5, 13), 'line-opacity': 0.8 } });
  L('lines', 'line', 'lines', { layout: lc, paint: { 'line-color': ['get', 'c'], 'line-width': wz(3, 8) } });
  L('alt', 'line', 'alt', { layout: lc, paint: { 'line-color': ['get', 'c'], 'line-width': wz(3, 6), 'line-dasharray': [2, 2], 'line-opacity': 0.8 } });
  L('mst', 'line', 'mst', { filter: ['==', ['get', 'd'], 0], layout: lc, paint: { 'line-color': ['get', 'c'], 'line-width': ['get', 'w'], 'line-opacity': ['get', 'o'] } });
  L('mst-dash', 'line', 'mst', { filter: ['==', ['get', 'd'], 1], layout: lc, paint: { 'line-color': ['get', 'c'], 'line-width': ['get', 'w'], 'line-opacity': ['get', 'o'], 'line-dasharray': [2, 2] } });
  L('halo-crit', 'circle', 'halo', { filter: ['==', ['get', 'kind'], 'crit'], paint: { 'circle-radius': ['get', 'r'], 'circle-color': '#ff5470', 'circle-opacity': 0.25, 'circle-stroke-color': '#ff5470', 'circle-stroke-width': 2, 'circle-pitch-alignment': 'map' } });
  L('halo-vuln', 'circle', 'halo', { filter: ['==', ['get', 'kind'], 'vuln'], paint: { 'circle-radius': ['get', 'r'], 'circle-color': ['get', 'c'], 'circle-opacity': 0.35, 'circle-stroke-color': ['get', 'c'], 'circle-stroke-width': 1.5, 'circle-pitch-alignment': 'map' } });
  L('halo-fail', 'circle', 'halo', { filter: ['==', ['get', 'kind'], 'fail'], paint: { 'circle-radius': ['get', 'r'], 'circle-color': '#FF0000', 'circle-opacity': 0.18, 'circle-stroke-color': '#FF0000', 'circle-stroke-width': 3, 'circle-pitch-alignment': 'map' } });
  L('halo-fail2', 'circle', 'halo', { filter: ['==', ['get', 'kind'], 'fail2'], paint: { 'circle-radius': ['get', 'r'], 'circle-color': '#FF0000', 'circle-opacity': 0.35, 'circle-stroke-color': '#FF4444', 'circle-stroke-width': 2.5, 'circle-pitch-alignment': 'map' } });
  L('halo-affected', 'circle', 'halo', { filter: ['==', ['get', 'kind'], 'affected'], paint: { 'circle-radius': ['get', 'r'], 'circle-color': '#FF8C00', 'circle-opacity': 0.28, 'circle-stroke-color': '#FFA500', 'circle-stroke-width': 2.5, 'circle-pitch-alignment': 'map' } });
  L('route-casing', 'line', 'route', { layout: lc, paint: { 'line-color': '#06222c', 'line-width': wz(8, 18) } });
  L('route', 'line', 'route', { layout: lc, paint: { 'line-color': '#00D4FF', 'line-width': wz(4, 10) } });
  L('route-arrows', 'symbol', 'route', { layout: { 'symbol-placement': 'line', 'symbol-spacing': 70, 'text-field': '>', 'text-font': ['Noto Sans Bold'], 'text-size': 16, 'text-keep-upright': false, 'text-allow-overlap': true, 'text-ignore-placement': true }, paint: { 'text-color': '#ffffff', 'text-halo-color': '#06222c', 'text-halo-width': 1.5 } });
  L('route-dots', 'circle', 'rdots', { paint: { 'circle-radius': ['get', 'r'], 'circle-color': '#ffffff', 'circle-stroke-color': '#00D4FF', 'circle-stroke-width': 3 } });
  L('st-inter', 'circle', 'st', { filter: ['==', ['get', 'inter'], 1], paint: { 'circle-radius': wz(9, 20), 'circle-color': '#ffffff', 'circle-stroke-color': '#0b1220', 'circle-stroke-width': 3 } });
  L('st', 'circle', 'st', { paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, ['*', ['get', 'r'], 0.5], 15, ['*', ['get', 'r'], 1.7]], 'circle-color': ['get', 'c'], 'circle-stroke-color': '#0b1220', 'circle-stroke-width': 1.5 } });
  L('st-deg', 'symbol', 'st', { minzoom: 11.5, layout: { 'text-field': ['to-string', ['get', 'deg']], 'text-font': ['Noto Sans Bold'], 'text-size': 11, 'text-allow-overlap': true }, paint: { 'text-color': '#ffffff', 'text-halo-color': '#0b1220', 'text-halo-width': 1.6 } });
  const lab = { 'text-field': ['get', 'name'], 'text-font': ['Noto Sans Bold'], 'text-anchor': 'top', 'text-offset': [0, 1.1], 'text-optional': true };
  const lp = { 'text-color': '#0b1220', 'text-halo-color': '#ffffff', 'text-halo-width': 1.8 };
  L('st-label', 'symbol', 'st', { minzoom: 12.2, filter: ['==', ['get', 'inter'], 0], layout: { ...lab, 'text-size': 11 }, paint: lp });
  L('st-label-inter', 'symbol', 'st', { minzoom: 9.5, filter: ['==', ['get', 'inter'], 1], layout: { ...lab, 'text-size': 13, 'text-offset': [0, 1.6] }, paint: lp });
  S.layerHooks.forEach(h => h(m));
  S.mapReady = true; applyVis(); paintMap();
}
function applyVis() {
  if (!S.mapReady) return; const m = S.map;
  Object.entries(LAY).forEach(([k, ids]) => ids.forEach(id => m.getLayer(id) && m.setLayoutProperty(id, 'visibility', S.layers[k] ? 'visible' : 'none')));
  m.setTerrain(S.layers.terrain ? { source: 'dem', exaggeration: 1.6 } : null);
}
const setSrc = (id, f) => { const s = S.map.getSource(id); if (s) s.setData(fc(f)); };
function paintMap() {
  if (!S.mapReady) return; const o = S.overlay;
  S.F.lines.forEach((f, i) => f.properties.c = edgeColor(S.edges[i]));
  S.F.st.forEach((f, i) => { const id = S.st[i].id; f.properties.c = nodeColor(id); f.properties.r = S.failed.has(id) ? 16 : id === S.sel ? Math.max(8, S.sizeFn ? S.sizeFn(id) : 0) : S.sizeFn ? S.sizeFn(id) : S.st[i].lines.length > 1 ? 6.5 : 5; });
  setSrc('lines', S.F.lines); setSrc('st', S.F.st);
  setSrc('mst', (o.extra || []).map(x => feat(edgeGeom(x.u, x.v), { c: x.c, w: x.w || 3, o: x.o ?? 1, d: x.d ? 1 : 0 })));
  setSrc('alt', (o.alt || []).map(a => feat(routeCoords(a.stations), { c: a.c })));
  const halos = [];
  S.bcRank.slice(0, 10).forEach(id => halos.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [S.by[id].lon, S.by[id].lat] }, properties: { kind: 'crit', r: 12 + 60 * S.intel[id].betweenness } }));
  const mx = Math.max(1e-9, ...Object.values(S.rank));
  S.st.forEach(s => { if (S.rank[s.id] != null) halos.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] }, properties: { kind: 'vuln', r: 6 + 34 * S.rank[s.id], c: `hsl(${55 - 55 * S.rank[s.id] / mx},95%,52%)` } }); });
  S.failed.forEach(id => { const st = S.by[id]; if (st) { halos.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [st.lon, st.lat] }, properties: { kind: 'fail', r: 38 } }); halos.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [st.lon, st.lat] }, properties: { kind: 'fail2', r: 22 } }); } });
  if (S._affectedSet && S._affectedSet.size) { S._affectedSet.forEach(id => { const st = S.by[id]; if (st && !S.failed.has(id)) halos.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [st.lon, st.lat] }, properties: { kind: 'affected', r: 20 } }); }); }
  setSrc('halo', halos);
  setSrc('proposed', S.proposed && S.proposed.available ? S.proposed.geojson.features : []);
  S.paintHooks.forEach(h => h());
}

// ---------------- route animation (map + graph share S.rt) ----------------
let rtTok = 0;
function startRoute(ids, fit = true) {
  rtTok++; const tok = rtTok;
  if (S.mapReady) { setSrc('route', []); setSrc('rdots', []); }
  if (!ids || ids.length < 2) { S.rt = null; drawGraph(); return; }
  const coords = routeCoords(ids), cum = [0];
  for (let i = 1; i < coords.length; i++) cum.push(cum[i - 1] + hv(coords[i - 1], coords[i]));
  S.rt = { ids, coords, cum, total: cum[cum.length - 1], p: RM ? 1 : 0 };
  if (fit && S.mapReady && S.mode !== 'graph') { const lo = [Math.min(...coords.map(c => c[0])), Math.min(...coords.map(c => c[1]))], hi = [Math.max(...coords.map(c => c[0])), Math.max(...coords.map(c => c[1]))]; S.map.fitBounds([lo, hi], { padding: 90, pitch: 50, duration: RM ? 0 : 1400, maxZoom: 15 }); }
  const t0 = performance.now(); let last = 0;
  (function step(now) {
    if (tok !== rtTok) return;
    if (now - last > 30) {
      last = now; const el = (now - t0) / 1000, p = RM ? 1 : Math.min(1, el / 3.2), R = S.rt; R.p = p;
      if (S.mapReady) {
        setSrc('route', [feat(lineUpTo(R.coords, R.cum, p * R.total), {})]);
        const dots = []; if (!RM) { if (p < 1) dots.push([...posAt(R.coords, R.cum, p * R.total), 9]); else for (let i = 0; i < 4; i++) dots.push([...posAt(R.coords, R.cum, ((el / 8 + i / 4) % 1) * R.total), 6]); }
        setSrc('rdots', dots.map(d => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [d[0], d[1]] }, properties: { r: d[2] } })));
      }
      S.rt.phase = el; drawGraph();
    }
    if (!document.hidden) requestAnimationFrame(step); else setTimeout(() => requestAnimationFrame(step), 500);
  })(t0);
}
function flyAlong() {
  const R = S.rt; if (!R || !S.mapReady) return; if (S.fly) clearInterval(S.fly); let i = 0; const N = 28;
  const go1 = () => { const d = (i / N) * R.total, a = posAt(R.coords, R.cum, d), b = posAt(R.coords, R.cum, Math.min(R.total, d + R.total / N)); const brg = Math.atan2(b[0] - a[0], b[1] - a[1]) * 180 / Math.PI; S.map.easeTo({ center: a, zoom: 14.2, pitch: 65, bearing: brg, duration: 1000, easing: t => t }); i++; if (i > N) { clearInterval(S.fly); S.fly = null; } };
  go1(); S.fly = setInterval(go1, 1000); S.timers.push(S.fly);
}

// ---------------- GRAPH THEORY VIEW (canvas) ----------------
const G = { on: false, T: { k: 1, x: 0, y: 0 }, hover: null, pos: {} };
function initGraph() {
  G.cv = $('#graph canvas'); G.ctx = G.cv.getContext('2d');
  S.st.forEach(s => G.pos[s.id] = S.proj(s));
  $('#gh').textContent = `Graph G = (V, E) · |V| = ${S.st.length}, |E| = ${S.edges.length} · same data as the map · edge weight = ${S.wmode === 'km' ? 'track km' : 'minutes'}`;
  let drag = null;
  G.cv.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, tx: G.T.x, ty: G.T.y, moved: false }; G.cv.setPointerCapture(e.pointerId); });
  G.cv.addEventListener('pointermove', e => {
    const r = G.cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    if (drag) { const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.hypot(dx, dy) > 3) drag.moved = true; if (drag.moved) { G.T.x = drag.tx + dx; G.T.y = drag.ty + dy; drawGraph(); return; } }
    const n = nearest(mx, my); if (n !== G.hover) { G.hover = n; drawGraph(); }
  });
  G.cv.addEventListener('pointerup', e => { if (drag && !drag.moved) { const r = G.cv.getBoundingClientRect(), n = nearest(e.clientX - r.left, e.clientY - r.top); if (n) pick(n); } drag = null; });
  G.cv.addEventListener('wheel', e => { e.preventDefault(); const r = G.cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, f = Math.exp(-e.deltaY * 0.0015); G.T.x = mx - (mx - G.T.x) * f; G.T.y = my - (my - G.T.y) * f; G.T.k *= f; drawGraph(); }, { passive: false });
}
function fitGraph() {
  const xs = Object.values(G.pos).map(p => p[0]), ys = Object.values(G.pos).map(p => p[1]), w = G.cv.clientWidth || 600, h = G.cv.clientHeight || 400, pad = 40;
  const k = Math.min((w - 2 * pad) / (Math.max(...xs) - Math.min(...xs)), (h - 2 * pad) / (Math.max(...ys) - Math.min(...ys)));
  G.T = { k, x: pad - Math.min(...xs) * k + ((w - 2 * pad) - (Math.max(...xs) - Math.min(...xs)) * k) / 2, y: pad - Math.min(...ys) * k + ((h - 2 * pad) - (Math.max(...ys) - Math.min(...ys)) * k) / 2 }; G.k0 = k;
}
const gp = id => [G.pos[id][0] * G.T.k + G.T.x, G.pos[id][1] * G.T.k + G.T.y];
function nearest(mx, my) { let best = null, bd = 14; S.st.forEach(s => { const p = gp(s.id), d = Math.hypot(p[0] - mx, p[1] - my); if (d < bd) { bd = d; best = s.id; } }); return best; }
function resizeGraph() { if (!G.cv) return; const r = G.cv.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2); if (!r.width) return; G.cv.width = r.width * dpr; G.cv.height = r.height * dpr; G.ctx.setTransform(dpr, 0, 0, dpr, 0, 0); G.w = r.width; G.h = r.height; if (!G.fitted) { fitGraph(); G.fitted = true; } drawGraph(); }
function drawGraph() {
  if (!G.on || !G.w) return; const c = G.ctx, o = S.overlay, zoomed = G.T.k > G.k0 * 1.8;
  c.clearRect(0, 0, G.w, G.h); c.fillStyle = '#0d1524'; c.fillRect(0, 0, G.w, G.h);
  c.lineCap = 'round'; c.font = '10px Inter, sans-serif'; c.textAlign = 'center';
  S.edges.forEach(e => { const a = gp(e.u), b = gp(e.v), hl = o.edges && o.edges[ek(e.u, e.v)]; c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.strokeStyle = edgeColor(e); c.globalAlpha = o.dim && !hl ? 0.5 : 1; c.lineWidth = hl ? 4 : 2.2; c.stroke(); c.globalAlpha = 1; if (zoomed || hl) { c.fillStyle = hl ? '#ffd9a0' : '#7d8aa3'; c.fillText(f2(e[S.wmode], 2), (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 4); } });
  (o.extra || []).forEach(x => { const a = gp(x.u), b = gp(x.v); c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.setLineDash(x.d ? [5, 4] : []); c.strokeStyle = x.c; c.globalAlpha = x.o ?? 1; c.lineWidth = (x.w || 3) * 0.9; c.stroke(); c.setLineDash([]); c.globalAlpha = 1; });
  (o.alt || []).forEach(al => { c.beginPath(); al.stations.forEach((id, i) => { const p = gp(id); i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1]); }); c.setLineDash([6, 5]); c.strokeStyle = al.c; c.lineWidth = 3; c.stroke(); c.setLineDash([]); });
  if (S.rt) { const ps = S.rt.ids.map(gp), seg = []; let tot = 0; for (let i = 1; i < ps.length; i++) { const d = Math.hypot(ps[i][0] - ps[i - 1][0], ps[i][1] - ps[i - 1][1]); seg.push(d); tot += d; }
    const upto = S.rt.p * tot; let acc = 0; c.beginPath(); c.moveTo(ps[0][0], ps[0][1]); let head = ps[0];
    for (let i = 1; i < ps.length; i++) { if (acc + seg[i - 1] <= upto) { c.lineTo(ps[i][0], ps[i][1]); head = ps[i]; acc += seg[i - 1]; } else { const t = (upto - acc) / (seg[i - 1] || 1); head = [ps[i - 1][0] + t * (ps[i][0] - ps[i - 1][0]), ps[i - 1][1] + t * (ps[i][1] - ps[i - 1][1])]; c.lineTo(head[0], head[1]); break; } }
    c.strokeStyle = '#00D4FF'; c.lineWidth = 5; c.stroke(); c.beginPath(); c.arc(head[0], head[1], 6, 0, 7); c.fillStyle = '#fff'; c.fill(); }
  const showAll = G.T.k > G.k0 * 3.5, lab = [];
  S.st.forEach(s => { const p = gp(s.id), deg = Object.keys(S.adj[s.id]).length, r = (S.sizeFn ? S.sizeFn(s.id) * 0.7 : 3.5 + (s.lines.length > 1 ? 3 : 0)) + (s.id === S.sel ? 2 : 0) + (S.failed.has(s.id) ? 5 : 0);
    if (S.failed.has(s.id)) { c.beginPath(); c.arc(p[0], p[1], r + 9, 0, 7); c.strokeStyle = '#FF0000'; c.lineWidth = 2.5; c.globalAlpha = 0.45; c.stroke(); c.globalAlpha = 1; }
    c.beginPath(); c.arc(p[0], p[1], r, 0, 7); c.fillStyle = nodeColor(s.id); c.fill(); c.strokeStyle = S.failed.has(s.id) ? '#FF0000' : '#0b1220'; c.lineWidth = S.failed.has(s.id) ? 2.5 : 1.2; c.stroke();
    if (showAll || s.id === S.sel || s.id === G.hover || s.lines.length > 1 || (o.nodes && o.nodes[s.id] && Object.keys(o.nodes).length < 30) || (S.rt && S.rt.ids.includes(s.id) && S.rt.ids.length < 14)) lab.push([s, p, r]); });
  S.failed.forEach(id => { if (!G.pos[id]) return; const p = gp(id), sz = 9; c.save(); c.strokeStyle = '#FF0000'; c.lineWidth = 3; c.globalAlpha = 1; c.lineCap = 'round'; c.beginPath(); c.moveTo(p[0]-sz, p[1]-sz); c.lineTo(p[0]+sz, p[1]+sz); c.stroke(); c.beginPath(); c.moveTo(p[0]+sz, p[1]-sz); c.lineTo(p[0]-sz, p[1]+sz); c.stroke(); c.restore(); });
  c.font = '11px Inter, sans-serif'; c.fillStyle = '#e6ecf7'; lab.forEach(([s, p, r]) => c.fillText(short(s.name), p[0], p[1] - r - 4));
  if (S.layers.conn) { c.font = 'bold 9px Inter'; c.fillStyle = '#fff'; S.st.forEach(s => { const p = gp(s.id); c.fillText(Object.keys(S.adj[s.id]).length, p[0], p[1] + 3); }); }
  S.graphHooks.forEach(h => h(c, gp));
}

// ---------------- UI wiring ----------------
function setMode(m) {
  S.mode = m; $('#stage').className = 'm-' + m; G.on = m !== 'geo'; document.querySelectorAll('#modes button').forEach(b => b.classList.toggle('on', b.dataset.v === m));
  requestAnimationFrame(() => { S.map.resize(); resizeGraph(); drawGraph(); });
}
function initUI() {
  const lb = $('#lb'); lb.innerHTML = Object.keys(LAYNAME).map(k => `<label><input type="checkbox" id="ly-${k}" ${S.layers[k] ? 'checked' : ''}> ${LAYNAME[k]}</label>`).join('');
  Object.keys(LAYNAME).forEach(k => $('#ly-' + k).onchange = e => { S.layers[k] = e.target.checked; applyVis(); drawGraph(); if (S.onLayer) S.onLayer(k, e.target.checked); });
  $('#lh').onclick = () => $('#layers').classList.toggle('c');
  document.querySelectorAll('nav [data-m]').forEach(b => b.onclick = () => go(b.dataset.m));
  $('#tog').onclick = () => { $('#nav').classList.toggle('c'); setTimeout(() => { S.map.resize(); resizeGraph(); }, 300); };
  $('#modes').onclick = e => e.target.dataset.v && setMode(e.target.dataset.v);
  $('#bases').onclick = e => e.target.dataset.v && setBase(e.target.dataset.v);
  $('#pitch').onclick = () => S.map.easeTo({ pitch: S.map.getPitch() > 10 ? 0 : 60, bearing: S.map.getPitch() > 10 ? 0 : -15, duration: RM ? 0 : 900 });
  $('#reset').onclick = () => { G.fitted = false; resizeGraph(); S.map.fitBounds(S.bounds, { padding: 60, pitch: 45, bearing: -12, duration: RM ? 0 : 1200 }); };
  $('#fs').onclick = () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => {});
  $('#q').onchange = e => { const id = idOf(e.target.value); if (id) { const st = S.by[id]; if (S.mode !== 'graph') S.map.flyTo({ center: [st.lon, st.lat], zoom: 14, pitch: 55, duration: RM ? 0 : 1400 }); pick(id); } else mapStatus('No station by that name — pick one from the list.'); };
  new ResizeObserver(() => { S.map.resize(); resizeGraph(); }).observe($('#stage'));
  setTimeout(() => S.map.fitBounds(S.bounds, { padding: 60, pitch: 45, bearing: -12, duration: 0 }), 0);
}

// ---------------- helpers for modules ----------------
const mod = html => { $('#mod').innerHTML = html; };
const clearTimers = () => { S.timers.forEach(clearInterval); S.timers = []; };
function chart(el, opt) {
  const c = echarts.init(el, null, { renderer: 'canvas' });
  c.setOption({ backgroundColor: 'transparent', textStyle: { color: '#9AA9BE' }, animationDuration: RM ? 0 : 500, tooltip: { trigger: 'axis', backgroundColor: '#172235', borderColor: '#243350', textStyle: { color: '#F1F5FC' } }, grid: { left: 52, right: 14, top: 36, bottom: 44 }, title: { textStyle: { color: '#F1F5FC', fontSize: 12 } }, ...opt });
  return c;
}
const axis = (name, extra = {}) => ({ name, nameLocation: 'middle', nameGap: 30, axisLine: { lineStyle: { color: '#243350' } }, splitLine: { lineStyle: { color: '#151f33' } }, ...extra });
const err = (el, e) => { el.innerHTML = `<div class="err">⚠ ${e.message}</div>`; };
function countUp(el, v, d = 0) { if (RM) { el.textContent = v.toFixed(d); return; } const t0 = performance.now(); (function s(t) { const k = Math.min(1, (t - t0) / 700); el.textContent = (v * k).toFixed(d); if (k < 1) requestAnimationFrame(s); })(t0); }
function go(m) {
  S.leaveHooks.forEach(h => h()); S.clickHook = null; S.cut.clear(); S.offLine = null; clearTimers(); S.onPick = null; S.onPickSearch = null; S.failed.clear(); S.wmode = 'km'; S.overlay = {}; S.rtKey = ''; startRoute(null);
  document.querySelectorAll('nav [data-m]').forEach(b => b.classList.toggle('on', b.dataset.m === m));
  paint(); MODS[m]();
}
const tbl = (rows, cols) => `<table><tr>${cols.map(c => `<th>${c[0]}</th>`).join('')}</tr>${rows.map(r => `<tr>${cols.map(c => `<td>${c[1](r)}</td>`).join('')}</tr>`).join('')}</table>`;
const MODS = {};

// ---------------- 1. Command Center ----------------
MODS.cc = async () => {
  setMode(S.mode === 'graph' ? 'graph' : 'geo');
  mod(`<h2>Command Center</h2><div id="g" class="grid"></div><div class="note">Network: operational Namma Metro Purple, Green and Yellow lines. Source: ${S.source.name} (${S.source.basis}). Feed valid ${S.source.feed_valid}. Distances are along the track alignment; times are timetable values modeled by the feed author.</div>
  <div id="c1" class="chart"></div><div id="c2" class="chart"></div><div id="c3" class="chart"></div><div id="health"></div>`);
  try {
    const m = await api('/metrics'), it = await api('/intel');
    const cards = [['Stations', m.stations, 0, 'Vertices |V| of the graph.'], ['Connections', m.connections, 0, 'Edges |E|: consecutive stations on a line.'], ['Lines', m.lines, 0, 'Operational lines in the feed.'], ['Components', m.components, 0, 'Connected components; 1 = every station reaches every other.'],
      ['Density', m.density, 4, '2|E| / (|V|(|V|−1)): fraction of possible edges present.'], ['Avg degree', m.avg_degree, 2, '2|E|/|V|. Near 2 means path-like.'], ['Interchanges', m.interchanges, 0, 'Stations served by more than one line.'], ['Articulation pts', m.articulation_points, 0, 'Stations whose removal increases the number of components.'], ['Track km', m.total_km, 1, 'Sum of edge lengths along the alignment.'], ['Avg path (hops)', m.avg_path_hops, 1, 'Mean unweighted shortest-path length.']];
    $('#g').innerHTML = cards.map(c => `<div class="stat" title="${c[3]}"><b data-v="${c[1]}" data-d="${c[2]}">0</b><span>${c[0]} ⓘ</span></div>`).join('');
    document.querySelectorAll('#g b').forEach(b => countUp(b, +b.dataset.v, +b.dataset.d));
    const dd = Object.entries(m.degree_distribution);
    chart($('#c1'), { title: { text: 'Degree distribution' }, xAxis: { type: 'category', data: dd.map(d => d[0]), ...axis('degree k') }, yAxis: { type: 'value', ...axis('stations (count)', { nameGap: 36 }) }, series: [{ type: 'bar', data: dd.map(d => d[1]), itemStyle: { color: '#00D4FF' } }] });
    const lp = Object.entries(m.stations_per_line);
    chart($('#c2'), { title: { text: 'Stations per line (interchanges counted on each)' }, xAxis: { type: 'category', data: lp.map(d => d[0]), ...axis('line') }, yAxis: { type: 'value', ...axis('stations (count)', { nameGap: 36 }) }, series: [{ type: 'bar', data: lp.map(d => ({ value: d[1], itemStyle: { color: S.lc[d[0]] } })) }] });
    const tb = it.top_betweenness.slice().reverse();
    chart($('#c3'), { title: { text: 'Top 10 critical stations by betweenness' }, grid: { left: 150, right: 20, top: 36, bottom: 40 }, xAxis: { type: 'value', ...axis('normalised betweenness C_B') }, yAxis: { type: 'category', data: tb.map(r => short(r.name)), axisLabel: { fontSize: 10 } }, series: [{ type: 'bar', data: tb.map(r => +r.betweenness.toFixed(4)), itemStyle: { color: '#617CFF' } }] });
    $('#health').innerHTML = `<h3>Network health</h3><div class="note">${m.is_tree ? '<span class="wn">The network is a tree (|E| = |V| − 1): exactly one route between any two stations, so there is <b>no redundancy</b>.</span>' : 'Network contains cycles.'} ${m.components === 1 ? 'Fully connected.' : ''} Open the Layers card on the map and enable “Critical stations” or “Network vulnerability”.</div>`;
  } catch (e) { err($('#health'), e); }
};

// ---------------- 2. Route Optimizer ----------------
MODS.route = () => {
  mod(`<h2>Route Optimizer</h2><label class="f">Origin</label>${stIn('o', 'Origin station')}<label class="f">Destination</label>${stIn('d', 'Destination station')}
  <label class="f">Objective</label><select id="obj"><option value="time">Fastest journey (time)</option><option value="distance">Shortest distance</option><option value="generalized">Minimum generalized cost</option><option value="transfers">Minimum transfers</option></select>
  <div class="row"><button class="b p" id="go">Optimize</button><button class="b" id="fly">▶ Fly along route</button></div><div class="note">Click stations on the map (or search) to fill origin, then destination.</div><div id="res"></div><div id="cmp"></div>`);
  let flip = 0; S.onPick = id => { $(flip ? '#d' : '#o').value = S.by[id].name; flip ^= 1; select(id); };
  $('#fly').onclick = flyAlong;
  $('#go').onclick = async () => {
    const o = idOf($('#o').value), d = idOf($('#d').value), res = $('#res');
    if (!o || !d) { res.innerHTML = '<div class="err">Choose valid origin and destination stations from the list.</div>'; return; }
    res.textContent = 'Computing…';
    try {
      const objn = $('#obj').value, all = await api(`/route/compare?src=${o}&dst=${d}`), r = all[objn];
      if (!r.reachable) { res.innerHTML = '<div class="err">No route exists.</div>'; return; }
      const nodes = {}; r.stations.forEach(s => nodes[s] = '#9fe9ff'); r.transfer_stations.forEach(s => nodes[s] = '#FFB84D'); nodes[o] = '#32D69A'; nodes[d] = '#FF5470';
      const alt = ['distance', 'time', 'generalized', 'transfers'].filter(k => k !== objn && all[k].reachable && all[k].stations.join() !== r.stations.join()).map((k, i) => ({ stations: all[k].stations, c: PAL[i + 2], k }));
      setOverlay({ nodes, route: r.stations, alt, dim: true });
      const why = { time: 'minimises timetable ride time plus 5 min per transfer', distance: 'minimises total track distance; transfers are free', generalized: 'minimises time + an 8 min-equivalent penalty per transfer', transfers: 'minimises transfers first (weight 10 000 each), then time' }[objn];
      res.innerHTML = `<h3>Result</h3>${tbl([['Origin', S.by[o].name], ['Destination', S.by[d].name], ['Distance', f2(r.distance_km) + ' km (track)'], ['Journey time', f2(r.time_min, 1) + ' min'], ['Transfers', r.transfers + (r.transfer_stations.length ? ' at ' + r.transfer_stations.map(s => short(S.by[s].name)).join(', ') : '')], ['Lines', r.lines_used.join(' → ')], ['Objective weight', f2(r.objective_value, 2)]], [['', x => x[0]], ['', x => x[1]]])}
      <h3>Station sequence (${r.stations.length})</h3><ol style="margin:0;padding-left:20px">${r.stations.map(s => `<li ${r.transfer_stations.includes(s) ? 'class="wn"' : ''}>${short(S.by[s].name)}${r.transfer_stations.includes(s) ? ' — interchange' : ''}</li>`).join('')}</ol>
      <div class="note">Why: this route ${why}. Weight = ${r.weight_explanation}. Dijkstra runs on a transfer-aware graph (one node per station and line). The route follows the real track alignment.</div>`;
      $('#cmp').innerHTML = `<h3>Objective comparison</h3>` + tbl(Object.values(all), [['Objective', x => x.objective], ['km', x => f2(x.distance_km)], ['min', x => f2(x.time_min, 1)], ['Transfers', x => x.transfers]]) + `<div class="note">${alt.length ? 'Dashed lines show routes from other objectives.' : 'All objectives give the same route: the network is a tree, so only one simple path exists between two stations. Alternatives appear only when a network has cycles.'}</div>`;
    } catch (e) { err(res, e); }
  };
};

// ---------------- 3. Algorithm Lab ----------------
MODS.algo = () => {
  setMode('split');
  mod(`<h2>Algorithm Simulation Lab</h2><div class="note">Split view: the map and the graph show the same algorithm state.</div><label class="f">Algorithm</label><select id="al"><option value="dijkstra">Dijkstra (shortest path)</option><option value="kruskal">Kruskal (MST)</option><option value="prim">Prim (MST)</option></select>
  <label class="f">Source station</label>${stIn('src', 'Source')}<div id="tgw"><label class="f">Target station</label>${stIn('tgt', 'Target')}<label class="f">Weight</label><select id="wt"><option value="km">distance (km)</option><option value="min">time (min)</option></select></div>
  <div id="scw" style="display:none"><label class="f">Graph</label><select id="sc"><option value="candidate">Candidate graph (pairs within max km)</option><option value="existing">Existing network</option></select><label class="f">Max candidate distance: <b id="mkv">3</b> km</label><input type="range" id="mk" min="0.5" max="8" step="0.5" value="3"></div>
  <h3>Edit the graph</h3><div class="note">Change a connection's weight, add a link between two stations, or remove one (type A, B, then a weight in the current units; leave weight empty to remove). Then press Load. In a tree no weight change alters the MST, so use the candidate graph.</div><div class="row">${stIn('oa', 'Station A')}${stIn('ob', 'Station B')}<input id="ow" type="number" step="0.1" min="0.1" placeholder="weight" style="width:80px"></div><div class="row"><button class="b" id="oadd">Apply edit</button><button class="b" id="oclr">Clear edits</button></div><div id="olist" class="note">No edits.</div>
  <div class="row"><button class="b p" id="run">Load</button><button class="b" id="prev">◀</button><button class="b" id="play">▶ Play</button><button class="b" id="next">▶|</button><button class="b" id="rst">Reset</button><select id="spd"><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option><option value="0.5">0.5×</option></select></div>
  <div id="eq" class="note"></div><div id="state"></div><h3>Compare Kruskal vs Prim (measured)</h3><div class="row"><button class="b" id="cmpb">Run comparison</button></div><div id="cmpr"></div>`);
  let steps = [], i = -1, meta = null, tm = null, ovr = [];
  const showOvr = () => { $('#olist').textContent = ovr.length ? 'Edits: ' + ovr.map(o => { const [p, v] = o.split(':'), [a, b] = p.split('~'); return short(S.by[a].name) + '–' + short(S.by[b].name) + ' → ' + (v === 'x' ? 'removed' : v); }).join('; ') : 'No edits.'; };
  $('#oadd').onclick = () => { const a = idOf($('#oa').value), b = idOf($('#ob').value); if (!a || !b || a === b) { $('#olist').innerHTML = '<span class="err">Pick two different valid stations.</span>'; return; } const w = $('#ow').value; ovr = ovr.filter(o => !o.startsWith(a + '~' + b + ':')); ovr.push(`${a}~${b}:${w ? +w : 'x'}`); showOvr(); };
  $('#oclr').onclick = () => { ovr = []; showOvr(); };
  S.onPick = id => { $('#src').value = S.by[id].name; select(id); };
  $('#mk').oninput = e => $('#mkv').textContent = e.target.value;
  $('#wt').onchange = () => { S.wmode = $('#wt').value; drawGraph(); };
  $('#al').onchange = () => { const d = $('#al').value === 'dijkstra'; $('#tgw').style.display = d ? '' : 'none'; $('#scw').style.display = d ? 'none' : ''; };
  $('#run').onclick = async () => {
    const s = idOf($('#src').value), t = idOf($('#tgt').value), a = $('#al').value, box = $('#state');
    if (!s) { box.innerHTML = '<div class="err">Choose a valid source station.</div>'; return; }
    try { meta = await api(`/trace?name=${a}&source=${s}${a === 'dijkstra' && t ? '&target=' + t : ''}&scope=${$('#sc').value}&max_km=${$('#mk').value}&weight=${$('#wt').value}${ovr.length ? '&overrides=' + encodeURIComponent(ovr.join(';')) : ''}`); steps = meta.steps; i = -1; stop(); render(); } catch (e) { err(box, e); }
  };
  const stop = () => { clearInterval(tm); tm = null; $('#play').textContent = '▶ Play'; };
  const go1 = d => { i = Math.max(-1, Math.min(steps.length - 1, i + d)); render(); if (i >= steps.length - 1) stop(); };
  $('#next').onclick = () => { stop(); go1(1); }; $('#prev').onclick = () => { stop(); go1(-1); }; $('#rst').onclick = () => { stop(); i = -1; render(); };
  $('#play').onclick = () => { if (tm) return stop(); if (!steps.length) return; if (i >= steps.length - 1) i = -1; $('#play').textContent = '❚❚ Pause'; tm = setInterval(() => go1(1), 700 / +$('#spd').value); S.timers.push(tm); };
  $('#spd').onchange = () => { if (tm) { stop(); $('#play').click(); } };
  function render() {
    if (!meta) return; const box = $('#state'), N = steps.length, hdr = `<b>Step ${i + 1} / ${N}</b>`;
    if (meta.algo === 'dijkstra') {
      const dist = { [meta.source]: 0 }, vis = new Set(), prev = {}; let cur = null, rl = null, pq = [];
      for (let k = 0; k <= i; k++) { const e = steps[k]; if (e.t === 'select') { cur = e.u; vis.add(e.u); dist[e.u] = e.d; pq = e.pq; rl = null; } else { rl = e; if (e.upd) { dist[e.v] = e.cand; prev[e.v] = e.u; } } }
      const mx = Math.max(1e-9, ...Object.values(dist)), nodes = {}, edges = {};
      Object.keys(dist).forEach(id => nodes[id] = vis.has(id) ? `hsl(${190 + 60 * dist[id] / mx},100%,${62 - 22 * dist[id] / mx}%)` : '#617CFF');
      vis.forEach(v => { if (prev[v]) edges[ek(prev[v], v)] = '#00D4FF'; }); if (cur) nodes[cur] = '#FFB84D'; nodes[meta.source] = '#32D69A'; if (rl) edges[ek(rl.u, rl.v)] = '#FFB84D';
      const done = i >= N - 1 && i >= 0; setOverlay({ nodes, edges, dim: true, route: done && meta.path.length > 1 ? meta.path : null, fit: false });
      const u = meta.weight === 'km' ? 'km' : 'min', nm = id => short(S.by[id].name);
      $('#eq').innerHTML = `<span class="fm">d(v) = min(d(v), d(u) + w(u,v))</span> · complexity <b>${meta.complexity}</b>` + (rl ? `<br>Relaxing ${nm(rl.u)} → ${nm(rl.v)}: min(${rl.old == null ? '∞' : f2(rl.old, 3)}, ${f2(rl.cand - rl.w, 3)} + ${f2(rl.w, 3)}) = ${f2(Math.min(rl.old ?? Infinity, rl.cand), 3)} ${u} → <b class="${rl.upd ? 'ok' : 'wn'}">${rl.upd ? 'updated' : 'no improvement'}</b>` : cur ? `<br>Selected ${nm(cur)} (d = ${f2(dist[cur], 3)} ${u}): it has the smallest tentative distance among all unvisited vertices in the priority queue, so its distance is now final.` : '');
      const rows = Object.entries(dist).sort((a, b) => a[1] - b[1]).slice(0, 10);
      box.innerHTML = `${hdr}<table><tr><th>Station</th><th>d(v)</th><th>State</th></tr>${rows.map(([id, d]) => `<tr><td>${nm(id)}</td><td>${f2(d, 3)}</td><td>${id === cur ? 'current' : vis.has(id) ? 'visited' : 'in queue'}</td></tr>`).join('')}</table>
      <div class="note">Priority queue (min first): ${pq.map(p => `${nm(p[1])} (${f2(p[0], 2)})`).join(', ') || '—'} · visited ${vis.size}${done && meta.target ? `<br>Final ${meta.final_dist == null ? '<span class="err">target unreachable</span>' : 'distance ' + f2(meta.final_dist, 3) + ' ' + u + ' via ' + meta.path.length + ' stations (highlighted on the map)'}` : ''}</div>`;
    } else {
      const acc = [], rej = [], extra = []; let cur = null, fr = []; const nodes = {}, nm = id => short(S.by[id].name);
      for (let k = 0; k <= i; k++) { const e = steps[k]; if (e.t === 'edge') { cur = e; (e.acc ? acc : rej).push(e); } else if (e.t === 'pick') { acc.push(e); cur = e; fr = e.frontier; } else if (e.t === 'skip') { rej.push(e); cur = e; } else if (e.t === 'start') { nodes[e.s] = '#32D69A'; } }
      acc.forEach(e => extra.push({ u: e.u, v: e.v, c: '#32D69A', w: 5 })); rej.slice(-60).forEach(e => extra.push({ u: e.u, v: e.v, c: '#FF5470', o: .45, d: 1, w: 2 }));
      if (cur) { extra.push({ u: cur.u, v: cur.v, c: '#FFB84D', w: 6 }); nodes[cur.u] = nodes[cur.v] = '#FFB84D'; } fr.forEach(f => extra.push({ u: f[1], v: f[2], c: '#617CFF', w: 4, o: .9 }));
      setOverlay({ extra, nodes, dim: true, fit: false });
      if (meta.algo === 'kruskal') {
        const nxt = steps.slice(i + 1, i + 7);
        $('#eq').innerHTML = `Kruskal: sort edges by weight; accept an edge iff its endpoints are in different Union-Find sets · <b>${meta.complexity}</b>` + (cur ? `<br>Examine ${nm(cur.u)} – ${nm(cur.v)} (${f2(cur.w, 3)} km): find(u)=${nm(cur.ru)}, find(v)=${nm(cur.rv)} → <b class="${cur.acc ? 'ok' : 'err'}">${cur.acc ? 'different sets: ACCEPT, union' : 'same set: REJECT (would form a cycle)'}</b>` : '');
        box.innerHTML = `${hdr}<div class="note">Accepted ${acc.length} · rejected ${rej.length} · components = |V| − accepted = ${meta.n - acc.length}<br>Next sorted edges (km): ${nxt.map(e => f2(e.w, 2)).join(', ') || '—'}</div>${i >= N - 1 ? `<div class="note">Final MST weight <b>${f2(meta.weight, 3)} km</b> with ${meta.edges.length} edges (${meta.components} component${meta.components > 1 ? 's' : ''}); ${meta.examined} edges examined of ${meta.candidate_edges}</div>` : ''}`;
      } else {
        $('#eq').innerHTML = `Prim: repeatedly add the cheapest edge leaving the current tree · <b>${meta.complexity}</b>` + (cur && cur.t === 'pick' ? `<br>Picked ${nm(cur.u)} → ${nm(cur.v)} (${f2(cur.w, 3)} km)` : cur ? `<br>Skipped edge to visited ${nm(cur.v)}` : '');
        box.innerHTML = `${hdr}<div class="note">Tree edges ${acc.length} · skipped ${rej.length}<br>Cheapest candidate edges: ${fr.map(f => `${nm(f[1])}–${nm(f[2])} (${f2(f[0], 2)})`).join('; ') || '—'}</div>${i >= N - 1 ? `<div class="note">Final MST weight <b>${f2(meta.weight, 3)} km</b>, ${meta.edges.length} edges, ${meta.examined} edges examined</div>` : ''}`;
      }
    }
  }
  $('#cmpb').onclick = async () => {
    const el = $('#cmpr'); try {
      const r = await api(`/algorithms/compare?max_km=${$('#mk').value}`);
      el.innerHTML = r.results.map(x => `<h3>${x.scope} graph (V=${x.V}, E=${x.E})</h3>` + tbl([['Kruskal', x.kruskal], ['Prim', x.prim]], [['Algo', a => a[0]], ['Time ms', a => f2(a[1].time_ms, 3)], ['Examined', a => a[1].examined], ['MST km', a => f2(a[1].weight, 3)], ['Edges', a => a[1].selected], ['Comp.', a => a[1].components]]) + `<div class="note">Weights equal: <b class="${x.weights_equal ? 'ok' : 'err'}">${x.weights_equal}</b>. Median of 30 runs; Kruskal ${r.complexity.kruskal}, Prim ${r.complexity.prim}.</div>`).join('');
    } catch (e) { err(el, e); }
  };
};

// ---------------- 4. Network Expansion ----------------
MODS.exp = () => {
  mod(`<h2>Network Expansion Simulator</h2><div class="note">Question: ignoring real alignments, what is the minimum-length connected network over these stations, given a maximum link length? Candidate graph = all station pairs within the limit (straight lines).</div>
  <label class="f">Max candidate link: <b id="a">3</b> km</label><input type="range" id="mx" min="0.5" max="10" step="0.5" value="3"><label class="f">Nearest-neighbour limit k (0 = all): <b id="bk">0</b></label><input type="range" id="k" min="0" max="10" value="0">
  <label class="f">Budget (km of link, blank = none)</label><input id="bud" type="number" min="1" placeholder="e.g. 40"><label class="f">Assumed cost (₹ crore / km)</label><input id="cpk" type="number" value="300" min="0">
  <label class="f">Algorithm</label><select id="alg"><option value="kruskal">Kruskal</option><option value="prim">Prim</option></select><div class="row"><button class="b p" id="go">Run</button><button class="b" id="anim">Replay build</button></div><div id="res"></div>`);
  let last = null;
  const draw = n => { const extra = []; last.rejected.forEach(e => extra.push({ u: e.u, v: e.v, c: '#FF5470', o: .3, w: 1, d: 1 })); last.selected.slice(0, n).forEach(e => extra.push({ u: e.u, v: e.v, c: e.existing ? '#00D4FF' : '#32D69A', w: e.existing ? 5 : 4 })); setOverlay({ extra, dim: true, fit: false }); };
  const run = async () => {
    $('#a').textContent = $('#mx').value; $('#bk').textContent = $('#k').value; const el = $('#res');
    try {
      const b = $('#bud').value; last = await api(`/expansion?max_km=${$('#mx').value}&k=${$('#k').value}&algorithm=${$('#alg').value}&cost_per_km=${$('#cpk').value || 0}${b ? '&budget_km=' + b : ''}`);
      draw(last.selected.length); const r = last;
      el.innerHTML = `<h3>Results</h3>${tbl([['Candidate edges', r.candidate_edges], ['Selected (tree edges)', r.selected.length + ' (' + r.overlap_with_existing + ' coincide with real links)'], ['Rejected candidates', r.rejected_count], ['MST total', f2(r.mst_km, 2) + ' km (straight lines)'], ['Real network, same basis', f2(r.baseline.existing_km, 2) + ' km straight (' + f2(r.baseline.existing_track_km, 2) + ' km of track)'], ['Difference', f2(r.difference_km, 2) + ' km'], ['Components', r.components + (r.budget_stopped ? ' (budget reached)' : '')], ['Cost, same model', '₹' + f2(r.estimated_cost, 0) + ' cr (real network: ₹' + f2(r.baseline.existing_cost_same_model, 0) + ' cr)'], ['Kruskal vs Prim', f2(r.kruskal_km, 3) + ' vs ' + f2(r.prim_km, 3) + ' km']], [['', x => x[0]], ['', x => x[1]]])}
      <div class="note"><span class="wn">Legend:</span> cyan = MST link that matches a real link · green = MST link not in the real network · faint dashed red = rejected candidates (first 300). ${r.components > 1 ? 'The candidate graph is disconnected at this limit, so the result is a spanning forest. ' : ''}${r.overlap_with_existing === r.selected.length && r.components === 1 ? '<b>The real network is itself the minimum spanning tree at this limit.</b> ' : ''}${r.limitations}</div>`;
    } catch (e) { err(el, e); }
  };
  $('#go').onclick = run; $('#mx').oninput = () => $('#a').textContent = $('#mx').value; $('#k').oninput = () => $('#bk').textContent = $('#k').value;
  $('#anim').onclick = () => { if (!last) return; clearTimers(); let n = 0; const t = setInterval(() => { n += 2; draw(n); if (n >= last.selected.length) clearInterval(t); }, RM ? 1 : 80); S.timers.push(t); };
  run();
};

// ---------------- 5. Network Intelligence ----------------
MODS.intel = async () => {
  mod('<h2>Network Intelligence</h2><div id="body">Loading…</div>');
  try {
    const it = await api('/intel'), m = await api('/metrics'); S.layers.crit = true; $('#ly-crit').checked = true; applyVis();
    $('#body').innerHTML = `<div class="row"><a class="b" href="/api/export/stations.csv" style="text-decoration:none;color:inherit">⬇ Export CSV</a></div>
    <div class="note"><span class="fm">C<sub>D</sub>(v)=deg(v)/(N−1)</span> · <span class="fm">C<sub>B</sub>(v)=Σ σ<sub>st</sub>(v)/σ<sub>st</sub></span> (normalised). High degree = many direct neighbours; high betweenness = many shortest paths pass through; articulation point = removal disconnects the graph. ${m.is_tree ? 'In this tree-shaped network every non-terminal station is an articulation point, but betweenness still ranks how much each matters. Red halos on the map mark the top 10 by betweenness.' : ''}</div>
    <h3>Top betweenness</h3>${tbl(it.top_betweenness, [['Station', r => short(r.name)], ['C_B', r => f2(r.betweenness, 3)], ['deg', r => r.degree], ['Artic.', r => r.articulation ? 'yes' : 'no']])}
    <h3>Top degree centrality</h3>${tbl(it.top_degree, [['Station', r => short(r.name)], ['C_D', r => f2(r.degree_centrality, 3)], ['deg', r => r.degree]])}
    <div id="sc" class="chart" style="height:260px"></div><h3>Articulation points: ${it.articulation_points.length} of ${m.stations}</h3><div class="note">Not articulation points: ${it.stations.filter(r => !r.articulation).map(r => short(r.name)).join(', ')}</div>`;
    chart($('#sc'), { title: { text: 'Degree vs betweenness (each dot = station)' }, tooltip: { formatter: p => p.data[2] + '<br>deg ' + p.data[0] + ' · C_B ' + p.data[1].toFixed(3) }, xAxis: { type: 'value', ...axis('degree k', { min: 0, max: 4, interval: 1 }) }, yAxis: { type: 'value', ...axis('betweenness C_B (dimensionless)', { nameGap: 36 }) }, series: [{ type: 'scatter', symbolSize: 9, data: it.stations.map(r => [r.degree, r.betweenness, short(r.name)]), itemStyle: { color: '#00D4FF' } }] });
  } catch (e) { err($('#body'), e); }
};

// ---------------- 6. Failure Simulator ----------------
MODS.fail = () => {
  S.layers.vuln = true; $('#ly-vuln').checked = true; applyVis();
  mod(`<h2>Infrastructure Failure Simulator</h2><div class="note">Click stations on the map or graph to add/remove them from the failure set. Each simulation works on a copy; the original graph is never modified. Heat halos show single-station vulnerability.</div><div id="fl">None selected</div>
  <label class="f">Disable an entire line (corridor)</label><select id="fline"><option value="">None</option>${Object.keys(S.lc).map(l => `<option>${l}</option>`).join('')}</select><div class="note">To cut one connection, click a metro line on the map and press “Cut this connection”.</div><div id="fcut"></div><label class="f">Optional route check: origin</label>${stIn('fo', 'Origin')}<label class="f">Destination</label>${stIn('fd', 'Destination')}
  <div class="row"><button class="b p" id="sim">SIMULATE FAILURE</button><button class="b" id="cascade-sim" style="border-color:#FF8C00;color:#FFB84D">⚡ Cascading Failure</button><button class="b" id="rec">Recover / reset</button></div><div id="res"></div><h3>Single-station impact ranking</h3><div id="rk" class="chart" style="height:300px"></div>`);
  if ($('#cascade-sim')) $('#cascade-sim').onclick = () => window.runCascadingFailure && window.runCascadingFailure();
  const upd = () => { $('#fcut').innerHTML = S.cut.size ? [...S.cut].map(k => { const [a, b] = k.split('|'); return `<span class="chip" style="background:#a33">✂ ${short(S.by[a].name)}–${short(S.by[b].name)}</span>`; }).join('') : ''; $('#fl').innerHTML = S.failed.size ? [...S.failed].map(id => `<span class="chip" style="background:#CC0000;border:1px solid #FF4444;font-weight:600">⛔ ${short(S.by[id].name)}</span>`).join('') : 'None selected'; paint(); };
  S.onPick = id => { S.failed.has(id) ? S.failed.delete(id) : S.failed.add(id); select(id); upd(); };
  window.cutEdge = (u, v) => { S.cut.add(ek(u, v)); upd(); };
  $('#fline').onchange = () => { S.offLine = $('#fline').value || null; upd(); };
  $('#rec').onclick = () => { S.failed.clear(); S.cut.clear(); S.offLine = null; S._affectedSet = null; $('#fline').value = ''; upd(); setOverlay({}); $('#res').innerHTML = ''; };
  $('#sim').onclick = async () => {
    const el = $('#res'); if (!S.failed.size && !S.cut.size && !S.offLine) { el.innerHTML = '<div class="err">Select a station, cut a connection or disable a line first.</div>'; return; }
    if (S.failed.size > 1 && !confirm(`Simulate failure of ${S.failed.size} stations?`)) return;
    try {
      const body = { removed: [...S.failed], removed_edges: [...S.cut].map(k => k.split('|')), removed_line: S.offLine, src: idOf($('#fo').value) || null, dst: idOf($('#fd').value) || null };
      const r = await api('/failure', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      // — Build node colour overlay: failed=red, affected(cut-off)=amber, main component=green, others=palette
      const affectedSet = new Set(r.affected || []);
      const nodes = {};
      r.components.forEach((c, k) => c.stations.forEach(s => {
        if (S.failed.has(s)) nodes[s] = '#FF0000';
        else if (affectedSet.has(s)) nodes[s] = '#FF8C00';
        else nodes[s] = k === 0 ? '#32D69A' : PAL[(k + 1) % PAL.length];
      }));
      // Also add affected halos into paintMap via a paintHook flag
      S._affectedSet = affectedSet;
      setOverlay({ nodes, fit: false });

      // — Big impact numbers
      const connLoss = f2(100 * r.connectivity_loss, 1);
      const reachPct = f2(100 * r.after.reachable_pair_fraction, 1);
      const ttBefore = r.avg_travel_time_before != null ? f2(r.avg_travel_time_before, 1) : null;
      const ttAfter  = r.avg_travel_time_after  != null ? f2(r.avg_travel_time_after,  1) : null;
      const ttShift  = r.travel_time_increase_pct != null ? r.travel_time_increase_pct : null;
      const cutOff   = r.affected.length;
      const severed  = r.affected_edges ? r.affected_edges.length : 0;

      el.innerHTML = `
      <button class="b p" id="btn-open-report" style="width:100%;margin-bottom:10px;padding:8px 12px;display:flex;align-items:center;justify-content:center;gap:6px;font-weight:600">📄 Export Executive Disruption Report (PDF/Print)</button>
      <div class="fsim-banner ${r.after.components > 1 ? 'fsim-banner-err' : 'fsim-banner-ok'}">
        ${r.after.components > 1
          ? `⛔ NETWORK FRAGMENTED — ${r.after.components} isolated components`
          : '✅ Network remains connected'}
      </div>

      <div class="fsim-cards">
        <div class="fsim-card fsim-card-red">
          <div class="fsim-num">${cutOff}</div>
          <div class="fsim-label">Stations<br>Cut Off</div>
        </div>
        <div class="fsim-card fsim-card-amber">
          <div class="fsim-num">${connLoss}%</div>
          <div class="fsim-label">Connectivity<br>Loss</div>
        </div>
        <div class="fsim-card fsim-card-amber">
          <div class="fsim-num">${reachPct}%</div>
          <div class="fsim-label">Reachable<br>Pairs Left</div>
        </div>
        <div class="fsim-card ${ttShift != null && ttShift < 0 ? 'fsim-card-green' : 'fsim-card-amber'}">
          <div class="fsim-num">${ttShift != null ? (ttShift > 0 ? '+' : '') + f2(ttShift, 1) + '%' : '—'}</div>
          <div class="fsim-label">Travel Time<br>Shift</div>
        </div>
      </div>

      ${cutOff > 0 ? `<div class="fsim-affected-banner">
        🟠 <b>${cutOff} affected station${cutOff > 1 ? 's' : ''} (shown in orange on map):</b>
        <div class="fsim-affected-chips">${r.affected.map(s => `<span class="chip" style="background:#a05000;border:1px solid #FF8C00">${short(S.by[s].name)}</span>`).join('')}</div>
      </div>` : ''}

      <div class="fsim-section">
        <div class="fsim-section-title">BEFORE VS AFTER</div>
        ${tbl([['Components', r.before.components, r.after.components],
               ['Stations active', r.before.stations, r.after.stations],
               ['Reachable pairs', '100%', reachPct + '%'],
               ['Avg path (hops)', f2(r.before.avg_path_hops, 1), f2(r.after.avg_path_hops, 1)]],
              [['Metric', x => x[0]], ['Before', x => x[1]], ['After', x => x[2]]])}
        <div class="note">Component sizes after: ${r.after.component_sizes.join(', ')} (green = largest). Connectivity loss <b class="err">${connLoss}%</b>.</div>
      </div>

      ${ttBefore != null && ttAfter != null ? `<div class="fsim-section">
        <div class="fsim-section-title">⏱ AVERAGE TRAVEL TIME IMPACT</div>
        <div class="fsim-tt-row">
          <div class="fsim-tt-box">
            <div class="fsim-tt-val">${ttBefore} min</div>
            <div class="fsim-tt-lbl">Before failure</div>
          </div>
          <div class="fsim-tt-arrow">→</div>
          <div class="fsim-tt-box fsim-tt-box-after">
            <div class="fsim-tt-val">${ttAfter} min</div>
            <div class="fsim-tt-lbl">After failure</div>
          </div>
          <div class="fsim-tt-box ${ttShift > 0 ? 'fsim-tt-box-bad' : 'fsim-tt-box-good'}">
            <div class="fsim-tt-val">${ttShift > 0 ? '+' : ''}${f2(ttShift, 1)}%</div>
            <div class="fsim-tt-lbl">Time shift</div>
          </div>
        </div>
      </div>` : ''}

      ${severed > 0 ? `<div class="fsim-section">
        <div class="fsim-section-title">✂ DIRECTLY SEVERED CONNECTIONS (${severed})</div>
        ${tbl(r.affected_edges, [['From', e => short(e.u_name)], ['To', e => short(e.v_name)],
          ['Line', e => `<span class="chip" style="background:${S.lc[e.line]||'#555'}">${e.line}</span>`],
          ['Track', e => f2(e.km) + ' km'], ['Time', e => f2(e.min, 1) + ' min']])}
      </div>` : ''}

      ${r.passenger_load && r.passenger_load.length ? `<div class="fsim-section">
        <div class="fsim-section-title">📈 PASSENGER LOAD SHIFT ON ALTERNATIVES</div>
        <div class="note">Estimated via betweenness centrality shift on surviving graph.</div>
        ${tbl(r.passenger_load, [['Connection', e => `${short(e.u_name)} – ${short(e.v_name)}`],
          ['Line', e => `<span class="chip" style="background:${S.lc[e.line]||'#555'}">${e.line}</span>`],
          ['Load change', e => `<span class="${e.load_increase_pct > 0 ? 'wn' : 'ok'}">${e.load_increase_pct > 0 ? '+' : ''}${f2(e.load_increase_pct, 1)}%</span>`]])}
      </div>` : ''}

      <div class="fsim-section">
        <div class="fsim-section-title">◈ CENTRALITY CHANGE (BETWEENNESS)</div>
        ${tbl(r.centrality_change, [['Station', x => short(x.name)], ['Before', x => f2(x.before, 3)], ['After', x => f2(x.after, 3)]])}
        <div class="note">In this tree-shaped network a cut station or link leaves <b>no detour</b> — disconnected pairs have no route at all.</div>
      </div>

      ${r.route_check ? `<div class="fsim-section">
        <div class="fsim-section-title">🛣 ROUTE CHECK</div>
        <div class="fsim-tt-row">
          <div class="fsim-tt-box"><div class="fsim-tt-val">${r.route_check.before.reachable ? f2(r.route_check.before.time_min,1)+' min' : '—'}</div><div class="fsim-tt-lbl">Before</div></div>
          <div class="fsim-tt-arrow">→</div>
          <div class="fsim-tt-box ${r.route_check.after.reachable ? '' : 'fsim-tt-box-bad'}"><div class="fsim-tt-val">${r.route_check.after.reachable ? f2(r.route_check.after.time_min,1)+' min' : 'NO ROUTE'}</div><div class="fsim-tt-lbl">After</div></div>
        </div>
      </div>` : ''}

      <div id="recovery-sim-mount"></div>`;
      const btnRep = $('#btn-open-report');
      if (btnRep) btnRep.onclick = () => window.generateDisruptionReport && window.generateDisruptionReport(r);
      if (window.renderRecoverySimulator) window.renderRecoverySimulator(r);
    } catch (e) { err(el, e); }
  };
  api('/failure/ranking').then(rk => { const top = rk.slice(0, 15).reverse(); const c = chart($('#rk'), { title: { text: 'Top 15 stations by connectivity loss if removed' }, grid: { left: 150, right: 20, top: 36, bottom: 40 }, xAxis: { type: 'value', ...axis('share of remaining station pairs disconnected', { axisLabel: { formatter: v => (100 * v).toFixed(0) + '%' } }) }, yAxis: { type: 'category', data: top.map(r => short(r.name)), axisLabel: { fontSize: 10 } }, series: [{ type: 'bar', data: top.map(r => +r.connectivity_loss.toFixed(4)), itemStyle: { color: '#FF5470' } }] }); c.on('click', p => { const r = top[p.dataIndex]; S.failed.add(r.id); select(r.id); upd(); }); }).catch(e => err($('#rk'), e));
};

// ---------------- 7. Mathematics ----------------
MODS.math = () => {
  const C = [['Graph', 'G = (V, E): vertices and edges. Here V = stations, E = links between consecutive stations on a line. N = 83, M = 82. Switch to “Graph theory” mode to see G drawn with its weights.'],
    ['Weighted graph', 'w: E → ℝ≥0, here track km or timetable minutes. Dijkstra requires w ≥ 0.'], ['Directed vs undirected', 'Tracks are used both ways, so G is undirected: (u,v) = (v,u).'],
    ['Degree', 'deg(v) = number of edges at v; Σ deg(v) = 2|E|. Terminals 1, ordinary stations 2, interchanges 4.'], ['Adjacency matrix', 'A<sub>ij</sub> = 1 if (i,j) ∈ E. Row sums give degrees. See the live example below.'],
    ['Connectivity', 'G is connected if a path joins every pair. A tree has |E| = |V| − 1 and exactly one path between any two vertices.'],
    ['Dijkstra', 'd(v) = min(d(v), d(u) + w(u,v)). Greedy: finalise the nearest unvisited vertex. O((V+E) log V) with a binary heap.'],
    ['Minimum spanning tree', 'Spanning tree T minimising Σ w(e): |V| − 1 edges, no cycle. A cheapest connected network under the given weights, not a construction plan.'],
    ['Prim', 'Grow one tree; always add the cheapest edge leaving it. O(E log V).'], ['Kruskal', 'Sort edges; accept an edge if it joins two different Union-Find sets. O(E log E).'],
    ['Degree centrality', 'C<sub>D</sub>(v) = deg(v)/(N−1).'], ['Betweenness centrality', 'C<sub>B</sub>(v) = Σ σ<sub>st</sub>(v)/σ<sub>st</sub>: share of shortest paths through v.'],
    ['Articulation point', 'v such that G − v has more components; found by DFS low-link in O(V+E).']];
  mod(`<h2>Mathematics Explorer</h2>${C.map(c => `<h3>${c[0]}</h3><div>${c[1]}</div>`).join('')}<h3>Live example: adjacency matrix of a station's neighbourhood</h3><div id="am" class="note">Click a station on the map or graph.</div>`);
  S.onPick = id => { select(id); const ids = [id, ...Object.keys(S.adj[id])], n = x => short(S.by[x].name).slice(0, 7); $('#am').innerHTML = `<table><tr><th></th>${ids.map(i => `<th>${n(i)}</th>`).join('')}</tr>${ids.map(a => `<tr><th>${n(a)}</th>${ids.map(b => `<td>${S.adj[a][b] ? 1 : 0}</td>`).join('')}</tr>`).join('')}</table>Row sum of the first row = deg = ${ids.length - 1}.`; };
};

window.closeStation = id => { go('fail'); S.onPick(id); $('#sim').click(); };
Object.assign(window, { NODAL: { setBase, S, G, MODS, api, $, f2, short, tbl, mod, chart, axis, err, setOverlay, paint, paintMap, drawGraph, select, pick, go, setMode, idOf, stIn, fc, feat, hv, routeCoords, edgeGeom, posAt, lineUpTo, setSrc, applyVis, LAY, LAYNAME, PAL, RM, countUp, clearTimers, lineChips, ek } });
boot().catch(e => { $('#mod').innerHTML = `<div class="err">⚠ Could not start: ${e.message}</div>`; console.error(e); });
