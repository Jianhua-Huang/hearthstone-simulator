"""Exact zero evidence and grouped native generation, split and choice paths."""
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
from hs_sim.cards.simple_followup_p53_cards import (STONE, BARRAGE, INGREDIENT, LEGS,
    CREATION, SHADE, ATTACK, DRUID, SHRED, ROOTS, DEPENDENCIES, PARENTS, POOL_ID,
    load_batch, register_simple_followup_p53_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, Keyword, PaymentType, PlayCard, PlayerSetup, Scenario,
    SelectChoice, SpellSchool, TargetSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy,
    InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest

TEST = 'p53.test.'
YETI = 'CORE_CS2_182'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
FEL4, FEL2, DRUID3, DRUID_MINION = (TEST + name for name in ('fel4', 'fel2', 'druid3', 'druid_minion'))
MEMBERS = (FEL4, FEL2, DRUID3, DRUID_MINION, YETI)
CONTEXT = GenerationContext('p53-explicit-complete-fixture', 'experimental')


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS + DEPENDENCIES)
    if not any(present):
        register_simple_followup_p53_cards(r)
    elif not all(present):
        raise AssertionError('P53 assembly must contain all reviewed physical and choice definitions')
    register_candidate_pool_metadata(r)
    r.validate()
    return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    r.register_behavior(TEST + 'nop', lambda c: ())
    for cid, cost, card_class, school in (
            (FEL4, 4, CardClass.WARLOCK, SpellSchool.FEL),
            (FEL2, 2, CardClass.DEMON_HUNTER, SpellSchool.FEL),
            (DRUID3, 3, CardClass.DRUID, SpellSchool.NATURE)):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=TEST + 'nop',
            metadata=CardMetadata(True, (card_class,), None, tribes=()), spell_school=school))
    r.register_card(CardDefinition(DRUID_MINION, 'Explicit Druid minion', CardType.MINION,
        cost=2, attack=2, health=3, metadata=CardMetadata(True, (CardClass.DRUID,), None, tribes=())))
    r.register_card(CardDefinition(TEST + 'power', 'Ordinary five Spell Damage', CardType.MINION,
        health=20, spell_damage=5, metadata=META))
    r.register_card(CardDefinition(TEST + 'both', 'Native Choose Both', CardType.MINION,
        health=20, choose_both=True, metadata=META))
    scripts = dict(
        kill=lambda c: (Destroy(c.target_id, c.source_id),),
        silence=lambda c: (Silence(c.target_id),),
        control=lambda c: (ChangeControl(c.target_id, 2),),
        wound_enemy=lambda c: (Damage(c.state.players[2].hero_id, 29, c.source_id),),
        enemy_cast=lambda c: (CastSpell(2, BARRAGE, c.source_id),),
        current_copy=lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]),
            c.player_id, mode='current', source_id=c.source_id),),
        base_copy=lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]),
            c.player_id, mode='base', source_id=c.source_id),),
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P53 deliberate continuation failure')))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        kwargs = {}
        if name in ('kill', 'silence', 'control'):
            kwargs['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
        if name in ('current_copy', 'base_copy'):
            kwargs['targeting'] = TargetSpec(zones=(Zone.HAND,), kinds=(CardType.SPELL,), relation='friendly')
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=TEST + name, metadata=META, **kwargs))
    if mode:
        def eligible(c):
            if mode == 'last':
                result = health_result(c.event)
                return (result is not None and result.split_packet is not None and
                        result.source_card_id == BARRAGE and result.split_packet.index == 6)
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == (STONE if mode == 'gift' else INGREDIENT)

        def watch(c):
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(TEST + 'fail', c.source_id, 1),))), c.source_id),)

        event = 'health_resolved' if mode == 'last' else 'card_added_to_hand'
        r.register_behavior(TEST + 'watch', watch)
        r.register_trigger_condition(TEST + 'eligible', eligible)
        r.register_card(CardDefinition(TEST + 'watch', 'Actual continuation witness', CardType.WEAPON,
            durability=5, metadata=META, limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch',
                condition_id=TEST + 'eligible'),)))
    for cid in members:
        if cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p53-complete-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared_registry(mode, members):
    return registry(mode, members)


class SimpleFollowupP53Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), members=MEMBERS, mode=None, armor=0):
        self.config = (mode, members)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=(YETI,) * 6, mana=30, max_mana=30, mana_cap=30, armor=armor,
            weapon_card_id=TEST + 'watch' if mode else None),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,) * 6, mana=30, max_mana=30,
                mana_cap=30)), seed=5353, generation_context=CONTEXT), shared_registry(*self.config))

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone)
                    if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, branch=None):
        entity = self.first(g, cid)
        g.apply(PlayCard(1, entity.id, target, position=len(g.state.players[1].board)
                         if entity.kind == CardType.MINION else None, branch_id=branch))
        return entity.id

    def choose(self, g, key='ok'):
        g.apply(SelectChoice(1, g.state.pending_choice.id, (key,)))

    def created(self, g, source):
        return [g.state.entities[e.target_id] for e in g.events if e.kind == 'card_created' and e.source_id == source]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(
                g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'behavior_id', 'source_json', 'split_damage_history'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_fifteen_complete_source_rows_thirty_primary_faces_eighteen_links_and_explicit_zeros(self):
        from tools.card_batch import check_face
        data = load_batch()
        rows = {x['record']['id']: x for section in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only') for x in data[section]}
        self.assertEqual(len(rows), 15)
        self.assertEqual(len(data['official_observations']), 30)
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['official_observations']}
        for o in data['official_observations']:
            raw = rows[o['card_id']]['record']
            original = json.dumps(raw, ensure_ascii=False, sort_keys=True)
            check_face(raw, o['face'], o['locale'], numeric_normalizations=data['numeric_normalizations'].get(raw['id']))
            self.assertEqual(json.dumps(raw, ensure_ascii=False, sort_keys=True), original)
            self.assertEqual(canonical_digest(raw), rows[raw['id']]['record_sha256'])
            self.assertEqual(o['response_sha256'], o['observation']['sha256'])
        self.assertEqual(len(data['numeric_normalizations']), 10)
        for cid, declaration in data['numeric_normalizations'].items():
            raw = rows[cid]['record']
            for field, zero in declaration.items():
                self.assertIsNone(raw[field])
                self.assertNotIn('COST' if field == 'cost' else 'ATK', raw['tags'])
                self.assertEqual((type(zero), zero), (int, 0))
        self.assertEqual(len(data['exact_parent_child_links']), 18)
        for link in data['exact_parent_child_links']:
            self.assertEqual(rows[link['child']]['record']['dbf_id'], link['dbf_id'])
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
        with self.assertRaisesRegex(ValueError, 'numeric face drift'):
            check_face(rows[STONE]['record'], faces[STONE, 'zh_CN'], 'zh_CN')
        self.assertFalse(data['formal_pool_complete'] or data['cn_calibrated'] or data['source_parents_implemented'])

    def test_eleven_definitions_three_collectible_six_minions_two_choice_only_and_all_old_data_preserved(self):
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
        self.assertEqual(sum(after.card(i).metadata.collectible for i in ROOTS), 3)
        self.assertEqual(sum(after.card(i).kind == CardType.MINION and not after.card(i).metadata.collectible for i in ROOTS), 6)
        for cid in DEPENDENCIES:
            self.assertTrue(after.card(cid).choice_only)
            self.assertFalse(after.card(cid).hand_playable)
            self.assertNotIn(cid, after.pool_cards)
        for cid in PARENTS:
            self.assertEqual(cid in before.cards, cid in after.cards)
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(), DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_every_printed_body_metadata_and_zero_field_matches_its_independent_full_face(self):
        data, r = load_batch(), batch_registry()
        for row in data['cards'] + data['dependencies']:
            raw = row['record']
            card = r.card(raw['id'])
            expected = dict(data['numeric_normalizations'].get(raw['id'], {}))
            self.assertEqual(card.cost, expected.get('cost', raw['cost']))
            self.assertEqual(card.metadata, metadata_from_record(raw))
            if card.kind == CardType.MINION:
                self.assertEqual((card.attack, card.health), (expected.get('attack', raw['attack']), raw['health']))
        self.assertEqual(r.card(STONE).keywords, (Keyword.TAUNT,))
        self.assertEqual(r.card(CREATION).metadata.tribes, ('dragon', 'undead'))
        self.assertEqual(r.card(SHADE).metadata.tribes, ('undead',))
        for cid in (CREATION, SHADE):
            card = r.card(cid)
            self.assertFalse(card.keywords or card.triggers or card.battlecry or card.deathrattle or card.colossal)

    def test_stone_real_zero_attack_taunt_paid_body_and_two_cross_class_local_health_prices(self):
        for cid in (FEL4, FEL2):
            with self.subTest(cid=cid):
                g = self.game((STONE, TEST + 'kill', cid), members=(cid,), armor=3)
                source = self.play(g, STONE)
                self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (0, 8))
                self.assertEqual(g.state.players[1].mana, 25)
                normal = self.first(g, cid)
                self.play(g, TEST + 'kill', source)
                gifts = self.created(g, source)
                self.assertEqual(len(gifts), 2)
                self.assertTrue(all(card.card_id == cid for card in gifts))
                self.assertTrue(all(quote_unselected_cost(g.state, g.registry, card).payment == PaymentType.HEALTH for card in gifts))
                self.assertEqual(quote_unselected_cost(g.state, g.registry, normal).payment, PaymentType.MANA)
                g.apply(PlayCard(1, gifts[0].id))
                hero = g.state.entities[g.state.players[1].hero_id]
                cost = g.registry.card(cid).cost
                self.assertEqual((hero.health, hero.armor), (30 - max(0, cost - 3), max(0, 3 - cost)))
                self.assertEqual(g.state.players[1].mana, 25)
                self.assertEqual(g.state.play_history[-1].payment, PaymentType.HEALTH)

    def test_stone_health_price_current_copy_retains_local_payment_base_copy_and_original_face_do_not(self):
        g = self.game((TEST + 'kill', TEST + 'current_copy', TEST + 'base_copy'), board=(STONE,), members=(FEL4,))
        source = self.first(g, STONE, 'board').id
        self.play(g, TEST + 'kill', source)
        gift = self.created(g, source)[0]
        current = self.play(g, TEST + 'current_copy', gift.id)
        base = self.play(g, TEST + 'base_copy', gift.id)
        current_card, = self.created(g, current)
        base_card, = self.created(g, base)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, current_card).payment, PaymentType.HEALTH)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, base_card).payment, PaymentType.MANA)
        self.portable(g)

    def test_stone_actual_gift_delivery_wait_restore_replay_and_failed_resume_keep_both_original_gifts(self):
        g = self.game((TEST + 'kill',), board=(STONE,), members=(FEL2,), mode='gift')
        source = self.first(g, STONE, 'board').id
        self.play(g, TEST + 'kill', source)
        self.assertEqual(len(self.created(g, source)), 1)
        self.assertNotIn(FEL2, json.dumps(g.for_player(2).observe()))
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.created(g, source)), 2)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)

    def test_stone_silence_removes_printed_deathrattle_and_full_hand_burns_only_overflow_gift(self):
        g = self.game((TEST + 'silence', TEST + 'kill'), board=(STONE,), members=(FEL4,))
        source = self.first(g, STONE, 'board').id
        self.play(g, TEST + 'silence', source)
        self.play(g, TEST + 'kill', source)
        self.assertFalse(self.created(g, source))
        g = self.game((TEST + 'kill',) + (YETI,) * 9, board=(STONE,), members=(FEL4,))
        source = self.first(g, STONE, 'board').id
        self.play(g, TEST + 'kill', source)
        self.assertEqual([card.zone for card in self.created(g, source)], [Zone.HAND, Zone.GRAVEYARD])
        self.assertEqual(len(g.state.players[1].hand), 10)

    def test_barrage_immune_six_spell_units_one_cast_then_one_exact_two_shred_shuffle(self):
        g = self.game((BARRAGE,), board=(TEST + 'power',))
        source = self.play(g, BARRAGE)
        root, = g.state.split_damage_history
        self.assertEqual((root.request.spell_bonus_multiplier, root.quote.spell_bonus, root.quote.budget), (0, 0, 6))
        self.assertEqual(root.quote.contributions, ())
        self.assertEqual(len(root.packets), 6)
        self.assertTrue(root.completed)
        self.assertEqual(root.quote.cast.source_id, source)
        self.assertEqual(len(g.state.cast_history), 1)
        results = [row.health_result for row in g.state.damage_history]
        self.assertTrue(all((value.base_amount, value.spell_bonus, value.damage_kind) == (1, 0, 'spell') for value in results))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
        self.assertEqual(g.state.players[1].mana, 28)
        self.assertEqual(sum(g.state.entities[i].card_id == SHRED for i in g.state.players[1].deck), 2)
        fact, = g.state.deck_shuffle_history
        self.assertEqual((fact.actor_id, fact.player_id, fact.declared_count), (1, 1, 2))
        closed = next(e.sequence for e in g.events if e.kind == 'split_damage_closed')
        self.assertGreater(fact.event_sequence, closed)
        self.portable(g)

    def test_barrage_last_real_packet_wait_restore_failure_and_completion_shuffle_execute_once(self):
        g = self.game((BARRAGE,), board=(TEST + 'power',), mode='last')
        self.play(g, BARRAGE)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.deck_shuffle_history)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(g.state.damage_history), 6)
        self.assertEqual(len(g.state.deck_shuffle_history), 1)
        self.assertEqual(sum(g.state.entities[i].card_id == SHRED for i in g.state.players[1].deck), 2)

    def test_barrage_indirect_other_player_keeps_actual_cast_owner_and_shuffle_recipient(self):
        g = self.game((TEST + 'enemy_cast',), enemy=(TEST + 'power',))
        self.play(g, TEST + 'enemy_cast')
        root, = g.state.split_damage_history
        self.assertEqual((root.request.player_id, root.quote.budget), (2, 6))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 24)
        fact, = g.state.deck_shuffle_history
        self.assertEqual((fact.actor_id, fact.player_id, fact.declared_count), (2, 2, 2))
        self.assertEqual(g.state.players[2].mana, 30)
        self.assertEqual(sum(g.state.entities[i].card_id == SHRED for i in g.state.players[2].deck), 2)
        self.portable(g)

    def test_barrage_terminal_unit_interrupts_remaining_budget_and_does_not_run_shuffle_tail(self):
        g = self.game((TEST + 'wound_enemy', BARRAGE))
        self.play(g, TEST + 'wound_enemy')
        self.play(g, BARRAGE)
        self.assertEqual(g.state.winner, 1)
        self.assertEqual(len(g.state.split_damage_history[0].packets), 1)
        self.assertFalse(g.state.deck_shuffle_history)
        self.assertEqual(len(g.state.players[1].deck), 6)

    def test_ingredient_zero_cost_attack_branch_is_temporary_and_druid_branch_includes_all_card_types(self):
        g = self.game((INGREDIENT,))
        source = self.play(g, INGREDIENT, branch=ATTACK)
        hero = g.state.players[1].hero_id
        self.assertEqual((g.state.entities[hero].attack, g.state.players[1].mana), (2, 30))
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history)), (1, 1))
        self.assertEqual(g.state.play_history[0].source_id, source)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[hero].attack, 0)
        for cid in (DRUID3, DRUID_MINION):
            with self.subTest(cid=cid):
                g = self.game((INGREDIENT,), members=(cid, YETI))
                self.play(g, INGREDIENT, branch=DRUID)
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [cid])
                self.assertEqual(g.state.players[1].mana, 30)

    def test_ingredient_native_combined_wait_restore_replay_failure_keeps_one_buff_one_gift_and_payment(self):
        g = self.game((INGREDIENT,), board=(TEST + 'both',), members=(DRUID3,), mode='ingredient')
        self.play(g, INGREDIENT, branch=INGREDIENT + ':combined')
        hero = g.state.players[1].hero_id
        self.assertEqual(g.state.entities[hero].attack, 2)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((g.state.players[1].mana, len(g.state.play_history), len(g.state.cast_history)), (30, 1, 1))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [DRUID3])
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[hero].attack, 0)

    def test_ingredient_missing_unknown_or_unauthorized_combined_branch_is_atomic(self):
        for branch in (None, 'unknown', INGREDIENT + ':combined'):
            with self.subTest(branch=branch):
                g = self.game((INGREDIENT,))
                saved = g.snapshot()
                with self.assertRaises(IllegalAction):
                    self.play(g, INGREDIENT, branch=branch)
                self.assertEqual(g.snapshot(), saved)

    def test_all_four_leg_forms_grow_only_their_own_residence_on_current_controller_end(self):
        g = self.game(board=(*LEGS, YETI), enemy=(YETI,))
        g.apply(EndTurn(1))
        for cid in LEGS:
            card = self.first(g, cid, 'board')
            self.assertEqual((card.attack, card.health), (1, 3))
        self.assertEqual((self.first(g, YETI, 'board').attack, self.first(g, YETI, 'board').health), (4, 5))
        g.apply(EndTurn(2))
        self.assertTrue(all(self.first(g, cid, 'board').attack == 1 for cid in LEGS))
        self.portable(g)

    def test_leg_silence_and_control_transfer_use_native_lifecycle_without_parent_behavior(self):
        g = self.game((TEST + 'silence', TEST + 'control'), board=(LEGS[0], LEGS[1], CREATION, SHADE))
        silenced = self.first(g, LEGS[0], 'board').id
        transferred = self.first(g, LEGS[1], 'board').id
        self.play(g, TEST + 'silence', silenced)
        self.play(g, TEST + 'control', transferred)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[silenced].attack, 0)
        self.assertEqual(g.state.entities[transferred].attack, 0)
        self.assertEqual((self.first(g, CREATION, 'board').attack, self.first(g, CREATION, 'board').health), (1, 1))
        self.assertEqual((self.first(g, SHADE, 'board').attack, self.first(g, SHADE, 'board').health), (3, 2))
        g.apply(EndTurn(2))
        self.assertEqual((g.state.entities[transferred].controller, g.state.entities[transferred].attack,
            g.state.entities[transferred].health), (2, 1, 3))

    def test_complete_unknown_eligible_fel_or_druid_content_rejects_before_rng_and_restores_original_action(self):
        r = batch_registry()
        fel = next(c.card_id for c in r.pool_cards.values() if c.card_id not in r.cards and c.kind == CardType.SPELL
            and c.metadata.collectible and c.spell_school == SpellSchool.FEL)
        druid = next(c.card_id for c in r.pool_cards.values() if c.card_id not in r.cards and c.metadata.collectible
            and c.metadata.classes and CardClass.DRUID in c.metadata.classes)
        for kind, members in (('fel', (FEL4, fel)), ('druid', (DRUID3, druid))):
            with self.subTest(kind=kind):
                g = self.game((TEST + 'kill',) if kind == 'fel' else (INGREDIENT,),
                    board=(STONE,) if kind == 'fel' else (), members=members)
                saved, calls = g.snapshot(), []
                original = random.Random.randrange
                def spy(rng, *args, **kwargs):
                    calls.append(args)
                    return original(rng, *args, **kwargs)
                with patch.object(random.Random, 'randrange', autospec=True, side_effect=spy):
                    with self.assertRaises(ResolutionError):
                        if kind == 'fel':
                            self.play(g, TEST + 'kill', self.first(g, STONE, 'board').id)
                        else:
                            self.play(g, INGREDIENT, branch=DRUID)
                self.assertFalse(calls)
                self.assertEqual(g.snapshot(), saved)


if __name__ == '__main__':
    unittest.main()
