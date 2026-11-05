"""Real weapon text over the existing attack, death, summon and save pipelines.

Three-member domains and source hands are diagnostic, not formal curated-pool
or legal starting-deck evidence. Every offered recipe uses a real producer.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
from fixture_inputs import fixture_input_map
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import assemble_hero_attack_weapon_fragments as cards
from hs_sim.cards.native_assemble_entry_cards import FLESH, NURTURER, FETCHER, POOL_ID
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, RuleContext, Scenario, SelectChoice,
    SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleRecipe
from hs_sim.engine.assemble_reactions import (AssembleReactionSource, AssembleWeaponReactionSource,
    reaction_behavior_id)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Destroy,
    GainArmor, InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, SummonQuantitySpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

FLAMER, MACE, CLAWS, SCYTHE, CANNON, AXE, HAMMER = cards.SOURCES
LOOT, BASE, DRAIN, CAIRNE = cards.LOOT, 'CORE_UNG_809', 'CORE_GIL_622', 'CORE_EX1_110'
COIN = 'GAME_005'
P = 'fixture.assemble_hero_attack_weapon.'
KILL, MUTE, STEAL, HERO_ATTACK, WEAPON, FILL, POWER, MULT, WATCH, FAIL = (
    P+x for x in ('kill', 'mute', 'steal', 'hero-attack', 'weapon', 'fill', 'power', 'mult', 'watch', 'fail'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CTX = GenerationContext('k522-complete-weapon-text-diagnostic-domains', 'experimental')
HEROES = {CardClass.HUNTER: 'HERO_05', CardClass.PALADIN: 'HERO_04',
    CardClass.DEMON_HUNTER: 'HERO_10', CardClass.DEATH_KNIGHT: 'HERO_11',
    CardClass.WARRIOR: 'HERO_01', CardClass.SHAMAN: 'HERO_02'}


def parts(donor, mode):
    if mode == 'body':
        return (DRAIN, FETCHER, CAIRNE) if donor in (MACE, SCYTHE, HAMMER) else (BASE, NURTURER, LOOT)
    return LOOT, FLESH, DRAIN


def unadapted():
    return batch.registration_prefix(build_registry,
        'hs_sim.cards.assemble_hero_attack_weapon_fragments.register_assemble_hero_attack_weapon_fragments',
        cards.register_assemble_hero_attack_weapon_fragments)


@lru_cache(maxsize=None)
def fixture(donor=MACE, mode='reaction', role='writer'):
    r = build_registry()
    r._version += '.k522.'+donor+'.'+mode
    target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    for cid, body in (
            (KILL, lambda c: (Destroy(c.target_id, c.source_id),)),
            (MUTE, lambda c: (Silence(c.target_id),)),
            (STEAL, lambda c: (ChangeControl(c.target_id, 3-c.player_id),))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=target, metadata=META))
    r.register_behavior(HERO_ATTACK, lambda c: (Buff(c.state.players[c.player_id].hero_id,
        attack=1, expires_turn=c.state.turn, source_id=c.source_id),))
    r.register_card(CardDefinition(HERO_ATTACK, HERO_ATTACK, CardType.SPELL, on_play=HERO_ATTACK, metadata=META))
    r.register_card(CardDefinition(WEAPON, WEAPON, CardType.WEAPON, attack=1,
        durability=1 if mode == 'last' else 4, metadata=META))
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, attack=2, health=20, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.MINION, health=20, spell_damage=4, metadata=META))
    r.register_card(CardDefinition(MULT, MULT, CardType.MINION, health=20, metadata=META,
        summon_quantities=(SummonQuantitySpec(factor=2, source_kinds=(CardType.WEAPON,)),)))

    def fail(c):
        raise ResolutionError('deliberate completed-hero-attack projection failure')

    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or not source.card_id.startswith('assemble:'):
            return ()
        if mode == 'fail':
            return (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('card_drawn', WATCH),)))
    base, _, other = parts(donor, mode)
    r.register_pool(PoolDefinition(POOL_ID, 'three-complete-physical-sources-v1', CTX.target_id,
        CTX.mode, tuple(PoolMember(cid) for cid in (base, other, donor)), complete=True))
    if mode == 'missing':
        r._assemble_reaction_sources.pop(donor)
        r._assemble_projections.pop(donor)
    return r


class AssembleHeroAttackWeaponTests(CardBatchTestMixin, unittest.TestCase):
    def registry_factory(self, mode, role):
        return fixture(self.donor, mode, role)

    def game(self, donor=MACE, mode='reaction', actor=1, board=(), enemy=(), weapon=True):
        self.donor, self.mode = donor, mode
        r = fixture(donor, mode)
        hero = HEROES[r.card(donor).metadata.classes[0]]
        root = parts(donor, mode)[1]
        own_board = (*board, WATCH) if mode in ('wait', 'fail') else board
        return Game.from_scenario(Scenario(tuple(PlayerSetup(hero,
            hand=(root, KILL, MUTE, STEAL, HERO_ATTACK) if p == actor else (),
            board=own_board if p == actor else enemy, deck=(COIN,)*20,
            weapon_card_id=WEAPON if weapon else None, mana=30, max_mana=30, mana_cap=30)
            for p in (1, 2)), active_player=actor, seed=522, generation_context=CTX), r)

    def play(self, g, cid, target=None):
        return super().play(g, cid, target, player=g.state.active_player)

    def manufacture(self, g, half=None):
        base, root, _ = parts(self.donor, self.mode)
        self.play(g, root)
        half = half or ('bottom' if self.mode in ('body', 'death') else 'top')
        cid = AssembleRecipe(base, self.donor, half).card_id
        q = g.state.pending_choice
        option = next(x for x in q.options if x.card_id == cid)
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        return cid

    def attack(self, g, player=None):
        player = player or g.state.active_player
        g.apply(Attack(player, g.state.players[player].hero_id, g.state.players[3-player].hero_id))

    def draws(self, g, source):
        return [x for x in g.state.draw_history if x.source_id == source and x.parent_id is None]

    def tokens(self, g, cid, player=1):
        return [g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id == cid]

    def assert_body(self, g, donor, source, natural=False):
        children = cards.load_batch()['fixed_children']
        if donor in (FLAMER, SCYTHE):
            child = children['overdrive' if donor == FLAMER else 'soul']
            self.assertEqual(sum(g.state.entities[i].card_id == child for i in g.state.players[1].hand), 1)
        elif donor == MACE:
            self.assertEqual([(x.card_id, x.outcome) for x in self.draws(g, source)], [(COIN, 'hand')])
        elif donor == AXE:
            targets = [g.state.entities[i] for i in g.state.players[2].board]
            self.assertEqual([e.health for e in targets], [19])
            rows = [x.health_result for x in g.state.damage_history]
            self.assertTrue(rows)
            self.assertTrue(all(x.damage_kind == DamageKind.MINION_ABILITY.value and
                x.source_card_id == g.state.entities[source].card_id for x in rows))
        else:
            key, count = ('grub', 1) if donor == CLAWS else ('ghoul', 1) if donor == CANNON else ('elemental', 2)
            tokens = self.tokens(g, children[key])
            printed = g.registry.card(children[key])
            self.assertEqual(len(tokens), count)
            self.assertTrue(all((x.attack, x.max_health, x.keywords) ==
                (printed.attack, printed.health, set(printed.keywords)) for x in tokens))
            if natural:
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board[1:1+count]],
                    [children[key]]*count)

    def test_complete_fifteen_records_twenty_faces_and_exact_native_profiles(self):
        d = cards.load_batch()
        r = fixture()
        rows = {x['record']['id']: x for x in d['existing_dependencies']}
        self.assertEqual(len(rows), 15)
        self.assertEqual(len(d['official_observations']), 20)
        for cid, row in rows.items():
            self.assertEqual(batch.canonical(asdict(r.card(cid))), row['definition_sha256'])
        for obs in d['official_observations']:
            p = Path(obs['response_file'])
            self.assertEqual(batch.sha(p), obs['response_sha256'])
            data = json.loads(p.read_text(encoding='utf-8-sig'))
            raw = rows[obs['card_id']]['record']
            self.assertEqual([x for x in data['cards'] if x['id'] == raw['dbf_id']], [obs['face']])
            batch.check_face(raw, obs['face'], obs['locale'])
        for cid in cards.SOURCES:
            profile = r.assemble_reaction_sources[cid]
            self.assertIs(type(profile), AssembleWeaponReactionSource)
            self.assertEqual(profile.definition_sha256, rows[cid]['definition_sha256'])
            self.assertEqual(profile.original_behavior_id, r.card(cid).triggers[0].behavior_id)
            self.assertEqual(profile.source_kind, CardType.WEAPON)
        for amendment in (d['draw_amendment'], *d['body_amendments']):
            old = amendment['old_full_template']
            now = json.loads(json.dumps(asdict(r.assemble_templates[amendment['card_id']])))
            now['suffix']['allowed_timings'] = old['suffix']['allowed_timings']
            self.assertEqual(now, old)

    def test_all_seven_actual_prefixes_draw_after_original_hero_attack_without_weapon_body(self):
        children = cards.load_batch()['fixed_children']
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                g = self.game(donor)
                cid = self.manufacture(g)
                source = self.play(g, cid)
                mana = g.state.players[1].mana
                self.assertIsNone(g.registry.card(cid).deathrattle)
                self.assertFalse(self.draws(g, source))
                weapon = g.state.players[1].weapon_id
                self.attack(g)
                self.assertEqual([(x.card_id, x.outcome) for x in self.draws(g, source)], [(COIN, 'hand')])
                self.assertEqual(g.state.players[1].mana, mana)
                self.assertEqual(g.state.entities[weapon].durability, 3)
                self.assertFalse(any(g.state.entities[i].card_id in children.values() for i in g.state.players[1].hand))
                self.assertFalse(any(g.state.entities[i].card_id in children.values() for i in g.state.players[1].board))
                self.assertEqual(g.state.character_attack_history[-1].terminal.status, 'completed')

    def test_other_seat_last_weapon_use_keeps_minion_prefix_independent_of_retired_weapon(self):
        g = self.game(HAMMER, 'last', actor=2)
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.attack(g)
        self.assertEqual(len(self.draws(g, source)), 1)
        self.assertIsNone(g.state.players[2].weapon_id)
        event = next(x for x in reversed(g.events) if x.kind == 'attack_finished')
        native = g.registry.card(HAMMER).triggers[0].behavior_id
        self.assertEqual(g.registry.behavior(native)(RuleContext(g.state, source, 2, event=event)), ())

    def test_unarmed_hero_can_trigger_the_borrowed_prefix(self):
        g = self.game(FLAMER, weapon=False)
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.play(g, HERO_ATTACK)
        self.attack(g)
        self.assertEqual(len(self.draws(g, source)), 1)
        self.assertIsNone(g.state.players[1].weapon_id)

    def test_opponent_hero_and_own_minion_do_not_consume_owner_hero_prefix(self):
        g = self.game()
        cid = self.manufacture(g)
        source = self.play(g, cid)
        g.apply(EndTurn(1))
        self.attack(g)
        self.assertFalse(self.draws(g, source))
        g.apply(EndTurn(2))
        g.apply(Attack(1, source, g.state.players[2].hero_id))
        self.assertFalse(self.draws(g, source))
        self.attack(g)
        self.assertEqual(len(self.draws(g, source)), 1)

    def test_silence_death_and_current_controller_use_the_existing_minion_lifecycle(self):
        for helper in (MUTE, KILL, STEAL):
            with self.subTest(helper=helper):
                g = self.game()
                cid = self.manufacture(g)
                source = self.play(g, cid)
                self.play(g, helper, source)
                self.attack(g)
                self.assertFalse(self.draws(g, source))
                if helper == STEAL:
                    g.apply(EndTurn(1))
                    self.attack(g)
                    row, = self.draws(g, source)
                    self.assertEqual(row.player_id, 2)

    def test_all_seven_battlecry_bodies_use_minion_source_and_public_effects(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                g = self.game(donor, 'body', board=(POWER, MULT), enemy=(FILL,))
                cid = self.manufacture(g)
                source = self.play(g, cid)
                self.assertFalse(g.state.character_attack_history)
                self.assert_body(g, donor, source)
                self.assertEqual(g.state.players[1].weapon_id,
                    next(i for i, e in g.state.entities.items() if e.card_id == WEAPON and e.controller == 1))

    def test_six_changed_natural_death_bodies_keep_real_death_slot_and_source(self):
        for donor in (FLAMER, CLAWS, SCYTHE, CANNON, AXE, HAMMER):
            with self.subTest(donor=donor):
                g = self.game(donor, 'death', board=(FILL, FILL), enemy=(FILL,))
                cid = self.manufacture(g)
                source = self.entity(g, cid).id
                g.apply(PlayCard(1, source, position=1))
                self.play(g, KILL, source)
                self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
                self.assert_body(g, donor, source, natural=True)

    def test_mace_draw_over_loot_draw_is_correctly_filtered_as_unchanged(self):
        g = self.game(MACE, 'death')
        self.play(g, FLESH)
        choice = g.state.pending_choice
        ids = {x.card_id for x in choice.options}
        self.assertNotIn(AssembleRecipe(LOOT, MACE, 'bottom').card_id, ids)
        top = AssembleRecipe(LOOT, MACE, 'top').card_id
        self.assertIn(top, ids)
        option = next(x for x in choice.options if x.card_id == top)
        g.apply(SelectChoice(choice.player_id, choice.id, (option.id,)))
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(self.entity(g, top).card_id, top)

    def test_fire_fly_original_body_runs_after_hero_attack_without_claw_summon(self):
        g = self.game(CLAWS, 'body')
        cid = self.manufacture(g, 'top')
        self.play(g, cid)
        self.assertFalse(any(g.state.entities[i].card_id == 'UNG_809t1' for i in g.state.players[1].hand))
        self.attack(g)
        self.assertEqual(sum(g.state.entities[i].card_id == 'UNG_809t1' for i in g.state.players[1].hand), 1)
        self.assertFalse(self.tokens(g, cards.load_batch()['fixed_children']['grub']))

    def test_lifedrinker_original_body_follows_actual_hero_combat_and_heals_its_controller(self):
        g = self.game(HAMMER, 'body', enemy=(FILL,))
        cid = self.manufacture(g, 'top')
        self.play(g, cid)
        g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].board[0]))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health, 19)
        self.assertFalse(self.tokens(g, cards.load_batch()['fixed_children']['elemental']))

    def test_generated_ghoul_keeps_original_charge_and_own_end_death(self):
        g = self.game(CANNON, 'death')
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.play(g, KILL, source)
        ghoul, = self.tokens(g, cards.load_batch()['fixed_children']['ghoul'])
        self.assertIn(Keyword.CHARGE, ghoul.keywords)
        count = len(g.state.death_history)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[ghoul.id].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.death_history), count+1)

    def test_attack_draw_wait_restores_clones_replays_and_completes_same_attack(self):
        g = self.game(HAMMER, 'wait')
        cid = self.manufacture(g)
        self.play(g, cid)
        self.attack(g)
        self.assertIsNotNone(g.state.pending_choice)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate completed-hero-attack'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        reader = fixture(HAMMER, 'wait', 'independent-reader')
        self.assertIsNot(reader, g.registry)
        legs = (g, Game.from_snapshot(json.loads(json.dumps(saved)), reader), g.clone(), replay(build_replay(g), reader))
        for other in legs:
            self.assertEqual(other.snapshot(), saved)
            self.choose(other)
            self.assertIsNone(other.state.pending_choice)
        self.assertTrue(all(other.snapshot() == g.snapshot() for other in legs))
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            for key in ('rng_state', 'resolution_frame', 'submitted_cost', 'hand_entry_id'):
                self.assertNotIn('"'+key+'"', view)

    def test_late_draw_failure_rolls_back_whole_hero_attack_weapon_health_draw_and_rng(self):
        g = self.game(HAMMER, 'fail')
        cid = self.manufacture(g)
        self.play(g, cid)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate completed-hero-attack'):
            self.attack(g)
        self.assertEqual(g.snapshot(), saved)

    def test_unknown_eligible_weapon_adapter_is_not_cropped_and_rolls_back_real_producer(self):
        g = self.game(HAMMER, 'missing')
        saved = g.snapshot()
        with self.assertRaises((ResolutionError, ValueError)):
            self.play(g, FLESH)
        self.assertEqual(g.snapshot(), saved)
        self.assertIn(HAMMER, [x.card_id for x in g.registry.pool(POOL_ID, CTX).members])

    def test_old_default_save_is_rejected_by_new_core_with_same_snapshot_schema(self):
        from hs_sim.engine.representative import build_registry as defaults
        root = Path(__file__).resolve().parents[1]
        before = batch.read_registry_observation(root/'tests/fixtures/history/card-integration-20261014/k521-native-weapon-fragments/after-runtime-reference-02.json', root=root, input_paths=fixture_input_map())
        r = defaults()
        self.assertEqual(r.fingerprint(), before['default_fingerprint'])
        self.assertEqual(before['default_snapshot']['schema_version'], 587)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(before['default_snapshot'], r)


class WeaponReactionSourceContractTests(unittest.TestCase):
    def test_old_minion_and_new_weapon_source_types_do_not_impersonate_each_other(self):
        r = unadapted()
        d = cards.load_batch()
        row = d['existing_dependencies'][0]
        declaration = d['reviewed_projections'][0]
        before = r.fingerprint()
        with self.assertRaises(ValueError):
            r.register_assemble_reaction_source(AssembleReactionSource(FLAMER, 'attack_finished',
                declaration['original_behavior_id'], cards.CONDITION))
        with self.assertRaises(ValueError):
            r.register_assemble_reaction_source(AssembleWeaponReactionSource(LOOT,
                r.card(LOOT).deathrattle, cards.CONDITION, batch.canonical(asdict(r.card(LOOT)))))
        valid = AssembleWeaponReactionSource(FLAMER, declaration['original_behavior_id'],
            cards.CONDITION, row['definition_sha256'])
        for changes in ({'definition_sha256': '0'*64}, {'original_behavior_id': r.card(HAMMER).triggers[0].behavior_id}):
            with self.assertRaises(ValueError):
                r.register_assemble_reaction_source(replace(valid, **changes))
        for changes in ({'event': 'card_played'}, {'source_kind': 'weapon'}, {'definition_sha256': 'bad'}):
            with self.assertRaises(ValueError):
                replace(valid, **changes)
        self.assertEqual(r.fingerprint(), before)

    def test_weapon_profile_projection_pin_condition_and_plain_prefix_must_match(self):
        r = unadapted()
        cards.register_assemble_hero_attack_weapon_fragments(r)
        projection = r._assemble_projections.pop(HAMMER)
        profile = r._assemble_reaction_sources.pop(HAMMER)
        with self.assertRaises(ValueError):
            r.register_assemble_projection(projection)
        r.register_assemble_reaction_source(profile)
        for changed in (
                replace(projection, definition_sha256='0'*64),
                replace(projection, prefix=AssemblePrefix('attack_finished', condition_id='cards.assemble_attack_finished.self_attack')),
                replace(projection, prefix=AssemblePrefix('attack_finished', keywords=(Keyword.TAUNT,), condition_id=cards.CONDITION))):
            with self.assertRaises(ValueError):
                r.register_assemble_projection(changed)
        with self.assertRaises(ValueError):
            r.validate()
        r.register_assemble_projection(projection)
        r.validate()
        before = r.fingerprint()
        with self.assertRaises(ValueError):
            r.register_assemble_reaction_source(profile)
        self.assertEqual(r.fingerprint(), before)
        with self.assertRaises(TypeError):
            r.assemble_reaction_sources[HAMMER] = profile
        r.freeze()
        with self.assertRaises(ValueError):
            r.register_assemble_reaction_source(profile)

    def test_full_child_and_current_draw_amendment_conflicts_reject_before_installation(self):
        for conflict in ('child', 'draw'):
            with self.subTest(conflict=conflict):
                r = unadapted()
                before = r.fingerprint()
                data = deepcopy(cards.load_batch())
                if conflict == 'child':
                    data['existing_dependencies'][-1]['definition_sha256'] = '0'*64
                else:
                    data['draw_amendment']['old_full_template']['suffix']['allowed_timings'].remove('on_play')
                with patch.object(cards, 'load_batch', lambda: data):
                    with self.assertRaises(TargetValidationError):
                        cards.register_assemble_hero_attack_weapon_fragments(r)
                self.assertEqual(r.fingerprint(), before)


if __name__ == '__main__':
    unittest.main()
