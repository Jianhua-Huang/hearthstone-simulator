"""Captured power identities, replacement/removal and selected indirect activations."""
import json
import unittest
from dataclasses import replace

from hs_sim.engine import (AddHeroPower, CardDefinition, CardType, CostSpec, EndTurn, Game,
    HeroPowerReference, IllegalAction, PaymentType, PlayCard, PlayerSetup, Registry,
    RemoveHeroPower, ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec,
    TriggerHeroPower, TriggerSpec, UseHeroPower, Zone, hero_power_references)
from hs_sim.engine.effects import (ChoiceOption, GainArmor, InvokeBehavior, RefreshHeroPower,
    ReplaceHero, ReplaceHeroPower, RequestChoice, SetHeroPowerUses)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class PowerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('power-lifecycle-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        self.r.register_card(CardDefinition('body','body',CardType.MINION,attack=1,health=4))
        self.power('one',lambda c:[GainArmor(c.player_id,1)])
        self.power('two',lambda c:[GainArmor(c.player_id,2)],cost=3)
        self.r.register_behavior('listen',lambda c:[GainArmor(c.player_id,5)])
        self.r.register_card(CardDefinition('passive','passive',CardType.HERO_POWER,
            passive_hero_power=True,triggers=(TriggerSpec('card_played','listen'),)))

    def power(self,cid,fn,cost=2,**kw):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.HERO_POWER,cost=cost,on_use=cid,**kw))
    def script(self,cid,fn):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    def watch(self,cid,event,fn):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,triggers=(TriggerSpec(event,cid),)))
    def game(self,hand=(),extras=('two',),primary='one',board=(),mana=10):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,
            hero_power_card_id=primary,additional_hero_power_card_ids=extras,
            deck=('body',)*4,mana=mana,max_mana=10,corpses=6),
            PlayerSetup('hero',hero_power_card_id='one',deck=('body',)*4)),seed=68),self.r)
    def refs(self,state): return hero_power_references(state,1)
    def ref(self,g,i=1): return self.refs(g.state)[i]
    def use(self,g,i=1): g.apply(UseHeroPower(1,self.ref(g,i).entity_id))
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid))
    def armor(self,g): return g.state.entities[g.state.players[1].hero_id].armor
    def choose(self,g):
        c=g.state.pending_choice; g.apply(SelectChoice(c.player_id,c.id,(c.options[0].id,)))
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))
    def choice(self,effects): return RequestChoice(1,(ChoiceOption('go','go',tuple(effects)),))
    def replacement(self,card='one'):
        self.script('replace',lambda c:[ReplaceHeroPower(1,card,power=self.refs(c.state)[1])])
    def corpse_cost(self): return CostSpec(payment=PaymentType.CORPSES,card_types=(CardType.HERO_POWER,))

    def test_reference_query_captures_order_and_is_pure(self):
        g=self.game(extras=('two','one')); before=g.snapshot()
        self.assertEqual([r.card_id for r in self.refs(g.state)],['one','two','one'])
        self.assertEqual(hero_power_references(g.state,1,scope='primary'),(self.ref(g,0),))
        self.assertEqual(hero_power_references(g.state,1,scope='additional'),self.refs(g.state)[1:])
        self.assertEqual(g.snapshot(),before)
    def test_reference_query_empty_primary_does_not_reclassify_extra(self):
        g=self.game(primary=None)
        self.assertEqual(hero_power_references(g.state,1,scope='primary'),())
        self.assertEqual(self.refs(g.state),hero_power_references(g.state,1,scope='additional'))
    def test_reference_rejects_invalid_fields_and_non_power_capture(self):
        g=self.game(); ref=self.ref(g)
        for kw in ({'entity_id':True},{'player_id':3},{'zone_epoch':-1},{'entered_order':0},{'card_id':''}):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError): replace(ref,**kw)
        with self.assertRaises(ValueError): HeroPowerReference.capture(g.state.entities[g.state.players[1].hero_id])
        with self.assertRaises(ValueError): hero_power_references(g.state,1,scope='random')
    def test_selectors_reject_foreign_reference_and_bare_id(self):
        g=self.game(); foreign=hero_power_references(g.state,2)[0]
        for bad in (foreign,self.ref(g).entity_id):
            for fn in (lambda:RefreshHeroPower(1,bad),lambda:SetHeroPowerUses(1,2,bad),
                       lambda:ReplaceHeroPower(1,'one',bad),lambda:RemoveHeroPower(1,bad),
                       lambda:TriggerHeroPower(1,power=bad)):
                with self.assertRaises(ValueError): fn()

    def test_targeted_replace_keeps_extra_position_and_primary(self):
        self.replacement(); g=self.game(hand=('replace',),extras=('two','passive')); before=self.refs(g.state)
        self.play(g,'replace'); after=self.refs(g.state)
        self.assertEqual((after[0],after[2]),(before[0],before[2]))
        self.assertEqual(after[1].card_id,'one'); self.assertNotEqual(after[1].entity_id,before[1].entity_id)
        self.assertIn(before[1].entity_id,g.state.players[1].graveyard); self.check(g)
    def test_same_definition_replacement_has_fresh_uses_and_keeps_aggregate(self):
        self.replacement('two'); g=self.game(hand=('replace',)); old=self.ref(g); self.use(g); self.play(g,'replace')
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,1)
        self.assertEqual(g.state.entities[self.ref(g).entity_id].uses_this_turn,0)
        self.use(g); self.assertEqual([r.source_id for r in g.state.hero_power_history],[old.entity_id,self.ref(g).entity_id]); self.check(g)
    def test_reference_to_primary_does_not_follow_later_primary(self):
        self.script('swap',lambda c:[ReplaceHeroPower(1,'two'),RefreshHeroPower(1,self.refs(c.state)[0])])
        g=self.game(hand=('swap',)); old=self.ref(g,0); self.play(g,'swap')
        self.assertEqual([e.target_id for e in g.events if e.kind=='effect_skipped'],[old.entity_id])
        self.assertFalse(any(e.kind=='hero_power_refreshed' for e in g.events)); self.check(g)
    def test_dynamic_primary_operation_resolves_new_primary(self):
        self.script('swap',lambda c:[ReplaceHeroPower(1,'two'),SetHeroPowerUses(1,3),TriggerHeroPower(1,c.source_id)])
        g=self.game(hand=('swap',)); self.play(g,'swap')
        self.assertEqual(g.state.entities[self.ref(g,0).entity_id].use_limit,3)
        self.assertEqual(g.state.hero_power_history[0].source_id,self.ref(g,0).entity_id); self.check(g)
    def test_stale_replace_does_not_create_new_power_or_consume_ids(self):
        self.script('twice',lambda c:[ReplaceHeroPower(1,'one',self.refs(c.state)[1]),
                                      ReplaceHeroPower(1,'two',self.refs(c.state)[1])])
        g=self.game(hand=('twice',)); before=g.state.next_entity_id; self.play(g,'twice')
        self.assertEqual(g.state.next_entity_id,before+1)
        self.assertEqual(self.ref(g).card_id,'one'); self.check(g)
    def test_stale_replacement_still_rejects_unknown_definition(self):
        self.script('bad',lambda c:[RemoveHeroPower(1,self.refs(c.state)[1]),
                                   ReplaceHeroPower(1,'unknown',self.refs(c.state)[1])])
        g=self.game(hand=('bad',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_remove_extra_keeps_other_instances(self):
        self.script('remove',lambda c:[RemoveHeroPower(1,self.refs(c.state)[1],c.source_id)])
        g=self.game(hand=('remove',),extras=('two','one')); refs=self.refs(g.state); self.play(g,'remove')
        self.assertEqual(self.refs(g.state),(refs[0],refs[2])); self.assertIn(refs[1].entity_id,g.state.players[1].graveyard)
        self.assertFalse(g.state.death_history); self.check(g)
    def test_remove_primary_leaves_extra_in_its_role(self):
        self.script('remove',lambda c:[RemoveHeroPower(1)])
        g=self.game(hand=('remove',)); extra=self.ref(g); self.play(g,'remove')
        self.assertIsNone(g.state.players[1].hero_power_id); self.assertEqual(self.refs(g.state),(extra,)); self.use(g,0); self.check(g)
    def test_repeated_reference_removal_is_skipped_and_does_not_clear_primary(self):
        self.script('remove',lambda c:[RemoveHeroPower(1,self.refs(c.state)[1])]*2)
        g=self.game(hand=('remove',)); primary=self.ref(g,0); self.play(g,'remove')
        self.assertEqual(self.refs(g.state),(primary,)); self.assertEqual(sum(e.kind=='hero_power_removed' for e in g.events),1); self.check(g)
    def test_missing_dynamic_primary_operations_error_transactionally(self):
        ops=(RemoveHeroPower(1),RefreshHeroPower(1),SetHeroPowerUses(1,2),TriggerHeroPower(1))
        for n,op in enumerate(ops):self.script(str(n),lambda c,op=op:[op])
        for n in range(len(ops)):
            g=self.game(primary=None,hand=(str(n),)); before=g.snapshot()
            with self.assertRaises(ResolutionError): self.play(g,str(n))
            self.assertEqual(g.snapshot(),before)
    def test_removal_event_is_public_without_internal_reference_fields(self):
        self.script('remove',lambda c:[RemoveHeroPower(1,self.refs(c.state)[1],c.source_id)])
        g=self.game(hand=('remove',)); self.play(g,'remove')
        for viewer in (1,2):
            event=next(e for e in g.player_events(viewer) if e['kind']=='hero_power_removed')
            self.assertEqual(event['target']['card_id'],'two'); self.assertNotIn('zone_epoch',json.dumps(event))
        self.check(g)
    def test_removed_handle_cannot_activate_new_same_definition(self):
        self.script('renew',lambda c:[RemoveHeroPower(1,self.refs(c.state)[1]),AddHeroPower(1,'two')])
        g=self.game(hand=('renew',)); old=g.observe(1)['players'][0]['additional_hero_powers'][0]['ref']
        self.play(g,'renew'); port=g.for_player(1); view=port.observe(); before=g.snapshot()
        self.assertNotEqual(old,view['observation']['players'][0]['additional_hero_powers'][0]['ref'])
        result=port.submit({'revision':view['revision'],'action':{'type':'use_hero_power','power':old}})
        self.assertFalse(result['accepted']); self.assertEqual(g.snapshot(),before)
    def test_reference_does_not_depend_on_shifting_extra_index(self):
        self.script('shift',lambda c:[RemoveHeroPower(1,self.refs(c.state)[1]),
                                      SetHeroPowerUses(1,3,self.refs(c.state)[2])])
        g=self.game(hand=('shift',),extras=('two','one')); last=self.ref(g,2); self.play(g,'shift')
        self.assertEqual(self.ref(g),last); self.assertEqual(g.state.entities[last.entity_id].use_limit,3); self.check(g)

    def test_targeted_refresh_does_not_refresh_primary_or_reset_total(self):
        self.script('refresh',lambda c:[RefreshHeroPower(1,self.refs(c.state)[1])])
        g=self.game(hand=('refresh',)); self.use(g); self.use(g,0); self.play(g,'refresh')
        self.assertEqual([g.state.entities[r.entity_id].uses_this_turn for r in self.refs(g.state)],[1,0])
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,2); self.use(g); self.check(g)
    def test_targeted_limit_does_not_change_other_skill(self):
        self.script('limit',lambda c:[SetHeroPowerUses(1,2,self.refs(c.state)[1])])
        g=self.game(hand=('limit',)); self.play(g,'limit'); self.use(g); self.use(g)
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.state.entities[self.ref(g,0).entity_id].use_limit,1)
    def test_frozen_all_refresh_does_not_follow_replaced_member(self):
        self.watch('replace','hero_power_refreshed',lambda c:[ReplaceHeroPower(1,'one',self.refs(c.state)[1])]
                   if c.event.target_id==c.state.players[1].hero_power_id else [])
        self.script('all',lambda c:[RefreshHeroPower(1,power=p) for p in self.refs(c.state)])
        g=self.game(hand=('all',),board=('replace',)); old=self.ref(g); self.use(g); self.play(g,'all')
        self.assertNotEqual(old.entity_id,self.ref(g).entity_id)
        self.assertEqual(sum(e.kind=='hero_power_refreshed' for e in g.events),1)
        self.assertTrue(any(e.kind=='effect_skipped' and e.target_id==old.entity_id for e in g.events)); self.check(g)

    def test_selected_indirect_activation_ignores_cost_and_exhaustion(self):
        self.script('trigger',lambda c:[TriggerHeroPower(1,c.source_id,power=self.refs(c.state)[1])])
        g=self.game(hand=('trigger',),mana=3); self.use(g); self.play(g,'trigger')
        records=g.state.hero_power_history
        self.assertEqual([r.origin for r in records],['manual','effect'])
        self.assertEqual(g.state.players[1].mana,0); self.assertEqual(g.state.players[1].hero_power_uses_this_turn,1)
        self.assertEqual(self.armor(g),4); self.check(g)
    def test_stale_indirect_reference_does_not_activate_replacement(self):
        self.script('trigger',lambda c:[ReplaceHeroPower(1,'one',self.refs(c.state)[1]),
                         TriggerHeroPower(1,c.source_id,power=self.refs(c.state)[1])])
        g=self.game(hand=('trigger',)); self.play(g,'trigger')
        self.assertEqual(self.armor(g),0); self.assertEqual(g.state.hero_power_history,[]); self.check(g)
    def test_selected_passive_records_failed_attempt_without_manual_payload(self):
        self.script('trigger',lambda c:[TriggerHeroPower(1,c.source_id,power=self.refs(c.state)[1])])
        g=self.game(hand=('trigger',),extras=('passive',)); self.play(g,'trigger')
        record=g.state.hero_power_history[0]
        self.assertEqual((record.source_id,record.failure),(self.ref(g).entity_id,'passive'))
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,0); self.check(g)
    def test_selected_random_choice_does_not_pause_for_player(self):
        self.power('choice',lambda c:[RequestChoice(1,(ChoiceOption('go','go',(GainArmor(1,4),)),),source_id=c.source_id)])
        self.script('trigger',lambda c:[TriggerHeroPower(1,c.source_id,power=self.refs(c.state)[1])])
        # Automatic choice routing depends on the source, not which slot it uses.
        g=self.game(hand=('trigger',),extras=('choice',)); self.play(g,'trigger')
        self.assertIsNone(g.state.pending_choice); self.assertEqual(self.armor(g),4); self.check(g)
    def test_selected_player_choice_restores_same_source_and_record(self):
        self.power('choice',lambda c:[RequestChoice(1,(ChoiceOption('go','go',(GainArmor(1,4),)),),source_id=c.source_id)])
        self.script('trigger',lambda c:[TriggerHeroPower(1,c.source_id,choices='player',power=self.refs(c.state)[1])])
        g=self.game(hand=('trigger',),extras=('choice',)); self.play(g,'trigger'); self.check(g)
        self.assertEqual(g.state.pending_choice.source_id,self.ref(g).entity_id)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot()); self.check(g)
    def test_selected_target_failure_does_not_fallback_to_primary(self):
        self.power('target',lambda c:[GainArmor(1,9)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.script('trigger',lambda c:[TriggerHeroPower(1,c.source_id,power=self.refs(c.state)[1])])
        g=self.game(hand=('trigger',),extras=('target',)); self.play(g,'trigger')
        self.assertEqual(g.state.hero_power_history[0].failure,'no_target'); self.assertEqual(self.armor(g),0); self.check(g)
    def test_effect_start_removal_does_not_retarget_accepted_payload(self):
        self.watch('remove','hero_power_trigger_started',lambda c:[RemoveHeroPower(1,HeroPowerReference.capture(c.state.entities[c.event.source_id]))])
        self.script('trigger',lambda c:[TriggerHeroPower(1,c.source_id,power=self.refs(c.state)[1])])
        g=self.game(hand=('trigger',),board=('remove',)); old=self.ref(g); self.play(g,'trigger')
        self.assertEqual(self.armor(g),2); self.assertTrue(g.state.hero_power_history[0].completed)
        self.assertIn(old.entity_id,g.state.players[1].graveyard); self.check(g)

    def test_install_cost_is_visible_before_added_event_reactions(self):
        self.watch('inspect','hero_power_added',lambda c:[GainArmor(1,7)]
            if c.state.entities[c.event.target_id].enchantments[-1].payment==PaymentType.CORPSES else [])
        self.script('add',lambda c:[AddHeroPower(1,'two',c.source_id,self.corpse_cost())])
        g=self.game(hand=('add',),extras=(),board=('inspect',),mana=0); self.play(g,'add')
        self.assertEqual(self.armor(g),7); self.assertEqual(g.quote_cost(self.ref(g).entity_id).payment,PaymentType.CORPSES)
        self.use(g); self.assertEqual(self.armor(g),9); self.check(g)
    def test_replacement_cost_is_atomic_and_resets_old_attachments(self):
        self.watch('inspect','hero_power_replaced',lambda c:[GainArmor(1,c.state.entities[c.event.target_id].cost)])
        self.script('replace',lambda c:[ReplaceHeroPower(1,'one',self.refs(c.state)[1],
            CostSpec(set_to=1,card_types=(CardType.HERO_POWER,)),source_id=c.source_id)])
        g=self.game(hand=('replace',),board=('inspect',)); self.play(g,'replace')
        self.assertEqual(self.armor(g),1); self.assertEqual(g.quote_cost(self.ref(g).entity_id).amount,1); self.check(g)
    def test_install_cost_expiry_reverts_without_removing_skill(self):
        self.script('add',lambda c:[AddHeroPower(1,'two',c.source_id,self.corpse_cost(),c.state.turn)])
        g=self.game(hand=('add',),extras=()); self.play(g,'add'); ref=self.ref(g); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.ref(g),ref); self.assertEqual(g.quote_cost(ref.entity_id).payment,PaymentType.MANA); self.check(g)
    def test_invalid_cost_type_filter_or_expiry_rolls_back_installation(self):
        self.script('filter',lambda c:[AddHeroPower(1,'two',cost=CostSpec(delta=-1))])
        self.script('expired',lambda c:[ReplaceHeroPower(1,'one',self.refs(c.state)[1],self.corpse_cost(),1)])
        g=self.game(hand=('filter','expired')); before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'filter')
        self.assertEqual(g.snapshot(),before);g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'expired')
        self.assertEqual(g.snapshot(),before)
    def test_creation_cost_requires_spec_and_valid_expiry(self):
        for fn in (lambda:AddHeroPower(1,'one',cost={}),lambda:AddHeroPower(1,'one',expires_turn=2),
                   lambda:ReplaceHeroPower(1,'one',cost=True),lambda:ReplaceHeroPower(1,'one',expires_turn=0)):
            with self.assertRaises(ValueError):fn()

    def test_removal_stops_passive_listener_before_start(self):
        self.watch('remove','card_played',lambda c:[RemoveHeroPower(1,self.refs(c.state)[1])])
        self.script('install',lambda c:[AddHeroPower(1,'passive')])
        g=self.game(hand=('install',),extras=(),board=('remove',));self.play(g,'install')
        self.assertEqual(self.armor(g),0);self.assertEqual(len(self.refs(g.state)),1);self.check(g)
    def test_removed_and_readded_passive_does_not_receive_captured_old_event(self):
        self.watch('renew','card_played',lambda c:[RemoveHeroPower(1,self.refs(c.state)[1]),AddHeroPower(1,'passive')])
        self.script('install',lambda c:[AddHeroPower(1,'passive')])
        g=self.game(hand=('install',),extras=(),board=('renew',));self.play(g,'install')
        self.assertEqual(self.armor(g),0);self.check(g)
    def test_started_passive_choice_finishes_after_its_own_removal(self):
        self.r.register_behavior('listener',lambda c:[RequestChoice(1,(ChoiceOption('go','go',
            (RemoveHeroPower(1,HeroPowerReference.capture(c.source)),GainArmor(1,4))),),source_id=c.source_id)])
        self.r.register_card(CardDefinition('choosing','choosing',CardType.HERO_POWER,passive_hero_power=True,
            triggers=(TriggerSpec('card_played','listener'),)))
        g=self.game(hand=('body',),extras=('choosing',));self.play(g,'body');self.check(g);self.choose(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.refs(g.state)),1);self.check(g)
    def test_pending_reference_survives_restore_and_skips_replacement(self):
        self.script('wait',lambda c:[self.choice((ReplaceHeroPower(1,'one',self.refs(c.state)[1]),)),
            TriggerHeroPower(1,c.source_id,power=self.refs(c.state)[1])])
        g=self.game(hand=('wait',));self.play(g,'wait');self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.hero_power_history,[]);self.check(g)
    def test_failed_choice_rolls_back_removed_entities_and_cost_attachments(self):
        def fail(c):raise ValueError('expected failure')
        self.r.register_behavior('fail',fail)
        self.script('wait',lambda c:[self.choice((RemoveHeroPower(1,self.refs(c.state)[1]),
            AddHeroPower(1,'one',cost=self.corpse_cost()),InvokeBehavior('fail',c.source_id,1)))])
        g=self.game(hand=('wait',));self.play(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)
    def test_snapshot_rejects_invalid_captured_reference_fields(self):
        self.script('wait',lambda c:[self.choice((RefreshHeroPower(1,self.refs(c.state)[1]),))])
        g=self.game(hand=('wait',));self.play(g,'wait')
        def find(value):
            if isinstance(value,dict):
                if str(value.get('type','')).endswith('.HeroPowerReference'):return value['fields']
                for child in value.values():
                    found=find(child)
                    if found is not None:return found
            elif isinstance(value,list):
                for child in value:
                    found=find(child)
                    if found is not None:return found
        for key,value in (('zone_epoch',True),('entered_order',0),('player_id',2),('card_id','body')):
            s=g.snapshot();find(s['resolution_frame'])[key]=value;self.reject(s)

    def test_hero_effect_preserves_extra_by_default(self):
        self.script('change.hero',lambda c:[ReplaceHero(1,'hero',hero_power_card_id='two')])
        g=self.game(hand=('change.hero',));extra=self.ref(g);self.use(g);self.play(g,'change.hero')
        self.assertEqual(self.ref(g),extra);self.assertEqual(g.state.entities[extra.entity_id].uses_this_turn,1);self.check(g)
    def test_hero_effect_can_remove_all_extras_before_removal_events(self):
        self.watch('observe','hero_power_removed',lambda c:[GainArmor(1,3)]
            if not c.state.players[1].additional_hero_power_ids else [])
        self.script('change.hero',lambda c:[ReplaceHero(1,'hero',additional_power_policy='remove')])
        g=self.game(hand=('change.hero',),extras=('two','passive'),board=('observe',));old=self.refs(g.state);self.play(g,'change.hero')
        self.assertEqual(self.refs(g.state),(old[0],));self.assertEqual(self.armor(g),6)
        self.assertTrue(all(p.entity_id in g.state.players[1].graveyard for p in old[1:]));self.check(g)
    def test_playable_hero_policy_can_remove_extras(self):
        self.r.register_card(CardDefinition('hero.card','hero.card',CardType.HERO,health=30,hero_card=True,
            initial_hero_power='two',additional_power_policy='remove'))
        g=self.game(hand=('hero.card',),extras=('passive',));old=self.ref(g);self.play(g,'hero.card')
        self.assertEqual(len(self.refs(g.state)),1);self.assertEqual(self.ref(g,0).card_id,'two')
        self.assertIn(old.entity_id,g.state.players[1].graveyard);self.assertEqual(self.armor(g),0);self.check(g)
    def test_playable_hero_default_preserves_extra_identity(self):
        self.r.register_card(CardDefinition('hero.card','hero.card',CardType.HERO,health=30,hero_card=True,
            initial_hero_power='two'))
        g=self.game(hand=('hero.card',));extra=self.ref(g);self.play(g,'hero.card')
        self.assertEqual(self.ref(g),extra);self.check(g)
    def test_hero_replacement_policy_rejects_invalid_declarations(self):
        for policy in ('all',None,True):
            with self.assertRaises(ValueError):ReplaceHero(1,'hero',additional_power_policy=policy)
            with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',CardType.HERO,additional_power_policy=policy))
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',CardType.MINION,health=1,additional_power_policy='remove'))
    def test_hero_replacement_invalid_power_rolls_back_extra_removal(self):
        self.script('change.hero',lambda c:[ReplaceHero(1,'hero',hero_power_card_id='body',additional_power_policy='remove')])
        g=self.game(hand=('change.hero',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'change.hero')
        self.assertEqual(g.snapshot(),before)

    def test_reference_revision_and_definition_guards_skip_live_other_incarnation(self):
        self.script('guard',lambda c:[RefreshHeroPower(1,replace(self.refs(c.state)[1],**kw))
            for kw in ({'zone_epoch':100},{'entered_order':999},{'card_id':'one'})])
        g=self.game(hand=('guard',));self.use(g);self.play(g,'guard')
        self.assertEqual(g.state.entities[self.ref(g).entity_id].uses_this_turn,1)
        self.assertEqual(sum(e.kind=='effect_skipped' for e in g.events),3);self.check(g)

    def test_new_installation_is_excluded_from_frozen_all_selection(self):
        self.script('all',lambda c:[AddHeroPower(1,'one'),
            *(SetHeroPowerUses(1,3,power=p) for p in self.refs(c.state))])
        g=self.game(hand=('all',));self.play(g,'all')
        self.assertEqual([g.state.entities[p.entity_id].use_limit for p in self.refs(g.state)],[3,3,1]);self.check(g)

    def test_selected_explicit_target_is_preserved_in_activation_history(self):
        self.power('target',lambda c:[GainArmor(1,4)],targeting=TargetSpec(relation='enemy'))
        self.script('trigger',lambda c:[TriggerHeroPower(1,c.source_id,c.state.players[2].hero_id,
            targeting='explicit',power=self.refs(c.state)[1])])
        g=self.game(hand=('trigger',),extras=('target',));self.play(g,'trigger')
        record=g.state.hero_power_history[0]
        self.assertEqual((record.source_id,record.target_id),(self.ref(g).entity_id,g.state.players[2].hero_id))
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_manual_start_removal_preserves_payment_and_captured_completion(self):
        self.watch('remove','hero_power_started',lambda c:[RemoveHeroPower(1,
            HeroPowerReference.capture(c.state.entities[c.event.source_id]))])
        g=self.game(board=('remove',));old=self.ref(g);self.use(g)
        self.assertEqual((self.armor(g),g.state.players[1].mana,g.state.players[1].hero_power_uses_this_turn),(2,7,1))
        self.assertTrue(g.state.hero_power_history[0].completed)
        self.assertIn(old.entity_id,g.state.players[1].graveyard);self.check(g)


if __name__=='__main__':unittest.main()
