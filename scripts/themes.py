"""Fixed, internally colored SVG variants and GitHub picture markup.

No styles or scripts are required in the README. Brand badges and language
series colors remain intact; statistical chrome and snake use one palette.
"""
import hashlib,html,re,xml.etree.ElementTree as ET

NAMES={'hero.svg','asset-01.svg','asset-02.svg','asset-03.svg','ai-usage-30d.svg',
       'streak.svg','github-stats.svg','github-stats-original-rank.svg',
       'languages-compact.svg','languages-bars.svg','languages-donut.svg',
       'languages-repo.svg','languages-commit.svg','activity-graph.svg',
       'overview.svg','milestones.svg','productive-time.svg','snake-light.svg','snake-dark.svg'}
DARK={'#141321':'#101827','#ffffff00':'#101827','#00000000':'#101827',
      '#fe428e':'#a78bfa','#ae81ff':'#a78bfa','#006aff':'#a78bfa',
      '#f8d847':'#22d3ee','#0579c3':'#22d3ee','#06b6d4':'#22d3ee','#8b5cf6':'#a78bfa',
      '#a9fef7':'#dbe5f6','#417e87':'#dbe5f6','#e4e2e2':'#334155',
      '#ddd':'#273449','#555':'#101827','#0f172a':'#101827'}
LIGHT={'#101827':'#f8fafc','#334155':'#cbd5e1','#34445e':'#cbd5e1',
       '#fff':'#172033','#ffffff':'#172033',
       '#273449':'#e2e8f0','#25364e':'#e2e8f0','#1e293b':'#e2e8f0',
       '#f8fafc':'#172033','#f1f5ff':'#172033','#dbe5f6':'#334155','#e2e8f0':'#334155',
       '#cbd5e1':'#334155','#94a3b8':'#64748b','#64748b':'#64748b',
       '#a78bfa':'#7c3aed','#c4b5fd':'#6d28d9','#818cf8':'#6366f1',
       '#a5b4fc':'#6366f1','#a7c3df':'#64748b','#22d3ee':'#0891b2'}

def replace_colors(s,mapping):
    return re.sub(r'#[0-9a-f]{3,8}\b',lambda m:mapping.get(m[0].lower(),m[0]),s,flags=re.I)

def normalize_dark(s,snake=False):
    ET.fromstring(s)
    s=replace_colors(s,DARK)
    if snake:
        values={'cb':'#334155','cs':'#22d3ee','ce':'#273449','c0':'#273449',
                'c1':'#514b80','c2':'#7c6aa6','c3':'#a78bfa','c4':'#22d3ee'}
        for k,v in values.items():s=re.sub(r'(--'+k+r':)[^;}]+',lambda m:m[1]+v,s)
        if 'id="profile-bg"' not in s:
            s=re.sub(r'(<svg\b[^>]*>)',r'\1<rect id="profile-bg" x="-16" y="-32" width="880" height="192" fill="#101827" />',s,count=1)
    ET.fromstring(s)
    return '\n'.join(line.rstrip() for line in s.splitlines()).rstrip()+'\n'

def adaptive_svg(dark):
    colors=sorted({m.lower() for m in re.findall(r'#[0-9a-f]{3,8}\b',dark,re.I)} & LIGHT.keys())
    names={c:f'--profile-{i}' for i,c in enumerate(colors)}
    s=re.sub(r'#[0-9a-f]{3,8}\b',lambda m:'var('+names[m[0].lower()]+')' if m[0].lower() in names else m[0],dark,flags=re.I)
    defaults=''.join(f'{names[c]}:{c};' for c in colors)
    light=''.join(f'{names[c]}:{LIGHT[c]};' for c in colors)
    css='<style>:root{'+defaults+'}@media(prefers-color-scheme:light){:root{'+light+'}}</style>'
    s=s.replace('</svg>',css+'</svg>');ET.fromstring(s)
    return s

def make_variants(assets,write):
    refs={}
    for name in sorted(NAMES):
        p=assets/name
        if not p.exists():continue
        dark=normalize_dark(p.read_text(),name.startswith('snake'));write(p,dark)
        light=replace_colors(dark,LIGHT);ET.fromstring(light)
        versions=[]
        for mode,s in [('dark',dark),('light',light),('adaptive',adaptive_svg(dark))]:
            digest=hashlib.sha256(s.encode()).hexdigest()[:12]
            version=f'theme-{p.stem}-{mode}-{digest}.svg';write(assets/version,s);versions.append('assets/'+version)
        refs[name]=versions
    current={path.split('/')[-1] for paths in refs.values() for path in paths}
    for old in assets.glob('theme-*.svg'):
        match=re.fullmatch(r'theme-(.*)-(dark|light|adaptive)-[0-9a-f]{12}\.svg',old.name)
        if match and match[1]+'.svg' in NAMES and old.name not in current:old.unlink()
    return refs

def picture(name,alt,refs):
    dark,light,adaptive=refs[name];alt=html.escape(html.unescape(alt),quote=True)
    return f'<picture><source media="(prefers-color-scheme: dark)" srcset="{dark}" /><source media="(prefers-color-scheme: light)" srcset="{light}" /><img src="{adaptive}" alt="{alt}" /></picture>'

def adapt_readme(s,refs):
    # Update existing owned pictures instead of nesting them on subsequent runs.
    def canonical(path):
        n=path.split('/')[-1]
        if n.startswith('ai-usage-') and not n.startswith('theme-'):return 'ai-usage-30d.svg'
        m=re.fullmatch(r'theme-(.*)-(dark|light|adaptive)-[0-9a-f]{12}\.svg',n)
        return m[1]+'.svg' if m else n
    def old_picture(m):
        image=re.search(r'<img src="([^"]+)" alt="([^"]*)"\s*/?>',m[0])
        if image and canonical(image[1]) in refs:return picture(canonical(image[1]),image[2],refs)
        return m[0]
    s=re.sub(r'<picture>.*?</picture>',old_picture,s,flags=re.S)
    parts=re.split(r'(<picture>.*?</picture>)',s,flags=re.S)
    for i in range(0,len(parts),2):
        parts[i]=re.sub(r'<img src="(assets/[^"]+)" alt="([^"]*)"\s*/?>',lambda m:picture(canonical(m[1]),m[2],refs) if canonical(m[1]) in refs else m[0],parts[i])
        parts[i]=re.sub(r'!\[([^\]]*)\]\((assets/[^)]+)\)',lambda m:picture(canonical(m[2]),m[1],refs) if canonical(m[2]) in refs else m[0],parts[i])
    return ''.join(parts)

def fixed_preview(s):
    # Optional local editor copy: identical content/layout, deterministic dark
    # canvases independent of Typora's media-query state during external reload.
    def fallback(m):
        source=re.search(r'<source media="\(prefers-color-scheme: dark\)" srcset="([^"]+)"',m[0])
        alt=re.search(r'<img[^>]*alt="([^"]*)"',m[0])
        if not source or not alt:return m[0]
        return f'<img src="{source[1]}" alt="{alt[1]}" />'
    s=re.sub(r'<picture>.*?</picture>',fallback,s,flags=re.S)
    return s.replace('src="assets/','src="../assets/')
