// three.js models drawn inside the MapLibre map (a "custom layer"): real-looking docking stations
// (base plate, dock posts, one bike per docked bike, a kiosk lit in the status colour) and a
// delivery van that drives its route and faces where it is going. Models are drawn 14x life
// size (SCALE) so they stay readable at map zoom. Nothing here is computed from the statistics:
// the bike counts, statuses and van position all come from the frames.
import * as THREE from 'three'
import maplibregl from 'maplibre-gl'

const SCALE = 14                      // models are drawn 14x life size so they read at map zoom
const DOCK_GAP = 0.85                 // metres between docks (life size)
const STATUS = { ok: 0x3ddc84, back: 0x3ddc84, sig: 0xff4d4d, oos: 0xffb020, fix: 0x4da3ff }

// shared materials and geometries (one copy, many meshes)
const mat = {
  plate: new THREE.MeshStandardMaterial({ color: 0x2a3036, roughness: 0.9 }),
  post: new THREE.MeshStandardMaterial({ color: 0x8c98a4, metalness: 0.6, roughness: 0.4 }),
  frame: new THREE.MeshStandardMaterial({ color: 0x1e88e5, metalness: 0.3, roughness: 0.5 }),
  tyre: new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.8 }),
  seat: new THREE.MeshStandardMaterial({ color: 0x222222 }),
  kiosk: new THREE.MeshStandardMaterial({ color: 0x3a434c, metalness: 0.4, roughness: 0.5 }),
  vanBody: new THREE.MeshStandardMaterial({ color: 0xf4f4f0, roughness: 0.45, metalness: 0.15 }),
  vanStripe: new THREE.MeshStandardMaterial({ color: 0xffc400, roughness: 0.5 }),
  glass: new THREE.MeshStandardMaterial({ color: 0x1b2a3a, metalness: 0.8, roughness: 0.15 }),
  lightbar: new THREE.MeshStandardMaterial({ color: 0xff9800, emissive: 0xff7a00, emissiveIntensity: 1.2 }),
  head: new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff3c0, emissiveIntensity: 1 }),
  tail: new THREE.MeshStandardMaterial({ color: 0xff2020, emissive: 0xaa0000, emissiveIntensity: 0.8 }),
  rim: new THREE.MeshStandardMaterial({ color: 0xb0b8c0, metalness: 0.8, roughness: 0.3 }),
}
const geo = {
  wheel: new THREE.TorusGeometry(0.33, 0.045, 8, 20),
  tube: new THREE.CylinderGeometry(0.025, 0.025, 1, 6),
  post: new THREE.BoxGeometry(0.12, 0.9, 0.12),
  vanWheel: new THREE.CylinderGeometry(0.38, 0.38, 0.26, 18),
  vanRim: new THREE.CylinderGeometry(0.2, 0.2, 0.27, 12),
}

function tube(a, b, material = mat.frame) {
  const m = new THREE.Mesh(geo.tube, material)
  const va = new THREE.Vector3(...a)
  const vb = new THREE.Vector3(...b)
  m.position.copy(va).add(vb).multiplyScalar(0.5)
  m.scale.set(1, va.distanceTo(vb), 1)
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), vb.clone().sub(va).normalize())
  return m
}

// one city bike, life size, facing +Z (out of the dock), wheels in the YZ plane
function bike() {
  const g = new THREE.Group()
  for (const z of [-0.52, 0.52]) {
    const w = new THREE.Mesh(geo.wheel, mat.tyre)
    w.rotation.y = Math.PI / 2
    w.position.set(0, 0.36, z)
    g.add(w)
  }
  const rear = [0, 0.36, -0.52]
  const front = [0, 0.36, 0.52]
  const seatPost = [0, 0.95, -0.15]
  const head = [0, 0.95, 0.4]
  const crank = [0, 0.36, 0]
  g.add(tube(rear, seatPost), tube(seatPost, head), tube(head, front), tube(crank, seatPost), tube(crank, rear), tube(crank, head))
  g.add(tube([-0.25, 1.08, 0.42], [0.25, 1.08, 0.42], mat.post), tube(head, [0, 1.08, 0.42], mat.post))
  const seat = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.05, 0.26), mat.seat)
  seat.position.set(0, 1.0, -0.17)
  g.add(seat)
  return g
}

// a docking station with `capacity` docks in two back-to-back rows, and a kiosk at one end
function station(capacity) {
  const g = new THREE.Group()
  const perRow = Math.ceil(capacity / 2)
  const len = perRow * DOCK_GAP + 1.6
  const plate = new THREE.Mesh(new THREE.BoxGeometry(len, 0.12, 3.6), mat.plate)
  plate.position.set(len / 2 - 0.8, 0.06, 0)
  g.add(plate)
  const bikes = []
  for (let d = 0; d < capacity; d++) {
    const row = d < perRow ? 0 : 1
    const x = (d % perRow) * DOCK_GAP
    const side = row === 0 ? -1 : 1
    const post = new THREE.Mesh(geo.post, mat.post)
    post.position.set(x, 0.55, side * 0.25)
    g.add(post)
    const b = bike()
    b.position.set(x, 0.12, side * 0.95)
    if (side < 0) b.rotation.y = Math.PI
    g.add(b)
    bikes.push(b)
  }
  // kiosk with a lit screen and a beacon on top
  const kx = -1.1
  const k = new THREE.Mesh(new THREE.BoxGeometry(0.45, 2.0, 0.6), mat.kiosk)
  k.position.set(kx, 1.12, 0)
  g.add(k)
  const screenMat = new THREE.MeshStandardMaterial({ color: 0x3ddc84, emissive: 0x3ddc84, emissiveIntensity: 0.9 })
  const screen = new THREE.Mesh(new THREE.BoxGeometry(0.47, 0.6, 0.45), screenMat)
  screen.position.set(kx, 1.5, 0)
  g.add(screen)
  const beaconMat = new THREE.MeshStandardMaterial({ color: 0x3ddc84, emissive: 0x3ddc84, emissiveIntensity: 1.4 })
  const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.28, 16, 12), beaconMat)
  beacon.position.set(kx, 2.45, 0)
  g.add(beacon)
  g.userData = { bikes, screenMat, beaconMat, beacon }
  return g
}

// a delivery van, life size (about 5.6 m long), facing +X
function van() {
  const g = new THREE.Group()
  const box = (w, h, d, m, x, y, z) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m)
    mesh.position.set(x, y, z)
    g.add(mesh)
    return mesh
  }
  box(4.0, 2.1, 2.0, mat.vanBody, -0.6, 1.45, 0)            // cargo box
  box(1.5, 1.45, 1.96, mat.vanBody, 2.05, 1.12, 0)          // cab
  box(0.06, 0.75, 1.7, mat.glass, 2.83, 1.55, 0)            // windscreen
  box(0.9, 0.6, 2.02, mat.glass, 2.0, 1.55, 0)              // cab side windows
  box(4.02, 0.3, 2.02, mat.vanStripe, -0.6, 1.15, 0)        // company stripe
  box(5.6, 0.35, 2.04, mat.plate, 0.15, 0.5, 0)             // bumper / sill line
  box(0.5, 0.14, 1.6, mat.lightbar, 1.9, 1.92, 0)           // amber light bar on the cab
  for (const z of [-0.65, 0.65]) {
    box(0.05, 0.18, 0.3, mat.head, 2.82, 0.95, z)           // headlights
    box(0.05, 0.25, 0.2, mat.tail, -2.62, 1.0, z * 1.2)     // tail lights
  }
  for (const x of [1.85, -1.75]) {
    for (const z of [-1.0, 1.0]) {
      const w = new THREE.Mesh(geo.vanWheel, mat.tyre)
      w.rotation.x = Math.PI / 2
      w.position.set(x, 0.38, z)
      g.add(w)
      const r = new THREE.Mesh(geo.vanRim, mat.rim)
      r.rotation.x = Math.PI / 2
      r.position.set(x, 0.38, z)
      g.add(r)
    }
  }
  return g
}

// metres east and north of an origin (accurate enough over a few kilometres)
function enu(lon, lat, lon0, lat0) {
  return [(lon - lon0) * 111320 * Math.cos((lat0 * Math.PI) / 180), (lat - lat0) * 110540]
}

export function makeModelLayer() {
  const state = { origin: null, key: '', stations: [], van: null }
  let scene, camera, renderer, map, vanModel, sun, ambient
  const groups = {}

  const layer = {
    id: 'models-3d',
    type: 'custom',
    renderingMode: '3d',
    onAdd(m, gl) {
      map = m
      camera = new THREE.Camera()
      scene = new THREE.Scene()
      ambient = new THREE.AmbientLight(0xffffff, 1.1)
      scene.add(ambient)
      sun = new THREE.DirectionalLight(0xffffff, 2.2)
      sun.position.set(40, 80, 30)
      scene.add(sun)
      const fill = new THREE.DirectionalLight(0x9fc3ff, 0.8)
      fill.position.set(-30, 40, -50)
      scene.add(fill)
      vanModel = van()
      vanModel.scale.setScalar(SCALE)
      vanModel.visible = false
      scene.add(vanModel)
      renderer = new THREE.WebGLRenderer({ canvas: m.getCanvas(), context: gl, antialias: true })
      renderer.autoClear = false
    },
    render(gl, matrix) {
      if (!state.origin) return
      const o = state.origin
      const merc = maplibregl.MercatorCoordinate.fromLngLat([o.lon, o.lat], 0)
      const s = merc.meterInMercatorCoordinateUnits()
      const rotX = new THREE.Matrix4().makeRotationAxis(new THREE.Vector3(1, 0, 0), Math.PI / 2)
      const l = new THREE.Matrix4().makeTranslation(merc.x, merc.y, merc.z).scale(new THREE.Vector3(s, -s, s)).multiply(rotX)
      camera.projectionMatrix = new THREE.Matrix4().fromArray(matrix).multiply(l)
      // a signalling station's beacon pulses
      const t = performance.now() / 1000
      let pulsing = false
      for (const g of Object.values(groups)) {
        const sig = g.userData.cls === 'sig'
        g.userData.beaconMat.emissiveIntensity = sig ? 0.6 + 1.4 * Math.abs(Math.sin(t * 4)) : 1.2
        pulsing = pulsing || sig
      }
      renderer.resetState()
      renderer.render(scene, camera)
      if (pulsing) map.triggerRepaint()
    },
  }

  // stations: [{id, lon, lat, capacity, bikes, cls}], van: {lon, lat, heading (radians) | null, visible}
  function update(stations, vanState) {
    if (!scene || !stations.length) return
    const key = stations.map((s) => `${s.id}:${s.capacity}`).join('|')
    if (key !== state.key) {
      for (const id of Object.keys(groups)) { scene.remove(groups[id]); delete groups[id] }
      state.key = key
      state.origin = {
        lon: stations.reduce((a, s) => a + s.lon, 0) / stations.length,
        lat: stations.reduce((a, s) => a + s.lat, 0) / stations.length,
      }
      for (const s of stations) {
        const g = station(s.capacity)
        g.scale.setScalar(SCALE)
        const [e, n] = enu(s.lon, s.lat, state.origin.lon, state.origin.lat)
        const len = (Math.ceil(s.capacity / 2) * DOCK_GAP + 1.6) * SCALE
        g.position.set(e - len / 2 + 0.8 * SCALE, 0, -n)   // centred on the station point
        scene.add(g)
        groups[s.id] = g
      }
    }
    for (const s of stations) {
      const g = groups[s.id]
      if (!g) continue
      g.userData.bikes.forEach((b, j) => { b.visible = j < s.bikes })
      const c = STATUS[s.cls] ?? STATUS.ok
      g.userData.cls = s.cls
      g.userData.screenMat.color.setHex(c); g.userData.screenMat.emissive.setHex(c)
      g.userData.beaconMat.color.setHex(c); g.userData.beaconMat.emissive.setHex(c)
    }
    if (vanState && Number.isFinite(vanState.lon)) {
      const [e, n] = enu(vanState.lon, vanState.lat, state.origin.lon, state.origin.lat)
      vanModel.position.set(e, 0, -n)
      if (vanState.heading !== null && vanState.heading !== undefined) vanModel.rotation.y = vanState.heading
      vanModel.visible = vanState.visible
    } else if (vanModel) {
      vanModel.visible = false
    }
    map?.triggerRepaint()
  }

  // time-of-day lighting: sun colour (hex string), sun and ambient intensity
  function setLight(color, sunIntensity, ambientIntensity) {
    if (!sun) return
    sun.color.set(color)
    sun.intensity = sunIntensity
    ambient.intensity = ambientIntensity
    map?.triggerRepaint()
  }

  return { layer, update, setLight }
}
