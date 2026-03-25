"""HTML email template for the Morning Digest.

Uses Jinja2 for rendering. The template is designed for Gmail rendering compatibility:
- Inline styles (Gmail strips <style> tags in some contexts)
- Table-based layout for email clients
- System fonts with web-safe fallbacks
"""

from jinja2 import Template

# Note: Gmail is one of the better email clients for CSS support,
# but we still inline critical styles for maximum compatibility.
# The <style> block in <head> works in Gmail's web client.

EMAIL_TEMPLATE = Template('''\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { margin: 0; padding: 0; background: #e8e6e2; font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1a1a1a; line-height: 1.6; }
  h1, h2, h3 { margin: 0; padding: 0; font-size: inherit; font-weight: inherit; line-height: inherit; }
  .wrapper { max-width: 680px; margin: 0 auto; background: #faf9f7; }
  .header { background: #1a1a1a; color: #fff; padding: 28px 32px 24px; }
  .header-date { font-family: 'Courier New', monospace; font-size: 12px; letter-spacing: 1.5px; text-transform: uppercase; color: #999; margin-bottom: 6px; }
  .header-title { font-family: Georgia, 'Times New Roman', serif; font-size: 28px; font-weight: 700; letter-spacing: -0.5px; line-height: 1.2; }
  .header-sub { font-size: 13px; color: #aaa; margin-top: 4px; }

  .spiritual { padding: 20px 32px; background: #f7f5f0; border-bottom: 1px solid #e5e2dd; }
  .spiritual-ref { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: #666; margin-bottom: 8px; }
  .spiritual-text { font-family: Georgia, serif; font-size: 16px; line-height: 1.65; font-style: italic; color: #1a1a1a; }
  .spiritual-cite { font-size: 13px; color: #555; margin-top: 6px; font-style: normal; }
  .spiritual-ctx { font-size: 13px; color: #666; margin-top: 8px; }

  .bar { padding: 12px 32px; background: #f2f0ec; border-bottom: 1px solid #e5e2dd; font-size: 13px; color: #555; }
  .bar-mono { font-family: 'Courier New', monospace; font-weight: 500; color: #1a1a1a; }
  .bar-detail { font-size: 12px; color: #666; }
  .markets { font-family: 'Courier New', monospace; font-size: 12px; display: flex; gap: 18px; flex-wrap: wrap; }
  .mkt-label { color: #666; }
  .mkt-val { color: #1a1a1a; font-weight: 500; }
  .up { color: #1e8449; }
  .down { color: #c0392b; }

  .section { padding: 24px 32px; border-bottom: 1px solid #e5e2dd; }
  .sec-label { font-family: 'Courier New', monospace; font-size: 11px; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; color: #c05028; margin-bottom: 16px; border-bottom: 1px solid #e5e2dd; padding-bottom: 8px; }

  .scan-item { padding: 10px 0; border-bottom: 1px solid #e5e2dd; }
  .scan-item:last-child { border-bottom: none; }
  .scan-header { display: flex; align-items: flex-start; flex-wrap: nowrap; gap: 8px; margin-bottom: 3px; }
  .tag { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; padding: 2px 7px; border-radius: 3px; display: inline-block; flex-shrink: 0; margin-top: 2px; }
  .tag-war { color: #78281f; background: #f9ebea; }
  .tag-ai { color: #6c3483; background: #ebdef0; }
  .tag-domestic { color: #7d6608; background: #fef9e7; }
  .tag-defense { color: #1b4f72; background: #d4e6f1; }
  .tag-space { color: #1a5276; background: #d6eaf8; }
  .tag-tech { color: #4a235a; background: #f4ecf7; }
  .tag-local { color: #1e8449; background: #d5f5e3; }
  .tag-science { color: #7e5109; background: #fef5e7; }
  .tag-econ { color: #1a5276; background: #d4efdf; }
  .tag-cyber { color: #633974; background: #f5eef8; }
  .scan-hl { flex: 1; min-width: 0; font-size: 14px; font-weight: 600; line-height: 1.4; }
  .scan-ctx { font-size: 13px; color: #555; line-height: 1.45; }
  .scan-link { font-size: 11px; color: #666; margin-top: 4px; }
  .scan-link a { color: #666; text-decoration: none; border-bottom: 1px dotted #aaa; }

  .local-item { padding: 6px 0; font-size: 13px; color: #555; line-height: 1.5; }
  .local-item strong { color: #1a1a1a; font-weight: 500; }
  .cal-item { padding: 6px 0; font-size: 13px; color: #555; display: flex; align-items: baseline; gap: 10px; }
  .cal-date { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; color: #fff; background: #1a1a1a; padding: 2px 7px; border-radius: 3px; flex-shrink: 0; }

  .card { background: #fff; border: 1px solid #e5e2dd; border-top: 3px solid #c05028; border-radius: 0 0 6px 6px; padding: 20px 24px; margin-bottom: 16px; }
  .card:last-child { margin-bottom: 0; }
  .card-hl { font-family: Georgia, serif; font-size: 19px; font-weight: 700; line-height: 1.3; margin-bottom: 10px; letter-spacing: -0.3px; }
  .card-body { font-size: 14px; color: #444; line-height: 1.65; }
  .card-body p { margin: 0 0 10px 0; }
  .card-body p:last-child { margin-bottom: 0; }
  .wim { background: #f5ebe6; border-left: 3px solid #c05028; padding: 10px 14px; margin-top: 12px; border-radius: 0 4px 4px 0; }
  .wim-label { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: #c05028; margin-bottom: 4px; }
  .wim p { font-size: 13px; color: #1a1a1a; line-height: 1.55; margin: 0; }
  .fr { margin-top: 14px; padding-top: 12px; border-top: 1px solid #e5e2dd; }
  .fr-label { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: #666; margin-bottom: 6px; }
  .fr a { display: block; font-size: 13px; color: #1b4f72; text-decoration: none; line-height: 1.5; margin-bottom: 2px; }
  .fr .src { color: #666; font-size: 11px; }

  .seam-sub { font-family: 'Courier New', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: #7b241c; margin-bottom: 10px; }
  .seam-item { padding: 10px 0; border-bottom: 1px solid #e5e2dd; }
  .seam-item:last-child { border-bottom: none; }
  .seam-topic { font-size: 14px; font-weight: 600; line-height: 1.4; margin-bottom: 3px; }
  .seam-desc { font-size: 13px; color: #555; line-height: 1.45; }
  .seam-sources { font-size: 12px; color: #888; margin-top: 4px; font-style: italic; }

  .weekend-item { padding: 8px 0; border-bottom: 1px solid #e5e2dd; }
  .weekend-item:last-child { border-bottom: none; }
  .wk-title { font-size: 14px; font-weight: 500; }
  .wk-title a { color: #1b4f72; text-decoration: none; }
  .wk-meta { font-size: 12px; color: #666; margin-top: 2px; }
  .wk-desc { font-size: 13px; color: #555; margin-top: 3px; line-height: 1.45; }

  .footer { padding: 20px 32px; background: #1a1a1a; color: #aaa; font-size: 11px; line-height: 1.6; text-align: center; }
  .footer a { color: #ccc; text-decoration: none; }
</style>
</head>
<body>
<div class="wrapper">

  <!-- HEADER -->
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
  {% if weather and weather.current_temp_f is not none %}
  <div class="bar">
    <span>{{ weather.city }}, {{ weather.state }} — {{ weather.condition }}</span>
    <span class="bar-mono" style="float:right;">{{ weather.current_temp_f }}°F</span>
    {% if weather.forecast|length > 2 %}
    <br><span class="bar-detail">Tomorrow {{ weather.forecast[1].high_f }}°F {{ weather.forecast[1].condition }}. {{ weather.forecast[2].day_name }} {{ weather.forecast[2].high_f }}°F {{ weather.forecast[2].condition }}.</span>
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
      <div class="scan-ctx">{{ item.context }}</div>
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
      </div>
      {% endfor %}
    </div>
    {% endif %}
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
        <a href="{{ fr.url }}">{{ fr.title }} <span class="src">— {{ fr.source }}</span></a>
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
    <div class="local-item">{{ item }}</div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- WEEK AHEAD -->
  {% if week_ahead %}
  <div class="section">
    <h2 class="sec-label">Week Ahead</h2>
    {% for item in week_ahead %}
    <div class="cal-item"><span class="cal-date">{{ item.date }}</span> {{ item.event }}</div>
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

  <!-- FOOTER -->
  <div class="footer">
    Generated at {{ generated_at }} · Powered by Kimi K2.5 · Fireworks AI<br>
    Sources: {{ rss_source_names }}<br>
    {% if yt_source_names %}Analysis transcripts: {{ yt_source_names }}<br>{% endif %}
    Come Follow Me: churchofjesuschrist.org · Markets: Finnhub<br>
  </div>

</div>
</body>
</html>
''')


def render_email(data: dict) -> str:
    """Render the digest email from structured data."""
    return EMAIL_TEMPLATE.render(**data)
