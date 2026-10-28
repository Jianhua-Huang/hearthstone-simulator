"""Real paid Sargeras, independent portals, future grants and portable continuations."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json, unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, sargeras_portal as native
from hs_sim.engine import (EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError,
    Scenario, SnapshotError, UseInteractable, UseMinionAbility)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, Draw, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.information import VIEW_VERSION
from hs_sim.engine.model import (BattlecryRepeatSpec, CardDefinition, CardType, Enchantment,
    Keyword, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.passive_objects import BINDING, UNIT as UNIT_MARKER, bound_object, units
from hs_sim.engine.player_target_inputs import capture, canonical, decode, validate_full_state
from hs_sim.engine.pools import GenerationContext
from hs_sim.engine.serialization import canonical_hash
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k616.'
UNIT, VICTIM, DORMANT, REPEATER, WATCHER, FAILWATCH, COPY, BASE, BOUNCE, KILL, MUTE, NOOP, INTERFERE, FAIL = (
    P + s for s in ('unit', 'victim', 'dormant', 'repeater', 'watch', 'failwatch', 'copy', 'base',
                   'bounce', 'kill', 'mute', 'noop', 'interfere', 'failure'))


def context():
    return GenerationContext(P + 'complete', 'experimental')


@lru_cache(None)
def registry(mode='normal', role='writer'):
    if mode == 'wait':
        r = batch.registration_prefix(build_registry, 'hs_sim.cards.sargeras_portal.register_sargeras_portal', lambda r: None)
        register = r.register_behavior
        def intercept(name, body):
            if name in (native.PREFIX + 'open', native.PREFIX + native.SKILLS[2]):
                original = body
                def body(c):
                    work = tuple(original(c))
                    return (RequestChoice(c.player_id, (
                        ChoiceOption('continue', 'Continue', work),
                        ChoiceOption('depart', 'Original source dies', (Destroy(c.source_id, c.source_id),) + work),
                        ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
            register(name, body)
        with patch.object(r, 'register_behavior', side_effect=intercept):
            native.register_sargeras_portal(r)
    else:
        r = build_registry()
    r.register_behavior(NOOP, lambda c: ())
    def fail(c):
        raise ResolutionError('K616 deliberate continuation failure')
    r.register_behavior(FAIL, fail)
    for cid, body in (
        (COPY, lambda c: (CopyMinion(c.target_id, c.player_id),)),
        (BASE, lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),)),
        (BOUNCE, lambda c: (ReturnToHand(c.target_id),)),
        (KILL, lambda c: (Destroy(c.target_id, c.source_id),)),
        (MUTE, lambda c: (Silence(c.target_id),))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1, on_play=cid, targeting=TargetSpec()))
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, cost=1, on_play=NOOP))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=30))
    r.register_behavior(VICTIM, lambda c: (Draw(c.player_id),))
    r.register_card(CardDefinition(VICTIM, VICTIM, CardType.MINION, health=2,
        deathrattle=VICTIM, keywords=(Keyword.REBORN,)))
    r.register_card(CardDefinition(DORMANT, DORMANT, CardType.MINION, attack=1, health=2, dormant_turns=2))
    r.register_card(CardDefinition(REPEATER, REPEATER, CardType.MINION, health=8,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    def watch(c, failure=False):
        event = c.event
        if (event.target_id is None or c.state.entities[event.target_id].card_id not in (native.IMP, native.INFERNAL) or
                sum(c.state.entities[i].card_id in (native.IMP, native.INFERNAL)
                    for i in c.state.players[c.player_id].board) != 1):
            return ()
        if failure:
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
    for cid, failure in ((WATCHER, False), (FAILWATCH, True)):
        r.register_behavior(cid, lambda c, failure=failure: watch(c, failure))
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=8, triggers=(TriggerSpec('minion_summoned', cid),)))
    def interfere(c):
        obj = next(c.state.entities[i] for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == native.PORTAL)
        return (Damage(obj.id, 99, c.source_id), Buff(obj.id, 9, 9, c.source_id),
            Destroy(obj.id, c.source_id), Silence(obj.id), ReturnToHand(obj.id),
            Transform(obj.id, UNIT), ChangeControl(obj.id, 3 - c.player_id))
    r.register_behavior(INTERFERE, interfere)
    r.register_card(CardDefinition(INTERFERE, INTERFERE, CardType.SPELL, cost=1, on_play=INTERFERE))
    r.validate()
    return r


class SargerasPortalTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(registry)
    mode = 'normal'

    def game(self, hand=(native.SARGERAS,), *, board=(), enemy_hand=(), enemy_board=(UNIT,), mode='normal', player=1):
        self.mode = mode
        setups = tuple(PlayerSetup('HERO_09', hand=hand if p == player else enemy_hand,
            board=board if p == player else enemy_board, deck=(NOOP,) * 12,
            mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=616,
            generation_context=context()), registry(mode))

    def source(self, g, player=1):
        return self.entity(g, native.SARGERAS, player, 'board')

    def objects(self, g, player=1):
        return [g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id == native.PORTAL]

    def demons(self, g, cid, player=1):
        return [g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id == cid]

    def use(self, g, skill, *, source=None, player=1):
        sid = self.source(g, player).id if source is None else source
        mana = g.state.players[player].mana
        g.apply(UseMinionAbility(player, sid, skill))
        self.assertEqual(g.state.players[player].mana, mana)
        return sid

    def next_turn(self, g, player=1):
        g.apply(EndTurn(player)); g.apply(EndTurn(3 - player))

    def test_full_original_rows_primary_faces_and_existing_infernal_are_preserved(self):
        d = native.load_batch()
        self.assertEqual(sum(len(d[k]) for k in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only')), 9)
        self.assertEqual(len(d['official_observations']), 14)
        self.assertEqual(tuple(r['record']['id'] for r in d['existing_dependencies']), (native.INFERNAL,))
        r = registry()
        self.assertEqual((r.card(native.IMP).attack, r.card(native.IMP).health), (3, 2))
        self.assertEqual((r.card(native.INFERNAL).attack, r.card(native.INFERNAL).health), (6, 6))
        for cid in native.SKILLS:
            self.assertTrue(r.card(cid).choice_only)
            self.assertNotIn(cid, r.pool_cards)
        self.assertTrue(all(cid not in r.cards for cid in native.EVIDENCE))

    def test_paid_both_seats_open_one_untouchable_slot_without_a_minion_summon(self):
        for p in (1, 2):
            with self.subTest(player=p):
                g = self.game(player=p); sid = self.play(g, native.SARGERAS, player=p)
                self.assertEqual(g.state.players[p].mana, 21)
                obj, = self.objects(g, p)
                self.assertEqual(g.state.players[p].board, [sid, obj.id])
                self.assertFalse(obj.active); self.assertFalse(obj.is_character)
                self.assertIsNone(obj.dormancy); self.assertEqual(obj.corpse_value, 0)
                self.assertFalse(any(e.kind == 'minion_summoned' and e.target_id == obj.id for e in g.events))
                self.assertEqual(bound_object(g.state, g.registry, g.state.entities[sid], p, native.PORTAL).id, obj.id)

    def test_full_board_opening_fails_and_all_three_skills_are_known_noops_without_portal(self):
        for skill in native.SKILLS:
            g = self.game(board=(UNIT,) * 6); sid = self.play(g, native.SARGERAS)
            self.assertFalse(self.objects(g)); before = tuple(g.state.players[1].board), tuple(g.state.players[2].board)
            self.use(g, skill)
            self.assertEqual((tuple(g.state.players[1].board), tuple(g.state.players[2].board)), before)
            self.assertTrue(any(a.kind == 'activated' and a.activation.id == skill and a.consumed
                for a in g.state.entities[sid].abilities))

    def test_autonomous_portal_ticks_own_end_only_and_survives_original_source_death(self):
        g = self.game((native.SARGERAS, KILL)); sid = self.play(g, native.SARGERAS)
        self.play(g, KILL, sid); obj, = self.objects(g)
        g.apply(EndTurn(1)); self.assertEqual(len(self.demons(g, native.IMP)), 2)
        g.apply(EndTurn(2)); self.assertEqual(len(self.demons(g, native.IMP)), 2)
        self.assertEqual({d.card_id for d in g.state.death_history}, {native.SARGERAS})
        self.assertEqual(len([r for r in g.state.successful_summon_history if r.card_id == native.IMP]), 2)
        self.assertIn(obj.id, g.state.players[1].board)
        self.portable(g)

    def test_to_void_simultaneously_removes_other_active_minions_without_deathrattle_or_reborn(self):
        g = self.game(board=(VICTIM,), enemy_board=(VICTIM, UNIT, DORMANT))
        sid = self.play(g, native.SARGERAS); obj, = self.objects(g)
        removed = [i for p in (1, 2) for i in g.state.players[p].board
            if g.state.entities[i].card_id in (VICTIM, UNIT)]
        before = len(g.state.death_history), len(g.state.players[1].hand), len(g.state.players[2].hand)
        self.use(g, native.SKILLS[0])
        self.assertEqual(g.state.players[1].board, [sid, obj.id])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board], [DORMANT])
        self.assertTrue(all(g.state.entities[i].zone == Zone.SETASIDE for i in removed))
        self.assertEqual((len(g.state.death_history), len(g.state.players[1].hand), len(g.state.players[2].hand)), before)
        events = [e for e in g.events if e.kind == 'cards_removed_from_game']
        self.assertEqual(len(events), 1); self.assertEqual(events[0].amount, len(removed))
        self.portable(g)

    def test_friendly_copy_shares_exact_portal_and_future_imp_infernal_grants_enter_before_publication(self):
        g = self.game((native.SARGERAS, COPY)); sid = self.play(g, native.SARGERAS)
        self.play(g, COPY, sid); copy = [i for i in g.state.players[1].board
            if g.state.entities[i].card_id == native.SARGERAS and i != sid][0]
        self.use(g, native.SKILLS[2], source=copy); self.use(g, native.SKILLS[1], source=sid)
        self.assertEqual([(e.attack, e.health, Keyword.TAUNT in e.keywords) for e in self.demons(g, native.INFERNAL)], [(6, 8, True)] * 2)
        g.apply(EndTurn(1))
        self.assertEqual([(e.attack, e.health, Keyword.TAUNT in e.keywords) for e in self.demons(g, native.IMP)], [(3, 4, True)] * 2)
        self.assertEqual(units(g.registry, self.objects(g)[0]), 1)
        self.portable(g)

    def test_two_legion_units_stack_for_both_real_demon_dependencies(self):
        g = self.game((native.SARGERAS, COPY)); sid = self.play(g, native.SARGERAS)
        self.play(g, COPY, sid); other = [i for i in g.state.players[1].board if i != sid and g.state.entities[i].card_id == native.SARGERAS][0]
        self.use(g, native.SKILLS[2], source=sid); self.use(g, native.SKILLS[2], source=other)
        self.next_turn(g); self.assertEqual([e.health for e in self.demons(g, native.IMP)], [6, 6])
        self.use(g, native.SKILLS[1], source=sid)
        self.assertEqual([e.health for e in self.demons(g, native.INFERNAL)], [10, 10])
        self.assertEqual(units(g.registry, self.objects(g)[0]), 2)

    def test_legion_does_not_retroactively_upgrade_existing_demons(self):
        g = self.game(); self.play(g, native.SARGERAS); self.next_turn(g)
        old = tuple(e.id for e in self.demons(g, native.IMP)); self.use(g, native.SKILLS[2]); g.apply(EndTurn(1))
        self.assertEqual([(g.state.entities[i].health, Keyword.TAUNT in g.state.entities[i].keywords) for i in old], [(2, False)] * 2)
        fresh = [e for e in self.demons(g, native.IMP) if e.id not in old]
        self.assertEqual([(e.health, Keyword.TAUNT in e.keywords) for e in fresh], [(4, True)] * 2)

    def test_repeated_battlecry_opens_two_independent_portals_and_binds_latest_success(self):
        g = self.game(board=(REPEATER,)); sid = self.play(g, native.SARGERAS)
        portals = self.objects(g); self.assertEqual(len(portals), 2)
        self.use(g, native.SKILLS[2]); self.assertEqual([units(g.registry, e) for e in self.objects(g)], [0, 1])
        self.assertEqual(bound_object(g.state, g.registry, g.state.entities[sid], 1, native.PORTAL).id, portals[-1].id)
        g.apply(EndTurn(1))
        self.assertEqual([e.health for e in self.demons(g, native.IMP)], [2, 2, 4])

    def test_second_full_board_opening_keeps_first_successful_portal_link(self):
        g = self.game(board=(REPEATER,) + (UNIT,) * 4); sid = self.play(g, native.SARGERAS)
        self.assertEqual(len(self.objects(g)), 1)
        self.use(g, native.SKILLS[2]); self.assertEqual(units(g.registry, self.objects(g)[0]), 1)
        self.assertEqual(bound_object(g.state, g.registry, g.state.entities[sid], 1, native.PORTAL).id, self.objects(g)[0].id)

    def test_unbound_summoned_and_base_copy_can_find_existing_friendly_portal(self):
        g = self.game((native.SARGERAS, BASE), board=(native.SARGERAS,)); unbound = self.source(g).id
        sid = self.play(g, native.SARGERAS); self.use(g, native.SKILLS[2], source=unbound)
        self.play(g, BASE, sid)
        copied = [i for i in g.state.players[1].board if i not in (sid, unbound) and g.state.entities[i].card_id == native.SARGERAS][0]
        self.assertFalse(any(e.label.startswith(BINDING) for e in g.state.entities[copied].enchantments))
        self.use(g, native.SKILLS[1], source=copied)
        self.assertEqual([e.health for e in self.demons(g, native.INFERNAL)], [8, 8])

    def test_enemy_current_copy_cannot_use_foreign_link_or_unrelated_own_portal(self):
        g = self.game(enemy_hand=(native.SARGERAS, COPY)); original = self.play(g, native.SARGERAS)
        g.apply(EndTurn(1)); self.play(g, native.SARGERAS, player=2); self.play(g, COPY, original, player=2)
        copied = [i for i in g.state.players[2].board if g.state.entities[i].card_id == native.SARGERAS][-1]
        self.assertIsNone(bound_object(g.state, g.registry, g.state.entities[copied], 2, native.PORTAL))
        self.use(g, native.SKILLS[1], source=copied, player=2)
        self.assertFalse(self.demons(g, native.INFERNAL, 2)); self.assertEqual(units(g.registry, self.objects(g, 2)[0]), 0)

    def test_bounce_replay_opens_fresh_portal_and_leaves_old_one_autonomous(self):
        g = self.game((native.SARGERAS, BOUNCE)); sid = self.play(g, native.SARGERAS)
        self.use(g, native.SKILLS[2]); first = self.objects(g)[0].id
        self.play(g, BOUNCE, sid); sid = self.play(g, native.SARGERAS)
        self.assertEqual([units(g.registry, e) for e in self.objects(g)], [1, 0])
        self.assertNotEqual(bound_object(g.state, g.registry, g.state.entities[sid], 1, native.PORTAL).id, first)
        self.use(g, native.SKILLS[1]); self.assertEqual([e.health for e in self.demons(g, native.INFERNAL)], [6, 6])

    def test_portal_cannot_be_targeted_attacked_invested_or_changed_by_ordinary_effects(self):
        g = self.game((native.SARGERAS, KILL, MUTE, BOUNCE, INTERFERE)); self.play(g, native.SARGERAS)
        obj = self.objects(g)[0]
        for spell in (KILL, MUTE, BOUNCE):
            before = g.snapshot()
            with self.assertRaises(IllegalAction): self.play(g, spell, obj.id)
            self.assertEqual(g.snapshot(), before)
        with self.assertRaises(IllegalAction): g.apply(UseInteractable(1, obj.id, self.entity(g, KILL).id))
        self.play(g, INTERFERE)
        after = self.objects(g)[0]
        self.assertEqual((after.controller, after.health, after.attack, after.silenced, after.zone), (1, 1, 0, False, Zone.BOARD))
        self.assertFalse(any(getattr(a, 'attacker_id', None) == obj.id or getattr(a, 'entity_id', None) == obj.id for a in g.legal_actions()))

    def test_install_and_upgrade_wait_restore_clone_replay_and_failed_resume_are_atomic(self):
        g = self.game(mode='wait'); self.play(g, native.SARGERAS)
        for stage in ('install', 'upgrade'):
            self.assertIsNotNone(g.state.pending_choice); self.assertEqual(len(self.objects(g)), 0 if stage == 'install' else 1)
            g = self.portable(g); before = g.snapshot()
            with self.assertRaises(ResolutionError): self.choose(g, 'fail')
            self.assertEqual(g.snapshot(), before)
            self.choose(g)
            if stage == 'install': self.use(g, native.SKILLS[2])
        self.assertEqual(units(g.registry, self.objects(g)[0]), 1)
        self.portable(g)

    def test_accepted_opening_survives_source_death_without_binding_to_dead_body(self):
        g = self.game(mode='wait'); sid = self.play(g, native.SARGERAS); self.choose(g, 'depart')
        self.assertEqual(g.state.entities[sid].zone, Zone.GRAVEYARD)
        self.assertFalse(any(e.label.startswith(BINDING) for e in g.state.entities[sid].enchantments))
        self.assertEqual(len(self.objects(g)), 1); g.apply(EndTurn(1))
        self.assertEqual(len(self.demons(g, native.IMP)), 2); self.portable(g)

    def test_first_summon_wait_preserves_two_roots_and_upgraded_material_on_resume(self):
        g = self.game(board=(WATCHER,)); self.play(g, native.SARGERAS); self.use(g, native.SKILLS[2]); g.apply(EndTurn(1))
        self.assertEqual(len(self.demons(g, native.IMP)), 1); g = self.portable(g)
        self.choose(g); self.assertEqual([e.health for e in self.demons(g, native.IMP)], [4, 4]); self.portable(g)

    def test_failed_summon_reaction_rolls_back_consumption_bindings_allocations_and_events(self):
        g = self.game(board=(FAILWATCH,)); self.play(g, native.SARGERAS); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g, native.SKILLS[1])
        self.assertEqual(g.snapshot(), before)

    def test_public_object_and_original_inputs_have_no_hidden_combat_or_attachment_fields(self):
        g = self.game((native.SARGERAS, NOOP)); self.play(g, native.SARGERAS); self.use(g, native.SKILLS[2])
        for p in (1, 2):
            observation = g.for_player(p).observe()['observation']; self.assertEqual(observation['version'], VIEW_VERSION)
            row = next(e for e in observation['players'][0]['board'] if e['card_id'] == native.PORTAL)
            self.assertEqual(set(row), {'ref', 'card_id', 'controller', 'zone', 'kind', 'passive_object'})
            self.assertEqual(row['passive_object'], {'upgrades': 1})
            raw = json.dumps(observation) + json.dumps(g.player_events(p))
            for private in (BINDING, UNIT_MARKER, 'board_presence_id', 'zone_epoch', 'enchantments', 'rng_state'):
                self.assertNotIn(private, raw)
        source = g._state.entities[self.entity(g, NOOP).id]
        proof = capture(g, g._state, source)
        validate_full_state(g._state, g.registry, source, proof)
        for upgrades in (True, -1, 2):
            altered = json.loads(proof.observation_json)
            row = next(e for e in altered['players'][0]['board'] if e['card_id'] == native.PORTAL)
            row['passive_object']['upgrades'] = upgrades
            with self.assertRaises(ValueError):
                changed = replace(proof, observation_json=canonical(altered))
                if upgrades == 2 and type(upgrades) is int:
                    validate_full_state(g._state, g.registry, source, changed)
                else:
                    decode(changed)

    def test_rehashed_snapshot_rejects_foreign_binding_unit_and_passive_trigger(self):
        g = self.game(); sid = self.play(g, native.SARGERAS); self.use(g, native.SKILLS[2]); saved = g.snapshot()
        for mode in ('foreign_binding', 'foreign_unit', 'duplicate_binding', 'body'):
            bad = deepcopy(saved); rows = bad['state']['entities']; values = list(rows.values()) if isinstance(rows, dict) else rows
            root = next(e for e in values if e['id'] == sid); obj = next(e for e in values if e['card_id'] == native.PORTAL)
            if mode == 'foreign_binding': root['enchantments'][0]['source_id'] = g.state.players[2].board[0]
            elif mode == 'foreign_unit': obj['enchantments'][0]['label'] = UNIT_MARKER + 'unknown'
            elif mode == 'body': obj['abilities'][0]['behavior_id'] = NOOP
            else:
                duplicate = deepcopy(root['enchantments'][0]); duplicate['id'] = bad['state']['next_attachment_id']; bad['state']['next_attachment_id'] += 1
                root['enchantments'].append(duplicate)
            bad['state_hash'] = canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())
        for change in (dict(health=2), dict(expires_turn=3), dict(remove_on_silence=False), dict(source_id=None)):
            with self.assertRaises(ValueError): replace(Enchantment(1, source_id=sid, label=UNIT_MARKER + native.EVIDENCE[1]), **change)

    def test_complete_local_host_executes_native_skills_and_reachable_tokens(self):
        fmt = build_cn37_local_pool_format()
        for skill in native.SKILLS:
            g = Game.from_scenario(Scenario((PlayerSetup('HERO_09', hand=(native.SARGERAS,), mana=10, max_mana=10),
                PlayerSetup('HERO_09', board=('CORE_EX1_028',))), seed=616, generation_context=fmt.context), fmt.registry)
            sid = self.play(g, native.SARGERAS); g.apply(UseMinionAbility(1, sid, skill))
            self.assertEqual(Game.from_snapshot(g.snapshot(), fmt.registry).snapshot(), g.snapshot())
        self.assertIn(native.INFERNAL, fmt.registry.cards); self.assertIn(native.IMP, fmt.registry.cards)

    def test_invalid_last_descriptor_cannot_half_register_and_passive_shape_cannot_gain_actions(self):
        r = batch.registration_prefix(build_registry, 'hs_sim.cards.sargeras_portal.register_sargeras_portal', lambda r: None)
        d = deepcopy(native.load_batch()); d['dependencies'][-1]['record']['type'] = 'MINION'; before = r.fingerprint()
        with patch.object(native, 'load_batch', lambda: d), self.assertRaises(TargetValidationError): native.register_sargeras_portal(r)
        self.assertEqual(r.fingerprint(), before)
        portal = registry().card(native.PORTAL)
        for change in (dict(attack=1), dict(health=2), dict(battlecry=NOOP), dict(triggers=()), dict(on_use=NOOP)):
            with self.assertRaises(ValueError): r._validate_card(replace(portal, **change))
        with self.assertRaises(ValueError): self.game((native.PORTAL,))
        with self.assertRaises(ValueError): self.game((), board=(native.PORTAL,))

if __name__ == '__main__':
    unittest.main()
