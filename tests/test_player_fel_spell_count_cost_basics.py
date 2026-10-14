"""A real single-school count price reuses the original cast prefix and payment."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, EndTurn,
    Game, PlayerSetup, PlayerSpellCountCostSpec, PlayCard, Rarity, ResolutionError,
    Scenario, SelectChoice, SnapshotError, SpellSchool, TriggerSpec)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact,
    capture_quote_fact)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.intrinsic_costs import (validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell, cast_spells
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
import test_player_spell_school_cost_basics as schools
import test_player_spell_count_cost_basics as roots

NATIVE = 'CATA_529'
PROFILE = 'cost.player-fel-spell-count-v1'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/player-fel-spell-count-cost-basics.json'
PIN = 'f760e6162a1f12215e8346850060cfb0be3d13c80bb6ca1eb199fe68bb393cf2'


def evidence():
    value = json.loads(SUPPORT.read_bytes())
    if canonical_digest(value) != PIN:
        raise ValueError('Single-school complete evidence changed')
    row = value['records'][0]
    if row['id'] != NATIVE or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Single-school original raw changed')
    return row['data']


def registry(*, committed_wait=False):
    r = schools.registry()
    raw = evidence()
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        metadata=metadata(CardClass.DEMON_HUNTER, tribes=('NAGA',), rarity=Rarity.RARE),
        player_spell_count_cost=PlayerSpellCountCostSpec(PROFILE)))
    r.register_card(CardDefinition('fel.second', 'Another original Fel face', CardType.SPELL,
        spell_school=SpellSchool.FEL, on_play='count.noop', metadata=metadata()))
    r.register_behavior('fel.refill', lambda c: (AddToHand(c.player_id, 'fel.refill'),))
    r.register_card(CardDefinition('fel.refill', 'Same-face physical Fel roots', CardType.SPELL,
        spell_school=SpellSchool.FEL, on_play='fel.refill', metadata=metadata()))
    scripts = {
        'fel.acquire': lambda c: (AddToHand(c.player_id, NATIVE),),
        'fel.auto': lambda c: (CastSpell(c.player_id, 'schools.fel', c.source_id),),
        'fel.external': lambda c: (AddCostModifier(c.player_id,
            CostSpec(delta=-2, card_ids=(NATIVE,))),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=2,
            battlecry=cid, metadata=metadata()))
    r.register_behavior('fel.fail', lambda c: (AddToHand(c.player_id, 'schools.fel'),
        AddToHand(c.player_id, 'missing.fel.price.fixture')))

    def pause(c):
        if c.state.entities[c.event.source_id].card_id != NATIVE:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue original payment'),
            ChoiceOption('fault', 'Rollback delayed failure',
                (InvokeBehavior('fel.fail', c.source_id, c.player_id),)),
        ), c.source_id),)

    if committed_wait:
        r.register_behavior('fel.watch', pause)
        r.register_card(CardDefinition('fel.watch', 'Payment waiting fixture', CardType.MINION,
            health=3, triggers=(TriggerSpec('card_committed', 'fel.watch'),), metadata=metadata()))
    return r


class PlayerFelSpellCountCostTests(unittest.TestCase):
    def setUp(self):
        self.options = {}

    def game(self, hand=(NATIVE,), *, enemy_hand=(), board=(), enemy_board=(), mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=('card.1',) * 4,
                mana=mana, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board,
                deck=('card.4',) * 4, mana=10, max_mana=10)), seed=59), registry(**self.options))

    def source(self, g, cid=NATIVE, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand
                    if g.state.entities[eid].card_id == cid)

    def fact(self, g, cid=NATIVE, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))

    def play(self, g, cid=NATIVE):
        player = g.state.active_player
        eid = self.source(g, cid, player).id
        g.apply(PlayCard(player, eid))
        return eid

    def choose(self, g, option='continue'):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry(**self.options))
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(**self.options)).snapshot(), saved)
        for player in (1, 2):
            self.assertEqual(restored.observe(player), g.observe(player))
        return restored

    def two_fel(self, **kwargs):
        g = self.game((NATIVE, 'schools.fel', 'fel.second', *kwargs.pop('extras', ())), **kwargs)
        self.play(g, 'schools.fel')
        self.play(g, 'fel.second')
        return g

    def test_native_full_raw_face_and_finite_profile(self):
        raw = evidence()
        original = next(row for row in json.loads((SUPPORT.parents[1] / 'extracted/cards.json').read_bytes())
                        if row['id'] == NATIVE)
        self.assertEqual(raw, original)
        g = self.game()
        d = g.registry.card(NATIVE)
        self.assertEqual((d.cost, d.attack, d.health, d.metadata.classes,
            d.metadata.tribes, d.metadata.rarity),
            (6, 5, 5, (CardClass.DEMON_HUNTER,), ('NAGA',), Rarity.RARE))
        self.assertIsNone(d.battlecry)
        self.assertIsNone(d.deathrattle)
        self.assertEqual(self.fact(g).amount, 6)
        self.portable(g)

    def test_same_school_counts_each_physical_root_not_distinct_schools(self):
        g = self.two_fel(extras=(roots.ARCANE, schools.WISDOM))
        self.assertEqual((self.fact(g).amount, self.fact(g, roots.ARCANE).amount,
            self.fact(g, schools.WISDOM).amount), (4, 10, 4))
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.quantity, len(f.rows)), (2, 2))
        self.assertNotEqual(f.rows[0].source_id, f.rows[1].source_id)

    def test_other_and_unschooled_spells_are_preserved_without_discount(self):
        g = self.game((NATIVE, 'schools.fire', 'schools.none', 'schools.fel'))
        for cid in ('schools.fire', 'schools.none', 'schools.fel'):
            self.play(g, cid)
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.quantity, f.after, len(f.rows)), (1, 5, 3))
        self.assertEqual(tuple(row.spell_school for row in f.rows),
            (SpellSchool.FIRE, None, SpellSchool.FEL))
        self.portable(g)

    def test_actual_payer_and_turns_use_original_personal_roots(self):
        g = self.game((NATIVE, 'schools.fel'), enemy_hand=(NATIVE, 'schools.fel'))
        self.play(g, 'schools.fel')
        g.apply(EndTurn(1))
        self.play(g, 'schools.fel')
        g.apply(EndTurn(2))
        self.assertEqual((self.fact(g).amount, self.fact(g, player=2).amount), (5, 5))
        self.portable(g)

    def test_casts_before_card_acquisition_need_no_held_progress(self):
        g = self.game(('schools.fel', 'fel.second', 'fel.acquire'))
        for cid in ('schools.fel', 'fel.second', 'fel.acquire'):
            self.play(g, cid)
        self.assertEqual(self.fact(g).amount, 4)
        self.assertEqual(self.source(g).abilities, [])
        self.portable(g)

    def test_countered_and_automatic_rows_do_not_gain_personal_credit(self):
        g = self.game((NATIVE, 'schools.fel', 'fel.auto'), enemy_board=('count.counter',))
        self.play(g, 'schools.fel')
        self.play(g, 'fel.auto')
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.quantity, f.after, len(f.rows)), (0, 6, 2))
        self.assertEqual((f.rows[0].failure, f.rows[1].origin), ('countered', 'effect'))
        self.portable(g)

    def test_accepted_waiting_manual_root_counts_before_completion(self):
        g = self.game((NATIVE, 'schools.wait'))
        self.play(g, 'schools.wait')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(cast_spells(g.state, 1, successful=True)), 0)
        self.assertEqual(self.fact(g).amount, 5)
        restored = self.portable(g)
        for current in (g, restored):
            self.choose(current)
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_repeated_physical_fel_roots_reach_zero_floor(self):
        g = self.game((NATIVE, 'fel.refill'))
        for _ in range(7):
            self.play(g, 'fel.refill')
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.quantity, f.before, f.after), (7, 6, 0))
        self.play(g)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (0, 10))
        self.portable(g)

    def test_generated_and_physical_queries_are_pure_and_share_price(self):
        g = self.two_fel()
        before = g.snapshot()
        generated = capture_generated_quote_fact(g.state, g.registry, 1, NATIVE)
        self.assertEqual((generated.amount, generated.intrinsic.player_spells),
            (4, self.fact(g).intrinsic.player_spells))
        g.legal_actions()
        self.assertEqual(g.snapshot(), before)

    def test_external_cost_layer_and_payment_use_the_same_intrinsic_count(self):
        g = self.two_fel(extras=('fel.external',))
        self.play(g, 'fel.external')
        f = self.fact(g)
        self.assertEqual((f.intrinsic.amount, f.amount), (4, 2))
        self.play(g)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (2, 8))
        self.portable(g)

    def test_waiting_payment_keeps_frozen_prefix_after_later_personal_cast(self):
        self.options = dict(committed_wait=True)
        g = self.two_fel(extras=('schools.fel',), board=('fel.watch',))
        self.play(g)
        stage = g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertEqual((stage.player_spells.quantity, g.state.players[1].mana), (2, 6))
        restored = self.portable(g)
        for current in (g, restored):
            self.choose(current)
            self.play(current, 'schools.fel')
            validate_intrinsic_history_prefix(stage, current.state, current.registry)
            self.assertEqual(capture_generated_quote_fact(current.state, current.registry, 1, NATIVE).amount, 3)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.play_history[2].cost, 4)
        self.portable(g)

    def test_failed_waiting_choice_rolls_back_original_private_state(self):
        self.options = dict(committed_wait=True)
        g = self.two_fel(board=('fel.watch',))
        self.play(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_original_face_school_cannot_be_rewritten_even_with_same_amount(self):
        g = self.game((NATIVE, 'schools.fire'))
        self.play(g, 'schools.fire')
        stage = self.fact(g).intrinsic
        row = replace(stage.player_spells.rows[0], spell_school=SpellSchool.FROST)
        forged = replace(stage, player_spells=replace(stage.player_spells, rows=(row,)))
        with self.assertRaises(ValueError):
            validate_intrinsic_stage_fact(g.registry, forged)
        with self.assertRaises(ValueError):
            validate_intrinsic_origin(forged, g.state, g.registry)

    def test_excluded_unknown_original_face_is_not_hidden_by_zero_count(self):
        g = self.game((NATIVE, 'schools.fire'))
        self.play(g, 'schools.fire')
        stage = self.fact(g).intrinsic
        forged = replace(stage, player_spells=replace(stage.player_spells,
            rows=(replace(stage.player_spells.rows[0], card_id='missing.excluded.school'),)))
        with self.assertRaises(UnsupportedDefinitionError):
            validate_intrinsic_stage_fact(g.registry, forged)

    def test_saved_prefix_rejects_wrong_school_and_borrowed_finite_profile(self):
        g = self.two_fel()
        self.play(g)
        saved = g.snapshot()
        for edit in ('school', 'profile'):
            bad = deepcopy(saved)
            fact = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['player_spells']
            if edit == 'school':
                fact['rows'][0]['spell_school'] = 'fire'
            else:
                fact['spec']['profile_id'] = 'cost.player-spell-count-v1'
            with self.subTest(edit=edit), self.assertRaises(SnapshotError):
                Game.from_snapshot(roots.rehash(bad), registry())

    def test_existing_typed_fact_roundtrip_rejects_untyped_school(self):
        g = self.two_fel()
        stage = self.fact(g).intrinsic
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state, origin_events=g.events)
        self.assertEqual(codec.decode(codec.encode(stage)), stage)
        row = deepcopy(stage.player_spells.rows[0])
        object.__setattr__(row, 'spell_school', 'fel')
        with self.assertRaises((ValueError, TypeError, SnapshotError)):
            codec.decode(codec.encode(row))

    def test_player_prices_keep_opponent_face_and_complete_prefix_private(self):
        g = self.two_fel(enemy_hand=(NATIVE, 'schools.fire'))
        view = g.observe(1)
        self.assertEqual(view['players'][0]['hand'][0]['cost']['amount'], 4)
        self.assertTrue(all(row['card_id'] is None and row.get('cost') is None
            for row in view['players'][1]['hand']))
        for key in ('player_spells', 'cast_history', 'submitted_cost', 'cast_history_length', 'next_entity_id'):
            self.assertNotIn(key, json.dumps(view))
        self.portable(g)

    def test_wrong_carrier_and_unreviewed_school_profile_are_explicitly_rejected(self):
        r = registry()
        for d in (replace(r.card(NATIVE), id='bad.fel.spell', kind=CardType.SPELL, health=0),
                  replace(r.card(NATIVE), id='bad.fel.weapon', kind=CardType.WEAPON)):
            with self.subTest(card=d.id), self.assertRaises(ValueError):
                r.register_card(d)
        for profile in ('cost.player-fire-spell-count-v1', 'all.schools', True, None):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                PlayerSpellCountCostSpec(profile)
