# Kill dark mode, fix weather chart for light mode

**Date:** 2026-04-12
**Status:** Approved — ready for implementation plan

## Problem

Dark mode in the digest email isn't working out. The light-mode render also has a bug: the weather chart renders with black temperature bars and grey-on-light text because `modules/weather_display.py` hardcodes dark-palette colors (`#252525`, `#1e1e1e`, `#2a2a2a`, `#b0ada8`). See reference screenshot (provided in-conversation 2026-04-12) showing Logan, UT weather row with solid black bars on the light background.

## Goal

1. Remove the dark-mode code path from the email template so only the light palette ships.
2. Fix the weather chart so it reads correctly on the light background.
3. Preserve the CSS variable infrastructure so dark mode can be re-added later by dropping in one `@media` block (no broader refactor needed to revive it).
4. While touching these files, apply targeted simplifications (mono-label base class, weather display helpers).

Non-goals: new dark-mode implementation; visual redesign of the weather chart layout; unrelated refactors.

## Scope

Two files change:

- `templates/email_template.py` — CSS + JS deletions, one new base class.
- `modules/weather_display.py` — replace hardcoded dark colors with `var(--wx-*, <light fallback>)`; extract two small helpers.

Tests that assert on specific hex color strings will be updated to match new values. No other test changes.

## Part 1 — `templates/email_template.py`

### Deletions

Delete these blocks entirely. Keep the `:root { ... }` light palette as the single source of truth. Two `--wx-*` values inside `:root` are retuned for tick/swatch visibility — see Part 2.

| What | Lines (approx) | Reason |
|---|---|---|
| Flash-prevention `<script>` in `<head>` | 24–27 | Reads `data-theme`; no longer meaningful. |
| `@media (prefers-color-scheme: dark) { :root:not(...) { ... } }` | 90–149 | Dark palette override. |
| `[data-theme="dark"] { ... }` | 151–208 | JS-driven dark override. |
| `[data-theme="light"] { ... }` | 210–267 | Redundant with `:root`. |
| `.theme-bar`, `.theme-btn`, `.theme-btn:hover` CSS rules | 274–277 | Styles for deleted toggle button. |
| Theme-toggle injection `<script>` at bottom of `<body>` | 595–640 | Injected toggle button + matchMedia listener. |
| Docstring bullets referencing dark mode | 3–8 | Stale documentation. |

### Additions / modifications

- **New `.mono-label` base class** in the "Layout" section (right after `body`/`h1-3`/`.wrapper`). It carries the shared monospace uppercase declarations:
  ```css
  .mono-label {
    font-family: 'Courier New', monospace;
    font-weight: 600;
    text-transform: uppercase;
  }
  ```
- **Individual label classes keep their specific `font-size`, `color`, `letter-spacing`, and context-specific properties** (margin, padding, border-radius). They lose only the shared three declarations above. Affected classes:
  - `.header-date`, `.spiritual-ref`, `.sec-label`, `.wim-label`, `.fr-label`, `.seam-sub`, `.scan-voice`, `.cal-date`, `.tag`, `.mkt-label`
- **HTML markup** uses `class="mono-label <specific>"` on those elements so both rules apply. Update the Jinja template usages.
- **Updated docstring** drops dark-mode references; keeps Gmail/Proton compatibility note.

Note on `letter-spacing`: values differ per class (1px / 1.5px / 2px), so it stays on the specific class, not on `.mono-label`.

## Part 2 — `modules/weather_display.py`

### Replace hardcoded dark colors with themed values

All color strings below use `var(--wx-*, <light-fallback>)` form so the `:root` palette drives them and future dark mode can override via one `@media` block. The light fallbacks match `:root` values and are used by email clients that don't support CSS variables.

| Location | Current | New |
|---|---|---|
| Chart bar background | `background:#252525` | `background:var(--wx-grid, #d8d5d0)` |
| Precip bar background | `background:#1e1e1e` | `background:var(--wx-grid, #d8d5d0)` |
| Row separator border | `border-bottom:1px solid #2a2a2a` | `border-bottom:1px solid var(--border, #e5e2dd)` |
| Day-name text | `color:#b0ada8` | `color:var(--wx-label, #555)` |
| Lo-temp text | `color:#5a7aa0` | `color:var(--wx-lo, #4a6a90)` |
| Hi-temp text | `color:#d09050` | `color:var(--wx-hi, #c07830)` |
| Right-col / legend muted text | `color:#888582` | `color:var(--wx-label-dim, #888)` |
| Header fallback `color:var(--wx-label, #b0ada8)` | dark fallback | `color:var(--wx-label, #555)` |
| Header fallback `color:var(--wx-label-dim, #888582)` | dark fallback | `color:var(--wx-label-dim, #888)` |
| Legend "Forecast Hi" dot swatch | `background:#d09050` | `background:var(--wx-hi, #c07830)` |
| Legend "Forecast Lo" dashed swatch | `border-top:1px dashed #5a7aa0` | `border-top:1px dashed var(--wx-lo, #4a6a90)` |
| Legend "Normal" swatch | `background:rgba(100,160,100,0.45)` | `background:var(--wx-normal, rgba(80,140,80,0.45))` |
| Legend "Record" swatch | `background:rgba(211,47,47,0.45)` | `background:var(--wx-record, rgba(192,57,43,0.45))` — note: value rebalanced for light bg visibility |
| Legend "Precip" swatch | `background:#5b9bd5` | `background:var(--wx-precip, #5b9bd5)` |
| Temp gradient on bar | `linear-gradient(to right, rgba(90,122,160,0.35), rgba(208,144,80,0.40))` | unchanged — reads on light-grey bar |
| Normal tick color | `background:rgba(100,160,100,0.45)` | `background:var(--wx-normal, rgba(80,140,80,0.45))` |
| Record tick color | `background:rgba(211,47,47,0.35)` | `background:var(--wx-record, rgba(192,57,43,0.35))` |
| AQI legend "##" placeholders | hardcoded hex | keep hex — these are regulatory AQI colors, not themed |

### CSS var check

The `:root` block in `email_template.py` already defines all `--wx-*` variables used above:
`--wx-bg`, `--wx-hi`, `--wx-lo`, `--wx-normal`, `--wx-record`, `--wx-precip`, `--wx-snow`, `--wx-thunder`, `--wx-frz`, `--wx-grid`, `--wx-label`, `--wx-label-dim`. `--border` is also defined and used widely in the template.

Two `:root` values get retuned because the old light values (`--wx-normal: rgba(80,140,80,0.18)`, `--wx-record: rgba(0,0,0,0.04)`) are too subtle as thin ticks on a light-grey bar. These vars are only used by the weather chart, so nothing else is affected:

| Var | Old (`:root`) | New (`:root`) |
|---|---|---|
| `--wx-normal` | `rgba(80,140,80,0.18)` | `rgba(80,140,80,0.45)` |
| `--wx-record` | `rgba(0,0,0,0.04)` | `rgba(192,57,43,0.35)` |

### Simplifications

- **New helper `_tick_html(pct: float, color: str) -> str`** — collapses the four near-duplicate tick div blocks (`normal_lo_tick`, `normal_hi_tick`, `record_lo_tick`, `record_hi_tick`) in `_build_chart_html`. Each callsite becomes one line.
- **New helper `_legend_item(swatch_html: str, label: str) -> str`** — wraps the repeated `<span style="display:inline-flex;align-items:center;gap:3px;">...</span>` pattern used for every legend entry. `_build_legend_html` becomes a flat list of `_legend_item(...)` calls.

## Part 3 — Tests

- `tests/` likely contains color-string assertions for the weather chart. Update any tests that check for `#252525`, `#1e1e1e`, `#2a2a2a`, `#b0ada8`, `#5a7aa0`, `#d09050`, `#888582`, or the `rgba(100,160,100,...)` / `rgba(211,47,47,...)` tick values. Update to match the new `var(--wx-*, fallback)` strings.
- No new test coverage required — this is a visual/color change, not a behavior change.
- Run the full test suite under Docker (per project convention — see `CLAUDE.md`/memory on Docker-only execution) before considering the task complete.

## Part 4 — Acceptance

- Open a dry-run HTML render in a browser on a light system: temperature bars read as light-grey with visible gradient, labels legible, ticks visible, legend swatches match chart colors.
- No remaining references to `data-theme`, `prefers-color-scheme`, `theme-bar`, or `theme-btn` anywhere in `templates/` or `modules/`.
- Existing tests pass. Updated tests assert the new color strings.
- To revive dark mode later: a developer can add one `@media (prefers-color-scheme: dark) { :root { /* --wx-* + --bg-* + --text-* overrides */ } }` block to `:root` and the entire template (including the weather chart) themes correctly — no code changes required in `weather_display.py`.

## Out of scope

- New dark-mode implementation
- Visual redesign of weather chart layout (table structure, row heights, legend order)
- Unrelated CSS refactors (tag-class merging, scan-item/seam-item/weekend-item consolidation, inlining class styles into weather_display)
- Changes to any other section of the email
