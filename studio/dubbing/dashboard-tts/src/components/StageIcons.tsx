/*
 * Pird: animated six-stage process icons.
 * Source: process-icons.html (six SVG + CSS animations).
 * Animations are gated by the `stage-active` class on each icon container.
 *
 * Per-stage progress bars: each row has a thin track that fills smoothly
 * via requestAnimationFrame. Speed groups:
 *   - Stages 1-3 (Ingesting, Isolating, Extracting) tick at 3x
 *   - Stages 4-6 (Localizing, Synthesizing, Mastering) tick at 1x
 * This matches the user's mental model: "the first half of the pipeline
 * feels fast, the second half feels steady but still alive."
 *
 * Tag labels (i18n keys, with English fallbacks):
 *   stage_ingesting     "Ingesting"      (UPLOAD)
 *   stage_isolating     "Isolating"      (SEPARATE)
 *   stage_extracting    "Extracting"     (TRANSCRIBE)
 *   stage_localizing    "Localizing"     (TRANSLATE)
 *   stage_synthesizing  "Synthesizing"   (RE-VOICE)
 *   stage_mastering     "Mastering"      (ASSEMBLE)
 */
import { useEffect, useRef, useState } from "react";
import "./stage-icons.css";
import { t } from "@/lib/i18n";

type StageId =
  | "ingesting"
  | "isolating"
  | "extracting"
  | "localizing"
  | "synthesizing"
  | "mastering";

type Stage = {
  id: StageId;
  key: string;
  labelFallback: string;
  /** progress threshold (0-100) at which this stage is considered done */
  at: number;
  /**
   * Pird: smooth-fill speed multiplier. Stages 1-3 are 3x (frontend
   * feels "fast"), stages 4-6 are 1x (steady but alive). Tuned to
   * match the user's mental model from the bug report.
   */
  speed: number;
};

const STAGES: Stage[] = [
  { id: "ingesting",    key: "stage_ingesting",    labelFallback: "Ingesting",    at: 10,  speed: 3 },
  { id: "isolating",    key: "stage_isolating",    labelFallback: "Isolating",    at: 30,  speed: 3 },
  { id: "extracting",   key: "stage_extracting",   labelFallback: "Extracting",   at: 50,  speed: 3 },
  { id: "localizing",   key: "stage_localizing",   labelFallback: "Localizing",   at: 70,  speed: 1 },
  { id: "synthesizing", key: "stage_synthesizing", labelFallback: "Synthesizing", at: 90,  speed: 1 },
  { id: "mastering",    key: "stage_mastering",    labelFallback: "Mastering",    at: 100, speed: 1 },
];

/** Returns the index of the stage currently active (0-5), based on progress. */
export function activeStageIndex(progress: number): number {
  if (progress >= 100) return STAGES.length - 1;
  for (let i = 0; i < STAGES.length; i++) {
    const s = STAGES[i];
    if (progress < s.at) {
      if (i === 0) return 0;
      return progress >= STAGES[i - 1].at ? i : i - 1;
    }
  }
  return STAGES.length - 1;
}

/**
 * Pird: the 6 animated SVGs from process-icons.html, packaged as React.
 * Each row also has a per-stage progress bar that fills smoothly.
 *
 * The component maintains its own `internalActive` index that advances
 * automatically when a stage's local bar hits 100% — independent of the
 * server's `progress` poll. This is the "instant handoff" behavior: the
 * moment a bar fills, the next stage lights up and starts ticking.
 */
export default function StageIcons({ activeIndex }: { activeIndex: number }) {
  // Pird: track an internal "active" index that auto-advances when a
  // stage completes locally. We start at the server-reported activeIndex
  // but can only ever advance forward — never go back.
  const [internalActive, setInternalActive] = useState<number>(activeIndex);
  const [autoAdvanceTo, setAutoAdvanceTo] = useState<number | null>(null);

  useEffect(() => {
    // Server-side progress may jump (e.g. from 5% to 30%). If the
    // server's activeIndex is ahead of our internal one, snap forward.
    if (activeIndex > internalActive) {
      setInternalActive(activeIndex);
    }
  }, [activeIndex, internalActive]);

  useEffect(() => {
    if (autoAdvanceTo !== null) {
      setInternalActive(autoAdvanceTo);
      setAutoAdvanceTo(null);
    }
  }, [autoAdvanceTo]);

  // Pird: clamp internal active to the server's "truth" — if the server
  // says we're still on stage 0 (activeIndex=0), we don't auto-advance
  // past it. We only advance UP TO the server's value.
  const displayActive = Math.min(internalActive, Math.max(activeIndex, STAGES.length - 1));

  return (
    <>
      {/* Shared gradients (one per icon that needs them) */}
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
        <defs>
          <linearGradient id="ic1grad" x1="0" y1="0" x2="0" y2="1">
            <stop className="grad-amber" offset="0%" />
            <stop className="grad-teal" offset="100%" />
          </linearGradient>
          <linearGradient id="ic5grad" x1="0" y1="1" x2="0" y2="0">
            <stop className="grad-amber" offset="0%" />
            <stop className="grad-teal" offset="100%" />
          </linearGradient>
        </defs>
      </svg>

      <div className="flex flex-col gap-3">
        {STAGES.map((s, i) => (
          <StageIcon
            key={s.id}
            stage={s}
            isActive={i === displayActive}
            isDone={i < displayActive}
            onLocalComplete={
              i === displayActive && i < STAGES.length - 1
                ? () => setAutoAdvanceTo(i + 1)
                : undefined
            }
          />
        ))}
      </div>
    </>
  );
}

function StageIcon({
  stage,
  isActive,
  isDone,
  onLocalComplete,
}: {
  stage: Stage;
  isActive: boolean;
  isDone: boolean;
  onLocalComplete?: () => void;
}) {
  const label = t(stage.key, stage.labelFallback);

  // Pird: smooth local progress (0-100) for this stage. rAF drives
  // continuous movement; CSS transition on the fill width handles
  // abrupt changes (stage transitions) so the bar never jumps.
  const [localProgress, setLocalProgress] = useState<number>(
    isDone ? 100 : 0,
  );
  const lastActiveRef = useRef<boolean>(isActive);

  useEffect(() => {
    if (isActive && !lastActiveRef.current) {
      setLocalProgress(0);
    }
    if (isDone && !lastActiveRef.current) {
      setLocalProgress(100);
    }
    lastActiveRef.current = isActive;

    if (!isActive) return;

    const baseRatePerSec = 100 / 6;
    const rate = baseRatePerSec * stage.speed;
    let raf = 0;
    let lastTs = performance.now();
    const tick = (ts: number) => {
      const dt = (ts - lastTs) / 1000;
      lastTs = ts;
      setLocalProgress((p) => {
        // Pird: when the bar hits 100%, fire onLocalComplete so the
        // parent (StageIcons) can advance the active index immediately.
        // This is what fixes the "stuck at 100% then wait for the
        // next poll" feeling — the visual handoff is immediate.
        if (p >= 100) {
          if (onLocalComplete) onLocalComplete();
          return 100;
        }
        return p + dt * rate;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [isActive, isDone, stage.speed, onLocalComplete]);

  const label_color = isActive
    ? "text-cyan-300"
    : isDone
    ? "text-emerald-300"
    : "text-ink-400";

  return (
    <div
      className={`stage-icon relative flex flex-col gap-2 p-2 pr-3 rounded-lg transition-all ${
        isActive
          ? "bg-cyan-400/[0.08] ring-1 ring-cyan-400/30"
          : isDone
          ? "bg-emerald-400/[0.04]"
          : ""
      } ${isActive || isDone ? "opacity-100" : "opacity-40"} ${
        isActive ? "stage-active" : ""
      }`}
      role="img"
      aria-label={label}
      title={label}
    >
      <div className="flex flex-row items-center gap-3">
        <svg
          viewBox="0 0 160 160"
          className="w-12 h-12 sm:w-14 sm:h-14 shrink-0"
          fill="none"
        >
          {renderIconFor(stage.id)}
        </svg>
        <div
          className={`text-[11px] sm:text-xs tracking-wider uppercase font-mono ${label_color}`}
        >
          {label}
        </div>
      </div>
      {/* Pird: per-stage progress track. Clean bar without text overlay
          (the percentage lives in the box's top right corner below). */}
      {(isActive || isDone) && (
        <div
          className="relative h-2 w-full rounded-full bg-white/[0.08] overflow-hidden"
          role="progressbar"
          aria-label={`${label} progress`}
          aria-valuenow={Math.round(localProgress)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className={`absolute inset-y-0 left-0 rounded-full ${
              isDone
                ? "bg-emerald-400/70"
                : "bg-gradient-to-r from-brand-400 to-cyan-300"
            }`}
            style={{
              width: `${localProgress}%`,
              transition: "width 0.4s cubic-bezier(0.4, 0, 0.2, 1)",
            }}
          />
        </div>
      )}
      {/* Pird: numeric percentage in the top-right corner of the
          stage box, independent of the bar. Always visible for active
          + done stages so the user sees the value increment smoothly
          (4% → 4.3% → 4.7% → ...). Positioned absolute so it doesn't
          affect the bar's flow. */}
      {(isActive || isDone) && (
        <span
          className={`absolute top-1 right-2 text-base font-mono font-semibold tabular-nums leading-none ${
            isDone ? "text-emerald-300" : "text-cyan-200"
          }`}
        >
          {localProgress.toFixed(1)}%
        </span>
      )}
    </div>
  );
}

/**
 * Pird: dispatches to the right SVG body based on stage id.
 * Each SVG body is the exact markup from process-icons.html, with class
 * names matching the CSS in stage-icons.css.
 */
function renderIconFor(id: StageId) {
  switch (id) {
    case "ingesting":
      return (
        <g className="icon-ingest">
          <line className="ic1-path anim" x1="80" y1="134" x2="80" y2="80" />
          <g className="ic1-vault">
            <rect x="34" y="20" width="92" height="56" rx="14" />
            <line x1="46" y1="36" x2="114" y2="36" />
            <line x1="46" y1="48" x2="114" y2="48" />
            <line x1="46" y1="60" x2="96" y2="60" />
            <circle className="ic1-led anim" cx="104" cy="60" r="3.4" />
          </g>
          <circle className="ic1-ping anim" cx="80" cy="48" r="10" />
          <g className="ic1-file anim">
            <rect className="ic1-file-body" x="66" y="108" width="28" height="30" rx="3" />
            <path className="ic1-file-fold" d="M86 108 L94 116 L86 116 Z" />
            <line className="ic1-file-line" x1="70" y1="122" x2="88" y2="122" />
            <line className="ic1-file-line" x1="70" y1="127" x2="84" y2="127" />
          </g>
        </g>
      );
    case "isolating":
      return (
        <g className="icon-isolate">
          <g className="ic2-combined anim">
            {[29.5, 41.5, 53.5, 65.5, 77.5, 89.5, 101.5, 113.5, 125.5].map((x, i) => {
              const heights = [18, 34, 54, 40, 64, 46, 58, 32, 22];
              return (
                <rect key={i} x={x} y={80 - heights[i] / 2} width="5" height={heights[i]} rx="2.5" />
              );
            })}
          </g>
          <g className="ic2-voice anim">
            {[30.5, 42.5, 54.5, 66.5, 78.5, 90.5, 102.5, 114.5, 126.5].map((x, i) => {
              const heights = [8, 18, 26, 12, 24, 30, 18, 12, 8];
              return (
                <rect key={i} x={x} y={50 - heights[i] / 2} width="3" height={heights[i]} rx="1.5" />
              );
            })}
          </g>
          <g className="ic2-music anim">
            {[30.5, 42.5, 54.5, 66.5, 78.5, 90.5, 102.5, 114.5, 126.5].map((x, i) => {
              const heights = [12, 24, 34, 22, 34, 38, 26, 20, 12];
              return (
                <rect key={i} x={x} y={80 - heights[i] / 2} width="3" height={heights[i]} rx="1.5" />
              );
            })}
          </g>
          <g className="ic2-noise anim">
            {[30.5, 42.5, 54.5, 66.5, 78.5, 90.5, 102.5, 114.5, 126.5].map((x, i) => {
              const heights = [6, 10, 8, 12, 6, 14, 10, 8, 6];
              return (
                <rect key={i} x={x} y={110 - heights[i] / 2} width="3" height={heights[i]} rx="1.5" />
              );
            })}
          </g>
          <rect className="ic2-flash anim" x="78" y="14" width="4" height="132" rx="2" />
        </g>
      );
    case "extracting":
      return (
        <g className="icon-extract">
          <g>
            {[30, 42, 54, 66, 78, 90, 102, 114, 126].map((x, i) => {
              const delays = [0, -0.12, -0.24, -0.36, -0.48, -0.6, -0.72, -0.84, -0.96];
              const heights = [18, 34, 48, 26, 42, 30, 38, 20, 14];
              return (
                <rect
                  key={i}
                  className="ic3-bar anim"
                  style={{ animationDelay: `${delays[i]}s` }}
                  x={x}
                  y={94}
                  width="4"
                  height={heights[i]}
                  rx="2"
                />
              );
            })}
          </g>
          <g>
            {[
              { x: 32, y: 66, w: 78, d: 0 },
              { x: 32, y: 84, w: 60, d: 0.12 },
              { x: 32, y: 102, w: 70, d: 0.24 },
              { x: 32, y: 120, w: 42, d: 0.36 },
            ].map((l, i) => (
              <rect
                key={i}
                className="ic3-line anim"
                style={{ animationDelay: `${l.d}s` }}
                x={l.x}
                y={l.y}
                width={l.w}
                height="6"
                rx="3"
              />
            ))}
          </g>
        </g>
      );
    case "localizing":
      return (
        <g className="icon-localize">
          {[0, 0.09, 0.18, 0.27, 0.36, 0.45].map((delay, i) => {
            const x = 30 + i * 18;
            const rectH = [14, 20, 16, 23, 15, 19][i];
            const circleR = [6.3, 9, 7.2, 10.4, 6.8, 8.6][i];
            return (
              <g key={i} className="ic4-tile anim" style={{ animationDelay: `${delay}s` }}>
                <rect
                  className="ic4-a anim"
                  style={{ animationDelay: `${delay}s` }}
                  x={x}
                  y={80 - rectH / 2}
                  width="8"
                  height={rectH}
                  rx="4"
                />
                <circle
                  className="ic4-b anim"
                  style={{ animationDelay: `${delay}s` }}
                  cx={x + 4}
                  cy={80}
                  r={circleR}
                />
              </g>
            );
          })}
        </g>
      );
    case "synthesizing":
      return (
        <g className="icon-synthesize">
          <g>
            <rect className="ic5-line" x="32" y="120" width="74" height="5" rx="2.5" />
            <rect className="ic5-line" x="32" y="134" width="56" height="5" rx="2.5" />
            <rect className="ic5-line" x="32" y="148" width="64" height="5" rx="2.5" />
          </g>
          <g>
            {[0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3].map((delay, i) => {
              const x = 32 + i * 15;
              const heights = [24, 38, 50, 32, 46, 28, 36];
              return (
                <rect
                  key={i}
                  className="ic5-bar anim"
                  style={{ animationDelay: `${delay}s` }}
                  x={x}
                  y={86 - heights[i]}
                  width="6"
                  height={heights[i]}
                  rx="3"
                />
              );
            })}
          </g>
        </g>
      );
    case "mastering":
      return (
        <g className="icon-master">
          <rect className="ic6-ring anim" x="42" y="62" width="76" height="64" rx="10" />
          <rect className="ic6-video anim" x="45" y="66" width="70" height="17" rx="3" />
          <rect className="ic6-audio anim" x="45" y="84" width="70" height="17" rx="3" />
          <rect className="ic6-voice anim" x="45" y="102" width="70" height="17" rx="3" />
          <path className="ic6-check anim" d="M114 46 L120 52 L132 38" />
        </g>
      );
  }
}