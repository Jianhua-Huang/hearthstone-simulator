"""Real generated spell costs, ordinary health, waits and native Rewind."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.native_generated_cost_heal_cards import MEND, HOLY, POOL_ID, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    Keyword, PlayCard, PlayerSetup, Rarity, Ruleset, Scenario, SelectChoice, SnapshotError,
    SpellSchool, Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, CostSpec, Damage, InvokeBehavior, ModifyCost, RequestChoice
from hs_sim.engine.errors import ResolutionError, ResolutionLimitExceeded
from hs_sim.engine.generated_spell_healing import (ACCEPTED, FINISHED,
    GenerateSpellsAndHeal, decode, validate_boundary)
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import (GenerateFromPool, GenerationContext, PoolCard,
    PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, MoveCard

P = 'k143.'
ZERO, TWO, SEVEN, DARK, UNKNOWN, FILLER = (P+n for n in ('0', '2', '7', 'dark', 'unknown', 'filler'))
MEMBERS = (ZERO, TWO, SEVEN, DARK)
CONTEXT = GenerationContext('k143-complete-explicit-holy-pool', 'experimental')


def registry(mode=None, members=MEMBERS):
    r = build_registry()
    r.register_behavior(P+'noop', lambda c: ())
    for cid, cost, school, cls in ((ZERO, 0, SpellSchool.HOLY, CardClass.PALADIN),
            (TWO, 2, SpellSchool.HOLY, CardClass.PALADIN),
            (SEVEN, 7, SpellSchool.HOLY, CardClass.PRIEST), (DARK, 5, SpellSchool.SHADOW, CardClass.PRIEST)):
        card = CardDefinition(cid, cid, CardType.SPELL, cost=cost, spell_school=school,
            on_play=P+'noop', metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=()))
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    r.register_card(CardDefinition(FILLER, 'Ordinary held card', CardType.MINION, cost=2, attack=2, health=3))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.SPELL, 4,
        CardMetadata(True, (CardClass.PRIEST,), Rarity.COMMON, tribes=()),
        spell_school=SpellSchool.HOLY, battlecry=False, deathrattle=False, choose_one=False))
    r.register_pool(PoolDefinition(POOL_ID, 'k143-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid, 3 if cid == TWO else 1) for cid in members), complete=True))

    def fail(c):
        raise ResolutionError('K143 deliberate continuation failure')

    bodies = {
        'wound': lambda c: (Damage(c.state.players[c.player_id].hero_id, 12, c.source_id),),
        'wound2': lambda c: (Damage(c.state.players[2].hero_id, 12, c.source_id),),
        'auto': lambda c: (CastSpell(2, MEND, source_id=c.source_id),),
        'badcast': lambda c: (GenerateSpellsAndHeal(c.player_id, 999, c.source_id, POOL_ID, HOLY, 2),),
        'budget': lambda c: (GenerateSpellsAndHeal(c.player_id, c.cast.id, c.source_id, POOL_ID, HOLY, 1001),),
        'fail': fail,
    }
    for name, body in bodies.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name))
    r.register_card(CardDefinition(P+'power', 'Damage bonus is not printed spell cost',
        CardType.MINION, health=4, spell_damage=5))
    if mode:
        def eligible(c):
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == MEND and c.event.player_id == c.player_id

        def watch(c):
            if mode == 'full':
                return (AddToHand(c.player_id, FILLER, c.source_id), AddToHand(c.player_id, FILLER, c.source_id))
            if mode == 'fail':
                return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            if mode == 'lethal':
                return (Damage(c.state.players[c.player_id].hero_id, 40, c.source_id),)
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail',
                (InvokeBehavior(P+'fail', c.source_id, c.player_id),))]
            if mode == 'arrival':
                ref = CardReference.capture(c.state.entities[c.event.target_id])
                options.extend((ChoiceOption('edit', 'Change created cost',
                    (ModifyCost(ref.entity_id, CostSpec(set_to=19), c.source_id),)),
                    ChoiceOption('move', 'Transfer original created card',
                        (MoveCard(ref, 3-c.player_id, Zone.HAND, source_id=c.source_id),)),
                    ChoiceOption('random', 'Another ordinary random result',
                        (GenerateFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.SPELL,),
                            collectible=True, spell_schools=(SpellSchool.SHADOW,)), source_id=c.source_id),))))
            return (RequestChoice(c.player_id, tuple(options), c.source_id),)

        r.register_behavior(P+'watch', watch)
        r.register_trigger_condition(P+'eligible', eligible)
        event = 'spell_cast_accepted' if mode == 'full' else 'health_resolved' if mode == 'health' else 'card_created'
        r.register_card(CardDefinition(P+'watch', 'One original effect witness', CardType.WEAPON, durability=5,
            limited_triggers=(LimitedTriggerSpec(event, P+'watch', P+'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared_registry(mode, members):
    return registry(mode, members)


def wires(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from wires(child)
    elif isinstance(value, list):
        for child in value:
            yield from wires(child)


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


def edit_controls(value, action):
    if isinstance(value, dict):
        for child in value.values():
            edit_controls(child, action)
    elif isinstance(value, list):
        for item in list(value):
            if isinstance(item, dict) and item.get('type', '').endswith('.CompleteGeneratedSpellHealing'):
                if action == 'drop':
                    value.remove(item)
                else:
                    value.insert(value.index(item), deepcopy(item))
            else:
                edit_controls(item, action)


class NativeGeneratedCostHealTests(unittest.TestCase):
    def game(self, hand=None, *, mode=None, members=MEMBERS, limit=6, mana=3, board=()):
        self.config = mode, members
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_04', hand=(P+'wound', MEND) if hand is None else hand,
                deck=(FILLER,)*8, board=board, mana=mana, max_mana=10,
                weapon_card_id=P+'watch' if mode else None),
            PlayerSetup('HERO_08', deck=(FILLER,)*8)), seed=143, generation_context=CONTEXT),
            shared_registry(*self.config), Ruleset(max_hand=limit))

    def play(self, g, cid):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, source))
        return source

    def choose(self, g, option):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def begin(self, g):
        self.play(g, P+'wound')
        return self.play(g, MEND)

    def keep(self, g):
        self.assertIsNotNone(g.state.pending_choice)
        self.choose(g, 'keep')

    def hp(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].health

    def results(self, g):
        return [decode(g, e) for e in g.events if e.kind == ACCEPTED]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for actor in (1, 2):
            public = json.dumps(g.for_player(actor).observe())+json.dumps(g.player_events(actor))
            for key in ('rng_before', 'rng_after', 'candidates', 'generation', 'cast_event', 'source_json'):
                self.assertNotIn('"'+key+'"', public)
            self.assertNotIn('CompleteGeneratedSpellHealing', public)
        return other

    def test_complete_source_two_primary_faces_and_actual_holy_rewind_body(self):
        from tools.card_batch import check_face
        d = load_batch(); raw = d['cards'][0]['record']
        self.assertEqual(len(d['official_observations']), 2)
        for o in d['official_observations']:
            check_face(raw, o['face'], o['locale'])
        card = shared_registry(None, MEMBERS).card(MEND)
        self.assertEqual((card.cost, card.kind, card.spell_school), (3, CardType.SPELL, SpellSchool.HOLY))
        self.assertTrue(Keyword.REWIND in card.keywords and card.rewind is not None)
        self.assertFalse(d['formal_pool_complete'] or d['cn_calibrated'])

    def test_real_paid_two_spell_generation_and_one_ordinary_sum_heal_ignore_damage_bonus(self):
        g = self.game(board=(P+'power',)); source = self.begin(g)
        result, = self.results(g)
        self.assertEqual(len(result.selected), 2)
        self.assertEqual(result.candidates, ((ZERO, 1), (TWO, 3), (SEVEN, 1)))
        total = sum(g.registry.card(cid).cost for cid in result.selected)
        self.assertEqual((self.hp(g), g.state.players[1].mana), (min(30, 18+total), 0))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], list(result.selected))
        done, = [e for e in g.events if e.kind == FINISHED]
        self.assertEqual((done.source_id, dict(done.data)['requested_amount']), (source, total))
        self.keep(g); self.portable(g)

    def test_replacement_keeps_two_physical_zero_cost_spells_and_zero_healing(self):
        g = self.game(members=(ZERO,)); source = self.begin(g)
        self.assertEqual(self.results(g)[0].selected, (ZERO, ZERO))
        self.assertEqual(len(set(g.state.players[1].hand)), 2)
        self.assertEqual(self.hp(g), 18)
        done, = [e for e in g.events if e.kind == FINISHED]
        self.assertEqual((done.source_id, dict(done.data)['requested_amount']), (source, 0))
        self.keep(g)

    def test_full_hand_burns_both_actual_results_but_heals_original_costs(self):
        g = self.game(mode='full', members=(SEVEN,), limit=2); source = self.begin(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [FILLER, FILLER])
        self.assertEqual(sum(e.kind == 'card_burned' and e.source_id == source for e in g.events), 2)
        self.assertEqual((self.hp(g), dict(next(e for e in g.events if e.kind == FINISHED).data)['requested_amount']), (30, 14))
        self.keep(g); self.portable(g)

    def test_empty_eligible_pool_keeps_full_empty_receipt_without_rng(self):
        g = self.game(members=(DARK,)); self.play(g, P+'wound'); before = g.snapshot()['rng_state']
        self.play(g, MEND); result, = self.results(g)
        self.assertEqual((result.candidates, result.selected, result.rng_before), ((), (), result.rng_after))
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual((len(g.state.players[1].hand), self.hp(g)), (0, 18))
        self.keep(g)

    def test_unknown_eligible_content_rejects_before_rng_including_full_hand(self):
        for mode in (None, 'full'):
            with self.subTest(mode=mode):
                g = self.game(mode=mode, members=(TWO, UNKNOWN), limit=2)
                self.play(g, P+'wound'); saved = g.snapshot(); calls = []
                def fail(*args, **kwargs):
                    calls.append(args)
                    raise AssertionError('Unknown eligible spell reached RNG')
                with patch.object(random.Random, 'randrange', fail), self.assertRaises(ResolutionError):
                    self.play(g, MEND)
                self.assertFalse(calls)
                self.assertEqual(g.snapshot(), saved)

    def test_acquisition_wait_keeps_original_costs_after_price_transfer_or_later_rng(self):
        for option in ('edit', 'move', 'random'):
            with self.subTest(option=option):
                g = self.game(mode='arrival', members=(TWO, DARK)); self.begin(g)
                self.assertEqual(self.hp(g), 18)
                first = g.state.players[1].hand[0]
                self.portable(g); saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'deliberate'):
                    self.choose(g, 'bad')
                self.assertEqual(g.snapshot(), saved)
                self.choose(g, option)
                self.assertEqual(self.hp(g), 22)
                self.assertEqual(dict(next(e for e in g.events if e.kind == FINISHED).data)['requested_amount'], 4)
                if option == 'edit':
                    self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[first]).amount, 19)
                if option == 'move':
                    self.assertTrue(first in g.state.players[2].hand)
                if option == 'random':
                    self.assertTrue(any(g.state.entities[i].card_id == DARK for i in g.state.players[1].hand))
                self.keep(g); self.portable(g)

    def test_healing_wait_restores_and_never_executes_its_generated_result_twice(self):
        g = self.game(mode='health', members=(TWO,)); self.begin(g)
        self.assertEqual(self.hp(g), 22)
        self.assertEqual(sum(e.kind == FINISHED for e in g.events), 1)
        self.portable(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, 'ok'); self.keep(g)
        self.assertEqual((self.hp(g), sum(e.kind == FINISHED for e in g.events)), (22, 1))

    def test_two_actual_paid_casts_have_distinct_original_draw_and_completion_roots(self):
        g = self.game((P+'wound', MEND, MEND), members=(TWO,), mana=6)
        self.play(g, P+'wound'); self.play(g, MEND); self.keep(g)
        self.play(g, MEND); self.keep(g)
        roots = self.results(g)
        self.assertEqual(len({r.event_sequence for r in roots}), 2)
        self.assertEqual(len({r.request.cast_id for r in roots}), 2)
        self.assertEqual((self.hp(g), g.state.players[1].mana, len(g.state.players[1].hand)), (26, 0, 4))
        self.portable(g)

    def test_actual_rewind_restores_cards_and_health_but_retains_old_complete_receipts(self):
        g = self.game(members=(TWO,)); self.begin(g)
        previous = set(g.state.players[1].hand)
        self.assertEqual(self.hp(g), 22)
        self.choose(g, 'retry')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual((self.hp(g), g.state.players[1].mana, len(g.state.players[1].hand)), (22, 0, 2))
        self.assertFalse(previous & set(g.state.players[1].hand))
        self.assertEqual(sum(e.kind == ACCEPTED for e in g.events), 2)
        self.assertEqual(sum(e.kind == FINISHED for e in g.events), 2)
        self.portable(g)

    def test_other_player_automatic_cast_keeps_actual_recipient_source_and_hero(self):
        g = self.game((P+'wound2', P+'auto'), members=(TWO,))
        self.play(g, P+'wound2'); self.play(g, P+'auto')
        self.assertIsNone(g.state.pending_choice)
        root, = self.results(g)
        self.assertEqual((root.request.player_id, root.source.controller), (2, 2))
        self.assertEqual((self.hp(g, 1), self.hp(g, 2)), (30, 22))
        self.assertEqual((len(g.state.players[1].hand), len(g.state.players[2].hand)), (0, 2))
        self.portable(g)

    def test_acquisition_failure_rolls_back_payment_all_cards_rng_and_receipts(self):
        g = self.game(mode='fail'); self.play(g, P+'wound'); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.play(g, MEND)
        self.assertEqual(g.snapshot(), saved)

    def test_real_terminal_during_delivery_interrupts_original_cast_without_healing(self):
        g = self.game(mode='lethal', members=(TWO,)); source = self.begin(g)
        self.assertEqual(g.state.winner, 2)
        self.assertEqual(sum(e.kind == FINISHED for e in g.events), 0)
        self.assertEqual(sum(e.kind == 'card_created' and e.source_id == source for e in g.events), 1)
        self.assertTrue(g.state.cast_history[-1].interrupted)
        self.portable(g)

    def test_rehashed_queue_result_rng_and_choice_injection_are_rejected(self):
        g = self.game(mode='arrival', members=(TWO,)); self.begin(g); original = g.snapshot()
        for action in ('drop', 'duplicate', 'selected', 'count', 'rng', 'event', 'choice'):
            with self.subTest(action=action):
                saved = deepcopy(original)
                if action in ('drop', 'duplicate'):
                    edit_controls(saved['resolution_frame'], action)
                else:
                    controls = [x for x in wires(saved['resolution_frame']) if x.get('type', '').endswith('.CompleteGeneratedSpellHealing')]
                    self.assertTrue(controls)
                    if action == 'choice':
                        option = next(x for x in wires(saved['resolution_frame']) if x.get('type', '').endswith('.ChoiceOption'))
                        option['fields']['effects']['tuple'].append(deepcopy(controls[0]))
                    for row in controls:
                        if action == 'selected': row['fields']['selected'] = {'tuple': [SEVEN, SEVEN]}
                        if action == 'count': row['fields']['request']['fields']['count'] = 3
                        if action == 'rng': row['fields']['rng_after'] = deepcopy(row['fields']['rng_before'])
                        if action == 'event': row['fields']['event_sequence'] += 1
                with self.assertRaises((SnapshotError, ValueError)):
                    Game.from_snapshot(rehash(saved), registry(*self.config))

    def test_completion_health_binding_missing_receipt_old_schema_and_request_limits(self):
        g = self.game(mode='health', members=(TWO,)); self.begin(g)
        view = SimpleNamespace(_events=tuple(e for e in g.events if e.kind != FINISHED),
            _frame=g._frame, _state=g._state, registry=g.registry, _generation_context=g._generation_context,
            mechanics=g.mechanics)
        with self.assertRaisesRegex(ValueError, 'owed completion'):
            validate_boundary(view)
        saved = g.snapshot(); saved['schema_version'] = 350
        with self.assertRaises((SnapshotError, ValueError)):
            Game.from_snapshot(saved, registry(*self.config))
        request = GenerateSpellsAndHeal(1, 1, 1, POOL_ID, HOLY, 2)
        for changes in (dict(count=0), dict(query=PoolQuery(kinds=(CardType.MINION,), collectible=True))):
            with self.assertRaises(ValueError): replace(request, **changes)
        for cid, error in ((P+'badcast', ResolutionError), (P+'budget', ResolutionLimitExceeded)):
            other = self.game((P+'wound', cid)); self.play(other, P+'wound'); before = other.snapshot()
            with self.assertRaises(error): self.play(other, cid)
            self.assertEqual(other.snapshot(), before)

    def test_completion_receipt_rejects_equal_float_or_bool_integers(self):
        g = self.game(mode='health', members=(ZERO,)); self.begin(g)
        original, = (e for e in g.events if e.kind == FINISHED)
        data = dict(original.data)
        changes = [(key, float(value)) for key, value in data.items()]
        changes.append(('requested_amount', False))
        for key, value in changes:
            with self.subTest(field=key, value_type=type(value).__name__):
                edited = replace(original, data=tuple({**data, key: value}.items()))
                view = SimpleNamespace(_events=tuple(edited if e == original else e for e in g.events),
                    _frame=g._frame, _state=g._state, registry=g.registry,
                    _generation_context=g._generation_context, mechanics=g.mechanics)
                with self.assertRaises(ValueError):
                    validate_boundary(view)


if __name__ == '__main__':
    unittest.main()
