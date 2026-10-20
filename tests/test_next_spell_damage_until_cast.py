"""Real Moonlight lifetimes through an explicit component-installation fixture.

The fixture carrier is not an Elise recipe or production card adapter. These
checks cover the actual 1/2/4 next-spell payoff needed by the later craft source.
"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerEffectSpec, PlayerSetup, ResolutionError, Scenario, SelectChoice,
    SnapshotError, UseLocation, Zone)
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.replay import build_replay, replay
from tools.card_batch import canonical, read
from test_current_deck_empty_basics import rehash
from test_next_spell_damage_window_basics import registry as timed_registry, ARC, BOOST

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / 'data/cards/elise-crafted-locations-v1.json'
PIN = 'eddb7bad2bce4439d799e51dd3dab3788028d38a41437923ecca43b638cb8332'
P = 'fixture.moonlight.'
PARTS = {1: 'TLC_100t12', 2: 'TLC_100t22', 4: 'TLC_100t32'}
KIND = 'next_spell_damage_until_cast'


def registry():
    packet = read(PACKET)
    if canonical(packet) != PIN:
        raise ValueError('Complete Elise component source changed')
    rows = {x['record']['id']: x['record'] for x in packet['choice_only']}
    r = timed_registry()
    for amount, cid in PARTS.items():
        raw = rows[cid]
        r.register_card(CardDefinition(cid, raw['name'], CardType.SPELL,
            choice_only=True, metadata=metadata_from_record(raw)))
        key = P + cid
        r.register_player_effect(PlayerEffectSpec(key, key, kind=KIND, spell_damage=amount))
        r.register_behavior(key, lambda c, key=key: (AddPlayerEffect(c.player_id, key, c.source_id),))
        # Explicit installation fixture; this is not a forged initialized frame.
        r.register_card(CardDefinition(key, 'Moonlight component installation fixture',
            CardType.LOCATION, durability=2, on_use=key))
    def remove(c):
        target = next(i for i in c.state.players[1].board if c.state.entities[i].kind == CardType.LOCATION)
        return (DestroyLocation(target, c.source_id),)
    r.register_behavior(P + 'remove', remove)
    r.register_card(CardDefinition(P + 'remove', 'Nonspell carrier-removal fixture',
        CardType.MINION, health=2, battlecry=P + 'remove'))
    return r


class NextSpellDamageUntilCastTests(unittest.TestCase):
    def game(self, amount=1, hand=('spell', 'spell'), other=()):
        loc = P + PARTS[amount]
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=(loc,), deck=('plain',) * 12, mana=10, max_mana=10),
            PlayerSetup('hero', hand=other, deck=('plain',) * 12, mana=10, max_mana=10)), seed=312), registry())
    def use(self, g):
        eid = next(i for i in g.state.players[1].board if g.state.entities[i].kind == CardType.LOCATION)
        g.apply(UseLocation(1, eid))
        return eid
    def play(self, g, cid):
        player = g.state.active_player
        eid = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, eid))
    def cycle(self, g):
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
    def health(self, g):
        return g.state.entities[g.state.players[2].hero_id].health
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry()).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        return saved
    def test_all_three_real_component_amounts_survive_turns_and_are_claimed_once(self):
        for amount in PARTS:
            with self.subTest(amount=amount):
                g = self.game(amount)
                self.use(g)
                self.cycle(g)
                self.assertEqual(len(g.state.players[1].player_effects), 1)
                self.assertEqual(spell_bonus(g.state, 1, g.registry), 0)
                self.play(g, 'spell')
                cast = g.state.cast_history[-1]
                self.assertLess(cast.spell_damage_effects[0].created_turn, cast.turn)
                self.assertEqual(self.health(g), 79 - amount)
                self.assertFalse(g.state.players[1].player_effects)
                self.play(g, 'spell')
                self.assertEqual(self.health(g), 78 - amount)
        self.portable(g)
    def test_same_turn_timed_and_until_cast_programs_share_one_actual_spell(self):
        g = self.game(hand=(ARC, 'spell'))
        self.use(g)
        self.play(g, ARC)
        self.play(g, 'spell')
        self.assertEqual(self.health(g), 76)
        self.assertEqual(len(g.state.cast_history[-1].spell_damage_effects), 2)
        self.assertFalse(g.state.players[1].player_effects)
    def test_turn_cleanup_expires_original_timed_program_and_keeps_moonlight(self):
        g = self.game(hand=(ARC, 'spell'))
        self.use(g)
        self.play(g, ARC)
        self.cycle(g)
        self.assertEqual([e.spec_id for e in g.state.players[1].player_effects], [P + PARTS[1]])
        self.play(g, 'spell')
        self.assertEqual(self.health(g), 78)
        self.portable(g)
    def test_last_location_durability_keeps_both_already_installed_instances(self):
        g = self.game(amount=2)
        eid = self.use(g)
        self.cycle(g)
        self.cycle(g)
        self.use(g)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].player_effects), 2)
        self.play(g, 'spell')
        self.assertEqual(self.health(g), 75)
        self.portable(g)
    def test_source_removal_and_nondamage_spell_still_consume_exactly_once(self):
        g = self.game(hand=(P + 'remove', 'read', 'spell'))
        self.use(g)
        self.play(g, P + 'remove')
        self.assertEqual(len(g.state.players[1].player_effects), 1)
        self.cycle(g)
        self.play(g, 'read')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1)
        self.play(g, 'spell')
        self.assertEqual(self.health(g), 79)
    def test_opponent_spell_and_failed_automatic_target_do_not_take_own_program(self):
        g = self.game(hand=('failed-auto', 'spell'), other=('spell',))
        self.use(g)
        g.apply(EndTurn(1))
        self.play(g, 'spell')
        self.assertEqual(len(g.state.players[1].player_effects), 1)
        g.apply(EndTurn(2))
        self.play(g, 'failed-auto')
        self.assertEqual(g.state.cast_history[-1].failure, 'no_target')
        self.assertEqual(len(g.state.players[1].player_effects), 1)
        self.play(g, 'spell')
        self.assertFalse(g.state.players[1].player_effects)
    def test_later_automatic_cast_claims_the_same_program(self):
        g = self.game(hand=('auto-source',))
        self.use(g)
        self.cycle(g)
        self.play(g, 'auto-source')
        self.assertEqual(self.health(g), 78)
        self.assertEqual(len(g.state.cast_history[-1].spell_damage_effects), 1)
    def test_waiting_claim_from_earlier_turn_restores_and_failure_keeps_original_boundary(self):
        g = self.game(hand=('waiting',))
        self.use(g)
        self.cycle(g)
        self.play(g, 'waiting')
        saved = self.portable(g)
        with self.assertRaises(ResolutionError):
            g.apply(SelectChoice(1, g.state.pending_choice.id, ('fault',)))
        self.assertEqual(g.snapshot(), saved)
        g.apply(SelectChoice(1, g.state.pending_choice.id, ('hit',)))
        self.assertEqual(self.health(g), 78)
        self.portable(g)
    def test_failed_spell_rolls_back_the_still_pending_older_program(self):
        g = self.game(hand=('fault',))
        self.use(g)
        self.cycle(g)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'fault')
        self.assertEqual(g.snapshot(), saved)
        self.portable(g)
    def test_random_split_budget_uses_claimed_earlier_program_and_restores(self):
        g = self.game(amount=4, hand=('split',))
        self.use(g)
        self.cycle(g)
        self.play(g, 'split')
        self.assertEqual(self.health(g), 75)
        self.portable(g)
    def test_rehashed_old_turn_timed_identity_and_future_claim_are_rejected(self):
        g = self.game()
        self.use(g)
        self.cycle(g)
        self.play(g, 'spell')
        saved = self.portable(g)
        for mutation in ('timed', 'future'):
            bad = deepcopy(saved)
            effect = bad['state']['cast_history'][-1]['spell_damage_effects'][0]
            if mutation == 'timed':
                effect['spec_id'] = BOOST
            else:
                effect['created_turn'] = bad['state']['turn'] + 1
            rehash(bad)
            with self.subTest(mutation=mutation), self.assertRaises((SnapshotError, ValueError)) as error:
                Game.from_snapshot(bad, registry())
            self.assertNotIn('hash', str(error.exception).lower())
    def test_new_lifetime_is_independent_and_public_material_remains_private(self):
        spec = registry().player_effect(P + PARTS[1])
        for changes in ({'spell_damage': 0}, {'duration': 1}, {'tick_event': 'turn_ended'}, {'target_policy': 'spells_no_heroes'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(spec, **changes)
        g = self.game()
        self.use(g)
        self.cycle(g)
        self.play(g, 'spell')
        for player in (1, 2):
            text = json.dumps(g.observe(player))
            for private in ('spell_damage_effects', 'entered_order', 'source_allocation'):
                self.assertNotIn(private, text)


if __name__ == '__main__':
    unittest.main()
