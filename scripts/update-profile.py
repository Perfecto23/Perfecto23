#!/usr/bin/env python3
"""Update AI usage from the public tokscale profile, plus project names and the other profile cards.
Run --check for offline validation. Network failures preserve existing files.
Raw tokscale and GitHub responses are processed in memory and never saved.
The tokscale profile API is public and needs no token.
"""
import argparse, datetime as dt, decimal, fnmatch, html, json, math, os, re, sys
import urllib.parse, urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
D = decimal.Decimal
USER = 'Perfecto23'
# Public read. Never attach GITHUB_TOKEN; tokscale does not accept it.
TOKSCALE_USER = USER
TOKSCALE_API = 'https://tokscale.ai/api/users/' + TOKSCALE_USER
AI_ASSETS = (
    'ai-usage-light.svg',
    'ai-usage-dark.svg',
    'ai-usage-mobile-light.svg',
    'ai-usage-mobile-dark.svg',
)
CONFIG = {'github_username': USER, 'identity': {'name': 'Perfecto'},
          'exclude_repo_owners': ['Perfecto23', 'MoeGo', 'moego-ai', 'moego-pet'],
          'exclude_repo_owner_patterns': ['moego*'], 'only_organization_upstreams': True,
          'project_labels': {'langgenius/dify': 'Dify', 'web-infra-dev/rspack': 'Rspack',
                             'Tencent/WeKnora': 'Tencent WeKnora'}}
CLIENT_LABELS = {
    'claude': 'Claude', 'codex': 'Codex', 'cursor': 'Cursor', 'droid': 'Droid',
    'hermes': 'Hermes', 'kiro': 'Kiro', 'omp': 'OMP', 'openclaw': 'OpenClaw',
    'opencode': 'OpenCode', 'pi': 'Pi',
}
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
THEMES = {
    'light': {
        'bg': '#ffffff', 'border': '#d6d3d1', 'title': '#1c1917', 'muted': '#57534e',
        'faint': '#a8a29e', 'hero': '#6d28d9', 'line': '#6d28d9', 'area_opacity': '0.34',
        'track': '#e7e5e4',
        'levels': ['#f5f5f4', '#ddd6fe', '#c4b5fd', '#8b5cf6', '#5b21b6'],
    },
    'dark': {
        'bg': '#161b22', 'border': '#30363d', 'title': '#f5f5f4', 'muted': '#a8a29e',
        'faint': '#78716c', 'hero': '#c4b5fd', 'line': '#c4b5fd', 'area_opacity': '0.55',
        'track': '#30363d',
        'levels': ['#21262d', '#4c1d95', '#7c3aed', '#a78bfa', '#c4b5fd'],
    },
}
class InvalidData(ValueError): pass

def compact(value, digits=2):
    n=D(str(value))
    if not n.is_finite() or n<0: raise InvalidData('invalid nonnegative number')
    units=['','K','M','B','T']; i=0
    while n>=1000 and i<len(units)-1:n/=1000;i+=1
    quantum=D(1).scaleb(-digits); n=n.quantize(quantum,rounding=decimal.ROUND_HALF_UP)
    if n>=1000 and i<len(units)-1:n=(n/1000).quantize(quantum,rounding=decimal.ROUND_HALF_UP);i+=1
    return format(n,'f').rstrip('0').rstrip('.')+units[i] if '.' in format(n,'f') else str(n)+units[i]

def count(v):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or int(v)!=v:raise InvalidData('token/count value must be a nonnegative integer')
    return int(v)

def fetch(url, token=None):
    # Credentials only attach to GitHub API, never to tokscale or other external services.
    headers={'User-Agent':'Perfecto23-profile-refresh/1.0'}
    if url.startswith('https://api.github.com/'):
        headers['Accept']='application/vnd.github+json';headers['X-GitHub-Api-Version']='2022-11-28'
        if token:headers['Authorization']='Bearer '+token
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=35) as r:
        if r.status!=200:raise InvalidData('unexpected HTTP status')
        data=r.read(8*1024*1024+1)
    if len(data)>8*1024*1024:raise InvalidData('response exceeds size limit')
    return data

def parse_date(value, label):
    if not isinstance(value, str):
        raise InvalidData(label + ' date required')
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidData(label + ' date invalid') from exc

def hero_compact(value):
    number = value if isinstance(value, int) and not isinstance(value, bool) else count(value)
    return compact(number, 1 if number >= 1000000 else 2)

def value_size_for(value, base):
    length = len(str(value))
    if length <= 6:
        return base
    if length <= 9:
        return base - 6
    return max(16, base - 10)

def share(part, whole):
    if whole <= 0 or part <= 0:
        return '0%'
    pct = 100 * part / whole
    if pct < 0.05:
        return '<0.1%'
    text = f'{pct:.1f}'
    if text == '100.0':
        return '100%'
    if text == '0.0':
        return '<0.1%'
    return text + '%'

def client_label(name):
    key = str(name).strip().lower()
    if key in CLIENT_LABELS:
        return CLIENT_LABELS[key]
    if not name:
        return ''
    return name[0].upper() + name[1:]

def active_label(span):
    if 360 <= span <= 372:
        return 'Active days · 1y'
    return f'Active days · {span}d'

def subtitle_for(data, layout):
    if 360 <= data['span_days'] <= 372:
        if layout == 'mobile':
            return 'All-time · trailing year · UTC'
        return 'All-time totals · 1-year heatmap · UTC'
    start, end = data['window']
    return f'All-time · {start} – {end} · UTC'

def format_stamp(stamp, as_of):
    try:
        parsed = dt.datetime.fromisoformat(str(stamp).replace('Z', '+00:00')).astimezone(dt.timezone.utc)
    except ValueError:
        return str(stamp), True
    return parsed.strftime('%Y-%m-%d %H:%M UTC'), parsed.date() < as_of

def status_line(data, as_of):
    label, old = format_stamp(data['updated_at'], as_of)
    bits = ['Updated ' + label]
    if old:
        bits.append('older')
    if data.get('current_day_partial'):
        bits.append('in progress')
    if data.get('stale'):
        bits.append('stale')
    return ' · '.join(bits)

def heat_levels(values):
    nonzero = sorted(v for v in values if v > 0)
    if not nonzero:
        return [0 for _ in values]
    def pick(fraction):
        index = (len(nonzero) - 1) * fraction
        lo = math.floor(index)
        hi = math.ceil(index)
        if lo == hi:
            return nonzero[lo]
        weight = index - lo
        return nonzero[lo] * (1 - weight) + nonzero[hi] * weight
    q1, q3 = pick(0.25), pick(0.75)
    if q1 == q3:
        return [0 if v <= 0 else 3 for v in values]
    q2 = pick(0.5)
    levels = []
    for value in values:
        if value <= 0:
            levels.append(0)
        elif value <= q1:
            levels.append(1)
        elif value <= q2:
            levels.append(2)
        elif value <= q3:
            levels.append(3)
        else:
            levels.append(4)
    return levels

TOKEN_PARTS = ('input', 'output', 'cacheRead', 'cacheWrite', 'reasoning')

def _acc(row):
    if not isinstance(row, dict) or not isinstance(row.get('date'), str):
        raise InvalidData('daily object required')
    date = parse_date(row['date'], 'daily')
    totals = row.get('totals')
    if not isinstance(totals, dict) or 'tokens' not in totals:
        raise InvalidData('daily totals required')
    total = count(totals['tokens'])
    clients = row.get('clients') if row.get('clients') is not None else []
    if not isinstance(clients, list):
        raise InvalidData('daily clients array required')
    client_sum = 0
    model_sum = 0
    client_acc = {}
    model_acc = {}
    for client in clients:
        if not isinstance(client, dict):
            raise InvalidData('client object required')
        name = client.get('client')
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise InvalidData('invalid client name')
        name = name.strip()
        breakdown = client.get('tokens')
        if not isinstance(breakdown, dict):
            raise InvalidData('client token breakdown required')
        part = 0
        for key in TOKEN_PARTS:
            if key not in breakdown:
                raise InvalidData('client token breakdown incomplete on ' + date.isoformat())
            part += count(breakdown[key])
        client_sum += part
        client_acc[name] = client_acc.get(name, 0) + part
        models = client.get('models') if client.get('models') is not None else {}
        if not isinstance(models, dict):
            raise InvalidData('client models object required')
        for model_name, model_value in models.items():
            if not isinstance(model_name, str) or not model_name.strip() or len(model_name) > 120:
                raise InvalidData('invalid model name')
            model_name = model_name.strip()
            if isinstance(model_value, dict):
                if 'tokens' not in model_value:
                    raise InvalidData('model tokens required')
                model_tokens = count(model_value['tokens'])
            else:
                model_tokens = count(model_value)
            model_sum += model_tokens
            model_acc[model_name] = model_acc.get(model_name, 0) + model_tokens
    if client_sum != total or model_sum != total:
        raise InvalidData('daily token breakdown does not match total on ' + date.isoformat())
    return date, total, client_acc, model_acc

def normalize_tokscale(obj, as_of, captured_at):
    if not isinstance(obj, dict):
        raise InvalidData('profile object required')
    user = obj.get('user')
    if not isinstance(user, dict):
        raise InvalidData('user object required')
    if user.get('username') != TOKSCALE_USER:
        raise InvalidData('unexpected tokscale username')
    rank = user.get('rank')
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise InvalidData('rank must be a positive integer')
    period = obj.get('period', 'all')
    if period != 'all':
        raise InvalidData('expected all-time tokscale profile')
    chart = obj.get('chartRange')
    if not isinstance(chart, dict):
        raise InvalidData('chartRange required')
    start = parse_date(chart.get('start'), 'chartRange start')
    end = parse_date(chart.get('end'), 'chartRange end')
    if end < start:
        raise InvalidData('chartRange inverted')
    span = (end - start).days + 1
    if span < 7 or span > 800:
        raise InvalidData('chartRange length is not usable')
    if end > as_of + dt.timedelta(days=1):
        raise InvalidData('chartRange ends in the future')
    rows = obj.get('contributions')
    if not isinstance(rows, list) or not rows:
        raise InvalidData('contributions must be a nonempty array')
    if len(rows) > 5000:
        raise InvalidData('too many daily rows')
    by_date = {}
    clients = {}
    models = {}
    for row in rows:
        date, total, client_acc, model_acc = _acc(row)
        if date in by_date:
            raise InvalidData('duplicate daily date')
        by_date[date] = total
        for name, tokens in client_acc.items():
            clients[name] = clients.get(name, 0) + tokens
        for name, tokens in model_acc.items():
            models[name] = models.get(name, 0) + tokens
    series_total = sum(by_date.values())
    stats = obj.get('stats') if isinstance(obj.get('stats'), dict) else {}
    if 'totalTokens' in stats and count(stats['totalTokens']) != series_total:
        raise InvalidData('reported total does not match daily series')
    if series_total <= 0:
        raise InvalidData('empty/zero usage window; retain last-good until confirmed')
    days = []
    active = 0
    for offset in range(span):
        date = start + dt.timedelta(days=offset)
        total = by_date.get(date, 0)
        if total:
            active += 1
        days.append({'date': date.isoformat(), 'total_tokens': total})
    client_rows = [{'name': name, 'label': client_label(name), 'tokens': tokens}
                   for name, tokens in clients.items() if tokens > 0]
    model_rows = [{'name': name, 'tokens': tokens} for name, tokens in models.items() if tokens > 0]
    client_rows.sort(key=lambda item: (-item['tokens'], item['name']))
    model_rows.sort(key=lambda item: (-item['tokens'], item['name']))
    if not client_rows or not model_rows:
        raise InvalidData('usage is missing client or model attribution')
    display = user.get('displayName') or user.get('username') or TOKSCALE_USER
    if not isinstance(display, str):
        display = TOKSCALE_USER
    display = ' '.join(display.split())
    if not display or len(display) > 80:
        display = TOKSCALE_USER
    updated = obj.get('updatedAt')
    if not isinstance(updated, str) or not updated.strip():
        updated = captured_at
    freshness = obj.get('submissionFreshness')
    stale = isinstance(freshness, dict) and freshness.get('isStale') is True
    return {
        'schema_version': 2,
        'source': 'tokscale public profile API ' + TOKSCALE_API,
        'captured_at': captured_at,
        'updated_at': updated,
        'timezone': 'UTC',
        'username': TOKSCALE_USER,
        'display_name': display,
        'rank': rank,
        'total_tokens': series_total,
        'active_days': active,
        'window': [start.isoformat(), end.isoformat()],
        'span_days': span,
        'days': days,
        'clients': client_rows,
        'models': model_rows,
        'current_day_partial': end == as_of,
        'stale': stale,
    }

def esc(value):
    return html.escape(str(value), quote=True)

def text(x, y, value, size=14, color='#24292f', weight=400, anchor=None, eid=None):
    attrs = [f'x="{x}"', f'y="{y}"', f'font-size="{size}"', f'fill="{color}"', f'font-weight="{weight}"']
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    if eid:
        attrs.insert(0, f'id="{eid}"')
    return f'<text {" ".join(attrs)}>{esc(value)}</text>'

def fit_name(name, limit=14):
    if len(name) <= limit:
        return name
    return name[:limit - 1] + '…'

def rank_label(rank):
    return f'#{rank:,}'

def week_columns(days):
    first = dt.date.fromisoformat(days[0]['date'])
    lead = (first.weekday() + 1) % 7
    origin = first - dt.timedelta(days=lead)
    last = dt.date.fromisoformat(days[-1]['date'])
    count_days = (last - origin).days + 1
    columns = [[None] * 7 for _ in range((count_days + 6) // 7)]
    by_date = {day['date']: day for day in days}
    for offset in range(count_days):
        date = origin + dt.timedelta(days=offset)
        day = by_date.get(date.isoformat())
        if day is None:
            continue
        columns[offset // 7][(date.weekday() + 1) % 7] = day
    return columns

def grid_metrics(n_cols, max_width, cell=11, gap=3):
    def width_for(cell_size, gap_size):
        if n_cols <= 1:
            return cell_size
        return (n_cols - 1) * (cell_size + gap_size) + cell_size
    if n_cols < 1:
        return cell, gap, cell + gap, 0
    if width_for(cell, gap) <= max_width:
        return cell, gap, cell + gap, width_for(cell, gap)
    gap = 2 if n_cols > 1 else gap
    cell = (max_width - (n_cols - 1) * gap) // n_cols if n_cols else cell
    if cell < 4:
        gap = 1
        cell = (max_width - (n_cols - 1) * gap) // n_cols
    cell = max(2, cell)
    return cell, gap, cell + gap, width_for(cell, gap)

def month_marks(columns, grid_x, step):
    marks = []
    previous = None
    for col, week in enumerate(columns):
        dated = [cell for cell in week if cell]
        if not dated:
            continue
        date = dt.date.fromisoformat(dated[0]['date'])
        if date.month == previous:
            continue
        x = grid_x + col * step
        if marks and x - marks[-1][0] < 28:
            previous = date.month
            continue
        marks.append((x, MONTHS[date.month - 1]))
        previous = date.month
    return marks

def mix_line(x, y, prefix, entries, total, theme, max_width):
    chosen = []
    for entry in entries[:4]:
        label = entry.get('label') or entry['name']
        trial = chosen + [(label, share(entry['tokens'], total))]
        estimate = sum(len(label) + len(pct) + 4 for label, pct in trial)
        if chosen and estimate * 7.3 > max_width:
            break
        chosen = trial
    spans = []
    for index, (label, pct) in enumerate(chosen):
        if index:
            spans.append(f'<tspan fill="{theme["faint"]}">  ·  </tspan>')
        spans.append(f'<tspan fill="{theme["title"]}" font-weight="600">{esc(label)}</tspan>')
        spans.append(f'<tspan fill="{theme["muted"]}"> {esc(pct)}</tspan>')
    if not spans:
        spans.append(f'<tspan fill="{theme["muted"]}">—</tspan>')
    inner = ''.join(spans)
    return (
        text(x, y, prefix, 12, theme['muted'], 600)
        + f'<text x="{x + 78}" y="{y}" font-size="13">{inner}</text>'
    )

def legend(x, y, theme):
    parts = [text(x, y, 'Less', 11, theme['muted'])]
    cursor = x + 34
    for color in theme['levels']:
        parts.append(f'<rect x="{cursor}" y="{y - 9}" width="11" height="11" rx="2" fill="{color}"/>')
        cursor += 15
    parts.append(text(cursor + 6, y, 'More', 11, theme['muted']))
    return ''.join(parts)

def card_title(data):
    return (
        f"{data['display_name']} AI coding usage on tokscale: "
        f"{hero_compact(data['total_tokens'])} tokens, {data['active_days']} active days, rank {data['rank']}"
    )

def svg_doc(width, height, title, body):
    safe = esc(title)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{safe}" text-rendering="geometricPrecision">\n'
        f'<title>{safe}</title>\n'
        "<style>text{font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-variant-numeric:tabular-nums}</style>\n"
        f'{body}\n</svg>\n'
    )

def frame(width, height, theme):
    return f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="16" fill="{theme["bg"]}" stroke="{theme["border"]}"/>'

def header(data, theme, layout, title_x, title_y, right_x):
    mark_y = title_y - 11
    subtitle_y = title_y + 20
    return ''.join([
        f'<rect x="{title_x}" y="{mark_y}" width="8" height="8" rx="2" fill="{theme["hero"]}"/>',
        text(title_x + 14, title_y, 'AI coding usage', 15 if layout == 'desktop' else 14, theme['title'], 700),
        text(right_x, title_y, 'tokscale', 12, theme['muted'], 500, anchor='end'),
        text(title_x + 14, subtitle_y, subtitle_for(data, layout), 12, theme['muted']),
    ])

def render_stats(items, xs, label_y, value_y, value_size, theme):
    parts = []
    for x, (value, label, color) in zip(xs, items):
        parts.append(text(x, label_y, label, 11, theme['muted'], 500))
        parts.append(text(x, value_y, value, value_size_for(value, value_size), color, 700))
    return ''.join(parts)

def heatmap(data, theme, grid_x, grid_y, max_width):
    columns = week_columns(data['days'])
    cell, gap, step, width = grid_metrics(len(columns), max_width)
    levels = heat_levels([day['total_tokens'] for day in data['days']])
    level_by = {day['date']: level for day, level in zip(data['days'], levels)}
    radius = 2 if cell >= 8 else 1
    parts = ['<g data-chart="heatmap">']
    for x, label in month_marks(columns, grid_x, step):
        parts.append(text(x, grid_y - 10, label, 11, theme['muted'], 500))
    for row, letter in ((1, 'M'), (3, 'W'), (5, 'F')):
        parts.append(text(grid_x - 8, grid_y + row * step + cell - 2, letter, 10, theme['faint'], 500, anchor='end'))
    end = data['window'][1]
    partial = data.get('current_day_partial')
    for col, week in enumerate(columns):
        for row, day in enumerate(week):
            if day is None:
                continue
            x = grid_x + col * step
            y = grid_y + row * step
            tokens = day['total_tokens']
            suffix = ' · partial' if partial and day['date'] == end else ''
            tip = f"{day['date']}: {compact(tokens)} tokens{suffix}"
            fill = theme['levels'][level_by[day['date']]]
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="{radius}" fill="{fill}" data-date="{day["date"]}">'
                f'<title>{esc(tip)}</title></rect>'
            )
    parts.append('</g>')
    grid_bottom = grid_y + 6 * step + cell
    return '\n'.join(parts), grid_bottom, width

def area_chart(data, theme, x, y, width, height):
    values = [day['total_tokens'] for day in data['days']]
    n = len(values)
    logs = [math.sqrt(value) for value in values]
    peak = max(logs) if logs else 1
    if peak <= 0:
        peak = 1
    plot_top = y + 22
    plot_height = height - 22
    coords = []
    for index, magnitude in enumerate(logs):
        if n == 1:
            px = x + width / 2
        else:
            px = x + width * index / (n - 1)
        py = plot_top + plot_height - plot_height * magnitude / peak
        coords.append((px, py))
    def pair(point):
        return f'{point[0]:.2f},{point[1]:.2f}'
    line = 'M' + pair(coords[0]) + ''.join('L' + pair(point) for point in coords[1:])
    baseline = plot_top + plot_height
    fill = line + f'L{coords[-1][0]:.2f},{baseline:.2f}L{coords[0][0]:.2f},{baseline:.2f}Z'
    peak_index = max(range(n), key=lambda i: values[i])
    peak_point = coords[peak_index]
    anchor = 'middle'
    label_x = peak_point[0]
    if label_x < x + 36:
        anchor = 'start'
    elif label_x > x + width - 36:
        anchor = 'end'
    # Keep the peak figure in the top gutter so it never sits on the stroke.
    label_y = y + 12
    start, end = data['window']
    tip = f'Daily tokens, square-root scale, {start} to {end}'
    parts = [
        '<defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1">',
        f'<stop offset="0" stop-color="{theme["line"]}" stop-opacity="{theme["area_opacity"]}"/>',
        f'<stop offset="1" stop-color="{theme["line"]}" stop-opacity="0.02"/>',
        '</linearGradient></defs>',
        f'<g data-chart="area"><title>{esc(tip)}</title>',
        f'<line x1="{x:.2f}" y1="{baseline:.2f}" x2="{x + width:.2f}" y2="{baseline:.2f}" stroke="{theme["border"]}"/>',
        f'<path d="{fill}" fill="url(#area)"/>',
        f'<path d="{line}" fill="none" stroke="{theme["line"]}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>',
        f'<circle cx="{peak_point[0]:.2f}" cy="{peak_point[1]:.2f}" r="2.6" fill="{theme["line"]}" stroke="{theme["bg"]}" stroke-width="1"/>',
        text(label_x, label_y, compact(values[peak_index], 2), 11, theme['muted'], 600, anchor=anchor),
        '</g>',
    ]
    return ''.join(parts)

def bar_row(x, y, width, name, pct, ratio, theme, tip):
    name_width = 128
    pct_width = 54
    bar_x = x + name_width
    bar_width = width - name_width - pct_width
    fill_width = 0
    if ratio > 0:
        fill_width = max(4, int(round(bar_width * min(1, ratio))))
    bar_y = y - 8
    return ''.join([
        f'<g><title>{esc(tip)}</title>',
        text(x, y, fit_name(name, 18), 13, theme['title'], 600),
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_width}" height="4" rx="2" fill="{theme["track"]}"/>',
        f'<rect x="{bar_x}" y="{bar_y}" width="{fill_width}" height="4" rx="2" fill="{theme["hero"]}"/>',
        text(x + width, y, pct, 12, theme['muted'], 600, anchor='end'),
        '</g>',
    ])

def desktop_stats(data, theme):
    total = data['total_tokens']
    top = data['clients'][0]
    return [
        (hero_compact(total), 'Total tokens', theme['hero']),
        (f"{data['active_days']:,}", active_label(data['span_days']), theme['title']),
        (rank_label(data['rank']), 'All-time rank', theme['title']),
        (fit_name(top['label'], 12), f"Top client · {share(top['tokens'], total)}", theme['title']),
    ]

def render_desktop(data, theme, as_of):
    width = 820
    grid_x = 40
    right = width - 28
    title_y = 36
    label_y = 88
    value_y = 120
    models_y = 156
    clients_y = 178
    rule_y = 198
    grid_y = 228
    chart, grid_bottom, _grid_width = heatmap(data, theme, grid_x, grid_y, 739)
    legend_y = grid_bottom + 22
    height = legend_y + 18
    total = data['total_tokens']
    xs = [40, 230, 420, 610]
    start, end = data['window']
    body = '\n'.join([
        frame(width, height, theme),
        header(data, theme, 'desktop', grid_x, title_y, right),
        render_stats(desktop_stats(data, theme), xs, label_y, value_y, 30, theme),
        mix_line(grid_x, models_y, 'Models', data['models'], total, theme, right - grid_x - 78),
        mix_line(grid_x, clients_y, 'Clients', data['clients'], total, theme, right - grid_x - 78),
        f'<line x1="{grid_x}" y1="{rule_y}.5" x2="{right}" y2="{rule_y}.5" stroke="{theme["border"]}"/>',
        chart,
        legend(grid_x, legend_y, theme),
        text((grid_x + right) // 2, legend_y, f'{start} – {end}', 11, theme['muted'], anchor='middle'),
        text(right, legend_y, status_line(data, as_of), 11, theme['muted'], anchor='end', eid='ai-status'),
    ])
    return svg_doc(width, height, card_title(data), body)

def render_mobile(data, theme, as_of):
    width = 360
    pad = 16
    right = width - pad
    inner = right - pad
    total = data['total_tokens']
    top = data['clients'][0]
    title_y = 32
    left_stats = [
        (hero_compact(total), 'Total tokens', theme['hero']),
        (rank_label(data['rank']), 'All-time rank', theme['title']),
    ]
    right_stats = [
        (f"{data['active_days']:,}", active_label(data['span_days']), theme['title']),
        (fit_name(top['label'], 12), f"Top client · {share(top['tokens'], total)}", theme['title']),
    ]
    columns = [(pad, left_stats), (188, right_stats)]
    parts = [frame(width, 10, theme), header(data, theme, 'mobile', pad, title_y, right)]
    label_ys = [74, 132]
    value_ys = [100, 158]
    for x, stats in columns:
        for (value, label, color), label_y, value_y in zip(stats, label_ys, value_ys):
            parts.append(text(x, label_y, label, 11, theme['muted'], 500))
            parts.append(text(x, value_y, value, value_size_for(value, 24), color, 700))
    y = 188
    parts.append(text(pad, y, 'Models', 11, theme['muted'], 600))
    y = 210
    for entry in data['models'][:3]:
        tip = f"{entry['name']}: {compact(entry['tokens'])} tokens, {share(entry['tokens'], total)}"
        parts.append(bar_row(pad, y, inner, entry['name'], share(entry['tokens'], total), entry['tokens'] / total, theme, tip))
        y += 22
    y += 8
    parts.append(text(pad, y, 'Clients', 11, theme['muted'], 600))
    y += 22
    for entry in data['clients'][:3]:
        tip = f"{entry['label']}: {compact(entry['tokens'])} tokens, {share(entry['tokens'], total)}"
        parts.append(bar_row(pad, y, inner, entry['label'], share(entry['tokens'], total), entry['tokens'] / total, theme, tip))
        y += 22
    y += 10
    parts.append(text(pad, y, 'Daily tokens · sqrt scale', 11, theme['muted'], 500))
    chart_y = y + 8
    chart_h = 104
    parts.append(area_chart(data, theme, pad, chart_y, inner, chart_h))
    date_y = chart_y + chart_h + 16
    start, end = data['window']
    parts.append(text(pad, date_y, start, 11, theme['muted']))
    parts.append(text(right, date_y, end, 11, theme['muted'], anchor='end'))
    status_y = date_y + 20
    parts.append(text(pad, status_y, status_line(data, as_of), 11, theme['muted'], eid='ai-status'))
    height = status_y + 18
    parts[0] = frame(width, height, theme)
    body = '\n'.join(parts)
    return svg_doc(width, height, card_title(data), body)

def render_usage(data, theme_name, layout, as_of):
    theme = THEMES[theme_name]
    if layout == 'desktop':
        return render_desktop(data, theme, as_of)
    if layout == 'mobile':
        return render_mobile(data, theme, as_of)
    raise InvalidData('unknown usage layout')

def update_ai(today, captured):
    # Official embeds exist at /api/embed/<user>/svg and /api/badge/<user>/svg.
    # They are public too, but the badge is one number, and the card's intensity
    # scale flattens this profile while omitting clients and models. Drawing from
    # the public JSON keeps a last-good snapshot and needs no secret.
    profile = json.loads(fetch(TOKSCALE_API))
    data = normalize_tokscale(profile, today, captured)
    rendered = []
    for theme_name in ('light', 'dark'):
        rendered.append((f'ai-usage-{theme_name}.svg', render_usage(data, theme_name, 'desktop', today)))
        rendered.append((f'ai-usage-mobile-{theme_name}.svg', render_usage(data, theme_name, 'mobile', today)))
    for _name, svg in rendered:
        ET.fromstring(svg)
    for name, svg in rendered:
        publish(ROOT / 'assets' / name, svg)

def mark_ai_retained(today, captured):
    label, _old = format_stamp(captured, today)
    message = 'Refresh failed ' + label + ' · retained'
    for name in AI_ASSETS:
        path = ROOT / 'assets' / name
        if not path.exists():
            continue
        svg = path.read_text()
        updated, count = re.subn(
            r'(<text id="ai-status"[^>]*>)(.*?)(</text>)',
            lambda match: match.group(1) + html.escape(message) + match.group(3),
            svg,
            count=1,
            flags=re.S,
        )
        if count != 1:
            raise InvalidData('AI status label missing')
        publish(path, updated)

def filter_projects(repos, config):
    excluded={x.lower() for x in config['exclude_repo_owners']};exclude_repos={x.lower() for x in config.get('exclude_repositories',[])}
    projects={}
    for repo in repos:
        full=repo.get('full_name',''); owner=full.split('/')[0]
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',full):raise InvalidData('invalid repository full_name')
        if owner.lower() in excluded or any(fnmatch.fnmatch(owner.lower(),p.lower()) for p in config.get('exclude_repo_owner_patterns',[])):continue
        if full.lower() in exclude_repos or repo.get('private') or repo.get('fork'):continue
        if config.get('only_organization_upstreams') and repo.get('owner_type')!='Organization':continue
        if repo.get('merged_authored_pr_count',0)<1:continue
        projects[full.lower()]={'full_name':full,'name':config.get('project_labels',{}).get(full,full.split('/')[1]),'url':'https://github.com/'+full,
                                'merged_authored_pr_count':count(repo['merged_authored_pr_count'])}
    return sorted(projects.values(),key=lambda p:(-p['merged_authored_pr_count'],p['full_name'].lower()))

def fetch_projects(config):
    token=os.environ.get('GITHUB_TOKEN');user=config['github_username'];q=urllib.parse.quote(f'author:{user} is:pr is:merged is:public')
    rows=[];total=None
    for page in range(1,11):
        result=json.loads(fetch(f'https://api.github.com/search/issues?q={q}&per_page=100&page={page}',token))
        if result.get('incomplete_results') is not False:raise InvalidData('GitHub search incomplete')
        total=result['total_count'];rows.extend(result['items'])
        if len(rows)>=total:break
    if total is None or len(rows)!=total or total>1000:raise InvalidData('GitHub search truncated')
    counts={}
    for row in rows:
        pr=row.get('pull_request',{})
        if not pr.get('merged_at'):raise InvalidData('search item lacks merged evidence')
        full=row['repository_url'].removeprefix('https://api.github.com/repos/')
        counts[full]=counts.get(full,0)+1
    repos=[]
    for full,n in counts.items():
        # Filter obvious self/company before repository metadata calls.
        owner=full.split('/')[0].lower()
        if owner in {x.lower() for x in config['exclude_repo_owners']} or any(fnmatch.fnmatch(owner,p.lower()) for p in config.get('exclude_repo_owner_patterns',[])):continue
        r=json.loads(fetch('https://api.github.com/repos/'+full,token))
        repos.append({'full_name':r['full_name'],'fork':r['fork'],'private':r['private'],'owner_type':r['owner']['type'],'merged_authored_pr_count':n})
    return {'incomplete_results':False,'repositories':repos,'query':f'author:{user} is:pr is:merged is:public'}

def publish(path, svg):
    ET.fromstring(svg)
    svg = '\n'.join(line.rstrip() for line in svg.splitlines()).rstrip() + '\n'
    if path.exists() and path.read_text() == svg: return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(svg)
    temporary.replace(path)

def validate_productive(raw):
    root = ET.fromstring(raw)
    texts = ' '.join(''.join(n.itertext()) for n in root.iter() if n.tag.endswith('text'))
    bars = [n for n in root.iter() if n.tag.endswith('rect') and n.get('class') == 'bar']
    if not root.tag.endswith('svg') or re.search(r'ERROR|rate.?limit|unavailable|try again', texts, re.I):
        raise InvalidData('Productive Time provider returned an error card')
    if 'Commits (UTC +8.00)' not in texts or 'per day hour' not in texts or len(bars) != 24:
        raise InvalidData('Productive Time must contain the UTC+8 24-hour chart')
    if any(not math.isfinite(float(b.get('height', 'nan'))) or float(b.get('height', '-1')) < 0 for b in bars):
        raise InvalidData('invalid Productive Time bar values')
    for node in root.iter():
        if node.tag.rsplit('}', 1)[-1] in {'script', 'foreignObject'} or any(k.lower().startswith('on') for k in node.attrib):
            raise InvalidData('unsafe SVG content')

def update_productive(today, captured):
    raw = fetch('https://github-stats.perfecto23.com/summary/productive-time?username='+USER+'&theme=tokyonight&utcOffset=8')
    validate_productive(raw)
    publish(ROOT / 'assets/productive-time.svg', raw.decode())

def mobile_overview(raw, captured):
    root = ET.fromstring(raw)
    ns = {'s': 'http://www.w3.org/2000/svg'}
    group = root.find('s:g[@class="gpsc-root"]', ns)
    if root.get('viewBox') != '0 0 700 200' or group is None:
        raise InvalidData('unexpected Overview layout; retain previous mobile card')
    body = group.find('s:g[@transform="translate(0,40)"]', ns)
    graph = body.find('s:g[@transform="translate(295,10)"]', ns) if body is not None else None
    if graph is None or not graph.findall('.//s:path', ns):
        raise InvalidData('Overview graph missing')
    if any(n.tag.rsplit('}', 1)[-1] in {'script', 'foreignObject'} or any(k.lower().startswith('on') for k in n.attrib) for n in root.iter()):
        raise InvalidData('unsafe Overview SVG')
    root.set('width', '460'); root.set('height', '390'); root.set('viewBox', '0 0 460 390')
    group.find('s:rect', ns).set('width', '458')
    graph.set('transform', 'translate(53,180)')
    for node in graph.iter():
        if node.get('font-size') == '10': node.set('font-size', '13')
    for axis in graph.findall('.//s:g[@text-anchor="start"]', ns):
        ticks = axis.findall('s:g[@class="tick"]', ns)
        for tick in ticks[1::2]: axis.remove(tick)
    note = ET.SubElement(group, '{'+ns['s']+'}text', {'x': '16', 'y': '379', 'font-size': '11', 'fill': '#a9b1d6'})
    note.text = 'Snapshot: '+captured[:10]+' UTC'
    ET.register_namespace('', ns['s'])
    return ET.tostring(root, encoding='unicode')

def update_overview(today, captured):
    raw = fetch('https://github-stats.perfecto23.com/summary/profile-details?username='+USER+'&theme=tokyonight')
    publish(ROOT / 'assets/overview-mobile.svg', mobile_overview(raw, captured))

def update_projects(today, captured):
    raw = fetch_projects(CONFIG)
    projects = filter_projects(raw['repositories'], CONFIG)
    if not projects: raise InvalidData('empty external upstream list')
    links = ' · '.join(f'<a href="{html.escape(p["url"], quote=True)}">{html.escape(p["name"])}</a>' for p in projects[:12])
    pattern = r'(?<=<!-- BEGIN AUTO:PROJECTS -->).*?(?=<!-- END AUTO:PROJECTS -->)'
    updates = []
    for filename, label in (('README.md', 'Contributed to:'), ('README.zh-CN.md', '参与贡献的项目：')):
        path = ROOT / filename
        text = path.read_text()
        if len(re.findall(pattern, text, re.S)) != 1:
            raise InvalidData(f'{filename}: project markers missing/duplicated')
        updated = re.sub(pattern, lambda _: '\n<p><strong>' + label + '</strong> ' + links + '</p>\n', text, flags=re.S)
        updates.append((path, text, updated))
    # Validate both documents before changing either language.
    for path, text, updated in updates:
        if updated != text: path.write_text(updated)

def check():
    for filename in ('README.md', 'README.zh-CN.md'):
        readme = (ROOT / filename).read_text()
        assert readme.count('<details>') == readme.count('</details>')
        assert readme.count('<picture>') == readme.count('</picture>')
        assert readme.count('<!-- BEGIN AUTO:PROJECTS -->') == 1
        assert readme.count('<!-- END AUTO:PROJECTS -->') == 1
        for path in re.findall(r'(?:src|srcset)="(assets/[^"\s]+)"', readme):
            assert (ROOT / path).is_file(), path
    for path in (ROOT / 'assets').glob('*.svg'): ET.parse(path)
    validate_productive((ROOT / 'assets/productive-time.svg').read_bytes())
    print('Both READMEs and custom SVG resources valid')

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if args.check:
        check()
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    errors = []
    for operation in (update_ai, update_projects, update_productive, update_overview):
        try: operation(now.date(), now.isoformat(timespec='seconds'))
        except Exception as exc:
            errors.append(operation.__name__)
            if operation is update_ai: mark_ai_retained(now.date(), now.isoformat(timespec='seconds'))
            print(f'{operation.__name__}: retained previous output ({type(exc).__name__}: {exc})', file=sys.stderr)
    check()
    return int(bool(errors))

if __name__ == '__main__': sys.exit(main())
