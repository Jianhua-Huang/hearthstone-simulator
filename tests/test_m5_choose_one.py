"""Pre-activation branch identity, legality and composition; provisional R-112."""
import json
import unittest
from dataclasses import replace
from hs_sim.engine import (Game, Registry, CardDefinition, CardType, Scenario, PlayerSetup,
    PlayCard, UseHeroPower, SelectChoice, EndTurn, ChooseBranch, ChooseOneSpec, GrantChooseBoth,
    TargetSpec, TargetMode, Keyword, RewindSpec, SpellRepeatSpec, TriggerSpec,
    AddHeroPower, TriggerHeroPower, CastSpell, IllegalAction, ResolutionError, SnapshotError,
    CostSpec, PaymentType, CounterSpell, RedirectSpellTarget, CastWhenDrawnSpec,
    CastStoredSpell, RecastSpell, SecretSpec, QuestSpec, QuestStageSpec, ShatterSpec)
from hs_sim.engine.effects import (GainArmor, Damage, Draw, Buff, Summon, Silence, Destroy,
    CopyMinion, ChangeControl, Transform, ReturnToHand, ModifyCost, RequestChoice, ChoiceOption,
    InvokeBehavior, RefreshHeroPower, ReplaceHeroPower)
from hs_sim.engine.zones import CardReference, AddToDeck
from hs_sim.engine.actions import action_to_dict, action_from_dict
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.replay import build_replay, replay


class ChooseOneTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('choose-one-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        self.r.register_card(CardDefinition('body','body',CardType.MINION,attack=1,health=8))
        self.r.register_card(CardDefinition('both','both',CardType.MINION,health=4,choose_both=True))
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=4,spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        self.r.register_card(CardDefinition('retainer','retainer',CardType.MINION,health=4,retain_rewind_outcomes=True))
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,2)])
        self.r.register_behavior('damage',lambda c:[] if c.target_id is None else [Damage(c.target_id,3,c.source_id)])
        self.r.register_behavior('combined',lambda c:[GainArmor(c.player_id,7)])
        self.spec=ChooseOneSpec((ChooseBranch('armor','Armor','armor'),
            ChooseBranch('damage','Damage','damage',TargetSpec(kinds=(CardType.MINION,),relation='enemy'))),
            ChooseBranch('both','Both','combined'))
        self.card('choice',self.spec)
        self.card('power',self.spec,kind=CardType.HERO_POWER)

    def card(self,cid,spec,kind=CardType.SPELL,**kw):
        if kind==CardType.MINION:kw.setdefault('health',4)
        self.r.register_card(CardDefinition(cid,cid,kind,cost=2,choose_one=spec,**kw))
    def script(self,cid,fn):
        self.r.register_behavior(cid,fn);self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    def watch(self,cid,fn,event='card_committed'):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,triggers=(TriggerSpec(event,cid),)))
    def game(self,hand=('choice',),board=(),enemy=('body',),power='power',mana=10,seed=72):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('body',)*6,
            hero_power_card_id=power,mana=mana,max_mana=10),PlayerSetup('hero',board=enemy,
            hand=('choice',),deck=('body',)*6,mana=10,max_mana=10)),seed=seed),self.r)
    def play(self,g,cid='choice',branch='armor',target=None):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,i,target,branch_id=branch));return i
    def use(self,g,branch='armor',target=None,power=None):
        g.apply(UseHeroPower(1,power or g.state.players[1].hero_power_id,target,branch))
    def choose(self,g,option='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(option,)))
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def enemy(self,g):return g.state.entities[g.state.players[2].board[0]]
    def pause(self,c):return RequestChoice(1,(ChoiceOption('ok','OK',()),),source_id=c.source_id)
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_manual_branch_pays_and_records_once_without_pending_choice(self):
        g=self.game();self.play(g)
        self.assertEqual((self.armor(g),g.state.players[1].mana),(2,8))
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual([p.branch_id for p in g.state.play_history],['armor'])
        self.assertEqual([p.branch_id for p in g.state.cast_history],['armor']);self.check(g)
    def test_branch_targets_are_enumerated_separately(self):
        g=self.game();i=g.state.players[1].hand[0];target=self.enemy(g).id
        actions=[a for a in g.legal_actions() if type(a) is PlayCard]
        self.assertEqual(set((a.branch_id,a.target_id) for a in actions),{('armor',None),('damage',target)})
        self.assertEqual(g.legal_targets(i,branch_id='damage'),(target,))
        with self.assertRaises(IllegalAction):g.legal_targets(i)
    def test_no_target_branch_works_when_targeted_branch_is_unavailable(self):
        g=self.game(enemy=());self.assertEqual([a.branch_id for a in g.legal_actions() if type(a) is PlayCard],['armor'])
        self.play(g);self.assertEqual(self.armor(g),2);self.check(g)
    def test_missing_unknown_or_unavailable_branch_rolls_back_before_payment(self):
        g=self.game();s=g.snapshot()
        for b in (None,'missing','both'):
            with self.subTest(branch=b),self.assertRaises(IllegalAction):self.play(g,branch=b)
            self.assertEqual(g.snapshot(),s)
    def test_unselected_target_rule_does_not_reject_untargeted_branch(self):
        g=self.game();self.play(g);self.assertEqual(self.enemy(g).health,8)
    def test_target_cannot_be_attached_to_untargeted_branch(self):
        g=self.game();s=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,target=self.enemy(g).id)
        self.assertEqual(g.snapshot(),s)
    def test_damage_branch_requires_correct_side_and_target(self):
        g=self.game(board=('body',));s=g.snapshot()
        for target in (None,g.state.players[1].board[0],g.state.players[2].hero_id):
            with self.assertRaises(IllegalAction):self.play(g,branch='damage',target=target)
            self.assertEqual(g.snapshot(),s)
        self.play(g,branch='damage',target=self.enemy(g).id);self.assertEqual(self.enemy(g).health,5);self.check(g)
    def test_all_branches_unavailable_gives_no_action(self):
        targeted=ChooseBranch('a','a','damage',TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.card('targeted',ChooseOneSpec((targeted,replace(targeted,id='b')),replace(targeted,id='both')))
        g=self.game(hand=('targeted',),enemy=());self.assertFalse(any(type(a) is PlayCard for a in g.legal_actions()))
    def test_branch_board_requirement_does_not_block_other_branch(self):
        self.card('space',replace(self.spec,branches=(replace(self.spec.branches[0],requires_board_space=True),self.spec.branches[1])))
        g=self.game(hand=('space',),board=('body',)*7)
        self.assertEqual([a.branch_id for a in g.legal_actions() if type(a) is PlayCard],['damage']);self.check(g)
    def test_minion_target_if_available_can_play_without_preexisting_target(self):
        branch=ChooseBranch('a','a','damage',TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,),exclude_source=True))
        self.card('minion',ChooseOneSpec((branch,replace(branch,id='b')),replace(branch,id='both')),kind=CardType.MINION)
        g=self.game(hand=('minion',),enemy=());self.play(g,'minion','a')
        self.assertEqual(len(g.state.players[1].board),1);self.assertIsNone(g.state.play_history[0].target_id);self.check(g)
    def test_minion_branch_is_not_paid_or_counted_as_an_extra_card(self):
        self.card('minion',self.spec,kind=CardType.MINION)
        g=self.game(hand=('minion',));self.play(g,'minion')
        self.assertEqual((len(g.state.play_history),len(g.state.cast_history),self.armor(g)),(1,0,2));self.check(g)
    def test_combined_is_explicit_payload_not_automatic_concatenation(self):
        g=self.game(board=('both',));self.assertEqual([a.branch_id for a in g.legal_actions() if type(a) is PlayCard],['both'])
        self.play(g,branch='both');self.assertEqual((self.armor(g),self.enemy(g).health),(7,8));self.check(g)
    def test_multiple_combination_sources_do_not_duplicate_payload(self):
        g=self.game(board=('both','both'));self.play(g,branch='both');self.assertEqual(self.armor(g),7);self.check(g)
    def test_combination_gained_during_commit_does_not_change_captured_branch(self):
        self.watch('gain',lambda c:[Summon(1,'both')])
        g=self.game(board=('gain',));self.play(g);self.assertEqual(self.armor(g),2);self.check(g)
    def test_combination_lost_during_commit_does_not_change_captured_branch(self):
        self.watch('lose',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(board=('both','lose'));self.play(g,branch='both');self.assertEqual(self.armor(g),7);self.check(g)
    def test_silence_removes_combination_before_play(self):
        self.script('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(board=('both',),hand=('silence','choice'));self.play(g,'silence',None);self.play(g)
        self.assertEqual(self.armor(g),2);self.check(g)
    def test_control_transfer_moves_combination_policy(self):
        self.script('take',lambda c:[ChangeControl(c.state.players[2].board[0],1)])
        g=self.game(hand=('take','choice'),enemy=('both',));self.play(g,'take',None);self.play(g,branch='both')
        self.assertEqual(self.armor(g),7);self.check(g)
    def test_dynamic_combination_expires_at_turn_boundary(self):
        self.script('grant',lambda c:[GrantChooseBoth(c.state.players[1].board[0],c.source_id,c.state.turn)])
        g=self.game(hand=('grant','choice','choice'),board=('body',));self.play(g,'grant',None);self.play(g,branch='both')
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g);self.assertEqual(self.armor(g),9);self.check(g)
    def test_dormant_combination_source_is_inactive(self):
        self.r.register_card(CardDefinition('sleep','sleep',CardType.MINION,health=4,choose_both=True,dormant_turns=2))
        g=self.game(board=('sleep',));self.play(g);self.assertEqual(self.armor(g),2);self.check(g)
    def test_current_copy_preserves_granted_combination(self):
        self.script('copy',lambda c:[GrantChooseBoth(c.state.players[1].board[0]),CopyMinion(c.state.players[1].board[0],1),Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('copy','choice'),board=('body',));self.play(g,'copy',None);self.play(g,branch='both')
        self.assertEqual(self.armor(g),7);self.check(g)
    def test_return_to_hand_clears_granted_combination(self):
        self.script('return',lambda c:[GrantChooseBoth(c.state.players[1].board[0]),ReturnToHand(c.state.players[1].board[0])])
        g=self.game(hand=('return','choice'),board=('body',));self.play(g,'return',None);self.play(g,'body',None);self.play(g)
        self.assertEqual(self.armor(g),2);self.check(g)
    def test_combined_branch_can_have_a_distinct_target_domain(self):
        self.card('combined-target',replace(self.spec,combined=ChooseBranch('both','both','damage',
            TargetSpec(kinds=(CardType.MINION,),relation='friendly'))))
        g=self.game(hand=('combined-target',),board=('both',));target=g.state.players[1].board[0]
        self.assertEqual([(a.branch_id,a.target_id) for a in g.legal_actions() if type(a) is PlayCard],[('both',target)])
        self.play(g,'combined-target','both',target);self.assertEqual(g.state.entities[target].health,1);self.check(g)
    def test_effect_branch_can_suspend_and_restore_without_reselecting(self):
        self.r.register_behavior('pause',lambda c:[self.pause(c),GainArmor(1,3)])
        self.card('pause',replace(self.spec,branches=(replace(self.spec.branches[0],behavior_id='pause'),self.spec.branches[1])))
        g=self.game(hand=('pause',));self.play(g,'pause');self.assertEqual(g.state.players[1].mana,8);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),3);self.check(g)
    def test_commit_reaction_pause_captures_branch_before_resolution(self):
        self.watch('pause',lambda c:[self.pause(c)])
        g=self.game(board=('pause',));self.play(g);self.check(g);self.assertEqual(self.armor(g),0)
        self.choose(g);self.assertEqual(self.armor(g),2);self.check(g)
    def test_branch_transform_uses_explicit_combined_form(self):
        for name,stats in [('aform',(2,4)),('bform',(4,2)),('bothform',(4,4))]:
            self.r.register_card(CardDefinition(name,name,CardType.MINION,attack=stats[0],health=stats[1]))
            self.r.register_behavior(name,lambda c,n=name:[Transform(c.source_id,n)])
        spec=ChooseOneSpec((ChooseBranch('a','a','aform'),ChooseBranch('b','b','bform')),ChooseBranch('both','both','bothform'))
        self.card('shape',spec,kind=CardType.MINION)
        g=self.game(hand=('shape',),board=('both',));i=self.play(g,'shape','both')
        self.assertEqual(g.state.entities[i].card_id,'bothform');self.assertEqual(g.state.play_history[0].card_id,'shape');self.check(g)
    def test_manual_power_uses_branch_before_payment_and_target(self):
        g=self.game(hand=());self.use(g,'damage',self.enemy(g).id)
        self.assertEqual((self.enemy(g).health,g.state.hero_power_history[0].branch_id),(5,'damage'));self.check(g)
    def test_additional_power_and_combined_policy_share_entry(self):
        self.script('add',lambda c:[AddHeroPower(1,'power')])
        g=self.game(hand=('add',),board=('both',));self.play(g,'add',None)
        self.use(g,'both');self.use(g,'both',power=g.state.players[1].additional_hero_power_ids[0])
        self.assertEqual(self.armor(g),14);self.check(g)
    def test_power_replaced_in_start_reaction_keeps_frozen_branch(self):
        self.watch('replace',lambda c:[ReplaceHeroPower(1,'power')],event='hero_power_started')
        g=self.game(hand=(),board=('replace',));old=g.state.players[1].hero_power_id;self.use(g)
        self.assertNotEqual(old,g.state.players[1].hero_power_id);self.assertEqual(self.armor(g),2);self.check(g)
    def test_automatic_explicit_branch_bypasses_payment_without_a_play(self):
        self.script('cast',lambda c:[CastSpell(1,'choice',c.source_id,branch_id='armor')])
        g=self.game(hand=('cast',),mana=0);self.play(g,'cast',None)
        self.assertEqual((self.armor(g),len(g.state.play_history)),(2,1))
        self.assertEqual(g.state.cast_history[-1].branch_id,'armor');self.check(g)
    def test_automatic_random_branch_is_deterministic_and_keeps_failed_branch(self):
        self.script('cast',lambda c:[CastSpell(1,'choice',c.source_id)])
        seen=set()
        for seed in range(8):
            g=self.game(hand=('cast',),enemy=(),seed=seed);self.play(g,'cast',None)
            record=g.state.cast_history[-1];seen.add(record.branch_id)
            self.assertEqual(record.failure,'no_target' if record.branch_id=='damage' else None);self.check(g)
        self.assertEqual(seen,{'armor','damage'})
    def test_automatic_combined_branch_selected_without_consuming_rng(self):
        self.script('cast',lambda c:[CastSpell(1,'choice',c.source_id)])
        g=self.game(hand=('cast',),board=('both',));rng=g.snapshot()['rng_state'];self.play(g,'cast',None)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.armor(g),7);self.check(g)
    def test_automatic_explicit_target_applies_to_the_selected_branch(self):
        self.script('cast',lambda c:[CastSpell(1,'choice',c.source_id,c.state.players[2].board[0],targeting='explicit',branch_id='damage')])
        g=self.game(hand=('cast',));self.play(g,'cast',None);self.assertEqual(self.enemy(g).health,5);self.check(g)
    def test_indirect_power_does_not_invent_manual_payment_or_use(self):
        self.script('trigger',lambda c:[TriggerHeroPower(1,c.source_id,branch_id='armor')])
        g=self.game(hand=('trigger',),mana=0);self.play(g,'trigger',None)
        p=g.state.hero_power_history[0];self.assertEqual((p.origin,p.branch_id,p.cost),('effect','armor',None));self.check(g)
    def test_automatic_payload_choices_player_policy_does_not_rechoose_branch(self):
        self.r.register_behavior('pause',lambda c:[self.pause(c),GainArmor(1,2)])
        self.card('pause',replace(self.spec,branches=(replace(self.spec.branches[0],behavior_id='pause'),self.spec.branches[1])))
        self.script('cast',lambda c:[CastSpell(1,'pause',c.source_id,choices='player',branch_id='armor')])
        g=self.game(hand=('cast',));self.play(g,'cast',None);self.check(g);self.choose(g)
        self.assertEqual(self.armor(g),2);self.check(g)
    def test_repeat_uses_same_branch_even_after_combination_source_is_created(self):
        self.r.register_behavior('gain',lambda c:[Summon(1,'both'),GainArmor(1,1)])
        self.card('gain',replace(self.spec,branches=(replace(self.spec.branches[0],behavior_id='gain'),self.spec.branches[1])))
        g=self.game(hand=('gain',),board=('repeat',));self.play(g,'gain')
        self.assertEqual(self.armor(g),2);self.assertEqual([c.branch_id for c in g.state.cast_history],['armor','armor']);self.check(g)
    def test_rewind_retries_original_branch_and_one_payment(self):
        self.card('rewind',self.spec,rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        g=self.game(hand=('rewind',));self.play(g,'rewind');self.check(g);self.choose(g,'retry')
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(2,8,1));self.check(g)
    def test_retained_outcomes_keep_one_branch_record_and_multiple_payloads(self):
        self.card('rewind',self.spec,rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        g=self.game(hand=('rewind',),board=('retainer',));self.play(g,'rewind')
        self.assertEqual((self.armor(g),len(g.state.cast_history)),(4,1));self.check(g)
    def test_branch_failure_rolls_back_original_action(self):
        self.r.register_behavior('bad',lambda c:[Summon(1,'unknown')])
        self.card('bad',replace(self.spec,branches=(replace(self.spec.branches[0],behavior_id='bad'),self.spec.branches[1])))
        g=self.game(hand=('bad',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),s)
    def test_terminal_branch_keeps_single_interrupted_play(self):
        self.r.register_behavior('lethal',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)])
        self.card('lethal',replace(self.spec,branches=(replace(self.spec.branches[0],behavior_id='lethal'),self.spec.branches[1])))
        g=self.game(hand=('lethal',));self.play(g,'lethal')
        self.assertTrue(g.state.play_history[0].interrupted);self.assertEqual(g.state.play_history[0].branch_id,'armor');self.check(g)
    def test_alternative_payment_remains_root_quote(self):
        self.script('health',lambda c:[ModifyCost(c.state.players[1].hand[-1],CostSpec(payment=PaymentType.HEALTH))])
        g=self.game(hand=('health','choice'),mana=0);self.play(g,'health',None);self.play(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28);self.assertEqual(self.armor(g),2);self.check(g)
    def test_host_action_wire_preserves_and_validates_branch(self):
        for a in (PlayCard(1,2,branch_id='a'),UseHeroPower(1,2,branch_id='both')):
            self.assertEqual(action_from_dict(action_to_dict(a)),a)
            for value in (True,0,[], ''):
                raw=action_to_dict(a);raw['branch_id']=value
                with self.assertRaises(ValueError):action_from_dict(raw)
    def test_player_actions_expose_public_labels_without_behavior_ids(self):
        g=self.game();port=g.for_player(1);listing=port.legal_actions()
        self.assertIsNone(listing['error']);item=listing['observation']['players'][0]['hand'][0]
        self.assertEqual(item['choose_one'][0],{'id':'armor','label':'Armor'})
        self.assertNotIn('behavior_id',json.dumps(listing));self.assertNotIn('choose_one',g.observe(2)['players'][0]['hand'][0])
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['branch']=='armor')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted']);self.check(g)
    def test_player_rejects_forged_or_omitted_branch_without_state_change(self):
        g=self.game();p=g.for_player(1);l=p.legal_actions();a=next(a for a in l['actions'] if a['type']=='play_card');s=g.snapshot()
        for value in (None,'both','bad',True):
            bad={**a,'branch':value};self.assertFalse(p.submit({'revision':l['revision'],'action':bad})['accepted'])
            self.assertEqual(g.snapshot(),s)
    def test_player_preflight_rejects_private_branch_predicate(self):
        self.r.register_target_rule('private',lambda c:True)
        self.card('private',replace(self.spec,branches=(self.spec.branches[0],replace(self.spec.branches[1],target_rule='private'))))
        g=self.game(hand=('private',));self.assertEqual(g.for_player(1).legal_actions()['error'],'unsupported_rule')
    def test_snapshot_rejects_unknown_missing_and_cross_record_branch(self):
        g=self.game();self.play(g)
        for group,value in [('play_history','missing'),('play_history',None),('cast_history','damage')]:
            s=g.snapshot();s['state'][group][0]['branch_id']=value;self.reject(s)
        s=g.snapshot();del s['state']['play_history'][0]['branch_id'];self.reject(s)
    def test_plain_card_and_power_reject_extraneous_branch(self):
        self.script('plain',lambda c:[]);g=self.game(hand=('plain',));s=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'plain','armor')
        self.assertEqual(g.snapshot(),s)
    def test_bad_branch_declarations_rejected(self):
        for make in (lambda:ChooseOneSpec(self.spec.branches,self.spec.branches[0]),
                     lambda:ChooseOneSpec((self.spec.branches[0],),self.spec.combined),
                     lambda:ChooseBranch('a','a','engine.choose_one'),
                     lambda:ChooseBranch('a','a','armor',requires_board_space=1)):
            with self.assertRaises(ValueError):make()
        with self.assertRaises(ValueError):self.card('bad',self.spec,on_play='armor')
        with self.assertRaises(ValueError):self.card('bad-target',self.spec,requires_target=True)

    def test_unsupported_composite_roots_fail_at_registration(self):
        cases = (
            ('magnetic', CardType.MINION, dict(keywords=(Keyword.MAGNETIC,))),
            ('shatter', CardType.SPELL, dict(keywords=(Keyword.SHATTER,), shatter=ShatterSpec('left', 'right'))),
            ('secret', CardType.SPELL, dict(keywords=(Keyword.SECRET,),
                secret=SecretSpec('secret', ('spell_cast',), 'always', 'armor'))),
            ('quest', CardType.SPELL, dict(keywords=(Keyword.QUEST,), quest=QuestSpec('quest',
                (QuestStageSpec('unsupported.quest', 1, ('spell_cast',), 'armor', 'armor'),)))),
            ('ongoing', CardType.SPELL, dict(ongoing_effect_id='future')),
            ('battlecry', CardType.MINION, dict(battlecry='armor')),
            ('combo', CardType.MINION, dict(keywords=(Keyword.COMBO,), combo='armor')),
        )
        for name, kind, declarations in cases:
            with self.subTest(root=name), self.assertRaisesRegex(ValueError, 'Unsupported Choose One composite root'):
                self.card('unsupported.' + name, self.spec, kind=kind, **declarations)

    def test_removed_choice_metadata_is_not_accepted(self):
        with self.assertRaises(TypeError):
            ChooseBranch('a', 'A', 'armor', cost={})
        with self.assertRaises(TypeError):
            ChooseOneSpec(self.spec.branches, self.spec.combined, installation_policy='install_then_branch')
        with self.assertRaises(TypeError):
            ShatterSpec('left', 'right', split_branch_policy='inherit')

    def test_prior_composite_snapshot_schema_requires_original_engine(self):
        snapshot = self.game().snapshot()
        self.assertEqual(snapshot['schema_version'], 266)
        snapshot['schema_version'] = 148
        with self.assertRaisesRegex(SnapshotError, 'schemas 1 through 265 need their original engines'):
            Game.from_snapshot(snapshot, self.r)

    def test_unregistered_branch_behavior_is_explicitly_rejected(self):
        self.card('missing',replace(self.spec,combined=replace(self.spec.combined,behavior_id='missing')))
        with self.assertRaises(ValueError):self.game(hand=('missing',))

    def test_countered_spell_keeps_selected_branch_without_payload(self):
        self.watch('counter',lambda c:[CounterSpell(dict(c.event.data)['window_id'])])
        g=self.game(board=('counter',));self.play(g)
        self.assertEqual(self.armor(g),0);self.assertTrue(g.state.play_history[0].countered)
        self.assertEqual(g.state.cast_history[0].branch_id,'armor');self.check(g)

    def test_target_redirect_uses_selected_branch_domain(self):
        self.watch('redirect',lambda c:[RedirectSpellTarget(dict(c.event.data)['window_id'],c.state.players[2].hero_id)],event='spell_targeted')
        g=self.game(board=('redirect',));target=self.enemy(g).id;self.play(g,branch='damage',target=target)
        self.assertEqual((self.enemy(g).health,g.state.cast_history[0].target_id),(5,target));self.check(g)

    def test_drawn_spell_uses_current_combination_without_hand_play(self):
        self.card('drawn',self.spec,cast_when_drawn=CastWhenDrawnSpec(),keywords=(Keyword.CASTS_WHEN_DRAWN,))
        self.script('draw',lambda c:[AddToDeck(1,'drawn',position=0),Draw(1)])
        g=self.game(hand=('draw',),board=('both',));self.play(g,'draw',None)
        record=next(c for c in g.state.cast_history if c.origin=='draw')
        self.assertEqual((record.branch_id,self.armor(g)),('both',7));self.assertEqual(len(g.state.play_history),1);self.check(g)

    def test_stored_spell_keeps_physical_identity_and_prescribed_branch(self):
        self.script('stored',lambda c:[CastStoredSpell(CardReference.capture(c.state.entities[c.state.players[1].hand[-1]]),
            1,c.source_id,branch_id='armor')])
        g=self.game(hand=('stored','choice'));physical=g.state.players[1].hand[-1];self.play(g,'stored',None)
        self.assertEqual((g.state.cast_history[-1].source_id,self.armor(g)),(physical,2));self.check(g)

    def test_history_recast_captures_new_combination_policy(self):
        self.script('recast',lambda c:[Summon(1,'both'),RecastSpell(1,1,c.source_id)])
        g=self.game(hand=('choice','recast'));self.play(g);self.play(g,'recast',None)
        self.assertEqual((g.state.cast_history[-1].origin,g.state.cast_history[-1].branch_id,self.armor(g)),('history','both',9));self.check(g)

    def test_invalid_automatic_branch_rolls_back_rng_and_source_creation(self):
        self.script('cast',lambda c:[CastSpell(1,'choice',c.source_id,branch_id='unknown')])
        g=self.game(hand=('cast',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'cast',None)
        self.assertEqual(g.snapshot(),s)

    def test_power_snapshot_rejects_missing_branch(self):
        g=self.game(hand=());self.use(g);s=g.snapshot();s['state']['hero_power_history'][0]['branch_id']=None;self.reject(s)

    def test_old_snapshot_schema_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=70
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)


class ChooseOneRepresentativeTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    def game(self,hand,board=(),enemy=('CS2_182',)):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=hand,board=board,deck=('CS2_182',)*8,
            mana=10,max_mana=10),PlayerSetup('HERO_08',board=enemy))),self.r)
    def play(self,g,branch,target=None):g.apply(PlayCard(1,g.state.players[1].hand[0],target,branch_id=branch))
    def check(self,g):self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())
    def test_frozen_stats_and_nourish_preplay_declaration(self):
        for cid,values in [('EX1_154',(2,0,0)),('EX1_178',(7,5,5)),('OG_044',(4,3,6))]:
            c=self.r.card(cid);self.assertEqual((c.cost,c.attack,c.health),values)
        self.assertIsNotNone(self.r.card('EX1_164').choose_one)
    def test_wrath_damage_and_draw_branch(self):
        g=self.game(('EX1_154',));target=g.state.players[2].board[0];self.play(g,'draw',target)
        self.assertEqual(g.state.entities[target].health,4);self.assertEqual(len(g.state.players[1].hand),1);self.check(g)
    def test_fandral_nourish_both_effects_after_one_payment(self):
        g=self.game(('EX1_164',),board=('OG_044',));self.play(g,'both')
        self.assertEqual((g.state.players[1].mana,len(g.state.players[1].hand)),(5,3));self.assertIsNone(g.state.pending_choice);self.check(g)
    def test_wrath_combined_has_two_damage_packets(self):
        g=self.game(('EX1_154',),board=('OG_044',));target=g.state.players[2].board[0];self.play(g,'both',target)
        self.assertEqual(g.state.entities[target].health,1)
        self.assertEqual([e.amount for e in g.events if e.kind=='damage_dealt'],[3,1]);self.check(g)
    def test_war_combines_stats_and_taunt(self):
        g=self.game(('EX1_178',),board=('OG_044',));self.play(g,'both');body=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((body.attack,body.health),(10,10));self.assertIn(Keyword.TAUNT,body.keywords);self.check(g)
    def test_real_player_scenario_and_recovery(self):
        from examples.choose_one import run
        g,s=run();self.assertEqual(len(g.history),5);self.assertEqual(len(g.state.play_history),3)


if __name__=='__main__':unittest.main()
