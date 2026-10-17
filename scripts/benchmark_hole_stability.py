"""Replay labeled card pixels at varying sizes, with controlled OCR rejections."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from pokato.vision.automatic import AutoReading, arrange, detect_cards, hand_pairs
from pokato.vision.hole_tracking import HoleCardTracker
from pokato.vision.ocr import LocalOCR


def variants(image):
    yield 'original', image
    for scale in (.70, .71):
        yield f'scale-{scale}', image.resize((round(image.width*scale), round(image.height*scale)), Image.Resampling.LANCZOS)
    desktop = Image.new('RGB', (image.width+80, image.height+180), '#20242a')
    desktop.paste(image, (40, 130))
    yield 'desktop-padding', desktop


def expected(fields, prefix, count):
    return tuple(None if fields.get(f'{prefix}{i}.rank') in (None, 'empty') or
                 fields.get(f'{prefix}{i}.suit') in (None, 'empty') else
                 fields[f'{prefix}{i}.rank']+fields[f'{prefix}{i}.suit'] for i in range(count))


def compare(actual, truth, counts):
    for index, value in enumerate(truth):
        observed = actual[index] if index < len(actual) else None
        if observed and observed != value:
            counts['wrong'] += 1
        elif value:
            counts['correct' if observed == value else 'unknown'] += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('artifacts/hole-stability.json'))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    frames = [row for row in manifest['frames'] if row.get('split', 'test') == 'test']
    if not frames:
        parser.error('Manifest has no test frames')
    report = {'scope': 'Raw card pixels at four layouts/sizes; controlled alternating OCR rejection for tracking',
              'board': dict(correct=0, unknown=0, wrong=0), 'hand': dict(correct=0, unknown=0, wrong=0),
              'tracked': dict(correct=0, unknown=0, wrong=0), 'verified_held_pairs': 0, 'frames': []}
    tracker, ocr = HoleCardTracker(), LocalOCR()
    timestamp = 0.
    with patch('requests.sessions.Session.request', side_effect=AssertionError('Inference must stay offline')):
        for row in frames:
            with Image.open(args.manifest.parent/row['image']) as opened:
                image = opened.convert('RGB')
            truth_board, truth_hand = expected(row['fields'], 'board', 5), expected(row['fields'], 'hole', 2)
            for label, sample in variants(image):
                cards = detect_cards(sample, ocr)
                board, hand, issues = arrange(cards)
                raw = AutoReading(board=board, hand=hand, issues=issues, table_found=bool(board or hand),
                                  source='local replay', timestamp=timestamp,
                                  hand_views=hand_pairs(cards), image_size=sample.size)
                tracked = tracker.update(raw, now=timestamp)
                board_values, hand_values = tuple(c.value for c in board), tuple(c.value for c in hand)
                tracked_values = tuple(c.value for c in tracked.hand)
                compare(board_values, truth_board, report['board'])
                compare(hand_values, truth_hand, report['hand'])
                compare(tracked_values, truth_hand, report['tracked'])
                if len(hand) == 2:
                    slot = len(report['frames']) % 2
                    partial = tuple(replace(c, rank=None, suit=None, score=.4) if i == slot else c
                                    for i, c in enumerate(hand))
                    rejected = replace(raw, timestamp=timestamp+1, hand=partial, hand_views=(partial,))
                    held = tracker.update(rejected, now=timestamp+1)
                    compare(tuple(c.value for c in held.hand), truth_hand, report['tracked'])
                    if tracked_values == truth_hand and tuple(c.value for c in held.hand) == truth_hand and held.hand_held:
                        report['verified_held_pairs'] += 1
                report['frames'].append(dict(image=row['image'], variant=label, board=board_values,
                                             hand=hand_values, tracked=tracked_values))
                timestamp += 2
    report['ok'] = all(report[group]['wrong'] == 0 for group in ('board', 'hand', 'tracked'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'frames'}))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
