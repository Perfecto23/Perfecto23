import unittest,importlib.util,datetime as dt,json,tempfile,shutil,re
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('u',P/'scripts/update-profile.py');u=importlib.util.module_from_spec(s);s.loader.exec_module(u)
TODAY=dt.date(2026,10,6)
def fixture():
 dates=[TODAY-dt.timedelta(days=i) for i in range(364,-1,-1)]
 return {'period':{'kind':'total','from':dates[0].isoformat(),'to':dates[-1].isoformat()},'totals':{'total_tokens':7665},'heatmap':[{'date':d.isoformat(),'total_tokens':21,'models':{f'model-{j}':j for j in range(1,7)}} for d in dates]}
class T(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);shutil.copytree(P/'assets',self.root/'assets')
  for f in ['README.md','README.zh-CN.md']:shutil.copy(P/f,self.root/f)
  self.p=patch.object(u,'ROOT',self.root);self.p.start()
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def test_rounding(self):
  for n,s in [(999999,'1M'),(999999999,'1B'),(999999999999,'1T'),(0,'0')]:self.assertEqual(u.compact(n),s)
 def test_windows_and_all_models(self):
  f=fixture();a=u.normalize_profile(f,TODAY,'2026-10-06T12:00:00Z');t=u.profile_total(f,'2026-10-06T12:00:00Z');self.assertEqual(a['total_tokens'],630);self.assertEqual(a['daily_average_tokens'],21);self.assertEqual(t['total_tokens'],7665);self.assertEqual(sum(m['tokens'] for m in a['models']),630)
 def test_bad_model_sum(self):
  f=fixture();f['heatmap'][-1]['models']['wrong']=1
  with self.assertRaises(u.InvalidData):u.normalize_profile(f,TODAY,'stamp')
 def test_bad_year_scope(self):
  f=fixture();f['period']['from']='2026-01-01'
  with self.assertRaises(u.InvalidData):u.profile_total(f,'stamp')
 def test_failure_retention_recovery(self):
  originals={p.name:p.read_text() for p in (self.root/'assets').glob('ai-*.svg')}
  with patch.object(u,'fetch',side_effect=OSError('unavailable')):
   with self.assertRaises(OSError):u.update_ai(TODAY,'2026-10-06T12:00:00Z')
  u.mark_ai_retained(TODAY,'2026-10-06T12:00:00Z')
  # Optimizers may omit the final newline; publish() restores it.
  def data(s):return re.sub(r'<text[^>]*>(?:Refresh failed.*?|Perfecto · TokenTracker|Total: .*?|30d: .*?)</text>','',s).rstrip('\r\n')
  for n,old in originals.items():
   new=(self.root/'assets'/n).read_text();self.assertEqual(data(old),data(new));self.assertIn('retained',new)
  with patch.object(u,'fetch',return_value=json.dumps(fixture()).encode()):u.update_ai(TODAY,'2026-10-06T12:00:00Z')
  for n in originals:self.assertNotIn('retained',(self.root/'assets'/n).read_text())
 def test_productive_error_keeps_data(self):
  p=self.root/'assets/productive-time.svg';old=p.read_bytes()
  with patch.object(u,'fetch',return_value=b'<svg><text>ERROR rate limited</text></svg>'):
   with self.assertRaises(u.InvalidData):u.update_productive(TODAY,'stamp')
  self.assertEqual(old,p.read_bytes())
 def test_project_filter(self):
  repos=[{'full_name':'neworg/newproject','fork':False,'private':False,'owner_type':'Organization','merged_authored_pr_count':2},{'full_name':'MoeGo/internal','fork':False,'private':False,'owner_type':'Organization','merged_authored_pr_count':3}]
  self.assertEqual([r['full_name'] for r in u.filter_projects(repos,u.CONFIG)],['neworg/newproject'])
 def test_projects_update_both_languages(self):
  repos=[{'full_name':'neworg/newproject','fork':False,'private':False,'owner_type':'Organization','merged_authored_pr_count':2}]
  with patch.object(u,'fetch_projects',return_value={'repositories':repos}):u.update_projects(TODAY,'stamp')
  for filename,label in [('README.md','Contributed to:'),('README.zh-CN.md','参与贡献的项目：')]:
   text=(self.root/filename).read_text()
   self.assertIn('https://github.com/neworg/newproject',text)
   self.assertIn(label,text)
 def test_invalid_chinese_markers_preserve_both(self):
  p=self.root/'README.zh-CN.md';p.write_text(p.read_text().replace('<!-- END AUTO:PROJECTS -->',''))
  before={f:(self.root/f).read_bytes() for f in ['README.md','README.zh-CN.md']}
  repos=[{'full_name':'neworg/newproject','fork':False,'private':False,'owner_type':'Organization','merged_authored_pr_count':2}]
  with patch.object(u,'fetch_projects',return_value={'repositories':repos}):
   with self.assertRaises(u.InvalidData):u.update_projects(TODAY,'stamp')
  for f,value in before.items():self.assertEqual((self.root/f).read_bytes(),value)
 def test_structure(self):u.check()
if __name__=='__main__':unittest.main(verbosity=2)
