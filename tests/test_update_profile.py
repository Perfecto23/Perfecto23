import os, unittest, importlib.util, datetime as dt, json, tempfile, shutil, re
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
P = Path(__file__).resolve().parents[1]
s = importlib.util.spec_from_file_location('u', P / 'scripts/update-profile.py')
u = importlib.util.module_from_spec(s)
s.loader.exec_module(u)
TODAY = dt.date(2026, 10, 6)

def make_day(date, tokens, client='codex', model='gpt-6-astra'):
    return {
        'date': date.isoformat(),
        'totals': {'tokens': tokens},
        'clients': [{
            'client': client,
            'tokens': {'input': tokens, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0, 'reasoning': 0},
            'models': {model: {'tokens': tokens}},
        }],
    }

def fixture():
    end = TODAY
    start = end - dt.timedelta(days=13)
    days = [make_day(start - dt.timedelta(days=5), 5000, 'cursor', 'old-model')]
    for i in range(14):
        tokens = 0 if i % 5 == 0 else (i + 1) * 1000
        client = 'claude' if i >= 11 else 'codex'
        model = 'claude-opus-5-5' if i >= 11 else 'gpt-6-astra'
        days.append(make_day(start + dt.timedelta(days=i), tokens, client, model))
    total = sum(day['totals']['tokens'] for day in days)
    return {
        'user': {'username': 'Perfecto23', 'displayName': 'Perfecto', 'rank': 286, 'rankDateRange': None},
        'stats': {'totalTokens': total, 'activeDays': 999},
        'chartRange': {'start': start.isoformat(), 'end': end.isoformat()},
        'period': 'all',
        'updatedAt': '2026-10-06T03:41:00Z',
        'submissionFreshness': {'isStale': False},
        'contributions': days,
    }

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(P / 'assets', self.root / 'assets')
        for filename in ['README.md', 'README.zh-CN.md']:
            shutil.copy(P / filename, self.root / filename)
        self.p = patch.object(u, 'ROOT', self.root)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_rounding(self):
        for number, label in [(999999, '1M'), (999999999, '1B'), (999999999999, '1T'), (0, '0')]:
            self.assertEqual(u.compact(number), label)
        self.assertEqual(u.hero_compact(91778243106), '91.8B')
        self.assertEqual(u.compact(232063581), '232.06M')

    def test_share_and_labels(self):
        self.assertEqual(u.share(413, 1000), '41.3%')
        self.assertEqual(u.share(0, 10), '0%')
        self.assertEqual(u.share(1, 100000), '<0.1%')
        self.assertEqual(u.client_label('openclaw'), 'OpenClaw')
        self.assertEqual(u.client_label('custom-agent'), 'Custom-agent')
        self.assertEqual(u.heat_levels([0, 1, 2, 3, 4, 5, 6, 7, 8]), [0, 1, 1, 2, 2, 3, 3, 4, 4])
        self.assertEqual(u.heat_levels([0, 5, 5, 5]), [0, 3, 3, 3])

    def test_profile_uses_series_not_the_headline(self):
        data = u.normalize_tokscale(fixture(), TODAY, '2026-10-06T12:00:00Z')
        self.assertEqual(data['total_tokens'], 92000)
        self.assertEqual(data['active_days'], 11)
        self.assertEqual(data['peak_tokens'], 14000)
        self.assertEqual(data['peak_date'], '2026-10-06')
        self.assertEqual(len(data['days']), 14)
        self.assertEqual(data['days'][0]['total_tokens'], 0)
        self.assertEqual(data['rank'], 286)
        self.assertEqual([row['name'] for row in data['clients']], ['codex', 'claude', 'cursor'])
        self.assertEqual(data['models'][0]['name'], 'gpt-6-astra')
        self.assertTrue(data['current_day_partial'])
        self.assertFalse(data['stale'])
        self.assertIn('tokscale', data['source'])
        self.assertNotIn('TokenTracker', data['source'])

    def test_missing_day_is_filled_with_zero(self):
        payload = fixture()
        start = dt.date.fromisoformat(payload['chartRange']['start'])
        target = (start + dt.timedelta(days=4)).isoformat()
        removed = next(day for day in payload['contributions'] if day['date'] == target)
        payload['contributions'] = [day for day in payload['contributions'] if day['date'] != target]
        payload['stats']['totalTokens'] -= removed['totals']['tokens']
        data = u.normalize_tokscale(payload, TODAY, 'stamp')
        filled = next(day for day in data['days'] if day['date'] == target)
        self.assertEqual(filled['total_tokens'], 0)
        self.assertEqual(data['total_tokens'], payload['stats']['totalTokens'])

    def test_split_day_sums_clients_and_models(self):
        payload = fixture()
        day = payload['contributions'][-1]
        day['clients'] = [
            {'client': 'claude', 'tokens': {'input': 8000, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0, 'reasoning': 0},
             'models': {'claude-opus-5-5': {'tokens': 8000}}},
            {'client': 'codex', 'tokens': {'input': 6000, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0, 'reasoning': 0},
             'models': {'gpt-6-astra': {'tokens': 4000}, 'gpt-5.6-sol': {'tokens': 2000}}},
        ]
        data = u.normalize_tokscale(payload, TODAY, 'stamp')
        clients = {row['name']: row['tokens'] for row in data['clients']}
        models = {row['name']: row['tokens'] for row in data['models']}
        self.assertEqual(clients['codex'], 54000)
        self.assertEqual(clients['claude'], 33000)
        self.assertEqual(models['gpt-6-astra'], 52000)
        self.assertEqual(models['gpt-5.6-sol'], 2000)
        self.assertEqual(models['claude-opus-5-5'], 33000)

    def test_rejects_bad_payloads(self):
        payload = fixture()
        payload['contributions'][-1]['totals']['tokens'] += 1
        payload['stats']['totalTokens'] += 1
        with self.assertRaises(u.InvalidData):
            u.normalize_tokscale(payload, TODAY, 'stamp')
        payload = fixture()
        payload['stats']['totalTokens'] += 5
        with self.assertRaises(u.InvalidData):
            u.normalize_tokscale(payload, TODAY, 'stamp')
        payload = fixture()
        payload['contributions'].append(payload['contributions'][-1])
        with self.assertRaises(u.InvalidData):
            u.normalize_tokscale(payload, TODAY, 'stamp')
        payload = fixture()
        payload['user']['username'] = 'someone-else'
        with self.assertRaises(u.InvalidData):
            u.normalize_tokscale(payload, TODAY, 'stamp')
        payload = fixture()
        payload['user']['rank'] = 0
        with self.assertRaises(u.InvalidData):
            u.normalize_tokscale(payload, TODAY, 'stamp')
        payload = fixture()
        payload['period'] = 'month'
        with self.assertRaises(u.InvalidData):
            u.normalize_tokscale(payload, TODAY, 'stamp')
        payload = fixture()
        payload['chartRange']['end'] = '2026-12-01'
        with self.assertRaises(u.InvalidData):
            u.normalize_tokscale(payload, TODAY, 'stamp')
        payload = fixture()
        for day in payload['contributions']:
            day['totals']['tokens'] = 0
            for client in day['clients']:
                for key in client['tokens']:
                    client['tokens'][key] = 0
                for model in client['models'].values():
                    model['tokens'] = 0
        payload['stats']['totalTokens'] = 0
        with self.assertRaises(u.InvalidData):
            u.normalize_tokscale(payload, TODAY, 'stamp')

    def test_render_light_and_dark(self):
        data = u.normalize_tokscale(fixture(), TODAY, '2026-10-06T12:00:00Z')
        light = u.render_usage(data, 'light', TODAY)
        dark = u.render_usage(data, 'dark', TODAY)
        self.assertEqual(light, u.render_usage(data, 'light', TODAY))
        for svg, theme in ((light, 'light'), (dark, 'dark')):
            root = ET.fromstring(svg)
            self.assertEqual(root.get('width'), root.get('viewBox').split()[2])
            self.assertNotIn('TokenTracker', svg)
            self.assertNotIn('<script', svg.lower())
            self.assertNotIn('foreignObject', svg)
            self.assertIn(u.hero_compact(data['total_tokens']), svg)
            self.assertIn('>11<', svg)
            self.assertIn('#286', svg)
            self.assertIn('Codex', svg)
            self.assertIn('gpt-6-astra', svg)
            self.assertIn('Peak day', svg)
            self.assertIn('data-mix="models"', svg)
            self.assertIn('78.6%', svg)
            self.assertIn('id="ai-status"', svg)
            self.assertIn(f'fill="{u.THEMES[theme]["bg"]}"', svg)
        self.assertIn('data-chart="heatmap"', light)
        self.assertEqual(light.count('data-date='), len(data['days']))
        self.assertIn('Less', light)
        self.assertIn('More', light)
        self.assertIn('width="820"', light)
        self.assertIn('in progress', light)

    def test_fetch_does_not_send_github_token_to_tokscale(self):
        seen = {}
        class Resp:
            status = 200
            def read(self, n=-1):
                return b'{}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        def fake_open(req, timeout=0):
            seen['url'] = req.full_url
            seen['auth'] = req.get_header('Authorization')
            return Resp()
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'ghp_secret'}):
            with patch('urllib.request.urlopen', fake_open):
                # A token argument is still ignored unless the host is api.github.com.
                u.fetch('https://tokscale.ai/api/users/Perfecto23', 'ghp_secret')
                self.assertIsNone(seen['auth'])
                self.assertNotIn('ghp_secret', seen['url'])
                u.fetch('https://api.github.com/user', 'ghp_secret')
                self.assertEqual(seen['auth'], 'Bearer ghp_secret')

    def test_failure_retention_recovery(self):
        originals = {name: (self.root / 'assets' / name).read_text() for name in u.AI_ASSETS}
        with patch.object(u, 'fetch', side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):
                u.update_ai(TODAY, '2026-10-06T12:00:00Z')
        for name, old in originals.items():
            self.assertEqual(old, (self.root / 'assets' / name).read_text())
        u.mark_ai_retained(TODAY, '2026-10-06T12:00:00Z')
        def data(svg):
            return re.sub(r'<text id="ai-status"[^>]*>.*?</text>', '', svg, flags=re.S).rstrip('\r\n')
        for name, old in originals.items():
            new = (self.root / 'assets' / name).read_text()
            self.assertEqual(data(old), data(new))
            self.assertIn('retained', new)
        with patch.object(u, 'fetch', return_value=json.dumps(fixture()).encode()):
            u.update_ai(TODAY, '2026-10-06T12:00:00Z')
        for name in originals:
            self.assertNotIn('retained', (self.root / 'assets' / name).read_text())

    def test_update_reads_public_tokscale_url(self):
        with patch.object(u, 'fetch', return_value=json.dumps(fixture()).encode()) as fetch:
            u.update_ai(TODAY, '2026-10-06T12:00:00Z')
        self.assertEqual(fetch.call_args.args[0], 'https://tokscale.ai/api/users/Perfecto23')

    def test_productive_error_keeps_data(self):
        path = self.root / 'assets/productive-time.svg'
        old = path.read_bytes()
        with patch.object(u, 'fetch', return_value=b'<svg><text>ERROR rate limited</text></svg>'):
            with self.assertRaises(u.InvalidData):
                u.update_productive(TODAY, 'stamp')
        self.assertEqual(old, path.read_bytes())

    def test_project_filter(self):
        repos = [
            {'full_name': 'neworg/newproject', 'fork': False, 'private': False, 'owner_type': 'Organization', 'merged_authored_pr_count': 2},
            {'full_name': 'MoeGo/internal', 'fork': False, 'private': False, 'owner_type': 'Organization', 'merged_authored_pr_count': 3},
        ]
        self.assertEqual([row['full_name'] for row in u.filter_projects(repos, u.CONFIG)], ['neworg/newproject'])

    def test_projects_update_both_languages(self):
        repos = [{'full_name': 'neworg/newproject', 'fork': False, 'private': False, 'owner_type': 'Organization', 'merged_authored_pr_count': 2}]
        with patch.object(u, 'fetch_projects', return_value={'repositories': repos}):
            u.update_projects(TODAY, 'stamp')
        for filename, label in [('README.md', 'Contributed to:'), ('README.zh-CN.md', '参与贡献的项目：')]:
            text = (self.root / filename).read_text()
            self.assertIn('https://github.com/neworg/newproject', text)
            self.assertIn(label, text)

    def test_invalid_chinese_markers_preserve_both(self):
        path = self.root / 'README.zh-CN.md'
        path.write_text(path.read_text().replace('<!-- END AUTO:PROJECTS -->', ''))
        before = {filename: (self.root / filename).read_bytes() for filename in ['README.md', 'README.zh-CN.md']}
        repos = [{'full_name': 'neworg/newproject', 'fork': False, 'private': False, 'owner_type': 'Organization', 'merged_authored_pr_count': 2}]
        with patch.object(u, 'fetch_projects', return_value={'repositories': repos}):
            with self.assertRaises(u.InvalidData):
                u.update_projects(TODAY, 'stamp')
        for filename, value in before.items():
            self.assertEqual((self.root / filename).read_bytes(), value)

    def test_readmes_and_workflow_use_tokscale(self):
        for filename in ['README.md', 'README.zh-CN.md']:
            text = (self.root / filename).read_text()
            self.assertIn('https://tokscale.ai/u/Perfecto23', text)
            self.assertIn('prefers-color-scheme: dark', text)
            self.assertIn('assets/ai-usage-dark.svg', text)
            self.assertNotIn('ai-usage-mobile', text)
            self.assertNotIn('tokentracker', text.lower())
            self.assertNotIn('TokenTracker', text)
        workflow = (P / '.github/workflows/update-profile.yml').read_text()
        for name in u.AI_ASSETS:
            self.assertIn(name, workflow)
        self.assertNotIn('ai-models.svg', workflow)
        self.assertNotIn('ai-usage-mobile', workflow)
        self.assertNotIn('tokentracker', workflow.lower())
        self.assertNotIn('TOKSCALE', workflow)

    def test_structure(self):
        u.check()

if __name__ == '__main__':
    unittest.main(verbosity=2)
