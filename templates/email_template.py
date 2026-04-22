"""HTML email template for the Morning Digest.

Uses Jinja2 for rendering. The template is designed for Gmail/Proton Mail compatibility:
- CSS custom properties in :root drive all theming (supported in modern email clients)
- System fonts with web-safe fallbacks
"""

from jinja2 import Environment, BaseLoader

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
  /* ── Light palette (default) ─────────────────────────────── */
  :root {
    --bg-page:    #e8e6e2;
    --bg-wrap:    #faf9f7;
    --bg-tinted:  #f7f5f0;
    --bg-bar:     #f2f0ec;
    --bg-card:    #ffffff;
    --bg-wim:     #f5ebe6;
    --bg-chrome:  #1a1a1a;

    --border:     #e5e2dd;

    --text:           #1a1a1a;
    --text-body:      #444444;
    --text-secondary: #555555;
    --text-muted:     #666666;
    --text-faint:     #888888;

    --text-chrome:      #ffffff;
    --text-chrome-dim:  #999999;
    --text-chrome-muted:#aaaaaa;
    --text-chrome-link: #cccccc;

    --accent:      #c05028;
    --accent-seam: #7b241c;

    --link:        #1b4f72;
    --link-subtle: #666666;
    --link-border: #aaaaaa;

    --up:   #1e8449;
    --down: #c0392b;

    --tag-war-text: #78281f;  --tag-war-bg: #f9ebea;
    --tag-ai-text:  #6c3483;  --tag-ai-bg:  #ebdef0;
    --tag-domestic-text: #7d6608; --tag-domestic-bg: #fef9e7;
    --tag-defense-text:  #1b4f72; --tag-defense-bg:  #d4e6f1;
    --tag-space-text:    #1a5276; --tag-space-bg:    #d6eaf8;
    --tag-tech-text:     #4a235a; --tag-tech-bg:     #f4ecf7;
    --tag-local-text:    #1e8449; --tag-local-bg:    #d5f5e3;
    --tag-science-text:  #7e5109; --tag-science-bg:  #fef5e7;
    --tag-econ-text:     #1a5276; --tag-econ-bg:     #d4efdf;
    --tag-cyber-text:    #633974; --tag-cyber-bg:    #f5eef8;
    --tag-energy-text:   #784212; --tag-energy-bg:   #fdebd0;
    --tag-biotech-text:  #0e6251; --tag-biotech-bg:  #d1f2eb;

    /* Weather display */
    --wx-bg:         #f7f5f0;
    --wx-hi:         #c07830;
    --wx-lo:         #4a6a90;
    --wx-normal:     rgba(80,140,80,0.45);
    --wx-record:     rgba(192,57,43,0.35);
    --wx-precip:     #5b9bd5;
    --wx-snow:       #a0d4f0;
    --wx-thunder:    #8f3f97;
    --wx-frz:        #e06040;
    --wx-grid:       #d8d5d0;
    --wx-label:      #555555;
    --wx-label-dim:  #888888;
  }

  /* ── Layout ──────────────────────────────────────────────── */
  body { margin: 0; padding: 0; background: var(--bg-page); font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: var(--text); line-height: 1.6; }
  h1, h2, h3 { margin: 0; padding: 0; font-size: inherit; font-weight: inherit; line-height: inherit; }
  .wrapper { max-width: 680px; margin: 0 auto; background: var(--bg-wrap); }
  .mono-label { font-family: 'Courier New', monospace; font-weight: 600; text-transform: uppercase; }

  /* ── Header ──────────────────────────────────────────────── */
  .header { background: var(--bg-chrome); color: var(--text-chrome); padding: 28px 32px 24px; }
  .header-date { font-family: 'Courier New', monospace; font-size: 12px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-chrome-dim); margin-bottom: 6px; }
  .header-title { font-family: Georgia, 'Times New Roman', serif; font-size: 28px; font-weight: 700; letter-spacing: -0.5px; line-height: 1.2; }
  .header-sub { font-size: 13px; color: var(--text-chrome-muted); margin-top: 4px; }

  /* ── Spiritual ───────────────────────────────────────────── */
  .spiritual { padding: 20px 32px; background: var(--bg-tinted); border-bottom: 1px solid var(--border); }
  .spiritual-ref { font-size: 10px; letter-spacing: 1.5px; color: var(--text-muted); margin-bottom: 8px; }
  .spiritual-text { font-family: Georgia, serif; font-size: 16px; line-height: 1.65; font-style: italic; color: var(--text); }
  .spiritual-cite { font-size: 14px; color: var(--text-secondary); margin-top: 6px; font-style: normal; }
  .spiritual-ctx { font-size: 14px; color: var(--text-muted); margin-top: 8px; }

  /* ── Info bars (weather, markets) ───────────────────────── */
  .bar { padding: 12px 32px; background: var(--bg-bar); border-bottom: 1px solid var(--border); font-size: 14px; color: var(--text-secondary); }
  .bar-mono { font-family: 'Courier New', monospace; font-weight: 500; color: var(--text); }
  .bar-detail { font-size: 13px; color: var(--text-muted); }
  .wx-header { font-family: monospace; font-size: 13px; color: var(--wx-label, #555); margin-bottom: 4px; }
  .wx-date { color: var(--wx-label-dim, #888); font-size: 11px; text-align: right; }
  .wx-legend { font-family: monospace; margin: 4px 0 2px 0; }
  .wx-legend-title { font-size: 9px; color: #888; padding-right: 6px; white-space: nowrap; }
  .wx-legend-item { padding-right: 10px; white-space: nowrap; }
  .wx-legend-swatch { display: inline-block; width: 8px; height: 8px; border-radius: 2px; vertical-align: middle; margin-right: 3px; }
  .wx-legend-label { font-size: 9px; color: #666; }
  .wx-chart { width: 100%; border-collapse: collapse; margin-top: 8px; }
  .wx-day-cell { width: 32px; font-size: 9px; font-weight: 600; color: #555555; padding: 5px 6px 0 0; vertical-align: top; }
  .wx-temp-cell { width: 28px; font-size: 8px; padding-top: 6px; vertical-align: top; }
  .wx-lo-temp { color: #4a6a90; text-align: right; padding-right: 5px; }
  .wx-hi-temp { color: #c07830; padding-left: 5px; }
  .wx-gradient-cell { padding: 5px 4px 0; vertical-align: top; }
  .wx-temp-bar { width: 100%; border-collapse: collapse; height: 14px; background: #d8d5d0; border-radius: 6px; }
  .wx-bar-row { height: 14px; }
  .wx-bar-pad { height: 14px; padding: 0; font-size: 0; line-height: 0; }
  .wx-bar-fill { height: 14px; padding: 0; font-size: 0; line-height: 0; background: linear-gradient(to right, rgba(90,122,160,0.35), rgba(208,144,80,0.40)); border-radius: 6px; }
  .wx-condition-cell { width: 60px; font-size: 9px; color: #666666; text-align: right; padding: 6px 0 0 4px; vertical-align: top; }
  .wx-precip-cell { padding: 1px 4px 5px; }
  .markets-table { width: 100%; border-collapse: collapse; font-family: 'Courier New', monospace; font-size: 13px; }
  .market-cell { padding: 0 18px 0 0; white-space: nowrap; vertical-align: baseline; }
  .market-cell:last-child { padding-right: 0; }
  .mkt-context { font-size: 13px; color: var(--text-secondary); margin-top: 8px; line-height: 1.5; font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
  .mkt-label { color: var(--text-muted); }
  .mkt-val { color: var(--text); font-weight: 500; }
  .up { color: var(--up); }
  .down { color: var(--down); }

  /* ── Sections ────────────────────────────────────────────── */
  .section { padding: 24px 32px; border-bottom: 1px solid var(--border); }
  .sec-label { font-size: 11px; letter-spacing: 2px; color: var(--accent); margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }

  /* ── At a Glance ─────────────────────────────────────────── */
  .scan-item { padding: 10px 0; border-bottom: 1px solid var(--border); }
  .scan-item:last-child { border-bottom: none; }
  .scan-header-table { width: 100%; border-collapse: collapse; margin-bottom: 3px; }
  .scan-tag-cell { width: 1%; padding: 2px 8px 0 0; vertical-align: top; white-space: nowrap; }
  .scan-headline-cell { padding: 0; vertical-align: top; }
  .tag { font-size: 11px; letter-spacing: 1px; padding: 2px 7px; border-radius: 3px; display: inline-block; margin-top: 2px; }
  .tag-war      { color: var(--tag-war-text);      background: var(--tag-war-bg); }
  .tag-ai       { color: var(--tag-ai-text);       background: var(--tag-ai-bg); }
  .tag-domestic { color: var(--tag-domestic-text); background: var(--tag-domestic-bg); }
  .tag-defense  { color: var(--tag-defense-text);  background: var(--tag-defense-bg); }
  .tag-space    { color: var(--tag-space-text);    background: var(--tag-space-bg); }
  .tag-tech     { color: var(--tag-tech-text);     background: var(--tag-tech-bg); }
  .tag-local    { color: var(--tag-local-text);    background: var(--tag-local-bg); }
  .tag-science  { color: var(--tag-science-text);  background: var(--tag-science-bg); }
  .tag-econ     { color: var(--tag-econ-text);     background: var(--tag-econ-bg); }
  .tag-cyber    { color: var(--tag-cyber-text);    background: var(--tag-cyber-bg); }
  .tag-energy   { color: var(--tag-energy-text);   background: var(--tag-energy-bg); }
  .tag-biotech  { color: var(--tag-biotech-text);  background: var(--tag-biotech-bg); }
  .scan-hl { font-size: 15px; font-weight: 600; line-height: 1.4; }
  .scan-ctx { font-size: 14px; color: var(--text-secondary); line-height: 1.45; }
  .scan-ctx-block { margin-bottom: 6px; padding-left: 8px; border-left: 2px solid transparent; }
  .scan-ctx-block:last-child { margin-bottom: 0; }
  .scan-ctx-block-analysis { border-left-color: var(--border); }
  .scan-ctx-block-thread   { border-left-color: var(--accent-seam); }
  .scan-voice { font-size: 9px; letter-spacing: 1px; display: inline-block; min-width: 6.5ch; padding-right: 4px; vertical-align: baseline; }
  .scan-voice-src      { color: var(--text-faint); }
  .scan-voice-analysis { color: var(--text-muted); }
  .scan-voice-thread   { color: var(--accent-seam); }
  .scan-seam { margin-top: 7px; padding-left: 8px; border-left: 2px solid var(--wx-grid, #d8d5d0); color: var(--wx-label, #555555); font-size: 13px; line-height: 1.45; font-style: italic; }
  .aqi-warn { font-size: 13px; font-weight: 600; display: block; margin-top: 3px; }
  .scan-link { font-size: 13px; color: var(--link-subtle); margin-top: 4px; }
  .scan-link a { color: var(--link-subtle); text-decoration: none; border-bottom: 1px dotted var(--link-border); }

  /* ── Local / Calendar ───────────────────────────────────── */
  .local-item { padding: 6px 0; font-size: 14px; color: var(--text-secondary); line-height: 1.5; }
  .local-item strong { color: var(--text); font-weight: 500; }
  .local-item a { color: var(--link); text-decoration: none; font-weight: 500; border-bottom: 1px dotted var(--link-border); }
  .cal-item { padding: 6px 0; font-size: 14px; color: var(--text-secondary); display: flex; align-items: baseline; gap: 10px; }
  .cal-date { font-size: 10px; letter-spacing: 0.5px; color: var(--text-chrome); background: var(--bg-chrome); padding: 2px 7px; border-radius: 3px; flex-shrink: 0; }

  /* ── Deep Dive cards ─────────────────────────────────────── */
  .card { background: var(--bg-card); border: 1px solid var(--border); border-top: 3px solid var(--accent); border-radius: 0 0 6px 6px; padding: 20px 24px; margin-bottom: 16px; }
  .card:last-child { margin-bottom: 0; }
  .card-hl { font-family: Georgia, serif; font-size: 19px; font-weight: 700; line-height: 1.3; margin-bottom: 10px; letter-spacing: -0.3px; }
  .card-body { font-size: 15px; color: var(--text-body); line-height: 1.65; }
  .card-body p { margin: 0 0 10px 0; }
  .card-body p:last-child { margin-bottom: 0; }
  .wim { background: var(--bg-wim); border-left: 3px solid var(--accent); padding: 10px 14px; margin-top: 12px; border-radius: 0 4px 4px 0; }
  .wim-label { font-size: 10px; letter-spacing: 1.5px; color: var(--accent); margin-bottom: 4px; }
  .wim p { font-size: 14px; color: var(--text); line-height: 1.55; margin: 0; }
  .fr { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
  .fr-label { font-size: 10px; letter-spacing: 1.5px; color: var(--text-muted); margin-bottom: 6px; }
  .fr-item { padding: 5px 0; border-top: 1px dotted var(--border); }
  .fr-item:first-of-type { border-top: none; }
  .fr a { display: block; font-size: 14px; color: var(--link); text-decoration: none; line-height: 1.5; }
  .fr .src { color: var(--text-muted); font-size: 13px; }

  /* ── Perspective Seams ───────────────────────────────────── */
  .seam-sub { font-size: 10px; letter-spacing: 1.5px; color: var(--accent-seam); margin-bottom: 10px; }
  .seam-item { padding: 10px 0; border-bottom: 1px solid var(--border); }
  .seam-item:last-child { border-bottom: none; }
  .seam-topic { font-size: 15px; font-weight: 600; line-height: 1.4; margin-bottom: 3px; }
  .seam-desc { font-size: 14px; color: var(--text-secondary); line-height: 1.45; }
  .seam-sources { font-size: 13px; color: var(--text-faint); margin-top: 4px; font-style: italic; }

  /* ── Weekend reads ───────────────────────────────────────── */
  .weekend-item { padding: 8px 0; border-bottom: 1px solid var(--border); }
  .weekend-item:last-child { border-bottom: none; }
  .wk-title { font-size: 15px; font-weight: 500; }
  .wk-title a { color: var(--link); text-decoration: none; }
  .wk-meta { font-size: 13px; color: var(--text-muted); margin-top: 2px; }
  .wk-desc { font-size: 14px; color: var(--text-secondary); margin-top: 3px; line-height: 1.45; }

  /* ── Service notice ──────────────────────────────────────── */
  .svc-notice { padding: 16px 20px; background: #fef9e7; border: 1px solid #f0e0a0; border-radius: 4px; font-size: 14px; color: #7d6608; line-height: 1.5; }

  /* ── Footer ─────────────────────────────────────────────── */
  .footer { padding: 20px 32px; background: var(--bg-chrome); color: var(--text-chrome-muted); font-size: 11px; line-height: 1.6; text-align: center; }
  .footer a { color: var(--text-chrome-link); text-decoration: none; }

  @media (max-width: 480px) {
    .header { padding: 24px 16px 20px; }
    .spiritual { padding: 18px 16px; }
    .bar { padding: 12px 16px; }
    .section { padding: 22px 16px; }
    .footer { padding: 18px 16px; }
    .card { padding: 18px 16px; }
    .market-cell { display: block; padding: 0 0 4px 0; }
  }
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
    return EMAIL_TEMPLATE.render(**data)
