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
        'faint': '#a8a29e', 'hero': '#6d28d9',
        'track': '#e7e5e4',
        'tile': '#f5f3ff', 'tile_border': '#ddd6fe',
        'mix': ['#5b21b6', '#7c3aed', '#a78bfa', '#c4b5fd'], 'mix_rest': '#e7e5e4',
        'levels': ['#f5f5f4', '#ddd6fe', '#c4b5fd', '#8b5cf6', '#5b21b6'],
    },
    'dark': {
        'bg': '#161b22', 'border': '#30363d', 'title': '#f5f5f4', 'muted': '#a8a29e',
        'faint': '#78716c', 'hero': '#c4b5fd',
        'track': '#30363d',
        'tile': '#241c33', 'tile_border': '#3d3454',
        'mix': ['#c4b5fd', '#8b5cf6', '#6d28d9', '#4c1d95'], 'mix_rest': '#3d444d',
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

def active_caption(data):
    pct = share(data['active_days'], data['span_days'])
    if 360 <= data['span_days'] <= 372:
        return pct + ' of the year'
    return pct + f" of {data['span_days']}d"

def short_day(iso):
    date = dt.date.fromisoformat(iso)
    return f'{MONTHS[date.month - 1]} {date.day}'

def month_summary(days):
    groups = []
    index = {}
    for day in days:
        date = dt.date.fromisoformat(day['date'])
        key = f'{date.year:04d}-{date.month:02d}'
        row = index.get(key)
        if row is None:
            row = {
                'key': key, 'year': date.year, 'month': date.month,
                'label': MONTHS[date.month - 1], 'tokens': 0, 'active_days': 0,
                'first': date, 'last': date,
            }
            index[key] = row
            groups.append(row)
        row['tokens'] += day['total_tokens']
        row['last'] = date
        if day['total_tokens']:
            row['active_days'] += 1
    for row in groups:
        first = dt.date(row['year'], row['month'], 1)
        if row['month'] == 12:
            nxt = dt.date(row['year'] + 1, 1, 1)
        else:
            nxt = dt.date(row['year'], row['month'] + 1, 1)
        last = nxt - dt.timedelta(days=1)
        row['partial'] = row['first'] > first or row['last'] < last
        del row['first']
        del row['last']
    return groups

def _top_entry(mapping, labeler):
    ranked = [(name, tokens) for name, tokens in mapping.items() if tokens > 0]
    if not ranked:
        return None
    name, tokens = max(ranked, key=lambda item: (item[1], item[0]))
    return {'name': name, 'label': labeler(name), 'tokens': tokens}

def period_stats(detail, end, length):
    start = end - dt.timedelta(days=length - 1)
    tokens = 0
    active = 0
    clients = {}
    models = {}
    for offset in range(length):
        row = detail.get(start + dt.timedelta(days=offset))
        if row is None:
            continue
        total, client_acc, model_acc = row
        tokens += total
        if total:
            active += 1
        for name, value in client_acc.items():
            clients[name] = clients.get(name, 0) + value
        for name, value in model_acc.items():
            models[name] = models.get(name, 0) + value
    return {
        'start': start.isoformat(),
        'end': end.isoformat(),
        'days': length,
        'tokens': tokens,
        'active_days': active,
        'top_client': _top_entry(clients, client_label),
        'top_model': _top_entry(models, lambda name: name),
    }

def period_span(recent):
    start = dt.date.fromisoformat(recent['start'])
    end = dt.date.fromisoformat(recent['end'])
    if start.year == end.year:
        return f"{short_day(recent['start'])} – {short_day(recent['end'])}"
    return f"{short_day(recent['start'])} {start.year} – {short_day(recent['end'])} {end.year}"

def subtitle_for(data):
    if 360 <= data['span_days'] <= 372:
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
    detail = {}
    clients = {}
    models = {}
    for row in rows:
        date, total, client_acc, model_acc = _acc(row)
        if date in by_date:
            raise InvalidData('duplicate daily date')
        by_date[date] = total
        detail[date] = (total, client_acc, model_acc)
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
    if not days:
        raise InvalidData('chart window is empty')
    peak = max(days, key=lambda day: (day['total_tokens'], day['date']))
    months = month_summary(days)
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
        'peak_tokens': peak['total_tokens'],
        'peak_date': peak['date'],
        'window': [start.isoformat(), end.isoformat()],
        'span_days': span,
        'days': days,
        'months': months,
        'recent': period_stats(detail, end, 30),
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

def mix_line(x, y, prefix, entries, total, theme, max_width, prefix_width=72):
    chosen = []
    for entry in entries[:5]:
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
    name_x = x if not prefix else x + prefix_width
    prefix_svg = text(x, y, prefix, 12, theme['muted'], 600) if prefix else ''
    return prefix_svg + f'<text x="{name_x}" y="{y}" font-size="13">{inner}</text>'

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
        f"{hero_compact(data['total_tokens'])} tokens, peak {compact(data['peak_tokens'], 2)}, "
        f"{data['active_days']} active days, rank {data['rank']}"
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

def header(data, theme, title_x, title_y, right_x):
    mark_y = title_y - 11
    subtitle_y = title_y + 20
    return ''.join([
        f'<rect x="{title_x}" y="{mark_y}" width="8" height="8" rx="2" fill="{theme["hero"]}"/>',
        text(title_x + 14, title_y, 'AI coding usage', 15, theme['title'], 700),
        text(right_x, title_y, 'tokscale', 12, theme['muted'], 500, anchor='end'),
        text(title_x + 14, subtitle_y, subtitle_for(data), 12, theme['muted']),
    ])

def label_entries(entries, total, limit=4):
    shown = [entry for entry in entries if entry['tokens'] > 0][:limit]
    rest = total - sum(entry['tokens'] for entry in shown)
    if rest > 0 and total and rest / total >= 0.05:
        shown.append({'name': 'Other', 'label': 'Other', 'tokens': rest})
    return shown

def stacked_rows(entries, total, limit=4):
    shown = [entry for entry in entries[:limit] if entry['tokens'] > 0]
    used = sum(entry['tokens'] for entry in shown)
    rows = [{
        'label': entry.get('label') or entry['name'],
        'tokens': entry['tokens'],
        'rest': False,
    } for entry in shown]
    rest = total - used
    if rest > 0:
        rows.append({'label': 'Other', 'tokens': rest, 'rest': True})
    return rows

def segment_widths(weights, width, gap, minimum=5):
    count_rows = len(weights)
    if count_rows == 0:
        return []
    usable = width - gap * (count_rows - 1)
    if usable <= 0:
        return [0.0] * count_rows
    whole = sum(weights) or 1
    raw = [usable * weight / whole for weight in weights]
    if minimum * count_rows > usable:
        return raw
    widths = [max(minimum, value) for value in raw]
    extra = sum(widths) - usable
    if extra <= 0:
        return widths
    flexible = [index for index, value in enumerate(raw) if value > minimum]
    pool = sum(widths[index] - minimum for index in flexible)
    if pool <= 0:
        return raw
    for index in flexible:
        room = widths[index] - minimum
        widths[index] -= extra * room / pool
    return widths

def stacked_bar(x, y, width, height, entries, total, theme, chart_id):
    rows = stacked_rows(entries, total)
    gap = 3
    widths = segment_widths([row['tokens'] for row in rows], width, gap)
    parts = [f'<g data-chart="mix" data-mix="{esc(chart_id)}">']
    cursor = float(x)
    for index, (row, seg_w) in enumerate(zip(rows, widths)):
        color = theme['mix_rest'] if row['rest'] else theme['mix'][min(index, len(theme['mix']) - 1)]
        tip = f"{row['label']}: {compact(row['tokens'])} tokens, {share(row['tokens'], total)}"
        parts.append(
            f'<rect x="{cursor:.2f}" y="{y}" width="{max(seg_w, 0):.2f}" height="{height}" rx="{height / 2:.1f}" fill="{color}">'
            f'<title>{esc(tip)}</title></rect>'
        )
        cursor += seg_w + gap
    parts.append('</g>')
    return ''.join(parts)

def metric_tile(x, y, width, height, label, value, caption, theme, value_color, tip):
    return ''.join([
        '<g>',
        f'<title>{esc(tip)}</title>',
        f'<rect x="{x:.2f}" y="{y}" width="{width:.2f}" height="{height}" rx="12" fill="{theme["tile"]}" stroke="{theme["tile_border"]}"/>',
        text(x + 14, y + 22, label, 11, theme['muted'], 600),
        text(x + 14, y + 52, value, value_size_for(value, 26), value_color, 700),
        text(x + 14, y + 72, caption, 11, theme['faint'], 500),
        '</g>',
    ])

def dimension_tiles(data, theme, x, y, width, gap=10):
    tile_w = (width - 2 * gap) / 3
    specs = [
        ('Peak day', compact(data['peak_tokens'], 2), short_day(data['peak_date']), theme['hero'],
         f"Peak day {data['peak_date']}: {compact(data['peak_tokens'])} tokens"),
        ('Active days', f"{data['active_days']:,}", active_caption(data), theme['title'],
         f"{data['active_days']} active days in {data['span_days']}"),
        ('All-time rank', rank_label(data['rank']), 'on tokscale', theme['title'],
         f"All-time rank {data['rank']}"),
    ]
    parts = []
    for index, (label, value, caption, color, tip) in enumerate(specs):
        parts.append(metric_tile(x + index * (tile_w + gap), y, tile_w, 86, label, value, caption, theme, color, tip))
    return ''.join(parts)

def share_block(x, y, width, title, entries, total, theme, chart_id):
    return ''.join([
        text(x, y, title, 12, theme['muted'], 600),
        stacked_bar(x, y + 8, width, 12, entries, total, theme, chart_id),
        mix_line(x, y + 36, '', label_entries(entries, total), total, theme, width, prefix_width=0),
    ])

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

def month_chart(data, theme, x, y, width):
    rows = data['months']
    count = len(rows)
    gap = 8
    slot = (width - gap * (count - 1)) / count if count else 0
    bar_w = min(26, max(6, slot - 10))
    plot_h = 48
    positive = [row['tokens'] for row in rows if row['tokens'] > 0]
    floor = math.log10(min(positive)) if positive else 0
    ceiling = math.log10(max(positive)) if positive else 1
    span = ceiling - floor
    repeated = len({row['label'] for row in rows}) < count
    parts = ['<g data-chart="months">']
    for index, row in enumerate(rows):
        left = x + index * (slot + gap)
        cx = round(left + slot / 2, 1)
        if row['tokens'] <= 0 or span <= 0:
            bar_h = plot_h if row['tokens'] > 0 else 0
        else:
            bar_h = 6 + (plot_h - 6) * (math.log10(row['tokens']) - floor) / span
        bar_x = cx - bar_w / 2
        bar_y = y + plot_h - bar_h
        suffix = ' · partial' if row['partial'] else ''
        tip = f"{row['key']}: {compact(row['tokens'])} tokens, {row['active_days']} active days{suffix}"
        opacity = '1' if positive and row['tokens'] == max(positive) else '0.72'
        parts.append(
            f'<rect x="{bar_x:.1f}" y="{bar_y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="3" fill="{theme["hero"]}" fill-opacity="{opacity}" data-month="{row["key"]}">'
            f'<title>{esc(tip)}</title></rect>'
        )
        name = row['label']
        if repeated and slot >= 46:
            name = f"{row['label']} {row['year'] % 100:02d}"
        parts.append(text(cx, y + plot_h + 16, name, 11, theme['muted'], 600, anchor='middle'))
        if row['tokens'] > 0 and slot >= 34:
            parts.append(text(cx, round(bar_y - 6, 1), hero_compact(row['tokens']), 10, theme['faint'], 600, anchor='middle'))
    parts.append('</g>')
    return '\n'.join(parts), y + plot_h + 16

def recent_meta(recent):
    bits = [f"{recent['active_days']} active"]
    total = recent['tokens']
    model = recent.get('top_model')
    client = recent.get('top_client')
    if model and total:
        name = model['name'] if len(model['name']) <= 28 else model['name'][:27] + '…'
        bits.append(name + ' ' + share(model['tokens'], total))
    if client and total:
        bits.append(client['label'] + ' ' + share(client['tokens'], total))
    return ' · '.join(bits)

def render_desktop(data, theme, as_of):
    width = 820
    left = 36
    right = width - 36
    inner = right - left
    total = data['total_tokens']
    tiles_x = left + 236
    recent = data['recent']
    rule_y = 384
    month_y = 436
    months, month_bottom = month_chart(data, theme, left, month_y, inner)
    grid_y = month_bottom + 46
    chart, grid_bottom, _grid_width = heatmap(data, theme, left, grid_y, inner)
    legend_y = grid_bottom + 22
    height = legend_y + 18
    start, end = data['window']
    busiest = max(data['months'], key=lambda row: (row['tokens'], row['key']))
    body = '\n'.join([
        frame(width, height, theme),
        header(data, theme, left, 36, right),
        text(left, 96, 'Total tokens', 12, theme['muted'], 600),
        text(left, 146, hero_compact(total), 48, theme['hero'], 700),
        dimension_tiles(data, theme, tiles_x, 78, right - tiles_x),
        share_block(left, 188, inner, 'Models', data['models'], total, theme, 'models'),
        share_block(left, 252, inner, 'Clients', data['clients'], total, theme, 'clients'),
        text(left, 316, 'Last 30 days', 12, theme['muted'], 600),
        text(left, 342, hero_compact(recent['tokens']), 22, theme['hero'], 700),
        text(right, 342, period_span(recent), 13, theme['muted'], 500, anchor='end'),
        text(left, 364, recent_meta(recent), 12, theme['muted'], 500),
        f'<line x1="{left}" y1="{rule_y}.5" x2="{right}" y2="{rule_y}.5" stroke="{theme["border"]}"/>',
        text(left, 408, 'Months · log', 12, theme['muted'], 600),
        text(right, 408, f"Busiest {busiest['label']} {hero_compact(busiest['tokens'])}", 12, theme['title'], 600, anchor='end'),
        months,
        chart,
        legend(left, legend_y, theme),
        text((left + right) // 2, legend_y, f'{start} – {end}', 11, theme['muted'], anchor='middle'),
        text(right, legend_y, status_line(data, as_of), 11, theme['muted'], anchor='end', eid='ai-status'),
    ])
    return svg_doc(width, height, card_title(data), body)

def render_usage(data, theme_name, as_of):
    return render_desktop(data, THEMES[theme_name], as_of)

def update_ai(today, captured):
    # Official embeds exist at /api/embed/<user>/svg and /api/badge/<user>/svg.
    # They are public too, but the badge is one number, and the card's intensity
    # scale flattens this profile while omitting clients and models. Drawing from
    # the public JSON keeps a last-good snapshot and needs no secret.
    profile = json.loads(fetch(TOKSCALE_API))
    data = normalize_tokscale(profile, today, captured)
    rendered = []
    for theme_name in ('light', 'dark'):
        rendered.append((f'ai-usage-{theme_name}.svg', render_usage(data, theme_name, today)))
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
