from dataclasses import replace
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from pokato.vision.automatic import AutomaticReader, Card, arrange, amount, player_amounts, pot_amounts
from pokato.vision.ocr import LocalOCR, Text
from pokato.vision.screen import DesktopSource
from pokato.vision.sources import Frame
from auto_screens import screen


class AutomaticTests(unittest.TestCase):
    def test_unseen_clients_fonts_positions_and_four_color_cards_without_profiles(self):
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Inference must stay offline')):
            reader = AutomaticReader()
            for style in ('green','purple'):
                image, board, hand = screen(style)
                result = reader.read(Frame(image,0,0,'unseen fictional client'))
                with self.subTest(style=style):
                    self.assertTrue(result.table_found, result)
                    self.assertEqual(tuple(c.value for c in result.board),board)
                    self.assertEqual(tuple(c.value for c in result.hand),hand)
                    self.assertTrue(result.hero_verified, result)
                    self.assertTrue(any(p.value=='125.50' for p in result.pots), result.pots)

    def test_missing_middle_card_remains_an_unknown_slot(self):
        cards=tuple(Card((x,100,x+60,190),rank,'h',.95) for x,rank in ((100,'A'),(170,'K'),(310,'J'),(380,'T')))
        board, hand, issues=arrange(cards)
        self.assertEqual(len(board),5)
        self.assertIsNone(board[2].value)
        self.assertFalse(hand)

    def test_multiple_tables_and_showdown_hands_are_not_silently_merged(self):
        board=tuple(Card((x,100,x+60,190),rank,'h',.95) for x,rank in ((100,'A'),(170,'K'),(240,'Q')))
        second=tuple(replace(c,box=(c.box[0]+600,100,c.box[2]+600,190)) for c in board)
        self.assertIn('Multiple',arrange(board+second)[2][0])
        first=tuple(Card((x,350,x+60,440),rank,'c',.95) for x,rank in ((100,'2'),(170,'3')))
        other=tuple(Card((x,550,x+60,640),rank,'s',.95) for x,rank in ((100,'4'),(170,'5')))
        self.assertFalse(arrange(board+first+other)[1])

    def test_money_and_labels_reject_chat_and_ambiguous_numbers(self):
        self.assertTrue(amount('53.5K').approximate)
        self.assertEqual(amount('$125.50').value,'125.50')
        self.assertIsNone(amount('1,20'))
        self.assertIsNone(amount('won 50K'))
        chat=(Text('WickedShove5.2 won the pot',.99,(0,0,400,30)),Text('Other player won pot 200',.99,(0,40,400,70)))
        self.assertFalse(pot_amounts(chat))
        label=Text('Main pot',.99,(100,100,200,125));number=Text('$125.50',.99,(100,122,200,150))
        self.assertEqual(pot_amounts((label,number))[0].value,'125.50')
        name=Text('Opponent',.99,(100,100,200,130));stack=Text('50K',.99,(130,125,180,155))
        self.assertEqual(player_amounts((name,stack))[0].name,'Opponent')

    def test_desktop_capture_masks_the_hud_when_exclusion_is_unavailable(self):
        with patch('pokato.vision.screen.ImageGrab.grab',return_value=Image.new('RGB',(200,100),'white')):
            source=DesktopSource()
            # Virtual-screen offset is read from Windows; leave mask absent for
            # pixel preservation, then mock a zero-origin display for the mask.
            first=source.next();self.assertEqual(first.image.getpixel((5,5)),(255,255,255))
            source.mask=(0,0,40,40)
            with patch('pokato.vision.screen.sys.platform','linux'):
                second=source.next()
            self.assertEqual(second.image.getpixel((5,5)),(17,21,29))
            self.assertEqual(second.index,1)
            source.close();self.assertIsNone(source.next())
