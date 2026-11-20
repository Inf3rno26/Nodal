// Three.js train models rendered as a MapLibre custom layer. Geometry is in metres (x = right, y = forward, z = up).
// The cars are an enlarged, schematic EMU-style model built from primitives; they are NOT a licensed or surveyed rolling-stock model.
export function mercator(lng, lat) {
  const s = Math.sin(lat * Math.PI / 180);
  return { x: (lng + 180) / 360, y: 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI) };
}
export function buildCar(THREE, color, head) {
  const car = new THREE.Group(), M = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.55, metalness: 0.2, side: THREE.DoubleSide, ...o });
  const box = (w, l, h, mat, x, y, z) => { const m = new THREE.Mesh(new THREE.BoxGeometry(w, l, h), mat); m.position.set(x, y, z); car.add(m); return m; };
  const body = M(0xe9eef5), dark = M(0x1c2735), glass = M(0x203a55, { metalness: 0.6, roughness: 0.2 }), stripe = M(color), doorMat = M(0xbfc9d6);
  box(3.0, 20, 3.4, body, 0, 0, 2.2);                 // body
  box(2.8, 19.6, 0.15, M(0xcfd6df), 0, 0, 3.95);      // roof
  box(2.6, 18, 0.6, dark, 0, 0, 0.5);                 // underframe
  box(3.04, 20.02, 0.35, stripe, 0, 0, 1.55);         // line-colour livery stripe
  car.userData.doors = [];
  for (const sx of [-1, 1]) {
    for (let i = 0; i < 6; i++) { const y = -8 + i * 3.2; if (Math.abs(Math.abs(y) - 5) < 1.3) continue; box(0.06, 1.7, 1.0, glass, sx * 1.52, y, 2.9); }   // windows
    for (const dy of [-5, 5]) for (const leaf of [-1, 1]) {                                                                                      // double-leaf sliding doors
      const m = box(0.08, 0.85, 2.3, doorMat, sx * 1.53, dy + leaf * 0.43, 2.15); car.userData.doors.push({ mesh: m, base: dy + leaf * 0.43, dir: leaf });
    }
  }
  if (head) {
    box(2.7, 0.06, 1.25, glass, 0, 10.02, 3.0);       // windscreen
    for (const sx of [-1, 1]) { const l = box(0.35, 0.08, 0.25, M(0xfff6c9, { emissive: 0xfff2a8, emissiveIntensity: 1 }), sx * 1.0, 10.03, 1.2); l.name = 'headlight'; }
  }
  return car;
}
export function setDoors(car, open) {            // open: 0 (closed) .. 1 (fully open); each leaf slides 0.85 m along the car
  for (const d of car.userData.doors) d.mesh.position.y = d.base + d.dir * open * 0.85;
}
/** matrix placing a car at (lng, lat) with heading `bearing` (radians clockwise from north) and metre-scale `k`. */
export function carMatrix(THREE, lng, lat, bearing, k, out = new THREE.Matrix4()) {
  const m = mercator(lng, lat), unit = 1 / (40075016.686 * Math.cos(lat * Math.PI / 180));   // mercator units per metre
  // local model (x right, y forward, z up) -> rotate in the east-north frame by the compass bearing -> scale to mercator (y points south) -> translate
  const T = new THREE.Matrix4().makeTranslation(m.x, m.y, 0), F = new THREE.Matrix4().makeScale(unit * k, -unit * k, unit * k), R = new THREE.Matrix4().makeRotationZ(-bearing);
  return out.copy(T).multiply(F).multiply(R);
}
export async function createTrainLayer(THREE) {
  const layer = {
    id: 'trains3d', type: 'custom', renderingMode: '3d', cars: [], failed: false,
    onAdd(map, gl) {
      try {
        this.map = map; this.scene = new THREE.Scene(); this.camera = new THREE.Camera();
        this.scene.add(new THREE.AmbientLight(0xffffff, 1.1)); const sun = new THREE.DirectionalLight(0xffffff, 1.3); sun.position.set(0.3, -0.5, 1); this.scene.add(sun);
        this.renderer = new THREE.WebGLRenderer({ canvas: map.getCanvas(), context: gl, antialias: true }); this.renderer.autoClear = false;
        this.root = new THREE.Group(); this.scene.add(this.root); this.pool = [];
      } catch (e) { this.failed = true; console.warn('3D train layer unavailable, using fallback blocks:', e.message); }
    },
    onRemove() { try { this.renderer && this.renderer.dispose(); } catch (e) { /* ignore */ } },
    /** trains: [{lng, lat, bearing, color, selected, doorOpen, cars:[{lng, lat, bearing}]}], k = metre exaggeration */
    setTrains(trains, k) {
      if (this.failed || !this.root) return;
      let n = 0;
      trains.forEach(t => t.cars.forEach((c, ci) => {
        let car = this.pool[n];
        if (!car || car.userData.key !== t.color + (ci === 0)) { if (car) this.root.remove(car); car = buildCar(THREE, new THREE.Color(t.color), ci === 0); car.userData.key = t.color + (ci === 0); car.matrixAutoUpdate = false; this.pool[n] = car; this.root.add(car); }
        car.visible = true; carMatrix(THREE, c.lng, c.lat, c.bearing, k, car.matrix); car.matrixWorldNeedsUpdate = true; setDoors(car, t.doorOpen); n++;
      }));
      for (let i = n; i < this.pool.length; i++) this.pool[i].visible = false;
      this.map && this.map.triggerRepaint();
    },
    render(gl, matrix) {
      if (this.failed || !this.renderer) return;
      this.camera.projectionMatrix = new THREE.Matrix4().fromArray(matrix); this.renderer.resetState(); this.renderer.render(this.scene, this.camera);
    }
  };
  return layer;
}
