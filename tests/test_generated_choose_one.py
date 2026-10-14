"""Generated Choose One: pre-install branch policy, actual post-install body."""
from copy import deepcopy
from dataclasses import replace
import json
import random
import unittest

from hs_sim.engine import (BodyReference, BodyTargetBinding, BodyTargetProfile, CardDefinition,
    CardType, ChooseBranch, ChooseOneSpec, Game, GeneratedWholeTargetBinding, GrantBattlecry,
    GrantCombo, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.choose_one import GrantChooseBoth
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, GainArmor,
    RandomDamage, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.registry import Registry
from hs_sim.engine.model import BattlecryRepeatSpec, ComboRepeatSpec, RewindSpec
from hs_sim.engine.battlecry_modifiers import AddBattlecryRepeatModifier
from hs_sim.engine.combo_modifiers import AddComboRepeatModifier
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.generated_combo_repeats import SINGLE_PROFILES, REPEAT_PROFILES

PROFILES = (*SINGLE_PROFILES, *REPEAT_PROFILES)


def registry(mode='normal', profile=PROFILES[0], explicit=None, binding=True):
    r = Registry('generated-choice-'+mode+'-'+profile+'-'+str(explicit)+'-'+str(binding)+'-v1')
    r.register_behavior('armor', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    r.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, on_use='armor'))
    for name, health in (('tiny', 4), ('big', 12), ('plain', 8)):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=health))
    r.register_card(CardDefinition('both_source', 'Combined source', CardType.MINION, health=8, choose_both=True))
    r.register_card(CardDefinition('holder', 'Retained holder', CardType.MINION, health=8, retain_rewind_outcomes=True))
    enemy = TargetSpec(kinds=(CardType.MINION,), zones=(Zone.BOARD,), relation='enemy')
    friend = TargetSpec(kinds=(CardType.MINION,), zones=(Zone.BOARD,), relation='friendly', exclude_source=True)
    ownhero = TargetSpec(kinds=(CardType.HERO,), zones=(Zone.HERO,), relation='friendly')
    def branch_body(c, name, amount):
        if c.physical is None: return ()
        work = [GainArmor(c.player_id, amount)]
        if c.target_id is not None: work.append(Damage(c.target_id, 1))
        if mode == 'root_wait': work.append(RequestChoice(c.player_id, (ChoiceOption('go', 'Go'),), c.source_id))
        elif mode == 'root_grant': work.append(GrantChooseBoth(c.source_id, c.source_id))
        elif mode == 'fail': work.extend((RandomDamage(tuple(c.state.players[2].board), 1), Summon(c.player_id, 'unknown.choice.result')))
        elif mode == 'terminal': work.append(Damage(c.state.players[2].hero_id, 90))
        return tuple(work)
    for name, amount in (('left', 10), ('right', 20), ('both', 30)):
        r.register_behavior('branch.'+name, lambda c, n=name, a=amount: branch_body(c, n, a))
    def family(c):
        if c.physical is None: return ()
        work = []
        if c.battlecry is not None and mode == 'bc_transform': work.append(Transform(c.source_id, 'plain'))
        if c.battlecry is not None and mode == 'bc_control': work.append(ChangeControl(c.source_id, 2))
        if c.battlecry is not None and mode == 'bc_bounce': work.append(ReturnToHand(c.source_id))
        work.append(GainArmor(c.player_id, 1 if c.battlecry is not None else 2))
        return tuple(work)
    r.register_behavior('family', family)
    keywords = (Keyword.REWIND,) if profile == PROFILES[3] else ()
    r.register_card(CardDefinition('chooser', 'Chooser', CardType.MINION, cost=1, attack=1, health=8,
        choose_one=ChooseOneSpec((ChooseBranch('left', 'Left', 'branch.left', enemy),
            ChooseBranch('right', 'Right', 'branch.right', friend)), ChooseBranch('both', 'Both', 'branch.both', ownhero)),
        keywords=keywords,
        choose_both=mode == 'own_both', rewind=RewindSpec() if profile == PROFILES[3] else None))
    r.register_card(CardDefinition('donor', 'Donor', CardType.MINION, health=5,
        battlecry='family', combo='family', keywords=(Keyword.COMBO,)))
    def entry(c):
        ledger = c.state.whole_card_replay_ledger
        if not ledger.stack or c.event.target_id is None or c.state.entities[c.event.target_id].card_id != 'chooser': return ()
        if mode == 'entry_silence': return (Silence(c.event.target_id),)
        ref = BodyReference.capture(c.state.entities[c.event.target_id])
        result = [GrantBattlecry(ref, 'donor', c.source_id), GrantCombo(ref, 'donor', c.source_id)]
        if mode == 'entry_grant': result.append(GrantChooseBoth(c.event.target_id, c.source_id))
        if mode == 'entry_remove': result.extend(Silence(i) for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == 'both_source')
        if mode == 'entry_wait': result.append(RequestChoice(c.player_id, (ChoiceOption('go', 'Go'),), c.source_id))
        if mode == 'entry_random': result.append(RandomDamage(tuple(c.state.players[2].board), 1))
        if mode == 'grant_body': result.extend((GrantBattlecry(ref, 'donor', c.source_id), GrantCombo(ref, 'donor', c.source_id)))
        return tuple(result)
    r.register_behavior('entry', entry)
    r.register_card(CardDefinition('watch', 'Watch', CardType.MINION, health=8, triggers=(TriggerSpec('minion_summoned', 'entry'),)))
    def generate(c):
        # Remove historical physical carriers, keeping their committed records.
        work = [Destroy(i) for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == 'chooser']
        if mode == 'empty_left': work.extend(Destroy(i) for i in c.state.players[2].board)
        if mode == 'full': work.extend(Summon(c.player_id, 'plain') for _ in range(7))
        work.append(ReplayWholeCards(2 if mode == 'other' else c.player_id, c.source_id,
            WholeCardHistoryQuery(c.player_id, len(c.state.play_history)+1, kinds=(CardType.MINION,)),
            physical_profile=profile, choices='random' if mode == 'random_internal' else 'player',
            body_target_profile_id='generated' if binding else None, physical_branch_id=explicit))
        return tuple(work)
    r.register_behavior('generate', generate)
    r.register_card(CardDefinition('generate', 'Generate', CardType.SPELL, cost=1, on_play='generate'))
    r.register_behavior('policies', lambda c: (AddBattlecryRepeatModifier(c.player_id, BattlecryRepeatSpec(2), c.source_id, uses=1),
        AddComboRepeatModifier(c.player_id, ComboRepeatSpec(3), c.source_id, uses=1, trigger='activation')))
    r.register_card(CardDefinition('policies', 'Policies', CardType.SPELL, on_play='policies'))
    if binding:
        r.register_body_target_profile(BodyTargetProfile('generated', 'generated_whole', 'random', 'generated_acceptance'))
        r.register_generated_whole_target_binding(GeneratedWholeTargetBinding('chooser', 'generated', 'preserve_root'))
        for card, origin in (('donor', 'granted'),):
            for family in ('battlecry', 'combo'):
                r.register_body_target_binding(BodyTargetBinding(card, family, 'generated', origins=(origin,), carrier_card_ids=('chooser',)))
    return r


class GeneratedChooseOneTests(unittest.TestCase):
    def game(self, mode='normal', profile=PROFILES[0], explicit=None, binding=True, *, combined=False, twice=False, policies=False):
        board = ('watch', 'tiny') + (('both_source',) if combined else ()) + (('holder',) if profile == PROFILES[3] else ())
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('chooser',)+(('chooser',) if twice else ())+('policies','generate'),
            board=board, mana=10, max_mana=10, hero_power_card_id='power'),
            PlayerSetup('hero', board=('tiny','big'), hand=('plain',), mana=10, max_mana=10, hero_power_card_id='power')), seed=3),
            registry(mode, profile, explicit, binding))
        for _ in range(2 if twice else 1):
            available = ('both',) if combined or mode == 'own_both' and any(g.state.entities[i].card_id == 'chooser' for i in g.state.players[1].board) else ('left',)
            selected = available[0]
            target = g.state.players[1].hero_id if selected == 'both' else g.state.players[2].board[-1]
            self.play(g, 'chooser', target, selected)
        if policies: self.play(g, 'policies')
        return g

    def play(self, g, card, target=None, branch=None):
        entity = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == card)
        return g.apply(PlayCard(1, entity, target, branch_id=branch))

    def progress(self, g): return g.state.whole_card_replay_ledger.children[-1].physical

    def settled(self, mode='normal', profile=PROFILES[0], explicit=None, binding=True, **kw):
        g = self.game(mode, profile, explicit, binding, **kw); self.play(g, 'generate'); return g

    def portable(self, g, mode='normal', profile=PROFILES[0], explicit=None, binding=True):
        value = json.loads(json.dumps(g.snapshot()))
        branches = (Game.from_snapshot(value, registry(mode, profile, explicit, binding)), g.clone(),
            replay(build_replay(g), registry(mode, profile, explicit, binding)))
        for branch in branches:
            self.assertEqual(branch.snapshot(), value)
            for seat in (1,2): self.assertEqual(branch.observe(seat), g.observe(seat))
        return branches

    def reject(self, g, mutate, mode='normal', profile=PROFILES[0], explicit=None):
        value = deepcopy(g.snapshot()); mutate(value)
        value['state_hash'] = canonical_hash({k:v for k,v in value.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(value, registry(mode, profile, explicit))
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_random_branch_precedes_target_and_uses_actual_generated_identity(self):
        g = self.settled(); p = self.progress(g); receipt = p.choose_one
        self.assertEqual(receipt.options, ('left','right'))
        probe = random.Random(); probe.setstate(receipt.rng_before)
        self.assertEqual(receipt.branch_id, probe.choice(receipt.options))
        self.assertEqual(receipt.rng_after, probe.getstate())
        self.assertEqual(receipt.rng_after, p.selection.rng_before)
        self.assertEqual((len(p.battlecry_ids),len(p.combo_ids)), (1,1))
        self.assertEqual(len(g.state.play_history),2)
        self.portable(g)

    def test_prescribed_branch_does_not_use_branch_rng(self):
        g = self.settled(explicit='right'); p = self.progress(g)
        self.assertEqual(p.choose_one.branch_id, 'right')
        self.assertEqual(p.choose_one.rng_before,p.choose_one.rng_after)
        self.assertIn(p.selection.target_id,g.state.players[1].board)
        self.portable(g, explicit='right')

    def test_combined_sources_select_single_full_branch_without_branch_draw(self):
        g = self.settled(combined=True); p = self.progress(g)
        self.assertEqual(p.choose_one.options, ('both',))
        self.assertTrue(p.choose_one.combined_source_ids)
        self.assertEqual(p.choose_one.rng_before,p.choose_one.rng_after)
        self.assertEqual(p.selection.target_id,g.state.players[1].hero_id)
        self.portable(g)

    def test_entry_gain_of_combination_does_not_rewrite_branch(self):
        g = self.settled('entry_grant'); p = self.progress(g)
        self.assertEqual(p.choose_one.options, ('left','right'))
        self.assertIn(p.choose_one.branch_id, ('left','right'))
        self.portable(g,'entry_grant')

    def test_entry_loss_of_combination_preserves_accepted_combined_branch(self):
        g = self.settled('entry_remove',combined=True); p = self.progress(g)
        self.assertEqual(p.choose_one.branch_id,'both')
        self.assertEqual(p.selection.target_id,g.state.players[1].hero_id)
        self.portable(g,'entry_remove')

    def test_own_new_combined_ability_does_not_authorize_its_first_branch(self):
        g = self.settled('own_both'); self.assertEqual(self.progress(g).choose_one.options, ('left','right'))
        self.portable(g,'own_both')

    def test_later_child_accepts_new_combination_from_preceding_child(self):
        g = self.settled('own_both',twice=True); rows = [c.physical for c in g.state.whole_card_replay_ledger.children]
        self.assertEqual([p.choose_one.options for p in rows], [('left','right'),('both',)])
        self.assertNotEqual(rows[0].choose_one.child_id,rows[1].choose_one.child_id)
        self.assertEqual(rows[1].choose_one.combined_source_ids,tuple(a.id for a in g.state.entities[rows[0].source.entity_id].abilities if a.kind=='choose_both'))
        self.portable(g,'own_both')

    def test_empty_chosen_target_does_not_remove_branch_from_probability_pool(self):
        g = self.settled('empty_left'); p = self.progress(g)
        self.assertEqual(p.choose_one.options,('left','right'))
        self.assertEqual(p.choose_one.branch_id,'left')
        self.assertEqual(p.selection.failure,'no_target')
        self.assertEqual((len(p.battlecry_ids),len(p.combo_ids)),(1,1))
        self.portable(g,'empty_left')

    def test_empty_chosen_target_in_legacy_common_route_records_explicit_failure(self):
        g = self.settled('empty_left',explicit='left',binding=False); p = self.progress(g)
        self.assertEqual(p.failure,'no_target')
        self.assertEqual(p.choose_one.branch_id,'left')
        self.assertIsNone(p.activation)
        self.portable(g,'empty_left',explicit='left',binding=False)

    def test_full_board_keeps_branch_receipt_without_fake_installation(self):
        g = self.settled('full'); p = self.progress(g)
        self.assertEqual(p.failure,'board_full')
        self.assertIsNone(p.source); self.assertIsNone(p.activation)
        self.assertEqual(p.combo_ids,()); self.assertIsNotNone(p.choose_one)
        self.portable(g,'full')

    def test_silenced_entry_keeps_branch_but_no_ordinary_target_rng(self):
        g = self.settled('entry_silence'); p = self.progress(g)
        self.assertEqual(p.on_play,()); self.assertEqual(p.body_targets.slots,())
        self.assertEqual(p.selection.rng_before,p.selection.rng_after)
        self.assertEqual(p.choose_one.rng_after,p.selection.rng_before)
        self.portable(g,'entry_silence')

    def test_entry_random_work_can_advance_rng_between_branch_and_target(self):
        g = self.settled('entry_random'); p = self.progress(g)
        self.assertNotEqual(p.choose_one.rng_after,p.selection.rng_before)
        self.portable(g,'entry_random')

    def test_entry_choice_restores_full_pre_install_branch_before_body_acceptance(self):
        g = self.settled('entry_wait'); p = self.progress(g)
        self.assertEqual(p.phase,'installing'); self.assertIsNone(p.activation)
        self.assertIsNotNone(p.choose_one); self.assertIsNone(p.selection)
        branches = (g,*self.portable(g,'entry_wait'))
        action = SelectChoice(1,g.state.pending_choice.id,('go',))
        for b in branches: b.apply(action)
        self.assertTrue(all(b.snapshot()==g.snapshot() for b in branches))
        self.assertEqual(self.progress(g).choose_one,p.choose_one)

    def test_root_body_wait_restores_independent_branch_proof_and_dispatch(self):
        g = self.settled('root_wait'); p = self.progress(g)
        self.assertIsNotNone(g.state.pending_choice)
        branches = (g,*self.portable(g,'root_wait'))
        action = SelectChoice(1,g.state.pending_choice.id,('go',))
        for b in branches: b.apply(action)
        self.assertTrue(all(b.snapshot()==g.snapshot() for b in branches))
        self.assertEqual(self.progress(g).choose_one,p.choose_one)

    def test_battlecry_transform_does_not_substitute_original_branch_body(self):
        g = self.settled('bc_transform'); p = self.progress(g)
        self.assertEqual(g.state.entities[p.source.entity_id].card_id,'plain')
        self.assertEqual(p.choose_one.card_id,'chooser')
        self.portable(g,'bc_transform')

    def test_battlecry_control_change_keeps_original_branch_executor(self):
        g = self.settled('bc_control'); p = self.progress(g)
        self.assertEqual(g.state.entities[p.source.entity_id].controller,2)
        self.assertEqual(p.choose_one.player_id,1)
        self.assertTrue(all(g.state.combo_history[i-1].player_id==1 for i in p.combo_ids))
        self.portable(g,'bc_control')

    def test_battlecry_bounce_does_not_borrow_paid_dispatch(self):
        g = self.settled('bc_bounce'); p = self.progress(g)
        self.assertEqual(g.state.entities[p.source.entity_id].zone,Zone.HAND)
        self.assertEqual(p.choose_one.card_id,'chooser')
        self.assertEqual(len(g.state.play_history),2)
        self.portable(g,'bc_bounce')

    def test_root_gain_of_combination_keeps_accepted_branch(self):
        g = self.settled('root_grant'); p = self.progress(g)
        self.assertIn(p.choose_one.branch_id,('left','right'))
        self.portable(g,'root_grant')

    def test_single_profile_keeps_repeat_policies_unused(self):
        g = self.settled(policies=True); p = self.progress(g)
        self.assertEqual((len(p.battlecry_ids),len(p.combo_ids)),(1,1))
        self.assertEqual(g.state.players[1].battlecry_modifiers[0].uses_remaining,1)
        self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining,1)

    def test_battlecry_repeat_profile_keeps_branch_once_and_combo_single(self):
        g = self.settled(profile=PROFILES[1],policies=True); p = self.progress(g)
        self.assertEqual((len(p.battlecry_ids),len(p.combo_ids)),(2,1))
        self.assertEqual(p.on_play,('engine.choose_one',))
        self.assertEqual(g.state.players[1].battlecry_modifiers,[])
        self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining,1)
        self.portable(g,profile=PROFILES[1])

    def test_family_repeat_profile_has_independent_counts_and_one_branch(self):
        g = self.settled(profile=PROFILES[2],policies=True); p = self.progress(g)
        self.assertEqual((len(p.battlecry_ids),len(p.combo_ids)),(2,3))
        self.assertEqual(g.state.players[1].battlecry_modifiers,[])
        self.assertEqual(g.state.players[1].combo_modifiers,[])
        self.portable(g,profile=PROFILES[2])

    def test_retained_results_reuse_branch_and_original_target(self):
        g = self.settled('root_grant',profile=PROFILES[3],policies=True); p = self.progress(g)
        self.assertEqual((len(p.battlecry_ids),len(p.combo_ids)),(4,6))
        self.assertEqual(p.choose_one.options,('left','right'))
        self.assertIn(p.choose_one.branch_id,('left','right'))
        self.portable(g,'root_grant',PROFILES[3])

    def test_granted_battlecry_and_combo_share_no_branch_target_identity(self):
        g = self.settled('grant_body'); p = self.progress(g)
        self.assertEqual((len(p.battlecry_ids),len(p.combo_ids)),(2,2))
        self.assertTrue(all(s.selected.target_id is None for s in p.body_targets.slots))
        self.assertIsNotNone(p.selection.target_id)
        self.portable(g,'grant_body')

    def test_other_executor_has_own_branch_and_disabled_combo(self):
        g = self.settled('other'); p = self.progress(g)
        self.assertEqual(p.choose_one.player_id,2)
        self.assertEqual(p.combo_repeat_acceptance.status,'disabled')
        self.assertEqual(p.combo_ids,())
        self.portable(g,'other')

    def test_invalid_prescription_rolls_back_original_payment_and_branch_rng(self):
        g = self.game(explicit='unknown'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'generate')
        self.assertEqual(g.snapshot(),before)

    def test_prescription_conflicting_with_combined_policy_is_atomic(self):
        g = self.game(explicit='left',combined=True); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'generate')
        self.assertEqual(g.snapshot(),before)

    def test_unknown_selected_body_rolls_back_installation_history_payment_and_rng(self):
        g = self.game('fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'generate')
        self.assertEqual(g.snapshot(),before)

    def test_terminal_branch_stops_unstarted_combo_without_fake_identity(self):
        g = self.settled('terminal'); p = self.progress(g)
        self.assertNotEqual(g.state.status,'playing')
        self.assertEqual(p.combo_ids,())
        self.portable(g,'terminal')

    def test_compact_branch_options_and_draw_cannot_be_changed_after_rehash(self):
        g = self.settled()
        def trim(s): s['state']['whole_card_replay_ledger']['children'][0]['physical']['choose_one']['options']=['left']
        self.reject(g,trim)
        self.reject(g,lambda s:s['state']['whole_card_replay_ledger']['children'][0]['physical']['choose_one'].__setitem__('branch_id','both'))

    def test_actual_child_cannot_erase_or_borrow_branch_receipt(self):
        g = self.settled()
        self.reject(g,lambda s:s['state']['whole_card_replay_ledger']['children'][0]['physical'].__setitem__('choose_one',None))
        self.reject(g,lambda s:s['state']['whole_card_replay_ledger']['children'][0]['physical']['choose_one'].__setitem__('child_id',999))

    def test_combined_original_source_ids_cannot_be_trimmed(self):
        g = self.settled(combined=True)
        self.reject(g,lambda s:s['state']['whole_card_replay_ledger']['children'][0]['physical']['choose_one'].__setitem__('combined_source_ids',[]))

    def test_player_ports_never_receive_original_board_proof_or_branch_rng(self):
        g = self.settled('entry_wait')
        for seat in (1,2):
            value=json.dumps(g.observe(seat),ensure_ascii=False)
            for private in ('original_board_json','choose_proof','rng_before','combo_policy_receipts'):
                self.assertNotIn(private,value)

    def test_choose_one_binding_cannot_override_or_erase_branch_target_domain(self):
        r = registry()
        for mode in ('body_only','explicit_root'):
            with self.assertRaises(ValueError): r.register_generated_whole_target_binding(GeneratedWholeTargetBinding('chooser','generated',mode))

    def test_current_schema_rejects_prior_missing_generated_branch_semantics(self):
        g = self.settled(); s = g.snapshot(); self.assertEqual(s['schema_version'],265)
        s['schema_version']=137
        with self.assertRaises(SnapshotError): Game.from_snapshot(s,registry())

    def test_pending_install_cannot_trim_original_board_while_retaining_full_proof(self):
        g = self.settled('entry_wait')
        def mutate(s):
            def walk(value):
                if type(value) is dict:
                    if type(value.get('original_board_json')) is list:
                        value['original_board_json'] = value['original_board_json'][1:]
                    if str(value.get('type','')).endswith('.GeneratedChooseOneReceipt'):
                        row = value['fields']['original_board_json']['tuple']
                        value['fields']['original_board_json']['tuple'] = row[1:]
                    for child in value.values(): walk(child)
                elif type(value) is list:
                    for child in value: walk(child)
            walk(s)
        self.reject(g,mutate,'entry_wait')

    def test_pending_body_cannot_erase_its_original_branch_finish_proof(self):
        g = self.settled('root_wait')
        def mutate(s):
            def walk(value):
                if type(value) is dict:
                    if str(value.get('type','')).endswith('.PhysicalBodyProof'):
                        value['fields']['choose_proof']=None
                    for child in value.values(): walk(child)
                elif type(value) is list:
                    for child in value: walk(child)
            walk(s['resolution_frame'])
        self.reject(g,mutate,'root_wait')

    def test_existing_ancient_of_war_executes_combined_generated_branch(self):
        from hs_sim.engine import GenerationContext
        from hs_sim.engine.representative import build_registry

        def war_registry():
            r = build_registry()
            r.register_behavior('test.generated.war', lambda c: (ReplayWholeCards(c.player_id, c.source_id,
                WholeCardHistoryQuery(c.player_id, len(c.state.play_history)+1, kinds=(CardType.MINION,)),
                physical_profile=PROFILES[0]),))
            r.register_card(CardDefinition('test.generated.war', 'Test producer', CardType.SPELL,
                on_play='test.generated.war'))
            return r

        g = Game.from_scenario(Scenario((PlayerSetup('HERO_06', hand=('EX1_178','test.generated.war'),
            board=('OG_044',), mana=10, max_mana=10), PlayerSetup('HERO_08')), seed=72,
            generation_context=GenerationContext('local-2026-09-23','experimental')), war_registry())
        self.play(g,'EX1_178',branch='both')
        original = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == 'EX1_178')
        self.play(g,'test.generated.war')
        progress = self.progress(g); carrier = g.state.entities[progress.source.entity_id]
        self.assertNotEqual(carrier.id,original)
        self.assertEqual(progress.choose_one.branch_id,'both')
        self.assertEqual(progress.choose_one.options,('both',))
        self.assertEqual((carrier.attack,carrier.health),(10,10))
        self.assertIn(Keyword.TAUNT,carrier.keywords)
        self.assertEqual(len(g.state.play_history),2)
        value = json.loads(json.dumps(g.snapshot()))
        for match in (Game.from_snapshot(value,war_registry()),g.clone(),replay(build_replay(g),war_registry())):
            self.assertEqual(match.snapshot(),value)
            for seat in (1,2): self.assertEqual(match.observe(seat),g.observe(seat))

    def test_ordinary_child_rejects_a_physical_branch_request_atomically(self):
        g = Game.from_scenario(Scenario((PlayerSetup('hero',hand=('plain','generate'),mana=10,max_mana=10,
            hero_power_card_id='power'),PlayerSetup('hero',hero_power_card_id='power')),seed=3),registry(explicit='left',binding=False))
        self.play(g,'plain'); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'generate')
        self.assertEqual(g.snapshot(),before)
