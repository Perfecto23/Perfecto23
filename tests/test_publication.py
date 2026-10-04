import datetime as dt, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import refresh as r

class PublicationTests(unittest.TestCase):
 def fixture(self):
  end=dt.date(2026,10,4)
  return {'heatmap':[{'date':(end-dt.timedelta(days=i)).isoformat(),
      'total_tokens':66,'models':{f'test-{j}':j+1 for j in range(11)}} for i in range(29,-1,-1)]}
 def test_public_snapshot_drops_raw_models_but_keeps_totals(self):
  raw=r.normalize_profile(self.fixture(),dt.date(2026,10,4),'test')
  public=r.public_ai_snapshot(raw)
  self.assertEqual(public['model_count'],11);self.assertEqual(len(public['models']),5)
  self.assertEqual(public['total_tokens'],1980);self.assertEqual(public['daily_average_tokens'],66)
  self.assertTrue(all(set(d)=={'date','total_tokens'} for d in public['days']))
  self.assertEqual(r.public_ai_snapshot(public),public)
 def test_bad_public_summary_fails_reconciliation(self):
  public=r.public_ai_snapshot(r.normalize_profile(self.fixture(),dt.date(2026,10,4),'test'))
  public['days'][0]['total_tokens']+=1
  with self.assertRaises(r.InvalidData):r.public_ai_snapshot(public)
 def test_raw_import_not_saved_in_publishable_sources(self):
  config=r.read_json(Path(__file__).resolve().parents[1]/'profile-config.json')
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'README.md').write_text('\n'.join(f'<!-- BEGIN AUTO:{k} -->\n<!-- END AUTO:{k} -->' for k in ['AI','PROJECTS','ACTIVITY']))
   path=root/'local-inputs/raw.json';r.json_write(path,self.fixture())
   self.assertFalse(r.refresh(root,config,dt.date(2026,10,4),profile=path)['errors'])
   self.assertFalse((root/'sources/tokentracker-profile.json').exists())
   summary=r.read_json(root/'sources/tokentracker-last-good.json')
   self.assertEqual(len(summary['models']),5)
   self.assertTrue(all('models' not in d for d in summary['days']))

if __name__=='__main__':unittest.main()
