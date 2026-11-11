from pathlib import Path
import json
import tempfile
import unittest

from ssr.crosscut import gap_census as api
import test_mouse_actions as fixtures  # authored write_kmb helper

class PagingTests(unittest.TestCase):
    def test_complete_pages_and_disjoint_worker_partitions(self):
        with tempfile.TemporaryDirectory() as temp:
            source = fixtures.write_kmb(Path(temp) / 'source.kmb',
                [f'X q{i}' for i in range(50)] * 2, num_qubits=50)
            digest = api.sha256(source)
            full = Path(temp) / 'all.json'
            api.census(source, digest, full_artifact=full)
            expected = [row['handle'] for row in json.loads(full.read_text())['cards']]
            def collect(offset, stride):
                rows = []
                while offset is not None:
                    page = api.census(source, digest, offset=offset, stride=stride, limit=7)
                    self.assertLessEqual(len(page['cards']), 7)
                    rows.extend(page['cards'])
                    offset = page['next_offset']
                return rows
            ordinary = collect(0, 1)
            self.assertEqual([r['handle'] for r in ordinary], expected)
            self.assertEqual([r['rank'] for r in ordinary], list(range(1, len(expected)+1)))
            workers = [collect(i, 3) for i in range(3)]
            merged = sorted([r for worker in workers for r in worker], key=lambda r:r['rank'])
            self.assertEqual([r['handle'] for r in merged], expected)
            self.assertEqual(len({r['handle'] for r in merged}), len(expected))
            self.assertEqual(api.census(source, digest, offset=10000)['cards'], [])
            for field, values in [('offset', [-1, True, 1.2]), ('stride', [0, -1, True, 257])]:
                for value in values:
                    with self.assertRaises(api.CensusError):
                        api.census(source, digest, **{field:value})
            with self.assertRaisesRegex(api.CensusError, 'stale'):
                api.census(source, '0'*64, offset=7)

if __name__ == '__main__':
    unittest.main()
