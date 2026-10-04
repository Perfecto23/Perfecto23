import datetime as dt,json,os,shutil,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import refresh as r
P=Path(__file__).resolve().parents[1]
CONFIG=r.read_json(P/'profile-config.json')
ERROR=b'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="180"><rect width="400" height="180"/><text x="20" y="50">Service Unavailable</text></svg>'
EMPTY=b'<svg xmlns="http://www.w3.org/2000/svg"/>'
def copy_profile(root):
 for directory in ['assets','sources']:shutil.copytree(P/directory,root/directory)
 shutil.copyfile(P/'README.md',root/'README.md')
 # Fixed synthetic history makes cross-day tests independent of live refreshes.
 end=dt.date(2026,10,4)
 fixture={'heatmap':[{'date':(end-dt.timedelta(days=i)).isoformat(),'total_tokens':i+1,'models':{'test-only-model':i+1}} for i in range(29,-1,-1)]}
 r.json_write(root/'sources/tokentracker-last-good.json',r.public_ai_snapshot(r.normalize_profile(fixture,end,'2026-10-01T00:00:00Z')))
 for name in ['tokentracker-last-good.json','tokentracker-cumulative.json']:
  obj=r.read_json(root/'sources'/name);obj['captured_at']='2026-10-01T00:00:00Z';r.json_write(root/'sources'/name,obj)
 (root/'sources/source-status.json').unlink(missing_ok=True)

class FailureTests(unittest.TestCase):
 def test_normal_cards_not_rejected(self):
  names=['streak.svg','github-stats.svg','github-stats-original-rank.svg','languages-compact.svg','languages-bars.svg','languages-donut.svg','languages-repo.svg','languages-commit.svg','overview.svg','productive-time.svg','asset-01.svg','asset-02.svg','asset-03.svg','snake-dark.svg','snake-light.svg']
  for name in names:
   with self.subTest(name=name):r.validate_svg((P/'assets'/name).read_bytes(),name)
 def test_error_empty_and_unrelated_xml_rejected(self):
  unrelated=b'<svg xmlns="http://www.w3.org/2000/svg"><text>Unrelated illustration 500</text></svg>'
  for raw in [ERROR,EMPTY,unrelated]:
   with self.subTest(raw=raw),self.assertRaises(r.InvalidData):r.palette_svg(raw,'streak.svg')
  with self.assertRaises(r.InvalidData):r.palette_svg(ERROR)
  with self.assertRaises(r.InvalidData):r.palette_svg(EMPTY)
 def test_failed_network_card_preserves_bytes_and_capture(self):
  for response in [ERROR,EMPTY]:
   with self.subTest(response=response),tempfile.TemporaryDirectory() as t:
    root=Path(t);copy_profile(root)
    r.json_write(root/'sources/resource-manifest.json',[{'path':'assets/asset-61.svg','url':'https://example.invalid/streak'}])
    previous=(root/'assets/streak.svg').read_bytes()
    prior=r.read_json(root/'sources/image-status.json')['streak.svg']['captured_at']
    with patch.object(r,'fetch',return_value=response),patch.object(r,'fetch_projects',side_effect=OSError('fixture unavailable')):
     report=r.refresh(root,CONFIG,dt.date(2026,10,4),network=True,github_only=True)
    self.assertTrue(any(e.startswith('streak.svg:') for e in report['errors']))
    self.assertEqual((root/'assets/streak.svg').read_bytes(),previous)
    status=r.read_json(root/'sources/image-status.json')['streak.svg']
    self.assertEqual(status['status'],'retained');self.assertEqual(status['captured_at'],prior)
 def test_cumulative_failure_daily_success_independent(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);copy_profile(root)
   asof=dt.date(2026,10,5)
   fixture={'heatmap':[{'date':(asof-dt.timedelta(days=i)).isoformat(),'total_tokens':i+1,'models':{'fixture':i+1}} for i in range(30)]}
   profile=root/'new-daily.json';r.json_write(profile,fixture);embed=root/'bad-embed.svg';embed.write_bytes(ERROR)
   cumulative=(root/'sources/tokentracker-cumulative.json').read_bytes()
   r.refresh(root,CONFIG,asof,profile=profile,embed=embed)
   self.assertEqual((root/'sources/tokentracker-cumulative.json').read_bytes(),cumulative)
   status=r.read_json(root/'sources/source-status.json');self.assertEqual(status['cumulative']['status'],'retained');self.assertEqual(status['daily']['status'],'valid')
   svg=(root/'assets/ai-usage-30d.svg').read_text();self.assertIn('Total: 2026-10-01 00:00 UTC · retained',svg)
   self.assertIn('30d: '+r.source_stamp(r.read_json(root/'sources/tokentracker-last-good.json'),asof),svg)
   r.refresh(root,CONFIG,asof);self.assertEqual(r.read_json(root/'sources/source-status.json')['cumulative']['status'],'retained')
 def test_daily_failure_cumulative_success_cross_day(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);copy_profile(root);asof=dt.date(2026,10,5)
   profile=root/'bad-daily.json';r.json_write(profile,{'heatmap':[]})
   embed=root/'new-embed.svg';embed.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><text>TOKENS</text><text>60B</text></svg>')
   timestamp=dt.datetime(2026,10,5,12,tzinfo=dt.timezone.utc).timestamp();os.utime(embed,(timestamp,timestamp))
   daily=(root/'sources/tokentracker-last-good.json').read_bytes()
   r.refresh(root,CONFIG,asof,profile=profile,embed=embed)
   self.assertEqual((root/'sources/tokentracker-last-good.json').read_bytes(),daily)
   status=r.read_json(root/'sources/source-status.json');self.assertEqual(status['daily']['status'],'retained');self.assertEqual(status['cumulative']['status'],'valid')
   svg=(root/'assets/ai-usage-30d.svg').read_text()
   self.assertIn('Total: 2026-10-05 12:00 UTC',svg);self.assertIn('30d: 2026-10-01 00:00 UTC · retained',svg)
   self.assertIn('2026-09-05 → 2026-10-04 · inclusive UTC window',svg);self.assertNotIn('today included',svg)
if __name__=='__main__':unittest.main()
