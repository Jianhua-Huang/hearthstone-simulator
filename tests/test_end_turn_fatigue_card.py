"""A real owner-end weapon reads current successful casts and shares fatigue."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.constructed import build_registry
from hs_sim.cards.end_turn_fatigue_card import CARD, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice)
from hs_sim.engine.effects import (ChoiceOption, EquipWeapon, GainArmor, InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.fatigue import TakeFatigue
from hs_sim.engine.model import CardClass, CardMetadata, EndTurnSpec, SpellSchool, TriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from tools.card_batch import check_face

P = 'fixture.blade_fatigue.'
SHADOW, FIRE, PLAIN, AUTO, TICK, SWAP, WAIT, FAULT, END, POWER = (P+x for x in
    ('shadow', 'fire', 'plain', 'auto', 'tick', 'swap', 'wait', 'fault', 'end', 'power'))
IMMUNE = P+'immune'
COIN = 'GAME_005'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent registry role required')
    r = build_registry()
    def fail(c): raise ResolutionError('Explicit fatigue reaction failure')
    r.register_behavior(P+'fail', fail)
    bodies = {
        SHADOW: lambda c: (), FIRE: lambda c: (), PLAIN: lambda c: (),
        AUTO: lambda c: (CastSpell(c.player_id, SHADOW, c.source_id),),
        TICK: lambda c: (TakeFatigue(3-c.player_id, c.source_id),),
        SWAP: lambda c: (EquipWeapon(c.player_id, 'CS2_106'),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            spell_school=SpellSchool.SHADOW if cid == SHADOW else SpellSchool.FIRE if cid == FIRE else None,
            metadata=META))
    def wait(c):
        if c.event.player_id != c.player_id: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('shadow', 'Cast Shadow',
            (CastSpell(c.player_id, SHADOW, c.source_id),)), ChoiceOption('fail', 'Fail',
            (GainArmor(c.player_id, 1), InvokeBehavior(P+'fail', c.source_id, c.player_id)))), c.source_id),)
    r.register_behavior(P+'wait', wait)
    r.register_behavior(P+'fault', lambda c: (InvokeBehavior(P+'fail', c.source_id, c.player_id),))
    r.register_behavior(P+'end', lambda c: (CastSpell(c.player_id, SHADOW, c.source_id),))
    for cid, event, body in [(WAIT, 'fatigue', 'wait'), (FAULT, 'fatigue', 'fault'), (END, 'turn_ended', 'end')]:
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=5,
            triggers=(TriggerSpec(event, P+body, EndTurnSpec() if cid == END else None),), metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.MINION, health=5, spell_damage=20, metadata=META))
    r.register_card(replace(r.card('HERO_09'), id=IMMUNE, keywords=(Keyword.IMMUNE,)))
    return r


class EndTurnFatigueTests(unittest.TestCase):
    def game(self, hand=(), board=(), weapon=None, armor=0, hero='HERO_09', enemy_hand=(), enemy_hero='HERO_08'):
        return Game.from_scenario(Scenario((PlayerSetup(hero, hand=hand, board=board, weapon_card_id=weapon,
            deck=(COIN,)*6, armor=armor, mana=10, max_mana=10), PlayerSetup(enemy_hero,
            hand=enemy_hand, deck=(COIN,)*6, mana=10, max_mana=10)), seed=345), fixture())

    def hero(self, g, p=1): return g.state.entities[g.state.players[p].hero_id]

    def play(self, g, cid, p=1):
        eid = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, eid)); return eid

    def portable(self, g):
        saved = g.snapshot()
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), fixture('reader')).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fixture('reader')).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for name in ('"resolution_frame"', '"cast_history"', '"rng_state"', 'SpellHistoryQuery'):
                self.assertNotIn(name, public)

    def test_complete_bilingual_face_retains_absent_attack_and_real_durability(self):
        d = load_batch(); raw = d['cards'][0]['record']; card = fixture().card(CARD)
        self.assertIsNone(raw['attack']); self.assertNotIn('ATK', raw['tags'])
        self.assertEqual((card.cost, card.attack, card.durability, card.metadata.classes), (3, 0, 3, ('priest',)))
        self.assertEqual(len(d['official_observations']), 2)
        for f in d['official_observations']:
            self.assertIsNone(f['face'].get('attack')); check_face(raw, f['face'], f['locale'])

    def test_native_equipping_does_not_tick_until_owner_end_and_armor_absorbs(self):
        g = self.game((CARD,), armor=4); weapon = self.play(g, CARD)
        self.assertEqual((g.state.players[1].mana, g.state.players[1].fatigue), (7, 0))
        g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).health, self.hero(g).armor), (1, 30, 3))
        self.assertEqual((g.state.players[2].fatigue, g.state.entities[weapon].durability), (0, 3))

    def test_successful_shadow_hand_cast_selects_enemy(self):
        g = self.game((SHADOW,), weapon=CARD); self.play(g, SHADOW); g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].fatigue, g.state.players[2].fatigue), (0, 1))
        self.assertEqual(self.hero(g, 2).health, 29)

    def test_nonshadow_and_unschooled_casts_do_not_qualify(self):
        g = self.game((FIRE, PLAIN), weapon=CARD)
        self.play(g, FIRE); self.play(g, PLAIN); g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].fatigue, g.state.players[2].fatigue), (1, 0))

    def test_cast_before_equipping_still_counts_this_turn(self):
        g = self.game((SHADOW, CARD)); self.play(g, SHADOW); self.play(g, CARD); g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].fatigue, g.state.players[2].fatigue), (0, 1))

    def test_automatic_successful_shadow_counts_without_a_hand_play(self):
        g = self.game((AUTO,), weapon=CARD); self.play(g, AUTO); g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].fatigue, g.state.players[2].fatigue), (0, 1))

    def test_earlier_end_body_cast_is_seen_at_blade_resolution(self):
        g = self.game((CARD,), board=(END,)); self.play(g, CARD); g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].fatigue, g.state.players[2].fatigue), (0, 1))

    def test_old_turn_shadow_is_excluded_and_opponent_end_does_not_tick_blade(self):
        g = self.game((SHADOW,), weapon=CARD); self.play(g, SHADOW); g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].fatigue, g.state.players[2].fatigue), (0, 1))
        g.apply(EndTurn(2))
        self.assertEqual((g.state.players[1].fatigue, g.state.players[2].fatigue), (0, 1))
        g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].fatigue, g.state.players[2].fatigue), (1, 1))

    def test_opponent_shadow_cast_does_not_satisfy_owners_condition(self):
        g = self.game(weapon=CARD, enemy_hand=(SHADOW,)); g.apply(EndTurn(1))
        self.play(g, SHADOW, 2); g.apply(EndTurn(2)); g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].fatigue, g.state.players[2].fatigue), (2, 0))

    def test_actual_fatigue_counter_advances_existing_enemy_account(self):
        g = self.game((TICK, SHADOW), weapon=CARD)
        self.play(g, TICK); self.play(g, SHADOW); g.apply(EndTurn(1))
        self.assertEqual((g.state.players[2].fatigue, self.hero(g, 2).health), (2, 27))
        self.assertEqual([e.amount for e in g.events if e.kind == 'fatigue'], [1, 2])

    def test_fatigue_is_not_spell_damage_and_immunity_does_not_undo_tick(self):
        g = self.game((SHADOW,), board=(POWER,), weapon=CARD, enemy_hero=IMMUNE)
        self.play(g, SHADOW); g.apply(EndTurn(1))
        self.assertEqual((g.state.players[2].fatigue, self.hero(g, 2).health), (1, 30))
        self.assertTrue(any(e.kind == 'damage_prevented' for e in g.events))

    def test_replacing_weapon_removes_future_end_trigger(self):
        g = self.game((SWAP,), weapon=CARD); self.play(g, SWAP); g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].fatigue, g.state.players[2].fatigue), (0, 0))

    def test_tick_wait_restores_and_later_shadow_does_not_redirect_accepted_recipient(self):
        g = self.game(board=(WAIT,), weapon=CARD); g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).health), (1, 30))
        self.portable(g); saved = g.snapshot(); restored = Game.from_snapshot(saved, fixture('reader'))
        with self.assertRaises(ResolutionError):
            restored.apply(SelectChoice(1, restored.state.pending_choice.id, ('fail',)))
        self.assertEqual(restored.snapshot(), saved)
        for game in (g, restored): game.apply(SelectChoice(1, game.state.pending_choice.id, ('shadow',)))
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual((self.hero(g).health, self.hero(g, 2).health), (29, 30))
        self.portable(g)

    def test_failed_end_reaction_rolls_back_turn_tick_and_queued_damage(self):
        g = self.game(board=(FAULT,), weapon=CARD); saved = g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), saved)
