# Plan: DSS TrafficSentinel AI — Surveillance & ANPR Dashboard

## Context

The user wants a high-fidelity, 1920×1080 dark-themed desktop surveillance and ANPR traffic control dashboard inspired by Dahua DSS Security Center. The project is a blank-slate React + Vite + Tailwind CSS v4 app. Everything will be built from scratch into the existing shell.

## Aesthetic Direction

- **Stance:** High-tech ops-center. Swiss precision layout with a pure dark-mode palette. No editorial warmth — cold, functional, every pixel earning its place.
- **Fonts:** Inter (Google Fonts) for all text — thin/regular labels, semibold headings, mono-spaced plate numbers via `font-mono`/JetBrains Mono for license plates.
- **Palette (from brief, honored literally):**
  - `--bg`: `#0d1117` (Dark Obsidian canvas)
  - `--panel`: `#161c28` (Dark Charcoal Blue)
  - `--accent`: `#00d2ff` (Neon Cyan)
  - `--border`: `#262f40`
  - `--text`: `#ffffff`
  - `--muted`: `#a0aec0`
- **Spatial UI:** Subtle depth layering — panels slightly elevated from canvas via border + faint shadow, top nav higher z-index, ANPR cards have hover lift effect. Use `backdrop-filter` on overlays for depth.

---

## Files to Create / Modify

### 1. `src/index.css` — Font + Token wiring
- Add `@import url(...)` for Inter (weights 300–700) and JetBrains Mono at top
- Define CSS custom properties for the palette

### 2. `src/App.tsx` — Root layout (4-region grid)
- Grid: `grid-rows-[50px_1fr]` + `grid-cols-[260px_1fr_340px]` scoped to inner area
- Renders: `<TopNav>`, `<LeftSidebar>`, `<VideoViewport>`, `<RightSidebar>`
- State: `activeTab`, `liveClock` (updated every second via `useEffect`)

### 3. `src/components/TopNav.tsx`
- Fixed 50px bar, full-width, z-index 50
- Left: camera icon SVG + "DSS TrafficSentinel AI" wordmark
- Center: 5 nav tabs with active state (cyan bottom border, cyan text), state from prop
- Right: Bell (green badge "0"), Mute, Grid, Clock display, Avatar, window controls (–, □, ×)

### 4. `src/components/LeftSidebar.tsx`
- 260px width, full-height scrollable panel
- Search input with magnifying glass icon
- "Resources" / "Favorites" tab switcher
- Expandable tree: "Current Site (1/1)" → IP node → 3 cameras (Exit selected/active with cyan highlight)
- Accordion: "View Controls" (collapsed)
- Accordion: "Electronic Focus / PTZ" — Zoom slider, Focus slider, "Auto Focus" + "Reset" buttons
- State: expanded nodes, selected camera, accordion open/close

### 5. `src/components/VideoViewport.tsx`
- Flex container, aspect-ratio 16/9 bounding box centered
- Top overlay bar (semi-transparent): stream info left, timestamp center-right, 5 tool icons right
- Center: dark gradient placeholder with subtle road/vehicle silhouette pattern or gradient texture
- Bottom-right floating badge: "STOP" in red or speed indicator
- Bottom toolbar: 1×1 / 2×2 / 3×3 grid switcher buttons, aspect ratio toggle, fullscreen button

### 6. `src/components/RightSidebar.tsx`
- 340px width, full-height
- Top bar: "Pause Refresh" toggle button (state: paused/running), "Clear" button, 4 filter tabs (All / Violations / ANPR / Vehicles)
- Scrollable feed of 5 `<ANPRCard>` components
- `ANPRCard`: cyan "ANPR" tag, source name, timestamp, split layout with plate image thumbnail (styled div showing plate number in mono font) + details (bold plate text, vehicle type, color)

### 7. Sample ANPR event data (inline in RightSidebar.tsx)
5 realistic entries with varied plates, timestamps, vehicle types, and colors.

---

## Implementation Details

### Layout grid (App.tsx)
```
┌─────────────────────────────────────────────────────────┐  ← TopNav (col-span-3, row 1)
│ DSS TrafficSentinel AI   [tabs]   [icons] [clock] [usr] │
├──────────────┬──────────────────────────┬────────────────┤
│ LeftSidebar  │  VideoViewport           │ RightSidebar   │
│ 260px        │  flex-1                  │ 340px          │
│              │  [video overlay top]     │ [ANPR feed]    │
│ [search]     │  [video body]            │ [cards]        │
│ [tree]       │  [video toolbar bot]     │                │
│ [ptz panel]  │                          │                │
└──────────────┴──────────────────────────┴────────────────┘
```

### Spatial depth layers
- Canvas: z-0, `#0d1117`
- Panels: z-10, `#161c28`, `border border-[#262f40]`, `shadow-[0_2px_12px_rgba(0,0,0,0.6)]`
- Top nav: z-50, same panel bg + bottom border
- Overlays (video info bar): z-20, `bg-black/60 backdrop-blur-sm`
- ANPR card hover: `hover:border-[#00d2ff]/50 hover:shadow-[0_0_8px_rgba(0,210,255,0.12)]`

### Live clock
```tsx
const [time, setTime] = useState(new Date());
useEffect(() => {
  const id = setInterval(() => setTime(new Date()), 1000);
  return () => clearInterval(id);
}, []);
```

### Scrollbar styling (index.css)
```css
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #262f40; border-radius: 2px; }
```

---

## Verification
1. Open the preview in the browser — full 4-region layout should render at 1920×1080.
2. Click nav tabs — active tab switches with cyan underline.
3. Click camera tree items — selected item highlights cyan.
4. Clock ticks every second in the top-right.
5. Hover ANPR cards — subtle cyan border glow appears.
6. PTZ accordion opens/closes on click.
