import * as THREE from './vendor/three.module.min.js';

// Original scene. The food texture is a credited, real photograph — no generated food.
export function mountFoodScene() {
  const stage = document.getElementById('food-stage');
  const host = document.getElementById('food-canvas');
  const media = matchMedia('(prefers-reduced-motion: reduce)');
  if (!stage || !host) return;
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'low-power' }); }
  catch { return; } // The HTML photograph remains fully usable without WebGL.
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(43, 1, .1, 50);
  camera.position.z = 8.7;
  scene.add(new THREE.HemisphereLight(0xfffcf1, 0x82351b, 2.4));
  const light = new THREE.DirectionalLight(0xffffff, 3);
  light.position.set(-3, 4, 6);
  scene.add(light);
  const rimLight = new THREE.DirectionalLight(0xffbc76, 1.4);
  rimLight.position.set(4, -2, 3);
  scene.add(rimLight);
  const plate = new THREE.Group();
  scene.add(plate);
  const ceramic = new THREE.MeshStandardMaterial({ color: 0xfff9ed, roughness: .3, metalness: .05 });
  const base = new THREE.Mesh(new THREE.CylinderGeometry(2.61, 2.49, .22, 80), ceramic);
  base.rotation.x = Math.PI / 2;
  plate.add(base);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(2.56, .13, 16, 100), ceramic);
  rim.position.z = .13;
  rim.scale.z = .6;
  plate.add(rim);
  const line = new THREE.Mesh(new THREE.TorusGeometry(2.39, .022, 8, 100), new THREE.MeshStandardMaterial({ color: 0xd8e987, roughness: .5 }));
  line.position.z = .19;
  plate.add(line);
  let ready = false;
  const photo = new Image();
  photo.onload = () => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1024;
    const ctx = canvas.getContext('2d');
    const side = Math.min(photo.naturalWidth, photo.naturalHeight);
    ctx.drawImage(photo, (photo.naturalWidth - side) / 2, (photo.naturalHeight - side) / 2, side, side, 0, 0, 1024, 1024);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = Math.min(renderer.capabilities.getMaxAnisotropy(), 4);
    const surface = new THREE.Mesh(new THREE.CircleGeometry(2.37, 100), new THREE.MeshBasicMaterial({ map: texture }));
    surface.position.z = .19;
    plate.add(surface);
    ready = true;
    render(0);
    stage.classList.add('webgl-ready');
  };
  photo.src = '/gioi-thieu/img/bun-dau.jpg';
  let targetX = 0, targetY = 0, x = 0, y = 0, visible = true;
  function render(time) {
    x += (targetX - x) * .065;
    y += (targetY - y) * .065;
    const moving = !media.matches && !document.body.classList.contains('motion-paused');
    plate.rotation.set(.16 + y * .2, -.18 + x * .25, -.2 + (moving ? Math.sin(time * .0003) * .025 : 0));
    plate.position.y = moving ? Math.sin(time * .00065) * .065 : 0;
    renderer.render(scene, camera);
  }
  function syncMotion() {
    const active = visible && !document.hidden && !media.matches && !document.body.classList.contains('motion-paused');
    renderer.setAnimationLoop(active ? render : null);
    if (!active && ready) render(0);
  }
  const resize = new ResizeObserver(() => {
    const { width, height } = host.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    render(0);
  });
  resize.observe(host);
  stage.addEventListener('pointermove', event => {
    if (event.pointerType === 'touch') return;
    const bounds = stage.getBoundingClientRect();
    targetX = ((event.clientX - bounds.left) / bounds.width - .5) * 2;
    targetY = ((event.clientY - bounds.top) / bounds.height - .5) * 2;
  });
  stage.addEventListener('pointerleave', () => { targetX = targetY = 0; });
  const visibility = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; syncMotion(); });
  visibility.observe(stage);
  document.addEventListener('visibilitychange', syncMotion);
  document.addEventListener('tastoria-motion', syncMotion);
  media.addEventListener('change', syncMotion);
  renderer.domElement.addEventListener('webglcontextlost', event => { event.preventDefault(); renderer.setAnimationLoop(null); stage.classList.remove('webgl-ready'); });
  window.addEventListener('pageshow', syncMotion);
  window.addEventListener('pagehide', event => {
    renderer.setAnimationLoop(null);
    if (event.persisted) return;
    visibility.disconnect(); resize.disconnect();
    scene.traverse(object => { object.geometry?.dispose(); if (object.material) { object.material.map?.dispose(); object.material.dispose(); } });
    renderer.dispose();
  });
  syncMotion();
}
