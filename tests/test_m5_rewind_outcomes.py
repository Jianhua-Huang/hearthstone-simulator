"""Cumulative outcomes, capture/lifecycle and distinct activation accounting."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CastSpell, CastWhenDrawnSpec, EndTurn, Game,
    GrantRewindRetention, Keyword, PlayCard, PlayerSetup, RecastSpell, RewindSpec,
    Scenario, SelectChoice, SnapshotError, SpellRepeatSpec, TriggerSpec, Zone, Ruleset, ResolutionLimitExceeded)
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, Draw, GainArmor, RequestChoice, ReturnToHand, ShuffleIntoDeck,
    Silence, Summon, Transform)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.model import DamageKind
from hs_sim.engine.pools import GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.secrets import SetSecret


class RewindOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('aura','aura',CardType.MINION,health=6,retain_rewind_outcomes=True))
        self.r.register_card(CardDefinition('body','body',CardType.MINION,attack=2,health=3))
    def card(self,fn=None,cid='spell',*,kind=CardType.SPELL,retries=1,**kw):
        self.r.register_behavior(cid,fn or (lambda c:[GainArmor(c.player_id,c.rewind_attempt+1)]))
        if kind==CardType.MINION:kw.setdefault('attack',2);kw.setdefault('health',4)
        extra=kw.pop('keywords',())
        self.r.register_card(CardDefinition(cid,cid,kind,cost=2,on_play=cid,
            keywords=(Keyword.REWIND,)+extra,rewind=RewindSpec(retries),**kw))
    def script(self,name,fn):
        self.r.register_behavior(name,fn);self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))
    def forms(self,fn=None):
        self.r.register_behavior('forms',fn or (lambda c:[GainArmor(1,1)]))
        for n in (2,1,0):
            self.r.register_card(CardDefinition(f'f{n}',f'f{n}',CardType.MINION,cost=2,attack=2,health=4,
                keywords=(Keyword.REWIND,) if n else (),rewind=RewindSpec(n,f'f{n-1}') if n else None,on_play='forms'))
    def game(self,hand=('spell',),*,board=('aura',),enemy=(),deck=(),context=GenerationContext('local-2026-09-23','experimental'),rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,max_mana=10,mana=10),
            PlayerSetup('HERO_01',board=enemy)),seed=53,generation_context=context),self.r,ruleset=rules)
    def play(self,g,cid='spell'):
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,source));return source
    def choose(self,g,option=None):
        choice=g.state.pending_choice
        g.apply(SelectChoice(choice.player_id,choice.id,(option or choice.options[0].id,)))
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snap)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as e:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(e.exception))
    def choice_spell(self):
        self.card(lambda c:[RequestChoice(c.player_id,(ChoiceOption('x','x',(GainArmor(1,c.rewind_attempt+1),)),),source_id=c.source_id)])

    def test_spell_retains_both_without_repaying_or_recasting(self):
        self.card();g=self.game();self.play(g)
        self.assertEqual((self.armor(g),g.state.players[1].mana),(3,8))
        self.assertEqual((len(g.state.play_history),len(g.state.cast_history)),(1,1))
        self.assertIsNone(g.state.pending_choice);self.assertIsNone(g.snapshot()['rewind_session'])
        self.assertFalse(any(e.kind=='timeline_rewound' for e in g.events));self.check(g)

    def test_minion_retains_payload_without_summoning_second_body(self):
        self.card(kind=CardType.MINION);g=self.game();source=self.play(g)
        self.assertEqual(g.state.players[1].board[-1],source);self.assertEqual(len(g.state.players[1].board),2)
        self.assertEqual(self.armor(g),3);self.assertFalse(g.state.cast_history);self.check(g)

    def test_multiple_rewinds_keep_each_budgeted_outcome(self):
        self.card(retries=3);g=self.game();self.play(g)
        self.assertEqual(self.armor(g),10);self.assertEqual(g.state.rewind_outcomes[0].completed,4);self.check(g)

    def test_two_retention_sources_do_not_stack(self):
        self.card();g=self.game(board=('aura','aura'));self.play(g)
        self.assertEqual(self.armor(g),3);self.assertEqual(len(g.state.rewind_outcomes[0].contributors),2);self.check(g)

    def test_opponent_aura_does_not_retain_own_outcomes(self):
        self.card();g=self.game(board=(),enemy=('aura',));self.play(g)
        self.assertEqual(g.state.pending_choice.purpose.value,'rewind');self.assertFalse(g.state.rewind_outcomes);self.check(g)

    def test_silenced_aura_does_not_retain_future_play(self):
        self.card();self.script('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(('silence','spell'));self.play(g,'silence');self.play(g)
        self.assertEqual(g.state.pending_choice.purpose.value,'rewind');self.check(g)

    def test_dormant_aura_does_not_retain_future_play(self):
        self.card();self.script('sleep',lambda c:[MakeDormant(c.state.players[1].board[0],2)])
        g=self.game(('sleep','spell'));self.play(g,'sleep');self.play(g)
        self.assertEqual(g.state.pending_choice.purpose.value,'rewind');self.check(g)

    def test_dead_aura_during_first_outcome_keeps_captured_quota(self):
        self.card(lambda c:[Destroy(c.state.players[1].board[0]),GainArmor(1,1)] if not c.rewind_attempt else [GainArmor(1,2)])
        g=self.game();self.play(g);self.assertEqual(self.armor(g),3);self.assertFalse(g.state.players[1].board);self.check(g)

    def test_silenced_aura_during_first_outcome_keeps_captured_quota(self):
        self.card(lambda c:[Silence(c.state.players[1].board[0]),GainArmor(1,1)])
        g=self.game();self.play(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_control_changed_aura_during_payload_keeps_original_player(self):
        self.card(lambda c:[ChangeControl(c.state.players[1].board[0],2),GainArmor(1,1)] if not c.rewind_attempt else [GainArmor(1,1)])
        g=self.game();self.play(g);self.assertEqual((self.armor(g),self.armor(g,2)),(2,0));self.check(g)

    def test_bounced_aura_during_payload_keeps_captured_quota(self):
        self.card(lambda c:[ReturnToHand(c.state.players[1].board[0]),GainArmor(1,1)] if not c.rewind_attempt else [GainArmor(1,1)])
        g=self.game();self.play(g);self.assertEqual(len(g.state.players[1].hand),1);self.assertEqual(self.armor(g),2);self.check(g)

    def test_new_aura_in_original_payload_does_not_retroactively_capture(self):
        self.card(lambda c:[Summon(1,'aura'),GainArmor(1,1)])
        g=self.game(board=());self.play(g)
        self.assertEqual(g.state.pending_choice.purpose.value,'rewind');self.assertEqual(self.armor(g),1);self.check(g)

    def test_manual_capture_precedes_commit_reactions(self):
        self.r.register_behavior('kill_aura',lambda c:[Destroy(c.source_id)] if c.event.source_id!=c.source_id else [])
        self.r.register_card(CardDefinition('fragile','fragile',CardType.MINION,health=4,retain_rewind_outcomes=True,
            triggers=(TriggerSpec('card_committed','kill_aura'),)))
        self.card();g=self.game(board=('fragile',));self.play(g)
        self.assertEqual(self.armor(g),3);self.assertFalse(g.state.players[1].board);self.check(g)

    def test_dynamic_retention_grant(self):
        self.card();self.script('grant',lambda c:[GrantRewindRetention(c.state.players[1].board[0],c.source_id)])
        g=self.game(('grant','spell'),board=('body',));self.play(g,'grant');self.play(g)
        self.assertEqual(self.armor(g),3);self.check(g)

    def test_temporary_grant_expires(self):
        self.card();self.script('grant',lambda c:[GrantRewindRetention(c.state.players[1].board[0],c.source_id,c.state.turn)])
        g=self.game(('grant','spell'),board=('body',),deck=('body',));self.play(g,'grant')
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g)
        self.assertEqual(g.state.pending_choice.purpose.value,'rewind');self.check(g)

    def test_copied_retention_source_keeps_ability(self):
        self.card();self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1),Destroy(c.state.players[1].board[0])])
        g=self.game(('copy','spell'));self.play(g,'copy');self.play(g);self.assertEqual(self.armor(g),3);self.check(g)

    def test_transform_removes_retention_for_future_play(self):
        self.card();self.script('morph',lambda c:[Transform(c.state.players[1].board[0],'body')])
        g=self.game(('morph','spell'));self.play(g,'morph');self.play(g)
        self.assertEqual(g.state.pending_choice.purpose.value,'rewind');self.check(g)

    def test_both_portal_cards_remain_and_keep_discount(self):
        g=self.game(('TIME_000',));self.play(g,'TIME_000');p=g.state.players[1]
        self.assertEqual((len(p.hand),p.mana),(2,8))
        for i in p.hand:
            card=g.state.entities[i];self.assertEqual(card.cost,max(0,self.r.card(card.card_id).cost-3))
        self.assertNotEqual(*p.hand);self.check(g)

    def test_sands_has_two_discoveries_with_second_current_class(self):
        g=self.game(('TIME_EVENT_999',));self.play(g,'TIME_EVENT_999');self.check(g)
        self.choose(g);first=g.state.players[1].hand[0];self.check(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{'CS2_029','CS2_024'})
        self.choose(g);self.assertIn(first,g.state.players[1].hand)
        self.assertEqual((len(g.state.players[1].hand),g.state.players[1].mana),(2,9))
        self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_morchie_real_battlecry_uses_explicit_class_rewind_pool(self):
        g=self.game(('END_036',),board=());source=self.play(g,'END_036')
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{'TIME_000'})
        self.choose(g);self.play(g,'TIME_000')
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,6))
        self.assertEqual((len(g.state.players[1].hand),g.state.players[1].mana),(2,4));self.check(g)

    def test_morchie_missing_pool_context_rolls_back(self):
        g=self.game(('END_036',),board=(),context=None);before=g.snapshot()
        with self.assertRaises(ValueError):self.play(g,'END_036')
        self.assertEqual(g.snapshot(),before)

    def test_automatic_cast_retains_without_manual_session(self):
        self.card();self.script('auto',lambda c:[CastSpell(1,'spell',c.source_id)])
        g=self.game(('auto',));self.play(g,'auto')
        self.assertEqual(self.armor(g),3);self.assertEqual(len(g.state.play_history),1)
        self.assertEqual([c.origin for c in g.state.cast_history],['hand','effect']);self.check(g)

    def test_automatic_choices_follow_cast_policy_for_both_outcomes(self):
        self.choice_spell();self.script('auto',lambda c:[CastSpell(1,'spell',c.source_id)])
        g=self.game(('auto',));self.play(g,'auto');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(self.armor(g),3);self.assertEqual(sum(e.kind=='spell_choice_automatic' for e in g.events),2);self.check(g)

    def test_automatic_player_choices_suspend_both_outcomes(self):
        self.choice_spell();self.script('auto',lambda c:[CastSpell(1,'spell',c.source_id,choices='player')])
        g=self.game(('auto',));self.play(g,'auto');self.check(g);self.choose(g);self.check(g);self.choose(g);self.check(g)
        self.assertEqual(self.armor(g),3)

    def test_no_aura_automatic_cast_has_one_payload_no_rewind_choice(self):
        self.card();self.script('auto',lambda c:[CastSpell(1,'spell',c.source_id)])
        g=self.game(('auto',),board=());self.play(g,'auto')
        self.assertEqual(self.armor(g),1);self.assertFalse(g.state.rewind_outcomes);self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_historical_recast_has_own_retained_activation(self):
        self.card();self.script('again',lambda c:[RecastSpell(1,1,c.source_id)])
        g=self.game(('spell','again'));self.play(g);self.play(g,'again')
        self.assertEqual(self.armor(g),6);self.assertEqual(len(g.state.rewind_outcomes),2)
        self.assertEqual(g.state.cast_history[-1].origin,'history');self.check(g)

    def test_spell_repeat_and_retention_keep_distinct_accounting(self):
        self.card();self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=4,
            spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        g=self.game(board=('aura','repeat'));self.play(g)
        self.assertEqual(self.armor(g),6);self.assertEqual(len(g.state.cast_history),2)
        self.assertEqual((len(g.state.play_history),g.state.players[1].mana),(1,8))
        self.assertEqual(len(g.state.rewind_outcomes),2);self.check(g)

    def test_second_outcome_sees_first_death_and_cannot_destroy_same_minion(self):
        self.card(lambda c:[Destroy(c.state.players[2].board[0])] if c.state.players[2].board else [])
        g=self.game(enemy=('body','body'));self.play(g)
        self.assertFalse(g.state.players[2].board);self.assertEqual(len(g.state.death_history),2);self.check(g)

    def test_second_outcome_sees_deathrattle_summon(self):
        self.r.register_behavior('spawn',lambda c:[Summon(2,'body')])
        self.r.register_card(CardDefinition('egg','egg',CardType.MINION,health=2,deathrattle='spawn'))
        self.card(lambda c:[Destroy(c.state.players[2].board[0])] if c.state.players[2].board else [])
        g=self.game(enemy=('egg',));self.play(g)
        self.assertEqual([d.card_id for d in g.state.death_history],['egg','body']);self.assertFalse(g.state.players[2].board);self.check(g)

    def test_full_board_capacity_is_applied_between_outcomes(self):
        self.card(lambda c:[Summon(1,'body')]);g=self.game(board=('aura',)+('body',)*5);self.play(g)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.state.rewind_outcomes[0].completed,2);self.check(g)

    def test_full_hand_second_outcome_burns_instead_of_overwriting(self):
        self.card(lambda c:[AddToHand(1,'body')]);g=self.game(('spell',)+('body',)*9);self.play(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(sum(e.kind=='card_burned' for e in g.events),1);self.check(g)

    def test_lethal_interrupts_remaining_outcome_under_current_terminal_policy(self):
        self.card(lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id,DamageKind.SPELL)])
        g=self.game();self.play(g)
        self.assertEqual(g.state.status,'finished');self.assertTrue(g.state.rewind_outcomes[0].interrupted);self.check(g)

    def test_countered_spell_has_no_retained_payload(self):
        self.script('setup',lambda c:[SetSecret(2,'EX1_287')])
        g=self.game(('setup','TIME_000'));self.play(g,'setup');self.play(g,'TIME_000')
        self.assertFalse(g.state.rewind_outcomes);self.assertFalse(g.state.players[1].hand)
        self.assertTrue(g.state.play_history[-1].countered);self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_error_in_second_outcome_rolls_back_whole_action(self):
        def fn(c):
            if c.rewind_attempt:raise ValueError('second outcome failure')
            return [GainArmor(1,1)]
        self.card(fn);g=self.game();before=g.snapshot()
        with self.assertRaises(ValueError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_error_after_choice_rolls_back_to_current_choice(self):
        def fn(c):
            if c.rewind_attempt:raise ValueError('second outcome failure')
            return [RequestChoice(1,(ChoiceOption('x','x',(GainArmor(1,1),)),),source_id=c.source_id)]
        self.card(fn);g=self.game();self.play(g);before=g.snapshot()
        with self.assertRaises(ValueError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_form_chain_advances_without_duplicate_play(self):
        self.forms();g=self.game(('f2',));source=self.play(g,'f2')
        self.assertEqual(g.state.entities[source].card_id,'f0');self.assertNotIn(Keyword.REWIND,g.state.entities[source].keywords)
        self.assertEqual(g.state.play_history[0].card_id,'f2');self.assertEqual(self.armor(g),3);self.check(g)

    def test_bounced_source_consumes_retained_faces_in_hand(self):
        self.forms(lambda c:[ReturnToHand(c.source_id)]);g=self.game(('f2',));source=self.play(g,'f2')
        self.assertIn(source,g.state.players[1].hand);self.assertEqual(g.state.entities[source].card_id,'f0');self.check(g)

    def test_shuffled_source_face_does_not_create_deck_tracking_handles(self):
        self.forms(lambda c:[ShuffleIntoDeck(c.source_id)] if not c.rewind_attempt else [])
        g=self.game(('f2',));source=self.play(g,'f2')
        self.assertEqual(g.state.entities[source].card_id,'f0')
        for k in g.snapshot()['information']['players'].values():self.assertNotIn(str(source),k['refs'])
        self.check(g)

    def test_transformed_source_is_not_replaced_by_old_retry_face(self):
        self.forms(lambda c:[Transform(c.source_id,'body')] if not c.rewind_attempt else [GainArmor(1,1)])
        g=self.game(('f2',));source=self.play(g,'f2')
        self.assertEqual(g.state.entities[source].card_id,'body');self.assertEqual(self.armor(g),2);self.check(g)

    def test_nested_retained_casts_restore_matching_control_stack(self):
        self.choice_spell();self.card(lambda c:[CastSpell(1,'spell',c.source_id,choices='player')],cid='outer')
        g=self.game(('outer',));self.play(g,'outer')
        for _ in range(4):self.check(g);self.choose(g)
        self.assertEqual(self.armor(g),6);self.assertEqual(len(g.state.rewind_outcomes),3);self.check(g)

    def test_player_port_rejects_first_discovery_handle_at_second(self):
        g=self.game(('TIME_EVENT_999',));self.play(g,'TIME_EVENT_999');port=g.for_player(1)
        first=port.legal_actions();action=first['actions'][0]
        self.assertTrue(port.submit({'revision':first['revision'],'action':action})['accepted'])
        second=port.legal_actions();before=g.snapshot()
        self.assertFalse(port.submit({'revision':second['revision'],'action':action})['accepted']);self.assertEqual(g.snapshot(),before)
        self.assertTrue(port.submit({'revision':second['revision'],'action':second['actions'][0]})['accepted']);self.check(g)

    def test_history_is_not_exposed_in_player_observation(self):
        self.choice_spell();g=self.game();self.play(g)
        for p in (1,2):
            text=json.dumps(g.observe(p));self.assertNotIn('rewind_outcomes',text);self.assertNotIn('contributors',text)
        self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1});self.check(g)

    def test_drawn_cast_keeps_both_but_replacement_draw_occurs_once(self):
        self.card(cast_when_drawn=CastWhenDrawnSpec(),keywords=(Keyword.CASTS_WHEN_DRAWN,))
        self.script('draw',lambda c:[Draw(1,source_id=c.source_id)])
        g=self.game(('draw',),deck=('spell','body'));self.play(g,'draw')
        self.assertEqual(self.armor(g),3);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertEqual([d.outcome for d in g.state.draw_history],['cast','hand'])
        self.assertEqual([c.origin for c in g.state.cast_history],['hand','draw']);self.check(g)

    def test_minion_dying_during_payload_does_not_duplicate_body(self):
        self.card(lambda c:[Destroy(c.source_id),GainArmor(1,1)],kind=CardType.MINION)
        g=self.game();source=self.play(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(len(g.state.death_history),1)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.check(g)

    def test_error_budget_rolls_back_all_retained_outputs(self):
        self.card(lambda c:[GainArmor(1,1)]*10,retries=3);g=self.game(rules=Ruleset(max_resolution_steps=35));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_clones_can_complete_separate_choice_branches(self):
        self.choice_spell();g=self.game();self.play(g);fork=g.clone();self.choose(g)
        self.assertEqual(self.armor(fork),0);self.choose(fork)
        self.assertEqual(g.snapshot(),fork.snapshot());self.choose(g);self.choose(fork)
        self.assertEqual(g.snapshot(),fork.snapshot());self.check(g)

    def test_missing_outcome_completion_marker_is_rejected(self):
        self.choice_spell();g=self.game();self.play(g);s=g.snapshot()
        q=s['resolution_frame']['fields']['continuation']['tuple']
        q[:]=[w for w in q if not w.get('type','').endswith('.FinishRewindOutcome')]
        self.reject(s)

    def test_outcomes_cannot_be_moved_after_cast_completion(self):
        self.choice_spell();g=self.game();self.play(g);s=g.snapshot()
        q=s['resolution_frame']['fields']['continuation']['tuple']
        i=next(i for i,w in enumerate(q) if w.get('type','').endswith('.FinishRewindOutcomes'))
        q.append(q.pop(i));self.reject(s)

    def test_corrupt_cast_link_is_rejected(self):
        self.choice_spell();g=self.game();self.play(g);s=g.snapshot()
        s['state']['rewind_outcomes'][0]['cast_id']=None;self.reject(s)

    def test_unknown_retention_contributor_is_rejected(self):
        self.choice_spell();g=self.game();self.play(g);s=g.snapshot()
        s['state']['rewind_outcomes'][0]['contributors']=[99999];self.reject(s)

    def test_corrupt_outcome_total_is_rejected(self):
        self.choice_spell();g=self.game();self.play(g);s=g.snapshot();s['state']['rewind_outcomes'][0]['total']=3;self.reject(s)

    def test_corrupt_outcome_source_is_rejected(self):
        self.choice_spell();g=self.game();self.play(g);s=g.snapshot();s['state']['rewind_outcomes'][0]['source_id']=1;self.reject(s)

    def test_missing_outcome_history_field_is_rejected(self):
        self.choice_spell();g=self.game();self.play(g);s=g.snapshot();del s['state']['rewind_outcomes'];self.reject(s)

    def test_retention_definition_requires_boolean_minion(self):
        for kind,value in ((CardType.MINION,1),(CardType.SPELL,True)):
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                self.r.register_card(CardDefinition('bad','bad',kind,health=3,retain_rewind_outcomes=value))

    def test_grant_to_dead_source_is_skipped(self):
        self.card();self.script('grant',lambda c:[Destroy(c.state.players[1].board[0]),GrantRewindRetention(c.state.players[1].board[0])])
        g=self.game(('grant','spell'),board=('body',));self.play(g,'grant');self.play(g)
        self.assertEqual(g.state.pending_choice.purpose.value,'rewind');self.check(g)
