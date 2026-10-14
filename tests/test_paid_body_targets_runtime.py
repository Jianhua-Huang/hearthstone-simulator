"""Actual paid actions exercise targets, original proof, waiting and rollback."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (BodyReference, BodyRootTargetBinding, BodyTargetBinding,
    BodyTargetProfile, BodyTargetSelection, PaidBodyTargetRequest, CardDefinition,
    CardType, Game, GrantBattlecry, GrantCombo, IllegalAction, Keyword, PlayCard,
    PlayBodyTarget, PlayerSetup, Registry, Scenario, SelectChoice, TargetMode,
    TargetSpec, TriggerSpec, Zone, paid_body_root_target_plan,
    preflight_paid_body_root_targets, play_with_body_targets)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, Destroy, GainArmor,
    RandomDamage, RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import AppendageSpec, BattlecryRepeatSpec, ComboRepeatSpec, RewindSpec
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.replay import build_replay, replay

FRIEND = TargetSpec(TargetMode.IF_AVAILABLE, (Zone.BOARD,), (CardType.MINION,), 'friendly')
ENEMY = replace(FRIEND, mode=TargetMode.REQUIRED, relation='enemy')


def registry(mode='normal', carrier='unit'):
    r = Registry('paid-body-runtime-' + mode + '-' + carrier)
    r.register_body_target_profile(BodyTargetProfile('paid', 'paid_hand', 'manual', 'pre_payment'))
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=100))
    r.register_card(CardDefinition('friend', 'Friend', CardType.MINION, attack=1, health=12))
    r.register_card(CardDefinition('enemy', 'Enemy', CardType.MINION, attack=1, health=12))
    def body(c):
        effects = [GainArmor(c.player_id, 1)]
        if c.target_id is not None: effects.append(Buff(c.target_id, attack=1, source_id=c.source_id))
        if mode == 'wait':
            return [RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', tuple(effects)),), c.source_id)]
        if mode == 'fail' and c.combo is not None:
            return [RandomDamage((c.state.players[2].hero_id,), 1, source_id=c.source_id), Summon(c.player_id, 'unknown.runtime.card')]
        return effects
    r.register_behavior('body', body)
    def ordinary(c):
        if mode == 'depart': return [Destroy(c.state.players[c.player_id].board[0])]
        return [Damage(c.target_id, 2, c.source_id)] if c.target_id is not None else [GainArmor(c.player_id, 2)]
    r.register_behavior('ordinary', ordinary)
    values = dict(battlecry='body', targeting=FRIEND, on_play='ordinary')
    if carrier != 'weapon': values.update(combo='body', keywords=(Keyword.COMBO,))
    if carrier == 'weapon':
        r.register_card(CardDefinition('unit', 'Unit', CardType.WEAPON, cost=2, attack=1, durability=4, **values))
    elif carrier == 'hero':
        r.register_behavior('power', lambda c: [])
        r.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, cost=2, on_use='power'))
        r.register_card(CardDefinition('unit', 'Unit', CardType.HERO, cost=2, health=100,
            hero_card=True, hero_armor=3, initial_hero_power='power', **values))
    else:
        if mode == 'late':
            values.update(colossal=(AppendageSpec('limb'),), keywords=(Keyword.COMBO, Keyword.COLOSSAL))
            r.register_card(CardDefinition('limb', 'Limb', CardType.MINION, health=2))
        if mode in ('retained', 'retry'):
            values.update(rewind=RewindSpec(), keywords=(Keyword.COMBO, Keyword.REWIND))
        r.register_card(CardDefinition('unit', 'Unit', CardType.MINION, cost=2, health=12, **values))
    for name, threshold in (('low', 5), ('high', 9)):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=12, battlecry='body', combo='body',
            targeting=FRIEND, manathirst=threshold, keywords=(Keyword.COMBO, Keyword.MANATHIRST)))
    def setup(c):
        e = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == 'unit')
        return [effect(BodyReference.capture(e), name, c.source_id)
                for name in ('low', 'high') for effect in (GrantBattlecry, GrantCombo)]
    r.register_behavior('setup', setup)
    r.register_card(CardDefinition('setup', 'Setup', CardType.SPELL, on_play='setup'))
    r.register_behavior('tempo', lambda c: [GainArmor(c.player_id, 1)])
    r.register_card(CardDefinition('tempo', 'Tempo', CardType.SPELL, on_play='tempo'))
    for name in ('unit', 'low', 'high'):
        for family in ('battlecry', 'combo'):
            if getattr(r.card(name), family) is not None:
                r.register_body_target_binding(BodyTargetBinding(name, family, 'paid'))
    r.register_body_root_target_binding(BodyRootTargetBinding('unit', 'paid', 'explicit_root', ENEMY))
    if mode == 'repeat':
        r.register_card(CardDefinition('repeat', 'Repeat', CardType.MINION, health=12,
            battlecry_repeats=(BattlecryRepeatSpec(2),), combo_repeats=(ComboRepeatSpec(3),)))
    if mode == 'retained':
        r.register_card(CardDefinition('holder', 'Holder', CardType.MINION, health=12, retain_rewind_outcomes=True))
    if mode == 'generated':
        from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
        from hs_sim.engine.whole_card_replays import ReplayWholeCards
        from hs_sim.engine.generated_retained_outcomes import PROFILE
        r.register_behavior('replay', lambda c: [ReplayWholeCards(c.player_id, c.source_id,
            WholeCardHistoryQuery(c.player_id, len(c.state.play_history)+1, kinds=(CardType.MINION,)),
            physical_profile=PROFILE, choices='player')])
        r.register_card(CardDefinition('replay', 'Replay', CardType.SPELL, on_play='replay'))
    if mode == 'late':
        def late(c):
            e=c.state.entities.get(c.event.source_id)
            if e is None or e.card_id != 'unit' or e.zone != Zone.BOARD: return []
            e=c.state.entities[c.event.source_id]
            return [GrantBattlecry(BodyReference.capture(e), 'low', c.source_id)]
        r.register_behavior('late', late)
        r.register_card(CardDefinition('late', 'Late', CardType.MINION, health=12,
            triggers=(TriggerSpec('minion_summoned', 'late'),)))
    return r


class PaidBodyTargetRuntimeTests(unittest.TestCase):
    def game(self, mode='normal', *, carrier='unit', grant=True, board=None):
        board = ('friend', 'friend', *((mode,) if mode in ('repeat', 'late') else ('holder',) if mode == 'retained' else ())) if board is None else board
        g=Game.from_scenario(Scenario((PlayerSetup('hero', hand=('setup','unit','tempo',* (('replay',) if mode=='generated' else ())), board=board, mana=6,max_mana=6),
            PlayerSetup('hero', board=('enemy',), hand=('enemy',)))), registry(mode,carrier))
        if grant: g.apply(PlayCard(1,g.state.players[1].hand[0]))
        return g

    def action(self,g,*,reverse=False):
        source=next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id=='unit')
        raw=PlayCard(1,source.id,g.state.players[2].board[0])
        plan=paid_body_root_target_plan(g,raw,'paid')
        slots=tuple(BodyTargetSelection(v.declaration.reference,v.target_choices[i%len(v.target_choices)]) for i,v in enumerate(plan.bodies.requirements))
        request=PaidBodyTargetRequest(raw,'paid',tuple(reversed(slots)) if reverse else slots)
        return play_with_body_targets(preflight_paid_body_root_targets(g,request))

    def resume(self,g):
        while g.state.pending_choice is not None:
            choice=g.state.pending_choice
            g.apply(SelectChoice(choice.player_id,choice.id,(choice.options[0].id,)))

    def roundtrip(self,g):
        s=g.snapshot()
        self.assertEqual(Game.from_snapshot(s,registry(self.mode,self.carrier)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(self.mode,self.carrier)).snapshot(),s)

    def test_actual_ordinary_enemy_and_six_body_targets_are_independent(self):
        g=self.game(); action=self.action(g); enemy=action.target_id; before=g.state.players[1].mana
        g.apply(action); p=g.state.play_history[-1]
        self.assertEqual(g.state.players[1].mana,before-2)
        self.assertEqual(g.state.entities[enemy].damage,2)
        expected=[v.target_id for v in p.body_targets.selected]
        self.assertEqual([r.target_id for r in g.state.battlecry_history],expected[:3])
        self.assertEqual([r.target_id for r in g.state.combo_history],expected[3:])
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board[:2]],[4,4])
        self.assertIsNotNone(p.paid_hand_close)

    def test_original_submission_order_is_preserved_and_execution_order_canonical(self):
        g=self.game();a=self.action(g,reverse=True);g.apply(a);p=g.state.play_history[-1]
        self.assertEqual(p.body_targets.action.body_targets,a.body_targets)
        self.assertEqual([v.ability_id for v in p.body_targets.selected],list(reversed([v.ability_id for v in a.body_targets])))
        self.assertEqual(p.body_targets.registry_fingerprint,g.registry.fingerprint())

    def test_typed_action_strict_json_roundtrip_and_legacy_shape(self):
        g=self.game();a=self.action(g)
        self.assertEqual(action_from_dict(json.loads(json.dumps(action_to_dict(a)))),a)
        raw=action_to_dict(PlayCard(1,a.entity_id))
        self.assertNotIn('body_targets',raw);self.assertNotIn('body_target_profile_id',raw)
        for mutation in (lambda w:w['body_targets'][0].update(extra=True),lambda w:w['body_targets'][0].update(ability_id=True),lambda w:w.pop('body_target_profile_id')):
            w=deepcopy(action_to_dict(a));mutation(w)
            with self.assertRaises(ValueError):action_from_dict(w)

    def test_missing_extra_stale_wrong_family_and_wrong_target_are_atomic(self):
        g=self.game();a=self.action(g);s=g.snapshot()
        first=a.body_targets[0]
        candidates=[replace(a,body_targets=a.body_targets[:-1]),replace(a,body_targets=(replace(first,ability_id=99999),*a.body_targets[1:])),
            replace(a,body_targets=(replace(first,family='combo'),*a.body_targets[1:])),
            replace(a,body_targets=(replace(first,zone_epoch=first.zone_epoch+1),*a.body_targets[1:])),
            replace(a,body_targets=(replace(first,target_id=a.target_id),*a.body_targets[1:]))]
        for bad in candidates:
            with self.assertRaises((IllegalAction,ValueError)):g.apply(bad)
            self.assertEqual(g.snapshot(),s)

    def test_waiting_each_body_restores_clones_and_replays_actual_targets(self):
        self.mode='wait';self.carrier='unit';g=self.game(self.mode);a=self.action(g);g.apply(a); waits=0
        while g.state.pending_choice is not None:
            waits+=1;self.roundtrip(g);choice=g.state.pending_choice
            g.apply(SelectChoice(1,choice.id,('ok',)))
        self.assertEqual(waits,6);self.roundtrip(g)
        self.assertEqual([v.target_id for v in g.state.battlecry_history], [v.target_id for v in g.state.play_history[-1].body_targets.selected[:3]])

    def test_repeat_each_body_reuses_its_own_target_and_root_pays_once(self):
        g=self.game('repeat');a=self.action(g);g.apply(a);p=g.state.play_history[-1]
        self.assertEqual(len(g.state.battlecry_history),6);self.assertEqual(len(g.state.combo_history),9)
        for record in (*g.state.battlecry_history,*g.state.combo_history):
            slot=next(v for v in p.body_targets.selected if v.ability_id==record.payload.ability_id)
            self.assertEqual(record.target_id,slot.target_id)
        self.assertEqual(g.state.players[1].mana,4)

    def test_retained_results_keep_original_vector_and_single_payment(self):
        self.mode='retained';self.carrier='unit';g=self.game(self.mode);a=self.action(g);g.apply(a)
        self.assertEqual(len(g.state.battlecry_history),6);self.assertEqual(len(g.state.combo_history),6)
        self.assertEqual(g.state.players[1].mana,4);self.assertEqual(g.state.rewind_outcomes[-1].completed,2)
        self.roundtrip(g)

    def test_departed_targets_skip_only_their_own_bodies(self):
        g=self.game('depart');a=self.action(g);first=g.state.players[1].board[0];g.apply(a)
        failed=[r for r in (*g.state.battlecry_history,*g.state.combo_history) if r.failure is not None]
        self.assertEqual(len(failed),3);self.assertTrue(all(r.target_id==first for r in failed))
        self.assertTrue(all(r.completed for r in failed));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3)

    def test_second_family_failure_rolls_back_first_family_payment_rng_and_events(self):
        g=self.game('fail');a=self.action(g);s=g.snapshot();history=g.history
        with self.assertRaises(ResolutionError):g.apply(a)
        self.assertEqual(g.snapshot(),s);self.assertEqual(g.history,history)

    def test_late_unsubmitted_actual_body_rejects_entire_root(self):
        g=self.game('late');a=self.action(g);s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'not submitted in the original paid target vector'):g.apply(a)
        self.assertEqual(g.snapshot(),s)

    def test_disabled_combo_still_requires_explicit_none_slots(self):
        g=self.game(grant=False);a=self.action(g);combo=next(v for v in a.body_targets if v.family=='combo')
        self.assertIsNone(combo.target_id);g.apply(a)
        self.assertEqual(len(g.state.battlecry_history),1);self.assertFalse(g.state.combo_history)

    def test_empty_if_available_pool_keeps_original_none_after_source_enters(self):
        g=self.game(board=());a=self.action(g);self.assertTrue(all(v.target_id is None for v in a.body_targets));g.apply(a)
        self.assertTrue(all(v.target_id is None for v in (*g.state.battlecry_history,*g.state.combo_history)))

    def test_weapon_and_hero_actual_body_targets_preserve_original_payment(self):
        for carrier in ('weapon','hero'):
            self.mode='normal';self.carrier=carrier;g=self.game(carrier=carrier);a=self.action(g);g.apply(a)
            p=g.state.play_history[-1];self.assertEqual(g.state.players[1].mana,4)
            self.assertEqual([r.target_id for r in (*g.state.battlecry_history,*g.state.combo_history)], [v.target_id for v in p.body_targets.selected])
            self.roundtrip(g)

    def test_terminal_snapshot_rehashed_wrong_vector_and_condition_flags_rejected(self):
        self.mode='normal';self.carrier='unit';g=self.game();g.apply(self.action(g));self.roundtrip(g)
        for mutate in (lambda r:r['selected'][0].update(family='combo'),lambda r:r['body_target_active'].__setitem__(0,False),lambda r:r.update(registry_fingerprint='0'*64)):
            s=g.snapshot();mutate(s['state']['play_history'][-1]['body_targets']);s['state_hash']=g.state_hash()
            with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_waiting_original_payment_proof_recomputes_target_candidates(self):
        g=self.game('wait');g.apply(self.action(g));s=g.snapshot()
        # The receipt in the genuine payment tail is independently validated;
        # editing its compact candidate vector cannot be made valid by rehashing.
        def walk(v):
            if isinstance(v,dict):
                if v.get('type')=='hs_sim.engine.model.PaidBodyTargetReceipt':
                    v['fields']['original_state_hash']='0'*64
                for x in v.values():walk(x)
            elif isinstance(v,list):
                for x in v:walk(x)
        walk(s['resolution_frame'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry('wait'))

    def test_player_views_and_filtered_events_never_expose_host_target_receipt(self):
        g=self.game('wait');g.apply(self.action(g))
        for player in (1,2):
            raw=json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).events())
            for hidden in ('original_state_hash','body_target_profile_id','grant_source_id','zone_epoch','registry_fingerprint'):
                self.assertNotIn(hidden,raw)

    def test_unconnected_rewind_retry_producer_is_explicitly_refused(self):
        g=self.game('retry');a=self.action(g);s=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(a)
        self.assertEqual(g.snapshot(),s)

    def test_original_turn_affordability_position_and_branch_validation_still_apply(self):
        g=self.game();a=self.action(g);s=g.snapshot()
        for bad in (replace(a,position=99),replace(a,branch_id='unknown'),replace(a,player_id=2)):
            with self.assertRaises((IllegalAction,ValueError)):g.apply(bad)
            self.assertEqual(g.snapshot(),s)

    def test_trusted_separation_binding_cannot_be_bypassed_with_shared_legacy_target(self):
        g=self.game();a=self.action(g);before=g.snapshot()
        legacy=PlayCard(1,a.entity_id,g.state.players[1].board[0])
        with self.assertRaisesRegex(IllegalAction,'complete independent paid body target vector'):g.apply(legacy)
        self.assertEqual(g.snapshot(),before)

    def test_bound_completed_history_cannot_drop_original_target_receipt(self):
        g=self.game();g.apply(self.action(g));bad=g.clone()
        bad._state.play_history[-1]=replace(bad._state.play_history[-1],body_targets=None)
        snapshot=bad.snapshot()
        with self.assertRaisesRegex(SnapshotError,'lost its original independent body target receipt'):
            Game.from_snapshot(snapshot,registry())

    def test_paid_target_profile_does_not_silently_authorize_generated_whole_replay(self):
        g=self.game('generated');g.apply(self.action(g));before=g.snapshot()
        source=next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id=='replay')
        with self.assertRaisesRegex(ResolutionError,'own generated origin producer'):g.apply(PlayCard(1,source.id))
        self.assertEqual(g.snapshot(),before)
