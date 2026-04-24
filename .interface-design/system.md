# vmUI Design System

> Source of truth for all UI decisions. Read this before writing any component.
> Established across sessions 013–016 of the vmUI project.

---

## Intent

**Who:** Developers, technical users, and AI enthusiasts managing local LLM inference on Apple Silicon. They're at a desk or remote into a machine. They came from another app (Cursor, Claude, an agentic system) that needed an endpoint, or they're deciding which model to run. They are not casual users — they understand tokens, quantization, memory pressure.

**What they must do:**
1. Know instantly whether their inference server is running and how to connect to it
2. Switch, load, or download a model with minimal friction
3. Compare models for their specific use case before committing to a download
4. Manage multiple machines from one place

**How it should feel:** Quiet authority. A terminal that grew a face. Dense but not cramped — every element earns its space. It should feel like it was built by someone who runs models daily, not someone who read about dashboards.

---

## Product Domain

**Domain concepts:** inference endpoints, model weights, quantization (int4/int8/qat), unified memory, tokens/sec, VRAM pressure, MLX backend, Apple Silicon, Thunderbolt, fleet management, swarms (future).

**Color world:** This product lives in the space of glowing terminal text on dark aluminium, the blue-white light of a server rack, the amber warning LEDs on overloaded hardware, the phosphorescent green of a healthy status indicator, copper traces on a circuit board. These colors belong here — they don't belong on a SaaS pricing page.

**Signature element:** The unified memory arc gauge in the sidebar — a silicon-blue SVG semicircle showing how much of the Mac's shared memory is in use. It fills to copper when under pressure. This element only makes sense for Apple Silicon, where GPU and CPU share the same pool. No other product has this exact problem to solve.

---

## Technology

- **Framework:** Vue 3 + Vite + TypeScript
- **State:** Pinia
- **Router:** Vue Router 4
- **Charts:** Chart.js + vue-chartjs
- **No CSS framework** — all styling from this token system
- **Target:** Served as static files from FastAPI during Streamlit transition; Electron-embeddable for Kilroy merger

---

## Navigation Structure

```
Sidebar
├── [Logo] vmUI
├── [Machines] — fleet switcher (local + remote)
│   └── + Add machine
├── [Memory Arc Gauge] — signature element, per active machine
├── Serve          ← home / primary page
├── Models
└── Settings
    ── (divider)
    └── Test Chat  ← utility, visually separated
Footer: version · status dot
```

**Pages:**
- **Serve** — endpoint URL/model ID copy fields, server start/stop, metrics (active requests, queued, t/s, memory), server configuration (collapsible), server logs (collapsible)
- **Models** — tabs: Library | Find | Benchmark | *(Swarms — future Kilroy placeholder)*
- **Settings** — sections: Fleet | Preferences | Storage | *(Kilroy Platform — future placeholder)*
- **Test Chat** — utility panel, visually separated in nav

---

## Token System

### Primitives (never use raw hex in components — always use semantic tokens below)

```css
/* Graphite scale */
--g-950: #080809   /* near-black base */
--g-900: #1C1C1E   /* surface */
--g-800: #2C2C2E   /* elevated */
--g-700: #3A3A3C   /* overlay */
--g-600: #48484A
--g-500: #636366
--g-400: #8E8E93
--g-300: #AEAEB2
--g-200: #C7C7CC
--g-100: #E5E5EA
--g-050: #F5F5F7

/* Silicon Blue — brand */
--si-700: #3D4A8F
--si-600: #4C5BAD
--si-500: #5B6AD0   /* primary accent */
--si-400: #7A87DB
--si-300: #9AA3E6
--si-200: #BFC5F0

/* Copper — warning / pressure */
--cu-600: #B45309
--cu-500: #D97706
--cu-400: #F59E0B
--cu-300: #FCD34D

/* Phosphor — success / healthy */
--ph-500: #22C55E
--ph-400: #4ADE80
--ph-300: #86EFAC

/* Critical — error / danger */
--cr-500: #EF4444
--cr-300: #FCA5A5
```

### Semantic tokens (dark mode defaults)

```css
/* Backgrounds */
--bg-base:     var(--g-950)   /* page canvas */
--bg-surface:  var(--g-900)   /* cards, sidebar */
--bg-elevated: var(--g-800)   /* inputs, toolbar, hover states */
--bg-overlay:  var(--g-700)   /* dropdowns, tooltips */

/* Borders — always rgba, never solid hex */
--bd-subtle:   rgba(255,255,255,.05)   /* softest — row separators */
--bd-default:  rgba(255,255,255,.09)   /* card borders */
--bd-emphasis: rgba(255,255,255,.16)   /* hover/active borders */
--bd-focus:    var(--si-500)           /* focus rings */

/* Text hierarchy — all four levels used */
--tx-primary:   var(--g-100)   /* headlines, values, active labels */
--tx-secondary: var(--g-300)   /* body text, nav items */
--tx-tertiary:  var(--g-400)   /* supporting text */
--tx-muted:     var(--g-500)   /* labels, captions, placeholders */

/* Accent */
--ac-primary:  var(--si-500)
--ac-hover:    var(--si-400)
--ac-bg:       rgba(91,106,208,.10)   /* active nav / selected state fill */
--ac-border:   rgba(91,106,208,.22)   /* active nav / selected state border */

/* Arc gauge */
--arc-track: #2C2C2E
```

### Light mode overrides

```css
[data-theme="light"] {
  --bg-base:     #F2F2F7
  --bg-surface:  #FFFFFF
  --bg-elevated: #F2F2F7
  --bg-overlay:  #E5E5EA
  --bd-subtle:   rgba(0,0,0,.06)
  --bd-default:  rgba(0,0,0,.11)
  --bd-emphasis: rgba(0,0,0,.20)
  --tx-primary:  #1C1C1E
  --tx-secondary:#3A3A3C
  --tx-tertiary: #636366
  --tx-muted:    #8E8E93
  --ac-bg:       rgba(91,106,208,.07)
  --ac-border:   rgba(91,106,208,.18)
  --arc-track:   #D1D1D6
}
```

---

## Typography

```css
--font-sans:    -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif
--font-display: -apple-system, BlinkMacSystemFont, "SF Pro Display", system-ui, sans-serif
--font-mono:    "SF Mono", "JetBrains Mono", ui-monospace, monospace
```

**Why SF Pro system stack:** This tool runs on Apple Silicon Macs. The OS UI uses SF Pro. Matching it makes vmUI feel native — like Activity Monitor or Instruments, not a web widget. The monospace SF Mono is used for all data values (URLs, model IDs, token counts, GB figures) because these are exact strings, not prose.

**Type scale:**
| Role | Size | Weight | Notes |
|------|------|--------|-------|
| Page title / topbar | 15px | 600 | letter-spacing: -.3px |
| Section title (uppercase label) | 10–11px | 700 | letter-spacing: .07em, uppercase |
| Body / nav | 13–13.5px | 500 | |
| Form label (uppercase) | 11px | 700 | letter-spacing: .06em, uppercase |
| Metric value | 22px | 700 | monospace, letter-spacing: -.5px |
| Data / mono | 11.5–13px | 400–500 | monospace |
| Caption / sub | 11px | 400 | tx-muted |
| Badge / pill | 11px | 600–700 | letter-spacing: .06em, uppercase |

---

## Spacing

Base unit: **4px**. All spacing in multiples.

```
--sp-1:  4px
--sp-2:  8px
--sp-3:  12px
--sp-4:  16px
--sp-5:  20px
--sp-6:  24px
--sp-8:  32px
--sp-10: 40px
```

**Card padding:** `--sp-4` to `--sp-5` horizontal, `--sp-4` vertical.
**Page padding:** `--sp-6` all sides.
**Topbar height:** 46px.
**Sidebar width:** 224px (collapses to 0 below 720px).

---

## Depth Strategy

**Borders-only.** No drop shadows. Elevation is communicated through:
1. Background color steps (base → surface → elevated → overlay)
2. Border opacity steps (subtle → default → emphasis)
3. Focus rings (box-shadow: 0 0 0 3px rgba(91,106,208,.12) — the only permitted shadow)

**Rule:** If you're adding `box-shadow` for anything other than focus, stop.

---

## Border Radius

```
--r-sm:   4px   /* inputs, buttons, small chips */
--r-md:   6px   /* most interactive elements */
--r-lg:   10px  /* cards, panels, table-cards */
--r-xl:   14px  /* large modals */
--r-pill: 9999px /* status pills, badges, filter chips */
```

---

## Component Patterns

### Buttons

Four variants. One size modifier.

```
.btn-primary   — background: ac-primary, color: #fff, border: si-600
.btn-secondary — background: bg-elevated, color: tx-secondary, border: bd-default
.btn-danger    — background: rgba(cr-500,.08), color: cr-300, border: rgba(cr-500,.2)
.btn-ghost     — background: transparent, border: transparent

.btn-sm — padding: 5px 10px, font-size: 12px
default — padding: 7px 14px, font-size: 13px
```

### Status Pill

```html
<span class="status-pill running|stopped">
  <span class="status-pill-dot"></span>Running
</span>
```
Running: ph-400 text, ph-500 glow dot. Stopped: tx-muted. Uppercase, letter-spacing .06em.

### Badges

```
.badge-active   — ph-400 text, ph-500 border tint
.badge-queued   — si-300 text, si-500 border tint
.badge-getting  — cu-300 text, cu-400 border tint (downloading)
.badge-offline  — tx-muted
.badge-error    — cr-300 text, cr-500 border tint
```

### Model Tags (mtag)

```
.mtag-chat      — si-300
.mtag-coding    — cu-300
.mtag-reasoning — purple (#C4B5FD)
.mtag-vision    — cyan (#67E8F9)
.mtag-quant     — tx-muted (neutral — quantization info)
```

### Fit Tags

Inline colored text (no background):
```
fit-perfect — ph-400  "● Perfect fit"
fit-good    — ph-400  "● Good fit"
fit-tight   — cu-400  "◐ Tight"
fit-no      — cr-500  "✗ Too large"
```

### Filter Chips (toolbar)

```
default: bg-elevated, bd-default, tx-tertiary
hover:   bd-emphasis, tx-secondary
active:  ac-bg, ac-border, si-300, font-weight 600
```
Size: padding 4px 12px, r-pill, 12px font.

### Input / Select

```
background: bg-elevated   ← inset, darker than surface
border: bd-default
focus: border bd-focus + box-shadow 0 0 0 3px rgba(91,106,208,.12)
font-size: 13px
padding: 7px 12px
```

### Tab Bar

```
Tab bar: border-bottom bd-default
Active tab: si-300 text, si-500 bottom border 2px, margin-bottom -1px
Inactive: tx-tertiary, hover tx-secondary
Font: 13px, weight 500
```

### Collapsible Section

```
border: bd-default, r-lg
header: bg-surface, hover bg-elevated, padding sp-3 sp-5
body: bg-base (one level below surface), border-top bd-subtle
chevron: rotates 180° when open (transition .18s)
```

### Library Model Card (lib-card)

Row layout: `[status dot] | [identity: name + path + tags] | [size + badge + actions]`
- Name row: model shortname + inline copy icon button
- Path row: full HF path + inline copy icon button (monospace, tx-muted)
- Tags row: mtag chips + fit-tag
- Active model: ac-bg background fill
- Hover: rgba(255,255,255,.012) — barely perceptible

### Endpoint Fields (serve page)

2×2 grid of inset fields:
```
.endpoint-field: bg-elevated, bd-subtle, r-md, padding sp-3 sp-4
.field-label:    uppercase, 10px, tx-muted
.field-value:    monospace, 12.5px, tx-primary
Copy button:     bg-overlay, bd-default, r-sm, 11px
```

### Metric Cards

4-column grid (collapses 2-col at 1100px):
```
background: bg-surface, border bd-default, r-lg, padding sp-4
label: uppercase 10px tx-muted
value: monospace 22px font-weight 700 letter-spacing -.5px
sub:   11px tx-muted
Memory card gets a 5px progress track (si-500 fill, turns cu-500 under pressure)
```

### Memory Arc Gauge (signature)

SVG semicircle. Path: `M 10 65 A 50 50 0 0 1 110 65`, viewBox `0 0 120 72`.
- Track stroke: `--arc-track`
- Fill stroke: `--si-500` → transitions to `--cu-500` above 75% pressure
- stroke-dasharray: 157 (full arc). stroke-dashoffset computed from usage %: `offset = 157 - (157 * pct)`
- stroke-width: 9, stroke-linecap: round
- Center text: usage GB (monospace 17px, tx-primary), "of X GB" (9.5px tx-muted)
- Below gauge: active model name (11px tx-tertiary, truncated)

### Download Queue Card

Shown only when downloads are active. `bg-surface, bd-default, r-lg`.
Each row: `[name + HF ID + progress track + pct text] | [badge]`
Progress track: 4px height, cu-500 fill (copper = in-progress activity).
`badge-getting` or `badge-queued`.

### Charts

**Horizontal bar chart:** label (140px fixed) | track (flex, 8px, r-pill) | value (56px right-aligned mono)
Colors: si-500 primary, cu-500 secondary comparisons.

**Radar chart:** SVG polygon. si-500 fill at 0.2 opacity, si-500 stroke. Second model: cu-500.

**Bar chart (benchmark):** standard Chart.js vertical bars.

### Benchmark Configure Panel

Toggle button: secondary style, turns `si-300` text + `si-500` border when open.
Panel: 3-column grid (bg-elevated, bd-subtle, r-lg, sp-5 padding).
Columns: Performance params | Quality suite sample sizes | Charts & output toggles.
Sample size chips: Quick / Standard / Full — pill style, single-select per suite.

### Use-Case Analysis (Benchmark tab)

Horizontal chip row: each chip = emoji icon + label.
```
Selected: ac-bg, ac-border, si-300
Default:  bg-elevated, bd-default, tx-secondary
```
Result card: bg-surface, ac-border border, r-lg. Shows winner model, explanation text, key metric pills.

---

## Layout Patterns

### Sidebar
- `background: bg-surface` — same hue as cards, border-right bd-default separates from canvas
- Sections divided by bd-subtle bottom borders
- Machine switcher: top section
- Arc gauge: middle section (signature)
- Nav: flex-1, fills remaining space
- Footer: version + status dot, pinned to bottom

### Machine Item
```
default: transparent bg, transparent border
hover:   bg-elevated
active:  ac-bg, ac-border
```
Status dot: 7px circle. running = ph-500 + glow. stopped = g-600. warning = cu-400.

### Topbar
46px height, border-bottom bd-subtle. `[title (flex:1)] [engine version] [update btn] [theme toggle]`

### Responsive
- ≤ 1100px: metric grid 2-col, charts 1-col
- ≤ 1000px: endpoint grid 1-col, two-col forms 1-col
- ≤ 720px: sidebar hidden (drawer pattern needed in Vue)

---

## Machine / Fleet Context

The currently selected machine is the context for all pages. Switching machine re-fetches all data. This drives: the arc gauge, all metrics, the model library, server status.

Machine states:
- `running` — server active, model loaded
- `stopped` — reachable but server off
- `warning` — high memory pressure or connection issues
- `offline` — unreachable

Local machine is always first. Remote machines show IP/hostname + RAM.

---

## API Contract (mgmt_server, port 8502)

All requests from the Vue app target the mgmt server. Base URL is configurable (local: `http://127.0.0.1:8502`, remote: user-configured).

Key endpoints:
```
GET  /status                         → server running, model, uptime, t/s
GET  /memory/stats                   → total_gb, used_gb, percent, pressure
GET  /models                         → list of cached models
POST /models/download                → { model_id } → starts download
GET  /models/download_status/{id}    → { status, progress, error }
POST /server/start                   → { model_id, config }
POST /server/stop
POST /server/restart
GET  /benchmark/results
POST /benchmark                      → start benchmark run
```

---

## Kilroy Integration Notes

- vmUI will eventually merge into Kilroy (Electron + Vue)
- Reserve: **Swarms** tab in Models nav (empty, hidden until enabled)
- Reserve: **Kilroy Platform** section in Settings (empty, hidden until enabled)
- No Kilroy UI surfaces in vmUI today — just placeholder slots
- When merging: MachineItem, MemoryArcGauge, LibCard, EndpointCard are the most reusable components

---

## Roadmap / Future Features

These are confirmed user-requested features, not yet built. Design decisions should leave room for them.

### In-Progress / Near-Term (fix before or during JS migration)
- **Connection Info placement** — move below Server Configuration on the Serve page (Bug 2c, deprioritized)
- **Overview redesign elements** (deferred to JS UI):
  - Load a model directly from the Serve/home page
  - Unified Memory gauge at top of page (not buried)
  - Model recommendation wizard — asks what you want AI to do, recommends a model + config

### Models — Benchmark Tab
- **Multi-model batch benchmarking** — select a group of models, run the same benchmark config against all of them in one go, then get a comparison table + charts. This is the primary reason Benchmark is a tab inside Models, not a standalone page.
- **Leaderboard suite imports** — import and run benchmark suites used by reputable model leaderboards:
  - GSM8K (math / grade-school reasoning)
  - HumanEval (code generation)
  - MMLU (multidisciplinary knowledge)
  - MMLU-Pro
  - Additional: HellaSwag, ARC, TruthfulQA, etc.
- **Use-case analysis** — after benchmarking, user picks their use case (agentic, research, personal, business, images/vision) and the UI recommends the best model from the results with an explanation. Mockup has the chip + analysis card pattern for this.
- **Export** — save benchmark results as CSV, view run history across sessions

### Navigation / Update Indicator
- **Update available badge** in sidebar footer — small indicator when a new vmUI version is available, with one-click update + restart button (currently requires terminal)

### Fleet / Settings
- **Machine naming** — give each remote machine a human name (e.g., "Mac Studio", "Home MacBook") stored in local config
- **Multiple remote servers** — currently only one remote machine is supported. Settings → Fleet needs to support N machines with add/edit/remove
- **Auto-discovery** — client machine discovers a vmUI server on the local network automatically (mDNS / Bonjour), pulls optimal connection config without manual IP entry
- **Thunderbolt direct connect** — already labelled correctly as of v0.3.32; future: detect and explain the performance advantage of Thunderbolt vs Wi-Fi for remote access

### Kilroy Platform Integration (Future — not in vmUI today)
- **Swarms tab** in Models — create and access LLM swarms via the Kilroy platform. Tab slot is reserved in the nav, empty until Kilroy integration ships.
- **Kilroy Platform section** in Settings — account, swarm management, platform config. Section slot reserved, empty until integration ships.
- vmUI will eventually merge into Kilroy (Electron + Vue). All components should be written with that extraction in mind.

### Test Chat Evolution
- Currently: utility panel for quick endpoint testing
- Future: may stay as-is or be absorbed into Kilroy's chat experience at merge time
- Should not grow into a primary feature — keep it as a developer test tool

---

## What Not To Do

- No drop shadows except focus rings
- No gradients
- No more than one accent color in a component (si-500 OR cu-500, not both decoratively)
- No large border radius on small elements (r-pill only on pills/badges/chips)
- No OS-native `<select>` where custom styling is needed — build a custom dropdown
- Don't use raw hex in component CSS — always reference a semantic token
- Don't add navigation items without a reserved Kilroy note if they're for future use
