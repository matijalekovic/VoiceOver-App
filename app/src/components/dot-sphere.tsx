import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/**
 * A sphere of dots drawn on a canvas: it turns slowly, ripples like speech while `active`,
 * fills with light from the bottom as `progress` (0–1) rises (a sweeping band when it is
 * null), tilts toward the pointer and can be spun by dragging.
 */
export function DotSphere({
  size = 120,
  active = true,
  progress = null,
  className,
}: {
  size?: number;
  active?: boolean;
  progress?: number | null;
  className?: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  // Read by the animation loop without restarting it.
  const live = useRef({ active, progress });
  live.current = { active, progress };

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    el.width = size * dpr;
    el.height = size * dpr;
    ctx.scale(dpr, dpr);

    // Evenly spread points (Fibonacci sphere).
    const count = Math.round(Math.min(900, Math.max(260, size * 5)));
    const points: [number, number, number][] = [];
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < count; i++) {
      const y = 1 - (i / (count - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      points.push([Math.cos(golden * i) * r, y, Math.sin(golden * i) * r]);
    }

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let ink = "";
    let inkCheckedAt = -1;
    const state = { spin: 0, spinVelocity: 0, tiltX: -0.35, tiltY: 0, targetX: -0.35, targetY: 0, energy: 0, level: 0 };
    let dragging: { x: number; at: number } | null = null;

    const onMove = (e: PointerEvent) => {
      const box = el.getBoundingClientRect();
      const nx = (e.clientX - box.left) / box.width - 0.5;
      const ny = (e.clientY - box.top) / box.height - 0.5;
      state.targetY = nx * 0.9;
      state.targetX = -0.35 + ny * 0.9;
      if (dragging) {
        const now = performance.now();
        const dx = e.clientX - dragging.x;
        state.spin += dx * 0.012;
        state.spinVelocity = (dx * 0.012) / Math.max((now - dragging.at) / 1000, 0.008);
        dragging = { x: e.clientX, at: now };
      }
    };
    const onDown = (e: PointerEvent) => {
      dragging = { x: e.clientX, at: performance.now() };
      el.setPointerCapture(e.pointerId);
    };
    const onUp = () => {
      dragging = null;
    };
    const onLeave = () => {
      state.targetX = -0.35;
      state.targetY = 0;
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.addEventListener("pointerleave", onLeave);

    let frame = 0;
    let last = performance.now();
    const draw = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      const t = now / 1000;
      if (now - inkCheckedAt > 1000) {
        ink = getComputedStyle(el).getPropertyValue("--ink").trim() || "#000";
        inkCheckedAt = now;
      }
      const { active: isActive, progress: p } = live.current;
      // Ease toward the targets so changes never jump.
      state.energy += ((isActive ? 1 : 0.15) - state.energy) * Math.min(dt * 3, 1);
      if (p != null) state.level += (p - state.level) * Math.min(dt * 4, 1);
      state.tiltX += (state.targetX - state.tiltX) * Math.min(dt * 4, 1);
      state.tiltY += (state.targetY - state.tiltY) * Math.min(dt * 4, 1);
      if (!dragging) {
        state.spinVelocity *= Math.pow(0.05, dt); // inertia after a flick
        state.spin += (0.25 + state.energy * 0.35 + state.spinVelocity) * dt;
      }

      const half = size / 2;
      const radius = half * 0.78;
      ctx.clearRect(0, 0, size, size);
      ctx.fillStyle = ink;
      const cy = Math.cos(state.spin + state.tiltY), sy = Math.sin(state.spin + state.tiltY);
      const cx = Math.cos(state.tiltX), sx = Math.sin(state.tiltX);
      // Level of light: a fill from the bottom, or a band sweeping up when progress is unknown.
      const fill = p == null ? null : -1 + 2 * state.level;
      const band = (t * 0.6) % 2.4 - 1.2;
      for (const [x0, y0, z0] of points) {
        // Speech ripple: waves running around and along the sphere, stronger while active.
        const wave =
          Math.sin(y0 * 7 + t * 3.2) * 0.5 + Math.sin(Math.atan2(z0, x0) * 5 - t * 2.4) * 0.5;
        const r = 1 + wave * 0.07 * state.energy;
        let x = x0 * r, y = y0 * r, z = z0 * r;
        [x, z] = [x * cy - z * sy, x * sy + z * cy]; // turn
        [y, z] = [y * cx - z * sx, y * sx + z * cx]; // tilt
        const depth = (z + 1.1) / 2.2; // 0 back, 1 front
        const scale = 1.6 / (2.6 - z); // perspective
        const lit = fill == null ? Math.max(0, 1 - Math.abs(-y - band) * 3) : -y <= fill ? 1 : 0;
        ctx.globalAlpha = (0.12 + 0.55 * depth) * (0.4 + 0.6 * lit);
        const dot = (0.55 + 1.1 * depth + lit * 0.5) * (size / 120);
        ctx.beginPath();
        ctx.arc(half + x * radius * scale, half + y * radius * scale, dot, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      if (!reduceMotion) frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      el.removeEventListener("pointerleave", onLeave);
    };
  }, [size]);

  return (
    <canvas
      ref={canvas}
      aria-hidden
      className={cn("cursor-grab touch-none select-none active:cursor-grabbing", className)}
      style={{ width: size, height: size }}
    />
  );
}
