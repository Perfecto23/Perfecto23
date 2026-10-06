#!/usr/bin/env python3
"""Update AI, the Productive Time fallback and project names; other cards stay remote.
Run --check for offline validation. Network failures preserve existing files.
Raw TokenTracker/GitHub responses are processed in memory and never saved.
"""
import argparse, datetime as dt, decimal, fnmatch, html, json, math, os, re, sys
import urllib.parse, urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
D = decimal.Decimal
USER = 'Perfecto23'
TOKEN_USER = 'b6f3aece-2e2d-4764-91aa-963aa814aca0'
TOKEN_BASE = 'https://srctyff5.us-east.insforge.app/functions/'
CONFIG = {'github_username': USER, 'identity': {'name': 'Perfecto'},
          'exclude_repo_owners': ['Perfecto23', 'MoeGo', 'moego-ai', 'moego-pet'],
          'exclude_repo_owner_patterns': ['moego*'], 'only_organization_upstreams': True,
          'project_labels': {'langgenius/dify': 'Dify', 'web-infra-dev/rspack': 'Rspack',
                             'Tencent/WeKnora': 'Tencent WeKnora'}}
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

def normalize_profile(obj, as_of, captured_at):
    if not isinstance(obj,dict):raise InvalidData('profile object required')
    if 'heatmap' not in obj and isinstance(obj.get('data'),dict):obj=obj['data']
    rows=obj.get('heatmap')
    if not isinstance(rows,list) or not rows:raise InvalidData('heatmap must be a nonempty array')
    by_date={}
    for row in rows:
        if not isinstance(row,dict):raise InvalidData('daily object required')
        date=dt.date.fromisoformat(row['date'])
        if date in by_date:raise InvalidData('duplicate daily date')
        total=count(row['total_tokens']);models=row.get('models')
        if models is None and total==0:models={}
        if not isinstance(models,dict):raise InvalidData('daily models object required')
        models={str(k):count(v) for k,v in models.items()}
        if any(not name or len(name)>120 for name in models):raise InvalidData('invalid model name')
        if sum(models.values())!=total:raise InvalidData('model tokens do not sum to daily total')
        by_date[date]={'date':date.isoformat(),'total_tokens':total,'models':models}
    dates=[as_of-dt.timedelta(days=i) for i in range(29,-1,-1)]
    missing=[d.isoformat() for d in dates if d not in by_date]
    if missing:raise InvalidData('incomplete rolling window: '+','.join(missing[:3]))
    days=[by_date[d] for d in dates];models={}
    for day in days:
        for name,n in day['models'].items():models[name]=models.get(name,0)+n
    total=sum(d['total_tokens'] for d in days)
    if total==0:raise InvalidData('empty/zero usage window; retain last-good until confirmed')
    ranking=sorted(models.items(),key=lambda item:(-item[1],item[0]))
    return {'schema_version':1,'source':'TokenTracker public profile heatmap; all models included',
            'captured_at':captured_at,'timezone':'UTC','window':[dates[0].isoformat(),dates[-1].isoformat()],
            'total_tokens':total,'daily_average_tokens':total/30,'models':[{'name':k,'tokens':v} for k,v in ranking],
            'days':days,'current_day_partial':True}

def fetch(url, token=None):
    # Credentials only attach to GitHub API, never to external image or TokenTracker services.
    headers={'User-Agent':'Perfecto23-profile-refresh/1.0'}
    if url.startswith('https://api.github.com/'):
        headers['Accept']='application/vnd.github+json';headers['X-GitHub-Api-Version']='2022-11-28'
        if token:headers['Authorization']='Bearer '+token
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=35) as r:
        if r.status!=200:raise InvalidData('unexpected HTTP status')
        data=r.read(8*1024*1024+1)
    if len(data)>8*1024*1024:raise InvalidData('response exceeds size limit')
    return data

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

def txt(x,y,value,size=14,color='#cbd5e1',weight=400):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{html.escape(str(value))}</text>'

def card(width,height,body,title):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img"><title>{html.escape(title)}</title><style>text{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}</style><defs><linearGradient id="g"><stop stop-color="#bf91f3"/><stop offset="1" stop-color="#7dcfff"/></linearGradient></defs><rect x="1" y="1" width="{width-2}" height="{height-2}" rx="10" fill="#1a1b27" stroke="#414868"/>{body}</svg>'''

def source_stamp(obj,as_of,failed=False):
    if not obj:return 'unavailable'
    stamp=obj['captured_at']
    try:
        parsed=dt.datetime.fromisoformat(stamp.replace('Z','+00:00'))
        label=parsed.astimezone(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        old=parsed.astimezone(dt.timezone.utc).date()<as_of
    except ValueError:label=stamp;old=True
    return label+(' · retained' if failed else ' · older' if old else '')

def render_ai(ai,profile_summary,config,as_of=None,panel="overview"):
    as_of=as_of or dt.date.fromisoformat(ai['window'][1])
    n=ai['total_tokens'];rows=ai['models'];start,end=ai['window'];partial=not bool(ai.get('days'))
    # Two fixed-width panels wrap naturally in GitHub Markdown without device/theme variants.
    b=txt(24,31,'Perfecto · TokenTracker',14,'#a9b1d6')
    if panel == 'models':
        b+=txt(16,76,'Models · last 30 days',23,'#70a5fd',700)
        for i,row in enumerate(sorted(rows,key=lambda m:(-m['tokens'],m['name']))[:5]):
            y=110+i*43;share=row['tokens']/n
            share_label='<0.1%' if 0<share<0.001 else f'{share:.1%}'
            b+=txt(16,y,row['name'],17,'#c0caf5',500)
            b+=txt(258,y,compact(row['tokens']),16,'#7dcfff',600)+txt(338,y,share_label,14,'#a9b1d6')
            b+=f'<rect x="16" y="{y+12}" width="368" height="6" rx="3" fill="#292e42"/><rect x="16" y="{y+12}" width="{368*share:.2f}" height="6" rx="3" fill="url(#g)"/>'
        b+=txt(16,325,f'Top 5 of {len(rows)} models · share of all tokens',14,'#a9b1d6')
    else:
        b+=txt(16,68,'Profile total · 365 days',16,'#70a5fd',600)
        b+=txt(16,111,profile_summary['display'] if profile_summary else '—',40,'#c0caf5',700)
        for x,label,val in [(16,'Last 30 days',compact(n)),(216,'Daily average',compact(n/30))]:
            b+=txt(x,150,label,16,'#a9b1d6')+txt(x,181,val,28,'#7dcfff',700)
        b+=txt(16,207,f'{start} → {end} · UTC',14,'#a9b1d6')
        b+=txt(16,242,'Daily activity',18,'#70a5fd',600)
        if partial:
            b+=txt(16,281,'Daily detail pending import',16,'#bf91f3')
        else:
            maximum=max(d['total_tokens'] for d in ai['days']);palette=['#292e42','#414868','#62578f','#8b71c1','#bf91f3','#7dcfff']
            for i,day in enumerate(ai['days']):
                v=day['total_tokens'];level=0 if not v else min(5,max(1,math.ceil(5*math.log1p(15*v/maximum)/math.log(16))))
                x=16+(i%15)*24.5;y=255+(i//15)*27;label=f"{day['date']}: {compact(v)} tokens"
                b+=f'<rect x="{x}" y="{y}" width="21" height="23" rx="3" fill="{palette[level]}"><title>{html.escape(label)}</title></rect>'
            b+=txt(16,325,start,14,'#a9b1d6')+txt(290,325,end,14,'#a9b1d6')
    b+='<path d="M16 337H384" stroke="#414868"/>'
    b+=txt(16,357,'Total: '+source_stamp(profile_summary,as_of),12,'#a9b1d6')
    b+=txt(16,377,'30d: '+source_stamp(ai,as_of),12,'#a9b1d6')
    return card(400,394,b,'Perfecto AI usage: '+('past-30-day Top 5 models' if panel == 'models' else '365-day profile total, past-30-day total, daily average and heatmap'))

def publish(path, svg):
    ET.fromstring(svg)
    svg = '\n'.join(line.rstrip() for line in svg.splitlines()).rstrip() + '\n'
    if path.exists() and path.read_text() == svg: return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(svg)
    temporary.replace(path)

def profile_total(profile, captured):
    if 'heatmap' not in profile and isinstance(profile.get('data'), dict): profile = profile['data']
    period = profile['period']
    start, end = (dt.date.fromisoformat(period[k]) for k in ('from', 'to'))
    if period['kind'] != 'total' or (end-start).days != 364:
        raise InvalidData('public profile total must cover 365 inclusive days')
    rows = profile['heatmap']
    expected = [(start+dt.timedelta(days=i)).isoformat() for i in range(365)]
    if sorted(row['date'] for row in rows) != expected:
        raise InvalidData('public profile total requires a complete daily window')
    total = count(profile['totals']['total_tokens'])
    if not total or sum(count(row['total_tokens']) for row in rows) != total:
        raise InvalidData('public profile headline does not reconcile with daily usage')
    return {'display': compact(total, 1), 'captured_at': captured,
            'window': [start.isoformat(), end.isoformat()], 'total_tokens': total}

def update_ai(today, captured):
    # Headline, 30-day models and heatmap come from the same public profile response.
    profile = json.loads(fetch(TOKEN_BASE + 'tokentracker-leaderboard-profile?user_id=' + TOKEN_USER + '&period=total&tz=Etc%2FUTC'))
    daily = normalize_profile(profile, today, captured)
    profile_summary = profile_total(profile, captured)
    panels = [('ai-usage.svg', 'overview'), ('ai-models.svg', 'models')]
    rendered = [(name, render_ai(daily, profile_summary, CONFIG, today, panel)) for name, panel in panels]
    for name, svg in rendered: ET.fromstring(svg)
    for name, svg in rendered: publish(ROOT / 'assets' / name, svg)

def mark_ai_retained(today, captured):
    for name in ('ai-usage.svg', 'ai-models.svg'):
        path = ROOT / 'assets' / name
        if not path.exists(): continue
        svg = path.read_text()
        stamp = dt.datetime.fromisoformat(captured.replace('Z', '+00:00')).astimezone(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        status = html.escape('Refresh failed '+stamp)+'<tspan x="24" dy="19">saved snapshot retained</tspan>'
        svg, changed = re.subn(r'(<text x="24" y="31"[^>]*>).*?(</text>)', lambda m: m[1]+status+m[2], svg, count=1)
        if changed != 1: raise InvalidData('AI status label missing')
        def retained(m):
            value = re.sub(r' · (?:older|retained)', '', m[2])
            old = dt.date.fromisoformat(value[:10]) < today
            return '>'+m[1]+value+(' · older' if old else '')+' · retained<'
        svg = re.sub(r'>(Total: |30d: )([^<]+)<', retained, svg)
        publish(path, svg)

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
