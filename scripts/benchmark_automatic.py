"""Evaluate automatic cards on local labeled images, without a calibration profile."""
import argparse
import json
from pathlib import Path
import time
from unittest.mock import patch
from PIL import Image
from pokato.vision.automatic import AutomaticReader
from pokato.vision.sources import Frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('artifacts/automatic-benchmark.json'))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    rows = [row for row in manifest['frames'] if row.get('split', 'test') == 'test']
    if not rows:
        parser.error('Manifest has no test frames')
    report = {'scope': 'Card recognition only; no profiles, network or strategy evaluation',
              'frames': [], 'board': {'correct': 0, 'unknown': 0, 'wrong': 0},
              'hand': {'correct': 0, 'unknown': 0, 'wrong': 0}, 'complete_verified_hands': 0}
    reader = AutomaticReader()
    with patch('requests.sessions.Session.request', side_effect=AssertionError('Inference must stay offline')):
        for index, row in enumerate(rows):
            started = time.monotonic()
            with Image.open(args.manifest.parent/row['image']) as image:
                reading = reader.read(Frame(image.convert('RGB'), index, index, row['image']))
            result = {'image': row['image'], 'table_found': reading.table_found,
                      'hero_verified': reading.hero_verified, 'wrong': []}
            for group, prefix, count, actual in (('board', 'board', 5, reading.board),
                                                  ('hand', 'hole', 2, reading.hand)):
                values = [card.value for card in actual]
                result[group] = values
                expected_values = []
                for slot in range(count):
                    rank = row['fields'].get(f'{prefix}{slot}.rank')
                    suit = row['fields'].get(f'{prefix}{slot}.suit')
                    if rank is None or suit is None:
                        expected_values.append(None)
                        continue
                    expected = None if 'empty' in (rank, suit) else rank+suit
                    expected_values.append(expected)
                    value = values[slot] if slot < len(values) else None
                    if value is not None and value != expected:
                        report[group]['wrong'] += 1
                        result['wrong'].append({'field': f'{prefix}{slot}', 'actual': value, 'expected': expected})
                    elif expected is not None:
                        report[group]['correct' if value == expected else 'unknown'] += 1
                result['expected_'+group] = expected_values
            if reading.hero_verified and result['hand'] == result['expected_hand']:
                report['complete_verified_hands'] += 1
            result['seconds'] = round(time.monotonic()-started, 2)
            report['frames'].append(result)
    report['ok'] = not (report['board']['wrong'] or report['hand']['wrong'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'frames'}))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
