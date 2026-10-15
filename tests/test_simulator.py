import unittest
from pokato.core.game import Game
from pokato.simulator.render import render
from pokato.simulator.bots import choose_action
from pokato.simulator.layout import WIDTH, HEIGHT


class SimulatorTests(unittest.TestCase):
    def test_bots_finish_hand_and_public_render_hides_opponents(self):
        g = Game()
        g.new_hand()
        self.assertEqual(render(g).size, (WIDTH, HEIGHT))
        # Changing hidden opponents' cards cannot change the visible frame.
        before = render(g).tobytes()
        g.players[1].hole = ["As", "Ah"]
        self.assertEqual(before, render(g).tobytes())
        # Restore legal unique cards before running the hand.
        g = Game()
        g.new_hand()
        for _ in range(150):
            if g.actor < 0:
                break
            action, target = choose_action(g)
            g.act(action, target)
        self.assertEqual(g.street, "X")
        self.assertEqual(sum(p.stack for p in g.players), 6000)


if __name__ == "__main__":
    unittest.main()
