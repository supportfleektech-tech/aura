/* AURA Orb — functional system-state visualization (Three.js/WebGL + 2D fallback). */
import { useEffect, useRef, useState } from "react";
import type * as THREE from "three";
import type { OrbState } from "./api";

const COLORS: Record<OrbState, { core: number; glow: number; speed: number; pulse: number }> = {
  idle: { core: 0x38bdf8, glow: 0xa855f7, speed: 0.35, pulse: 0.06 },
  listening: { core: 0x22d3ee, glow: 0x818cf8, speed: 1.6, pulse: 0.22 },
  thinking: { core: 0xa855f7, glow: 0x38bdf8, speed: 2.4, pulse: 0.12 },
  retrieving: { core: 0x34d399, glow: 0x38bdf8, speed: 2.0, pulse: 0.16 },
  working: { core: 0x60a5fa, glow: 0xe879f9, speed: 1.8, pulse: 0.18 },
  seeing: { core: 0xe879f9, glow: 0x38bdf8, speed: 2.2, pulse: 0.2 },
  waiting_approval: { core: 0xfbbf24, glow: 0xf472b6, speed: 0.9, pulse: 0.3 },
  success: { core: 0x34d399, glow: 0x22d3ee, speed: 0.8, pulse: 0.1 },
  warning: { core: 0xfbbf24, glow: 0xfb923c, speed: 1.0, pulse: 0.24 },
  error: { core: 0xf87171, glow: 0xef4444, speed: 2.8, pulse: 0.3 },
  offline: { core: 0x475569, glow: 0x1e293b, speed: 0.12, pulse: 0.03 },
};

export default function Orb({ state, levelRef, size = 300 }: { state: OrbState; levelRef?: React.MutableRefObject<number>; size?: number }) {
  const mount = useRef<HTMLDivElement>(null);
  const stateRef = useRef(state);
  const [fallback, setFallback] = useState(true);
  stateRef.current = state;

  useEffect(() => {
    const el = mount.current;
    if (!el) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) { setFallback(true); return; }
    let cancelled = false;
    let dispose: (() => void) | undefined;
    setFallback(true);
    import("three").then((THREE) => {
    if (cancelled) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    } catch { setFallback(true); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    renderer.setSize(size, size);
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const cam = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    cam.position.z = 5.2;
    scene.add(new THREE.AmbientLight(0x8899ff, 0.7));
    const key = new THREE.PointLight(0x66ccff, 30, 30); key.position.set(4, 3, 4); scene.add(key);
    const rim = new THREE.PointLight(0xcc66ff, 24, 30); rim.position.set(-4, -2, 3); scene.add(rim);

    const group = new THREE.Group();
    scene.add(group);
    const coreGeo = new THREE.SphereGeometry(1.25, 48, 48);
    const coreMat = new THREE.MeshPhysicalMaterial({
      color: 0x0b1530, metalness: 0.35, roughness: 0.25,
      emissive: 0x1d4ed8, emissiveIntensity: 0.55, transparent: true, opacity: 0.92,
    });
    const core = new THREE.Mesh(coreGeo, coreMat);
    group.add(core);

    const wire = new THREE.Mesh(
      new THREE.SphereGeometry(1.34, 24, 18),
      new THREE.MeshBasicMaterial({ color: 0x67e8f9, wireframe: true, transparent: true, opacity: 0.28 })
    );
    group.add(wire);

    const rings: THREE.Mesh[] = [];
    [[1.75, 0.011, 0.5, 0.2], [1.95, 0.008, -0.4, 1.1], [2.15, 0.006, 0.9, -0.6]].forEach(([r, tube, rx, rz], i) => {
      const m = new THREE.Mesh(
        new THREE.TorusGeometry(r as number, tube as number, 12, 120),
        new THREE.MeshBasicMaterial({ color: i % 2 ? 0xe879f9 : 0x38bdf8, transparent: true, opacity: 0.75 })
      );
      m.rotation.x = rx as number; m.rotation.z = rz as number;
      group.add(m); rings.push(m);
    });

    // particles
    const N = 420;
    const pos = new Float32Array(N * 3);
    const seed = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1), rr = 1.5 + Math.random() * 1.1;
      pos[i * 3] = rr * Math.sin(ph) * Math.cos(th);
      pos[i * 3 + 1] = rr * Math.cos(ph);
      pos[i * 3 + 2] = rr * Math.sin(ph) * Math.sin(th);
      seed[i] = Math.random() * Math.PI * 2;
    }
    const pGeo = new THREE.BufferGeometry();
    pGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const pMat = new THREE.PointsMaterial({ color: 0x93c5fd, size: 0.035, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false });
    const points = new THREE.Points(pGeo, pMat);
    group.add(points);

    // aura sprite glow
    const cv = document.createElement("canvas"); cv.width = cv.height = 128;
    const g2 = cv.getContext("2d")!;
    const grad = g2.createRadialGradient(64, 64, 4, 64, 64, 64);
    grad.addColorStop(0, "rgba(120,180,255,0.85)"); grad.addColorStop(0.5, "rgba(150,100,255,0.28)"); grad.addColorStop(1, "rgba(0,0,0,0)");
    g2.fillStyle = grad; g2.fillRect(0, 0, 128, 128);
    const glowTex = new THREE.CanvasTexture(cv);
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false }));
    glow.scale.set(6.4, 6.4, 1);
    scene.add(glow);

    // base disc
    const disc = new THREE.Mesh(
      new THREE.RingGeometry(1.5, 2.4, 64),
      new THREE.MeshBasicMaterial({ color: 0x7c3aed, transparent: true, opacity: 0.35, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false })
    );
    disc.rotation.x = -Math.PI / 2.35; disc.position.y = -2.15;
    scene.add(disc);

    let raf = 0, t = 0, visible = true;
    const io = new IntersectionObserver((es) => { visible = es[0].isIntersecting; });
    io.observe(el);
    const tCore = new THREE.Color(), tGlow = new THREE.Color();

    const frame = () => {
      raf = requestAnimationFrame(frame);
      if (!visible || document.hidden) return;
      const cfg = COLORS[stateRef.current] || COLORS.idle;
      const mic = stateRef.current === "listening" ? (levelRef?.current || 0) * 0.6 : 0;
      t += 0.016 * (0.6 + cfg.speed);
      const breathe = 1 + Math.sin(t * (1 + cfg.speed)) * (cfg.pulse * 0.5) + mic * 0.35;
      group.scale.setScalar(breathe);
      core.rotation.y += 0.004 * cfg.speed;
      wire.rotation.y -= 0.006 * cfg.speed; wire.rotation.x += 0.002 * cfg.speed;
      rings[0].rotation.z += 0.008 * cfg.speed; rings[1].rotation.z -= 0.006 * cfg.speed; rings[2].rotation.z += 0.005 * cfg.speed;
      points.rotation.y += 0.0016 * (1 + cfg.speed);
      const parr = (pGeo.attributes.position as THREE.BufferAttribute).array as Float32Array;
      for (let i = 0; i < N; i += 3) {
        parr[i * 3 + 1] += Math.sin(t * 2 + seed[i]) * 0.0009 * (1 + cfg.speed);
      }
      pGeo.attributes.position.needsUpdate = true;
      tCore.setHex(cfg.core); tGlow.setHex(cfg.glow);
      const k = 0.06;
      (coreMat.emissive as THREE.Color).lerp(tCore, k);
      (wire.material as THREE.Material as unknown as { color: THREE.Color }).color.lerp(tGlow, k);
      (pMat.color as THREE.Color).lerp(tGlow, k);
      (rings[0].material as THREE.MeshBasicMaterial).color.lerp(tGlow, k);
      (rings[1].material as THREE.MeshBasicMaterial).color.lerp(tCore, k);
      glow.material.opacity = 0.55 + Math.sin(t * 2) * 0.12 + mic * 0.5;
      if (stateRef.current === "error") group.position.x = (Math.random() - 0.5) * 0.05;
      else group.position.x *= 0.9;
      renderer.render(scene, cam);
    };
    frame();

    setFallback(false);
    dispose = () => {
      cancelAnimationFrame(raf);
      io.disconnect();
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.geometry) m.geometry.dispose();
        const mt = (m as unknown as { material?: THREE.Material | THREE.Material[] }).material;
        if (Array.isArray(mt)) mt.forEach((x) => x.dispose()); else if (mt) mt.dispose();
      });
      glowTex.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
    }).catch(() => { if (!cancelled) setFallback(true); });
    return () => { cancelled = true; dispose?.(); };
  }, [size]);

  const placeholder = () => {
    const c = COLORS[state] || COLORS.idle;
    const hex = `#${c.core.toString(16).padStart(6, "0")}`;
    return (
      <div className="orb2d" style={{ width: size, height: size, ["--oc" as string]: hex }}>
        <div className="orb2d-core" />
        <div className="orb2d-ring r1" /><div className="orb2d-ring r2" /><div className="orb2d-ring r3" />
      </div>
    );
  };
  return <div ref={mount} className="orb3d" style={{ width: size, height: size }} aria-label={`AURA state: ${state}`} role="img">{fallback && placeholder()}</div>;
}
