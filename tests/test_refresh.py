import datetime as dt,hashlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('refresh',P/'scripts/refresh.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
CONFIG=json.loads((P/'profile-config.json').read_text())
# Synthetic test-only records. Never copied to production sources/assets.
def fixture(asof=dt.date(2026,10,4),length=32):
 return {'heatmap':[{'date':(asof-dt.timedelta(days=length-1-i)).isoformat(),'total_tokens':i+1,'models':{'test-model':i+1}} for i in range(length)]}
class RefreshTests(unittest.TestCase):
 def test_compact_units_and_rounding_boundaries(self):
  expected={0:'0',999:'999',999.995:'1K',1000:'1K',999999:'1M',1000000:'1M',999999999:'1B',1000000000:'1B',20772897628:'20.77B',692429920.933:'692.43M'}
  for n,v in expected.items():self.assertEqual(r.compact(n),v)
  for n in [-1,float('nan'),float('inf')]:
   with self.assertRaises(r.InvalidData):r.compact(n)
 def test_utc_window_rolls_across_midnight(self):
  f=fixture();a=r.normalize_profile(f,dt.date(2026,10,3),'test');b=r.normalize_profile(f,dt.date(2026,10,4),'test')
  self.assertEqual(a['window'],['2026-09-04','2026-10-03']);self.assertEqual(b['window'],['2026-09-05','2026-10-04'])
  self.assertEqual(b['total_tokens']-a['total_tokens'],30);self.assertEqual(b['daily_average_tokens'],b['total_tokens']/30)
 def test_future_days_excluded_models_sum(self):
  f=fixture();f['heatmap'].append({'date':'2026-10-05','total_tokens':1000000,'models':{'future':1000000}})
  a=r.normalize_profile(f,dt.date(2026,10,4),'test');self.assertNotIn('future',[m['name'] for m in a['models']]);self.assertEqual(sum(m['tokens'] for m in a['models']),a['total_tokens'])
 def test_duplicate_missing_and_mismatched_days_rejected(self):
  for mutate in [lambda f:f['heatmap'].append(f['heatmap'][-1]),lambda f:f['heatmap'].pop(),lambda f:f['heatmap'][-1]['models'].update({'bad':1})]:
   f=fixture();mutate(f)
   with self.assertRaises(r.InvalidData):r.normalize_profile(f,dt.date(2026,10,4),'test')
 def test_upstreams_deduplicated_and_self_company_forks_excluded(self):
  repos=[{'full_name':name,'merged_authored_pr_count':2,'fork':fork,'private':False,'owner_type':'Organization'} for name,fork in [('pnpm/pnpm',False),('pnpm/pnpm',False),('Perfecto23/demo',False),('MoeGo/tools',False),('moego-agent/tools',False),('other/fork',True)]]
  out=r.filter_projects(repos,CONFIG);self.assertEqual([p['full_name'] for p in out],['pnpm/pnpm'])
 def test_invalid_and_empty_refresh_preserves_last_good(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'sources').mkdir();(root/'assets').mkdir();(root/'qa').mkdir()
   (root/'README.md').write_text('\n'.join(f'<!-- BEGIN AUTO:{k} -->\nold\n<!-- END AUTO:{k} -->' for k in ['AI','PROJECTS','ACTIVITY']))
   good=r.normalize_profile(fixture(),dt.date(2026,10,4),'original-time');r.json_write(root/'sources/tokentracker-last-good.json',good)
   r.refresh(root,CONFIG,dt.date(2026,10,4));before={p:p.read_bytes() for p in [root/'sources/tokentracker-last-good.json',root/'assets/ai-usage-30d.svg']}
   bad=root/'bad.json';bad.write_text('{"heatmap":[]}');report=r.refresh(root,CONFIG,dt.date(2026,10,5),profile=bad)
   self.assertTrue(report['errors'])
   self.assertEqual((root/'sources/tokentracker-last-good.json').read_bytes(),before[root/'sources/tokentracker-last-good.json'])
   self.assertIn('original-time · retained',(root/'assets/ai-usage-30d.svg').read_text())
   self.assertNotIn('today included',(root/'assets/ai-usage-30d.svg').read_text())
   self.assertIn('Updated original-time · latest available snapshot',(root/'README.md').read_text())
 def test_provider_zero_days_without_models(self):
  f=fixture();f['heatmap'][-1]={'date':'2026-10-04','total_tokens':0}
  out=r.normalize_profile(f,dt.date(2026,10,4),'test')
  self.assertEqual(out['days'][-1]['models'],{});self.assertEqual(out['days'][-1]['total_tokens'],0)
  f['heatmap'][-1]['total_tokens']=1
  with self.assertRaises(r.InvalidData):r.normalize_profile(f,dt.date(2026,10,4),'test')
 def test_embed_cumulative_scope_not_profile_365(self):
  raw=b'<svg xmlns="http://www.w3.org/2000/svg"><text>TOKENS</text><text>59.53B</text></svg>'
  x=r.parse_embed(raw,'captured');self.assertEqual(x['display'],'59.53B');self.assertTrue(x['rounded']);self.assertNotIn('totalTokensExact',x)
if __name__=='__main__':unittest.main()
