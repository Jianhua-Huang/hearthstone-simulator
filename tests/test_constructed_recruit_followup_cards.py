"""Complete new real cards and their existing Kindred/Prepare entry points."""
import unittest
from hs_sim.cards.recruit_followup_cards import load_batch
from hs_sim.engine import (Attack, EndTurn, Game, Keyword, PlayCard, PlayerSetup,
    Scenario, UseHandAction)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from test_recruit_followups import registry


class ConstructedRecruitFollowupCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r = registry()
    def game(self, hand=(), board=(), deck=('k08.body','k08.demon','k08.other'), enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero', hand=hand, board=board,
            deck=deck, mana=30, max_mana=30, mana_cap=30), PlayerSetup('test.hero', board=enemy)), seed=83), self.r)
    def eid(self, g, cid): return next(e for e in g.state.players[1].hand if g.state.entities[e].card_id == cid)
    def play(self, g, cid, target=None):
        e = self.eid(g, cid); g.apply(PlayCard(1, e, target_id=target)); return e
    def names(self, g, zone='board', p=1): return [g.state.entities[e].card_id for e in getattr(g.state.players[p],zone)]
    def price(self, g, cid): return quote_cost(g.state, g.registry, g.state.entities[self.eid(g,cid)]).amount
    def portable(self, g):
        saved = g.snapshot()
        for other in (g.clone(), Game.from_snapshot(saved, registry()), replay(build_replay(g), registry())):
            self.assertEqual(other.snapshot(), saved)

    def test_eight_full_pinned_definitions_and_seven_root_entry_points(self):
        data = load_batch(); self.assertEqual(len(data['cards']),8)
        for row in data['cards']:
            cid = row['record']['id']; spec = row['recipe']
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            if not spec['root']: continue
            with self.subTest(card=cid):
                g = self.game((cid,'k08.kill')); before = g.state.players[1].mana
                target = g.state.players[2].hero_id if cid == 'TLC_600' else None
                e = self.play(g,cid,target)
                self.assertEqual(g.state.play_history[-1].mana_after,before-row['record']['cost'])
                if 'deathrattle' in spec['bodies']: self.play(g,'k08.kill',e)
                self.assertIsNone(g.state.pending_choice)

    def test_scarlet_recruiter_moves_two_originals_grants_rush_and_not_own_body(self):
        g = self.game(('JAIL_516',),deck=('k08.body','k08.cry','k08.other'),enemy=('k08.other',))
        original = set(g.state.players[1].deck); recruiter = self.play(g,'JAIL_516')
        bodies = [e for e in g.state.players[1].board if e != recruiter]
        self.assertEqual(len(bodies),2); self.assertTrue(set(bodies)<=original)
        self.assertNotIn(Keyword.RUSH,g.state.entities[recruiter].keywords)
        self.assertTrue(all(Keyword.RUSH in g.state.entities[e].keywords for e in bodies))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        legal=g.legal_actions()
        self.assertTrue(any(isinstance(a,Attack) and a.attacker_id in bodies for a in legal))
        self.assertFalse(any(isinstance(a,Attack) and a.attacker_id in bodies and a.defender_id==g.state.players[2].hero_id for a in legal))
        g.apply(next(a for a in legal if isinstance(a,Attack) and a.attacker_id in bodies))
        self.portable(g)

    def test_possessed_animalmancer_filters_beast_and_actual_combat_lifesteals(self):
        g = self.game(('DINO_131','k08.kill','k08.wound'),deck=('k08.body','k08.demon'),enemy=('k08.other',))
        original = g.state.players[1].deck[0]; source = self.play(g,'DINO_131'); self.play(g,'k08.kill',source)
        e = g.state.entities[original]; self.assertEqual(e.controller,1); self.assertIn(Keyword.LIFESTEAL,e.keywords)
        self.assertEqual(self.names(g,'deck'),['k08.demon']);self.play(g,'k08.wound')
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        g.apply(Attack(1,original,g.state.players[2].board[0]))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28);self.portable(g)

    def test_morag_grants_real_deathrattle_return_and_returned_card_keeps_own_prepare_and_death(self):
        g = self.game(('JAIL_906','k08.kill','k08.kill'),deck=('k08.demon','k08.body'))
        source = self.play(g,'JAIL_906'); demon = g.state.players[1].deck[0]; self.play(g,'k08.kill',source)
        self.assertEqual(self.names(g,'board').count('JAIL_906'),0)
        self.play(g,'k08.kill',demon)
        returned = next(e for e in g.state.players[1].board if g.state.entities[e].card_id == 'JAIL_906')
        self.assertNotEqual(returned,source); self.assertEqual((g.state.entities[returned].attack,g.state.entities[returned].health),(6,5))
        self.assertTrue(g.registry.card('JAIL_906').hand_actions); self.portable(g)

    def test_duel_recruits_own_original_and_creates_opponent_complete_stealth_tiger(self):
        g = self.game(('TIME_870',),deck=('k08.body',)); original = g.state.players[1].deck[0]
        self.play(g,'TIME_870'); self.assertEqual(g.state.players[1].board,[original])
        tiger = g.state.entities[g.state.players[2].board[0]]
        self.assertEqual((tiger.card_id,tiger.owner,tiger.controller,tiger.attack,tiger.health),('TIME_870t',2,2,5,5))
        self.assertIn(Keyword.STEALTH,tiger.keywords); self.portable(g)

    def test_duel_empty_deck_still_delivers_opponent_tiger_without_fatigue(self):
        g = self.game(('TIME_870',),deck=()); self.play(g,'TIME_870')
        self.assertEqual(self.names(g),[]); self.assertEqual(self.names(g,p=2),['TIME_870t'])
        self.assertEqual(g.state.draw_history,[])

    def test_kindred_discounts_use_previous_actual_owner_turn_and_payment(self):
        cards=('TLC_366','TLC_600','TLC_816','k08.body','k08.other','k08.holy')
        g = self.game(cards)
        self.assertEqual([self.price(g,c) for c in cards[:3]],[6,8,4])
        self.play(g,'k08.body'); self.play(g,'k08.other'); self.play(g,'k08.holy')
        self.assertEqual([self.price(g,c) for c in cards[:3]],[6,8,4])
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual([self.price(g,c) for c in cards[:3]],[4,6,2])
        self.play(g,'TLC_366'); self.assertEqual(g.state.play_history[-1].cost,4)
        self.play(g,'TLC_600',g.state.players[2].hero_id); self.assertEqual(g.state.play_history[-1].cost,6)
        self.play(g,'TLC_816'); self.assertEqual(g.state.play_history[-1].cost,2); self.portable(g)

    def test_whelp_battlecry_damage_is_not_spell_bonus_and_armor_runs_after_it(self):
        g = self.game(('TLC_600',),board=('k08.spellpower',)); self.play(g,'TLC_600',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)

    def test_morag_prepare_reuses_investment_and_original_hand_lifetime(self):
        g = self.game(('JAIL_906',)); source = self.eid(g,'JAIL_906')
        g.apply(UseHandAction(1,source,'prepare'))
        self.assertEqual(self.price(g,'JAIL_906'),0)
        self.assertFalse(any(isinstance(a,PlayCard) and a.entity_id == source for a in g.legal_actions()))
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g,'JAIL_906')
        self.assertEqual(g.state.play_history[-1].cost,0); self.portable(g)


if __name__ == '__main__': unittest.main()
