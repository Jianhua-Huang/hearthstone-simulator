"""Whole-budget SPELL combinations and strict restore boundaries; local policy, not CN calibration."""
from pathlib import Path
from copy import deepcopy
import hashlib, json, sys, time, unittest, zipfile
from hs_sim.engine import CardDefinition, CardType, Game, PlayerSetup, Scenario, Registry, HealthRule, HealthFlow, HealthOp, HealthLayer, DamageKind, Keyword, PlayCard, SelectChoice, ResolutionError, RecoverHero, RandomSplitDamage, SplitDamageScope
from hs_sim.engine.effects import ChoiceOption, RequestChoice, RandomDamage, EquipWeapon, Summon, GainArmor
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.replay import build_replay, replay
import ast, hashlib, json, sys, time, unittest, zipfile
from hs_sim.engine import CardDefinition, CardType, Game, PlayerSetup, Scenario, Registry, HealthRule, HealthFlow, HealthOp, HealthLayer, DamageKind, Keyword, PlayCard, SelectChoice, SnapshotError, ResolutionError, RecoverHero, RandomSplitDamage, SplitDamageScope
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine import CardDefinition, CardType, Game, PlayerSetup, Scenario, Registry, HealthRule, HealthFlow, HealthOp, HealthLayer, DamageKind, Keyword, PlayCard, SelectChoice, ResolutionError, RecoverHero, RewindSpec, RandomSplitDamage, SplitDamageScope
from hs_sim.engine.effects import ChoiceOption, RequestChoice, RandomDamage, EquipWeapon, Summon, GainArmor, Damage
from hs_sim.engine.spell_casts import CastSpell
import ast, hashlib, json, random, sys, time, unittest, zipfile
from hs_sim.engine import CardDefinition, CardType, Game, PlayerSetup, Scenario, Registry, HealthRule, HealthFlow, HealthOp, HealthLayer, DamageKind, Keyword, PlayCard, SelectChoice, ResolutionError, RecoverHero, RandomSplitDamage, SplitDamageScope, TriggerSpec, HealthLossReplacementSpec, CastWhenDrawnSpec, SpellRepeatSpec, CounterPolicySpec, GrantCounterPolicy
from hs_sim.engine.effects import ChoiceOption, RequestChoice, RandomDamage, EquipWeapon, Summon, GainArmor, Damage, Draw, ChangeControl, Destroy
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine import SnapshotError
from hs_sim.engine.random_split_damage import DeliverSplitPacket
from hs_sim.engine import CardDefinition, CardType, Game, PlayerSetup, Scenario, Registry, HealthRule, HealthFlow, HealthOp, HealthLayer, DamageKind, Keyword, PlayCard, SelectChoice, ResolutionError, RecoverHero, RandomSplitDamage, SplitDamageScope, PlayerEffectSpec
from hs_sim.engine.effects import ChoiceOption, RequestChoice, RandomDamage, EquipWeapon, Summon, GainArmor, Damage, DamageBatch
from hs_sim.engine.player_effects import AddPlayerEffect

def initial_registry():
    r = Registry('v155-first-public-whole-budget-combinations')

    def split(c, amount=5, relation='enemy', kinds=(CardType.HERO,), callback=None):
        return [RandomSplitDamage(c.player_id, c.cast.id, c.source_id, amount, SplitDamageScope(relation, kinds), callback)]

    def after(c):
        v = health_result(c.event)
        if v.split_packet.index != 1:
            return []
        bad = (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), EquipWeapon(1, 'invalid'))
        return [RequestChoice(1, (ChoiceOption('ok', 'Continue original budget', ()), ChoiceOption('bad', 'Rollback RNG failure', bad)), c.source_id)]

    def provider_dr(c):
        return [Summon(1, 'body'), RequestChoice(1, (ChoiceOption('ok', 'Complete old deathrattle', ()),), c.source_id)]
    for name, body in {'enemy5': lambda c: split(c), 'friendly5': lambda c: split(c, relation='friendly', kinds=(CardType.MINION,)), 'enemy7': lambda c: split(c, 7), 'enemy3': lambda c: split(c, 3), 'zero': lambda c: split(c, 0), 'empty': lambda c: split(c, 3, kinds=(CardType.MINION,)), 'waiting3': lambda c: split(c, 3, callback='after'), 'after': after, 'provider_dr': provider_dr, 'hero_save': lambda c: [RequestChoice(c.player_id, (ChoiceOption('save', 'Save physical Hero', (RecoverHero(c.hero_lethal, 5),)),), c.source_id)]}.items():
        r.register_behavior(name, body)
    for card in (CardDefinition('hero', 'Hero', CardType.HERO, health=30), CardDefinition('fragile', 'One-health Hero', CardType.HERO, health=1), CardDefinition('savehero', 'Five-health Hero', CardType.HERO, health=5, deathrattle='hero_save'), CardDefinition('immunehero', 'Immune Hero', CardType.HERO, health=30, keywords=(Keyword.IMMUNE,)), CardDefinition('floorhero', 'Floor Hero', CardType.HERO, health=1, health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.FLOOR, 1, layer=HealthLayer.TARGET, target_relation='self'),)), CardDefinition('provider', 'Fragile bonus source', CardType.MINION, health=1, spell_damage=2, deathrattle='provider_dr'), CardDefinition('bonus', 'Bonus source', CardType.MINION, health=20, spell_damage=2), CardDefinition('body', 'Later physical target', CardType.MINION, health=10), CardDefinition('invalid', 'Invalid equipment', CardType.MINION, health=1)):
        r.register_card(card)
    for name in ('enemy5', 'friendly5', 'enemy7', 'enemy3', 'zero', 'empty', 'waiting3'):
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=1, on_play=name))
    return r

class WholeBudgetInitialTests(unittest.TestCase):
    registry = staticmethod(initial_registry)

    def game(self, spell, board=(), enemy='hero'):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=(spell,), board=board, mana=10, max_mana=10), PlayerSetup(enemy)), seed=155), self.registry())

    def cast(self, g):
        g.apply(PlayCard(1, g.state.players[1].hand[0]))

    def choose(self, g, key):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (key,)))

    def values(self, g):
        return [v for e in g.events if (v := health_result(e)) is not None and v.split_packet is not None]

    def portable(self, g, label):
        snap = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(deepcopy(snap), self.registry()).snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), self.registry()).snapshot(), snap)
        for player in (1, 2):
            public = json.dumps(g.observe(player)) + json.dumps(g.player_events(player)) + json.dumps(g.for_player(player).legal_actions())
            for key in ('split_damage_history', 'split_packet', 'source_allocation', 'rng_before', 'rng_after', 'contributions', 'resolution_frame'):
                self.assertNotIn('"' + key + '"', public)
        return snap

    def test_total_five_plus_two_is_seven_spell_units_with_one_payment(self):
        g = self.game('enemy5', ('bonus',))
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual((root.request.amount, root.quote.spell_bonus, root.quote.budget, len(root.packets)), (5, 2, 7, 7))
        self.assertTrue(root.completed)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 23)
        self.assertEqual([(v.base_amount, v.spell_bonus, v.modified_amount, v.damage_kind) for v in self.values(g)], [(1, 0, 1, 'spell')] * 7)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(g.state.players[1].mana, 9)
        self.portable(g, 'seven-singleton-units-original-budget')

    def test_first_unit_kills_bonus_source_original_DR_wait_then_new_target_uses_remaining_six(self):
        g = self.game('friendly5', ('provider',))
        original = g.state.players[1].board[0]
        self.cast(g)
        self.assertEqual(g.state.pending_choice.source_id, original)
        root = g.state.split_damage_history[0]
        self.assertEqual(root.quote.budget, 7)
        self.assertEqual(len(root.packets), 1)
        self.assertFalse(root.packets[0].completed)
        self.assertEqual(len(g.state.players[1].board), 1)
        new = g.state.players[1].board[0]
        self.assertNotEqual(new, original)
        self.portable(g, 'old-source-deathrattle-new-target-waiting')
        self.choose(g, 'ok')
        root = g.state.split_damage_history[0]
        self.assertEqual(g.state.entities[new].health, 4)
        self.assertEqual([v.target_id for v in self.values(g)], [original] + [new] * 6)
        self.assertEqual([p.selection.selected.allocation.entity_id for p in root.packets], [original] + [new] * 6)
        self.assertTrue(root.completed)
        self.portable(g, 'original-seven-budget-after-provider-death')

    def test_fifth_unit_opens_Hero_recovery_before_remaining_two(self):
        g = self.game('enemy7', enemy='savehero')
        hero = g.state.players[2].hero_id
        self.cast(g)
        self.assertEqual(g.state.pending_choice.player_id, 2)
        root = g.state.split_damage_history[0]
        self.assertEqual(len(root.packets), 5)
        self.assertFalse(root.packets[-1].completed)
        self.portable(g, 'fifth-unit-Hero-save-original-budget-tail')
        self.choose(g, 'save')
        self.assertEqual(g.state.entities[hero].health, 3)
        self.assertEqual(len(g.state.split_damage_history[0].packets), 7)
        self.assertTrue(g.state.split_damage_history[0].completed)
        self.assertEqual(g.state.status, 'playing')
        self.portable(g, 'all-seven-after-original-Hero-recovery')

    def test_terminal_first_unit_interrupts_original_remaining_budget(self):
        g = self.game('enemy3', enemy='fragile')
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual(len(root.packets), 1)
        self.assertTrue(root.interrupted)
        self.assertEqual(root.reason, 'terminal')
        self.assertEqual(g.state.winner, 1)
        self.assertEqual(len(self.values(g)), 1)
        self.portable(g, 'terminal-one-of-three-original-units')

    def test_true_zero_and_initial_empty_pool_keep_rng_and_record_explicit_reason(self):
        for spell, reason in (('zero', 'exhausted'), ('empty', 'empty_pool')):
            with self.subTest(spell=spell):
                g = self.game(spell)
                before = g.snapshot()['rng_state']
                self.cast(g)
                root = g.state.split_damage_history[0]
                self.assertEqual(root.reason, reason)
                self.assertEqual(root.packets, ())
                self.assertEqual(g.snapshot()['rng_state'], before)
                self.assertEqual(self.values(g), [])
                self.portable(g, spell + '-no-draw')

    def test_first_result_true_waiting_and_rng_error_rollback_no_redraw(self):
        g = self.game('waiting3')
        self.cast(g)
        snap = self.portable(g, 'first-unit-result-waiting')
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), snap)
        self.portable(g, 'original-first-selection-rollback')
        self.choose(g, 'ok')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
        self.assertEqual(len(self.values(g)), 3)
        self.portable(g, 'three-after-first-result-callback')

    def test_immune_and_floor_prevention_each_consume_all_three_original_units(self):
        for hero, reason in (('immunehero', 'immune'), ('floorhero', None)):
            with self.subTest(hero=hero):
                g = self.game('enemy3', enemy=hero)
                self.cast(g)
                root = g.state.split_damage_history[0]
                self.assertEqual(len(root.packets), 3)
                self.assertTrue(root.completed)
                values = self.values(g)
                self.assertEqual([v.prevention for v in values], [reason] * 3)
                self.assertEqual([v.damage_dealt for v in values], [0] * 3)
                if hero == 'floorhero':
                    self.assertEqual([v.floor_prevented for v in values], [1] * 3)
                self.portable(g, hero + '-all-original-budget-spent')

def integrity_rehash(s):
    s['events_hash'] = canonical_hash(s['events'])
    s['state_hash'] = canonical_hash({k: v for k, v in s.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return s

class SplitIntegrityNegatives(WholeBudgetInitialTests):
    registry = staticmethod(initial_registry)

    def reject(self, s, label):
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k: v for k, v in s.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(s, self.registry())
        self.assertNotIn('digest mismatch', str(error.exception).lower())

    def test_closed_future_packet_health_link_rejected(self):
        g = self.game('enemy5', ('bonus',))
        self.cast(g)
        snap = g.snapshot()
        e = next((e for e in snap['events'] if e['kind'] == 'health_resolved' and dict(e['data']['result'])['split_packet'] is not None))
        link = dict(e['data']['result'])['split_packet']
        next((r for r in link if r[0] == 'root_id'))[1] = 999999
        self.reject(snap, 'future-closed-result-link')

    def test_closed_result_association_cannot_point_to_other_event(self):
        g = self.game('enemy5', ('bonus',))
        self.cast(g)
        snap = g.snapshot()
        snap['state']['split_damage_history'][0]['packets'][0]['result_events'][0] -= 1
        self.reject(snap, 'closed-root-borrows-other-event')

    def test_closed_root_cannot_disappear_without_real_retry(self):
        g = self.game('enemy5', ('bonus',))
        self.cast(g)
        snap = g.snapshot()
        snap['state']['split_damage_history'] = []
        self.reject(snap, 'closed-root-deleted-without-Retry')

    def test_waiting_root_and_packet_real_tails_preserve_original_order(self):
        g = self.game('waiting3')
        self.cast(g)
        original = g.snapshot()
        for name in ('drop_root', 'drop_packet', 'early_root', 'extra_delivery', 'changed_budget'):
            with self.subTest(name=name):
                snap = deepcopy(original)
                work = snap['resolution_frame']['fields']['continuation']['tuple']
                if name.startswith('drop_'):
                    kind = 'FinishRandomSplitRoot' if name == 'drop_root' else 'FinishSplitPacket'
                    work[:] = [w for w in work if not w.get('type', '').endswith(kind)]
                elif name == 'early_root':
                    i = next((i for i, w in enumerate(work) if w.get('type', '').endswith('FinishRandomSplitRoot')))
                    work.insert(0, work.pop(i))
                elif name == 'extra_delivery':
                    work.insert(0, {'type': 'hs_sim.engine.random_split_damage.DeliverSplitPacket', 'fields': {'root_id': 1, 'index': 2}})
                else:
                    snap['state']['split_damage_history'][0]['quote']['budget'] = 1
                self.reject(snap, 'waiting-' + name)

def nested_registry():
    r = initial_registry()

    def nested_after(c):
        v = health_result(c.event)
        return [CastSpell(1, 'enemy3', c.source_id, choices='player')] if v.split_packet.index == 1 else []
    bodies = {'auto_wait': lambda c: [CastSpell(1, 'waiting3', c.source_id, choices='player')], 'nested2': lambda c: [RandomSplitDamage(c.player_id, c.cast.id, c.source_id, 2, on_result='nested_after')], 'nested_after': nested_after, 'fatal_right': lambda c: [Damage(c.state.players[2].hero_id, 99, c.source_id)], 'parent_hero_auto': lambda c: [RecoverHero(c.hero_lethal, 5), CastSpell(2, 'enemy7', c.source_id, choices='player')]}
    for name, body in bodies.items():
        r.register_behavior(name, body)
    for name in ('auto_wait', 'nested2', 'fatal_right'):
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=1, on_play=name))
    r.register_card(CardDefinition('retry_auto', 'Actual paid Retry with new CAST source', CardType.SPELL, cost=1, on_play='auto_wait', keywords=(Keyword.REWIND,), rewind=RewindSpec(1)))
    r.register_card(CardDefinition('parenthero', 'Parent recovered Hero', CardType.HERO, health=5, deathrattle='parent_hero_auto'))
    return r

class NestedRetryTests(WholeBudgetInitialTests):
    registry = staticmethod(nested_registry)

    def test_real_auto_CAST_budget_waiting_and_original_manual_tail(self):
        g = self.game('auto_wait')
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual(root.quote.cast.origin, 'effect')
        self.assertNotEqual(root.request.source_id, g.state.play_history[0].source_id)
        self.assertEqual(len(root.packets), 1)
        self.assertFalse(g.state.play_history[0].completed)
        self.portable(g, 'generated-CAST-first-budget-unit-waiting')
        self.choose(g, 'ok')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
        self.assertTrue(all((c.completed for c in g.state.cast_history)))
        self.assertTrue(g.state.play_history[0].completed)
        self.assertEqual(g.state.players[1].mana, 9)
        self.portable(g, 'generated-CAST-and-original-paid-tail-completed')

    def test_nested_callback_new_budget_has_own_source_quote_parent_and_unique_tails(self):
        g = self.game('nested2')
        self.cast(g)
        a, b = g.state.split_damage_history
        self.assertEqual((a.id, b.id, b.parent_id), (1, 2, 1))
        self.assertNotEqual(a.request.source_id, b.request.source_id)
        self.assertEqual((a.quote.budget, b.quote.budget), (2, 3))
        self.assertTrue(a.completed and b.completed)
        self.assertEqual([v.split_packet.root_id for v in self.values(g)], [1, 2, 2, 2, 1])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 25)
        self.portable(g, 'nested-child-budget-before-original-second-unit')

    def test_real_Retry_deletes_generated_CAST_source_but_keeps_old_results_and_monotonic_roots(self):
        g = self.game('retry_auto')
        self.cast(g)
        first = g.state.split_damage_history[0]
        old_source = first.request.source_id
        self.choose(g, 'ok')
        self.portable(g, 'first-real-CAST-budget-complete-before-Rewind-choice')
        self.assertTrue(any((o.id == 'retry' for o in g.state.pending_choice.options)))
        self.choose(g, 'retry')
        second = g.state.split_damage_history[0]
        self.assertGreater(second.id, first.id)
        self.assertNotEqual(second.request.source_id, old_source)
        self.assertNotIn(old_source, g.state.entities)
        self.assertEqual(len(second.packets), 1)
        self.portable(g, 'Retry-deleted-source-second-CAST-budget-waiting-old-events-retained')
        self.choose(g, 'ok')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual([v.split_packet.root_id for v in self.values(g)], [first.id] * 3 + [second.id] * 3)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
        self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual(len(g.state.play_history), 1)
        self.portable(g, 'two-budgets-kept-events-one-real-payment-after-Retry')

    def test_budget_inside_original_Hero_DR_auto_CAST_keeps_own_tail_around_child_save(self):
        g = Game.from_scenario(Scenario((PlayerSetup('savehero', hand=('fatal_right',), mana=10, max_mana=10), PlayerSetup('parenthero')), seed=15509), self.registry())
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual(root.request.player_id, 2)
        self.assertEqual(root.quote.cast.origin, 'effect')
        self.assertEqual(len(root.packets), 5)
        self.assertEqual(g.state.pending_choice.player_id, 1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 5)
        self.assertFalse(g.state.deathrattle_history[0].completed)
        self.portable(g, 'original-Hero-DR-CAST-budget-child-Hero-save-waiting')
        self.choose(g, 'save')
        self.assertEqual(g.state.status, 'playing')
        self.assertEqual(tuple((g.state.entities[g.state.players[p].hero_id].health for p in (1, 2))), (3, 5))
        self.assertTrue(g.state.split_damage_history[0].completed)
        self.assertTrue(all((x.completed for x in g.state.deathrattle_history)))
        self.assertTrue(all((x.phase == 'finished' for x in g.state.hero_lethal_history)))
        self.assertTrue(all((x.completed for x in g.state.cast_history)))
        self.portable(g, 'original-Hero-DR-and-child-budget-complete-after-seven-units')

def expanded_registry():
    r = initial_registry()

    def split(c, n=3, side='enemy', kinds=(CardType.HERO,), cb=None):
        return [RandomSplitDamage(c.player_id, c.cast.id, c.source_id, n, SplitDamageScope(side, kinds), cb)]

    def add_bonus(c):
        v = health_result(c.event)
        return [Summon(1, 'bonus')] if v.split_packet.index == 1 else []

    def prepare_pool(c):
        sleeper = next((i for i in c.state.players[2].board if c.state.entities[i].card_id == 'sleepbody'))
        return [MakeDormant(sleeper, None), *split(c, kinds=(CardType.MINION,), side='any')]

    def reaction(c):
        v = health_result(c.event)
        if v is None or v.split_packet is None or v.split_packet.index != 1:
            return []
        return [RequestChoice(1, (ChoiceOption('change', 'Change the next pool', (ChangeControl(v.original_target_id, 2), Summon(1, 'body'), RandomDamage((c.state.players[2].hero_id,), 1, c.source_id))),), c.source_id)]

    def arm(c):
        target = c.state.entities[c.state.players[2].board[0]]
        return [GrantCounterPolicy(MinionReference.capture(target), CounterPolicySpec(CardType.SPELL), c.source_id)]
    bodies = {'growing3': lambda c: split(c, cb='add_bonus'), 'add_bonus': add_bonus, 'all3': lambda c: split(c, kinds=(CardType.MINION,), side='any'), 'prepare_pool': prepare_pool, 'friendly3': lambda c: split(c, side='friendly'), 'friendlyminion3': lambda c: split(c, side='friendly', kinds=(CardType.MINION,)), 'enemyminion3': lambda c: split(c, kinds=(CardType.MINION,)), 'reaction': reaction, 'reaction_driver': lambda c: [EquipWeapon(1, 'watchweapon'), *split(c, side='friendly', kinds=(CardType.MINION,))], 'arm': arm, 'draw_driver': lambda c: [Draw(1, 1, c.source_id)], 'history_driver': lambda c: [RecastSpell(1, next((x.id for x in c.state.cast_history if x.card_id == 'enemy3')), c.source_id)], 'hurt_then_split': lambda c: [Damage(c.state.players[1].hero_id, 10, c.state.players[1].hero_id), *split(c)], 'convert_split': lambda c: split(c)}
    for n, f in bodies.items():
        r.register_behavior(n, f)
    for n in ('growing3', 'all3', 'prepare_pool', 'friendly3', 'friendlyminion3', 'enemyminion3', 'arm', 'draw_driver', 'history_driver', 'convert_split', 'reaction_driver'):
        r.register_card(CardDefinition(n, n, CardType.SPELL, cost=1, on_play=n, metadata=CardMetadata(False, (CardClass.MAGE,), None)))
    r.register_card(CardDefinition('lifesplit', 'Intrinsic Lifesteal', CardType.SPELL, cost=1, on_play='hurt_then_split', keywords=(Keyword.LIFESTEAL,)))
    r.register_card(CardDefinition('poisonsplit', 'Poison unit', CardType.SPELL, cost=1, on_play='enemyminion3', keywords=(Keyword.POISONOUS,)))
    r.register_card(CardDefinition('drawsplit', 'Actual drawn split', CardType.SPELL, on_play='enemy3', keywords=(Keyword.CASTS_WHEN_DRAWN,), cast_when_drawn=CastWhenDrawnSpec(replacement=False)))
    for card in (CardDefinition('repeat', 'Repeat all actual spells', CardType.MINION, health=10, spell_repeats=(SpellRepeatSpec(class_mode='any'),)), CardDefinition('stealthbody', 'Stealthed random target', CardType.MINION, health=20, keywords=(Keyword.STEALTH,)), CardDefinition('immunebody', 'Immune random target', CardType.MINION, health=20, keywords=(Keyword.IMMUNE,)), CardDefinition('sleepbody', 'Dormant excluded', CardType.MINION, health=20), CardDefinition('place', 'Location excluded', CardType.LOCATION, durability=3, on_use='enemy3'), CardDefinition('rebornbody', 'Two physical lives', CardType.MINION, health=1, keywords=(Keyword.REBORN,)), CardDefinition('watchweapon', 'Ordinary health listener', CardType.WEAPON, durability=3, triggers=(TriggerSpec('health_resolved', 'reaction'),)), CardDefinition('shieldhero', 'Shield and armor', CardType.HERO, health=30, keywords=(Keyword.DIVINE_SHIELD,)), CardDefinition('guard', 'Health debit replacement', CardType.MINION, health=20, health_loss_replacements=(HealthLossReplacementSpec(),)), CardDefinition('scale', 'SOURCE double', CardType.MINION, health=20, health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2, source_relation='friendly', damage_kinds=(DamageKind.SPELL,)),)), CardDefinition('caphero', 'TARGET add and cap', CardType.HERO, health=30, health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.ADD, 1, layer=HealthLayer.TARGET, target_relation='self'), HealthRule(HealthFlow.DAMAGE, HealthOp.CAP, 2, layer=HealthLayer.TARGET, target_relation='self'))), CardDefinition('redirect', 'MINION to own Hero', CardType.MINION, health=20, health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.REDIRECT, layer=HealthLayer.TARGET, target_relation='self', redirect_to='friendly_hero'),)), CardDefinition('converter', 'Convert spell damage', CardType.MINION, health=20, health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.CONVERT, source_relation='friendly', damage_kinds=(DamageKind.SPELL,)),)), CardDefinition('hurt', 'Damage then add converter', CardType.SPELL, cost=1, on_play='hurt'), CardDefinition('mech', 'Physical host', CardType.MINION, health=20, metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',))), CardDefinition('mag', 'Material is not another weight', CardType.MINION, health=3, keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',), metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',)))):
        r.register_card(card)
    r.register_behavior('hurt', lambda c: [Damage(c.state.players[2].hero_id, 5, c.source_id), Summon(1, 'converter')])
    return r

class ExpandedSplitTests(WholeBudgetInitialTests):
    registry = staticmethod(expanded_registry)

    def scenario(self, hand, left=(), right=(), hero1='hero', hero2='hero', armor2=0, deck=()):
        return Game.from_scenario(Scenario((PlayerSetup(hero1, hand=hand, board=left, deck=deck, mana=10, max_mana=10), PlayerSetup(hero2, board=right, armor=armor2)), seed=15519), self.registry())

    def play_named(self, g, name, position=None):
        i = next((i for i in g.state.players[1].hand if g.state.entities[i].card_id == name))
        g.apply(PlayCard(1, i, position=position))

    def test_repeat_accepts_new_bonus_after_old_budget_stays_three(self):
        g = self.scenario(('growing3',), left=('repeat',))
        self.cast(g)
        a, b = g.state.split_damage_history
        self.assertEqual((a.quote.budget, b.quote.budget), (3, 5))
        self.assertEqual((len(a.packets), len(b.packets)), (3, 5))
        self.assertEqual([r.quote.cast.origin for r in (a, b)], ['hand', 'repeat'])
        self.assertEqual([r.quote.spell_bonus for r in (a, b)], [0, 2])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 22)
        self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual(len(g.state.play_history), 1)
        self.portable(g, 'repeat-two-real-CASTs-new-bonus-second-quote')

    def test_complete_both_MINION_pool_excludes_location_and_dormancy_keeps_stealth_and_immunity(self):
        g = self.scenario(('prepare_pool',), left=('body', 'place'), right=('stealthbody', 'immunebody', 'sleepbody'))
        expected = sorted((i for p in (1, 2) for i in g.state.players[p].board if g.state.entities[i].card_id not in ('place', 'sleepbody')))
        self.cast(g)
        root = g.state.split_damage_history[0]
        for p in root.packets:
            self.assertEqual([r.allocation.entity_id for r in p.selection.candidates], expected)
            probe = random.Random()
            probe.setstate(p.selection.rng_before)
            self.assertEqual(probe.choice(p.selection.candidates), p.selection.selected)
            self.assertEqual(probe.getstate(), p.selection.rng_after)
        self.portable(g, 'complete-both-MINION-pool-physical-only')

    def test_magnetic_material_never_adds_a_second_physical_weight(self):
        g = self.scenario(('mag', 'all3'), left=('mech',), right=('body',))
        host = g.state.players[1].board[0]
        self.play_named(g, 'mag', position=0)
        self.assertEqual(g.state.players[1].board, [host])
        self.play_named(g, 'all3')
        root = g.state.split_damage_history[0]
        expected = sorted((host, g.state.players[2].board[0]))
        self.assertTrue(g.state.magnetic_history)
        self.assertTrue(all(([r.allocation.entity_id for r in p.selection.candidates] == expected for p in root.packets)))
        self.portable(g, 'fused-host-one-weight-all-three-units')

    def test_reborn_creates_new_physical_target_then_mid_pool_empty_has_no_extra_draw(self):
        g = self.scenario(('friendlyminion3',), left=('rebornbody',))
        old = g.state.players[1].board[0]
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual((root.quote.budget, len(root.packets), root.reason), (3, 2, 'empty_pool'))
        first, second = root.packets
        self.assertEqual(first.selection.selected.allocation.entity_id, old)
        self.assertNotEqual(second.selection.selected.allocation.entity_id, old)
        self.assertEqual(root.empty_selection.rng_before, second.selection.rng_after)
        self.assertEqual(root.empty_selection.rng_before, root.empty_selection.rng_after)
        self.assertEqual(len(self.values(g)), 2)
        self.assertEqual(g.state.players[1].board, [])
        self.portable(g, 'two-real-Reborn-lives-before-empty-remaining-budget')

    def test_zero_base_with_two_bonus_consumes_two_real_singleton_choices(self):
        g = self.scenario(('zero',), left=('bonus',))
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual((root.request.amount, root.quote.budget, len(root.packets)), (0, 2, 2))
        self.assertTrue(all((p.selection.rng_before != p.selection.rng_after for p in root.packets)))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)
        self.portable(g, 'zero-base-positive-whole-bonus-not-inert')

    def test_shield_then_armor_then_health_each_spends_one_budget_unit(self):
        g = self.scenario(('enemy5',), hero2='shieldhero', armor2=2)
        self.cast(g)
        v = self.values(g)
        self.assertEqual([x.prevention for x in v], ['divine_shield', None, None, None, None])
        self.assertEqual([x.armor_absorbed for x in v], [0, 1, 1, 0, 0])
        self.assertEqual([x.health_lost for x in v], [0, 0, 0, 1, 1])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)
        self.portable(g, 'shield-armor-health-five-units-no-refund')

    def test_lifesteal_auxiliary_results_have_no_extra_budget_identity(self):
        g = self.scenario(('lifesplit',))
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual(len(root.packets), 3)
        restored = [x for e in g.events if (x := health_result(e)) is not None and x.from_lifesteal]
        self.assertEqual(len(restored), 3)
        self.assertTrue(all((x.split_packet is None for x in restored)))
        self.assertEqual([x.health_gained for x in restored], [1] * 3)
        self.assertEqual(tuple((g.state.entities[g.state.players[p].hero_id].health for p in (1, 2))), (23, 27))
        self.portable(g, 'intrinsic-Lifesteal-three-auxiliary-results-one-budget')

    def test_poison_and_health_loss_replacement_share_existing_settlement(self):
        g = self.scenario(('poisonsplit',), right=('body',))
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual((len(root.packets), root.reason), (1, 'empty_pool'))
        self.assertEqual(g.state.players[2].board, [])
        self.assertEqual(self.values(g)[0].health_lost, 1)
        self.portable(g, 'Poison-positive-life-damage-kills-and-empties-pool')
        g = self.scenario(('friendly3',), left=('guard',))
        self.cast(g)
        v = self.values(g)
        h = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((h.health, h.max_health), (33, 33))
        self.assertEqual([x.health_replaced for x in v], [1] * 3)
        self.assertEqual(len(g.state.split_damage_history[0].packets), 3)
        self.portable(g, 'three-debit-replacements-do-not-refund-budget')

    def test_SOURCE_scale_and_TARGET_add_cap_are_per_packet_in_explicit_profile(self):
        g = self.scenario(('enemy3',), left=('scale',), hero2='caphero')
        self.cast(g)
        v = self.values(g)
        self.assertEqual([x.modified_amount for x in v], [2] * 3)
        self.assertTrue(all((len(x.rule_ids) == 3 for x in v)))
        self.assertEqual(g.state.split_damage_history[0].quote.budget, 3)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
        self.portable(g, 'three-local-unit-packets-share-numeric-layers')

    def test_redirect_and_conversion_keep_original_selection_and_unit_identity(self):
        g = self.scenario(('enemyminion3',), right=('redirect',))
        target = g.state.players[2].board[0]
        self.cast(g)
        v = self.values(g)
        hero = g.state.players[2].hero_id
        self.assertEqual([(x.original_target_id, x.target_id) for x in v], [(target, hero)] * 3)
        self.assertEqual(g.state.entities[target].health, 20)
        self.assertEqual(g.state.entities[hero].health, 27)
        self.portable(g, 'original-MINION-selections-redirected-to-Hero')
        g = self.scenario(('hurt', 'convert_split'))
        self.play_named(g, 'hurt')
        self.play_named(g, 'convert_split')
        self.assertEqual([x.flow for x in self.values(g)], ['healing'] * 3)
        self.assertTrue(all((x.converted and x.split_packet is not None for x in self.values(g))))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)
        self.portable(g, 'converted-three-units-heal-without-reallocation')

    def test_ordinary_health_reaction_true_waiting_changes_pool_and_rng_before_next_unit(self):
        g = self.scenario(('reaction_driver',), left=('body',))
        old = g.state.players[1].board[0]
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual(len(root.packets), 1)
        self.assertFalse(root.packets[0].completed)
        self.portable(g, 'ordinary-reaction-before-original-first-packet-finish')
        self.choose(g, 'change')
        root = g.state.split_damage_history[0]
        new = g.state.players[1].board[0]
        self.assertNotEqual(new, old)
        self.assertEqual(g.state.entities[old].controller, 2)
        self.assertEqual([p.selection.selected.allocation.entity_id for p in root.packets], [old, new, new])
        self.assertNotEqual(root.packets[0].selection.rng_after, root.packets[1].selection.rng_before)
        self.assertEqual(g.state.entities[new].health, 8)
        self.assertEqual(len(g.state.play_history), 1)
        self.portable(g, 'new-pool-after-ordinary-reaction-and-independent-RNG')

    def test_draw_history_origins_and_countered_manual_cast_have_distinct_budget_semantics(self):
        g = self.scenario(('draw_driver',), deck=('drawsplit',))
        self.cast(g)
        self.assertEqual(g.state.split_damage_history[0].quote.cast.origin, 'draw')
        self.assertEqual(g.state.players[1].mana, 9)
        self.portable(g, 'real-draw-CAST-budget')
        g = self.scenario(('enemy3', 'history_driver'))
        self.play_named(g, 'enemy3')
        self.play_named(g, 'history_driver')
        self.assertEqual([r.quote.cast.origin for r in g.state.split_damage_history], ['hand', 'history'])
        self.assertNotEqual(*[r.request.source_id for r in g.state.split_damage_history])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
        self.portable(g, 'history-new-source-new-budget')
        g = self.scenario(('arm', 'enemy3'), right=('body',))
        self.play_named(g, 'arm')
        before = g.snapshot()['rng_state']
        self.play_named(g, 'enemy3')
        self.assertEqual(g.state.split_damage_history, [])
        self.assertEqual(g.state.cast_history[-1].failure, 'countered')
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.portable(g, 'countered-payload-no-root-no-RNG')

def domain_registry():
    r = expanded_registry()

    def child(c):
        v = health_result(c.event)
        return [CastSpell(1, 'enemy3', c.source_id, choices='player')] if v.split_packet.index == 1 else []
    r.register_behavior('child', child)
    r.register_behavior('nested', lambda c: [RandomSplitDamage(1, c.cast.id, c.source_id, 2, on_result='child')])
    r.register_card(CardDefinition('nested', 'Nested child', CardType.SPELL, cost=1, on_play='nested'))
    return r

def domain_rehash(s):
    s['events_hash'] = canonical_hash(s['events'])
    s['state_hash'] = canonical_hash({k: v for k, v in s.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

def sync_closed(s, row):
    e = next((e for e in s['events'] if e['kind'] == 'split_damage_closed' and json.loads(e['data']['root'])['id'] == row['id']))
    e['data']['root'] = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

class DomainNegatives(WholeBudgetInitialTests):
    registry = staticmethod(domain_registry)
    scenario = ExpandedSplitTests.scenario

    def reject(self, s, label):
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k: v for k, v in s.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(s, self.registry())
        self.assertNotIn('digest mismatch', str(error.exception).lower())

    def pool_snapshot(self):
        g = self.scenario(('enemyminion3',), right=('body', 'body'))
        self.cast(g)
        self.portable(g, 'legitimate-complete-two-target-pools')
        return g.snapshot()

    def test_closed_unselected_candidate_requires_original_registered_and_allocated_physical_fact(self):
        original = self.pool_snapshot()
        for mode in ('unknown_card', 'future_allocation', 'wrong_relation'):
            with self.subTest(mode=mode):
                s = deepcopy(original)
                row = s['state']['split_damage_history'][0]
                p = next((p for p in row['packets'] if p['selection']['selected'] != p['selection']['candidates'][-1]))
                a = p['selection']['candidates'][-1]['allocation']
                if mode == 'unknown_card':
                    a['card_id'] = 'UNREGISTERED_ORIGINAL_CANDIDATE'
                elif mode == 'future_allocation':
                    a['entity_id'] = s['state']['next_entity_id'] + 100
                    a['next_entity_id'] = a['entity_id'] + 1
                else:
                    a['controller'] = 1
                sync_closed(s, row)
                self.reject(s, 'unselected-' + mode)

    def test_closed_quote_requires_real_CAST_allocation_domain(self):
        g = self.game('enemy3')
        self.cast(g)
        s = g.snapshot()
        row = s['state']['split_damage_history'][0]
        row['quote']['cast']['id'] = row['request']['cast_id'] = 999999
        sync_closed(s, row)
        self.reject(s, 'closed-future-CAST')

    def test_closed_child_cannot_erase_its_own_original_active_parent_interval(self):
        g = self.game('nested')
        self.cast(g)
        s = g.snapshot()
        row = s['state']['split_damage_history'][1]
        self.assertEqual(row['parent_id'], 1)
        row['parent_id'] = None
        sync_closed(s, row)
        self.reject(s, 'nested-child-erased-parent')

    def test_waiting_queue_cannot_add_an_orphan_delivery_or_choice_internal_control(self):
        g = self.game('waiting3')
        self.cast(g)
        original = g.snapshot()
        self.portable(g, 'legitimate-first-unit-waiting')
        for mode in ('orphan_delivery', 'choice_control'):
            with self.subTest(mode=mode):
                s = deepcopy(original)
                control = {'type': 'hs_sim.engine.random_split_damage.DeliverSplitPacket', 'fields': {'root_id': 999999 if mode == 'orphan_delivery' else 1, 'index': 2}}
                if mode == 'orphan_delivery':
                    s['resolution_frame']['fields']['continuation']['tuple'].insert(0, control)
                else:
                    s['resolution_frame']['fields']['options']['tuple'][0]['fields']['effects']['tuple'].append(control)
                self.reject(s, mode)

def hero_registry():
    r = initial_registry()

    def dual(c):
        return [DamageBatch(tuple((Damage(c.state.players[p].hero_id, 4, c.state.players[1].hero_id) for p in (1, 2)))), RandomSplitDamage(1, c.cast.id, c.source_id, 3, SplitDamageScope('enemy', (CardType.HERO,)))]

    def complete(c):
        row = json.loads(dict(c.event.data)['root'])
        if not row['completed']:
            raise ValueError('Completion callback preceded root completion')
        return [GainArmor(1, len(row['packets']))]
    r.register_behavior('dual', dual)
    r.register_behavior('complete', complete)
    r.register_behavior('persistent', lambda c: [AddPlayerEffect(1, 'long_bonus', c.source_id), RandomSplitDamage(1, c.cast.id, c.source_id, 5, on_complete='complete')])
    r.register_card(CardDefinition('dual', 'Damage plus converted intrinsic restore', CardType.SPELL, cost=1, on_play='dual', keywords=(Keyword.LIFESTEAL,)))
    r.register_card(CardDefinition('healconverter', 'Intrinsic heal to damage', CardType.MINION, health=20, health_rules=(HealthRule(HealthFlow.HEALING, HealthOp.CONVERT, source_relation='friendly'),)))
    r.register_card(CardDefinition('persistent', 'Persistent bonus producer', CardType.SPELL, cost=1, on_play='persistent'))
    r.register_player_effect(PlayerEffectSpec('long_bonus', 'persistent', spell_damage=2))
    for name, body in (('invalid_zero_cast', lambda c: [RandomSplitDamage(1, 999999, c.source_id, 0)]), ('invalid_empty_player', lambda c: [RandomSplitDamage(2, c.cast.id, c.source_id, 3, SplitDamageScope('enemy', (CardType.MINION,)))]), ('invalid_zero_callback', lambda c: [RandomSplitDamage(1, c.cast.id, c.source_id, 0, on_result='UNKNOWN_CALLBACK')])):
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=1, on_play=name))
    return r

class HeroOriginBoundaries(WholeBudgetInitialTests):
    registry = staticmethod(hero_registry)

    def test_single_packet_dual_Hero_opportunities_both_save_before_original_remaining_two(self):
        g = Game.from_scenario(Scenario((PlayerSetup('savehero', hand=('dual',), board=('healconverter',), mana=10, max_mana=10), PlayerSetup('savehero')), seed=15527), self.registry())
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual(len(root.packets), 1)
        self.assertEqual(tuple((g.state.entities[g.state.players[p].hero_id].health for p in (1, 2))), (0, 0))
        self.assertEqual(len(g.state.hero_lethal_history), 2)
        self.portable(g, 'single-budget-unit-both-Hero-opportunities-original-tail')
        first = g.state.pending_choice.player_id
        self.choose(g, 'save')
        self.assertNotEqual(g.state.pending_choice.player_id, first)
        self.assertEqual(len(g.state.split_damage_history[0].packets), 1)
        self.portable(g, 'first-Hero-saved-second-opportunity-before-more-budget')
        self.choose(g, 'save')
        self.assertEqual(g.state.status, 'playing')
        self.assertEqual(tuple((g.state.entities[g.state.players[p].hero_id].health for p in (1, 2))), (3, 3))
        self.assertEqual(len(g.state.split_damage_history[0].packets), 3)
        self.assertTrue(g.state.split_damage_history[0].completed)
        self.assertEqual(g.state.players[1].mana, 9)
        self.portable(g, 'both-saved-all-three-budget-units')

    def test_player_persistent_bonus_is_quoted_once_and_completion_callback_follows_closed_root(self):
        g = self.game('persistent')
        self.cast(g)
        root = g.state.split_damage_history[0]
        self.assertEqual((root.quote.spell_bonus, root.quote.budget, len(root.packets)), (2, 7, 7))
        self.assertEqual(len(root.quote.contributions), 1)
        self.assertIsNotNone(root.quote.contributions[0].player_effect)
        self.assertIsNone(root.quote.contributions[0].allocation)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 7)
        self.portable(g, 'persistent-player-quote-and-completed-root-callback')

    def test_zero_and_empty_paths_validate_true_active_CAST_issuer_and_callback_before_shortcut(self):
        for card in ('invalid_zero_cast', 'invalid_empty_player', 'invalid_zero_callback'):
            with self.subTest(card=card):
                g = self.game(card)
                before = g.snapshot()
                with self.assertRaises(ResolutionError):
                    self.cast(g)
                self.assertEqual(g.snapshot(), before)
                self.portable(g, card + '-complete-transaction-rollback')

def load_tests(loader, standard_tests, pattern):
    classes = (WholeBudgetInitialTests, SplitIntegrityNegatives, NestedRetryTests, ExpandedSplitTests, DomainNegatives, HeroOriginBoundaries)
    return unittest.TestSuite((cls(name) for cls in classes for name in vars(cls) if name.startswith('test_')))
