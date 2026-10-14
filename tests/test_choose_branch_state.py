"""Physical preselection and origin-authorized inheritance through real actions."""
from copy import deepcopy
from dataclasses import replace
import unittest

from test_player_choose_both import registry as base_registry, play
from hs_sim.engine import (AddChooseBothModifier, CardDefinition, CardType, ChooseBranchSelection,
    EndTurn, Game, HeroPowerReference, IllegalAction, Keyword, PlayCard, PlayerSetup,
    RecastSpell, RewindSpec, Scenario, SelectChoice, SetChooseBranch, UseHeroPower, Zone)
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, GainArmor, RequestChoice,
    ReturnToHand, Silence, Transform, ReplaceHeroPower)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_sources import CopyStoredMinion
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.generated_combo_repeats import PROFILES


def registry(mode='normal', target='spell', origins=('hand',), selected='left', combination='override',
             source_policy='inherit', copy_mode='current', profile=PROFILES[0], policies=None):
    r = base_registry(mode, policies, profile)
    def subject(c):
        if target == 'power': return c.state.entities[c.state.players[1].hero_power_id]
        return next(e for e in c.state.entities.values() if e.card_id == target and e.zone in (Zone.HAND, Zone.DECK))
    def preset(c):
        e = subject(c)
        reference = HeroPowerReference.capture(e) if e.kind == CardType.HERO_POWER else CardReference.capture(e)
        effect = SetChooseBranch(reference, selected, origins, combination, c.source_id)
        return (RequestChoice(1, (ChoiceOption('set', 'Set', (effect,)),), c.source_id),) if mode == 'set_wait' else (effect,)
    def clear(c):
        e = subject(c)
        reference = HeroPowerReference.capture(e) if e.kind == CardType.HERO_POWER else CardReference.capture(e)
        return (SetChooseBranch(reference, None, origins, source_id=c.source_id),)
    def copy(c):
        return (CopyCard(CardReference.capture(subject(c)), 1, mode=copy_mode, source_id=c.source_id),)
    def move(c):
        e = subject(c); ref = CardReference.capture(e)
        return (MoveCard(ref, 2 if mode == 'transfer' else 1, Zone.HAND if mode == 'transfer' else Zone.DECK,
                         reset=mode == 'reset', source_id=c.source_id),
                *((SetChooseBranch(ref, 'right', origins, source_id=c.source_id),) if mode == 'stale' else ()))
    def history(c):
        if mode == 'stored_conflict':
            from hs_sim.engine.spell_casts import CastStoredSpell
            return (CastStoredSpell(CardReference.capture(subject(c)), 1, c.source_id, branch_id='right'),)
        original = next(row for row in reversed(c.state.cast_history) if row.card_id == 'spell' and row.completed)
        return (RecastSpell(1, original.id, c.source_id, choices='player', branch_policy=source_policy),)
    def physical(c):
        from hs_sim.engine.effects import Destroy
        return (*(Destroy(i) for i in c.state.players[1].board if c.state.entities[i].card_id == 'minion'),
                ReplayWholeCards(1, c.source_id, WholeCardHistoryQuery(1, len(c.state.play_history)+1,
                    kinds=(CardType.MINION,)), choices='player', physical_profile=profile, physical_branch_policy=source_policy))
    def copy_body(c):
        from hs_sim.engine.summon_quantities import SummonCause
        cause = SummonCause.capture(c)
        if mode == 'stored_copy': return (CopyStoredMinion(CardReference.capture(subject(c)), 1, mode=copy_mode, cause=cause),)
        original = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'minion')
        return (CopyMinion(original, 1, mode=copy_mode, cause=cause),)
    for key, body in (('preset',preset),('clear',clear),('copy',copy),('move',move),('inherit',history),('physical',physical),('copy_body',copy_body)):
        r.register_behavior('branch.'+key, body)
        r.register_card(CardDefinition('branch_'+key, key, CardType.SPELL, on_play='branch.'+key))
    # Real descending Rewind faces differ only in the declared retry identity.
    original = r.card('rewind_spell')
    r.register_card(replace(original, id='branch_retry0', rewind=RewindSpec(2, 'branch_retry1')))
    r.register_card(replace(original, id='branch_retry1', rewind=RewindSpec(1, 'branch_retry2')))
    r.register_card(replace(original, id='branch_retry2', keywords=(), rewind=None))
    return r


def game(*, hand=('branch_preset','spell','branch_clear','branch_copy'), deck=('plain',)*7, board=(), **config):
    g = Game.from_scenario(Scenario((PlayerSetup('hero', hero_power_card_id='power', hand=hand, deck=deck,
        board=board, mana=10, max_mana=10), PlayerSetup('hero', board=('plain',), deck=('plain',)*7, mana=10,max_mana=10)),
        seed=76), registry(**config))
    return g


class ChooseBranchStateTests(unittest.TestCase):
    def check(self, g, **config):
        snap = g.snapshot()
        restored = Game.from_snapshot(snap, registry(**config))
        self.assertEqual(restored.snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(**config)).snapshot(), snap)
        for p in (1,2): self.assertEqual(g.observe(p), restored.observe(p))
        return restored
    def source(self,g,card='spell'):
        return next(e for e in g.state.entities.values() if e.card_id==card and e.zone in (Zone.HAND,Zone.DECK))
    def branch_actions(self,g,entity):
        return {a.branch_id for a in g.legal_actions() if isinstance(a,(PlayCard,UseHeroPower)) and a.entity_id==entity}
    def choose(self,g,option='go'):
        c=g.state.pending_choice; g.apply(SelectChoice(c.player_id,c.id,(option,)))
    def resign(self,snap):
        snap['events_hash']=canonical_hash(snap['events'])
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
        return snap
    def test_preselection_queries_are_pure_and_legal_actions_use_it(self):
        g=game(); play(g,'branch_preset'); e=self.source(g); before=g.snapshot()
        for _ in range(3):
            self.assertEqual(self.branch_actions(g,e.id),{'left'}); g.legal_targets(e.id,branch_id='left'); g.for_player(1).legal_actions()
        self.assertEqual(g.snapshot(),before); self.check(g)
    def test_wrong_and_missing_manual_branch_reject_without_payment(self):
        g=game(); play(g,'branch_preset'); e=self.source(g); before=g.snapshot()
        for branch in (None,'right','unknown'):
            with self.assertRaises(IllegalAction): g.apply(PlayCard(1,e.id,branch_id=branch))
            self.assertEqual(g.snapshot(),before)
    def test_clear_reopens_normal_options(self):
        g=game(); play(g,'branch_preset'); play(g,'branch_clear'); self.assertEqual(self.branch_actions(g,self.source(g).id),{'left','right'}); self.check(g)
    def test_preselected_combined_branch_without_live_sources(self):
        cfg=dict(selected='both'); g=game(**cfg); play(g,'branch_preset'); play(g,'spell','both')
        self.assertEqual(g.state.play_history[-1].branch_id,'both'); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,7); self.check(g,**cfg)
    def test_combination_overrides_preference_and_consumes_its_own_policy(self):
        g=game(hand=('branch_preset','policy','spell')); play(g,'branch_preset'); play(g,'policy')
        self.assertEqual(self.branch_actions(g,self.source(g).id),{'both'}); play(g,'spell','both')
        self.assertFalse(g.state.players[1].choose_both_modifiers); self.assertEqual(g.state.choose_policy_receipts[-1].branch_id,'both'); self.check(g)
    def test_strict_conflict_has_no_legal_root_and_rolls_back_automatic(self):
        cfg=dict(combination='strict',origins=('hand','cast_effect'), policies=(AddChooseBothModifier(1,uses=1,origins=('hand','cast_effect')),))
        g=game(hand=('branch_preset','policy','spell','stored'),**cfg)
        play(g,'branch_preset'); play(g,'policy'); self.assertEqual(self.branch_actions(g,self.source(g).id),set())
        before=g.snapshot()
        with self.assertRaises(ResolutionError): play(g,'stored')
        self.assertEqual(g.snapshot(),before); self.check(g,**cfg)
    def test_stored_cast_uses_preselection_without_branch_rng_or_payment(self):
        cfg=dict(origins=('cast_effect',)); g=game(hand=('branch_preset','spell','stored'),**cfg); play(g,'branch_preset'); before=g.snapshot()['rng_state']; play(g,'stored')
        self.assertEqual(g.state.cast_history[-1].branch_id,'left'); self.assertEqual(g.snapshot()['rng_state'],before); self.check(g,**cfg)
    def test_unauthorized_automatic_origin_still_selects_normally(self):
        g=game(hand=('branch_preset','spell','stored')); play(g,'branch_preset'); before=g.snapshot()['rng_state']; play(g,'stored')
        self.assertNotEqual(g.snapshot()['rng_state'],before); self.assertIn(g.state.cast_history[-1].branch_id,('left','right')); self.check(g)
    def test_new_automatic_entity_does_not_borrow_another_cards_recipe(self):
        cfg=dict(mode='auto_conflict',selected='right',origins=('cast_effect',))
        # Prescribed CastSpell creates a fresh entity and does not borrow another card's preference.
        g=game(hand=('branch_preset','spell','auto'),**cfg); play(g,'branch_preset'); play(g,'auto')
        self.assertEqual(g.state.cast_history[-1].branch_id,'left'); self.check(g,**cfg)
    def test_explicit_stored_branch_conflicting_with_recipe_rolls_back(self):
        cfg=dict(mode='stored_conflict',origins=('cast_effect',)); g=game(hand=('branch_preset','spell','branch_inherit'),**cfg)
        play(g,'branch_preset'); before=g.snapshot()
        with self.assertRaises(ResolutionError): play(g,'branch_inherit')
        self.assertEqual(g.snapshot(),before); self.check(g,**cfg)
    def test_draw_cast_reads_deck_preselection(self):
        cfg=dict(target='draw_spell',origins=('cast_draw',)); g=game(hand=('branch_preset','draw'),deck=('draw_spell','plain'),**cfg)
        play(g,'branch_preset'); before=g.snapshot()['rng_state']; play(g,'draw')
        self.assertEqual(next(c for c in g.state.cast_history if c.origin=='draw').branch_id,'left'); self.assertEqual(g.snapshot()['rng_state'],before); self.check(g,**cfg)
    def test_manual_and_effect_power_share_physical_preselection(self):
        cfg=dict(target='power',origins=('power_manual','power_effect')); g=game(hand=('branch_preset','trigger'),**cfg)
        play(g,'branch_preset'); p=g.state.players[1].hero_power_id; self.assertEqual(self.branch_actions(g,p),{'left'})
        g.apply(UseHeroPower(1,p,branch_id='left')); play(g,'trigger')
        self.assertEqual([r.branch_id for r in g.state.hero_power_history],['left','left']); self.assertEqual(g.state.entities[p].uses_this_turn,1); self.check(g,**cfg)
    def test_current_copy_inherits_but_base_copy_drops_preselection(self):
        for mode in ('current','base'):
            with self.subTest(mode=mode):
                cfg=dict(copy_mode=mode); g=game(**cfg); play(g,'branch_preset'); original=self.source(g).id; play(g,'branch_copy')
                copies=[g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id=='spell' and i!=original]
                self.assertEqual(len(copies),1); self.assertEqual(self.branch_actions(g,copies[0].id),{'left'} if mode=='current' else {'left','right'}); self.check(g,**cfg)
    def test_nonreset_transfer_keeps_recipe_for_new_controller(self):
        cfg=dict(mode='transfer'); g=game(hand=('branch_preset','spell','branch_move'),**cfg); play(g,'branch_preset'); play(g,'branch_move'); g.apply(EndTurn(1))
        e=self.source(g); self.assertEqual(e.controller,2); self.assertEqual(self.branch_actions(g,e.id),{'left'}); g.apply(PlayCard(2,e.id,branch_id='left')); self.check(g,**cfg)
    def test_reset_movement_clears_recipe(self):
        cfg=dict(mode='reset'); g=game(hand=('branch_preset','spell','branch_move'),**cfg); play(g,'branch_preset'); play(g,'branch_move'); self.assertIsNone(self.source(g).choose_branch); self.check(g,**cfg)
    def test_stale_reference_cannot_reselect_after_movement(self):
        cfg=dict(mode='stale'); g=game(hand=('branch_preset','spell','branch_move'),**cfg); play(g,'branch_preset'); play(g,'branch_move')
        self.assertEqual(self.source(g).choose_branch.branch_id,'left'); self.assertTrue(any(e.kind=='zone_target_skipped' for e in g.events)); self.check(g,**cfg)
    def test_board_copy_material_freezes_original_recipe(self):
        cfg=dict(target='minion'); g=game(hand=('branch_preset','minion','branch_copy_body'),**cfg); play(g,'branch_preset'); play(g,'minion','left'); play(g,'branch_copy_body')
        rows=[g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id=='minion']; self.assertEqual(len(rows),2)
        self.assertEqual(rows[0].choose_branch,rows[1].choose_branch); self.assertEqual(g.state.card_summon_history[-1].request.materials[0].local.choose_branch.branch_id,'left'); self.check(g,**cfg)
    def test_stored_copy_material_preserves_and_base_recipe_clears(self):
        for mode in ('current','base'):
            with self.subTest(mode=mode):
                cfg=dict(mode='stored_copy',target='minion',copy_mode=mode); g=game(hand=('branch_preset','minion','branch_copy_body'),**cfg)
                play(g,'branch_preset'); play(g,'branch_copy_body'); e=g.state.entities[g.state.players[1].board[0]]
                self.assertEqual(e.choose_branch is not None,mode=='current'); self.check(g,**cfg)
    def test_transform_and_bounce_reset_but_silence_retains_recipe(self):
        for mode in ('transform','bounce','silence'):
            with self.subTest(mode=mode):
                cfg=dict(mode=mode,target='minion'); g=game(hand=('branch_preset','minion','mutate'),**cfg); play(g,'branch_preset'); source=play(g,'minion','left'); play(g,'mutate')
                self.assertEqual(g.state.entities[source].choose_branch is not None,mode=='silence'); self.check(g,**cfg)
    def test_pending_preselection_effect_restores_before_application(self):
        cfg=dict(mode='set_wait'); g=game(**cfg); play(g,'branch_preset'); self.assertIsNone(self.source(g).choose_branch); other=self.check(g,**cfg)
        self.choose(g,'set'); self.choose(other,'set'); self.assertEqual(g.snapshot(),other.snapshot()); self.assertEqual(self.branch_actions(g,self.source(g).id),{'left'}); self.check(g,**cfg)
    def test_payload_wait_restores_frozen_branch_and_physical_recipe(self):
        cfg=dict(mode='wait'); g=game(**cfg); play(g,'branch_preset'); play(g,'spell','left'); other=self.check(g,**cfg)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(),other.snapshot()); self.assertEqual(g.state.cast_history[-1].branch_id,'left')
    def test_power_wait_restores_manual_and_effect_selected_roots(self):
        cfg=dict(mode='wait',target='power',origins=('power_manual','power_effect')); g=game(hand=('branch_preset','trigger'),**cfg)
        play(g,'branch_preset'); g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,branch_id='left')); self.check(g,**cfg); self.choose(g)
        play(g,'trigger'); self.check(g,**cfg); self.choose(g); self.assertEqual([p.branch_id for p in g.state.hero_power_history],['left','left']); self.check(g,**cfg)
    def test_repeated_paid_payload_reuses_preselected_branch_and_payment(self):
        g=game(hand=('branch_preset','spell'),board=('repeat',)); play(g,'branch_preset'); play(g,'spell','left')
        self.assertEqual([c.branch_id for c in g.state.cast_history if c.card_id=='spell'],['left','left'])
        self.assertEqual(g.state.players[1].mana,9); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4); self.check(g)
    def test_exception_restores_recipe_rng_and_payment(self):
        cfg=dict(mode='fail'); g=game(hand=('branch_preset','spell'),**cfg); play(g,'branch_preset'); before=g.snapshot()
        with self.assertRaises(ResolutionError): play(g,'spell','left')
        self.assertEqual(g.snapshot(),before); self.check(g,**cfg)
    def test_terminal_keeps_captured_branch_and_saved_recipe(self):
        cfg=dict(mode='terminal'); g=game(hand=('branch_preset','spell'),**cfg); play(g,'branch_preset'); source=play(g,'spell','left')
        self.assertEqual(g.state.status,'finished'); self.assertEqual(g.state.play_history[-1].branch_id,'left'); self.assertEqual(g.state.entities[source].choose_branch.branch_id,'left'); self.check(g,**cfg)
    def test_historical_cast_source_explicitly_inherits_or_reselects(self):
        for policy in ('inherit','current'):
            with self.subTest(policy=policy):
                cfg=dict(selected='both',source_policy=policy); g=game(hand=('branch_preset','spell','branch_inherit'),**cfg); play(g,'branch_preset'); play(g,'spell','both'); before=g.snapshot()['rng_state']; play(g,'branch_inherit')
                record=g.state.cast_history[-1]; self.assertEqual(record.origin,'history'); self.assertEqual(record.branch_id=='both',policy=='inherit'); self.assertEqual(g.snapshot()['rng_state']==before,policy=='inherit'); self.check(g,**cfg)
    def test_new_history_root_can_combine_and_consume_its_own_policy(self):
        p=(AddChooseBothModifier(1,uses=1,kinds=(CardType.SPELL,),origins=('cast_history',)),); cfg=dict(policies=p)
        g=game(hand=('branch_preset','spell','policy','branch_inherit'),**cfg); play(g,'branch_preset'); play(g,'spell','left'); play(g,'policy'); play(g,'branch_inherit')
        self.assertEqual(g.state.cast_history[-1].branch_id,'both'); self.assertEqual(len(g.state.choose_policy_receipts),1); self.assertFalse(g.state.players[1].choose_both_modifiers); self.check(g,**cfg)
    def test_four_physical_profiles_inherit_each_own_occurrence(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                cfg=dict(profile=profile); g=game(hand=('minion','minion','branch_physical'),**cfg); play(g,'minion','left'); play(g,'minion','right'); play(g,'branch_physical')
                choices=[c.physical.choose_one for c in g.state.whole_card_replay_ledger.children]
                self.assertEqual([c.inherited_branch_id for c in choices],['left','right']); self.assertEqual([c.branch_id for c in choices],['left','right']); self.assertTrue(all(c.rng_before==c.rng_after for c in choices)); self.check(g,**cfg)
    def test_physical_new_windows_combine_then_return_to_inherited_branch(self):
        p=(AddChooseBothModifier(1,uses=1,kinds=(CardType.MINION,),origins=('physical',)),); cfg=dict(policies=p)
        g=game(hand=('minion','minion','policy','branch_physical'),**cfg); play(g,'minion','left'); play(g,'minion','right'); play(g,'policy'); play(g,'branch_physical')
        self.assertEqual([c.physical.choose_one.branch_id for c in g.state.whole_card_replay_ledger.children],['both','right']); self.assertEqual(len(g.state.choose_policy_receipts),1); self.check(g,**cfg)
    def test_generated_wait_restores_and_rejects_inheritance_tampering(self):
        cfg=dict(mode='wait'); g=game(hand=('minion','branch_physical'),**cfg); play(g,'minion','right'); self.choose(g); play(g,'branch_physical'); self.check(g,**cfg)
        original=g.snapshot(); child=original['state']['whole_card_replay_ledger']['children'][0]
        for field,value in (('inherited_branch_id','left'),('branch_policy','current')):
            snap=deepcopy(original); snap['state']['whole_card_replay_ledger']['children'][0]['physical']['choose_one'][field]=value
            with self.assertRaises(SnapshotError): Game.from_snapshot(self.resign(snap),registry(**cfg))
        self.choose(g); self.check(g,**cfg)
    def test_rewind_face_rebind_preserves_preselection_and_original_payment(self):
        cfg=dict(target='branch_retry0'); g=game(hand=('branch_preset','branch_retry0'),**cfg); play(g,'branch_preset'); source=play(g,'branch_retry0','left')
        self.check(g,**cfg); self.choose(g,'retry'); self.assertEqual(g.state.entities[source].card_id,'branch_retry1'); self.assertEqual(g.state.entities[source].choose_branch.card_id,'branch_retry1'); self.check(g,**cfg)
        self.choose(g,'keep'); self.assertEqual(g.state.play_history[-1].branch_id,'left'); self.assertEqual(g.state.play_history[-1].cost,1); self.check(g,**cfg)
    def test_retained_rewind_results_rebind_recipe_and_pay_once(self):
        cfg=dict(target='branch_retry0'); g=game(hand=('branch_preset','branch_retry0'),board=('retainer',),**cfg)
        play(g,'branch_preset'); source=play(g,'branch_retry0','left')
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.state.entities[source].card_id,'branch_retry2')
        self.assertEqual(g.state.entities[source].choose_branch.card_id,'branch_retry2'); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,6)
        self.assertEqual(g.state.players[1].mana,9); self.check(g,**cfg)
    def test_hidden_enemy_hand_and_events_do_not_leak_preselection(self):
        g=game(); play(g,'branch_preset'); own=g.observe(1)['players'][0]['hand'][0]; enemy=g.observe(2)['players'][0]['hand'][0]
        self.assertEqual(own['choose_selection']['branch'],'left'); self.assertNotIn('choose_selection',enemy)
        self.assertFalse(any(e['kind']=='choose_branch_changed' for e in g.for_player(2).events())); self.check(g)
    def test_corrupted_selection_shape_origin_or_face_is_rejected(self):
        g=game(); play(g,'branch_preset'); original=g.snapshot(); identity=str(self.source(g).id)
        for field,value in (('card_id','minion'),('branch_id','unknown'),('origins',['physical']),('combination','unknown')):
            snap=deepcopy(original); snap['state']['entities'][identity]['choose_branch'][field]=value
            with self.assertRaises(SnapshotError): Game.from_snapshot(self.resign(snap),registry())
    def test_invalid_preselection_declarations_are_explicit_errors(self):
        for origins,policy in (((), 'override'),(('hand','hand'),'override'),(('mystery',),'override'),(('hand',),'unknown')):
            with self.assertRaises(ValueError): ChooseBranchSelection('spell','left',origins,policy)
        for target,origins in (('plain',('hand',)),('power',('hand',)),('spell',('power_effect',))):
            cfg=dict(target=target,origins=origins); g=game(hand=('branch_preset','plain','spell'),**cfg); before=g.snapshot()
            with self.assertRaises(ResolutionError): play(g,'branch_preset')
            self.assertEqual(g.snapshot(),before)
    def test_inheritance_request_rejects_unknown_policy_and_ambiguous_override(self):
        q=WholeCardHistoryQuery(1,1,kinds=(CardType.MINION,))
        with self.assertRaises(ValueError): ReplayWholeCards(1,1,q,physical_branch_policy='inherit')
        with self.assertRaises(ValueError): ReplayWholeCards(1,1,q,physical_profile=PROFILES[0],physical_branch_policy='inherit',physical_branch_id='left')
        with self.assertRaises(ValueError): RecastSpell(1,1,branch_policy='unknown')


if __name__=='__main__': unittest.main()
