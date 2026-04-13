# Kill Dark Mode + Fix Weather Chart for Light Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the dark-mode code path from the email template, fix the weather chart's hardcoded dark colors so it reads on a light background, and apply targeted simplifications (`.mono-label` base class, weather display helpers).

**Architecture:** Keep the `:root { --* }` CSS variable system as the single theme source of truth. Delete the dark-mode machinery (`@media prefers-color-scheme`, `[data-theme="*"]` blocks, toggle JS). Swap hardcoded dark colors in `modules/weather_display.py` for `var(--wx-*, <light-fallback>)` form so future dark-mode revival needs only one new `@media` block. Extract two small helpers for tick + legend rendering.

**Tech Stack:** Python, Jinja2, inline HTML/CSS, pytest, Docker.

**Spec:** `docs/superpowers/specs/2026-04-12-kill-dark-mode-design.md`

---

## File Map

- **Modify:** `templates/email_template.py` — delete dark-mode CSS + JS, retune two `:root` vars, add `.mono-label` base class, refactor 8 class usages
- **Modify:** `modules/weather_display.py` — swap hardcoded dark colors for `var(--wx-*, fallback)`, extract `_tick_html` and `_legend_item` helpers
- **Modify:** `tests/test_weather_integration.py` — update two rgba color assertions to match new values
- **Modify:** `README.md` — remove Dark Mode section, update weather chart CSS note
- **No changes:** test fixtures, `stages/prepare_weather.py`, `stages/assemble.py`

---

## Test Command Convention

Per `AGENTS.md`, always run tests inside Docker:

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/ -v --tb=short
```

For targeted runs, append a file or `-k` filter. Never run `pytest` on the host.

---

### Task 1: Retune two `:root` vars for light-bg tick visibility

The existing `--wx-normal: rgba(80,140,80,0.18)` and `--wx-record: rgba(0,0,0,0.04)` in the light `:root` are too subtle to serve as thin ticks. Bump opacities and shift record color.

**Files:**
- Modify: `templates/email_template.py` (around lines 79–80, inside `:root { ... }`)

- [ ] **Step 1: Update `--wx-normal` value**

Find this line in the `:root { ... }` block (near line 79):

```css
--wx-normal:     rgba(80,140,80,0.18);
```

Replace with:

```css
--wx-normal:     rgba(80,140,80,0.45);
```

- [ ] **Step 2: Update `--wx-record` value**

Find this line (near line 80):

```css
--wx-record:     rgba(0,0,0,0.04);
```

Replace with:

```css
--wx-record:     rgba(192,57,43,0.35);
```

- [ ] **Step 3: Verify the template still renders**

Run the lint/template import test:

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/test_lint.py tests/test_assemble.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add templates/email_template.py
git commit -m "style(email): retune --wx-normal/--wx-record for light-bg tick visibility"
```

---

### Task 2: Delete dark-mode CSS blocks

Remove the three color-override blocks and the toggle-button CSS.

**Files:**
- Modify: `templates/email_template.py`

- [ ] **Step 1: Delete the `@media (prefers-color-scheme: dark)` block**

Find and delete the entire block starting at:

```css
  /* ── Dark palette — system preference (Proton Mail / Apple Mail) ── */
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
```

…through its closing `}` and the closing `}` of the `@media` rule (approximately lines 90–149). The block ends with the inner `}` for `:root:not(...)` and the outer `}` for the `@media` rule.

- [ ] **Step 2: Delete the `[data-theme="dark"]` block**

Find and delete:

```css
  /* ── Dark palette — explicit JS override (browser only) ──── */
  [data-theme="dark"] {
```

…through its closing `}` (approximately lines 151–208).

- [ ] **Step 3: Delete the `[data-theme="light"]` block**

Find and delete:

```css
  /* ── Light override — lets a dark-system user switch back ── */
  [data-theme="light"] {
```

…through its closing `}` (approximately lines 210–267). This block is redundant with `:root`.

- [ ] **Step 4: Delete the `.theme-bar` + `.theme-btn` CSS rules**

Find and delete these three rules (near lines 274–277):

```css
  /* Theme toggle bar — injected by JS, invisible in email clients */
  .theme-bar { padding: 6px 32px; text-align: right; background: var(--bg-chrome); border-bottom: 1px solid rgba(255,255,255,0.05); }
  .theme-btn { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; background: transparent; border: 1px solid var(--border); color: var(--text-muted); padding: 4px 10px; border-radius: 3px; cursor: pointer; }
  .theme-btn:hover { color: var(--text); border-color: var(--text-muted); }
```

- [ ] **Step 5: Verify no remaining dark-mode CSS references**

```bash
grep -nE "prefers-color-scheme|data-theme|theme-bar|theme-btn" templates/email_template.py
```

Expected: no matches (empty output). If anything matches, delete the matching block.

- [ ] **Step 6: Run the full test suite**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/ -v --tb=short
```

Expected: all tests pass. Nothing in tests depends on these CSS selectors.

- [ ] **Step 7: Commit**

```bash
git add templates/email_template.py
git commit -m "refactor(email): remove dark-mode CSS color blocks and toggle styles"
```

---

### Task 3: Delete dark-mode JavaScript

Remove both the flash-prevention script in `<head>` and the toggle-injection script at the bottom of `<body>`.

**Files:**
- Modify: `templates/email_template.py`

- [ ] **Step 1: Delete the flash-prevention script**

Find and delete (near lines 24–27):

```html
<!-- Flash prevention: read localStorage before first paint so browser never flashes wrong theme -->
<script>
(function(){try{var t=localStorage.getItem('md-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();
</script>
```

- [ ] **Step 2: Delete the toggle-injection script**

Find and delete the entire block starting at:

```html
<!-- Browser-only toggle: injected by JS so it never appears as a dead button in email clients -->
<script>
(function() {
```

…through its closing `</script>` tag (approximately lines 595–640). The block is the complete IIFE that builds the theme-bar, wires the click handler, and listens on `matchMedia`.

- [ ] **Step 3: Update the module docstring**

Find the docstring at the top of `templates/email_template.py`:

```python
"""HTML email template for the Morning Digest.

Uses Jinja2 for rendering. The template is designed for Gmail/Proton Mail compatibility:
- CSS custom properties for theming (supported in modern email clients)
- @media (prefers-color-scheme: dark) for automatic dark mode in Proton Mail / Apple Mail
- JS-injected toggle for the browser dry-run HTML; stripped by email clients so no dead button
- System fonts with web-safe fallbacks
"""
```

Replace with:

```python
"""HTML email template for the Morning Digest.

Uses Jinja2 for rendering. The template is designed for Gmail/Proton Mail compatibility:
- CSS custom properties in :root drive all theming (supported in modern email clients)
- System fonts with web-safe fallbacks
"""
```

- [ ] **Step 4: Verify no remaining dark-mode references in the template**

```bash
grep -nE "prefers-color-scheme|data-theme|md-theme|matchMedia|theme-bar|theme-btn" templates/email_template.py
```

Expected: no matches.

- [ ] **Step 5: Run the full test suite**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add templates/email_template.py
git commit -m "refactor(email): remove dark-mode flash-prevention and toggle scripts"
```

---

### Task 4: Add `.mono-label` base class and refactor 8 usages

Consolidate the repeated `font-family: 'Courier New', monospace; font-weight: 600; text-transform: uppercase;` declarations across 8 mono-style label classes into a single `.mono-label` base class. Each class keeps its specific `font-size`, `letter-spacing`, `color`, and context-specific properties.

`.header-date` is deliberately excluded because it has no `font-weight: 600` — leaving it as-is preserves its lighter visual weight.

**Files:**
- Modify: `templates/email_template.py`

- [ ] **Step 1: Add the `.mono-label` base class**

In the "Layout" section of the `<style>` block, immediately after the `.wrapper` rule (near line 272), add:

```css
  .mono-label { font-family: 'Courier New', monospace; font-weight: 600; text-transform: uppercase; }
```

- [ ] **Step 2: Remove the three shared declarations from `.spiritual-ref`**

Current rule (near line 287):

```css
  .spiritual-ref { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px; }
```

Replace with:

```css
  .spiritual-ref { font-size: 10px; letter-spacing: 1.5px; color: var(--text-muted); margin-bottom: 8px; }
```

- [ ] **Step 3: Remove the three shared declarations from `.sec-label`**

Current rule (near line 305):

```css
  .sec-label { font-family: 'Courier New', monospace; font-size: 11px; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; color: var(--accent); margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
```

Replace with:

```css
  .sec-label { font-size: 11px; letter-spacing: 2px; color: var(--accent); margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
```

- [ ] **Step 4: Remove the three shared declarations from `.tag`**

Current rule (near line 311):

```css
  .tag { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; padding: 2px 7px; border-radius: 3px; display: inline-block; flex-shrink: 0; margin-top: 2px; }
```

Replace with:

```css
  .tag { font-size: 10px; letter-spacing: 1px; padding: 2px 7px; border-radius: 3px; display: inline-block; flex-shrink: 0; margin-top: 2px; }
```

- [ ] **Step 5: Remove the three shared declarations from `.scan-voice`**

Current rule (near line 328):

```css
  .scan-voice { font-family: 'Courier New', monospace; font-size: 9px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; display: inline-block; min-width: 6.5ch; padding-right: 4px; vertical-align: baseline; }
```

Replace with:

```css
  .scan-voice { font-size: 9px; letter-spacing: 1px; display: inline-block; min-width: 6.5ch; padding-right: 4px; vertical-align: baseline; }
```

- [ ] **Step 6: Remove the three shared declarations from `.cal-date`**

Current rule (near line 341):

```css
  .cal-date { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; color: var(--text-chrome); background: var(--bg-chrome); padding: 2px 7px; border-radius: 3px; flex-shrink: 0; }
```

Replace with:

```css
  .cal-date { font-size: 10px; letter-spacing: 0.5px; color: var(--text-chrome); background: var(--bg-chrome); padding: 2px 7px; border-radius: 3px; flex-shrink: 0; }
```

- [ ] **Step 7: Remove the three shared declarations from `.wim-label`**

Current rule (near line 351):

```css
  .wim-label { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent); margin-bottom: 4px; }
```

Replace with:

```css
  .wim-label { font-size: 10px; letter-spacing: 1.5px; color: var(--accent); margin-bottom: 4px; }
```

- [ ] **Step 8: Remove the three shared declarations from `.fr-label`**

Current rule (near line 354):

```css
  .fr-label { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 6px; }
```

Replace with:

```css
  .fr-label { font-size: 10px; letter-spacing: 1.5px; color: var(--text-muted); margin-bottom: 6px; }
```

- [ ] **Step 9: Remove the three shared declarations from `.seam-sub`**

Current rule (near line 359):

```css
  .seam-sub { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent-seam); margin-bottom: 10px; }
```

Replace with:

```css
  .seam-sub { font-size: 10px; letter-spacing: 1.5px; color: var(--accent-seam); margin-bottom: 10px; }
```

- [ ] **Step 10: Update HTML markup — add `mono-label` class to each affected element**

In the `<body>` Jinja template, update the `class="..."` attribute for each element that uses one of the refactored classes. Each class below currently appears as `class="<classname>"` and must become `class="mono-label <classname>"`. Do NOT add `mono-label` to `.header-date` (excluded above) or to `.mkt-label` (not a mono-style class).

Search and update each of these once:

| Current | New |
|---|---|
| `class="spiritual-ref"` | `class="mono-label spiritual-ref"` |
| `class="sec-label"` | `class="mono-label sec-label"` |
| `class="wim-label"` | `class="mono-label wim-label"` |
| `class="fr-label"` | `class="mono-label fr-label"` |
| `class="seam-sub"` | `class="mono-label seam-sub"` |
| `class="cal-date"` | `class="mono-label cal-date"` |

For `.tag`, the current markup is `class="tag tag-{{ item.tag }}"` — update to `class="mono-label tag tag-{{ item.tag }}"`.

For `.scan-voice`, current markup has three variants: `class="scan-voice scan-voice-src"`, `class="scan-voice scan-voice-analysis"`, `class="scan-voice scan-voice-thread"`. Update each to prefix with `mono-label`:

- `class="scan-voice scan-voice-src"` → `class="mono-label scan-voice scan-voice-src"`
- `class="scan-voice scan-voice-analysis"` → `class="mono-label scan-voice scan-voice-analysis"`
- `class="scan-voice scan-voice-thread"` → `class="mono-label scan-voice scan-voice-thread"`

Use one `grep -n "class=" templates/email_template.py` pass after the edits to spot-check that every mono-label class has the `mono-label ` prefix.

- [ ] **Step 11: Run the full test suite**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/ -v --tb=short
```

Expected: all tests pass. Nothing asserts on the specific class strings.

- [ ] **Step 12: Commit**

```bash
git add templates/email_template.py
git commit -m "refactor(email): extract .mono-label base class, dedupe 8 label rules"
```

---

### Task 5: Update `README.md`

Remove the Dark Mode section and update documentation that references dark-mode behavior or the toggle.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the renders-into-email bullet (around line 33)**

Find:

```markdown
3. **Renders** the output into a polished HTML email with dark mode support
```

Replace with:

```markdown
3. **Renders** the output into a polished HTML email
```

- [ ] **Step 2: Update the weather chart CSS note (around line 292)**

Find:

```markdown
All SVG colors use CSS custom properties (`--wx-*`) with hardcoded fallbacks, so the chart adapts to light/dark mode while remaining compatible with email clients that don't support CSS variables.
```

Replace with:

```markdown
All chart colors use CSS custom properties (`--wx-*`) with hardcoded light fallbacks, so email clients that don't support CSS variables still render a correct light-mode chart.
```

- [ ] **Step 3: Delete the entire Dark Mode section (around lines 347–355)**

Find and delete:

```markdown
## Dark Mode

The digest supports automatic dark mode:

- **In email** (Proton Mail, Apple Mail): Follows your system's `prefers-color-scheme` setting automatically — no interaction needed.
- **In browser** (dry-run HTML): A toggle button appears in the top-right corner. Your preference is saved in `localStorage`.

Gmail and Outlook do not support `prefers-color-scheme` and will always render in light mode.

---
```

Remove the trailing `---` separator that belonged to the deleted section so two horizontal rules don't collapse.

- [ ] **Step 4: Update the project-tree annotation (around line 419)**

Find:

```markdown
│   └── email_template.py    # Jinja2 HTML email template (light/dark mode)
```

Replace with:

```markdown
│   └── email_template.py    # Jinja2 HTML email template
```

- [ ] **Step 5: Verify no stale dark-mode references**

```bash
grep -nE "dark mode|prefers-color-scheme|data-theme" README.md
```

Expected: no matches.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs(readme): remove dark mode section and stale references"
```

---

### Task 6: Extract `_tick_html` helper (TDD)

The four tick-div blocks in `_build_chart_html` (`normal_lo_tick`, `normal_hi_tick`, `record_lo_tick`, `record_hi_tick`) are nearly identical. Extract a helper.

**Files:**
- Modify: `modules/weather_display.py`
- Modify: `tests/test_weather_display.py`

- [ ] **Step 1: Write failing tests for `_tick_html`**

Append to `tests/test_weather_display.py` (at the end of the file, preserving existing classes):

```python
from modules.weather_display import _tick_html


class TestTickHtml:
    """Absolute-positioned tick div for normals/records on the temperature bar."""

    def test_contains_percentage_position(self):
        html = _tick_html(42.5, "rgba(80,140,80,0.45)")
        assert "left:42.5%" in html

    def test_contains_color(self):
        html = _tick_html(10.0, "rgba(192,57,43,0.35)")
        assert "background:rgba(192,57,43,0.35)" in html

    def test_standard_structure(self):
        html = _tick_html(50.0, "#000")
        assert "position:absolute" in html
        assert "top:0" in html
        assert "width:2px" in html
        assert "height:100%" in html
        assert "border-radius:1px" in html

    def test_one_decimal_rounding(self):
        html = _tick_html(33.3333, "#000")
        assert "left:33.3%" in html
        assert "33.33%" not in html
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/test_weather_display.py::TestTickHtml -v
```

Expected: FAIL with `ImportError: cannot import name '_tick_html' from 'modules.weather_display'`.

- [ ] **Step 3: Add the `_tick_html` helper**

In `modules/weather_display.py`, in the "Helpers" section at the bottom (after `_temp_to_pct` definition, near line 388), add:

```python
def _tick_html(pct: float, color: str) -> str:
    """Absolute-positioned 2px tick div for normal/record temperature markers."""
    return (
        f'<div style="position:absolute;left:{pct:.1f}%;top:0;'
        f'width:2px;height:100%;background:{color};border-radius:1px;"></div>'
    )
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/test_weather_display.py::TestTickHtml -v
```

Expected: 4 passed.

- [ ] **Step 5: Replace the four inline tick blocks with `_tick_html` calls**

In `modules/weather_display.py` inside `_build_chart_html`, locate the four tick blocks (near lines 244–282). Replace this existing code:

```python
        # Normal ticks
        normal_lo_tick = ""
        normal_hi_tick = ""
        if show_normals and i < len(normals):
            nr = normals[i]
            if nr.get("normal_lo") is not None:
                nlo_pct = _temp_to_pct(nr["normal_lo"], temp_min, temp_max)
                normal_lo_tick = (
                    f'<div style="position:absolute;left:{nlo_pct:.1f}%;top:0;'
                    f'width:2px;height:100%;background:rgba(100,160,100,0.45);'
                    f'border-radius:1px;"></div>'
                )
            if nr.get("normal_hi") is not None:
                nhi_pct = _temp_to_pct(nr["normal_hi"], temp_min, temp_max)
                normal_hi_tick = (
                    f'<div style="position:absolute;left:{nhi_pct:.1f}%;top:0;'
                    f'width:2px;height:100%;background:rgba(100,160,100,0.45);'
                    f'border-radius:1px;"></div>'
                )

        # Record ticks
        record_lo_tick = ""
        record_hi_tick = ""
        if show_records and i < len(normals):
            nr = normals[i]
            if nr.get("record_lo") is not None:
                rlo_pct = _temp_to_pct(nr["record_lo"], temp_min, temp_max)
                record_lo_tick = (
                    f'<div style="position:absolute;left:{rlo_pct:.1f}%;top:0;'
                    f'width:2px;height:100%;background:rgba(211,47,47,0.35);'
                    f'border-radius:1px;"></div>'
                )
            if nr.get("record_hi") is not None:
                rhi_pct = _temp_to_pct(nr["record_hi"], temp_min, temp_max)
                record_hi_tick = (
                    f'<div style="position:absolute;left:{rhi_pct:.1f}%;top:0;'
                    f'width:2px;height:100%;background:rgba(211,47,47,0.35);'
                    f'border-radius:1px;"></div>'
                )
```

With:

```python
        # Normal + record ticks
        normal_lo_tick = ""
        normal_hi_tick = ""
        record_lo_tick = ""
        record_hi_tick = ""
        if i < len(normals):
            nr = normals[i]
            if show_normals:
                if nr.get("normal_lo") is not None:
                    normal_lo_tick = _tick_html(
                        _temp_to_pct(nr["normal_lo"], temp_min, temp_max),
                        "rgba(100,160,100,0.45)",
                    )
                if nr.get("normal_hi") is not None:
                    normal_hi_tick = _tick_html(
                        _temp_to_pct(nr["normal_hi"], temp_min, temp_max),
                        "rgba(100,160,100,0.45)",
                    )
            if show_records:
                if nr.get("record_lo") is not None:
                    record_lo_tick = _tick_html(
                        _temp_to_pct(nr["record_lo"], temp_min, temp_max),
                        "rgba(211,47,47,0.35)",
                    )
                if nr.get("record_hi") is not None:
                    record_hi_tick = _tick_html(
                        _temp_to_pct(nr["record_hi"], temp_min, temp_max),
                        "rgba(211,47,47,0.35)",
                    )
```

Note: the rgba values here are unchanged (they still match the current behavior). They are refactored into `var(--wx-*, ...)` form in Task 8.

- [ ] **Step 6: Run the full weather test file to confirm no regressions**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/test_weather_display.py tests/test_weather_integration.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add modules/weather_display.py tests/test_weather_display.py
git commit -m "refactor(weather): extract _tick_html helper for chart tick markers"
```

---

### Task 7: Extract `_legend_item` helper (TDD)

The legend builder wraps every entry in the same `<span style="display:inline-flex;align-items:center;gap:3px;">...</span>` structure. Extract that wrapper.

**Files:**
- Modify: `modules/weather_display.py`
- Modify: `tests/test_weather_display.py`

- [ ] **Step 1: Write failing tests for `_legend_item`**

Append to `tests/test_weather_display.py`:

```python
from modules.weather_display import _legend_item


class TestLegendItem:
    """Legend entry wrapper: swatch + label."""

    def test_wraps_swatch_and_label(self):
        html = _legend_item('<span class="sw"></span>', "Forecast Hi")
        assert '<span class="sw"></span>' in html
        assert "Forecast Hi" in html

    def test_uses_inline_flex(self):
        html = _legend_item("", "x")
        assert "display:inline-flex" in html
        assert "align-items:center" in html
        assert "gap:3px" in html

    def test_opens_and_closes_span(self):
        html = _legend_item("swatch", "label")
        assert html.startswith("<span")
        assert html.endswith("</span>")
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/test_weather_display.py::TestLegendItem -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the `_legend_item` helper**

In `modules/weather_display.py`, in the Helpers section (after `_tick_html`), add:

```python
def _legend_item(swatch_html: str, label: str) -> str:
    """Wrap a legend swatch + label in the standard inline-flex span."""
    return (
        f'<span style="display:inline-flex;align-items:center;gap:3px;">'
        f"{swatch_html}{label}</span>"
    )
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/test_weather_display.py::TestLegendItem -v
```

Expected: 3 passed.

- [ ] **Step 5: Refactor `_build_legend_html` to use `_legend_item`**

Replace the entire body of `_build_legend_html` (currently at approximately lines 118–172) with:

```python
def _build_legend_html(weather: dict, show_aqi: bool, show_records: bool) -> str:
    """Legend row with colored swatches."""
    items = [
        _legend_item(
            '<span style="width:8px;height:8px;background:#d09050;'
            'border-radius:50%;display:inline-block;"></span>',
            "Forecast Hi",
        ),
        _legend_item(
            '<span style="width:8px;height:1px;border-top:1px dashed #5a7aa0;'
            'display:inline-block;"></span>',
            "Forecast Lo",
        ),
        _legend_item(
            '<span style="width:2px;height:10px;background:rgba(100,160,100,0.45);'
            'border-radius:1px;display:inline-block;"></span>',
            "Normal",
        ),
    ]
    if show_records:
        items.append(
            _legend_item(
                '<span style="width:2px;height:10px;background:rgba(211,47,47,0.45);'
                'border-radius:1px;display:inline-block;"></span>',
                "Record",
            )
        )
    items.append(
        _legend_item(
            '<span style="width:8px;height:3px;background:#5b9bd5;'
            'border-radius:1px;display:inline-block;"></span>',
            "Precip",
        )
    )
    if show_aqi:
        aqi_swatch = (
            "AQI "
            '<span style="color:#00e400;font-weight:600;font-size:8px;">##</span>'
            '<span style="color:#cccc00;font-weight:600;font-size:8px;">##</span>'
            '<span style="color:#ff0000;font-weight:600;font-size:8px;">##</span>'
        )
        items.append(_legend_item(aqi_swatch, " on bar"))

    return (
        '<div style="font-size:10px;color:#888582;margin-bottom:6px;'
        'display:flex;gap:12px;flex-wrap:wrap;">'
        + "".join(items)
        + "</div>"
    )
```

Note: hex/rgba literals here are unchanged. They are refactored into `var(--wx-*, ...)` form in Task 8.

- [ ] **Step 6: Run the full weather test suite**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/test_weather_display.py tests/test_weather_integration.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add modules/weather_display.py tests/test_weather_display.py
git commit -m "refactor(weather): extract _legend_item helper for legend entries"
```

---

### Task 8: Swap hardcoded dark colors for `var(--wx-*, light-fallback)`

This task fixes the visible bug: black bars on the light background. Every hardcoded dark color in the chart output becomes `var(--wx-*, <light-fallback>)`. Test assertions that match the old rgba values are updated to match the new values.

**Files:**
- Modify: `modules/weather_display.py`
- Modify: `tests/test_weather_integration.py`

- [ ] **Step 1: Update the two integration-test rgba assertions**

In `tests/test_weather_integration.py` line 146, replace:

```python
        # Normals show as green bands
        assert "rgba(100,160,100" in html
```

With:

```python
        # Normals show as green bands (var with light fallback)
        assert "rgba(80,140,80,0.45)" in html
```

In `tests/test_weather_integration.py` line 153, replace:

```python
        # Records show as red tick marks
        assert "211,47,47" in html
```

With:

```python
        # Records show as red tick marks (var with light fallback)
        assert "192,57,43" in html
```

- [ ] **Step 2: Run the integration tests to confirm they now fail**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/test_weather_integration.py::TestRenderWeatherHtml::test_normals_rendered tests/test_weather_integration.py::TestRenderWeatherHtml::test_records_rendered -v
```

Expected: FAIL (the current code emits the old rgba values).

- [ ] **Step 3: Update `_build_header_html` color fallbacks**

In `modules/weather_display.py`, find `_build_header_html` (near lines 72–115). Locate the two `color:var(--wx-label, #b0ada8)` / `color:var(--wx-label-dim, #888582)` occurrences in the return statement and replace with light fallbacks:

Current:

```python
    return (
        f'<div style="font-family:JetBrains Mono,monospace;font-size:13px;'
        f'color:var(--wx-label, #b0ada8);'
        f'margin-bottom:4px;display:flex;justify-content:space-between;align-items:baseline;">'
        f"<span>{header_text}</span>"
        f'<span style="color:var(--wx-label-dim, #888582);font-size:11px;">{date_str}</span>'
        f"</div>"
        f"{aqi_alert}"
    )
```

Replace with:

```python
    return (
        f'<div style="font-family:JetBrains Mono,monospace;font-size:13px;'
        f'color:var(--wx-label, #555);'
        f'margin-bottom:4px;display:flex;justify-content:space-between;align-items:baseline;">'
        f"<span>{header_text}</span>"
        f'<span style="color:var(--wx-label-dim, #888);font-size:11px;">{date_str}</span>'
        f"</div>"
        f"{aqi_alert}"
    )
```

- [ ] **Step 4: Update `_build_legend_html` colors**

Replace the entire body of `_build_legend_html` (written in Task 7 step 5) with the themed version:

```python
def _build_legend_html(weather: dict, show_aqi: bool, show_records: bool) -> str:
    """Legend row with colored swatches."""
    items = [
        _legend_item(
            '<span style="width:8px;height:8px;background:var(--wx-hi, #c07830);'
            'border-radius:50%;display:inline-block;"></span>',
            "Forecast Hi",
        ),
        _legend_item(
            '<span style="width:8px;height:1px;'
            'border-top:1px dashed var(--wx-lo, #4a6a90);'
            'display:inline-block;"></span>',
            "Forecast Lo",
        ),
        _legend_item(
            '<span style="width:2px;height:10px;'
            'background:var(--wx-normal, rgba(80,140,80,0.45));'
            'border-radius:1px;display:inline-block;"></span>',
            "Normal",
        ),
    ]
    if show_records:
        items.append(
            _legend_item(
                '<span style="width:2px;height:10px;'
                'background:var(--wx-record, rgba(192,57,43,0.35));'
                'border-radius:1px;display:inline-block;"></span>',
                "Record",
            )
        )
    items.append(
        _legend_item(
            '<span style="width:8px;height:3px;'
            'background:var(--wx-precip, #5b9bd5);'
            'border-radius:1px;display:inline-block;"></span>',
            "Precip",
        )
    )
    if show_aqi:
        aqi_swatch = (
            "AQI "
            '<span style="color:#00e400;font-weight:600;font-size:8px;">##</span>'
            '<span style="color:#cccc00;font-weight:600;font-size:8px;">##</span>'
            '<span style="color:#ff0000;font-weight:600;font-size:8px;">##</span>'
        )
        items.append(_legend_item(aqi_swatch, " on bar"))

    return (
        '<div style="font-size:10px;color:var(--wx-label-dim, #888);'
        'margin-bottom:6px;display:flex;gap:12px;flex-wrap:wrap;">'
        + "".join(items)
        + "</div>"
    )
```

Note: AQI hex literals (`#00e400`, `#cccc00`, `#ff0000`) stay hardcoded — they are regulatory EPA colors, not themed.

- [ ] **Step 5: Update tick colors to use `var(--wx-*, fallback)`**

In `_build_chart_html` (refactored in Task 6 step 5), replace the four `_tick_html` calls' color arguments. Replace this block:

```python
            if show_normals:
                if nr.get("normal_lo") is not None:
                    normal_lo_tick = _tick_html(
                        _temp_to_pct(nr["normal_lo"], temp_min, temp_max),
                        "rgba(100,160,100,0.45)",
                    )
                if nr.get("normal_hi") is not None:
                    normal_hi_tick = _tick_html(
                        _temp_to_pct(nr["normal_hi"], temp_min, temp_max),
                        "rgba(100,160,100,0.45)",
                    )
            if show_records:
                if nr.get("record_lo") is not None:
                    record_lo_tick = _tick_html(
                        _temp_to_pct(nr["record_lo"], temp_min, temp_max),
                        "rgba(211,47,47,0.35)",
                    )
                if nr.get("record_hi") is not None:
                    record_hi_tick = _tick_html(
                        _temp_to_pct(nr["record_hi"], temp_min, temp_max),
                        "rgba(211,47,47,0.35)",
                    )
```

With:

```python
            if show_normals:
                if nr.get("normal_lo") is not None:
                    normal_lo_tick = _tick_html(
                        _temp_to_pct(nr["normal_lo"], temp_min, temp_max),
                        "var(--wx-normal, rgba(80,140,80,0.45))",
                    )
                if nr.get("normal_hi") is not None:
                    normal_hi_tick = _tick_html(
                        _temp_to_pct(nr["normal_hi"], temp_min, temp_max),
                        "var(--wx-normal, rgba(80,140,80,0.45))",
                    )
            if show_records:
                if nr.get("record_lo") is not None:
                    record_lo_tick = _tick_html(
                        _temp_to_pct(nr["record_lo"], temp_min, temp_max),
                        "var(--wx-record, rgba(192,57,43,0.35))",
                    )
                if nr.get("record_hi") is not None:
                    record_hi_tick = _tick_html(
                        _temp_to_pct(nr["record_hi"], temp_min, temp_max),
                        "var(--wx-record, rgba(192,57,43,0.35))",
                    )
```

- [ ] **Step 6: Update chart bar + precip bar + row border + column text colors**

Still inside `_build_chart_html`, find the temperature row and precip row emission (near lines 336–373). Replace the current row emission:

```python
        lo_str = f"{round(lo)}&deg;" if lo is not None else "&mdash;"
        hi_str = f"{round(hi)}&deg;" if hi is not None else "&mdash;"
        border = 'border-bottom:1px solid #2a2a2a;' if i < len(forecast) - 1 else ''

        # Temperature row
        rows.append(
            f'<tr>'
            f'<td style="width:32px;font-size:9px;font-weight:600;color:#b0ada8;'
            f'padding:5px 6px 0 0;vertical-align:top;">{day_name.upper()}</td>'
            f'<td style="width:28px;font-size:8px;color:#5a7aa0;text-align:right;'
            f'padding:6px 5px 0 0;vertical-align:top;">{lo_str}</td>'
            f'<td style="padding:5px 4px 0;vertical-align:top;">'
            f'<div style="position:relative;height:14px;background:#252525;'
            f'border-radius:6px;">'
            f'{record_lo_tick}{record_hi_tick}'
            f'{normal_lo_tick}{normal_hi_tick}'
            f'<div style="position:absolute;left:{lo_pct:.1f}%;'
            f'width:{bar_width:.1f}%;height:100%;background:linear-gradient('
            f'to right,rgba(90,122,160,0.35),rgba(208,144,80,0.40));'
            f'border-radius:6px;"></div>'
            f'{aqi_html}'
            f'</div>'
            f'</td>'
            f'<td style="width:28px;font-size:8px;color:#d09050;'
            f'padding:6px 0 0 5px;vertical-align:top;">{hi_str}</td>'
            f'<td style="width:50px;font-size:7px;color:#888582;text-align:right;'
            f'padding:6px 0 0 4px;vertical-align:top;">{right_col}</td>'
            f'</tr>'
        )
```

With:

```python
        lo_str = f"{round(lo)}&deg;" if lo is not None else "&mdash;"
        hi_str = f"{round(hi)}&deg;" if hi is not None else "&mdash;"
        border = (
            'border-bottom:1px solid var(--border, #e5e2dd);'
            if i < len(forecast) - 1
            else ''
        )

        # Temperature row
        rows.append(
            f'<tr>'
            f'<td style="width:32px;font-size:9px;font-weight:600;'
            f'color:var(--wx-label, #555);'
            f'padding:5px 6px 0 0;vertical-align:top;">{day_name.upper()}</td>'
            f'<td style="width:28px;font-size:8px;'
            f'color:var(--wx-lo, #4a6a90);text-align:right;'
            f'padding:6px 5px 0 0;vertical-align:top;">{lo_str}</td>'
            f'<td style="padding:5px 4px 0;vertical-align:top;">'
            f'<div style="position:relative;height:14px;'
            f'background:var(--wx-grid, #d8d5d0);'
            f'border-radius:6px;">'
            f'{record_lo_tick}{record_hi_tick}'
            f'{normal_lo_tick}{normal_hi_tick}'
            f'<div style="position:absolute;left:{lo_pct:.1f}%;'
            f'width:{bar_width:.1f}%;height:100%;background:linear-gradient('
            f'to right,rgba(90,122,160,0.35),rgba(208,144,80,0.40));'
            f'border-radius:6px;"></div>'
            f'{aqi_html}'
            f'</div>'
            f'</td>'
            f'<td style="width:28px;font-size:8px;color:var(--wx-hi, #c07830);'
            f'padding:6px 0 0 5px;vertical-align:top;">{hi_str}</td>'
            f'<td style="width:50px;font-size:7px;'
            f'color:var(--wx-label-dim, #888);text-align:right;'
            f'padding:6px 0 0 4px;vertical-align:top;">{right_col}</td>'
            f'</tr>'
        )
```

Note: the linear-gradient on the temperature bar (`rgba(90,122,160,0.35), rgba(208,144,80,0.40)`) stays unchanged — it reads well on the new light-grey bar background.

- [ ] **Step 7: Update the precip underline bar background**

Still in `_build_chart_html`, find `precip_bar_html` (near lines 308–318). Replace:

```python
        # Precip underline bar
        precip_bar_html = ""
        if precip_pct > 0 and precip_type != "none":
            p_color = _precip_color(precip_type)
            opacity = 0.5 + (precip_pct / 100.0) * 0.3
            precip_bar_html = (
                f'<div style="position:relative;height:3px;background:#1e1e1e;'
                f'border-radius:2px;">'
                f'<div style="position:absolute;left:0;width:{precip_pct}%;'
                f'height:100%;background:{p_color};opacity:{opacity:.2f};'
                f'border-radius:2px;"></div></div>'
            )
```

With:

```python
        # Precip underline bar
        precip_bar_html = ""
        if precip_pct > 0 and precip_type != "none":
            p_color = _precip_color(precip_type)
            opacity = 0.5 + (precip_pct / 100.0) * 0.3
            precip_bar_html = (
                f'<div style="position:relative;height:3px;'
                f'background:var(--wx-grid, #d8d5d0);'
                f'border-radius:2px;">'
                f'<div style="position:absolute;left:0;width:{precip_pct}%;'
                f'height:100%;background:{p_color};opacity:{opacity:.2f};'
                f'border-radius:2px;"></div></div>'
            )
```

- [ ] **Step 8: Verify no hardcoded dark colors remain in the weather module**

```bash
grep -nE "#252525|#1e1e1e|#2a2a2a|#b0ada8|#5a7aa0|#d09050|#888582" modules/weather_display.py
```

Expected: only `#888582` in the `_aqi_color(None)` branch (the "unknown AQI" text color). If any other hits, re-check the swaps above. The `#888582` in `_aqi_color` stays — it is a neutral-grey value consumers see when AQI data is unavailable, not a themed value.

- [ ] **Step 9: Run the full weather test suite and confirm pass**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/test_weather_display.py tests/test_weather_integration.py -v
```

Expected: all tests pass, including the two updated assertions from step 1.

- [ ] **Step 10: Commit**

```bash
git add modules/weather_display.py tests/test_weather_integration.py
git commit -m "fix(weather): swap hardcoded dark colors for var(--wx-*, light-fallback)"
```

---

### Task 9: Final full-suite verification + visual smoke test

**Files:**
- No code changes expected. This task verifies integration.

- [ ] **Step 1: Run the full test suite**

```bash
docker compose run --rm --no-deps morning-digest python -m pytest tests/ -v --tb=short
```

Expected: all tests pass, including `tests/test_lint.py` (ruff).

- [ ] **Step 2: Generate a dry-run HTML render and inspect manually**

Find the dry-run command in the project. Common patterns:

```bash
docker compose run --rm --no-deps morning-digest python pipeline.py --dry-run 2>/dev/null || \
docker compose run --rm --no-deps morning-digest python pipeline.py --help
```

If `--dry-run` isn't present, look for an existing dry-run path in `pipeline.py` or an `entrypoint.py` flag. The goal is to produce an HTML file under `output/` that can be opened in a browser. If no dry-run path exists, skip this step and note that visual verification requires a full pipeline run.

- [ ] **Step 3: Manual visual checks**

Open the generated HTML in a browser on a light-mode system. Verify:

- [ ] Weather chart temperature bars render as light-grey (not black)
- [ ] Day labels (SUN/MON/…) are legible dark-grey, not washed out
- [ ] Lo-temp column reads in muted blue, Hi-temp column in muted orange
- [ ] Normal ticks (green) and record ticks (red) are visible on the light bar
- [ ] Legend swatches match the tick/bar colors
- [ ] AQI numbers on the bar use EPA regulatory colors (green/yellow/orange/red/purple/maroon)
- [ ] No theme-toggle button appears in the top-right
- [ ] No literal `##` characters appear outside the legend
- [ ] Header, markets, At-a-Glance, Deep Dives, footer — all render in light palette with correct mono-label styling on monospace UI chrome

If any visual check fails, diagnose whether it's a CSS issue (template) or an inline-style issue (weather module). Fix inline, re-run the suite, commit with a `fix:` prefix.

- [ ] **Step 4: Confirm no residual dark-mode references across the repo**

```bash
grep -rnE "prefers-color-scheme|data-theme|theme-bar|theme-btn|md-theme" \
  templates/ modules/ stages/ README.md
```

Expected: no matches.

- [ ] **Step 5: If step 3 required fixes, commit them**

```bash
git status
# Review any diffs
git add <modified files>
git commit -m "fix(weather): <specific visual fix from step 3>"
```

If no fixes were needed, no commit is required for this task — the goal was verification.

---

## Self-Review

**Spec coverage:** Every spec section maps to a task:

- Spec Part 1 deletions → Tasks 2 (CSS) + 3 (JS) + 5 (docstring + README)
- Spec Part 1 `:root` retuning → Task 1
- Spec Part 1 `.mono-label` base class → Task 4
- Spec Part 2 color swaps → Task 8
- Spec Part 2 `_tick_html` helper → Task 6
- Spec Part 2 `_legend_item` helper → Task 7
- Spec Part 3 test updates → Task 8 step 1
- Spec Part 4 acceptance criteria → Task 9

**Type consistency:** `_tick_html(pct: float, color: str) -> str` and `_legend_item(swatch_html: str, label: str) -> str` signatures are defined in Tasks 6/7 and used consistently in Task 8.

**Known non-issue:** `_aqi_color(None)` returns `#888582` (grep will hit this in Task 8 step 8). Intentionally left — it's the "no AQI data" fallback, not a themed color.
