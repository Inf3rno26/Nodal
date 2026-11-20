import * as THREE from '../frontend/vendor/three.module.js';
import { buildCar, setDoors, carMatrix, mercator, createTrainLayer } from '../frontend/trains3d.mjs';
let fails = 0; const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) fails++; };
const car = buildCar(THREE, new THREE.Color('#8C2877'), true);
ok(car.children.length > 20, 'car model built from ' + car.children.length + ' meshes');
const bb = new THREE.Box3().setFromObject(car), sz = bb.getSize(new THREE.Vector3());
ok(Math.abs(sz.y - 20.1) < 0.4 && Math.abs(sz.x - 3.1) < 0.3 && sz.z > 3.5 && sz.z < 4.6, `car dimensions ${sz.x.toFixed(1)} x ${sz.y.toFixed(1)} x ${sz.z.toFixed(1)} m (realistic metro car)`);
ok(car.userData.doors.length === 8, '8 door leaves (2 doors x 2 leaves x 2 sides)');
const y0 = car.userData.doors.map(d => d.mesh.position.y); setDoors(car, 1); const y1 = car.userData.doors.map(d => d.mesh.position.y);
ok(car.userData.doors.every((d, i) => Math.abs(Math.abs(y1[i] - y0[i]) - 0.85) < 1e-9), 'doors slide 0.85 m when open'); setDoors(car, 0);
ok(car.userData.doors.every((d, i) => Math.abs(d.mesh.position.y - y0[i]) < 1e-9), 'doors return to closed');
setDoors(car, 0.5); ok(car.userData.doors.every((d, i) => Math.abs(Math.abs(d.mesh.position.y - y0[i]) - 0.425) < 1e-9), 'door opening is proportional');
// orientation: local forward (+y) must map to the direction of travel in mercator space for several headings
const A = [77.5946, 12.9716];
for (const [name, B] of [['north', [77.5946, 12.99]], ['east', [77.62, 12.9716]], ['south-west', [77.57, 12.95]], ['north-east', [77.61, 12.99]]]) {
  const a = mercator(...A), b = mercator(...B), d = new THREE.Vector2(b.x - a.x, b.y - a.y).normalize();
  const phi = (B[0] - A[0]) * Math.cos(A[1] * Math.PI / 180), lam = B[1] - A[1]; const bearing = Math.atan2(phi, lam);
  const m = carMatrix(THREE, A[0], A[1], bearing, 1); const f = new THREE.Vector3(0, 1, 0).transformDirection(m); const fv = new THREE.Vector2(f.x, f.y).normalize();
  ok(fv.dot(d) > 0.9999, `heading ${name}: car faces the direction of travel (dot=${fv.dot(d).toFixed(5)})`);
}
// scale: a 20 m car must span 20 m in mercator units
const m1 = carMatrix(THREE, 77.5946, 12.9716, 0, 1); const p0 = new THREE.Vector3(0, -10, 0).applyMatrix4(m1), p1 = new THREE.Vector3(0, 10, 0).applyMatrix4(m1);
const metres = Math.hypot(p1.x - p0.x, p1.y - p0.y) * 40075016.686 * Math.cos(12.9716 * Math.PI / 180); ok(Math.abs(metres - 20) < 0.01, `20 m car spans ${metres.toFixed(3)} m in mercator`);
const pos = new THREE.Vector3().setFromMatrixPosition(m1), mc = mercator(77.5946, 12.9716); ok(Math.abs(pos.x - mc.x) < 1e-12 && Math.abs(pos.y - mc.y) < 1e-12, 'car placed at its mercator coordinate');
const layer = await createTrainLayer(THREE); ok(layer.type === 'custom' && layer.renderingMode === '3d', 'custom layer object');
layer.root = new THREE.Group(); layer.pool = []; layer.setTrains([{ color: '#32D69A', doorOpen: 1, cars: [{ lng: 77.59, lat: 12.97, bearing: 1 }, { lng: 77.591, lat: 12.971, bearing: 1 }, { lng: 77.592, lat: 12.972, bearing: 1 }] }, { color: '#8C2877', doorOpen: 0, cars: [{ lng: 77.6, lat: 12.98, bearing: 0 }] }], 8);
ok(layer.pool.length === 4 && layer.pool.every(c => c.visible), 'layer pools cars for all trains'); layer.setTrains([{ color: '#32D69A', doorOpen: 0, cars: [{ lng: 77.59, lat: 12.97, bearing: 1 }] }], 8);
ok(layer.pool.filter(c => c.visible).length === 1, 'unused pooled cars are hidden');
// failure path: no WebGL -> layer marks itself failed and does not throw
const l2 = await createTrainLayer(THREE); l2.onAdd({ getCanvas() { return {}; } }, null); ok(l2.failed === true, 'WebGL failure falls back gracefully (failed flag)'); l2.setTrains([], 1); l2.render(null, new Array(16).fill(0));
console.log(fails ? fails + ' FAILED' : 'ALL 3D MODEL TESTS PASS'); process.exit(fails ? 1 : 0);
