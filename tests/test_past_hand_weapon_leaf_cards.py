"""Actual historical targeting, pure quotes and original equipment consumers."""
from dataclasses import asdict
from functools import lru_cache
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.past_hand_weapon_leaf_cards import SORCERESS, DEFILER, BUCCANEER, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction,
    PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, RequestChoice
from hs_sim.engine.model import CostSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from tools.card_batch import check_face

P = 'fixture.past_hand_weapon.'
SET_ZERO, WATCH = P+'set_zero', P+'watch'
FIRE, PYRO, FEL, HOLY, RAVEN, DAGGER = (
    'CORE_CS2_029', 'EX1_279', 'CORE_BT_035', 'CORE_CS2_004', 'KAR_300', 'CS2_082')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    registry = build_registry()
    registry.register_behavior(SET_ZERO, lambda c: (ModifyStoredCost(
        CardReference.capture(c.state.entities[c.target_id]), CostSpec(set_to=0), c.source_id),))
    registry.register_card(CardDefinition(SET_ZERO, 'Explicit stored cost adjustment', CardType.SPELL,
        on_play=SET_ZERO, targeting=TargetSpec(zones=(Zone.HAND,), kinds=(CardType.SPELL,), relation='friendly')))
    if mode != 'normal':
        def observe(c):
            event = c.event; target = c.state.entities.get(event.target_id)
            source = c.state.entities.get(event.source_id)
            if mode == 'fill' and event.kind == 'minion_summoned' and target is not None and target.card_id == DEFILER:
                return (AddToHand(c.player_id, HOLY, c.source_id),)
            wanted = (mode == 'wait_cost' and event.kind == 'cost_modified' and source is not None and source.card_id == SORCERESS or
                mode == 'wait_copy' and event.kind == 'card_added_to_hand' and source is not None and source.card_id == DEFILER)
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),) if wanted else ()
        body = WATCH+'.'+mode; registry.register_behavior(body, observe)
        registry.register_card(CardDefinition(WATCH, 'Explicit reaction observer', CardType.MINION, health=20,
            triggers=tuple(TriggerSpec(kind, body) for kind in ('minion_summoned', 'cost_modified', 'card_added_to_hand'))))
    registry.validate()
    return registry


class PastHandWeaponLeafTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.readers = {'normal': fixture.__wrapped__()}

    def game(self, hand=(), board=(), *, enemy_hand=(), mode='normal', weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03', hand=hand, board=((WATCH,) if mode != 'normal' else ())+board,
                hero_power_card_id='HERO_03bp', weapon_card_id=weapon, mana=10, max_mana=10),
            PlayerSetup('HERO_03', hand=enemy_hand, hero_power_card_id='HERO_03bp', mana=10, max_mana=10)),
            seed=324), fixture(mode))

    def eid(self, game, cid, *, player=1):
        return next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == cid)

    def play(self, game, cid, *, target=None):
        eid = self.eid(game, cid); game.apply(PlayCard(1, eid, target_id=target)); return eid

    def price(self, game, eid):
        return quote_unselected_cost(game.state, game.registry, game.state.entities[eid]).amount

    def portable(self, game, mode='normal'):
        if mode not in self.readers: self.readers[mode] = fixture.__wrapped__(mode)
        registry = self.readers[mode]; saved = game.snapshot()
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        return Game.from_snapshot(saved, registry)

    def test_three_full_rows_six_primary_faces_and_actual_original_metadata(self):
        data = load_batch(); self.assertEqual(len(data['dependencies']), 3)
        self.assertEqual(len(data['official_observations']), 6)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        rows = {r['record']['id']: r['record'] for r in data['dependencies']}
        for cid, raw in rows.items():
            card = fixture().card(cid)
            self.assertEqual((card.cost, card.attack, card.health), (raw['cost'], raw['attack'], raw['health']))
            self.assertEqual(asdict(card.metadata), asdict(metadata_from_record(raw)))
        for o in data['official_observations']: check_face(rows[o['card_id']], o['face'], o['locale'])

    def test_sorceress_discounts_unique_highest_spell_and_ignores_minion_cost(self):
        game = self.game((SORCERESS, FIRE, PYRO, 'TIME_890'))
        fire, pyro = self.eid(game, FIRE), self.eid(game, PYRO); before = game._rng.getstate()
        self.play(game, SORCERESS)
        self.assertEqual((self.price(game, fire), self.price(game, pyro)), (4, 9))
        self.assertEqual((game.state.players[1].mana, len(game.state.cast_history)), (9, 0))
        self.assertEqual(game._rng.getstate(), before)

    def test_sorceress_compares_current_quotes_instead_of_printed_mana(self):
        game = self.game((SET_ZERO, SORCERESS, PYRO, FIRE))
        pyro, fire = self.eid(game, PYRO), self.eid(game, FIRE)
        self.play(game, SET_ZERO, target=pyro); self.play(game, SORCERESS)
        self.assertEqual((self.price(game, pyro), self.price(game, fire)), (0, 3))

    def test_sorceress_tie_selects_exactly_one_physical_spell_without_a_player_menu(self):
        game = self.game((SORCERESS, FIRE, FIRE))
        originals = [i for i in game.state.players[1].hand if game.state.entities[i].card_id == FIRE]
        before = game._rng.getstate(); self.play(game, SORCERESS)
        self.assertEqual(sorted(self.price(game, i) for i in originals), [3, 4])
        self.assertIsNone(game.state.pending_choice); self.assertNotEqual(game._rng.getstate(), before)

    def test_sorceress_no_spell_keeps_rng_and_other_minions_unchanged(self):
        for other in ((), (RAVEN,)):
            with self.subTest(other=other):
                game = self.game((SORCERESS,)+other); before = game._rng.getstate(); self.play(game, SORCERESS)
                self.assertEqual(game._rng.getstate(), before)
                self.assertEqual(len(game.state.players[1].hand), len(other))

    def test_sorceress_automatic_tie_wait_restores_without_reselecting_or_discounting_twice(self):
        game = self.game((SORCERESS, FIRE, FIRE), mode='wait_cost'); self.play(game, SORCERESS)
        self.assertIsNotNone(game.state.pending_choice); before = game._rng.getstate()
        game = self.portable(game, 'wait_cost')
        q = game.state.pending_choice; game.apply(SelectChoice(q.player_id, q.id, ('continue',)))
        originals = [i for i in game.state.players[1].hand if game.state.entities[i].card_id == FIRE]
        self.assertEqual(sorted(self.price(game, i) for i in originals), [3, 4])
        self.assertEqual(game._rng.getstate(), before); self.portable(game, 'wait_cost')

    def test_defiler_uses_original_fel_arrow_and_copies_current_cost_to_new_identity(self):
        game = self.game((SET_ZERO, DEFILER, FEL)); original = self.eid(game, FEL)
        self.play(game, SET_ZERO, target=original); self.play(game, DEFILER, target=original)
        cards = [game.state.entities[i] for i in game.state.players[1].hand]
        self.assertEqual(len(cards), 2); self.assertTrue(all(e.card_id == FEL for e in cards))
        copied, = [e for e in cards if e.id != original]
        self.assertEqual(copied.origin_entity_id, original)
        self.assertEqual((self.price(game, copied.id), self.price(game, original)), (0, 0))
        self.assertEqual(len(game.state.cast_history), 1)

    def test_defiler_rejects_wrong_school_enemy_or_self_before_payment(self):
        game = self.game((DEFILER, FEL, HOLY), enemy_hand=(FEL,))
        source, fel, holy = (self.eid(game, cid) for cid in (DEFILER, FEL, HOLY))
        legal = [a for a in game.legal_actions() if isinstance(a, PlayCard) and a.entity_id == source]
        self.assertEqual({a.target_id for a in legal}, {fel})
        for target in (holy, source, game.state.players[2].hand[0]):
            saved = game.snapshot()
            with self.assertRaises(IllegalAction): game.apply(PlayCard(1, source, target_id=target))
            self.assertEqual(game.snapshot(), saved)

    def test_defiler_without_a_fel_target_still_plays_its_body(self):
        game = self.game((DEFILER, HOLY)); source = self.play(game, DEFILER)
        self.assertIn(source, game.state.players[1].board)
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].hand], [HOLY])
        self.assertEqual(game.state.players[1].mana, 9)

    def test_defiler_full_hand_reaction_burns_copy_and_preserves_original(self):
        game = self.game((DEFILER, FEL)+(RAVEN,)*8, mode='fill'); original = self.eid(game, FEL)
        self.play(game, DEFILER, target=original)
        self.assertEqual(len(game.state.players[1].hand), 10)
        self.assertIn(original, game.state.players[1].hand)
        copies = [e for e in game.state.entities.values() if e.origin_entity_id == original]
        self.assertEqual(len(copies), 1); self.assertEqual(copies[0].zone, Zone.GRAVEYARD)

    def test_defiler_copy_notification_wait_restores_one_original_delivery(self):
        game = self.game((DEFILER, FEL), mode='wait_copy'); original = self.eid(game, FEL)
        self.play(game, DEFILER, target=original); self.assertIsNotNone(game.state.pending_choice)
        game = self.portable(game, 'wait_copy'); q = game.state.pending_choice
        game.apply(SelectChoice(q.player_id, q.id, ('continue',)))
        self.assertEqual(len(game.state.players[1].hand), 2)
        self.assertEqual(sum(e.origin_entity_id == original for e in game.state.entities.values()), 1)
        self.portable(game, 'wait_copy')

    def test_buccaneers_modify_each_new_equipment_once_through_real_hero_power_and_hand_play(self):
        game = self.game((DAGGER,), (BUCCANEER, BUCCANEER))
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        old = game.state.players[1].weapon_id
        self.assertEqual(game.state.entities[old].attack, 3)
        source = self.play(game, DAGGER); self.assertNotEqual(source, old)
        self.assertEqual(game.state.players[1].weapon_id, source)
        self.assertEqual(game.state.entities[source].attack, 3)
        self.assertEqual(game.state.entities[old].zone, Zone.GRAVEYARD)
        self.portable(game)

    def test_buccaneer_entry_does_not_buff_existing_weapon_or_opponent_equipment(self):
        game = self.game((BUCCANEER,), weapon=DAGGER); weapon = game.state.players[1].weapon_id
        self.play(game, BUCCANEER); self.assertEqual(game.state.entities[weapon].attack, 1)
        game = self.game(board=(BUCCANEER,)); game.apply(EndTurn(1))
        game.apply(UseHeroPower(2, game.state.players[2].hero_power_id))
        self.assertEqual(game.state.entities[game.state.players[2].weapon_id].attack, 1)


if __name__ == '__main__': unittest.main()
