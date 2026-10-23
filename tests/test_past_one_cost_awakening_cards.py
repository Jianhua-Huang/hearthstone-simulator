from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin, event_player
from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_awakening_cards import (
    AXE, CAT, CRIER, DEPENDENCIES, EGG, ENVOY, EXISTING, GANARG, JADE_FORMS, LEAVES,
    MACAW, MERCHANT, METAMORFIN, POOL_ID, RAIDER, STREAMRUNNER, SUNGILL, SWAMP,
    SWARMER, WHELP, load_batch,
)
from hs_sim.engine import (
    AwakenMinion, CardDefinition, CardType, EndTurn, Game, Keyword, PlayerSetup,
    Scenario, TargetSpec, TriggerSpec, UseHeroPower, Zone,
)
from hs_sim.engine.effects import (
    Buff, ChangeControl, ChoiceOption, Damage, DamageBatch, Destroy, GrantKeyword,
    Heal, InvokeBehavior, RequestChoice, ReturnToHand, Silence, TriggerDeathrattles,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, SpellSchool, TargetMode
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from tools import card_batch as batch


P = 'test.k458.'
HIT, LETHAL, ZERO, MASS, HEAL, KILL, DR, BOUNCE, TAKE, SILENCE, SHIELD, WAKE, RECRUIT, FAIL, WATCH = (
    P + name for name in ('hit', 'lethal', 'zero', 'mass', 'heal', 'kill', 'deathrattle',
        'bounce', 'take', 'silence', 'shield', 'wake', 'recruit', 'fail', 'watch'))
FEL, ARCANE = P + 'fel', P + 'arcane'
YETI, RAVEN, DRAGON, PIRATE, REBORN, ONE, RUSH = (
    'CORE_CS2_182', 'KAR_300', 'NEW1_023', 'CORE_WON_351', 'CORE_ULD_723', 'EX1_008', 'LEG_CS3_037')
COUNTER, FLASHBACK = 'CORE_EX1_287', 'TIME_711'
UNKNOWN = P + 'unimplemented-dragon'
POOL_CARDS = (DRAGON, PIRATE, REBORN, RAVEN, ONE)
CONTEXT = GenerationContext('k458-explicit-consumer-fixture', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    missing = replace(r.card(DRAGON), id=UNKNOWN, name=UNKNOWN,
        metadata=replace(r.card(DRAGON).metadata, deck_identity=UNKNOWN))
    r.register_pool_card(PoolCard.from_definition(missing))
    members = () if mode == 'empty' else (DRAGON, UNKNOWN) if mode == 'unknown' else POOL_CARDS
    if mode != 'unbound':
        r.register_pool(PoolDefinition(POOL_ID, 'explicit-consumers-v1', CONTEXT.target_id,
            CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    r.register_pool(PoolDefinition('constructed.past.cards', 'explicit-awakening-leaves-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))

    def fail(c):
        raise ResolutionError('K458 original late failure')

    def mass(c):
        targets = tuple(c.state.players[p].hero_id for p in (1, 2)) + tuple(
            i for p in (1, 2) for i in c.state.players[p].board
            if c.state.entities[i].card_id != WATCH)
        return (DamageBatch(tuple(Damage(i, 1, c.source_id, DamageKind.SPELL) for i in targets)),)

    def wake(c):
        return (AwakenMinion(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].dormancy is not None)),)

    bodies = {
        HIT: lambda c: (Damage(c.target_id, 1, c.source_id),),
        LETHAL: lambda c: (Damage(c.target_id, 20, c.source_id),),
        ZERO: lambda c: (Damage(c.target_id, 0, c.source_id),),
        MASS: mass, HEAL: lambda c: (Heal(c.target_id, 20, c.source_id),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        DR: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),),
        SILENCE: lambda c: (Silence(c.target_id),),
        SHIELD: lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        WAKE: wake,
        RECRUIT: lambda c: (SummonFromZone(c.player_id, zone=Zone.HAND,
            query=PoolQuery(card_ids=(SUNGILL,)), selection='first', source_id=c.source_id,
            cause=SummonCause.capture(c)),),
        FAIL: fail, FEL: lambda c: (), ARCANE: lambda c: (),
    }
    no_target = (MASS, WAKE, RECRUIT, FAIL, FEL, ARCANE)
    any_character = (HIT, LETHAL, ZERO, HEAL)
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        target = None if cid in no_target else TargetSpec() if cid in any_character else (
            TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,)))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=target,
            spell_school=SpellSchool.FEL if cid == FEL else SpellSchool.ARCANE if cid == ARCANE else None))

    def watch(c):
        if event_player(c) != c.player_id:
            return ()
        event = c.event
        recipient = c.state.entities.get(event.target_id)
        cid = None if recipient is None else recipient.card_id
        relevant = (
            event.kind == 'damage_dealt' and cid == EGG or
            event.kind == 'limited_trigger_used' and c.state.entities[event.source_id].card_id == ENVOY or
            event.kind == 'minion_awakened' and cid in (SUNGILL, GANARG) or
            event.kind == 'minion_summoned' and cid in (WHELP, STREAMRUNNER, *JADE_FORMS) or
            event.kind == 'card_added_to_hand' and cid in POOL_CARDS or
            event.kind == 'weapon_equipped')
        if not relevant:
            return ()
        if mode == 'fail':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        expected = {'wait_damage': 'damage_dealt', 'wait_frenzy': 'limited_trigger_used',
            'wait_awaken': 'minion_awakened', 'wait_jade': 'minion_summoned',
            'wait_hand': 'card_added_to_hand'}.get(mode)
        if event.kind != expected:
            return ()
        options = [ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))]
        if mode == 'wait_damage':
            options.append(ChoiceOption('kill', 'Destroy the damaged original', (Destroy(event.target_id),)))
        return (RequestChoice(c.player_id, tuple(options), c.source_id),)

    behavior = WATCH + '.' + mode
    r.register_behavior(behavior, watch)
    events = ('damage_dealt', 'limited_trigger_used', 'minion_awakened',
        'minion_summoned', 'card_added_to_hand', 'weapon_equipped')
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40,
        metadata=replace(r.card(YETI).metadata, collectible=False, deck_identity=WATCH),
        triggers=tuple(TriggerSpec(event, behavior) for event in events)
            if mode.startswith('wait_') or mode == 'fail' else ()))
    r.validate()
    return r


class PastOneCostAwakeningTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, enemy_board=(), enemy_hand=(), deck=(), enemy_deck=(),
             mode='normal', active=1):
        self.mode = mode
        marker = (WATCH,) if mode.startswith('wait_') or mode == 'fail' else ()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=marker+board, deck=deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            active_player=active, seed=458, generation_context=CONTEXT), fixture(mode))

    def ids(self, g, player=1, zone='board'):
        return tuple(g.state.entities[i].card_id for i in getattr(g.state.players[player], zone))

    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def test_nineteen_complete_records_and_thirty_eight_full_primary_faces(self):
        data = load_batch(); rows = data['dependencies'] + data['existing_dependencies']
        self.assertEqual((len(rows), len(data['official_observations'])), (19, 38))
        records = {row['record']['id']: row['record'] for row in rows}
        hashes = {}
        for observation in data['official_observations']:
            cid, locale = observation['card_id'], observation['locale']
            path = observation['response_file']
            if path not in hashes:
                hashes[path] = batch.sha(Path(path))
            self.assertEqual(hashes[path], observation['response_sha256'])
            batch.check_face(records[cid], observation['face'], locale,
                data['display_normalizations'].get(cid),
                numeric_normalizations=data['numeric_normalizations'].get(cid))
        for row in data['existing_dependencies']:
            self.assertEqual(batch.canonical(asdict(fixture().card(row['record']['id']))), row['definition_sha256'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_named_whelp_and_sungill_dependencies_retain_real_primary_edges(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['dependencies']}
        for parent, child in ((EGG, WHELP), (SUNGILL, STREAMRUNNER)):
            self.assertEqual(rows[parent]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'], rows[child]['dbf_id'])
            for o in data['official_observations']:
                if o['card_id'] == parent:
                    self.assertIn(rows[child]['dbf_id'], o['face']['childIds'])
        self.assertEqual((fixture().card(WHELP).attack, fixture().card(WHELP).health), (2, 1))
        self.assertEqual(fixture().card(STREAMRUNNER).metadata.tribes, ('murloc',))

    def test_swarmer_display_exception_cannot_hide_changed_source_or_additional_rules(self):
        data = load_batch(); row = next(x['record'] for x in data['dependencies'] if x['record']['id'] == SWARMER)
        observations = [x for x in data['official_observations'] if x['card_id'] == SWARMER]
        for o in observations:
            for key, value in (('id', 'other'), ('health', 2), ('text', row['text'] + ' 抽一张牌。'),
                    ('text_en', row['text_en'] + ' Draw a card.')):
                changed = deepcopy(row); changed[key] = value
                with self.assertRaises(ValueError):
                    batch.check_face(changed, o['face'], o['locale'], data['display_normalizations'][SWARMER])
            face = dict(o['face']); face['text'] += ' Draw a card.'
            with self.assertRaises(ValueError):
                batch.check_face(row, face, o['locale'], data['display_normalizations'][SWARMER])
            with self.assertRaises(ValueError): batch.check_face(row, o['face'], o['locale'])

    def test_swarmer_display_requires_exact_locale_markers_and_all_printed_numbers(self):
        data = load_batch(); row = next(x['record'] for x in data['dependencies'] if x['record']['id'] == SWARMER)
        for o in data['official_observations']:
            if o['card_id'] != SWARMER:
                continue
            for declaration in ({'{0}': '1'}, {'@': ''}, {'{1}': ''}, {'@': '', '{0}': '', '{1}': ''}):
                with self.assertRaises(ValueError): batch.check_face(row, o['face'], o['locale'], declaration)
            for key, value in (('manaCost', 2), ('attack', 2), ('health', 2), ('cardTypeId', 5)):
                face = dict(o['face']); face[key] = value
                with self.assertRaises(ValueError):
                    batch.check_face(row, face, o['locale'], data['display_normalizations'][SWARMER])

    def test_twelve_native_minions_pay_one_and_have_complete_printed_bodies(self):
        for cid in LEAVES:
            with self.subTest(card=cid):
                g = self.game((cid,)); source = self.play(g, cid)
                self.assertIn(source, g.state.players[1].board)
                self.assertEqual(g.state.players[1].mana, 9)
                self.assertEqual(g.state.entities[source].base_attack, fixture().card(cid).attack)
                self.assertEqual(g.state.entities[source].max_health, fixture().card(cid).health)

    def test_envoy_counts_all_damaged_friendly_and_enemy_characters_once(self):
        g = self.game((MASS, HIT, HEAL), board=(ENVOY, YETI), enemy_board=(YETI,))
        source = self.entity(g, ENVOY, zone='board').id
        self.play(g, MASS); self.assertEqual(g.state.entities[source].attack, 6)
        self.play(g, HEAL, source); self.play(g, HIT, source)
        self.assertEqual(g.state.entities[source].attack, 6)
        self.assertEqual(sum(e.kind == 'limited_trigger_used' for e in g.events), 1)

    def test_envoy_zero_shield_and_lethal_damage_do_not_use_frenzy(self):
        g = self.game((ZERO, SHIELD, HIT, LETHAL), board=(ENVOY,))
        source = self.entity(g, ENVOY, zone='board').id
        self.play(g, ZERO, source); self.play(g, SHIELD, source); self.play(g, HIT, source)
        self.assertEqual(g.state.entities[source].attack, 1)
        self.play(g, LETHAL, source)
        self.assertEqual(sum(e.kind == 'limited_trigger_used' for e in g.events), 0)

    def test_envoy_wait_restores_original_consumed_frenzy_without_second_use(self):
        g = self.game((HIT,), board=(ENVOY,), mode='wait_frenzy')
        source = self.entity(g, ENVOY, zone='board').id
        self.play(g, HIT, source); self.assertIsNotNone(g.state.pending_choice)
        g = self.portable(g); self.choose(g)
        self.assertEqual(g.state.entities[source].attack, 2)
        self.assertEqual(sum(e.kind == 'limited_trigger_used' for e in g.events), 1)

    def test_egg_repeats_for_each_real_hit_and_keeps_its_lethal_trigger(self):
        g = self.game((HIT, HIT), board=(EGG,))
        source = self.entity(g, EGG, zone='board').id
        self.play(g, HIT, source); self.play(g, HIT, source)
        self.assertEqual(self.ids(g).count(WHELP), 2)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)

    def test_egg_zero_damage_shield_and_silence_do_not_summon(self):
        g = self.game((ZERO, SHIELD, HIT, SILENCE, HIT), board=(EGG,))
        source = self.entity(g, EGG, zone='board').id
        for cid in (ZERO, SHIELD, HIT, SILENCE, HIT): self.play(g, cid, source)
        self.assertNotIn(WHELP, self.ids(g))

    def test_egg_damage_wait_retains_original_trigger_if_source_dies_during_choice(self):
        g = self.game((HIT,), board=(EGG,), mode='wait_damage')
        source = self.entity(g, EGG, zone='board').id
        self.play(g, HIT, source); self.assertIsNotNone(g.state.pending_choice)
        g = self.portable(g); self.choose(g, 'kill')
        self.assertEqual(self.ids(g).count(WHELP), 1)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)

    def test_sungill_is_dormant_for_two_controller_starts_and_wakes_into_two_murlocs(self):
        g = self.game((SUNGILL,), deck=(RAVEN, RAVEN), enemy_deck=(RAVEN, RAVEN))
        source = self.play(g, SUNGILL)
        self.assertEqual(g.state.entities[source].dormancy.remaining_turns, 2)
        self.assertNotIn(STREAMRUNNER, self.ids(g))
        self.cycle(g); self.assertEqual(g.state.entities[source].dormancy.remaining_turns, 1)
        g = self.portable(g); self.cycle(g)
        self.assertIsNone(g.state.entities[source].dormancy)
        self.assertEqual(self.ids(g).count(STREAMRUNNER), 2)
        self.assertEqual(sum(e.kind == 'minion_awakened' and e.target_id == source for e in g.events), 1)

    def test_sungill_awaken_wait_resumes_two_summons_once(self):
        g = self.game((WAKE,), board=(SUNGILL,), mode='wait_awaken')
        self.play(g, WAKE); self.assertIsNotNone(g.state.pending_choice)
        g = self.portable(g); self.choose(g)
        self.assertEqual(self.ids(g).count(STREAMRUNNER), 2)

    def test_sungill_wakeup_uses_actual_capacity_and_does_not_add_battlecry(self):
        g = self.game((WAKE,), board=(SUNGILL,) + (YETI,) * 5)
        self.play(g, WAKE)
        self.assertEqual(self.ids(g).count(STREAMRUNNER), 1)
        self.assertFalse(g.state.battlecry_history)

    def test_ganarg_natural_wakeup_equips_real_three_two_axe(self):
        g = self.game((GANARG,), deck=(RAVEN, RAVEN), enemy_deck=(RAVEN, RAVEN))
        source = self.play(g, GANARG); self.assertIsNone(g.state.players[1].weapon_id)
        self.cycle(g); self.assertIsNone(g.state.players[1].weapon_id)
        self.cycle(g)
        axe = g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((axe.card_id, axe.attack, axe.durability), (AXE, 3, 2))
        self.assertIsNone(g.state.entities[source].dormancy)

    def test_ganarg_awaken_wait_restores_one_original_weapon_install(self):
        g = self.game((WAKE,), board=(GANARG,), mode='wait_awaken')
        self.play(g, WAKE); g = self.portable(g); self.choose(g)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id, AXE)

    def test_swarmer_natural_death_and_live_activation_share_real_jade_growth(self):
        g = self.game((DR, KILL), board=(SWARMER,))
        source = self.entity(g, SWARMER, zone='board').id
        self.assertIn(Keyword.STEALTH, g.state.entities[source].keywords)
        self.play(g, DR, source); self.play(g, KILL, source)
        golems = [g.state.entities[i] for i in g.state.players[1].board]
        # The natural Deathrattle uses Swarmer's vacated slot, before the first
        # golem that its earlier live activation placed on its right.
        self.assertEqual([(e.jade_size, e.base_attack, e.max_health) for e in golems], [(2, 2, 2), (1, 1, 1)])
        self.assertEqual(len(g.state.jade_history), 2)

    def test_swarmer_full_board_attempt_advances_growth_before_next_success(self):
        g = self.game((DR, KILL, DR), board=(SWARMER,) + (YETI,) * 6)
        source = self.entity(g, SWARMER, zone='board').id
        self.play(g, DR, source); self.assertEqual(len(g.state.players[1].board), 7)
        self.assertIsNone(g.state.jade_history[0].entity_id)
        self.play(g, KILL, self.entity(g, YETI, zone='board').id); self.play(g, DR, source)
        golem = next(g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].jade_size is not None)
        self.assertEqual(golem.jade_size, 2)

    def test_swarmer_summon_wait_restores_original_growth_and_receipt(self):
        g = self.game((DR,), board=(SWARMER,), mode='wait_jade')
        self.play(g, DR, self.entity(g, SWARMER, zone='board').id)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); self.choose(g)
        self.assertEqual(len(g.state.jade_history), 1)
        self.assertEqual(sum(g.state.entities[i].jade_size is not None for i in g.state.players[1].board), 1)

    def test_all_five_random_consumers_use_actual_query_and_original_recipient(self):
        for cid, allowed in ((SWAMP, (DRAGON,)), (CAT, (REBORN,)), (RAIDER, (PIRATE,)),
                (MACAW, (RAVEN,)), (MERCHANT, (PIRATE, REBORN, RAVEN, ONE))):
            with self.subTest(card=cid):
                g = self.game((cid, KILL))
                source = self.play(g, cid)
                if cid in (SWAMP, MERCHANT): self.play(g, KILL, source)
                generated = [x for x in self.ids(g, zone='hand') if x in POOL_CARDS]
                self.assertEqual(len(generated), 1); self.assertIn(generated[0], allowed)
                self.assertEqual(g.state.players[2].hand, [])

    def test_generation_uses_fresh_base_card_and_never_executes_its_native_body(self):
        g = self.game((CAT,)); self.play(g, CAT)
        mummy = self.entity(g, REBORN)
        self.assertEqual((mummy.base_attack, mummy.max_health), (fixture().card(REBORN).attack, fixture().card(REBORN).health))
        self.assertIn(Keyword.REBORN, mummy.keywords)
        self.assertEqual(len(g.state.players[1].board), 1)

    def test_generation_empty_domain_preserves_rng_and_unknown_matching_member_rolls_back(self):
        g = self.game((CAT,), mode='empty'); rng = g._rng.getstate(); self.play(g, CAT)
        self.assertEqual(g._rng.getstate(), rng); self.assertEqual(self.ids(g, zone='hand'), ())
        h = self.game((SWAMP, DR), mode='unknown'); source = self.play(h, SWAMP); before = h.snapshot()
        with self.assertRaises(ResolutionError): self.play(h, DR, source)
        self.assertEqual(h.snapshot(), before)

    def test_generation_unbound_host_domain_does_not_fall_back_to_registered_cards(self):
        g = self.game((CAT,), mode='unbound'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, CAT)
        self.assertEqual(g.snapshot(), before)

    def test_generation_hand_wait_restores_original_choice_without_second_random_draw(self):
        g = self.game((RAIDER,), mode='wait_hand'); self.play(g, RAIDER)
        self.assertIsNotNone(g.state.pending_choice); rng = g._rng.getstate()
        g = self.portable(g); self.choose(g)
        self.assertEqual(self.ids(g, zone='hand'), (PIRATE,)); self.assertEqual(g._rng.getstate(), rng)
        opponent = g.for_player(2).observe()['observation']
        self.assertTrue(all(row['card_id'] is None for row in opponent['players'][0]['hand']))

    def test_crier_draws_matching_physical_rush_card_and_preserves_other_deck_order(self):
        g = self.game((CRIER,), deck=(YETI, RUSH, RAVEN))
        rush = self.entity(g, RUSH, zone='deck').id
        self.play(g, CRIER)
        self.assertIn(rush, g.state.players[1].hand)
        self.assertEqual(self.ids(g, zone='deck'), (YETI, RAVEN))

    def test_crier_no_matching_minion_skips_without_fatigue_or_randomness(self):
        for deck in ((), (YETI, ARCANE)):
            g = self.game((CRIER,), deck=deck); rng = g._rng.getstate()
            hero = g.state.entities[g.state.players[1].hero_id].health
            self.play(g, CRIER)
            self.assertEqual(self.ids(g, zone='deck'), deck); self.assertEqual(g._rng.getstate(), rng)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, hero)

    def test_metamorfin_requires_original_own_fel_cast_this_turn(self):
        for spells, attack, health in (((FEL,), 3, 4), ((ARCANE,), 1, 2), ((), 1, 2)):
            g = self.game(spells + (METAMORFIN,))
            for cid in spells: self.play(g, cid)
            source = self.play(g, METAMORFIN)
            self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (attack, health))
            self.assertIn(Keyword.TAUNT, g.state.entities[source].keywords)

    def test_metamorfin_excludes_countered_fel_opponents_cast_and_previous_turn(self):
        g = self.game((FEL, METAMORFIN), enemy_hand=(COUNTER,), active=2)
        self.play(g, COUNTER, player=2); g.apply(EndTurn(2)); self.play(g, FEL)
        source = self.play(g, METAMORFIN); self.assertEqual(g.state.entities[source].attack, 1)
        h = self.game((METAMORFIN,), enemy_hand=(FEL,), active=2)
        self.play(h, FEL, player=2); h.apply(EndTurn(2))
        source = self.play(h, METAMORFIN); self.assertEqual(h.state.entities[source].attack, 1)
        k = self.game((FEL, METAMORFIN)); self.play(k, FEL); self.cycle(k)
        source = self.play(k, METAMORFIN); self.assertEqual(k.state.entities[source].attack, 1)

    def test_sungill_return_and_recruit_resets_native_dormancy_without_battlecry(self):
        # Use explicit wake before an ordinary targeting arrow can select it.
        h = self.game((WAKE, BOUNCE, RECRUIT), board=(SUNGILL,))
        source = self.entity(h, SUNGILL, zone='board').id
        self.play(h, WAKE); self.play(h, BOUNCE, source); self.play(h, RECRUIT)
        self.assertIn(source, h.state.players[1].board)
        self.assertEqual(h.state.entities[source].dormancy.remaining_turns, 2)
        self.assertEqual(self.ids(h).count(STREAMRUNNER), 2)

    def test_late_reaction_failures_roll_back_damage_frenzy_generation_jade_and_wakeup(self):
        for hand, board, operation, target in (
                ((HIT,), (EGG,), HIT, EGG), ((HIT,), (ENVOY,), HIT, ENVOY),
                ((CAT,), (), CAT, None), ((DR,), (SWARMER,), DR, SWARMER),
                ((WAKE,), (GANARG,), WAKE, None)):
            with self.subTest(operation=operation, board=board):
                g = self.game(hand, board=board, mode='fail'); before = g.snapshot()
                target_id = None if target is None else self.entity(g, target, zone='board').id
                with self.assertRaisesRegex(ResolutionError, 'K458 original late failure'):
                    self.play(g, operation, target_id)
                self.assertEqual(g.snapshot(), before)

    def test_real_flashback_summons_without_battlecry_and_enters_printed_dormancy(self):
        g = self.game((FLASHBACK,)); self.play(g, FLASHBACK)
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertEqual(self.ids(g, zone='hand'), ())
        for i in g.state.players[1].board:
            entity = g.state.entities[i]
            self.assertIn(entity.card_id, LEAVES)
            if entity.card_id in (SUNGILL, GANARG):
                self.assertEqual(entity.dormancy.remaining_turns, 2)
        self.assertFalse(g.state.battlecry_history)


if __name__ == '__main__':
    unittest.main()
