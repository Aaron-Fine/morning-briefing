# Weather HTML Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the SVG weather chart (stripped by Gmail) with an email-safe HTML table chart using the F2 horizontal-bar design with inline AQI numbers, record ticks, normal ticks, and precip underline bars.

**Architecture:** Rewrite `modules/weather_display.py` to emit HTML tables instead of SVG. The public API (`render_weather_html`) stays identical — same inputs, same integration with `stages/prepare_weather.py` and `templates/email_template.py`. The header and text-fallback functions are unchanged. All SVG-specific code (`_build_svg` and its sub-renderers) is replaced with a single `_build_chart_html` function and small helpers. Tests are updated to assert HTML table output instead of SVG.

**Tech Stack:** Python, inline HTML/CSS (no SVG), pytest

---

## File Map

- **Modify:** `modules/weather_display.py` — replace SVG rendering with HTML table rendering
- **Modify:** `tests/test_weather_display.py` — update assertions from SVG to HTML, add new tests for HTML chart features
- **No changes:** `stages/prepare_weather.py`, `templates/email_template.py`, `stages/assemble.py`, test fixtures

---

### Task 1: Remove SVG constants and add HTML chart helpers

**Files:**
- Modify: `modules/weather_display.py`

- [ ] **Step 1: Write failing tests for new helper functions**

Add to `tests/test_weather_display.py`:

```python
from modules.weather_display import (
    _temp_to_pct,
    _aqi_position_pct,
    _aqi_color,
    _precip_color,
)


class TestTempToPct:
    """Temperature to percentage position on the bar."""

    def test_at_min(self):
        assert _temp_to_pct(30, 30, 80) == 0.0

    def test_at_max(self):
        assert _temp_to_pct(80, 30, 80) == 100.0

    def test_midpoint(self):
        assert _temp_to_pct(55, 30, 80) == 50.0

    def test_equal_range(self):
        assert _temp_to_pct(50, 50, 50) == 50.0

    def test_below_min(self):
        """Below min should clamp to 0."""
        assert _temp_to_pct(20, 30, 80) == 0.0

    def test_above_max(self):
        """Above max should clamp to 100."""
        assert _temp_to_pct(90, 30, 80) == 100.0


class TestAqiPositionPct:
    """AQI value to percentage on 0-200 scale."""

    def test_zero(self):
        assert _aqi_position_pct(0) == 0.0

    def test_hundred(self):
        assert _aqi_position_pct(100) == 50.0

    def test_two_hundred(self):
        assert _aqi_position_pct(200) == 100.0

    def test_above_200_pins(self):
        """Values above 200 pin to 100%."""
        assert _aqi_position_pct(300) == 100.0

    def test_moderate(self):
        assert _aqi_position_pct(57) == pytest.approx(28.5)


class TestAqiColor:
    """AQI value to display color."""

    def test_good(self):
        assert _aqi_color(26) == "#00e400"

    def test_moderate(self):
        assert _aqi_color(57) == "#cccc00"

    def test_usg(self):
        assert _aqi_color(120) == "#ff7e00"

    def test_unhealthy(self):
        assert _aqi_color(175) == "#ff0000"

    def test_very_unhealthy(self):
        assert _aqi_color(220) == "#8f3f97"

    def test_hazardous(self):
        assert _aqi_color(350) == "#7e0023"

    def test_none(self):
        assert _aqi_color(None) == "#888582"


class TestPrecipColor:
    """Precipitation type to bar color."""

    def test_rain(self):
        assert _precip_color("rain") == "#5b9bd5"

    def test_snow(self):
        assert _precip_color("snow") == "#a0d4f0"

    def test_thunderstorm(self):
        assert _precip_color("thunderstorm") == "#5b9bd5"

    def test_mix(self):
        assert _precip_color("mix") == "#5b9bd5"

    def test_freezing_rain(self):
        assert _precip_color("freezing_rain") == "#5b9bd5"

    def test_none(self):
        assert _precip_color("none") == "#5b9bd5"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_weather_display.py::TestTempToPct tests/test_weather_display.py::TestAqiPositionPct tests/test_weather_display.py::TestAqiColor tests/test_weather_display.py::TestPrecipColor -v`
Expected: ImportError — functions don't exist yet

- [ ] **Step 3: Implement helper functions**

In `modules/weather_display.py`, remove the SVG constants block (lines 43-55: `SVG_WIDTH` through `DAY_START_X`) and the `_PRECIP_GRADIENTS` dict (lines 35-41). Remove `_render_defs`, `_render_zone2_gridlines`, `_render_zone2_bands`, `_render_zone2_lines`, `_render_zone3_aqi`, `_render_zone4_precip`, `_render_zone5_labels`, `_build_svg`, `_temp_to_y`, `_precip_to_height`, `_nice_step`. Keep `_AQI_COLORS`, `_AQI_OPACITIES`, `_precip_marker`, `_shorten_condition`, `_build_header_html`, `_build_legend_html`, `_build_text_fallback`.

Add these new constants and helpers:

```python
# --- Chart layout ---
DAY_COUNT = 7
AQI_SCALE_MAX = 200

# --- Precip bar colors by type ---
_PRECIP_COLORS = {
    "snow": "#a0d4f0",
    "freezing_rain": "#a0d4f0",
    "mix": "#a0d4f0",
}
_PRECIP_DEFAULT_COLOR = "#5b9bd5"


def _temp_to_pct(temp: float, temp_min: float, temp_max: float) -> float:
    """Map temperature to percentage position (0-100) on the bar. Clamps to bounds."""
    if temp_max == temp_min:
        return 50.0
    pct = (temp - temp_min) / (temp_max - temp_min) * 100.0
    return max(0.0, min(100.0, pct))


def _aqi_position_pct(aqi: int) -> float:
    """Map AQI value to percentage on 0-200 scale. Values above 200 pin to 100%."""
    if aqi is None:
        return 0.0
    return min(aqi / AQI_SCALE_MAX * 100.0, 100.0)


def _aqi_color(aqi: int | None) -> str:
    """Return display color for an AQI value using EPA breakpoints."""
    if aqi is None:
        return "#888582"
    if aqi <= 50:
        return "#00e400"
    if aqi <= 100:
        return "#cccc00"
    if aqi <= 150:
        return "#ff7e00"
    if aqi <= 200:
        return "#ff0000"
    if aqi <= 300:
        return "#8f3f97"
    return "#7e0023"


def _precip_color(precip_type: str) -> str:
    """Return bar color for precipitation type."""
    return _PRECIP_COLORS.get(precip_type, _PRECIP_DEFAULT_COLOR)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_weather_display.py::TestTempToPct tests/test_weather_display.py::TestAqiPositionPct tests/test_weather_display.py::TestAqiColor tests/test_weather_display.py::TestPrecipColor -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add modules/weather_display.py tests/test_weather_display.py
git commit -m "refactor(weather): remove SVG code, add HTML chart helpers

Replace SVG constants and gradient defs with helpers for the new
HTML table-based chart: _temp_to_pct, _aqi_position_pct, _aqi_color,
_precip_color."
```

---

### Task 2: Implement `_build_chart_html` — the core HTML table renderer

**Files:**
- Modify: `modules/weather_display.py`

- [ ] **Step 1: Write failing test for chart HTML output**

Add to `tests/test_weather_display.py`:

```python
from modules.weather_display import _build_chart_html


class TestBuildChartHtml:
    """HTML chart table rendering."""

    def test_returns_table(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "<table" in html
        assert "</table>" in html

    def test_contains_day_labels(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "TUE" in html
        assert "WED" in html

    def test_contains_hi_lo_temps(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "75&deg;" in html or "75°" in html  # hi temp for day 1
        assert "48&deg;" in html or "48°" in html  # lo temp for day 1

    def test_contains_aqi_number(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        # AQI 26 from fixture should appear as text on the bar
        assert ">26<" in html

    def test_contains_precip_bar(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        # Day 6 (Sun) has 60% precip
        assert "60%" in html

    def test_contains_record_ticks(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        # Record ticks use red color
        assert "211,47,47" in html

    def test_contains_normal_ticks(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        # Normal ticks use green color
        assert "100,160,100" in html

    def test_no_records_when_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=False, show_normals=True)
        assert "211,47,47" not in html

    def test_no_normals_when_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=False)
        assert "100,160,100" not in html

    def test_no_svg(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "<svg" not in html

    def test_condition_text(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "Sunny" in html

    def test_precip_marker_snow(self):
        weather = _load_fixture("weather_snow.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "❄" in html

    def test_precip_marker_thunderstorm(self):
        weather = _load_fixture("weather_thunderstorm.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "⚡" in html

    def test_aqi_above_200_pins(self):
        """AQI values above 200 should pin to right side of bar."""
        weather = _load_fixture("weather_inversion.json")
        # Modify a day to have AQI > 200
        weather["aqi_forecast"]["2026-01-17"]["aqi"] = 250
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        # Should contain "right:" positioning for pinned AQI
        assert "250" in html

    def test_minimal_data(self):
        """Minimal fixture with 2 days, no AQI."""
        weather = _load_fixture("weather_minimal.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "<table" in html
        assert "FRI" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_weather_display.py::TestBuildChartHtml -v`
Expected: ImportError — `_build_chart_html` doesn't exist yet

- [ ] **Step 3: Implement `_build_chart_html`**

Add to `modules/weather_display.py`:

```python
def _build_chart_html(
    weather: dict, show_records: bool, show_normals: bool
) -> str:
    """Build the HTML table chart — horizontal day rows with temp range bars."""
    forecast = weather.get("forecast", [])[:DAY_COUNT]
    normals = weather.get("normals", [])
    aqi_forecast = weather.get("aqi_forecast", {})

    if not forecast:
        return ""

    # Determine temperature scale from all data points
    all_temps = []
    for day in forecast:
        if day.get("high_f") is not None:
            all_temps.append(day["high_f"])
        if day.get("low_f") is not None:
            all_temps.append(day["low_f"])
    for nr in normals:
        if show_records:
            if nr.get("record_hi") is not None:
                all_temps.append(nr["record_hi"])
            if nr.get("record_lo") is not None:
                all_temps.append(nr["record_lo"])
        if show_normals:
            if nr.get("normal_hi") is not None:
                all_temps.append(nr["normal_hi"])
            if nr.get("normal_lo") is not None:
                all_temps.append(nr["normal_lo"])

    if not all_temps:
        temp_min, temp_max = 0, 100
    else:
        temp_min = min(all_temps) - 5
        temp_max = max(all_temps) + 5

    rows = []
    for i, day in enumerate(forecast):
        hi = day.get("high_f")
        lo = day.get("low_f")
        day_name = day.get("day_name", "???")
        date_str = day.get("date", "")
        condition = day.get("condition", day.get("short_forecast", ""))
        precip_pct = day.get("precip_chance", 0) or 0
        precip_type = day.get("precip_type", "none")

        # Temperature bar positions
        lo_pct = _temp_to_pct(lo, temp_min, temp_max) if lo is not None else 0
        hi_pct = _temp_to_pct(hi, temp_min, temp_max) if hi is not None else 100
        bar_width = max(hi_pct - lo_pct, 1)

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

        # AQI number on bar
        aqi_data = aqi_forecast.get(date_str, {})
        aqi_val = aqi_data.get("aqi")
        aqi_html = ""
        if aqi_val is not None:
            aqi_pct = _aqi_position_pct(aqi_val)
            color = _aqi_color(aqi_val)
            if aqi_val > AQI_SCALE_MAX:
                # Pin to right edge
                aqi_html = (
                    f'<div style="position:absolute;right:2px;top:0;height:100%;'
                    f'display:flex;align-items:center;">'
                    f'<span style="font-size:7px;color:{color};font-weight:600;">'
                    f'{aqi_val}</span></div>'
                )
            else:
                aqi_html = (
                    f'<div style="position:absolute;left:{aqi_pct:.1f}%;top:0;'
                    f'height:100%;display:flex;align-items:center;">'
                    f'<span style="font-size:7px;color:{color};font-weight:600;'
                    f'margin-left:-6px;">{aqi_val}</span></div>'
                )

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

        # Condition/precip right column
        short_cond = _shorten_condition(condition)
        marker = _precip_marker(precip_type)
        if precip_pct > 0 and precip_type != "none":
            p_color = _precip_color(precip_type)
            bold = " font-weight:600;" if precip_pct >= 40 else ""
            marker_str = f" {marker}" if marker else ""
            right_col = (
                f'<span style="color:{p_color};{bold}">'
                f'{precip_pct}%</span>{marker_str}'
            )
        else:
            right_col = short_cond

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

        # Precip underline + separator row
        rows.append(
            f'<tr style="{border}">'
            f'<td></td><td></td>'
            f'<td style="padding:1px 4px 5px;">'
            f'{precip_bar_html if precip_bar_html else "<div style=\\"height:3px;\\"></div>"}'
            f'</td>'
            f'<td colspan="2"></td>'
            f'</tr>'
        )

    return (
        '<table cellspacing="0" cellpadding="0" border="0" '
        'style="width:100%;border-collapse:collapse;margin-top:8px;">'
        + "".join(rows)
        + "</table>"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_weather_display.py::TestBuildChartHtml -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add modules/weather_display.py tests/test_weather_display.py
git commit -m "feat(weather): implement HTML table chart renderer

_build_chart_html produces horizontal day rows with gradient temp
bars, record/normal tick marks, inline AQI numbers (0-200 scale,
pins >200), and precip underline bars."
```

---

### Task 3: Wire up `render_weather_html` and update the legend

**Files:**
- Modify: `modules/weather_display.py`

- [ ] **Step 1: Write failing test for legend update**

Add to `tests/test_weather_display.py`:

```python
class TestBuildLegendHtmlUpdated:
    """Legend should include Record swatch."""

    def test_has_record_swatch(self):
        weather = {"aqi": 26}
        html = _build_legend_html(weather, show_aqi=True, show_records=True)
        assert "Record" in html
        assert "211,47,47" in html  # red color for record

    def test_no_record_when_disabled(self):
        weather = {}
        html = _build_legend_html(weather, show_aqi=True, show_records=False)
        assert "Record" not in html

    def test_has_precip_swatch(self):
        weather = {}
        html = _build_legend_html(weather, show_aqi=True, show_records=True)
        assert "Precip" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_weather_display.py::TestBuildLegendHtmlUpdated::test_has_record_swatch -v`
Expected: FAIL — legend doesn't include red record color yet

- [ ] **Step 3: Update `_build_legend_html` and `render_weather_html`**

Update `_build_legend_html` in `modules/weather_display.py` — change the Record swatch from white/subtle to red:

```python
def _build_legend_html(weather: dict, show_aqi: bool, show_records: bool) -> str:
    """Legend row with colored swatches."""
    parts = [
        '<div style="font-size:10px;color:#888582;margin-bottom:6px;'
        'display:flex;gap:12px;flex-wrap:wrap;">'
    ]

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:8px;background:#d09050;'
        'border-radius:50%;display:inline-block;"></span>'
        "Forecast Hi</span>"
    )

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:1px;border-top:1px dashed #5a7aa0;'
        'display:inline-block;"></span>'
        "Forecast Lo</span>"
    )

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:2px;height:10px;background:rgba(100,160,100,0.45);'
        'border-radius:1px;display:inline-block;"></span>'
        "Normal</span>"
    )

    if show_records:
        parts.append(
            '<span style="display:inline-flex;align-items:center;gap:3px;">'
            '<span style="width:2px;height:10px;background:rgba(211,47,47,0.45);'
            'border-radius:1px;display:inline-block;"></span>'
            "Record</span>"
        )

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:3px;background:#5b9bd5;'
        'border-radius:1px;display:inline-block;"></span>'
        "Precip</span>"
    )

    if show_aqi:
        parts.append(
            '<span style="display:inline-flex;align-items:center;gap:3px;">'
            "AQI "
            '<span style="color:#00e400;font-weight:600;font-size:8px;">##</span>'
            '<span style="color:#cccc00;font-weight:600;font-size:8px;">##</span>'
            '<span style="color:#ff0000;font-weight:600;font-size:8px;">##</span>'
            " on bar</span>"
        )

    parts.append("</div>")
    return "".join(parts)
```

Update `render_weather_html` to call `_build_chart_html` instead of `_build_svg`:

```python
def render_weather_html(weather: dict, config: dict) -> str:
    """Return complete HTML block for embedding in the email template.

    Fallback chain:
        - empty weather -> ""
        - insufficient data -> text-only header
        - chart exception -> text-only header
    """
    if not weather or not weather.get("forecast"):
        return ""

    display_config = config.get("weather", {})
    show_aqi = display_config.get("aqi_strip", True)
    show_records = display_config.get("record_band", True)
    show_normals = display_config.get("normal_band", True)

    try:
        chart = _build_chart_html(weather, show_records, show_normals)
        header = _build_header_html(weather)
        legend = _build_legend_html(weather, show_aqi, show_records)
        return f"{header}{legend}{chart}"
    except Exception as e:
        log.error(f"weather_display: chart render failed: {e}")
        return _build_text_fallback(weather)
```

- [ ] **Step 4: Run legend tests**

Run: `pytest tests/test_weather_display.py::TestBuildLegendHtmlUpdated -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add modules/weather_display.py tests/test_weather_display.py
git commit -m "feat(weather): wire render_weather_html to HTML chart

Replace _build_svg call with _build_chart_html. Update legend
swatches to match new design (tick-style normal/record, AQI
number indicators)."
```

---

### Task 4: Update existing tests for HTML output

**Files:**
- Modify: `tests/test_weather_display.py`

- [ ] **Step 1: Update test imports and SVG assertions**

Remove the SVG-specific imports from the top of the test file. Change:

```python
from modules.weather_display import (
    render_weather_html,
    _build_header_html,
    _build_legend_html,
    _build_text_fallback,
    _temp_to_y,
    _precip_to_height,
    _nice_step,
    _precip_marker,
    _shorten_condition,
    SVG_WIDTH,
    SVG_HEIGHT,
    ZONE2_TOP,
    ZONE2_BOTTOM,
    ZONE3_Y,
    ZONE4_BASELINE,
    ZONE5_Y,
    DAY_START_X,
    DAY_SPACING,
)
```

To:

```python
from modules.weather_display import (
    render_weather_html,
    _build_header_html,
    _build_legend_html,
    _build_chart_html,
    _build_text_fallback,
    _temp_to_pct,
    _aqi_position_pct,
    _aqi_color,
    _precip_color,
    _precip_marker,
    _shorten_condition,
    DAY_COUNT,
    AQI_SCALE_MAX,
)
```

Remove these test classes entirely (they test SVG-specific helpers that no longer exist):
- `TestTempToY`
- `TestPrecipToHeight`
- `TestNiceStep`

Update `TestRenderWeatherHtml` — replace all `assert "<svg" in html` with `assert "<table" in html`, and remove SVG-specific assertions:

```python
class TestRenderWeatherHtml:
    """Full render_weather_html integration tests."""

    def test_empty_weather(self):
        assert render_weather_html({}, _make_config()) == ""

    def test_no_forecast(self):
        assert render_weather_html({"city": "Logan"}, _make_config()) == ""

    def test_clear_skies_fixture(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "Logan, UT" in html
        assert "AQI 26" in html

    def test_inversion_fixture(self):
        weather = _load_fixture("weather_inversion.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "Action Day" in html

    def test_snow_fixture(self):
        weather = _load_fixture("weather_snow.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "❄" in html

    def test_thunderstorm_fixture(self):
        weather = _load_fixture("weather_thunderstorm.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "⚡" in html

    def test_mixed_fixture(self):
        weather = _load_fixture("weather_mixed.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "🌨" in html

    def test_minimal_fixture(self):
        weather = _load_fixture("weather_minimal.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "Logan, UT" in html

    def test_missing_aqi_fixture(self):
        weather = _load_fixture("weather_missing_aqi.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html

    def test_no_svg_in_output(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config())
        assert "<svg" not in html
        assert "viewBox" not in html

    def test_aqi_strip_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config(aqi_strip=False))
        # AQI numbers should still appear on bar (aqi_strip only controls legend)
        assert "<table" in html

    def test_record_band_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config(record_band=False))
        assert "<table" in html
        assert "211,47,47" not in html  # no record ticks

    def test_normal_band_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config(normal_band=False))
        assert "<table" in html
        assert "100,160,100" not in html  # no normal ticks

    def test_exception_falls_back_to_text(self):
        """Force an exception by passing bad data."""
        weather = {"forecast": [{"high_f": "not_a_number"}]}
        html = render_weather_html(weather, _make_config())
        assert isinstance(html, str)
```

Also update the `TestBuildLegendHtml` class — the default test should still pass. The `"AQI Good"` assertion needs updating since the legend format changed:

```python
class TestBuildLegendHtml:
    """Legend HTML generation."""

    def test_default_shows_all(self):
        weather = {"aqi": 26}
        html = _build_legend_html(weather, show_aqi=True, show_records=True)
        assert "Forecast Hi" in html
        assert "Forecast Lo" in html
        assert "Normal" in html
        assert "Record" in html
        assert "Precip" in html
        assert "AQI" in html

    def test_hide_aqi(self):
        weather = {}
        html = _build_legend_html(weather, show_aqi=False, show_records=True)
        assert "AQI" not in html

    def test_hide_records(self):
        weather = {}
        html = _build_legend_html(weather, show_aqi=True, show_records=False)
        assert "Record" not in html
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/test_weather_display.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_weather_display.py
git commit -m "test(weather): update all tests for HTML chart output

Remove SVG-specific test classes and imports. Update integration
tests to assert HTML table output. Verify no SVG elements in
output."
```

---

### Task 5: Run full test suite and push

**Files:** None (validation only)

- [ ] **Step 1: Run all weather tests**

Run: `pytest tests/test_weather_display.py tests/test_weather_core.py tests/test_weather_classify.py tests/test_weather_integration.py -v`
Expected: All PASS

- [ ] **Step 2: Run the full project test suite**

Run: `pytest tests/ -v --timeout=30`
Expected: All PASS. If any test outside weather references SVG constants (like `SVG_WIDTH`), it will fail — fix the import.

- [ ] **Step 3: Smoke test with real data**

Run: `python3 -c "
import json
from modules.weather_display import render_weather_html
weather = json.load(open('tests/fixtures/weather_clear.json'))
html = render_weather_html(weather, {})
print('Length:', len(html))
print('Has table:', '<table' in html)
print('No SVG:', '<svg' not in html)
print()
print(html[:500])
"`

Expected: HTML output with `<table`, no `<svg`.

- [ ] **Step 4: Push and clean up prototype files**

```bash
rm -f weather_options.html weather_options_v2.html weather_options_v3.html weather_options_final.html
git add -A
git commit -m "chore: remove weather chart prototype HTML files"
git push
```
