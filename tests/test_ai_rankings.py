import datetime as dt,sys,unittest,xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import refresh as r
P=Path(__file__).resolve().parents[1]
def fixture():
 end=dt.date(2026,10,4)
 return r.normalize_profile({'heatmap':[{'date':(end-dt.timedelta(days=i)).isoformat(),'total_tokens':66,'models':{f'fixture-model-{j}':j+1 for j in range(11)}} for i in range(29,-1,-1)]},end,'test-only')
class RankingTests(unittest.TestCase):
 def test_thirty_day_top5_keeps_full_totals_and_heatmap(self):
  ai=fixture();cum=None;config=r.read_json(P/'profile-config.json')
  svg=r.render_ai(ai,cum,config);root=ET.fromstring(svg)
  texts=[''.join(e.itertext()) for e in root.iter() if e.tag.endswith('text')]
  ranked=sorted(ai['models'],key=lambda m:(-m['tokens'],m['name']))
  self.assertEqual([v for v in texts if v in {m['name'] for m in ranked}],[m['name'] for m in ranked[:5]])
  self.assertLess(sum(m['tokens'] for m in ranked[:5]),ai['total_tokens'])
  self.assertIn(r.compact(ai['total_tokens']),texts);self.assertIn(r.compact(ai['total_tokens']/30),texts)
  self.assertIn('Past 30 days · Top 5',texts);self.assertIn('All-time · Top 5',texts);self.assertIn('Not available',texts)
  self.assertEqual(len([e for e in root.iter() if e.tag.endswith('title') and ' tokens' in ''.join(e.itertext())]),30)
 def test_365_favorite_or_provider_data_cannot_be_alltime(self):
  ai=fixture();config=r.read_json(P/'profile-config.json')
  for bad in [{'period':{'kind':'total'},'models':ai['models']},{'scope':'365_days','complete_history':True,'models':ai['models'],'total_tokens':ai['total_tokens']},{'scope':'all_time','complete_history':False,'models':ai['models'],'total_tokens':ai['total_tokens']}]:
   with self.subTest(bad=bad),self.assertRaises(r.InvalidData):r.render_ai(ai,None,config,all_time=bad)
 def test_verified_alltime_contract_top5_and_full_denominator(self):
  ai=fixture();config=r.read_json(P/'profile-config.json')
  models=[{'name':f'fixture-lifetime-{i}','tokens':i+1} for i in range(8)]
  data={'scope':'all_time','complete_history':True,'models':models,'total_tokens':36}
  svg=r.render_ai(ai,None,config,all_time=data);texts=[''.join(e.itertext()) for e in ET.fromstring(svg).iter() if e.tag.endswith('text')]
  self.assertEqual([v for v in texts if v.startswith('fixture-lifetime-')],[f'fixture-lifetime-{i}' for i in range(7,2,-1)])
  self.assertIn(f'{8/36:.1%}',texts);self.assertNotIn('Not available',texts)
if __name__=='__main__':unittest.main()
