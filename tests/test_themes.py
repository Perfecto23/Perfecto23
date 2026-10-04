import sys,tempfile,unittest,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import themes,refresh

class ThemeTests(unittest.TestCase):
 def test_stat_chrome_and_language_colors(self):
  raw='<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#ffffff00"/><text fill="#ae81ff">Title</text><path fill="#0579C3"/><path fill="#3178c6"/></svg>'
  dark=themes.normalize_dark(raw)
  for color in ['#101827','#a78bfa','#22d3ee','#3178c6']:self.assertIn(color,dark)
  self.assertEqual(themes.normalize_dark(dark),dark)
  adaptive=themes.adaptive_svg(dark)
  self.assertIn('@media(prefers-color-scheme:light)',adaptive)
  self.assertIn('#f8fafc',adaptive);self.assertIn('#7c3aed',adaptive)
  self.assertIn('fill="#3178c6"',adaptive)
 def test_snake_keyframes_and_timing_unchanged(self):
  raw='<svg xmlns="http://www.w3.org/2000/svg"><style>:root{--cs:purple;--c1:#9be9a8;--ce:#ebedf0}.s{animation:s 57700ms linear infinite}@keyframes s{50%{transform:translate(12px,0)}}</style></svg>'
  dark=themes.normalize_dark(raw,True)
  self.assertEqual(re.findall(r'@keyframes.*',dark),re.findall(r'@keyframes.*',raw))
  self.assertIn('animation:s 57700ms linear infinite',dark)
  self.assertIn('--cs:#22d3ee',dark);self.assertIn('--c1:#514b80',dark)
  self.assertEqual(themes.normalize_dark(dark,True),dark)
 def test_regeneration_and_picture_idempotence(self):
  with tempfile.TemporaryDirectory() as t:
   assets=Path(t);(assets/'overview.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#141321"/><text fill="#ae81ff">Title</text></svg>')
   refs=themes.make_variants(assets,refresh.write_atomic)
   md='User edited introduction\n![Overview](assets/overview.svg)'
   first=themes.adapt_readme(md,refs)
   refs2=themes.make_variants(assets,refresh.write_atomic)
   self.assertEqual(refs,refs2);self.assertEqual(first,themes.adapt_readme(first,refs2))
   self.assertIn('User edited introduction',first)
   self.assertEqual(first.count('<picture>'),1)
   self.assertIn('prefers-color-scheme: dark',first)
   self.assertIn('-adaptive-',first)
   for variants in refs2.values():
    for path in variants:self.assertTrue((assets/path.split('/')[-1]).exists())
   preview=themes.fixed_preview(first)
   self.assertNotIn('<picture>',preview);self.assertNotIn('-adaptive-',preview)
   self.assertIn('-dark-',preview);self.assertIn('../assets/',preview)
   self.assertIn('User edited introduction',preview)
if __name__=='__main__':unittest.main()
