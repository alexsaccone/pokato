from dataclasses import replace
import hashlib
import unittest
from pokato.vision.automatic import AutoReading, Card
from pokato.vision.hole_tracking import HoleCardTracker


def card(value, index=0, *, y=400, x=300):
    visual = hashlib.sha256(value.encode()).digest()*64
    return Card((x+index*85, y, x+index*85+75, y+110), value[0], value[1], .95, visual)


def reading(time, values=('Ac', 'Kh'), *, unknown=(), board=(), source='table', duplicate=False):
    pair = tuple(card(value, i) for i, value in enumerate(values))
    pair = tuple(replace(c, rank=None, suit=None, score=.4) if i in unknown else c for i, c in enumerate(pair))
    views = (pair, tuple(card(value, i, y=20, x=600) for i, value in enumerate(values))) if duplicate else (pair,)
    return AutoReading(hand=pair, board=tuple(card(value, i, y=200, x=100) for i, value in enumerate(board)),
                       hero_verified=True, table_found=True, source=source, timestamp=time,
                       hand_views=views, image_size=(1000, 700))


def values(result):
    return tuple(c.value for c in result.hand)


class HoleTrackingTests(unittest.TestCase):
    def setUp(self):
        self.tracker = HoleCardTracker()

    def update(self, time, *args, **kwargs):
        return self.tracker.update(reading(time, *args, **kwargs), now=time)

    def confirm(self, **kwargs):
        self.update(0, **kwargs)
        result = self.update(1, **kwargs)
        self.assertEqual(values(result), ('Ac', 'Kh'))
        return result

    def test_alternating_partial_frames_accumulate_both_cards(self):
        self.assertEqual(values(self.update(0, unknown=(1,))), (None, None))
        self.update(3, unknown=(0,))
        self.update(6, unknown=(1,))
        result = self.update(9, unknown=(0,))
        self.assertEqual(values(result), ('Ac', 'Kh'))
        self.assertTrue(result.hand_held)

    def test_confirmed_pair_survives_alternating_failures_with_matching_ink(self):
        self.confirm()
        for time, unknown in ((3, (0,)), (5, (1,)), (7, (0,)), (9, (1,))):
            result = self.update(time, unknown=unknown)
            self.assertEqual(values(result), ('Ac', 'Kh'))
            self.assertTrue(result.hand_held)
        self.assertFalse(self.update(10).hand_held)

    def test_slow_alternating_reads_do_not_expire_the_card_being_read_fresh(self):
        for time, unknown in ((0, (1,)), (7, (0,)), (14, (1,))):
            self.update(time, unknown=unknown)
        result = self.update(21, unknown=(0,))
        self.assertEqual(values(result), ('Ac', 'Kh'))
        self.assertTrue(result.hand_held)

    def test_unknown_glyph_change_clears_entire_pair_without_mixing_deals(self):
        self.confirm()
        changed = self.update(2, ('Ac', '9d'), unknown=(1,))
        self.assertEqual(values(changed), (None, None))
        self.assertNotIn('Kh', values(self.update(3, ('Ac', '9d'))))
        self.assertEqual(values(self.update(4, ('Ac', '9d'))), ('Ac', '9d'))

    def test_partial_recognized_rank_conflict_also_resets(self):
        self.confirm()
        raw = reading(2)
        hand = (replace(raw.hand[0], rank='Q', suit=None), raw.hand[1])
        result = self.tracker.update(replace(raw, hand=hand), now=2)
        self.assertEqual(values(result), (None, None))

    def test_changed_uncertain_suit_is_not_hidden_by_unchanged_rank_pixels(self):
        raw = reading(0)
        original = replace(raw.hand[0], visual=bytes([20])*1024+bytes([200])*1024)
        self.tracker.update(replace(raw, hand=(original, raw.hand[1])), now=0)
        self.tracker.update(replace(raw, timestamp=1, hand=(original, raw.hand[1])), now=1)
        changed = replace(original, suit=None, visual=bytes([20])*1024+bytes([150])*1024)
        result = self.tracker.update(replace(raw, timestamp=2, hand=(changed, raw.hand[1])), now=2)
        self.assertEqual(values(result), (None, None))

    def test_board_clear_blocks_lingering_old_pair_even_in_duplicate_views(self):
        board = ('2c', '3d', '4h', '5s', '9c')
        self.confirm(board=board)
        for time in (2, 3):
            result = self.update(time, duplicate=True)
            self.assertFalse(result.hand)
            self.assertIn('new hole cards', result.hand_status)
        self.assertEqual(values(self.update(4, ('9h', 'Ts'))), (None, None))
        self.assertEqual(values(self.update(5, ('9h', 'Ts'))), ('9h', 'Ts'))

    def test_transient_board_loss_can_reacquire_after_board_returns(self):
        board = ('2c', '3d', '4h')
        self.confirm(board=board)
        self.assertFalse(self.update(2).hand)
        self.assertEqual(values(self.update(3, board=board)), (None, None))
        self.assertEqual(values(self.update(4, board=board)), ('Ac', 'Kh'))

    def test_replaced_board_clears_old_cards(self):
        self.confirm(board=('2c', '3d', '4h'))
        result = self.update(2, ('Qh', 'Jd'), unknown=(1,), board=('7c', '8d', '9s'))
        self.assertNotIn('Ac', values(result))
        self.assertNotIn('Kh', values(result))

    def test_empty_deal_frame_clears_then_identical_new_pair_needs_fresh_evidence(self):
        self.confirm()
        result = self.tracker.update(replace(reading(2), hand=(), hand_views=()), now=2)
        self.assertFalse(result.hand)
        self.assertEqual(values(self.update(3)), (None, None))
        self.assertEqual(values(self.update(4)), ('Ac', 'Kh'))

    def test_source_loss_restart_and_long_gaps_drop_all_evidence(self):
        for kind in ('source', 'loss', 'restart', 'gap'):
            with self.subTest(kind=kind):
                self.tracker.reset()
                self.confirm()
                if kind == 'loss':
                    self.tracker.update(replace(reading(2), table_found=False), now=2)
                elif kind == 'restart':
                    self.tracker.reset()
                result = self.update(20 if kind == 'gap' else 3, source='other' if kind == 'source' else 'table', unknown=(1,))
                self.assertEqual(values(result), (None, None))

    def test_each_card_expires_even_while_the_other_is_fresh(self):
        self.confirm()
        for time in (3, 6, 9, 12):
            self.assertEqual(values(self.update(time, unknown=(1,))), ('Ac', 'Kh'))
        self.assertNotIn('Kh', values(self.update(14, unknown=(1,))))

    def test_two_unknown_cards_require_matching_visible_fingerprints(self):
        self.confirm()
        self.assertEqual(values(self.update(2, unknown=(0, 1))), ('Ac', 'Kh'))
        raw = reading(3, unknown=(0, 1))
        no_ink = tuple(replace(c, visual=b'') for c in raw.hand)
        self.assertEqual(values(self.tracker.update(replace(raw, hand=no_ink), now=3)), (None, None))

    def test_duplicate_views_can_corroborate_in_one_frame_but_one_frame_cannot_vote_twice(self):
        self.assertEqual(values(self.update(0, duplicate=True)), ('Ac', 'Kh'))
        self.tracker.reset()
        first = self.update(1)
        self.assertEqual(values(first), (None, None))
        self.assertEqual(values(self.update(1)), (None, None))
        self.tracker.reset()
        raw = reading(0)
        duplicate_same_pixels = replace(raw, hand_views=(raw.hand, raw.hand))
        self.assertEqual(values(self.tracker.update(duplicate_same_pixels, now=0)), (None, None))

    def test_previously_confirmed_duplicate_view_can_take_over_during_failure(self):
        self.update(0, duplicate=True)
        raw = reading(1, unknown=(1,))
        small = tuple(replace(c, box=card('Ac', i, y=20, x=600).box) for i, c in enumerate(raw.hand))
        result = self.tracker.update(replace(raw, hand=small), now=1)
        self.assertEqual(values(result), ('Ac', 'Kh'))

    def test_unknown_cards_at_unrelated_location_do_not_inherit_old_pair(self):
        self.confirm()
        raw = reading(2, unknown=(1,))
        other = tuple(replace(c, box=card('Ac', i, y=20, x=600).box) for i, c in enumerate(raw.hand))
        self.assertEqual(values(self.tracker.update(replace(raw, hand=other), now=2)), (None, None))

    def test_resize_preserves_normalized_card_positions(self):
        self.confirm()
        raw = reading(2, unknown=(1,))
        hand = tuple(replace(c, box=tuple(value*2 for value in c.box)) for c in raw.hand)
        result = self.tracker.update(replace(raw, hand=hand, image_size=(2000, 1400)), now=2)
        self.assertEqual(values(result), ('Ac', 'Kh'))

    def test_board_collision_with_held_card_clears_the_pair(self):
        self.confirm()
        result = self.update(2, unknown=(0,), board=('Ac', '3d', '4h'))
        self.assertFalse(result.hand)
        self.assertIn('Conflicting', result.hand_status)
