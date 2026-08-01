# Pird TTS — Design Tokens

## Goals & Non-Goals

**Goals.** Serious, low-density, native-Arabic-aware voice studio. Communicate *professional tooling* — closer to a recording console than a consumer AI toy. RTL by default (Sorani + Iraqi Arabic first-class). Chrome restrained: 1 primary surface, 1 accent, no rainbow gradients. Voice card is the hero of the page.

**Non-Goals.** No neon, no glass-morphism flooding, no celebratory confetti, no AI-clipart hero, no hero gradient text. We are not selling magic; we are presenting a roster of voices an engineer can audition.

---

## Color (semantic → hex)

| Token | Hex | Role |
|---|---|---|
| `--surface-0` | `#0a0a0b` | App background. Near-black, blue-pulled (0.95% B). |
| `--surface-1` | `#111114` | Card / panel base. One step lighter so cards float off the page. |
| `--surface-2` | `#15151a` | Elevated card (e.g. global player). |
| `--surface-3` | `#1c1c22` | Hover / pressed surfaces. |
| `--border-subtle` | `rgba(255,255,255,0.06)` | Hairline between cards and the page. |
| `--border-strong` | `rgba(255,255,255,0.10)` | Focused / hovered card outline. |
| `--text-primary` | `#fafafa` | Display + headings. Soft, not pure white. |
| `--text-secondary` | `#cfcfd3` | Body, descriptions. |
| `--text-muted` | `#7e7e8b` | Captions, meta, checkpoint hashes. |
| `--text-disabled` | `#5a5a68` | Disabled controls. |
| `--accent-primary` | `#38bdf8` | Sky-400 brand. Audio / play / CTA. "Studio console" reading. |
| `--accent-primary-deep` | `#0284c7` | Pressed accent. |
| `--accent-secondary` | `#a855f7` | Purple. Reserved for gradients + waveform end-stop. Never a button bg alone. |
| `--accent-success` | `#34d399` | "your voice" / active tag. |
| `--accent-warning` | `#fbbf24` | Amber banner / destructive confirmation. |
| `--accent-danger` | `#f87171` | Real errors only. |

**Rationale.** ElevenLabs, Murf, Play.ht all default to a near-black surface; we do too, but keep the chip palette *desaturated* (sky, violet, emerald) so voices feel like inventory, not toys. The accent pair (sky → violet) is the only place a gradient is permitted, only for play / waveform / avatar. WCAG: `text-primary` on `surface-0` is 18.4:1; `text-secondary` is 12.1:1. Both pass AAA. `text-muted` is 5.1:1 (AA borderline); `text-disabled` is 3.4:1 (AA fail) — only use for non-essential meta.

---

## Typography

| Role | Font | Size | Line-height | Weight |
|---|---|---|---|---|
| Display | Inter | 30px | 36px (1.20) | 600 |
| Heading | Inter | 24px | 32px (1.33) | 600 |
| Subheading | Inter | 16px | 24px (1.50) | 500 |
| Body | Inter | 14px | 20px (1.43) | 400 |
| Caption | Inter | 12px | 16px (1.33) | 500 |
| Micro | Inter (mono fallback) | 10px | 14px (1.40) | 500 |

**Rationale.** Inter is the dashboard's only face. For Arabic / Kurdish, system-UI falls through — both scripts render well at 16/500. No display face; product is about *content*, not headlines. Tracking is `0`.

---

## Spacing (4px scale)

`4, 8, 12, 16, 20, 24, 32, 40, 48, 64`. Mapped to Tailwind 1–4–6–8–10–12–16. Voice Library uses: `12` (card inner padding-top), `16` (chip gap), `20` (card padding), `24` (header margin-bottom), `32` (grid gap). Half-steps (12, 20) are intentional, not noise. **Never use 14, 18, 22.**

---

## Radius

| Token | Value | Purpose |
|---|---|---|
| `--radius-pill` | `9999px` | Chips, tag pills, language badge. |
| `--radius-sm` | `6px` | Inputs, small buttons. |
| `--radius-md` | `10px` | Buttons, dropdowns. |
| `--radius-lg` | `16px` | Voice cards. Softens the dark surface, keeps the "engineering tool" read. |
| `--radius-xl` | `20px` | Global player, modal sheets. Only the two "elevated" containers. |

---

## Shadow

| Token | Value | Purpose |
|---|---|---|
| `--shadow-sm` | `0 1px 0 0 rgba(255,255,255,0.04) inset` | 1px inner-top highlight on every card. Lifts card off dark page *without* drop shadow. |
| `--shadow-md` | `0 8px 32px -8px rgba(0,0,0,0.6)` | Page-level card elevation. |
| `--shadow-lg` | `0 0 0 1px rgba(56,189,248,0.25), 0 0 24px -4px rgba(56,189,248,0.4)` | Glow used *only* on the active play button — "this is the source of audio now." |
| `--shadow-glass` | `--shadow-sm + --shadow-md` | The combined card shadow. |

**Rationale.** Drop shadows on dark UIs are mush. Inset hairline is our primary elevation primitive — matches "studio console" reference, stays crisp on AMOLED. Brand glow rationed: one element at a time.

---

## Motion

Durations: `100ms` (micro: play-state toggle, chip press), `200ms` (hover, focus ring), `300ms` (page enter, sidebar indicator slide).

Easings: `standard` = `cubic-bezier(0.2, 0, 0, 1)` (Material standard). `decel` = `cubic-bezier(0, 0, 0.2, 1)` (entrances). `accel` = `cubic-bezier(0.4, 0, 1, 1)` (exits).

Spring for sidebar morph: stiffness 320, damping 32, mass 0.8.

List entrance: 30ms stagger, max 12 × 30 = 360ms — under 400ms attention budget.

`prefers-reduced-motion`: disable all entrance stagger + spring; keep only the 200ms hover/focus transitions.

---

## Breakpoints

Tailwind defaults: `sm 640`, `md 768`, `lg 1024`, `xl 1280`, `2xl 1536`. Voice Library grid: `1 col` < sm, `2 col` sm–md, `3 col` lg, `4 col` xl. Sidebar collapses < lg. No custom breakpoints.

---

## Iconography

`lucide-react`. Stroke-based, 1.5–2px stroke, `currentColor`. Icons in nav (16×16), buttons (16×16), table rows (16×16), empty states (64×64). No filled icons anywhere except the play triangle (deliberate focal point on the active button).

Color states: `text-secondary` default → `text-primary` on hover → `accent-primary` when active.

---

## Voice-Specific Tokens

**Voice chip — inactive.** Background `rgba(255,255,255,0.04)`, text `var(--text-secondary)`, border `rgba(255,255,255,0.06)`, pill shape, 10px Inter 600, padding 2px 8px. Used for `#arabic`, `#iq`, `#narrator` tags.

**Voice chip — "your" (active).** Background `rgba(52,211,153,0.15)`, text `#6ee7b7`, no border. Reserved for voices the user has cloned.

**Voice avatar.** 48×48 (card) / 32×32 (logo). Circle. Gradient `linear-gradient(135deg, rgba(56,189,248,0.30), rgba(168,85,247,0.30))`. Border `1px solid rgba(255,255,255,0.08)`. Letter (first char of voice name) at 18px / 600 / `text-primary`. **No deterministic hash-to-color per voice** — names are the primary scan target in an Arabic/Kurdish catalog.

**Audio waveform.** 24 bars, 2px wide, 2px gap. Height varies 30–100% via `30 + (i*37) % 70`. Fill `linear-gradient(to top, #38bdf8, #a855f7)`. Idle opacity 0.4 (static). Active: opacity oscillates `0.6 + sin-modulated 0.2`, transform `scaleY(0.4 + |sin(...)| * 0.8)` at 100ms tick. **The sky→violet gradient is *reserved* for audio signal UI only** — tells the eye "this is sound."

**Language badge.** Pill. `ar-IQ` → `bg: rgba(56,189,248,0.15), text: #7dd3fc`. `ckb` → `bg: rgba(168,85,247,0.15), text: #c084fc`. Two colors map to the two scripts the app actually serves; no third color means no ambiguity.

**Gender tag.** Plain text — no chip. `caption` size, `text-muted`. Renders after `·` separator. Metadata, not a filterable facet.

**Checkpoint hash.** `mono` 10px, `text-disabled`, truncated to first 12 chars + ellipsis. Full hash on hover via `title`. Engineers check, users ignore.

---

## Competitor Takeaways Adopted

- **ElevenLabs (`/app/voices`):** Side-by-side card grid with a single circular avatar, name, one-line description — *no* stat blocks, *no* usage graphs on the card. We adopt the **flat single-row card layout** over Murf's denser multi-stat card.
- **Murf (`/voice-over`):** Strong contrast between page background and card surface using one step of elevation, not a hard border. We adopt **single-step surface elevation** (`surface-0` → `surface-1`) with a hairline border as backup.
- **Play.ht (`/studio/voice-library`):** Language shown as a pill, gender/age as plain text. We adopt **the pill-vs-text distinction** so language reads filterable without making gender feel like a facet.

---

## Files in This System

- `DESIGN.md` — this file
- `design-tokens.json` — JSON Schema 2020-12 machine-readable tokens (3 palettes)
- `design-preview.html` — self-contained 1200×900 visual reference; opens in any browser

---

## Critical Action List (from audit + slop-check)

1. **Audio button accessibility.** Add `aria-label={Preview ${v.name}}` and `aria-pressed={previewingId === v.id}` to each card's play button. Add `aria-label="Search voices"` to the search input and language select. (`VoiceLibraryPage.tsx:133,77,87`)
2. **Waveform animation thrash.** `GlobalPlayer.tsx:170-171` uses `Date.now()` in render → 60×/sec re-renders. Move to CSS keyframe + `animation-play-state: running/paused` toggled by `active`.
3. **Lighting-mode parity.** Add `darkMode: 'class'` to `tailwind.config.js:4`. Add a real light palette — current `dark:` variants are no-ops (`dark:bg-ink-900/40` after `bg-ink-900/40`).
4. **Drop the violet/sky AI-default palette** in favor of brand-specific accent (current `accent-500: #a855f7` is Tailwind stock violet).
5. **Replace hardcoded-initial avatar circles** (`VoiceLibraryPage.tsx:114`, `VoicePickerModal.tsx:95`, `GeneratePage.tsx:435,519`, `TopNav.tsx:171`) with: language code + a fixed brand identity mark, or a small 1-second pre-cache waveform thumbnail.
6. **Unround the voice library.** `rounded-2xl` cards → `rounded-md`. `rounded-full` play buttons → `rounded-md`. Voice library is a tool panel, not a feature card.
7. **Strip entrance staggers from grids.** `VoiceLibraryPage.tsx:106-110` 30ms × 12 = 360ms per render — gratuitous when re-rendering on filter change.
8. **Consolidate `border-white/[0.06]`** (35+ occurrences) into a single `--divider` token and surface-role components.
