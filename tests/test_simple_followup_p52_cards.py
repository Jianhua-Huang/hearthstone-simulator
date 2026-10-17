"""Native grouped execution, original materials and three actual public gaps."""
from dataclasses import asdict
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p52_cards import (
    VULCANOS, EXECUTIONER, RAT, HELLRAISER, CROOK, TRAVELER, SHADOW, CYCLE,
    ENVOY, SUPPLICANT, MEND, ROOTS, DEPENDENCIES, EXISTING, SKIPPED, POOL_ID,
    load_batch, register_simple_followup_p52_cards)
from hs_sim.engine import (BoardPresenceReference, CardClass, CardDefinition, CardMetadata,
    CardType, CostSpec, EndTurn, Game, IllegalAction, Keyword, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SpellSchool, TargetSpec, UseHandAction, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.cross_zone import TransformPoolTarget
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, GainArmor,
    InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import (GenerateFromPool, GenerationContext, GenerationPolicy,
    PoolCard, PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_attack_groups import AttackSummonedGroup
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST = 'p52.test.'
YETI = 'CORE_CS2_182'
FIRE = 'CORE_CS2_029'
PLUMES = EXISTING
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CONTEXT = GenerationContext('p52-complete-explicit-fixture', 'experimental')
M0, M2, M4, OFF2, HOLY3 = (TEST + name for name in ('minion0', 'minion2', 'minion4', 'druid2', 'holy3'))
MEMBERS = (M0, M2, M4, FIRE, OFF2, HOLY3)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS + DEPENDENCIES)
    if not any(present):
        register_simple_followup_p52_cards(r)
    elif not all(present):
        raise AssertionError('P52 assembly must contain its complete accepted roots and token')
    register_candidate_pool_metadata(r)
    r.validate()
    return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    for cid, cost in ((M0, 0), (M2, 2), (M4, 4)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=2, health=6,
            metadata=CardMetadata(True, (CardClass.NEUTRAL,), None, tribes=())))
    for cid, cost, card_class, school in ((OFF2, 2, CardClass.DRUID, SpellSchool.NATURE),
                                          (HOLY3, 3, CardClass.PRIEST, SpellSchool.HOLY)):
        r.register_behavior(cid, lambda c: (GainArmor(c.player_id, 2),))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=cid,
            metadata=CardMetadata(True, (card_class,), None, tribes=()), spell_school=school))
    scripts = dict(
        kill=lambda c: (Destroy(c.target_id, c.source_id),),
        hit=lambda c: (Damage(c.target_id, 1, c.source_id),),
        silence=lambda c: (Silence(c.target_id),),
        discount=lambda c: (ModifyCost(c.target_id, CostSpec(delta=-2), c.source_id),),
        deck_discount=lambda c: tuple(ModifyCost(i, CostSpec(delta=-1), c.source_id)
            for i in c.state.players[1].deck if c.state.entities[i].kind == CardType.SPELL),
        cast=lambda c: (CastSpell(c.player_id, OFF2, c.source_id),),
        burn_full=lambda c: (AddToHand(1, YETI, c.source_id),),
        reenter=lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),
            c.state.entities[c.target_id].controller, cause=SummonCause.capture(c)),),
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P52 deliberate continuation failure')))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=TEST + name,
            metadata=META, **({'targeting': TargetSpec(zones=(Zone.HAND,) if name == 'discount' else (Zone.BOARD,),
                kinds=(CardType.SPELL, CardType.MINION))} if name in ('kill', 'hit', 'silence', 'discount') else {})))
    r.register_card(CardDefinition(TEST + 'dormant', 'Physical dormant occupant', CardType.MINION,
        attack=1, health=9, dormant_turns=2, metadata=META))

    def transform_gap(c):
        target = CardReference.capture(c.state.entities[c.state.players[1].deck[0]])
        return (TransformPoolTarget(target, POOL_ID, PoolQuery(collectible=True, class_mode='specified',
            classes=(CardClass.DRUID,)),
            GenerationPolicy(), c.player_id, source_card_id=c.source.card_id, source_id=c.source_id),)

    def traveler_gap(c):
        target = BoardPresenceReference.capture(c.state, c.state.players[2].board[0])
        return (SummonByCard(c.player_id, (SummonEntryMaterial(SHADOW),), SummonCause.capture(c)),
                AttackSummonedGroup(c, target))

    def missing_generated_result(c):
        received = tuple(c.state.entities[i].card_id for i in c.state.players[c.player_id].hand)
        if received != (HOLY3, HOLY3):
            raise AssertionError('Generation probe did not actually deliver its two original Holy cards')
        if c.choice is None and c.event is None and c.physical is None:
            raise ResolutionError('P52 two Holy cards delivered but no bound original generation result')
        raise AssertionError('Public generation acquired a result callback; revisit the deferred root')

    gaps = {'transform_gap': transform_gap, 'traveler_gap': traveler_gap,
        'generated_gap': lambda c: (GenerateFromPool(c.player_id, POOL_ID,
            PoolQuery(kinds=(CardType.SPELL,), collectible=True, spell_schools=(SpellSchool.HOLY,)),
            count=2, source_id=c.source_id), InvokeBehavior(TEST + 'missing_result', c.source_id, c.player_id)),
        'missing_result': missing_generated_result}
    for name, callback in gaps.items():
        r.register_behavior(TEST + name, callback)
    for name in ('transform_gap', 'generated_gap'):
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, metadata=META, on_play=TEST + name))
    r.register_card(CardDefinition(TEST + 'traveler_gap', 'Dead minion summon continuation probe',
        CardType.MINION, attack=4, health=1, metadata=META, deathrattle=TEST + 'traveler_gap'))
    for cid in members:
        if cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p52-complete-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        def eligible(c):
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == {'adjacent': EXECUTIONER, 'mana': CROOK, 'copy': RAT}[mode]

        def watch(c):
            options = [ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode == 'adjacent':
                target = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == YETI)
                options.append(ChoiceOption('reenter', 'Return and reenter original target',
                    (ReturnToHand(target), InvokeBehavior(TEST + 'reenter', c.source_id, 1, target))))
            return (RequestChoice(1, tuple(options), c.source_id),)

        event = {'adjacent': 'choice_skipped', 'mana': 'mana_consumption_resolved', 'copy': 'card_added_to_deck'}[mode]
        r.register_behavior(TEST + 'watch', watch)
        r.register_trigger_condition(TEST + 'eligible', eligible)
        r.register_card(CardDefinition(TEST + 'watch', 'Native continuation witness', CardType.WEAPON,
            durability=5, metadata=META, limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch',
                condition_id=TEST + 'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared_registry(mode, members):
    return registry(mode, members)


class SimpleFollowupP52Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(YETI,) * 6, mode=None,
             members=MEMBERS, mana=30):
        self.config = (mode, members)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=deck, mana=mana, max_mana=30, mana_cap=30,
            weapon_card_id=TEST + 'watch' if mode else None),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,) * 6, mana=30,
                max_mana=30, mana_cap=30)), seed=5252, generation_context=CONTEXT), shared_registry(*self.config))

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone)
                    if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, side=None, position=None):
        e = self.first(g, cid)
        dest = 1 if side is None else side
        if e.kind == CardType.MINION and position is None:
            position = len(g.state.players[dest].board)
        g.apply(PlayCard(1, e.id, target, position=position, board_player_id=side))
        return e.id

    def choose(self, g, key='ok'):
        g.apply(SelectChoice(1, g.state.pending_choice.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(
                g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'behavior_id', 'source_json', 'mana_result'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_complete_thirteen_rows_twenty_six_faces_six_explicit_links_and_printed_keywords(self):
        from tools.card_batch import check_face
        data, r = load_batch(), batch_registry()
        rows = {x['record']['id']: x for key in ('cards', 'dependencies', 'existing_dependencies', 'skipped') for x in data[key]}
        self.assertEqual(len(rows), 13)
        self.assertEqual(len(data['official_observations']), 26)
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['official_observations']}
        for o in data['official_observations']:
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
            self.assertEqual(o['response_sha256'], o['observation']['sha256'])
        self.assertEqual(len(data['exact_parent_child_links']), 6)
        for link in data['exact_parent_child_links']:
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
        for cid in ROOTS + DEPENDENCIES:
            raw = rows[cid]['record']
            card = r.card(cid)
            self.assertEqual((card.cost, card.attack, card.health, card.metadata),
                (raw['cost'], raw['attack'] or 0, raw['health'] or 0, metadata_from_record(raw)))
        self.assertEqual(r.card(HELLRAISER).keywords, (Keyword.TAUNT,))
        self.assertTrue(r.card(EXECUTIONER).disguised)
        self.assertEqual(r.card(CROOK).hand_actions[0].kind, 'prepare')
        self.assertEqual((r.card(SHADOW).attack, r.card(SHADOW).health), (4, 1))
        self.assertEqual(tuple(rows[cid]['record']['id'] for cid in SKIPPED), SKIPPED)
        self.assertTrue(all(cid not in r.cards for cid in SKIPPED))

    def test_only_eight_new_definitions_preserve_complete_old_cards_pool_metadata_families_and_default(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS + DEPENDENCIES) - set(before.cards))
        for cid, card in before.cards.items():
            self.assertEqual(after.card(cid), card)
        for cid, card in before.pool_cards.items():
            self.assertEqual(after.pool_cards[cid], card)
        self.assertEqual(dict(before.pools), dict(after.pools))
        self.assertEqual(dict(before.generation_families), dict(after.generation_families))
        for cid, pin in load_batch()['existing_dependency_definition_pins'].items():
            self.assertEqual(canonical_digest(asdict(after.card(cid))), pin)
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(), DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_vulcanos_native_colossal_actual_limbs_and_owner_end_batch_excludes_only_body(self):
        g = self.game((VULCANOS,), enemy=(YETI,))
        body = self.play(g, VULCANOS)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [PLUMES[0], VULCANOS, PLUMES[1]])
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[body].health, 8)
        for cid in PLUMES:
            self.assertEqual(self.first(g, cid, 'board').health, 2)
        self.assertEqual(self.first(g, YETI, 'board', 2).health, 2)
        self.assertEqual(len(g.state.players[1].hand), 2)
        self.assertTrue(all(g.state.entities[i].card_id == FIRE for i in g.state.players[1].hand))
        self.portable(g)

    def test_vulcanos_partial_capacity_and_silence_use_existing_colossal_and_trigger_lifecycle(self):
        g = self.game((VULCANOS, TEST + 'silence'), board=(YETI,) * 5)
        body = self.play(g, VULCANOS)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(sum(g.state.entities[i].card_id in PLUMES for i in g.state.players[1].board), 1)
        self.play(g, TEST + 'silence', body)
        before = [(i, g.state.entities[i].health) for i in g.state.players[1].board]
        g.apply(EndTurn(1))
        self.assertEqual([(i, g.state.entities[i].health) for i in g.state.players[1].board], before)

    def test_executioner_uses_actual_destination_neighbors_payer_and_native_disguised_entry(self):
        for side in (1, 2):
            with self.subTest(side=side):
                g = self.game((EXECUTIONER,), board=(YETI,) if side == 1 else (), enemy=(YETI,) if side == 2 else ())
                target = self.first(g, YETI, 'board', side).id
                source = self.play(g, EXECUTIONER, side=side, position=0)
                self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
                self.assertEqual(g.state.entities[source].controller, side)
                self.assertEqual(g.state.players[1].mana, 27)
                self.assertEqual(g.state.players[2].mana, 30)
        g = self.game((EXECUTIONER,))
        rng = g._rng.getstate()
        self.play(g, EXECUTIONER)
        self.assertEqual(g._rng.getstate(), rng)

    def test_executioner_original_neighbor_wait_restore_replay_failure_and_same_id_reentry(self):
        g = self.game((EXECUTIONER,), board=(YETI,), mode='adjacent')
        target = self.first(g, YETI, 'board')
        self.play(g, EXECUTIONER)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game, 'reenter')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[target.id].zone, Zone.BOARD)
        self.assertNotEqual(g.state.entities[target.id].board_presence_id, target.board_presence_id)

    def test_rat_copies_every_original_physical_spell_once_current_material_and_one_shuffle_fact(self):
        g = self.game((TEST + 'deck_discount', RAT), deck=(FIRE, FIRE, YETI, OFF2))
        self.play(g, TEST + 'deck_discount')
        originals = tuple(g.state.players[1].deck)
        source = self.play(g, RAT)
        copies = [g.state.entities[e.target_id] for e in g.events if e.kind == 'card_created' and e.source_id == source]
        self.assertEqual(sorted(e.card_id for e in copies), sorted((FIRE, FIRE, OFF2)))
        self.assertEqual({e.origin_entity_id for e in copies}, {i for i in originals if g.state.entities[i].kind == CardType.SPELL})
        for copy in copies:
            original = g.state.entities[copy.origin_entity_id]
            self.assertEqual(quote_unselected_cost(g.state, g.registry, copy).amount,
                quote_unselected_cost(g.state, g.registry, original).amount)
            self.assertEqual(quote_unselected_cost(g.state, g.registry, copy).amount, g.registry.card(copy.card_id).cost - 1)
        self.assertTrue(set(originals) <= set(g.state.players[1].deck))
        self.assertEqual(len(g.state.players[1].deck), 7)
        self.assertEqual(len(g.state.deck_shuffle_history), 1)
        fact = g.state.deck_shuffle_history[0]
        self.assertEqual((fact.player_id, fact.actor_id, fact.declared_count), (1, 1, 3))
        self.portable(g)

    def test_rat_copy_batch_wait_restore_and_failed_resume_keep_original_complete_group(self):
        g = self.game((RAT,), deck=(FIRE, OFF2, YETI), mode='copy')
        self.play(g, RAT)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(g.state.players[1].deck), 5)
        self.assertEqual(len(g.state.deck_shuffle_history), 1)

    def test_rat_death_draws_actual_spell_only_and_empty_filtered_deck_does_not_fatigue(self):
        for deck, expected in (((YETI, FIRE), FIRE), ((YETI,), None), ((), None)):
            with self.subTest(deck=deck):
                g = self.game((TEST + 'kill',), board=(RAT,), deck=deck)
                self.play(g, TEST + 'kill', self.first(g, RAT, 'board').id)
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [expected] if expected else [])
                self.assertEqual(g.state.players[1].fatigue, 0)

    def test_hellraiser_native_taunt_empty_buff_and_original_deck_discovery_take(self):
        g = self.game((HELLRAISER,), deck=())
        source = self.play(g, HELLRAISER)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (6, 6))
        self.assertIn(Keyword.TAUNT, g.state.entities[source].keywords)
        g = self.game((HELLRAISER,), deck=(FIRE, YETI, OFF2))
        original = set(g.state.players[1].deck)
        self.play(g, HELLRAISER)
        other = self.portable(g)
        key = g.state.pending_choice.options[0].id
        for game in (g, other):
            self.choose(game, key)
        self.assertEqual(g.snapshot(), other.snapshot())
        received, = g.state.players[1].hand
        self.assertIn(received, original)
        self.assertNotIn(received, g.state.players[1].deck)
        self.assertEqual(len(g.state.players[1].deck), 2)

    def test_crook_actual_remaining_mana_including_zero_and_native_prepare(self):
        for mana, expected in ((3, M0), (5, M2), (7, M4)):
            with self.subTest(mana=mana):
                g = self.game((CROOK,), mana=mana)
                self.play(g, CROOK)
                result, = g.state.mana_consumption_history
                self.assertEqual((result.actual, result.requested, result.mana_after), (mana - 3, None, 0))
                self.assertEqual(self.first(g, expected, 'board').card_id, expected)
                self.assertEqual(g.state.players[1].mana, 0)
        g = self.game((CROOK,), mana=7)
        eid = self.first(g, CROOK).id
        g.apply(UseHandAction(1, eid, 'prepare'))
        self.assertEqual(g.state.players[1].mana, 5)
        self.assertIsNotNone(g.state.entities[eid].preparation)
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, CROOK)
        self.assertEqual(g.snapshot(), saved)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.play(g, CROOK)
        self.assertEqual(g.state.play_history[-1].cost, 0)
        self.assertEqual(g.state.mana_consumption_history[-1].actual, 30)
        self.assertEqual(g.state.players[1].mana, 0)

    def test_crook_original_debit_wait_restore_replay_and_failure_pay_only_once(self):
        g = self.game((CROOK,), mana=5, mode='mana')
        self.play(g, CROOK)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(g.state.mana_consumption_history), 1)
        self.assertEqual(len([i for i in g.state.players[1].board if g.state.entities[i].card_id == M2]), 1)

    def test_crook_full_physical_capacity_spends_mana_but_does_not_summon(self):
        g = self.game((CROOK,), board=(YETI,) * 5 + (TEST + 'dormant',), mana=5)
        rng = g._rng.getstate()
        self.play(g, CROOK)
        self.assertEqual((len(g.state.players[1].board), g.state.players[1].mana), (7, 0))
        self.assertEqual(g._rng.getstate(), rng)

    def test_life_cycle_original_target_cost_controller_slot_and_actual_replacement_on_full_board(self):
        for player in (1, 2):
            with self.subTest(player=player):
                g = self.game((CYCLE,), board=(YETI,) * 7 if player == 1 else (), enemy=(YETI,) * 7 if player == 2 else ())
                target = self.first(g, YETI, 'board', player).id
                before = list(g.state.players[player].board)
                self.play(g, CYCLE, target)
                self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
                after = g.state.players[player].board
                self.assertEqual(len(after), 7)
                self.assertEqual(g.state.entities[after[0]].card_id, M4)
                self.assertEqual(after[1:], before[1:])
                self.assertEqual(g.state.players[1].mana, 29)
                self.assertEqual(g.state.players[2].mana, 30)
        self.portable(g)

    def test_supplicant_original_discounted_personal_spell_cost_other_current_class_and_no_self_recursion(self):
        g = self.game((TEST + 'discount', FIRE), board=(SUPPLICANT,), members=(OFF2,))
        self.play(g, TEST + 'discount', self.first(g, FIRE).id)
        self.play(g, FIRE, g.state.players[2].hero_id)
        self.assertEqual(g.state.play_history[-1].cost, 2)
        automatic = [c for c in g.state.cast_history if c.origin == 'effect']
        self.assertEqual([c.card_id for c in automatic], [OFF2])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.assertEqual(g.state.players[1].mana, 28)
        self.portable(g)

    def test_supplicant_indirect_spell_does_not_count_as_another_personal_spell(self):
        g = self.game((TEST + 'cast',), board=(SUPPLICANT,), members=(OFF2,))
        self.play(g, TEST + 'cast')
        self.assertEqual([c.card_id for c in g.state.cast_history if c.origin == 'effect'], [OFF2])

    def test_complete_unknown_eligible_minion_or_spell_errors_before_rng_and_restores_payment(self):
        r = batch_registry()
        unknown_minion = next(c.card_id for c in r.pool_cards.values() if c.card_id not in r.cards and
            c.kind == CardType.MINION and c.cost == 2 and c.metadata.collectible)
        unknown_spell = next(c.card_id for c in r.pool_cards.values() if c.card_id not in r.cards and
            c.kind == CardType.SPELL and c.cost == 4 and c.metadata.collectible and
            c.metadata.classes and CardClass.MAGE not in c.metadata.classes and CardClass.NEUTRAL not in c.metadata.classes)
        for hand, board, mana, members, cid, target in (
            ((CROOK,), (), 5, (M2, unknown_minion), CROOK, None),
            ((FIRE,), (SUPPLICANT,), 30, (unknown_spell,), FIRE, 'enemy')):
            with self.subTest(cid=cid):
                g = self.game(hand, board=board, mana=mana, members=members)
                saved, calls = g.snapshot(), []
                original = random.Random.randrange
                def spy(rng, *args, **kwargs):
                    calls.append(args)
                    return original(rng, *args, **kwargs)
                with patch.object(random.Random, 'randrange', autospec=True, side_effect=spy):
                    with self.assertRaises(ResolutionError):
                        self.play(g, cid, g.state.players[2].hero_id if target else None)
                self.assertFalse(calls)
                self.assertEqual(g.snapshot(), saved)

    def test_gap_traveler_actual_natural_death_summon_cannot_borrow_spell_group_attack_receipt(self):
        g = self.game((TEST + 'kill',), board=(TEST + 'traveler_gap',), enemy=(YETI,))
        saved = g.snapshot()
        with self.assertRaisesRegex((ResolutionError, ValueError), 'active physical spell'):
            self.play(g, TEST + 'kill', self.first(g, TEST + 'traveler_gap', 'board').id)
        self.assertEqual(g.snapshot(), saved)

    def test_gap_envoy_actual_stored_arbitrary_druid_pool_transform_rejects_minion_tier_only_contract(self):
        g = self.game((TEST + 'transform_gap',), deck=(FIRE,))
        saved = g.snapshot()
        with self.assertRaisesRegex((ResolutionError, ValueError), 'one minion cost tier'):
            self.play(g, TEST + 'transform_gap')
        self.assertEqual(g.snapshot(), saved)

    def test_gap_mend_actual_two_holy_generation_has_no_bound_batch_result_for_combined_healing(self):
        g = self.game((TEST + 'generated_gap',), members=(HOLY3,))
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'two Holy cards delivered but no bound original generation result'):
            self.play(g, TEST + 'generated_gap')
        self.assertEqual(g.snapshot(), saved)


if __name__ == '__main__':
    unittest.main()
