"""Installed Hero classified and generic finite carriers on the public pipelines."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition,CardType,EndTurn,EndTurnSpec,Game,Keyword,
    LimitedTriggerSpec,PlayCard,PlayerSetup,Registry,Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Damage,GainArmor,GrantTrigger,RandomDamage,
    ReplaceHero,RequestChoice,Summon)
from hs_sim.engine.end_turns import TriggerEndTurnEffects
from hs_sim.engine.end_turn_producers import TriggerRandomEndTurnEffects,end_turn_carriers
from hs_sim.engine.generated_heroes import InstallGeneratedHeroCard
from hs_sim.engine.limited_triggers import GrantLimitedTrigger
from hs_sim.engine.model import (EndTurnActivationProfile,EndTurnCandidateProfile,
    EndTurnProducerRequest,EndTurnRepeatSpec,EndTurnRequest,EndTurnSelector)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.generated_battlecry_repeats import PROFILE as BC_PROFILE
from hs_sim.engine.generated_combo_repeats import PROFILE as FAMILY_PROFILE
from hs_sim.engine.generated_activation_receipts import RETAINED_PROFILE


def request(seats=(1,),mode='owner',ids=(),profile='end_turn.effect',kinds=('hero',)):
    return EndTurnRequest(EndTurnSelector(mode,seats,kinds,ids),profile)


def registry(mode='normal',scope='controller'):
    r=Registry('hero-classified-'+mode+'-'+scope+'-v1')
    r.register_behavior('noop',lambda c:())
    r.register_trigger_condition('owner',lambda c:c.event.player_id==c.player_id)
    r.register_trigger_condition('eligible',lambda c:False if mode=='condition_false' else 1 if mode=='condition_type' else True)
    spec=EndTurnSpec(scope,'eligible')
    def body(c,amount):
        if mode=='wait':return (RequestChoice(c.player_id,(ChoiceOption('go','Go',(GainArmor(c.player_id,amount),)),),c.source_id),)
        if mode=='fail':return (RandomDamage(tuple(c.state.players[2].board),1,c.source_id),Summon(c.player_id,'missing.hero.trigger'))
        if mode=='lethal':return (Damage(c.state.players[2].hero_id,100,c.source_id),)
        if mode=='swap_body':return (ReplaceHero(c.player_id,'hero'),GainArmor(c.player_id,amount))
        if mode=='nested':return (GainArmor(c.player_id,amount),TriggerEndTurnEffects(c.player_id,request((c.player_id,)),c.source_id))
        return (GainArmor(c.player_id,amount),)
    r.register_behavior('end',lambda c:body(c,1))
    r.register_behavior('finite_end',lambda c:body(c,2))
    r.register_behavior('event',lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior('replace_first',lambda c:(ReplaceHero(c.player_id,'hero'),))
    r.register_behavior('replace_wait',lambda c:(RequestChoice(c.player_id,
        (ChoiceOption('go','Replace',(ReplaceHero(c.player_id,'hero'),)),),c.source_id),))
    normal=(TriggerSpec('turn_ended','end',spec),)
    finite=(LimitedTriggerSpec('turn_ended','finite_end',uses=2,end_turn=spec),)
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('marked','Marked',CardType.HERO,health=30,triggers=normal))
    r.register_card(CardDefinition('finite','Finite',CardType.HERO,health=30,limited_triggers=finite,
        triggers=(TriggerSpec('turn_started','phase'),) if mode=='phase' else ()))
    r.register_card(CardDefinition('mixed','Mixed',CardType.HERO,health=30,triggers=normal,limited_triggers=finite))
    r.register_card(CardDefinition('eventhero','Event hero',CardType.HERO,health=30,
        limited_triggers=(LimitedTriggerSpec('card_played','event','owner',uses=2),)))
    first='replace_wait' if mode=='pre_wait' else 'replace_first'
    r.register_card(CardDefinition('replacer','Replacer',CardType.HERO,health=30,
        triggers=(TriggerSpec('turn_ended',first),*normal)))
    r.register_card(CardDefinition('power','Power',CardType.HERO_POWER,on_use='noop'))
    r.register_card(CardDefinition('hero_card','Hero card',CardType.HERO,health=30,cost=1,
        hero_card=True,initial_hero_power='power',triggers=normal,limited_triggers=finite))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,health=10))
    for name,repeat_scope in (('all_twice','all'),('minion_twice','minion')):
        r.register_card(CardDefinition(name,name,CardType.MINION,health=10,
            end_turn_repeats=(EndTurnRepeatSpec(2,repeat_scope),)))
    r.register_card(CardDefinition('watch','Watch',CardType.MINION,health=10,
        triggers=(TriggerSpec('limited_trigger_used','replace_first'),) if mode=='used_replace' else ()))
    r.register_end_turn_profile(EndTurnActivationProfile('phase.hero',kind='phase',cause_events=('turn_started',)))
    r.register_behavior('phase',lambda c:(TriggerEndTurnEffects(c.player_id,
        request((c.player_id,),profile='phase.hero'),c.source_id,c.event),) if c.event.player_id==c.player_id else ())
    r.register_end_turn_candidate_profile(EndTurnCandidateProfile('any.hero',presence='any'))
    r.register_end_turn_candidate_profile(EndTurnCandidateProfile('printed.hero',basis='printed',consumed='include'))
    r.register_end_turn_candidate_profile(EndTurnCandidateProfile('current.hero',basis='current',consumed='include'))
    def invoke(c):
        ids=()
        if mode=='selected':ids=(c.state.players[c.player_id].hero_id,)
        elif mode=='select_retired':ids=(next(i for i in c.state.players[c.player_id].graveyard if c.state.entities[i].kind==CardType.HERO),)
        return (TriggerEndTurnEffects(c.player_id,request(mode='selected' if ids else 'owner',ids=ids),c.source_id),)
    r.register_behavior('invoke',invoke)
    r.register_behavior('random',lambda c:(TriggerRandomEndTurnEffects(c.player_id,
        EndTurnProducerRequest(EndTurnSelector('owner',(1,2),('hero',))),c.source_id),))
    r.register_behavior('grant_end',lambda c:(GrantTrigger(c.state.players[c.player_id].hero_id,
        'turn_ended','end',c.source_id,end_turn=spec),))
    r.register_behavior('grant_finite',lambda c:(GrantLimitedTrigger(c.state.players[c.player_id].hero_id,finite[0],c.source_id),))
    r.register_behavior('grant_event',lambda c:(GrantLimitedTrigger(c.state.players[c.player_id].hero_id,
        LimitedTriggerSpec('card_played','event','owner',uses=2),c.source_id),))
    r.register_behavior('grant_expiring',lambda c:(GrantLimitedTrigger(c.state.players[c.player_id].hero_id,
        finite[0],c.source_id,expires_turn=c.state.turn),))
    r.register_behavior('grant_bad',lambda c:(GrantLimitedTrigger(c.state.players[c.player_id].hero_id,
        LimitedTriggerSpec.spellburst('event'),c.source_id),))
    r.register_behavior('grant_dead',lambda c:(GrantLimitedTrigger(next(i for i in c.state.players[c.player_id].graveyard
        if c.state.entities[i].kind==CardType.HERO),finite[0],c.source_id),))
    r.register_behavior('replace',lambda c:(ReplaceHero(c.player_id,'hero'),))
    r.register_behavior('install',lambda c:(InstallGeneratedHeroCard(c.player_id,'hero_card',c.source_id),))
    physical_profile={'replay_bc':BC_PROFILE,'replay_family':FAMILY_PROFILE,'replay_retained':RETAINED_PROFILE}.get(mode,PROFILE)
    r.register_behavior('rerun',lambda c:(ReplayWholeCards(c.player_id,c.source_id,
        WholeCardHistoryQuery(c.player_id,len(c.state.play_history)+1,kinds=(CardType.HERO,)),
        physical_profile=physical_profile,choices='player'),))
    for name in ('pulse','invoke','random','grant_end','grant_finite','grant_event','grant_expiring','grant_bad','grant_dead','replace','install','rerun'):
        r.register_card(CardDefinition(name,name,CardType.SPELL,cost=1,on_play='noop' if name=='pulse' else name))
    return r


class HeroClassifiedTriggerTests(unittest.TestCase):
    def game(self,hero='mixed',mode='normal',scope='controller',hand=(),board=(),enemy='hero'):
        g=Game.from_scenario(Scenario((PlayerSetup(hero,hand=(('grant_finite',) if hero=='replacer' else ())+hand,board=board,deck=('plain',)*8,mana=10,max_mana=10),
            PlayerSetup(enemy,board=('plain',),deck=('plain',)*8,mana=10,max_mana=10)),seed=73),registry(mode,scope))
        if hero=='replacer':self.play(g,'grant_finite')
        return g

    def play(self,g,name):
        seat=g.state.active_player;i=next(i for i in g.state.players[seat].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(seat,i))

    def end(self,g):return g.apply(EndTurn(g.state.active_player))
    def armor(self,g,seat=1):return g.state.entities[g.state.players[seat].hero_id].armor
    def finite(self,g):return [a for a in g.state.entities[g.state.players[1].hero_id].abilities if a.kind=='limited_trigger']
    def choose(self,g):
        choice=g.state.pending_choice;return g.apply(SelectChoice(choice.player_id,choice.id,('go',)))
    def portable(self,g,mode='normal',scope='controller'):
        value=json.loads(json.dumps(g.snapshot()))
        copies=(Game.from_snapshot(value,registry(mode,scope)),g.clone(),replay(build_replay(g),registry(mode,scope)))
        for copy in copies:
            self.assertEqual(copy.snapshot(),value)
            for seat in (1,2):self.assertEqual(copy.observe(seat),g.observe(seat))
        return copies
    def reject(self,g,mutate,mode='normal'):
        value=deepcopy(g.snapshot());mutate(value)
        value['state_hash']=canonical_hash({k:v for k,v in value.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(value,registry(mode))
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_natural_mixed_hero_has_distinct_subjects_and_once_owner_clock(self):
        g=self.game();self.end(g)
        self.assertEqual(self.armor(g),3);self.assertEqual(len(g.state.end_turn_history),2)
        self.assertEqual(len({row.capture.subject.ability.id for row in g.state.end_turn_history}),2)
        self.assertEqual(sum(e.kind=='turn_ended' for e in g.events),1)
        self.assertEqual(g.state.turn,2);self.assertEqual(self.finite(g)[0].uses_remaining,1)
        self.portable(g)

    def test_active_hero_selector_runs_bodies_without_advancing_turn_clocks(self):
        g=self.game(hand=('invoke',));mana=g.state.players[1].mana;self.play(g,'invoke')
        self.assertEqual(self.armor(g),3);self.assertEqual(g.state.turn,1)
        self.assertEqual(g.state.players[1].mana,mana-1)
        self.assertFalse(any(e.kind=='turn_ended' for e in g.events));self.portable(g)

    def test_phase_hero_uses_real_cause_and_own_finite_guard_without_extra_clocks(self):
        g=self.game('finite','phase','opponent');self.end(g);self.end(g)
        self.assertEqual(self.armor(g),4);self.assertTrue(self.finite(g)[0].consumed)
        self.assertEqual([b.activation.kind for b in g.state.end_turn_batches],['natural','natural','phase'])
        self.assertEqual(g.state.turn,3);self.assertEqual(sum(e.kind=='turn_ended' for e in g.events),2)
        self.portable(g,'phase','opponent')

    def test_finite_hero_consumes_once_for_all_repeated_executions(self):
        g=self.game('finite',hand=('invoke',),board=('all_twice',));self.play(g,'invoke')
        self.assertEqual(self.armor(g),4);self.assertEqual(self.finite(g)[0].uses_remaining,1)
        rows=g.state.end_turn_history;self.assertEqual([row.capture.repeat_index for row in rows],[0,1])
        self.assertEqual(rows[0].guard_event,rows[1].guard_event);self.portable(g)

    def test_minion_only_repeat_source_does_not_repeat_hero_subject(self):
        g=self.game('finite',hand=('invoke',),board=('minion_twice',));self.play(g,'invoke')
        self.assertEqual(self.armor(g),2);self.assertEqual(len(g.state.end_turn_history),1);self.portable(g)

    def test_printed_finite_hero_exhausts_across_real_owner_boundaries(self):
        g=self.game('finite')
        for _ in range(5):self.end(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.end_turn_history),2)
        self.assertTrue(self.finite(g)[0].consumed);self.portable(g)

    def test_generic_finite_hero_is_not_spellburst_and_respects_registered_condition(self):
        g=self.game('eventhero',hand=('pulse','pulse'));self.play(g,'pulse');self.play(g,'pulse')
        self.assertEqual(self.armor(g),2);self.assertTrue(self.finite(g)[0].consumed)
        self.assertFalse(g.state.end_turn_history);self.portable(g)

    def test_dynamic_finite_hero_grant_has_own_instance_and_consumes_on_completed_grant(self):
        g=self.game('hero',hand=('grant_event','pulse'));self.play(g,'grant_event')
        self.assertEqual(self.finite(g)[0].uses_remaining,1);self.assertEqual(self.armor(g),1)
        self.play(g,'pulse');self.assertTrue(self.finite(g)[0].consumed);self.portable(g)

    def test_dynamic_classified_hero_grants_remain_independent(self):
        g=self.game('hero',hand=('grant_end','grant_finite','grant_finite','invoke'))
        for name in ('grant_end','grant_finite','grant_finite','invoke'):self.play(g,name)
        self.assertEqual(self.armor(g),5);self.assertEqual(len(g.state.end_turn_history),3)
        self.assertEqual([a.uses_remaining for a in self.finite(g)],[1,1]);self.portable(g)

    def test_natural_scope_controller_opponent_either_uses_hero_owner(self):
        for scope,count in (('controller',1),('opponent',1),('either',2)):
            with self.subTest(scope=scope):
                g=self.game('marked',scope=scope);self.end(g);self.end(g)
                self.assertEqual(self.armor(g),count);self.portable(g,scope=scope)

    def test_random_producer_counts_each_hero_once_despite_multiple_bodies(self):
        g=self.game(hand=('random',),enemy='marked')
        pool=end_turn_carriers(g.state,g.registry,EndTurnSelector('owner',(1,2),('hero',)))
        self.assertEqual(len(pool),2);self.assertEqual([r.kind for r in pool],['hero','hero'])
        self.play(g,'random');selection=g.state.end_turn_batches[-1].activation.selection
        self.assertEqual(selection.candidates,pool);self.assertIn(selection.selected,pool);self.portable(g)

    def test_selected_hero_accepts_only_its_actual_physical_carrier(self):
        g=self.game(mode='selected',hand=('invoke',));self.play(g,'invoke')
        self.assertEqual(self.armor(g),3)
        selector=g.state.end_turn_batches[-1].activation.request.selector
        self.assertEqual(selector.entity_ids,(g.state.players[1].hero_id,));self.portable(g,'selected')

    def test_selected_retired_hero_is_empty_and_does_not_rebind_to_replacement(self):
        g=self.game('marked','select_retired',hand=('replace','invoke'));self.play(g,'replace');self.play(g,'invoke')
        self.assertEqual(self.armor(g),0);self.assertFalse(g.state.end_turn_history)
        self.assertFalse(g.state.end_turn_batches[-1].subjects);self.portable(g,'select_retired')

    def test_candidate_query_presence_never_runs_hero_body_conditions(self):
        g=self.game(mode='condition_type');rows=end_turn_carriers(g.state,g.registry,EndTurnSelector('owner',(1,),('hero',)))
        self.assertEqual(len(rows),1);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'must return bool'):self.end(g)
        self.assertEqual(g.snapshot(),before)

    def test_false_conditions_do_not_consume_hero_finite_instance(self):
        g=self.game(mode='condition_false');self.end(g)
        self.assertEqual(self.armor(g),0);self.assertEqual(self.finite(g)[0].uses_remaining,2)
        self.assertFalse(g.state.end_turn_history);self.portable(g,'condition_false')

    def test_printed_current_active_candidate_policy_keeps_consumed_hero_bodies_distinct(self):
        g=self.game('finite',hand=('invoke','invoke'));self.play(g,'invoke');self.play(g,'invoke')
        selector=EndTurnSelector('owner',(1,),('hero',))
        self.assertFalse(end_turn_carriers(g.state,g.registry,selector))
        for profile in ('printed.hero','current.hero','any.hero'):
            self.assertEqual(len(end_turn_carriers(g.state,g.registry,selector,profile)),1)
        self.portable(g)

    def test_pre_guard_replacement_skips_finite_but_preserves_accepted_ordinary_hero(self):
        g=self.game('replacer');old=g.state.players[1].hero_id;self.end(g)
        self.assertNotEqual(g.state.players[1].hero_id,old);self.assertEqual(self.armor(g),1)
        self.assertEqual([row.skipped for row in g.state.end_turn_history],[False,True])
        self.portable(g)

    def test_wait_before_guard_retains_complete_proof_then_replacement_skips_finite(self):
        g=self.game('replacer','pre_wait');self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        for match in (g,*self.portable(g,'pre_wait')):
            self.choose(match);self.assertEqual(match.snapshot(),g.snapshot())
        self.assertEqual(self.armor(g),1);self.assertTrue(g.state.end_turn_history[-1].skipped)

    def test_after_consumption_replacement_keeps_accepted_finite_payload(self):
        g=self.game('finite','used_replace',board=('watch',));old=g.state.players[1].hero_id;self.end(g)
        self.assertNotEqual(g.state.players[1].hero_id,old);self.assertEqual(self.armor(g),2)
        self.assertTrue(g.state.end_turn_history[0].completed);self.portable(g,'used_replace')

    def test_body_replaces_hero_without_rebinding_already_accepted_repeat(self):
        g=self.game('finite','swap_body',hand=('invoke',),board=('all_twice',));old=g.state.players[1].hero_id
        self.play(g,'invoke');self.assertEqual(self.armor(g),4)
        self.assertTrue(all(row.capture.subject.source_id==old for row in g.state.end_turn_history));self.portable(g,'swap_body')

    def test_each_repeated_hero_body_wait_restores_and_resumes_one_guard(self):
        g=self.game('finite','wait',hand=('invoke',),board=('all_twice',));self.play(g,'invoke')
        for match in (g,*self.portable(g,'wait')):
            while match.state.pending_choice is not None:self.choose(match)
            self.assertEqual(match.snapshot(),g.snapshot())
        self.assertEqual(self.armor(g),4);self.assertEqual(self.finite(g)[0].uses_remaining,1)

    def test_nested_hero_roots_use_distinct_guard_windows_without_natural_events(self):
        g=self.game('finite','nested',hand=('invoke',));self.play(g,'invoke')
        self.assertEqual(self.armor(g),4);self.assertTrue(self.finite(g)[0].consumed)
        self.assertEqual(len(g.state.end_turn_history),2);self.assertEqual(g.state.turn,1);self.portable(g,'nested')

    def test_manual_hero_card_installs_classified_and_finite_printed_attachments(self):
        g=self.game('hero',hand=('hero_card','invoke'));self.play(g,'hero_card');self.play(g,'invoke')
        self.assertEqual(self.armor(g),3);self.assertEqual(len(g.state.play_history),2);self.portable(g)

    def test_generated_hero_installation_has_own_classified_and_finite_carriers(self):
        g=self.game('hero',hand=('install','invoke'));self.play(g,'install');self.play(g,'invoke')
        self.assertEqual(self.armor(g),3);self.assertEqual(len(g.state.play_history),2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].card_id,'hero_card');self.portable(g)

    def test_actual_whole_hero_replay_installs_new_printed_instances(self):
        for mode in ('normal','replay_bc','replay_family','replay_retained'):
            with self.subTest(profile=mode):
                g=self.game('hero',mode,hand=('hero_card','invoke','rerun','invoke'))
                self.play(g,'hero_card');self.play(g,'invoke');old=self.finite(g)[0];self.play(g,'rerun')
                self.assertNotEqual(self.finite(g)[0].id,old.id);self.assertEqual(self.finite(g)[0].uses_remaining,2)
                self.play(g,'invoke');self.assertEqual(self.armor(g),6)
                self.assertEqual(len(g.state.whole_card_replay_ledger.children),1);self.portable(g,mode)

    def test_replacement_reallocates_dynamic_instances_and_retains_remaining_uses(self):
        g=self.game('hero',hand=('grant_finite','invoke','replace','invoke'))
        self.play(g,'grant_finite');self.play(g,'invoke');old=self.finite(g)[0];self.play(g,'replace')
        new=self.finite(g)[0];self.assertNotEqual(new.id,old.id);self.assertEqual(new.uses_remaining,1)
        self.play(g,'invoke');self.assertEqual(self.armor(g),4);self.assertTrue(self.finite(g)[0].consumed);self.portable(g)

    def test_expiring_hero_grant_uses_only_real_turn_boundary(self):
        g=self.game('hero',hand=('grant_expiring','invoke'));self.play(g,'grant_expiring');self.play(g,'invoke')
        self.assertEqual(len(self.finite(g)),1);self.end(g)
        self.assertFalse(self.finite(g));self.assertEqual(self.armor(g),4);self.portable(g)

    def test_graveyard_hero_cannot_resubscribe_finite_grant(self):
        g=self.game('marked',hand=('replace','grant_dead','invoke'))
        for name in ('replace','grant_dead','invoke'):self.play(g,name)
        self.assertEqual(self.armor(g),0);self.assertFalse(self.finite(g));self.portable(g)

    def test_hero_keyword_spellburst_and_frenzy_stay_explicitly_rejected(self):
        for spec in (LimitedTriggerSpec.spellburst('event'),LimitedTriggerSpec.frenzy('event')):
            r=Registry('bad-keyword');r.register_behavior('event',lambda c:())
            with self.assertRaises(ValueError):r.register_card(CardDefinition('bad','Bad',CardType.HERO,health=30,
                keywords=(spec.keyword,),limited_triggers=(spec,)))
        g=self.game('hero',hand=('grant_bad',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Spellburst'):self.play(g,'grant_bad')
        self.assertEqual(g.snapshot(),before)

    def test_other_generic_finite_carrier_types_are_still_rejected(self):
        for kind in (CardType.HERO_POWER,CardType.LOCATION,CardType.SPELL):
            r=Registry('bad-carrier');r.register_behavior('event',lambda c:())
            with self.assertRaises(ValueError):r.register_card(CardDefinition('bad','Bad',kind,
                limited_triggers=(LimitedTriggerSpec('card_played','event'),)))

    def test_hero_end_failure_rolls_back_payment_consumption_rng_and_history(self):
        g=self.game('finite','fail',hand=('invoke',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'invoke')
        self.assertEqual(g.snapshot(),before);self.portable(g,'fail')

    def test_terminal_hero_body_never_fabricates_remaining_execution_or_turn_clock(self):
        g=self.game('mixed','lethal');self.end(g)
        self.assertEqual(g.state.status,'finished');self.assertEqual(g.state.turn,1)
        self.assertTrue(all(row.interrupted for row in g.state.end_turn_history));self.portable(g,'lethal')

    def test_rehashed_finite_hero_receipt_cannot_change_consumption(self):
        g=self.game('finite',hand=('invoke',));self.play(g,'invoke')
        self.reject(g,lambda s:s['state']['end_turn_history'][0]['guard_event'].__setitem__('amount',9))

    def test_pending_hero_body_cannot_erase_original_finish_batch(self):
        g=self.game('finite','wait',hand=('invoke',));self.play(g,'invoke')
        def mutate(s):
            removed=[]
            def walk(value):
                if type(value) is dict:
                    if type(value.get('tuple')) is list:
                        before=value['tuple'];value['tuple']=[x for x in before if not(type(x) is dict and str(x.get('type','')).endswith('.FinishEndTurnBatch'))]
                        removed.extend(range(len(before)-len(value['tuple'])))
                    for x in value.values():walk(x)
                elif type(value) is list:
                    for x in value:walk(x)
            walk(s['resolution_frame']);self.assertTrue(removed)
        self.reject(g,mutate,'wait')

    def test_unchanged_wire_layout_still_refuses_previous_rule_and_handler_versions(self):
        g=self.game('finite',hand=('invoke',));self.play(g,'invoke')
        self.assertEqual(g.snapshot()['schema_version'],266)
        self.reject(g,lambda s:s['ruleset'].__setitem__('id','prototype-v142'))
        self.reject(g,lambda s:s['mechanics_version'].__setitem__('version','core-effects-v142'))

    def test_hero_player_ports_publish_counts_without_behavior_or_private_proofs(self):
        g=self.game('finite','wait',hand=('invoke',));self.play(g,'invoke')
        for seat in (1,2):
            value=g.for_player(seat).observe()['observation'];self.assertEqual(value['players'][0]['hero']['limited_triggers'],[{'keyword':None,'uses_remaining':1}])
            text=json.dumps(value)
            for private in ('behavior_id','ability_id','source_json','EndTurnBatch'):self.assertNotIn(private,text)
        self.portable(g,'wait')
