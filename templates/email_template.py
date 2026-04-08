"""HTML email template for the Morning Digest.

Uses Jinja2 for rendering. The template is designed for Gmail/Proton Mail compatibility:
- CSS custom properties for theming (supported in modern email clients)
- @media (prefers-color-scheme: dark) for automatic dark mode in Proton Mail / Apple Mail
- JS-injected toggle for the browser dry-run HTML; stripped by email clients so no dead button
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

<!-- Flash prevention: read localStorage before first paint so browser never flashes wrong theme -->
<script>
(function(){try{var t=localStorage.getItem('md-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();
</script>

<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=DM+Sans:wght@400;500;600&display=swap');
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

    /* Weather display */
    --wx-bg:         #f7f5f0;
    --wx-hi:         #d09050;
    --wx-lo:         #5a7aa0;
    --wx-normal:     rgba(100,160,100,0.18);
    --wx-record:     rgba(255,255,255,0.04);
    --wx-precip:     #5b9bd5;
    --wx-snow:       #a0d4f0;
    --wx-thunder:    #8f3f97;
    --wx-frz:        #e06040;
    --wx-grid:       #1e1e22;
    --wx-label:      #555555;
    --wx-label-dim:  #888888;
  }

  /* ── Dark palette — system preference (Proton Mail / Apple Mail) ── */
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg-page:    #141210;
      --bg-wrap:    #1c1a17;
      --bg-tinted:  #222018;
      --bg-bar:     #222018;
      --bg-card:    #242220;
      --bg-wim:     #2a1f18;
      --bg-chrome:  #0e0d0b;

      --border:     #2e2b27;

      --text:           #e8e5e1;
      --text-body:      #c8c5c0;
      --text-secondary: #b0ada8;
      --text-muted:     #888582;
      --text-faint:     #888582;

      --text-chrome:       #e8e5e1;
      --text-chrome-dim:   #888582;
      --text-chrome-muted: #888582;
      --text-chrome-link:  #b0ada8;

      --accent:      #d4643a;
      --accent-seam: #d4643a;

      --link:        #7ab4e8;
      --link-subtle: #888582;
      --link-border: #3e3c39;

      --up:   #2ebd69;
      --down: #e05252;

      --tag-war-text: #f4a5a5;  --tag-war-bg: #3d1410;
      --tag-ai-text:  #d4a8f0;  --tag-ai-bg:  #2d1440;
      --tag-domestic-text: #e8d060; --tag-domestic-bg: #2a2206;
      --tag-defense-text:  #7ab4e8; --tag-defense-bg:  #0f2a3d;
      --tag-space-text:    #7ab4e8; --tag-space-bg:    #0f2a3d;
      --tag-tech-text:     #c89ae0; --tag-tech-bg:     #221030;
      --tag-local-text:    #5dd88a; --tag-local-bg:    #0d2e1a;
      --tag-science-text:  #e8b860; --tag-science-bg:  #281a06;
      --tag-econ-text:     #7ab4e8; --tag-econ-bg:     #0f2a3d;
      --tag-cyber-text:    #c89ae0; --tag-cyber-bg:    #221030;

      /* Weather display */
      --wx-bg:         #1c1a17;
      --wx-hi:         #d09050;
      --wx-lo:         #5a7aa0;
      --wx-normal:     rgba(100,160,100,0.18);
      --wx-record:     rgba(255,255,255,0.04);
      --wx-precip:     #5b9bd5;
      --wx-snow:       #a0d4f0;
      --wx-thunder:    #8f3f97;
      --wx-frz:        #e06040;
      --wx-grid:       #1e1e22;
      --wx-label:      #b0ada8;
      --wx-label-dim:  #888582;
    }
  }

  /* ── Dark palette — explicit JS override (browser only) ──── */
  [data-theme="dark"] {
    --bg-page:    #141210;
    --bg-wrap:    #1c1a17;
    --bg-tinted:  #222018;
    --bg-bar:     #222018;
    --bg-card:    #242220;
    --bg-wim:     #2a1f18;
    --bg-chrome:  #0e0d0b;

    --border:     #2e2b27;

    --text:           #e8e5e1;
    --text-body:      #c8c5c0;
    --text-secondary: #b0ada8;
    --text-muted:     #888582;
    --text-faint:     #5e5c59;

    --text-chrome:       #e8e5e1;
    --text-chrome-dim:   #5e5c59;
    --text-chrome-muted: #888582;
    --text-chrome-link:  #b0ada8;

    --accent:      #d4643a;
    --accent-seam: #d4643a;

    --link:        #7ab4e8;
    --link-subtle: #888582;
    --link-border: #3e3c39;

    --up:   #2ebd69;
    --down: #e05252;

    --tag-war-text: #f4a5a5;  --tag-war-bg: #3d1410;
    --tag-ai-text:  #d4a8f0;  --tag-ai-bg:  #2d1440;
    --tag-domestic-text: #e8d060; --tag-domestic-bg: #2a2206;
    --tag-defense-text:  #7ab4e8; --tag-defense-bg:  #0f2a3d;
    --tag-space-text:    #7ab4e8; --tag-space-bg:    #0f2a3d;
    --tag-tech-text:     #c89ae0; --tag-tech-bg:     #221030;
    --tag-local-text:    #5dd88a; --tag-local-bg:    #0d2e1a;
    --tag-science-text:  #e8b860; --tag-science-bg:  #281a06;
    --tag-econ-text:     #7ab4e8; --tag-econ-bg:     #0f2a3d;
    --tag-cyber-text:    #c89ae0; --tag-cyber-bg:    #221030;

    /* Weather display */
    --wx-bg:         #1c1a17;
    --wx-hi:         #d09050;
    --wx-lo:         #5a7aa0;
    --wx-normal:     rgba(100,160,100,0.18);
    --wx-record:     rgba(255,255,255,0.04);
    --wx-precip:     #5b9bd5;
    --wx-snow:       #a0d4f0;
    --wx-thunder:    #8f3f97;
    --wx-frz:        #e06040;
    --wx-grid:       #1e1e22;
    --wx-label:      #b0ada8;
    --wx-label-dim:  #888582;
  }

  /* ── Light override — lets a dark-system user switch back ── */
  [data-theme="light"] {
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

    --text-chrome:       #ffffff;
    --text-chrome-dim:   #999999;
    --text-chrome-muted: #aaaaaa;
    --text-chrome-link:  #cccccc;

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

    /* Weather display */
    --wx-bg:         #f7f5f0;
    --wx-hi:         #d09050;
    --wx-lo:         #5a7aa0;
    --wx-normal:     rgba(100,160,100,0.18);
    --wx-record:     rgba(255,255,255,0.04);
    --wx-precip:     #5b9bd5;
    --wx-snow:       #a0d4f0;
    --wx-thunder:    #8f3f97;
    --wx-frz:        #e06040;
    --wx-grid:       #1e1e22;
    --wx-label:      #555555;
    --wx-label-dim:  #888888;
  }

  /* ── Layout ──────────────────────────────────────────────── */
  body { margin: 0; padding: 0; background: var(--bg-page); font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: var(--text); line-height: 1.6; }
  h1, h2, h3 { margin: 0; padding: 0; font-size: inherit; font-weight: inherit; line-height: inherit; }
  .wrapper { max-width: 680px; margin: 0 auto; background: var(--bg-wrap); }

  /* Theme toggle bar — injected by JS, invisible in email clients */
  .theme-bar { padding: 6px 32px; text-align: right; background: var(--bg-chrome); border-bottom: 1px solid rgba(255,255,255,0.05); }
  .theme-btn { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; background: transparent; border: 1px solid var(--border); color: var(--text-muted); padding: 4px 10px; border-radius: 3px; cursor: pointer; }
  .theme-btn:hover { color: var(--text); border-color: var(--text-muted); }

  /* ── Header ──────────────────────────────────────────────── */
  .header { background: var(--bg-chrome); color: var(--text-chrome); padding: 28px 32px 24px; }
  .header-date { font-family: 'Courier New', monospace; font-size: 12px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-chrome-dim); margin-bottom: 6px; }
  .header-title { font-family: Georgia, 'Times New Roman', serif; font-size: 28px; font-weight: 700; letter-spacing: -0.5px; line-height: 1.2; }
  .header-sub { font-size: 13px; color: var(--text-chrome-muted); margin-top: 4px; }

  /* ── Spiritual ───────────────────────────────────────────── */
  .spiritual { padding: 20px 32px; background: var(--bg-tinted); border-bottom: 1px solid var(--border); }
  .spiritual-ref { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px; }
  .spiritual-text { font-family: Georgia, serif; font-size: 16px; line-height: 1.65; font-style: italic; color: var(--text); }
  .spiritual-cite { font-size: 14px; color: var(--text-secondary); margin-top: 6px; font-style: normal; }
  .spiritual-ctx { font-size: 14px; color: var(--text-muted); margin-top: 8px; }

  /* ── Info bars (weather, markets) ───────────────────────── */
  .bar { padding: 12px 32px; background: var(--bg-bar); border-bottom: 1px solid var(--border); font-size: 14px; color: var(--text-secondary); }
  .bar-mono { font-family: 'Courier New', monospace; font-weight: 500; color: var(--text); }
  .bar-detail { font-size: 13px; color: var(--text-muted); }
  .markets { font-family: 'Courier New', monospace; font-size: 13px; display: flex; gap: 18px; flex-wrap: wrap; }
  .mkt-context { font-size: 13px; color: var(--text-secondary); margin-top: 8px; line-height: 1.5; font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
  .mkt-label { color: var(--text-muted); }
  .mkt-val { color: var(--text); font-weight: 500; }
  .up { color: var(--up); }
  .down { color: var(--down); }

  /* ── Sections ────────────────────────────────────────────── */
  .section { padding: 24px 32px; border-bottom: 1px solid var(--border); }
  .sec-label { font-family: 'Courier New', monospace; font-size: 11px; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; color: var(--accent); margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }

  /* ── At a Glance ─────────────────────────────────────────── */
  .scan-item { padding: 10px 0; border-bottom: 1px solid var(--border); }
  .scan-item:last-child { border-bottom: none; }
  .scan-header { display: flex; align-items: flex-start; flex-wrap: nowrap; gap: 8px; margin-bottom: 3px; }
  .tag { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; padding: 2px 7px; border-radius: 3px; display: inline-block; flex-shrink: 0; margin-top: 2px; }
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
  .scan-hl { flex: 1; min-width: 0; font-size: 15px; font-weight: 600; line-height: 1.4; }
  .scan-ctx { font-size: 14px; color: var(--text-secondary); line-height: 1.45; }
  .scan-ctx-block { margin-bottom: 6px; padding-left: 8px; border-left: 2px solid transparent; }
  .scan-ctx-block:last-child { margin-bottom: 0; }
  .scan-ctx-block-analysis { border-left-color: var(--border); }
  .scan-ctx-block-thread   { border-left-color: var(--accent-seam); opacity: 0.9; }
  .scan-voice { font-family: 'Courier New', monospace; font-size: 9px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; display: inline-block; min-width: 6.5ch; padding-right: 4px; vertical-align: baseline; }
  .scan-voice-src      { color: var(--text-faint); }
  .scan-voice-analysis { color: var(--text-muted); }
  .scan-voice-thread   { color: var(--accent-seam); }
  .aqi-warn { font-size: 13px; font-weight: 600; display: block; margin-top: 3px; }
  .scan-link { font-size: 13px; color: var(--link-subtle); margin-top: 4px; }
  .scan-link a { color: var(--link-subtle); text-decoration: none; border-bottom: 1px dotted var(--link-border); }

  /* ── Local / Calendar ───────────────────────────────────── */
  .local-item { padding: 6px 0; font-size: 14px; color: var(--text-secondary); line-height: 1.5; }
  .local-item strong { color: var(--text); font-weight: 500; }
  .local-item a { color: var(--link); text-decoration: none; font-weight: 500; border-bottom: 1px dotted var(--link-border); }
  .cal-item { padding: 6px 0; font-size: 14px; color: var(--text-secondary); display: flex; align-items: baseline; gap: 10px; }
  .cal-date { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; color: var(--text-chrome); background: var(--bg-chrome); padding: 2px 7px; border-radius: 3px; flex-shrink: 0; }

  /* ── Deep Dive cards ─────────────────────────────────────── */
  .card { background: var(--bg-card); border: 1px solid var(--border); border-top: 3px solid var(--accent); border-radius: 0 0 6px 6px; padding: 20px 24px; margin-bottom: 16px; }
  .card:last-child { margin-bottom: 0; }
  .card-hl { font-family: Georgia, serif; font-size: 19px; font-weight: 700; line-height: 1.3; margin-bottom: 10px; letter-spacing: -0.3px; }
  .card-body { font-size: 15px; color: var(--text-body); line-height: 1.65; }
  .card-body p { margin: 0 0 10px 0; }
  .card-body p:last-child { margin-bottom: 0; }
  .wim { background: var(--bg-wim); border-left: 3px solid var(--accent); padding: 10px 14px; margin-top: 12px; border-radius: 0 4px 4px 0; }
  .wim-label { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent); margin-bottom: 4px; }
  .wim p { font-size: 14px; color: var(--text); line-height: 1.55; margin: 0; }
  .fr { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
  .fr-label { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 6px; }
  .fr a { display: block; font-size: 14px; color: var(--link); text-decoration: none; line-height: 1.5; margin-bottom: 2px; }
  .fr .src { color: var(--text-muted); font-size: 13px; }

  /* ── Perspective Seams ───────────────────────────────────── */
  .seam-sub { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent-seam); margin-bottom: 10px; }
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

  /* ── Footer ─────────────────────────────────────────────── */
  .footer { padding: 20px 32px; background: var(--bg-chrome); color: var(--text-chrome-muted); font-size: 11px; line-height: 1.6; text-align: center; }
  .footer a { color: var(--text-chrome-link); text-decoration: none; }
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
    <div class="spiritual-ref">Come, Follow Me · {{ spiritual.date_range }} · {{ spiritual.reading }}</div>
    <div class="spiritual-text">"{{ spiritual.scripture_text }}"</div>
    <div class="spiritual-cite">— {{ spiritual.key_scripture }}</div>
    {% if spiritual.reflection %}
    <div class="spiritual-ctx">{{ spiritual.reflection }}</div>
    {% endif %}
  </div>
  {% endif %}

  <!-- WEATHER -->
   {% if weather_html %}
   <div class="bar" style="padding:12px 32px;">{{ weather_html|safe }}</div>
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
  {% endif %}

  <!-- MARKETS -->
  {% if markets %}
  <div class="bar">
    <div class="markets">
      {% for m in markets %}
      <span>
        <span class="mkt-label">{{ m.label }}</span>
        <span class="mkt-val">{{ m.price }}</span>
        <span class="{{ m.direction }}" aria-label="{{ 'up' if m.direction == 'up' else 'down' }} {{ m.change_pct|abs }}%"><span aria-hidden="true">{% if m.direction == 'up' %}▲{% else %}▼{% endif %}</span> {{ m.change_pct|abs }}%</span>
      </span>
      {% endfor %}
    </div>
    {% if market_context %}
    <div class="mkt-context">{{ market_context }}</div>
    {% endif %}
  </div>
  {% endif %}

  <!-- AT A GLANCE -->
  {% if at_a_glance %}
  <div class="section">
    <h2 class="sec-label">At a Glance</h2>
    {% for item in at_a_glance %}
    <div class="scan-item">
      <div class="scan-header">
        <span class="tag tag-{{ item.tag }}">{{ item.tag_label }}</span>
        <span class="scan-hl">{{ item.headline }}</span>
      </div>
      <div class="scan-ctx">{% if item.facts or item.analysis or item.cross_domain_note %}{% if item.facts %}<div class="scan-ctx-block"><span class="scan-voice scan-voice-src">Sources</span>{{ item.facts }}</div>{% endif %}{% if item.analysis %}<div class="scan-ctx-block scan-ctx-block-analysis"><span class="scan-voice scan-voice-analysis">Analysis</span>{{ item.analysis }}</div>{% endif %}{% if item.cross_domain_note %}<div class="scan-ctx-block scan-ctx-block-thread"><span class="scan-voice scan-voice-thread">Thread</span>{{ item.cross_domain_note }}</div>{% endif %}{% else %}{{ item.context }}{% endif %}</div>
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
  {% endif %}

  <!-- CACHE VALLEY -->
  {% if local_items %}
  <div class="section">
    <h2 class="sec-label">Cache Valley</h2>
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

  <!-- DEEP DIVES -->
  {% if deep_dives %}
  <div class="section">
    <h2 class="sec-label">Deep Dives</h2>
    {% for dive in deep_dives %}
    <div class="card">
      <h3 class="card-hl">{{ dive.headline }}</h3>
      <div class="card-body">{{ dive.body }}</div>
      {% if dive.why_it_matters %}
      <div class="wim">
        <div class="wim-label">Why It Matters</div>
        <p>{{ dive.why_it_matters }}</p>
      </div>
      {% endif %}
      {% if dive.further_reading %}
      <div class="fr">
        <div class="fr-label">Further Reading</div>
        {% for fr in dive.further_reading %}
        <a href="{{ fr.url }}">{{ fr.label or fr.title }}{% if fr.source %} <span class="src">— {{ fr.source }}</span>{% endif %}</a>
        {% endfor %}
      </div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- PERSPECTIVE SEAMS -->
  {% if contested_narratives or coverage_gaps %}
  <div class="section">
    <h2 class="sec-label">Perspective Seams</h2>

    {% if contested_narratives %}
    <div style="margin-bottom: 16px;">
      <div class="seam-sub">Contested Narratives</div>
      {% for cn in contested_narratives %}
      <div class="seam-item">
        <div class="seam-topic">{{ cn.topic }}</div>
        <div class="seam-desc">{{ cn.description }}</div>
        <div class="seam-sources">{{ cn.sources_a }} vs. {{ cn.sources_b }}</div>
        {% if cn.analytical_significance %}
        <div class="seam-desc" style="margin-top:4px; font-style:italic;">{{ cn.analytical_significance }}</div>
        {% endif %}
        {% if cn.links %}
        <div class="scan-link" style="margin-top:4px;">{% for link in cn.links %}<a href="{{ link.url }}">{{ link.label }}</a>{% if not loop.last %} · {% endif %}{% endfor %}</div>
        {% endif %}
      </div>
      {% endfor %}
    </div>
    {% endif %}

    {% if coverage_gaps %}
    <div>
      <div class="seam-sub">Covered There, Not Here</div>
      {% for cg in coverage_gaps %}
      <div class="seam-item">
        <div class="seam-topic">{{ cg.topic }}</div>
        <div class="seam-desc">{{ cg.description }}</div>
        <div class="seam-sources">Present in {{ cg.present_in }} · Absent from {{ cg.absent_from }}</div>
        {% if cg.links %}
        <div class="scan-link" style="margin-top:4px;">{% for link in cg.links %}<a href="{{ link.url }}">{{ link.label }}</a>{% if not loop.last %} · {% endif %}{% endfor %}</div>
        {% endif %}
      </div>
      {% endfor %}
    </div>
    {% endif %}
  </div>
  {% endif %}

  <!-- WEEK AHEAD -->
  {% if week_ahead %}
  <div class="section">
    <h2 class="sec-label">Week Ahead</h2>
    {% for item in week_ahead %}
    <div class="cal-item"><span class="cal-date">{{ item.date or "TBD" }}</span> {{ item.event }}</div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- WEEKEND READS (Friday only) -->
  {% if weekend_reads %}
  <div class="section">
    <h2 class="sec-label">Weekend Reading · Friday Edition</h2>
    {% for r in weekend_reads %}
    <div class="weekend-item">
      <div class="wk-title"><a href="{{ r.url }}">{{ r.title }}</a></div>
      <div class="wk-meta">{{ r.source }} · {{ r.read_time }}</div>
      <div class="wk-desc">{{ r.description }}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- KEY ASSUMPTIONS CHECK -->
  {% if key_assumptions %}
  <div class="section">
    <h2 class="sec-label">Key Assumptions Check</h2>
    {% for ka in key_assumptions %}
    <div class="seam-item">
      <div class="seam-topic">{{ ka.topic }}</div>
      <div class="seam-desc">Assumes: {{ ka.assumption }}</div>
      <div class="seam-desc" style="margin-top:4px;">Would invalidate: {{ ka.invalidator }}</div>
      <div class="seam-sources">Confidence: {{ ka.confidence }}{% if ka.confidence_basis %} — {{ ka.confidence_basis }}{% endif %}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- FOOTER -->
  <div class="footer">
    Generated at {{ generated_at }} · Powered by Kimi K2.5 · Fireworks AI<br>
    Sources: {{ rss_source_names }}<br>
    {% if yt_source_names %}Analysis transcripts: {{ yt_source_names }}<br>{% endif %}
    Come Follow Me: churchofjesuschrist.org · Markets: Finnhub<br>
  </div>

  </div><!-- /.wrapper -->

<!-- Browser-only toggle: injected by JS so it never appears as a dead button in email clients -->
<script>
(function() {
  // Inject the toggle bar inside the wrapper (respects max-width alignment)
  var wrapper = document.querySelector('.wrapper');
  var bar = document.createElement('div');
  bar.className = 'theme-bar';
  var btn = document.createElement('button');
  btn.className = 'theme-btn';
  btn.id = 'theme-toggle';
  btn.setAttribute('aria-label', 'Toggle colour theme');
  bar.appendChild(btn);
  if (wrapper) {
    wrapper.insertBefore(bar, wrapper.firstChild);
  } else {
    document.body.insertBefore(bar, document.body.firstChild);
  }

  var html = document.documentElement;

  function systemTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function activeTheme() {
    return html.getAttribute('data-theme') || systemTheme();
  }

  function updateBtn() {
    btn.textContent = activeTheme() === 'dark' ? '\u2600 Light' : '\u263e Dark';
  }

  updateBtn();

  btn.addEventListener('click', function() {
    var next = activeTheme() === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    try { localStorage.setItem('md-theme', next); } catch(e) {}
    updateBtn();
  });

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
    try { if (!localStorage.getItem('md-theme')) updateBtn(); } catch(e) { updateBtn(); }
  });
})();
</script>

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
