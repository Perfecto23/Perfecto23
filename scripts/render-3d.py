"""Render the public calendar with the pinned upstream night renderer; no PAT needed."""
from pathlib import Path
from html.parser import HTMLParser
import json,re,os,subprocess
import sys,tempfile,urllib.request
from xml.etree import ElementTree as ET
root=Path(__file__).resolve().parents[1]
tool=Path(sys.argv[1]).resolve()
tmp=tempfile.TemporaryDirectory()
out=Path(tmp.name)
request=urllib.request.Request('https://github.com/users/Perfecto23/contributions', headers={'User-Agent':'Perfecto23-profile-art'})
with urllib.request.urlopen(request,timeout=40) as response:
 html=response.read().decode()
class Parser(HTMLParser):
 def __init__(self):super().__init__();self.days={};self.tips={};self.tip=None
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='td' and 'data-date' in a:self.days[a['id']]={'date':a['data-date'],'contributionLevel':int(a['data-level'])}
  if tag=='tool-tip':self.tip=a.get('for')
 def handle_data(self,s):
  if self.tip:self.tips[self.tip]=self.tips.get(self.tip,'')+s
 def handle_endtag(self,tag):
  if tag=='tool-tip':self.tip=None
p=Parser();p.feed(html)
days=[]
for id,d in p.days.items():
 t=p.tips[id].strip();m=re.match(r'(No|[\d,]+) contribution',t);assert m,t
 d['contributionCount']=0 if m[1]=='No' else int(m[1].replace(',',''));days.append(d)
days.sort(key=lambda d:d['date'])
assert 365 <= len(days) <= 372, 'Unexpected calendar length'
assert len({d['date'] for d in days}) == len(days), 'Duplicate dates'
assert all(0 <= d['contributionLevel'] <= 4 and d['contributionCount'] >= 0 for d in days)
info={'isHalloween':False,'contributionCalendar':days,'totalContributions':sum(d['contributionCount'] for d in days),'contributesLanguage':[]}
for k in ['totalCommitContributions','totalIssueContributions','totalPullRequestContributions','totalPullRequestReviewContributions','totalRepositoryContributions','totalForkCount','totalStargazerCount']:info[k]=0
(out/'public-calendar.json').write_text(json.dumps({'source':'https://github.com/users/Perfecto23/contributions','days':days,'total':info['totalContributions']},indent=2))
s=(tool/'dist/index.js').read_text()
assert 'const response = await client.fetchData(token, userName, maxRepos, year);' in s, 'Upstream renderer changed'
s=s.replace('const response = await client.fetchData(token, userName, maxRepos, year);\n        const userInfo = aggregate.aggregateUserInfo(response);','const userInfo = '+json.dumps(info)+'; userInfo.contributionCalendar.forEach(d=>d.date=new Date(d.date));')
s=s.replace('radar.createRadarContrib(svg, userInfo, radarX, 70, radarWidth, radarHeight, settings, isForcedAnimation);','')
s=s.replace('pie.createPieLanguage(svg, userInfo, 40, height - pieHeight - 70, pieWidth, pieHeight, settings, isForcedAnimation);','')
a=s.index('        const positionXStar = (width * 5) / 10;');b=s.index('        // ISO 8601 format',a)
# Remove star/fork statistics, preserving only the actual public contribution total.
s=s[:a]+s[b:]
(tool/'dist/profile-night.js').write_text(s)
settings=json.loads((tool/'src/settings/NightViewSettings.json').read_text());settings['fileName']='Perfecto23-night-view.svg';settings['growingAnimation']=True
(out/'night-settings.json').write_text(json.dumps(settings))
env=os.environ.copy();env['GITHUB_TOKEN']='offline-public-calendar';env['SETTING_JSON']=str(out/'night-settings.json')
r=subprocess.run(['node',str(tool/'dist/profile-night.js'),'Perfecto23'],cwd=out,env=env,capture_output=True,text=True)
print('renderer exit',r.returncode)
if r.returncode:print(r.stderr[:1500]);raise SystemExit(r.returncode)
print('days',len(days),'range',days[0]['date'],days[-1]['date'],'public contributions',info['totalContributions'])

svg=(out/'profile-3d-contrib/Perfecto23-night-view.svg').read_text()
ET.fromstring(svg)
(root/'assets/contributions-3d.svg').write_text(svg)
