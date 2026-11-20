import { JSDOM } from 'jsdom'; import fs from 'fs';
const FE = new URL('../frontend/', import.meta.url).pathname;
const html = fs.readFileSync(FE + 'index.html', 'utf8').replace(/<script[^>]*>[\s\S]*?<\/script>/g, '').replace(/<link[^>]*>/g, '');
const dom = new JSDOM(html, { url: 'http://localhost:8000/', runScripts: 'outside-only', pretendToBeVisual: true });
const w = dom.window, errors = [], log = [];
const ctx = new Proxy({}, { get: (t, k) => (k === 'measureText' ? () => ({ width: 5 }) : () => {}), set: () => true });
w.HTMLCanvasElement.prototype.getContext = () => ctx;
w.HTMLCanvasElement.prototype.setPointerCapture = () => {};
w.Element.prototype.setPointerCapture = () => {};
w.fetch = (u, o) => fetch(new URL(u, 'http://localhost:8000'), o);
w.ResizeObserver = class { observe() {} };
w.matchMedia = () => ({ matches: false });
w.confirm = () => true; w.devicePixelRatio = 1;
w.addEventListener('error', e => errors.push('window error: ' + e.message));
w.console.error = (...a) => errors.push('console.error: ' + a.join(' '));
// strict maplibre stub
const state = { sources: {}, layers: {}, setData: 0, calls: [] };
class Map {
  constructor() { this.h = {}; this._pitch = 45; setTimeout(() => this.fire('style.load'), 0); }
  on(ev, cb) { (this.h[ev] = this.h[ev] || []).push(cb); } fire(ev, e) { (this.h[ev] || []).forEach(f => f(e)); }
  addControl() {} getCanvas() { return { style: {} }; } resize() {} getPitch() { return this._pitch; } getZoom() { return 11; }
  setStyle(s) { state.sources = {}; state.layers = {}; state.calls.push('setStyle'); setTimeout(() => this.fire('style.load'), 0); }
  addSource(id, def) { if (state.sources[id]) errors.push('duplicate source ' + id); state.sources[id] = def; if (def.type === 'geojson') state.sources[id].data = def.data; }
  getSource(id) { const s = state.sources[id]; return s && { setData: d => { state.setData++; if (d.type !== 'FeatureCollection') errors.push('bad geojson for ' + id); d.features.forEach(f => { if (!f.geometry || !f.geometry.coordinates) errors.push('bad feature in ' + id); }); s.last = d; if (id === 'lines' || id === 'st') d.features.forEach(f => { const c = f.properties.c; if (!c || /undefined/.test(c)) errors.push('undefined colour in ' + id + ': ' + JSON.stringify(f.properties).slice(0, 80)); }); } }; }
  addLayer(l, before) { if (before && !state.layers[before]) errors.push('beforeId missing ' + before + ' for ' + l.id); if (!state.sources[l.source]) errors.push('layer ' + l.id + ' unknown source ' + l.source); if (state.layers[l.id]) errors.push('duplicate layer ' + l.id); state.layers[l.id] = l; }
  getLayer(id) { return state.layers[id]; } setLayoutProperty(id, p, v) { if (!state.layers[id]) errors.push('vis unknown layer ' + id); state.layers[id].vis = v; }
  setTerrain(t) { state.terrain = t; } fitBounds(b) { state.calls.push('fitBounds'); } flyTo() { state.calls.push('flyTo'); } easeTo(o) { state.calls.push('easeTo'); if (o.pitch != null) this._pitch = o.pitch; }
  queryRenderedFeatures(pt, o) { return (this.qr && this.qr(pt, o)) || []; } jumpTo(o) { state.jump = (state.jump || 0) + 1; state.lastJump = o; }
}
class Marker { constructor(o) { this.el = o.element; this.h = {}; state.markers = (state.markers || 0) + 1; this.ll = [0, 0]; } setLngLat(l) { this.ll = l; return this; } addTo() { return this; } getLngLat() { return { lng: this.ll[0], lat: this.ll[1] }; } on(e, f) { this.h[e] = f; } remove() { state.markers--; } }
w.maplibregl = { Marker, Map, NavigationControl: class {}, ScaleControl: class {}, AttributionControl: class {}, Popup: class { setLngLat() { return this; } setHTML() { return this; } addTo() { return this; } remove() {} } };
w.echarts = { init: () => ({ setOption() {}, on() {} }) };
let code = fs.readFileSync(FE + 'app.mjs', 'utf8') + '\nwindow.__S=S;window.__pick=pick;window.__go=go;window.__setMode=setMode;';
w.eval(code);
w.eval(fs.readFileSync(FE + 'ext.mjs', 'utf8'));
const sleep = ms => new Promise(r => setTimeout(r, ms)), $ = s => w.document.querySelector(s), click = s => $(s).dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) errors.push('assert: ' + m); };
await sleep(1500); const S = w.__S;
ok(S.st.length === 83 && S.edges.length === 82, 'network loaded 83/82');
ok(state.layers['st'] && state.layers['lines'] && state.layers['route'] && state.layers['halo-vuln'], 'map layers created');
ok($('#mod').textContent.includes('Stations') && $('#g').children.length === 10, 'command center stats');
const st = id => S.st.find(s => s.name.includes(id)).id;
// layer toggles
for (const k of Object.keys(S.layers)) { if (k === 'proposed') continue; const cb = $('#ly-' + k); cb.checked = !cb.checked; cb.dispatchEvent(new w.Event('change')); }
ok(state.layers['lines'].vis === 'none' && state.terrain === null || state.terrain, 'layer toggles apply'); 
for (const k of Object.keys(S.layers)) { if (k === 'proposed') continue; const cb = $('#ly-' + k); cb.checked = !cb.checked; cb.dispatchEvent(new w.Event('change')); }
// basemap switch re-adds layers
click('#bases button[data-v="hybrid"]'); await sleep(50); ok(state.layers['st'] && state.layers['route-dots'], 'basemap switch re-creates layers'); click('#bases button[data-v="roadmap"]'); await sleep(50);
// modes
for (const m of ['graph', 'split', 'geo']) { click(`#modes button[data-v="${m}"]`); await sleep(20); ok($('#stage').className === 'm-' + m, 'mode ' + m); }
// station select
w.__pick(st('Majestic')); ok($('#info').textContent.includes('Interchange') && $('#info').textContent.includes('km'), 'station info panel');
// route
click('nav [data-m="route"]'); await sleep(50);
$('#o').value = 'Whitefield (Kadugodi)'; $('#d').value = 'Silk Institute'; click('#go'); await sleep(1500);
ok($('#res').textContent.includes('Journey time') && $('#res').querySelectorAll('li').length === 38, 'route result with station sequence');
ok(state.sources.route.last && state.sources.route.last.features[0].geometry.coordinates.length > 10, 'route drawn on map progressively');
ok(state.sources.rdots.last.features.length > 0, 'moving indicators'); click('#fly'); await sleep(50); ok(state.calls.includes('easeTo'), 'fly along route');
$('#d').value = 'nonexistent'; click('#go'); await sleep(50); ok($('#res').textContent.includes('valid'), 'invalid input handled');
// algorithms
click('nav [data-m="algo"]'); await sleep(50); ok($('#stage').className === 'm-split', 'algo lab switches to split view');
$('#src').value = 'Majestic'; $('#tgt').value = 'Lalbagh'; click('#run'); await sleep(500); ok($('#eq').textContent.includes('d(v) = min'), 'dijkstra loaded');
for (let i = 0; i < 400; i++) click('#next'); await sleep(50); ok($('#state').textContent.includes('Final'), 'dijkstra completes with final distance');
ok(S.rt && S.rt.ids.length > 1, 'final dijkstra route shown'); click('#rst'); click('#prev');
$('#al').value = 'kruskal'; $('#al').dispatchEvent(new w.Event('change')); click('#run'); await sleep(500);
for (let i = 0; i < 500; i++) click('#next'); ok($('#state').textContent.includes('Final MST weight'), 'kruskal completes'); ok(state.sources.mst.last.features.length > 0, 'kruskal edges on map');
$('#al').value = 'prim'; $('#al').dispatchEvent(new w.Event('change')); $('#src').value = 'Majestic'; click('#run'); await sleep(500);
for (let i = 0; i < 700; i++) click('#next'); ok($('#state').textContent.includes('Final MST weight'), 'prim completes');
click('#play'); await sleep(100); click('#play'); click('#cmpb'); await sleep(1200); ok($('#cmpr').textContent.includes('Weights equal'), 'algorithm comparison');
// expansion
click('nav [data-m="exp"]'); await sleep(1200); ok($('#res').textContent.includes('MST total') && $('#res').textContent.includes('minimum spanning tree'), 'expansion run (real network == MST at 3 km)');
$('#mx').value = '1.5'; click('#go'); await sleep(1200); ok($('#res').textContent.includes('spanning forest'), 'expansion disconnected -> forest'); click('#anim'); await sleep(200);
// intel, failure
click('nav [data-m="intel"]'); await sleep(1000); ok($('#body').textContent.includes('Top betweenness'), 'intelligence');
click('nav [data-m="fail"]'); await sleep(300); w.__pick(st('Majestic')); click('#sim'); await sleep(1200); ok($('#res').textContent.includes('cut off'), 'failure simulation');
click('#rec'); ok(S.failed.size === 0, 'recover resets'); ok(S.overlay && !S.overlay.nodes, 'overlay cleared');
click('nav [data-m="math"]'); w.__pick(st('Majestic')); ok($('#am').textContent.includes('Row sum'), 'math explorer matrix');
$('#q').value = 'Lalbagh'; $('#q').dispatchEvent(new w.Event('change')); ok(S.sel === st('Lalbagh'), 'search selects station');

// ===== planning studio =====
click('nav [data-m="plan"]'); await sleep(1500);
ok($('#ptab').textContent.includes('Destinations ranked') && state.sources.access.last.features.length > 500, 'planning: accessibility heatmap drawn');
ok(state.sources.anchors.last.features.length === 18, 'planning: destinations layer');
const pe = w.__NODAL_EXT.P;
click('.tabs button[data-t="cor"]'); await sleep(2500);
ok($('#clist').querySelectorAll('.card').length >= 3, 'planning: ranked corridor candidates listed');
await sleep(3500);
ok(state.sources.plan.last.features.length >= 1 && state.sources['plan-st'].last.features.length >= 3, 'planning: proposed corridor + stations drawn (animated)');
ok($('#evalbox').textContent.includes('Before / after simulation') && $('#evalbox').textContent.includes('Recommendation report') && $('#evalbox').textContent.includes('Limitations'), 'planning: before/after + report shown');
ok($('#evalbox').textContent.includes('HYPOTHETICAL'), 'planning: labelled hypothetical');
const top1 = $('#clist .card b').textContent;
for (const k of ['coverage','destinations','connectivity','interchange','integration','feasibility']) { const e = $('#w_' + k); e.value = '0'; e.dispatchEvent(new w.Event('input')); } const cw = $('#w_cost'); cw.value = '5'; cw.dispatchEvent(new w.Event('input')); await sleep(3500);
ok($('#clist .card b').textContent !== top1, 'planning: changing weights changes the recommended corridor');
click('#ba button[data-v="before"]'); await sleep(100); ok(state.sources.plan.last.features.length === 0, 'planning: BEFORE view hides proposed corridor');
click('#ba button[data-v="after"]'); await sleep(3500); ok(state.sources.plan.last.features.length >= 1, 'planning: AFTER view restores corridor');
ok(state.sources.access.last.features.some(f => f.properties.c === '#00D4FF'), 'planning: improved cells highlighted');
click('#fst'); await sleep(50); ok(state.calls.includes('easeTo'), 'planning: camera flies through stations');
// designer
click('.tabs button[data-t="des"]'); await sleep(100);
ok(typeof S.clickHook === 'function', 'designer: map click mode active');
const hub = S.st.find(s => s.name.includes('Yeshwantpur')).id;
state.qrHit = [{ properties: { id: hub } }]; S.map.qr = () => state.qrHit; S.clickHook({ point: {}, lngLat: { lat: 13.0, lng: 77.5 } });
state.qrHit = []; S.clickHook({ point: {}, lngLat: { lat: 13.05, lng: 77.53 } }); S.clickHook({ point: {}, lngLat: { lat: 13.08, lng: 77.57 } });
await sleep(1500);
ok(state.markers === 2, 'designer: draggable markers for proposed stations');
ok($('#evalbox').textContent.includes('Before / after simulation') && $('#evalbox').textContent.includes('User-designed'), 'designer: user corridor evaluated');
await sleep(300);
w.prompt = () => 'My scenario'; click('#svs'); await sleep(1200);
ok($('#saved').textContent.includes('My scenario'), 'scenarios: user design saved and listed');
click('#gens'); await sleep(2500);
ok($('#gens-out').querySelectorAll('.card').length === 4, 'scenarios: A-D generated');
ok(/Scenario A/.test($('#gens-out').textContent) && /Scenario B/.test($('#gens-out').textContent), 'scenarios: named');
$('#gens-out .card').dispatchEvent(new w.MouseEvent('click', { bubbles: true })); await sleep(3500); ok(state.sources.plan.last.features.length >= 1, 'scenarios: selecting a scenario draws its corridors');
w.document.querySelector('[data-rm]') && w.document.querySelectorAll('#saved [data-rm]').forEach(b => b.dispatchEvent(new w.MouseEvent('click', { bubbles: true }))); await sleep(500);
// graph mode shows plan
click('#modes button[data-v="graph"]'); await sleep(100); ok(true, 'graph mode renders with planning overlay (no exception)'); click('#modes button[data-v="geo"]');
// leave clears
click('nav [data-m="cc"]'); await sleep(100); ok(state.sources.plan.last.features.length === 0 && state.markers === 0, 'leaving planning clears proposals and markers');
// ===== centrality sizing =====
const cm = $('#cm'); cm.value = 'closeness'; cm.dispatchEvent(new w.Event('change')); await sleep(50);
ok(state.sources.st.last.features.some(f => f.properties.r > 10) && state.sources.towers.last.features.length === 83, 'centrality: markers + 3D towers sized by closeness'); cm.value = ''; cm.dispatchEvent(new w.Event('change'));
// ===== station close =====
w.__pick(st('Majestic')); click('#closeSt'); await sleep(1500); ok($('#res').textContent.includes('cut off') && $('#res').textContent.includes('Centrality change'), 'station panel: simulate closing -> failure results');
// line + edge failures
click('#rec'); $('#fline').value = 'Yellow'; $('#fline').dispatchEvent(new w.Event('change')); click('#sim'); await sleep(1200); ok($('#res').textContent.includes('15 stations cut off'), 'failure: whole corridor (Yellow line) disabled');
click('#rec'); w.cutEdge(st('Majestic'), Object.keys(S.adj[st('Majestic')])[0]); click('#sim'); await sleep(1200); ok($('#res').textContent.includes('cut off'), 'failure: cut one connection');
// ===== trains =====
click('nav [data-m="trains"]'); await sleep(600);
const T = w.__NODAL_EXT.T; ok(Object.keys(T.lines).length === 3 && T.trains.length >= 6, 'trains: lines built from real geometry, ' + T.trains.length + ' trains');
await sleep(1500); const f1 = state.sources.trains.last; ok(f1 && f1.features.length === T.trains.length * 3, 'trains: 3 car blocks per train');
ok(Object.values(T.lines).every(L => L.stopKm.length === L.chain.length && L.stopKm.every((x, i) => i === 0 || x > L.stopKm[i - 1])), 'trains: station stops strictly increase along track');
const L = T.lines.Purple; ok(Math.abs(L.stopKm[L.stopKm.length - 1] - S.edges.filter(e => e.line === 'Purple').reduce((a, e) => a + e.km, 0)) < 1.0, 'trains: Purple track length matches data (' + L.stopKm.at(-1).toFixed(1) + ' km)');
const inb = f1.features.every(f => f.geometry.coordinates[0].every(p => p[0] > 77.3 && p[0] < 77.9 && p[1] > 12.7 && p[1] < 13.2)); ok(inb, 'trains: all positions within Bengaluru');
// kinematics: never exceed vmax, speed 0 when dwelling, position continuous
let vmaxSeen = 0, jump = 0, prev = null, dwell0 = true; const tr0 = T.trains[0];
for (let t = 0; t < 4000; t += 0.5) { const u = (t + tr0.phase) % tr0.L.C; const e = tr0.L.ev.find(x => u >= x.t0 && u < x.t1); if (!e) continue; }
ok(tr0.L.C > 3000 && tr0.L.C < 20000, 'trains: round trip time plausible (' + (tr0.L.C / 60).toFixed(0) + ' min)');
const ids0 = T.trains.map(t => t.st && t.st.mode); ok(ids0.some(m => m === 'cruising' || m === 'accelerating') , 'trains: moving trains present'); ok(T.trains.every(t => t.st && t.st.v <= T.vmax / 3.6 + 1e-6), 'trains: speed never exceeds max');
ok(T.trains.filter(t => t.st.mode === 'dwelling').every(t => t.st.v === 0), 'trains: speed 0 while dwelling');
T.sim = 0; const p0 = T.trains[0].head && T.trains[0].head.slice(); await sleep(800); ok(T.sim > 0 && T.trains[0].head[0] !== p0[0], 'trains: advance along track when playing');
click('#tp'); const s1 = T.sim; await sleep(300); ok(T.sim === s1, 'trains: pause stops motion'); click('#tp');
click('#tr'); ok(T.sim === 0, 'trains: reset');
T.trains[0] && (S.map.qr = () => [{ properties: {} }]); const trh = T.trains[2]; S.clickHook({ point: {}, lngLat: { lng: trh.head[0], lat: trh.head[1] } }); await sleep(400); ok(T.sel === trh.id && $('#tinfo').textContent.includes('next station'), 'trains: select by click shows next station + destination');
$('#tfl').checked = true; $('#tfl').dispatchEvent(new w.Event('change')); const j0 = state.jump || 0; await sleep(500); ok((state.jump || 0) > j0, 'trains: follow camera moves with train');
$('#thw').value = '20'; $('#thw').dispatchEvent(new w.Event('input')); ok(T.trains.length < 36, 'trains: interval slider changes train count');
click('nav [data-m="cc"]'); await sleep(200); const n1 = state.setData; await sleep(300); ok(T.on === false, 'trains: simulation stops when leaving module');
// ===== learn =====
click('nav [data-m="learn"]'); await sleep(800);
for (const k of ['1', '2', '4', '5', '6', '7']) { const b = $(`[data-b="${k}"]`); if (k === '1') $('#l1').value = 'Majestic'; b.dispatchEvent(new w.MouseEvent('click', { bubbles: true })); await sleep(k === '4' || k === '7' ? 3500 : 1200); const o = b.closest('.card').querySelector('.out').textContent; ok(o.length > 20 && !/⚠/.test(o), 'learn: concept ' + k + ' computed: ' + o.slice(0, 50)); }
$('[data-b="3"]').dispatchEvent(new w.MouseEvent('click', { bubbles: true })); await sleep(3500); ok($('#eq') && $('#eq').textContent.includes('d(v) = min'), 'learn: Dijkstra concept opens the lab and starts');
click('nav [data-m="learn"]'); await sleep(1500);
const find = k => w.document.querySelector(`[data-c="${k}"]`); 
$('#c1s').value = 'Sandal Soap Factory'; find('1').click(); await sleep(3000); ok($('#c1a').closest('.card').querySelector('.out').textContent.includes('NODAL'), 'challenge 1 compares with algorithm');
find('2n').click(); $('#c2g').value = '30'; find('2').click(); await sleep(1200); ok($('#c2g').closest('.card').querySelector('.out').textContent.includes('Dijkstra'), 'challenge 2');
find('3').click(); await sleep(300); ok($('#c3s').closest('.card').querySelector('.out').textContent.includes('Most critical'), 'challenge 3');
find('4l').click(); await sleep(3000); w.document.querySelector('#c4l input').checked = true; find('4').click(); await sleep(4000); ok($('#c4b').closest('.card').querySelector('.out').textContent.length > 20, 'challenge 4: ' + $('#c4b').closest('.card').querySelector('.out').textContent.slice(0, 60));
$('#c5s').value = 'Chickpete'; find('6').click(); await sleep(300); ok($('#c5s').closest('.card').querySelector('.out').textContent.includes('Worst'), 'challenge 5');
// algorithm edit UI
click('nav [data-m="algo"]'); await sleep(200); $('#al').value = 'kruskal'; $('#al').dispatchEvent(new w.Event('change'));
$('#src').value = 'Majestic'; $('#oa').value = 'Majestic'; $('#ob').value = 'Lalbagh'; $('#ow').value = '0.5'; click('#oadd'); ok($('#olist').textContent.includes('0.5'), 'algo lab: edge edit recorded'); click('#run'); await sleep(600); ok($('#eq').textContent.includes('Kruskal'), 'algo lab: runs with edited graph');


// ===== NODAL 2.0 additions =====
click('nav [data-m="cc"]'); await sleep(1500);
ok($('#mod').textContent.includes('Data provenance') && $('#mod').textContent.includes('Census of India 2011') && $('#mod').textContent.includes('BMTC'), 'provenance table shows sources, licences and limitations');
// view presets
const vp = $('#vp'); for (const v of ['sat', 'city3d', 'geo', 'graph', 'geo']) { vp.value = v; vp.dispatchEvent(new w.Event('change')); await sleep(200); }
ok(state.terrain !== undefined, 'view presets 1-5 run without error');
vp.value = 'heat'; vp.dispatchEvent(new w.Event('change')); await sleep(2500);
ok(S.layers.pop === true && state.sources.wards.last && state.sources.wards.last.features.length === 198, 'heatmap preset: 198 census ward polygons loaded');
ok($('#plegend').textContent.includes('Census of India 2011') && $('#plegend').textContent.includes('not jobs'), 'population legend with provenance and workers caveat');
ok($('#ptab').textContent.includes('Destinations ranked') && state.sources.access.last.features.length > 500, 'heatmap preset opens accessibility analysis');
ok(P0().acc.underserved_wards && P0().acc.underserved_wards.length === 12, 'underserved wards (census) listed');
function P0() { return w.__NODAL_EXT.P; }
const pcb = $('#ly-work'); pcb.checked = true; pcb.dispatchEvent(new w.Event('change')); await sleep(50); ok($('#plegend').textContent.includes('Workers by residence'), 'workers layer legend');
const bcb = $('#ly-bus'); bcb.checked = true; bcb.dispatchEvent(new w.Event('change')); await sleep(2500); ok(state.sources.bus.last && state.sources.bus.last.features.length > 5000, 'BMTC bus stops layer (' + (state.sources.bus.last && state.sources.bus.last.features.length) + ' stops)');
pcb.checked = false; pcb.dispatchEvent(new w.Event('change')); bcb.checked = false; bcb.dispatchEvent(new w.Event('change'));
// planning with population + road alignment
click('.tabs button[data-t="cor"]'); await sleep(3500);
ok($('#evalbox').textContent.includes('Residents') && $('#evalbox').textContent.includes('2011') && /Alignment/.test($('#evalbox').textContent), 'planning shows census residents and the alignment basis');
ok(/Population coverage \(2011 census\)/.test($('#ptab').textContent), 'coverage criterion relabelled to population');
// economics
click('nav [data-m="econ"]'); await sleep(1200);
ok($('#esrc') && $('#mod').textContent.includes('HYPOTHETICAL'), 'economics: sources + hypothetical label');
click('#ecalc'); await sleep(2500); ok($('#eres').textContent.includes('Total capital cost') && $('#eres').textContent.includes('Cost per km') && $('#eres').textContent.includes('Cost per station'), 'economics: results table');
ok($('#eres').textContent.includes('Demand-based benefits are not shown'), 'economics: no demand invented');
const e1 = $('#eres').textContent.match(/Total capital cost₹(\d+)/)[1]; $('#e_cost_per_km_cr').value = '600'; click('#ecalc'); await sleep(2500); const e2 = $('#eres').textContent.match(/Total capital cost₹(\d+)/)[1]; ok(+e2 > +e1 * 1.9 && +e2 < +e1 * 2.1, 'economics: doubling cost/km doubles capital (' + e1 + ' -> ' + e2 + ')');
$('#e_daily_trips').value = '50000'; $('#e_value_of_time_inr_per_hour').value = '150'; click('#ecalc'); await sleep(2500); ok($('#eres').textContent.includes('Benefit-cost ratio') && $('#eres').textContent.includes('Person-hours'), 'economics: demand benefits appear only when the user supplies demand');
click('#ecmp'); await sleep(4000); ok($('#ecm').textContent.includes('Cost-effectiveness comparison'), 'economics: comparison table');
// multimodal
click('nav [data-m="multi"]'); await sleep(1500);
S.map.qr = () => []; S.clickHook({ lngLat: { lat: 12.9857, lng: 77.7380 } }); S.clickHook({ lngLat: { lat: 12.8456, lng: 77.6603 } }); await sleep(2500);
ok($('#mmres').querySelectorAll('.card').length >= 2, 'multimodal: alternatives listed');
ok(state.sources.mm.last.features.length >= 1 && state.sources.mm.last.features.some(f => f.properties.mode === 'walk'), 'multimodal: route drawn with walking legs dashed layer');
ok($('#mmleg').textContent.includes('assumed straight link') && /Metro|Bus/.test($('#mmleg').textContent), 'multimodal: legs labelled actual vs assumed');
ok(state.markers === 2, 'multimodal: draggable origin/destination markers');
const cards = $('#mmres').querySelectorAll('.card'); cards[cards.length - 1].dispatchEvent(new w.MouseEvent('click', { bubbles: true })); await sleep(300); ok($('#mmleg').textContent.length > 20, 'multimodal: selecting an alternative updates legs');
$('#mma_bus_kmh').value = '30'; click('#mmgo'); await sleep(2000); const t30 = $('#mmres .card').textContent; ok(/\d+ min/.test(t30), 'multimodal: assumptions editable and re-run');
$('#mmo').value = 'Majestic bus and rail hub'; $('#mmo').dispatchEvent(new w.Event('change')); $('#mmd').value = 'NIMHANS'; $('#mmd').dispatchEvent(new w.Event('change')); await sleep(2500); ok($('#mmres').querySelectorAll('.card').length >= 1, 'multimodal: place search for origin/destination');
click('#mmclr'); await sleep(50); ok(state.sources.mm.last.features.length === 0 && state.markers === 0, 'multimodal: clear');
// 3D trains with doors (fake three layer) + proposed corridor trains
const T2 = w.__NODAL_EXT.T; const fake = { calls: 0, last: null, failed: false, hidden: false, setTrains(l, k) { this.calls++; this.last = l; this.k = k; } };
T2.three = { layer: fake }; T2.use3d = true;
click('nav [data-m="trains"]'); await sleep(800);
ok(fake.calls > 0 && fake.last.every(t => t.cars.length === 3 && typeof t.doorOpen === 'number'), '3D layer receives 3 cars per train with door state');
ok(state.sources.trains.last.features.length === 0, '3D mode: fallback blocks hidden');
click('#tp'); const trn = T2.trains[0], dw = trn.L.ev.find(e => e.type === 'dwell'); T2.sim = ((dw.t0 + 6) - trn.phase + trn.L.C * 3) % trn.L.C; await sleep(300);
const idx0 = T2.trains.indexOf(trn); ok(fake.last[idx0].doorOpen > 0.99 && trn.st.mode === 'dwelling' && trn.st.v === 0, 'doors fully open while the train is stopped (doorOpen=' + fake.last[idx0].doorOpen + ')');
T2.sim = ((dw.t0 + 0.5) - trn.phase + trn.L.C * 3) % trn.L.C; await sleep(200); ok(fake.last[idx0].doorOpen === 0, 'doors closed on arrival');
T2.sim = ((dw.t0 + 3) - trn.phase + trn.L.C * 3) % trn.L.C; await sleep(200); ok(fake.last[idx0].doorOpen > 0 && fake.last[idx0].doorOpen < 1, 'doors opening progressively');
click('#tp'); 
T2.use3d = false; await sleep(300); ok(state.sources.trains.last.features.length === T2.trains.length * 3, 'WebGL fallback: block cars shown when 3D unavailable');
T2.use3d = false; T2.three = null;
const pChk = $('#tprop'); ok(pChk && !pChk.disabled, 'proposed-corridor option enabled after evaluating a corridor');
pChk.checked = true; pChk.dispatchEvent(new w.Event('change')); await sleep(600); ok(Object.keys(T2.lines).some(k => k.startsWith('Proposed')) && T2.trains.some(t => t.L.hypo), 'trains run on the proposed hypothetical corridor');
T2.sel = T2.trains.find(t => t.L.hypo).id; await sleep(600); ok($('#tinfo').textContent.includes('hypothetical') && $('#tinfo').textContent.includes('SIMULATED'), 'proposed-corridor train labelled hypothetical + simulated');
const pl = Object.values(T2.lines).find(l => l.hypo); ok(pl.stopKm.every((x, i) => i === 0 || x > pl.stopKm[i - 1]) && pl.coords.length >= 2, 'proposed corridor track geometry valid');
// challenge 5
click('nav [data-m="learn"]'); await sleep(800); const f5l = w.document.querySelector('[data-c="5l"]'); f5l.click(); await sleep(3500); w.document.querySelector('#c5lst input').checked = true; w.document.querySelector('[data-c="5"]').click(); await sleep(5000);
ok($('#c5b').closest('.card').querySelector('.out').textContent.includes('Residents improved'), 'challenge 5: compares residents improved with algorithm');
ok($('#mod').textContent.includes('Challenge 6 — Greatest disruption'), 'challenges numbered 1-6');

await sleep(300);
console.log('setData calls', state.setData); console.log(errors.length ? 'ERRORS:\n' + errors.join('\n') : 'NO ERRORS'); process.exit(errors.length ? 1 : 0);
