"""HTML email template for the Morning Digest.

Uses Jinja2 for rendering. The template is designed for Gmail/Proton Mail compatibility:
- CSS custom properties in :root drive all theming (supported in modern email clients)
- System fonts with web-safe fallbacks
"""

from pathlib import Path

from jinja2 import Environment, BaseLoader

_TEMPLATE_DIR = Path(__file__).parent
_DIGEST_CSS = (_TEMPLATE_DIR / "digest.css").read_text(encoding="utf-8")

# Security Layer 4: autoescape=True ensures all {{ }} interpolations are HTML-escaped
# by default. Fields that intentionally contain HTML (e.g. deep dive body) must be
# wrapped with markupsafe.Markup() by the caller AFTER sanitization — see stages/assemble.py.
_env = Environment(loader=BaseLoader(), autoescape=True)

EMAIL_TEMPLATE = _env.from_string("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<style>
{{ digest_css | safe }}
</style>
</head>
<body>

  <!-- HEADER -->
  <div class="wrapper">
  <div class="header">
    <div class="header-date">{{ date_display }}</div>
    <h1 class="header-title">Morning Digest</h1>
    <div class="header-sub">World · AI · Defense &amp; Space — curated for Aaron</div>
  </div>

  <!-- SPIRITUAL THOUGHT -->
  {% if spiritual %}
  <div class="spiritual">
    <div class="mono-label spiritual-ref">Come, Follow Me · {{ spiritual.date_range }} · {{ spiritual.reading }}</div>
    <div class="spiritual-text">"{{ spiritual.scripture_text }}"</div>
    <div class="spiritual-cite">— {{ spiritual.key_scripture }}</div>
    {% if spiritual.reflection %}
    <div class="spiritual-ctx">{{ spiritual.reflection }}</div>
    {% endif %}
  </div>
  {% endif %}

  <!-- WEATHER -->
   {% if weather_html %}
   <div class="bar" style="padding:12px 32px;">{{ weather_html }}</div>
  {% elif weather and weather.current_temp_f is not none %}
  <div class="bar">
    <span>{{ weather.city }}, {{ weather.state }} — {{ weather.condition }}{% if weather.aqi %} · AQI {{ weather.aqi }} ({{ weather.aqi_label }}){% endif %}</span>
    <span class="bar-mono" style="float:right;">{{ weather.current_temp_f }}°F</span>
    {% if weather.aqi and weather.aqi >= 151 %}
    <span class="aqi-warn" style="color:{% if weather.aqi >= 301 %}#7e0023{% elif weather.aqi >= 201 %}#8f3f97{% else %}#d32f2f{% endif %};">{% if weather.aqi >= 301 %}Maroon Action Day — Hazardous air quality. Everyone should avoid all outdoor activity.{% elif weather.aqi >= 201 %}Purple Action Day — Very Unhealthy. Avoid prolonged outdoor activity; sensitive groups should stay indoors.{% else %}Red Action Day — Unhealthy air quality. Everyone should limit prolonged outdoor activity.{% endif %}</span>
    {% endif %}
    {% if weather.forecast|length > 1 %}
    <br><span class="bar-detail">{% for day in weather.forecast[1:] %}{{ day.day_name }} {{ day.high_f }}°/{{ day.low_f }}° {{ day.condition }}{% if day.precip_chance >= 30 %} ({{ day.precip_chance }}%){% endif %}{% if not loop.last %} · {% endif %}{% endfor %}</span>
    {% endif %}
  </div>
  {% elif weather and weather.aqi is not none %}
  <div class="bar">
    <span>{{ weather.city or 'Logan' }}, {{ weather.state or 'UT' }} — forecast unavailable (NWS) · AQI {{ weather.aqi }} ({{ weather.aqi_label }})</span>
    {% if weather.aqi and weather.aqi >= 151 %}
    <span class="aqi-warn" style="color:{% if weather.aqi >= 301 %}#7e0023{% elif weather.aqi >= 201 %}#8f3f97{% else %}#d32f2f{% endif %};">{% if weather.aqi >= 301 %}Maroon Action Day — Hazardous air quality. Everyone should avoid all outdoor activity.{% elif weather.aqi >= 201 %}Purple Action Day — Very Unhealthy. Avoid prolonged outdoor activity; sensitive groups should stay indoors.{% else %}Red Action Day — Unhealthy air quality. Everyone should limit prolonged outdoor activity.{% endif %}</span>
    {% endif %}
  </div>
  {% endif %}

  <!-- MARKETS -->
  {% if markets %}
  <div class="bar">
    <table class="markets-table" role="presentation" cellpadding="0" cellspacing="0">
      <tr>
      {% for m in markets %}
      <td class="market-cell">
        <span class="mkt-label">{{ m.label }}</span>
        <span class="mkt-val">{{ m.price }}</span>
        <span class="{{ m.direction }}" aria-label="{{ 'up' if m.direction == 'up' else 'down' }} {{ m.change_pct|abs }}%"><span aria-hidden="true">{% if m.direction == 'up' %}▲{% else %}▼{% endif %}</span> {{ m.change_pct|abs }}%</span>
      </td>
      {% endfor %}
      </tr>
    </table>
    {% if market_context %}
    <div class="mkt-context">{{ market_context }}</div>
    {% endif %}
  </div>
  {% endif %}

  <!-- AT A GLANCE -->
  {% if at_a_glance %}
  <div class="section">
    <h2 class="mono-label sec-label">At a Glance</h2>
    {% for item in at_a_glance %}
    <div class="scan-item">
      <table class="scan-header-table" role="presentation" cellpadding="0" cellspacing="0">
        <tr>
          <td class="scan-tag-cell"><span class="mono-label tag tag-{{ item.tag }}">{{ item.tag_label }}</span></td>
          <td class="scan-headline-cell"><span class="scan-hl">{{ item.headline }}</span></td>
        </tr>
      </table>
      <div class="scan-ctx">{% if item.facts or item.analysis or item.cross_domain_note %}{% if item.facts %}<div class="scan-ctx-block"><span class="mono-label scan-voice scan-voice-src">Sources</span>{{ item.facts }}</div>{% endif %}{% if item.analysis %}<div class="scan-ctx-block scan-ctx-block-analysis"><span class="mono-label scan-voice scan-voice-analysis">Analysis</span>{{ item.analysis }}</div>{% endif %}{% if item.cross_domain_note %}<div class="scan-ctx-block scan-ctx-block-thread"><span class="mono-label scan-voice scan-voice-thread">Thread</span>{{ item.cross_domain_note }}</div>{% endif %}{% else %}{{ item.context }}{% endif %}</div>
      {% if item.seam_annotation %}
      <div class="scan-seam">{{ item.seam_annotation.one_line }}</div>
      {% endif %}
      {% if item.links %}
      <div class="scan-link">
        {% for link in item.links %}
        <a href="{{ link.url }}">{{ link.label }}</a>{% if not loop.last %} · {% endif %}
        {% endfor %}
      </div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% elif analysis_unavailable %}
  <div class="section">
    <h2 class="mono-label sec-label">At a Glance</h2>
    <div class="svc-notice">Analysis unavailable — the upstream LLM provider did not respond. Sources were collected successfully but could not be analyzed. Check the pipeline logs for details.</div>
  </div>
  {% endif %}

  <!-- CACHE VALLEY -->
  {% if local_items %}
  <div class="section">
    <h2 class="mono-label sec-label">Cache Valley</h2>
    {% for item in local_items %}
    <div class="local-item">
      {% if item is mapping %}
        {% set headline = item.headline or item.title %}
        {% set ctx = item.context or item.summary %}
        {% if item.url %}<a href="{{ item.url }}">{{ headline }}</a>{% else %}<strong>{{ headline }}</strong>{% endif %}
        {% if ctx %} — {{ ctx }}{% endif %}
      {% else %}
        {{ item }}
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- UTAH & WEST -->
  {% if regional_items %}
  <div class="section">
    <h2 class="mono-label sec-label">Utah &amp; West</h2>
    {% for item in regional_items %}
    <div class="local-item">
      {% if item is mapping %}
        {% set headline = item.headline or item.title %}
        {% set ctx = item.context or item.summary %}
        {% if item.url %}<a href="{{ item.url }}">{{ headline }}</a>{% else %}<strong>{{ headline }}</strong>{% endif %}
        {% if ctx %} — {{ ctx }}{% endif %}
      {% else %}
        {{ item }}
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}

   <!-- WORTH READING -->
   {% if worth_reading %}
   <div class="section">
     <h2 class="mono-label sec-label">Worth Reading</h2>
     {% for r in worth_reading %}
     <div class="weekend-item">
       <div class="wk-title"><a href="{{ r.url }}">{{ r.title }}</a></div>
       <div class="wk-meta">{{ r.source }} · {{ r.read_time }}</div>
       <div class="wk-desc">{{ r.description }}</div>
     </div>
     {% endfor %}
   </div>
   {% endif %}

   <!-- DEEP DIVES -->
   {% if deep_dives %}
   <div class="section">
     <h2 class="mono-label sec-label">Deep Dives</h2>
    {% for dive in deep_dives %}
    <div class="card">
      <h3 class="card-hl">{{ dive.headline }}</h3>
      <div class="card-body">{{ dive.body }}</div>
      {% if dive.why_it_matters %}
      <div class="wim">
        <div class="mono-label wim-label">Why It Matters</div>
        <p>{{ dive.why_it_matters }}</p>
      </div>
      {% endif %}
      {% if dive.further_reading %}
      <div class="fr">
        <div class="mono-label fr-label">Further Reading</div>
        {% for fr in dive.further_reading %}
        <div class="fr-item"><a href="{{ fr.url }}">{{ fr.label or fr.title }}{% if fr.source %} <span class="src">— {{ fr.source }}</span>{% endif %}</a></div>
        {% endfor %}
      </div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% elif analysis_unavailable %}
  <div class="section">
    <h2 class="mono-label sec-label">Deep Dives</h2>
    <div class="svc-notice">Deep dives unavailable — analysis could not be completed for this edition.</div>
  </div>
  {% endif %}

  <!-- WEEK AHEAD -->
  {% if week_ahead %}
  <div class="section">
    <h2 class="mono-label sec-label">Week Ahead</h2>
    {% for item in week_ahead %}
    <div class="cal-item"><span class="mono-label cal-date">{{ item.date or "TBD" }}</span> {{ item.event }}</div>
    {% endfor %}
  </div>
  {% endif %}

  {% if coverage_gap_diagnostics and coverage_gap_diagnostics.gaps %}
  <div class="section">
    <h2 class="mono-label sec-label">Coverage Gaps Diagnostic</h2>
    {% for gap in coverage_gap_diagnostics.gaps %}
    <div class="seam-item">
      <div class="seam-topic">{{ gap.topic }}</div>
      <div class="seam-desc">{{ gap.description }}</div>
      <div class="seam-sources">{{ gap.significance|upper }} · Likely miss: {{ gap.hypothesis }}</div>
      {% if gap.suggested_source_category %}
      <div class="seam-desc" style="margin-top:4px;">Suggested source category: {{ gap.suggested_source_category }}</div>
      {% endif %}
    </div>
    {% endfor %}
    {% if coverage_gap_diagnostics.recurring_patterns %}
    <div style="margin-top: 12px;">
      <div class="mono-label seam-sub">Recurring Patterns</div>
      {% for pattern in coverage_gap_diagnostics.recurring_patterns %}
      <div class="seam-desc">{{ pattern }}</div>
      {% endfor %}
    </div>
    {% endif %}
  </div>
  {% endif %}

  <!-- FOOTER -->
  <div class="footer">
    {% if stage_failures %}
    <div class="footer-failures">
      Pipeline notices:
      {% for failure in stage_failures %}
      {{ failure.stage }}{% if failure.error %} ({{ failure.error }}){% endif %}{% if not loop.last %}; {% endif %}
      {% endfor %}
    </div>
    {% endif %}
    Generated at {{ generated_at }}<br>
    Sources: {{ rss_source_names }}<br>
    {% if yt_source_names %}Analysis transcripts: {{ yt_source_names }}<br>{% endif %}
    Come Follow Me: churchofjesuschrist.org · Markets: Finnhub<br>
  </div>

  </div><!-- /.wrapper -->

</body>
</html>
""")


def render_email(data: dict) -> str:
    """Render the digest email from structured data.

    Deep dive body fields must be wrapped with markupsafe.Markup() by the caller
    before being passed here, so Jinja2 autoescape renders them as HTML rather than
    escaping the tags as literal text.
    """
    return EMAIL_TEMPLATE.render(**data, digest_css=_DIGEST_CSS)
