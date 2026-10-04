#!/usr/bin/env python3
from pathlib import Path
import re,sys,xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1];readme=(root/'README.md').read_text()
paths=[a or b for a,b in re.findall(r'!\[[^\]]*\]\((assets/[^)]+)\)|src="(assets/[^"]+)"',readme)]
paths+=re.findall(r'srcset="(assets/[^"]+)"',readme)
for name in paths:
 path=(root/name).resolve()
 if not path.is_relative_to(root.resolve()) or not path.exists():raise ValueError('missing/unsafe local resource: '+name)
for path in (root/'assets').glob('*.svg'):ET.parse(path)
assert readme.count('<details>')==readme.count('</details>')
assert readme.count('<picture>')==readme.count('</picture>')
assert not re.search(r'^\s*HTML\s*$',readme,re.M)
assert not re.search(r'https://github.com/[^\s)]+/pull/\d+',readme)
for key in ['AI','PROJECTS','ACTIVITY']:
 assert readme.count('<!-- BEGIN AUTO:'+key+' -->')==readme.count('<!-- END AUTO:'+key+' -->')==1
print(f'PASS: {len(paths)} local images; all SVGs valid; generated markers and details balanced')
