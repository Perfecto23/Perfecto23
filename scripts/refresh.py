#!/usr/bin/env python3
"""Build local profile assets from validated inputs; --fetch explicitly enables network.
No dependencies, secrets creation, git mutation, or remote publication.
"""
from __future__ import annotations
import argparse, hashlib, datetime as dt, decimal, fnmatch, html, json, math, os, re, sys, urllib.parse, urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET
D=decimal.Decimal
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import themes
PROFILE_BASE='https://srctyff5.us-east.insforge.app/functions/'

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

def read_json(path):
    if path.stat().st_size>8*1024*1024:raise InvalidData('input exceeds 8 MiB')
    return json.loads(path.read_text())

def write_atomic(path, content):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=content if isinstance(content,bytes) else content.encode()
    if path.suffix=='.svg':data=('\n'.join(line.rstrip() for line in data.decode().splitlines()).rstrip()+'\n').encode()
    if path.exists() and path.read_bytes()==data:return
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_bytes(data);temp.replace(path)

def json_write(path, obj):write_atomic(path,json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

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

def parse_embed(data, captured_at):
    e=validate_svg(data,'tokentracker')
    texts=[''.join(n.itertext()).strip() for n in e.iter() if n.tag.endswith('text')]
    try:value=texts[texts.index('TOKENS')+1]
    except (ValueError,IndexError):raise InvalidData('embed token headline not found')
    m=re.fullmatch(r'([\d,.]+)([KMBT]?)',value)
    if not m:raise InvalidData('unrecognized embed headline')
    multiplier={'':1,'K':1000,'M':10**6,'B':10**9,'T':10**12}[m[2]]
    n=D(m[1].replace(',',''))*multiplier
    if n<=0:raise InvalidData('empty cumulative headline')
    return {'source':'Official TokenTracker cumulative embed, rounded provider display',
            'captured_at':captured_at,'display':compact(n),'approximate_tokens':str(n),'total_tokens_exact':None if m[2] else int(n),'rounded':bool(m[2])}

def public_ai_snapshot(ai):
    """Publish only the visible Top 5 and daily totals, never raw model history."""
    total=count(ai['total_tokens'])
    if total<=0:raise InvalidData('empty public AI summary')
    models=sorted(ai['models'],key=lambda m:(-count(m['tokens']),m['name']))
    if len({m['name'] for m in models})!=len(models):raise InvalidData('duplicate model name')
    if sum(count(m['tokens']) for m in models)>total:raise InvalidData('model sum exceeds full total')
    out={k:ai[k] for k in ['schema_version','source','captured_at','timezone','window','current_day_partial']}
    out.update(total_tokens=total,daily_average_tokens=total/30,
               model_count=ai.get('model_count',len(models)),
               models_display_scope='Top 5 only; full source total retained',models=models[:5],
               days=[{'date':d['date'],'total_tokens':count(d['total_tokens'])} for d in ai['days']])
    if len(out['days'])!=30 or sum(d['total_tokens'] for d in out['days'])!=total:raise InvalidData('public daily totals do not reconcile')
    expected=[(dt.date.fromisoformat(out['window'][0])+dt.timedelta(days=i)).isoformat() for i in range(30)]
    if [d['date'] for d in out['days']]!=expected or expected[-1]!=out['window'][1]:raise InvalidData('public daily dates must cover exactly 30 UTC days')
    return out

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

def normalize_projects(obj, config, captured_at):
    if not isinstance(obj,dict) or obj.get('incomplete_results') is not False:raise InvalidData('complete merged-PR source required')
    repos=obj.get('repositories')
    if not isinstance(repos,list) or not repos:raise InvalidData('empty repository response')
    items=filter_projects(repos,config)
    if not items:raise InvalidData('empty external upstream list; retain last-good')
    return {'schema_version':1,'captured_at':captured_at,'scope':'Public merged authored organization-upstream PRs; deduplicated; personal/self/company/forks excluded',
            'projects':items,'excluded_owners':config['exclude_repo_owners']}

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
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img"><title>{html.escape(title)}</title><style>text{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}</style><defs><linearGradient id="g"><stop stop-color="#a78bfa"/><stop offset="1" stop-color="#22d3ee"/></linearGradient></defs><rect x="1" y="1" width="{width-2}" height="{height-2}" rx="20" fill="#101827" stroke="#334155"/>{body}</svg>'''

def source_stamp(obj,as_of,failed=False):
    if not obj:return 'unavailable'
    stamp=obj['captured_at']
    try:
        parsed=dt.datetime.fromisoformat(stamp.replace('Z','+00:00'))
        label=parsed.astimezone(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        old=parsed.astimezone(dt.timezone.utc).date()<as_of
    except ValueError:label=stamp;old=True
    return label+(' · retained' if failed else ' · older' if old else '')

def render_ai(ai,cumulative,config,as_of=None,daily_failed=False,cumulative_failed=False,all_time=None):
    as_of=as_of or dt.date.fromisoformat(ai['window'][1])
    n=ai['total_tokens'];rows=ai['models'];start,end=ai['window'];partial=not bool(ai.get('days'))
    b=txt(24,31,'about-perfecto.md',12,'#94a3b8')+txt(758,31,'TokenTracker · UTC',12,'#94a3b8')
    b+=txt(24,65,config['identity']['name'],24,'#f8fafc',700)+txt(151,64,'AI coding usage',15,'#c4b5fd')
    for x,label,val in [(24,'TOTAL USAGE',cumulative['display'] if cumulative else '—'),(342,'LAST 30 DAYS',compact(n)),(660,'DAILY AVERAGE',compact(n/30))]:
        b+=txt(x,98,label,10,'#94a3b8',600)+txt(x,136,val,30,'#22d3ee' if x==660 else '#f8fafc',700)
    b+=txt(24,161,f'{start} → {end} · inclusive UTC window',11,'#94a3b8')
    b+='<path d="M24 177H936" stroke="#334155"/>'
    b+=txt(24,201,'Past 30 days · Top 5',16,'#e2e8f0',600)+txt(492,201,'All-time · Top 5',16,'#e2e8f0',600)
    def ranking(x,models,total):
        result=''
        for i,row in enumerate(sorted(models,key=lambda m:(-m['tokens'],m['name']))[:5]):
            y=228+i*33;share=row['tokens']/total
            share_label='<0.1%' if 0<share<0.001 else f'{share:.1%}'
            result+=txt(x,y,row['name'],12,'#cbd5e1',500)+txt(x+305,y,compact(row['tokens']),12,'#e2e8f0',600)+txt(x+391,y,share_label,11,'#94a3b8')
            result+=f'<rect x="{x}" y="{y+8}" width="440" height="3" rx="1.5" fill="#273449"/><rect x="{x}" y="{y+8}" width="{440*share:.2f}" height="3" rx="1.5" fill="url(#g)"/>'
        return result
    b+=ranking(24,rows,n)
    if all_time:
        # No current public source fulfills this contract. Never accept the
        # profile's period=total (365d), a favorite, or provider shares here.
        if all_time.get('scope')!='all_time' or all_time.get('complete_history') is not True:raise InvalidData('verified complete all-time model scope required')
        models=all_time.get('models');total=count(all_time.get('total_tokens'))
        if not models or not total or sum(count(m['tokens']) for m in models)!=total:raise InvalidData('complete all-time model totals required')
        b+=ranking(492,models,total)
    else:
        b+=txt(492,258,'Not available',22,'#c4b5fd',600)+txt(492,287,'in public data',12,'#94a3b8')
    heat_y=405;b+=txt(24,heat_y,'Daily activity',16,'#e2e8f0',600)
    if partial:
        b+=txt(24,heat_y+26,'Daily detail pending import',12,'#c4b5fd');bottom=heat_y+50
    else:
        maximum=max(d['total_tokens'] for d in ai['days']);palette=['#1e293b','#353958','#514b80','#7c6aa6','#a78bfa','#22d3ee']
        for i,day in enumerate(ai['days']):
            v=day['total_tokens'];level=0 if not v else min(5,max(1,math.ceil(5*math.log1p(15*v/maximum)/math.log(16))))
            x=24+i*30.5;label=f"{day['date']}: {compact(v)} tokens"
            b+=f'<rect x="{x}" y="{heat_y+17}" width="25" height="22" rx="4" fill="{palette[level]}"><title>{html.escape(label)}</title></rect>'
        b+=txt(24,heat_y+57,start,10,'#94a3b8')+txt(856,heat_y+57,end,10,'#94a3b8');bottom=heat_y+82
    b+=txt(24,bottom,'Total: '+source_stamp(cumulative,as_of,cumulative_failed),10,'#64748b')
    b+=txt(492,bottom,'30d: '+source_stamp(ai,as_of,daily_failed),10,'#64748b')
    return card(960,bottom+20,b,'Perfecto AI usage: cumulative totals, past-30-day Top 5, all-time availability and daily heatmap')

def render_heatmap(ai):
    if not ai.get('days'):return None
    days=ai['days'];maximum=max(d['total_tokens'] for d in days)
    b=txt(32,44,'30-day token activity',24,'#c4b5fd',650)+txt(32,72,f"{ai['window'][0]} → {ai['window'][1]} · UTC · {compact(ai['total_tokens'])} tokens",13,'#94a3b8')
    for i,d in enumerate(days):
        x=32+i*30;v=d['total_tokens'];height=0 if not v else 8+100*math.log1p(v)/math.log1p(maximum)
        b+=f'<rect x="{x}" y="{200-height:.2f}" width="23" height="{height:.2f}" rx="3" fill="url(#g)"><title>{d["date"]}: {html.escape(compact(v))} tokens</title></rect>'
    b+=txt(32,232,'Daily volume · log scale · window end is partial',12,'#94a3b8')
    return card(960,256,b,'30-day daily token activity, log-scaled bar chart')

def generated_html(body):
    # Continuous HTML keeps generator comments hidden and avoids Typora splitting blocks.
    out=[]
    for part in body.strip().split("\n\n"):
        t=html.escape(part)
        t=re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",r'<img src="\2" alt="\1" />',t)
        t=re.sub(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)",r'<a href="\2">\1</a>',t)
        t=re.sub(r"\*\*([^*]+)\*\*",r'<strong>\1</strong>',t)
        t=re.sub(r"\*([^*]+)\*",r'<em>\1</em>',t)
        t=re.sub(r"`([^`]+)`",r'<code>\1</code>',t)
        out.append('<p>'+t+'</p>')
    return "\n".join(out)

def versioned_asset(assets, prefix, content):
    digest=hashlib.sha256(content.encode()).hexdigest()[:12]
    filename=f'{prefix}-{digest}.svg'
    write_atomic(assets/filename,content)
    # Remove only prior outputs owned by this exact generator prefix.
    for old in assets.glob(prefix+'-*.svg'):
        if old.name!=filename and re.fullmatch(re.escape(prefix)+r'-[0-9a-f]{12}\.svg',old.name):old.unlink()
    return 'assets/'+filename


def update_region(readme,name,body):
    begin=f'<!-- BEGIN AUTO:{name} -->';end=f'<!-- END AUTO:{name} -->';pattern=re.escape(begin)+r'.*?'+re.escape(end)
    if len(re.findall(pattern,readme,re.S))!=1:raise InvalidData('missing or duplicate generated region '+name)
    return re.sub(pattern,lambda _:begin+'\n'+generated_html(body)+'\n'+end,readme,flags=re.S)

def validate_svg(data,name=None):
    root=ET.fromstring(data)
    local=lambda tag:tag.rsplit('}',1)[-1]
    if local(root.tag)!='svg':raise InvalidData('image not SVG')
    nodes=list(root.iter());s=data.decode() if isinstance(data,bytes) else data
    if any(local(n.tag) in {'script','foreignObject'} or any(k.lower().startswith('on') for k in n.attrib) for n in nodes):raise InvalidData('unsafe SVG response')
    text=' '.join(''.join(n.itertext()).strip() for n in nodes if local(n.tag) in {'text','title','desc'})
    if re.search(r'\b(?:service unavailable|bad gateway|gateway timeout|rate limit(?:ed| exceeded)?|error fetching|something went wrong|temporarily unavailable|access denied)\b',text,re.I):raise InvalidData('provider error SVG')
    if name and name.startswith('snake'):
        if '@keyframes' not in s or 'animation' not in s or sum(local(n.tag)=='rect' for n in nodes)<100:raise InvalidData('snake content contract missing')
        return root
    # Positive, per-component semantic contracts reject valid XML error cards,
    # blank/background-only SVGs and unrelated images without relying on blacklist.
    contracts={
      'streak.svg':['total contributions','current streak','longest streak'],
      'github-stats.svg':['total stars','total commits','total prs','total issues','contributed to'],
      'github-stats-original-rank.svg':['total stars','total commits','total prs','total issues','contributed to'],
      'languages-compact.svg':['most used languages'], 'languages-bars.svg':['most used languages'],
      'languages-donut.svg':['most used languages'],'languages-repo.svg':['top languages by repo'],
      'languages-commit.svg':['top languages by commit'],'overview.svg':['contributions','public repos'],
      'productive-time.svg':['commits'], 'asset-01.svg':['followers'],'asset-02.svg':['stars'],
      'asset-03.svg':['profile views'],'tokentracker':['tokens']}
    plain=re.sub(r'\s+',' ',text).lower()
    ring=name in {'languages-repo.svg','languages-commit.svg'}
    if not text.strip() or (not ring and not re.search(r'\d',text)):raise InvalidData('SVG lacks visible data content')
    if ring and not any(local(n.tag)=='path' and re.search(r'[aA]',n.get('d','')) for n in nodes):raise InvalidData('language ring chart missing')
    if not any(local(n.tag)=='text' and ''.join(n.itertext()).strip() for n in nodes):raise InvalidData('SVG lacks rendered labels/data')
    for label in contracts.get(name,[]):
        if label not in plain:raise InvalidData('SVG content contract missing: '+label)
    if name and name.startswith('languages') and name not in {'languages-repo.svg','languages-commit.svg'} and '%' not in text:raise InvalidData('language percentages missing')
    return root

def palette_svg(data,name=None):
    validate_svg(data,name)
    s=data.decode() if isinstance(data,bytes) else data
    for old,new in {'#141321':'#101827','#fe428e':'#a78bfa','#f8d847':'#22d3ee','#a9fef7':'#dbe5f6','#006aff':'#a78bfa','#417e87':'#dbe5f6','#00000000':'#101827'}.items():s=re.sub(old,new,s,flags=re.I)
    # Freeze entry animation only; native snake keyframes are never processed here.
    s=re.sub(r'animation(?:-delay)?:[^;"\n<>]+;?','',s).replace('opacity: 0;','opacity: 1;')
    if 'class="lang-progress"' in s:s=s.replace('class="lang-progress"','class="lang-progress" width="100%"').replace('fill="#ddd"','fill="#25364e"')
    ET.fromstring(s)
    return s

def calendar_from_html(contents):
    days={}
    for s in contents:
        ids={i:d for d,i in re.findall(r'<td[^>]*data-date="([0-9-]+)"[^>]*id="([^"]+)"',s)}
        for i,t in re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>(.*?)</tool-tip>',s,re.S):
            if i in ids:
                n=re.match(r'([\d,]+) contribution',html.unescape(t));days[ids[i]]=int(n[1].replace(',','')) if n else 0
    return days

def render_activity(days,as_of,captured_at):
    dates=[(as_of-dt.timedelta(days=i)).isoformat() for i in range(365,0,-1)]
    if any(d not in days for d in dates):raise InvalidData('missing complete calendar dates')
    vals=[days[d] for d in dates];total=sum(vals);active=sum(v>0 for v in vals);peak=max(vals) or 1
    b=txt(32,56,'Activity Graph',25,'#a78bfa',650)+txt(32,84,f'{compact(total)} contributions · {active} active days · 365 complete UTC days',14,'#94a3b8')
    for y in [118,174,230]:b+=f'<path d="M40 {y}H920" stroke="#25364e"/>'
    coords=[(40+i*880/364,230-v*112/peak) for i,v in enumerate(vals)]
    b+='<path d="M'+' L'.join(f'{x:.1f} {y:.1f}' for x,y in coords)+'" fill="none" stroke="#22d3ee" stroke-width="1.7"/>'
    b+=txt(40,260,dates[0],12,'#94a3b8')+txt(809,260,dates[-1],12,'#94a3b8')+txt(40,287,'GitHub calendar events may include anonymized private activity; not commit counts.',12,'#94a3b8')
    return card(960,311,b,'365 complete UTC days of GitHub contribution activity'),{'window':[dates[0],dates[-1]],'total':total,'active_days':active,'captured_at':captured_at,'days':[{'date':d,'contributions':v} for d,v in zip(dates,vals)]}

def refresh(root,config,as_of,profile=None,embed=None,projects=None,network=False,github_only=False):
    sources=root/'sources';assets=root/'assets';captured=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds');errors=[];updated=[]
    source_status=read_json(sources/'source-status.json') if (sources/'source-status.json').exists() else {}
    source_keys={'TokenTracker daily profile':'daily','TokenTracker file import':'daily','TokenTracker cumulative embed':'cumulative','Cumulative embed import':'cumulative','Recompute rolling window':'daily'}
    readme=(root/'README.md').read_text()
    def operation(name,fn):
        key=source_keys.get(name)
        try:
            fn();updated.append(name)
            if key and name!='Recompute rolling window':source_status[key]={'status':'valid','attempted_at':captured}
        except Exception as exc:
            errors.append(f'{name}: {type(exc).__name__}: {exc}');print(errors[-1],file=sys.stderr)
            if key:source_status[key]={'status':'retained','attempted_at':captured,'error':errors[-1]}
    if network and not github_only:
        uid=urllib.parse.quote(config['tokentracker_user_id']);url=PROFILE_BASE+'tokentracker-leaderboard-profile?user_id='+uid+'&period=total&tz=Etc%2FUTC'
        def get_profile():
            raw=fetch(url);obj=json.loads(raw);parsed=public_ai_snapshot(normalize_profile(obj,as_of,captured));json_write(sources/'tokentracker-last-good.json',parsed)
        operation('TokenTracker daily profile',get_profile)
        def get_embed():
            raw=fetch(PROFILE_BASE+'tokentracker-embed-svg?user_id='+uid+'&theme=dark');parsed=parse_embed(raw,captured);json_write(sources/'tokentracker-cumulative.json',parsed);write_atomic(assets/'tokentracker-official.svg',raw)
        operation('TokenTracker cumulative embed',get_embed)
    if profile:
        def import_profile():
            obj=read_json(profile);parsed=public_ai_snapshot(normalize_profile(obj,as_of,captured));json_write(sources/'tokentracker-last-good.json',parsed)
        operation('TokenTracker file import',import_profile)
    if embed:
        def import_embed():
            raw=embed.read_bytes();file_time=dt.datetime.fromtimestamp(embed.stat().st_mtime,dt.timezone.utc).isoformat(timespec="seconds");parsed=parse_embed(raw,file_time);json_write(sources/'tokentracker-cumulative.json',parsed);write_atomic(assets/'tokentracker-official.svg',raw)
        operation('Cumulative embed import',import_embed)
    if projects:
        operation('Upstream file import',lambda:json_write(sources/'upstream-last-good.json',normalize_projects(read_json(projects),config,captured)))
    if network:
        def get_projects():
            obj=fetch_projects(config);parsed=normalize_projects(obj,config,captured);json_write(sources/'upstream-last-good.json',parsed)
        operation('GitHub upstream projects',get_projects)
        def get_calendar():
            texts=[]
            for year in {as_of.year,(as_of-dt.timedelta(days=365)).year}:
                texts.append(fetch(f'https://github.com/users/{config["github_username"]}/contributions?from={year}-01-01&to={year}-12-31').decode())
            svg,data=render_activity(calendar_from_html(texts),as_of,captured);write_atomic(assets/'activity-graph.svg',svg);json_write(sources/'contributions-365.json',data)
        operation('GitHub calendar',get_calendar)
        # Original profile modules refresh independently. Unavailable endpoints retain their SVG.
        image_status=read_json(sources/'image-status.json') if (sources/'image-status.json').exists() else {}
        manifest=read_json(sources/'resource-manifest.json');mapping={61:'streak.svg',62:'github-stats-original-rank.svg',74:'github-stats.svg',63:'languages-compact.svg',76:'languages-bars.svg',64:'languages-donut.svg',65:'languages-repo.svg',66:'languages-commit.svg',68:'overview.svg',70:'productive-time.svg',71:'snake-dark.svg',72:'snake-light.svg',1:'asset-01.svg',2:'asset-02.svg',3:'asset-03.svg'}
        for i,name in mapping.items():
            row=next((r for r in manifest if r.get('path','').endswith(f'asset-{i:02d}.svg')),None)
            if row:
                def image(row=row,name=name):
                    raw=fetch(row['url']);validate_svg(raw,name)
                    processed=themes.normalize_dark(raw.decode(),True).encode() if name.startswith('snake') else themes.normalize_dark(palette_svg(raw,name)).encode()
                    write_atomic(assets/name,processed);image_status[name]={"source_url":row["url"],"captured_at":captured,"status":"valid"}
                before_errors=len(errors)
                operation(name,image)
                if len(errors)>before_errors:
                    image_status[name]={**image_status.get(name,{}),"source_url":row['url'],"status":"retained" if (assets/name).exists() else "unavailable","attempted_at":captured,"error":errors[-1]}
        json_write(sources/"image-status.json",image_status)
    # Offline rolling recomputation only succeeds when saved raw data covers the requested UTC window.
    raw=sources/'tokentracker-profile.json'
    if not profile and not (network and not github_only) and raw.exists():
        operation('Recompute rolling window',lambda:json_write(sources/'tokentracker-last-good.json',public_ai_snapshot(normalize_profile(read_json(raw),as_of,read_json(sources/'tokentracker-last-good.json')['captured_at']))))
    ai_file=sources/'tokentracker-last-good.json';cumulative_file=sources/'tokentracker-cumulative.json'
    for key,path in [('daily',ai_file),('cumulative',cumulative_file)]:
        if path.exists():source_status.setdefault(key,{'status':'valid'})['captured_at']=read_json(path)['captured_at']
    json_write(sources/'source-status.json',source_status)
    if ai_file.exists():
        ai=public_ai_snapshot(read_json(ai_file));cum=read_json(cumulative_file) if cumulative_file.exists() else None
        daily_failed=source_status.get('daily',{}).get('status')=='retained'
        cumulative_failed=source_status.get('cumulative',{}).get('status')=='retained'
        ai_svg=render_ai(ai,cum,config,as_of,daily_failed,cumulative_failed);write_atomic(assets/'ai-usage-30d.svg',ai_svg);ai_path=versioned_asset(assets,'ai-usage',ai_svg)
        heat=render_heatmap(ai)
        if heat:write_atomic(assets/'ai-daily.svg',heat)
        body=f'![AI usage: cumulative, rolling 30 days, models and daily heatmap]({ai_path})\n\n'
        if ai['window'][1]!=as_of.isoformat():body+='*Updated '+ai['captured_at']+' · latest available snapshot.*\n\n'
        if not ai.get('days'):body+='Daily detail pending import.\n\n'
        readme=update_region(readme,'AI',body)
    upstream=sources/'upstream-last-good.json'
    if upstream.exists():
        data=read_json(upstream);ps=data['projects'][:config['max_projects_displayed']]
        labels=' · '.join(f"[{p['name']}]({p['url']})" for p in ps)
        body='**Contributed to:** '+labels
        readme=update_region(readme,'PROJECTS',body)
    else:
        readme=update_region(readme,'PROJECTS','**Contributed to:** Awaiting a complete public merged-upstream source. The next successful refresh generates project names automatically.')
    activity=sources/'contributions-365.json'
    if activity.exists():
        data=read_json(activity)
        readme=update_region(readme,'ACTIVITY',"![Daily GitHub contribution activity](assets/activity-graph.svg)")
    # Milestone fallback derives from source counters, not a perpetual handwritten score.
    if activity.exists():
        data=read_json(activity);b=txt(32,53,'Open-source milestones',24,'#a78bfa',650)
        for x,value,label in [(32,compact(data['total']),'Calendar contributions'),(350,str(data['active_days']),'Active days / 365'),(669,str(len(read_json(upstream)['projects'])) if upstream.exists() else '—','External upstream projects')]:
            b+=txt(x,108,value,34,'#f1f5ff',700)+txt(x,139,label,13,'#94a3b8')
        b+=txt(32,177,'Saved public sources · calendar window '+ ' → '.join(data['window']),11,'#94a3b8')
        write_atomic(assets/'milestones.svg',card(960,202,b,'Source-generated open-source milestones'))
    # Keep local/GitHub theme handling in the refresh path, including cached sources.
    theme_refs=themes.make_variants(assets,write_atomic)
    readme=themes.adapt_readme(readme,theme_refs)
    write_atomic(root/'README.md',readme)
    write_atomic(root/'preview/README-Typora.md',themes.fixed_preview(readme))
    report={'attempted_at':captured,'requested_utc_date':as_of.isoformat(),'network_enabled':network,'updated':updated,'errors':errors,'ci_executed':False}
    json_write(root/'qa/refresh-report.json',report)
    return report

def import_bundle(path, root, as_of, expected_sha256=None, source_captured_at=None):
    raw=path.read_bytes()
    if expected_sha256 and hashlib.sha256(raw).hexdigest()!=expected_sha256.lower():raise InvalidData("bundle SHA-256 mismatch")
    obj=read_json(path)
    if not isinstance(obj,dict) or not isinstance(obj.get("profile"),dict):raise InvalidData("bundle profile object missing")
    manifest=obj.get("manifest",{})
    # Preserve source collection timestamp. Never use rank.generated_at as last sync.
    captured=source_captured_at or manifest.get('sources',{}).get('profile',{}).get('fetchedAt') or next((manifest[k] for k in ["capturedAtUTC","captured_at_utc","captured_at","capturedAt","fetchedAtUTC","fetched_at_utc","retrieved_at_utc"] if isinstance(manifest.get(k),str)),None)
    if not captured:raise InvalidData("source capture timestamp missing; provide --source-captured-at")
    parsed=normalize_profile(obj["profile"],as_of,captured)
    embed_obj=obj.get("officialEmbedSnapshot",{})
    embed=next((embed_obj[k] for k in ["svg","svgText","rawSvg","svg_content"] if isinstance(embed_obj.get(k),str)),None)
    if not embed:raise InvalidData("official embed SVG missing")
    embed_capture=manifest.get('sources',{}).get('officialEmbedSnapshot',{}).get('fetchedAt') or next((embed_obj[k] for k in ["capturedAtUTC","captured_at_utc","captured_at","capturedAt","fetched_at_utc"] if isinstance(embed_obj.get(k),str)),captured)
    cumulative=parse_embed(embed.encode(),embed_capture)
    # Validate both source contracts before any last-good mutation.
    json_write(root/"sources/tokentracker-last-good.json",public_ai_snapshot(parsed))
    json_write(root/"sources/tokentracker-cumulative.json",cumulative)
    write_atomic(root/"assets/tokentracker-official.svg",embed)
    json_write(root/'sources/source-status.json',{'daily':{'status':'valid','captured_at':captured},'cumulative':{'status':'valid','captured_at':embed_capture}})
    return {"sha256":hashlib.sha256(raw).hexdigest(),"captured_at":captured,"window":parsed["window"],"model_count":len(parsed["models"]),"total_tokens":parsed["total_tokens"]}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--profile-json',type=Path);p.add_argument('--embed-svg',type=Path);p.add_argument('--upstream-json',type=Path);p.add_argument('--bundle-json',type=Path);p.add_argument('--expected-sha256');p.add_argument('--source-captured-at');p.add_argument('--as-of',type=dt.date.fromisoformat,default=dt.datetime.now(dt.timezone.utc).date());p.add_argument('--fetch',action='store_true');p.add_argument('--github-only',action='store_true');args=p.parse_args()
    if args.github_only and not args.fetch:p.error('--github-only requires --fetch')
    config=read_json(args.root/'profile-config.json')
    if args.bundle_json:
        result=import_bundle(args.bundle_json,args.root,args.as_of,args.expected_sha256,args.source_captured_at);json_write(args.root/'sources/bundle-import.json',result)
    report=refresh(args.root,config,args.as_of,args.profile_json,args.embed_svg,args.upstream_json,args.fetch,args.github_only)
    print(json.dumps({'updated':report['updated'],'errors':report['errors'],'network_enabled':args.fetch},ensure_ascii=False))
    return 1 if report['errors'] else 0
if __name__=='__main__':sys.exit(main())
