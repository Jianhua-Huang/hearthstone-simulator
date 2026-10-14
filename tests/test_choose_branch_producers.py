"""Creation/install events observe complete choices; source transfers are explicit."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (AddChooseBothModifier, AddHeroPower, CardDefinition,
    CardType, ChooseBranch, ChooseBranchSelection, ChooseOneSpec, CostSpec, DiscoverSpellHistory,
    Game, HeroPowerReference, HeroPowerRepeatSpec, IllegalAction, Keyword, PlayCard,
    PlayerSetup, RemoveHeroPower, RewindSpec, Scenario, SelectChoice, SetChooseBranch,
    TriggerHeroPower, TriggerSpec, UseHeroPower, Zone, capture_power_choose_branch, transfer_choose_branch)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Draw, GainArmor, RequestChoice,
    ReplaceHeroPower, Summon)
from hs_sim.engine.card_creation import CardSpellRepeatGrant
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_history import SpellHistoryQuery
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard
from test_player_choose_both import registry as base_registry, play


MAPPING=(('left','low'),('right','high'),('both','all'))
POWER_ORIGINS=('power_manual','power_effect')


def registry(mode='normal', policy='inherit', target='upgraded_power', branch='left',
             origins=POWER_ORIGINS, combination='override', mapping=None, explicit=None,
             slot=0, distinct='cast', source_policy='inherit', retries=None):
    r=base_registry()
    def old_body(c,amount):
        work=[GainArmor(c.player_id,amount+c.rewind_attempt)]
        source=c.state.entities[c.source_id]
        if mode in ('self_replace','self_wait') and source.zone == Zone.HERO_POWER:
            recipe=capture_power_choose_branch(c.state,r,c.power.id)
            chosen=transfer_choose_branch(r,recipe,target,mapping)
            change=ReplaceHeroPower(c.player_id,target,power=HeroPowerReference.capture(source),choose_branch=chosen,source_id=c.source_id)
            work.append(RequestChoice(c.player_id,(ChoiceOption('go','Go',(change,)),),c.source_id)
                        if mode=='self_wait' else change)
        if mode=='body_wait':work.append(RequestChoice(c.player_id,(ChoiceOption('go','Go'),),c.source_id))
        return tuple(work)
    for key,n in (('old_left',2),('old_right',4),('old_both',7)):
        r.register_behavior(key,lambda c,a=n:old_body(c,a))
    oldspec=ChooseOneSpec((ChooseBranch('left','Left','old_left'),ChooseBranch('right','Right','old_right')),
                         ChooseBranch('both','Both','old_both'))
    r.register_card(CardDefinition('old_power','Old',CardType.HERO_POWER,cost=1,choose_one=oldspec,
        **(dict(keywords=(Keyword.REWIND,),rewind=RewindSpec(retries)) if retries is not None else {})))
    for key,n in (('new_left',8),('new_right',12),('new_both',20)):
        r.register_behavior(key,lambda c,a=n:(GainArmor(c.player_id,a),))
    new=ChooseOneSpec((ChooseBranch('left','Left','new_left'),
                      ChooseBranch('right','Right','new_right')),
                     ChooseBranch('both','Both','new_both'))
    r.register_card(CardDefinition('upgraded_power','Upgraded',CardType.HERO_POWER,cost=2,choose_one=new))
    renamed=ChooseOneSpec((replace(new.branches[0],id='low'),replace(new.branches[1],id='high')),
                         replace(new.combined,id='all'))
    r.register_card(CardDefinition('mapped_power','Mapped',CardType.HERO_POWER,cost=2,choose_one=renamed))
    r.register_card(CardDefinition('plain_power','Plain power',CardType.HERO_POWER,on_use='extra'))
    r.register_card(CardDefinition('power_repeat','Power repeat',CardType.MINION,health=8,
                                  hero_power_repeats=(HeroPowerRepeatSpec(),)))
    def subject(c):
        p=c.state.players[c.player_id]
        return c.state.entities[p.hero_power_id if slot==0 else p.additional_hero_power_ids[slot-1]]
    def recipe(cid):return ChooseBranchSelection(cid,branch,origins if cid.endswith('power') else ('hand',),combination)
    def preset(c):return (SetChooseBranch(HeroPowerReference.capture(subject(c)),branch,origins,combination,c.source_id),)
    def replacement(c):
        reference=HeroPowerReference.capture(subject(c))
        effect=ReplaceHeroPower(c.player_id,target,power=None if mode=='absent' else reference,source_id=c.source_id,
            cost=CostSpec(delta=-1,card_types=(CardType.HERO_POWER,)) if mode=='cost' else None,
            choose_branch=None if explicit is None else ChooseBranchSelection(target,explicit,origins,combination),
            branch_policy=policy,branch_map=mapping)
        work=(effect,)
        if mode=='stale':
            work=(ReplaceHeroPower(c.player_id,'upgraded_power',power=reference,
                  choose_branch=ChooseBranchSelection('upgraded_power','right',POWER_ORIGINS)),effect)
        if mode in ('live_wait','clear_wait'):
            work=(SetChooseBranch(reference,'right' if mode=='live_wait' else None,origins,combination),effect)
        if mode in ('absent','stale_bad'):
            work=(RemoveHeroPower(c.player_id,reference),effect)
        if mode=='replace_fail':work+=(Summon(c.player_id,'unknown.producer.result'),)
        if mode=='replace_terminal':work+=(Damage(c.state.players[2].hero_id,90),)
        return (RequestChoice(c.player_id,(ChoiceOption('go','Go',work),),c.source_id),) if mode in (
            'replace_wait','stale','live_wait','clear_wait') else work
    def creation(c):
        value=ChooseBranchSelection('spell',branch,('hand',),combination)
        cost=CostSpec(delta=-1,card_types=(CardType.SPELL,)) if mode=='cost' else None
        work=(AddToDeck(c.player_id,'spell','top',c.source_id,cost=cost,choose_branch=value),) if mode in ('deck','deck_wait') else (
            AddToHand(c.player_id,'spell',c.source_id,cost=cost,choose_branch=value,
                      spell_repeat=CardSpellRepeatGrant(2) if mode=='creation_repeat' else None),
            *((AddToHand(c.player_id,'spell',c.source_id,choose_branch=value),) if mode=='burn' else ()))
        return (RequestChoice(c.player_id,(ChoiceOption('go','Go',work),),c.source_id),) if mode in ('create_wait','deck_wait') else work
    def add(c):return (AddHeroPower(c.player_id,target,c.source_id,choose_branch=recipe(target),
        cost=CostSpec(delta=-1,card_types=(CardType.HERO_POWER,)) if mode=='cost' else None),)
    def discover(c):return (DiscoverSpellHistory(c.player_id,SpellHistoryQuery(origins=('hand',)),count=2,
        distinct=distinct,source_id=c.source_id,branch_policy=source_policy),)
    for key,fn in (('preset',preset),('replace',replacement),('create',creation),('add',add),('discover',discover),
                   ('draw_generated',lambda c:(Draw(c.player_id),)),
                   ('grant',lambda c:(AddChooseBothModifier(c.player_id,uses=1,kinds=(CardType.HERO_POWER,),origins=('power_manual',)),)),
                   ('indirect',lambda c:(TriggerHeroPower(c.player_id,c.source_id,choices='player'),))):
        r.register_behavior('producer_'+key,fn)
        r.register_card(CardDefinition('producer_'+key,key,CardType.SPELL,on_play='producer_'+key))
    def watch(c):
        if c.event.target_id is None:return ()
        e=c.state.entities[c.event.target_id]
        return (GainArmor(c.player_id,1 if e.choose_branch is not None else 99),)
    r.register_behavior('producer_watch',watch)
    r.register_card(CardDefinition('producer_watch','Watch',CardType.MINION,health=8,
        triggers=tuple(TriggerSpec(e,'producer_watch') for e in ('card_created','hero_power_added','hero_power_replaced'))))
    return r


def game(hand=('producer_preset','producer_replace'), board=(), primary='old_power', extras=(), **cfg):
    return Game.from_scenario(Scenario((PlayerSetup('hero',hero_power_card_id=primary,
        additional_hero_power_card_ids=extras,hand=hand,board=board,deck=('plain',)*8,mana=10,max_mana=10),
        PlayerSetup('hero',hero_power_card_id='old_power',hand=('spell',),deck=('plain',)*8)),seed=27),registry(**cfg))


class ChooseBranchProducerTests(unittest.TestCase):
    def power(self,g,slot=0):
        p=g.state.players[1];return p.hero_power_id if slot==0 else p.additional_hero_power_ids[slot-1]
    def use(self,g,branch='left',slot=0):g.apply(UseHeroPower(1,self.power(g,slot),branch_id=branch))
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def choose(self,g,key='go'):
        p=g.state.pending_choice;g.apply(SelectChoice(p.player_id,p.id,(key,)))
    def check(self,g,**cfg):
        snapshot=json.loads(json.dumps(g.snapshot()))
        copies=(Game.from_snapshot(snapshot,registry(**cfg)),g.clone(),replay(build_replay(g),registry(**cfg)))
        for other in copies:
            self.assertEqual(other.snapshot(),snapshot)
            for viewer in (1,2):
                self.assertEqual(other.observe(viewer),g.observe(viewer))
                self.assertEqual(other.player_events(viewer),g.player_events(viewer))
                self.assertEqual(other.for_player(viewer).legal_actions(),g.for_player(viewer).legal_actions())
        return copies[0]
    def negative(self,g,mutate,**cfg):
        bad=deepcopy(g.snapshot());mutate(bad)
        bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as e:Game.from_snapshot(bad,registry(**cfg))
        self.assertNotIn('digest mismatch',str(e.exception))
    def typed(self,value,name):
        if type(value)is dict:
            if value.get('type','').endswith('.'+name):return value
            for child in value.values():
                found=self.typed(child,name)
                if found is not None:return found
        elif type(value)is list:
            for child in value:
                found=self.typed(child,name)
                if found is not None:return found
        return None

    def test_hand_creation_is_preselected_before_first_acquisition_observer(self):
        g=game(hand=('producer_create',),board=('producer_watch',));play(g,'producer_create')
        e=g.state.entities[g.state.players[1].hand[0]]
        self.assertEqual(e.choose_branch,ChooseBranchSelection('spell','left'))
        self.assertEqual(self.armor(g),1)
        self.assertEqual({a.branch_id for a in g.legal_actions() if isinstance(a,PlayCard)}, {'left'})
        play(g,'spell','left');self.assertEqual(self.armor(g),3);self.check(g)
    def test_deck_creation_keeps_private_preselection_until_draw(self):
        cfg=dict(mode='deck');g=game(hand=('producer_create','producer_draw_generated'),**cfg);play(g,'producer_create')
        e=g.state.entities[g.state.players[1].deck[0]];self.assertEqual(e.choose_branch.branch_id,'left')
        self.assertNotIn('choose_branch',json.dumps(g.observe(2)))
        play(g,'producer_draw_generated');play(g,'spell','left');self.check(g,**cfg)
    def test_generated_cost_and_branch_are_installed_together(self):
        cfg=dict(mode='cost');g=game(hand=('producer_create',),board=('producer_watch',),**cfg);play(g,'producer_create')
        e=g.state.entities[g.state.players[1].hand[0]]
        self.assertEqual((e.choose_branch.branch_id,g.quote_cost(e.id).amount),('left',0))
        self.assertEqual(self.armor(g),1);self.check(g,**cfg)
    def test_burned_generated_card_keeps_complete_declared_recipe(self):
        cfg=dict(mode='burn');g=game(hand=('producer_create',)+('plain',)*9,**cfg);play(g,'producer_create')
        cards=[e for e in g.state.entities.values() if e.card_id=='spell' and e.owner==1]
        self.assertEqual([e.zone for e in cards],[Zone.HAND,Zone.GRAVEYARD])
        self.assertTrue(all(e.choose_branch.branch_id=='left' for e in cards));self.check(g,**cfg)
    def test_creation_repeat_runs_original_preselection_with_one_payment(self):
        cfg=dict(mode='creation_repeat');g=game(hand=('producer_create',),**cfg);play(g,'producer_create');play(g,'spell','left')
        self.assertEqual([c.branch_id for c in g.state.cast_history if c.card_id=='spell'],['left','left'])
        self.assertEqual((self.armor(g),g.state.players[1].mana),(4,9));self.check(g,**cfg)
    def test_default_creation_has_no_borrowed_preselection(self):
        r=registry();r.register_behavior('plain_create',lambda c:(AddToHand(1,'spell'),))
        r.register_card(CardDefinition('plain_create','Create',CardType.SPELL,on_play='plain_create'))
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('plain_create',),mana=10,max_mana=10),PlayerSetup('hero'))),r)
        play(g,'plain_create');self.assertIsNone(g.state.entities[g.state.players[1].hand[0]].choose_branch)
    def test_additional_power_installs_recipe_before_added_event(self):
        g=game(hand=('producer_add',),board=('producer_watch',));play(g,'producer_add')
        power=g.state.entities[self.power(g,1)]
        self.assertEqual(power.choose_branch.branch_id,'left');self.assertEqual(self.armor(g),1)
        self.use(g,'left',1);self.assertEqual((self.armor(g),g.state.players[1].mana),(9,8));self.check(g)
    def test_replacement_inherits_recipe_with_new_payload_and_card_price(self):
        g=game();play(g,'producer_preset');old=self.power(g);self.use(g);play(g,'producer_replace');new=self.power(g)
        self.assertNotEqual(new,old);self.assertEqual(g.state.entities[new].choose_branch.card_id,'upgraded_power')
        self.assertEqual((g.state.entities[new].uses_this_turn,g.state.entities[old].uses_this_turn),(0,1))
        self.use(g);self.assertEqual((self.armor(g),g.state.players[1].mana),(10,7));self.check(g)
    def test_explicit_mapping_transfers_ordinary_branch_to_renamed_face(self):
        cfg=dict(target='mapped_power',mapping=MAPPING);g=game(**cfg);play(g,'producer_preset');play(g,'producer_replace')
        self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'low');self.use(g,'low');self.check(g,**cfg)
    def test_explicit_mapping_preserves_combined_branch_role(self):
        cfg=dict(target='mapped_power',mapping=MAPPING,branch='both');g=game(**cfg);play(g,'producer_preset');play(g,'producer_replace')
        self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'all');self.use(g,'all');self.check(g,**cfg)
    def test_default_replacement_clears_old_recipe(self):
        cfg=dict(policy='clear');g=game(**cfg);play(g,'producer_preset');play(g,'producer_replace')
        self.assertIsNone(g.state.entities[self.power(g)].choose_branch);self.use(g,'right');self.check(g,**cfg)
    def test_replacement_can_explicitly_declare_another_branch_atomically(self):
        cfg=dict(policy='clear',explicit='right');g=game(board=('producer_watch',),**cfg);play(g,'producer_preset');play(g,'producer_replace')
        self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'right');self.assertEqual(self.armor(g),1)
        self.use(g,'right');self.check(g,**cfg)
    def test_inherited_origin_and_strict_conflict_remain_separate_from_new_policy(self):
        cfg=dict(origins=('power_manual',),combination='strict');g=game(hand=('producer_preset','producer_replace','producer_grant'),**cfg)
        play(g,'producer_preset');play(g,'producer_replace');play(g,'producer_grant')
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g,'both')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining,1)
        self.check(g,**cfg)
    def test_new_manual_root_combines_and_consumes_its_own_policy_once(self):
        g=game(hand=('producer_preset','producer_replace','producer_grant'))
        play(g,'producer_preset');play(g,'producer_replace');play(g,'producer_grant');self.use(g,'both')
        self.assertEqual(self.armor(g),20);self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'left')
        self.assertEqual(len(g.state.choose_policy_receipts),1);self.check(g)
    def test_targeted_additional_replacement_preserves_slot_and_other_instances(self):
        cfg=dict(slot=2);g=game(extras=('old_power','old_power'),**cfg);primary=self.power(g);first=self.power(g,1);old=self.power(g,2)
        play(g,'producer_preset');play(g,'producer_replace')
        self.assertEqual((self.power(g),self.power(g,1)),(primary,first));self.assertNotEqual(self.power(g,2),old)
        self.assertEqual(g.state.entities[self.power(g,2)].choose_branch.branch_id,'left');self.check(g,**cfg)
    def test_stale_targeted_inheritance_skips_without_retargeting_reinstalled_power(self):
        cfg=dict(mode='stale');g=game(**cfg);play(g,'producer_preset');old=self.power(g);play(g,'producer_replace')
        effect=self.typed(g.snapshot()['resolution_frame'],'ReplaceHeroPower')
        self.assertIsNotNone(effect);g=self.check(g,**cfg);before=g.state.next_entity_id;rng=g.snapshot()['rng_state'];self.choose(g)
        self.assertEqual(g.state.next_entity_id,before+1)
        self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'right')
        skipped=[e for e in g.events if e.kind=='effect_skipped']
        self.assertEqual([(e.target_id,dict(e.data)['reason']) for e in skipped],[(old,'hero_power_reference_stale')])
        self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g,**cfg)
    def test_waiting_inheritance_restores_the_frozen_request_then_uses_actual_old_recipe(self):
        cfg=dict(mode='replace_wait');g=game(**cfg);play(g,'producer_preset');play(g,'producer_replace');g=self.check(g,**cfg)
        self.choose(g);self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'left');self.check(g,**cfg)
    def test_accepted_power_branch_can_be_frozen_for_self_replacement(self):
        cfg=dict(mode='self_replace');g=game(hand=('producer_preset',),**cfg);play(g,'producer_preset');old=self.power(g);self.use(g)
        self.assertEqual(g.state.hero_power_history[-1].branch_id,'left');self.assertNotEqual(self.power(g),old)
        self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'left');self.check(g,**cfg)
    def test_accepted_combined_root_is_distinct_from_old_saved_ordinary_preference(self):
        cfg=dict(mode='self_replace');g=game(hand=('producer_preset','producer_grant'),**cfg)
        play(g,'producer_preset');play(g,'producer_grant');old=self.power(g);self.use(g,'both')
        self.assertEqual(g.state.entities[old].choose_branch.branch_id,'left')
        self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'both')
        self.assertFalse(g.state.players[1].choose_both_modifiers);self.check(g,**cfg)
    def test_self_replacement_wait_freezes_actual_branch_until_selection(self):
        cfg=dict(mode='self_wait');g=game(hand=('producer_preset',),**cfg);play(g,'producer_preset');self.use(g);g=self.check(g,**cfg)
        self.choose(g);self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'left');self.check(g,**cfg)
    def test_already_accepted_repeats_keep_old_branch_after_slot_replacement(self):
        cfg=dict(mode='self_replace');g=game(hand=('producer_preset',),board=('power_repeat',),**cfg);play(g,'producer_preset');old=self.power(g);self.use(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(g.state.hero_power_history[0].source_id,old);self.assertEqual(len(g.state.hero_power_payload_history),2)
        self.check(g,**cfg)
    def test_history_discovery_freezes_each_actual_offered_branch_until_creation(self):
        g=game(hand=('spell','spell','producer_discover'));play(g,'spell','left');play(g,'spell','right');play(g,'producer_discover')
        offered=g._frame.options;self.assertEqual({o.effects[0].choose_branch.branch_id for o in offered},{'left','right'})
        selected=next(o.id for o in offered if o.effects[0].choose_branch.branch_id=='right');g=self.check(g);self.choose(g,selected)
        e=g.state.entities[g.state.players[1].hand[0]];self.assertEqual(e.choose_branch.branch_id,'right')
        play(g,'spell','right');self.check(g)
    def test_history_card_dedup_inherits_its_canonical_first_occurrence(self):
        cfg=dict(distinct='card');g=game(hand=('spell','spell','producer_discover'),**cfg)
        play(g,'spell','left');play(g,'spell','right');play(g,'producer_discover')
        self.assertEqual(len(g._frame.options),1);self.assertEqual(g._frame.options[0].effects[0].choose_branch.branch_id,'left')
        self.choose(g,g._frame.options[0].id);self.check(g,**cfg)
    def test_default_history_discovery_creates_unselected_base_card(self):
        cfg=dict(source_policy='current');g=game(hand=('spell','producer_discover'),**cfg);play(g,'spell','right');play(g,'producer_discover')
        self.choose(g,g._frame.options[0].id);self.assertIsNone(g.state.entities[g.state.players[1].hand[0]].choose_branch);self.check(g,**cfg)
    def test_transfer_queries_are_pure_complete_and_preserve_origin_and_conflict_policy(self):
        r=registry();value=ChooseBranchSelection('old_power','right',('power_manual',),'strict')
        chosen=transfer_choose_branch(r,value,'mapped_power',MAPPING)
        self.assertEqual(chosen,ChooseBranchSelection('mapped_power','high',('power_manual',),'strict'))
        self.assertEqual(value.card_id,'old_power')
        for wrong in ((('left','low'),),(('left','all'),('right','high'),('both','low')),
                      (('right','high'),('left','low'),('both','all'))):
            with self.assertRaises(ValueError):transfer_choose_branch(r,value,'mapped_power',wrong)
        with self.assertRaises(ValueError):transfer_choose_branch(r,value,'mapped_power')
        with self.assertRaises(ValueError):transfer_choose_branch(r,value,'spell')
    def test_invalid_creation_and_replacement_declarations_fail_explicitly(self):
        for factory in (lambda:AddToHand(1,'spell',choose_branch='left'),
                        lambda:AddToDeck(1,'spell',choose_branch=ChooseBranchSelection('minion','left')),
                        lambda:AddHeroPower(1,'upgraded_power',choose_branch=ChooseBranchSelection('old_power','left',POWER_ORIGINS)),
                        lambda:ReplaceHeroPower(1,'upgraded_power',branch_policy='current'),
                        lambda:ReplaceHeroPower(1,'upgraded_power',choose_branch=ChooseBranchSelection('upgraded_power','left',POWER_ORIGINS),branch_policy='inherit'),
                        lambda:ReplaceHeroPower(1,'mapped_power',branch_map=MAPPING),
                        lambda:DiscoverSpellHistory(1,branch_policy='wrong')):
            with self.assertRaises(ValueError):factory()
    def test_invalid_inherited_mapping_rolls_back_installed_power_and_resources(self):
        cfg=dict(target='mapped_power');g=game(**cfg);play(g,'producer_preset');before=g.snapshot()
        with self.assertRaises(ResolutionError):play(g,'producer_replace')
        self.assertEqual(g.snapshot(),before);self.check(g,**cfg)
    def test_deferred_power_recipe_cannot_use_hand_activation_authority(self):
        cfg=dict(mode='replace_wait',policy='clear',explicit='left');g=game(**cfg);play(g,'producer_replace')
        def mutate(b):
            op=self.typed(b['resolution_frame'],'ReplaceHeroPower');op['fields']['choose_branch']['fields']['origins']={'tuple':['hand']}
        self.negative(g,mutate,**cfg);self.check(g,**cfg)
    def test_visible_recipe_does_not_leak_enemy_hand_or_host_proof_data(self):
        g=game(hand=('producer_create','producer_add'));play(g,'producer_create');play(g,'producer_add')
        for viewer in (1,2):
            text=json.dumps({'view':g.observe(viewer),'events':g.player_events(viewer)})
            for private in ('branch_map','HeroPowerReference','source_id','rng_state','resolution_frame'):
                self.assertNotIn('"'+private+'"',text)
        own=g.observe(1)['players'][0]['hand'][0];enemy=g.observe(2)['players'][0]['hand'][0]
        self.assertEqual(own['choose_selection']['branch'],'left');self.assertNotIn('choose_selection',enemy);self.check(g)

    def test_live_transfer_reads_recipe_at_installation_after_prior_effect(self):
        cfg=dict(mode='live_wait');g=game(**cfg);play(g,'producer_preset');play(g,'producer_replace');g=self.check(g,**cfg)
        self.choose(g);self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'right');self.check(g,**cfg)
    def test_cleared_recipe_does_not_guess_from_last_accepted_activation(self):
        cfg=dict(mode='clear_wait');g=game(**cfg);play(g,'producer_preset');self.use(g);play(g,'producer_replace');g=self.check(g,**cfg)
        self.choose(g);self.assertIsNone(g.state.entities[self.power(g)].choose_branch)
        self.assertEqual(g.state.hero_power_history[0].branch_id,'left');self.use(g,'right');self.check(g,**cfg)
    def test_manual_only_inheritance_leaves_indirect_branch_selection_to_source_policy(self):
        cfg=dict(origins=('power_manual',));g=game(hand=('producer_preset','producer_replace','producer_indirect'),**cfg)
        play(g,'producer_preset');play(g,'producer_replace');before=g.snapshot()['rng_state'];play(g,'producer_indirect')
        self.assertIsNone(g.state.pending_choice);self.assertNotEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(g.state.hero_power_history[-1].origin,'effect')
        self.assertIn(g.state.hero_power_history[-1].branch_id,('left','right'))
        self.assertEqual(g.state.players[1].mana,10);self.check(g,**cfg)
    def test_replaced_cost_and_branch_are_observed_together_and_pay_once(self):
        cfg=dict(mode='cost');g=game(board=('producer_watch',),**cfg);play(g,'producer_preset');play(g,'producer_replace')
        p=g.state.entities[self.power(g)];self.assertEqual((p.choose_branch.branch_id,g.quote_cost(p.id).amount),('left',1))
        self.assertEqual(self.armor(g),1);self.use(g);self.assertEqual((self.armor(g),g.state.players[1].mana),(9,9));self.check(g,**cfg)
    def test_deferred_hand_and_deck_creation_restore_typed_recipe_and_reject_wrong_origin(self):
        for mode,effect in (('create_wait','AddToHand'),('deck_wait','AddToDeck')):
            with self.subTest(mode=mode):
                cfg=dict(mode=mode);g=game(hand=('producer_create',),**cfg);play(g,'producer_create');g=self.check(g,**cfg)
                def mutate(b):
                    op=self.typed(b['resolution_frame'],effect)
                    op['fields']['choose_branch']['fields']['origins']={'tuple':['power_manual']}
                self.negative(g,mutate,**cfg);self.choose(g)
                p=g.state.players[1];eid=p.hand[0] if mode=='create_wait' else p.deck[0]
                self.assertEqual(g.state.entities[eid].choose_branch.branch_id,'left');self.check(g,**cfg)
    def test_deferred_replacement_rejects_incomplete_mapping_before_stale_skip(self):
        cfg=dict(mode='stale',target='mapped_power',mapping=MAPPING);g=game(**cfg);play(g,'producer_preset');play(g,'producer_replace')
        def mutate(b):
            def visit(v):
                if type(v)is dict:
                    if v.get('type','').endswith('.ReplaceHeroPower') and v['fields']['branch_policy']=='inherit':
                        v['fields']['branch_map']['tuple']=v['fields']['branch_map']['tuple'][:-1]
                    for child in v.values():visit(child)
                elif type(v)is list:
                    for child in v:visit(child)
            visit(b['resolution_frame'])
        self.negative(g,mutate,**cfg);g=self.check(g,**cfg);self.choose(g);self.check(g,**cfg)
    def test_stale_reference_still_rejects_incompatible_inherited_target(self):
        cfg=dict(mode='stale_bad',target='mapped_power');g=game(**cfg);play(g,'producer_preset');before=g.snapshot()
        with self.assertRaises(ResolutionError):play(g,'producer_replace')
        self.assertEqual(g.snapshot(),before);self.check(g,**cfg)
    def test_empty_primary_cannot_supply_an_inherited_recipe(self):
        cfg=dict(mode='absent');g=game(**cfg);play(g,'producer_preset');before=g.snapshot()
        with self.assertRaises(ResolutionError):play(g,'producer_replace')
        self.assertEqual(g.snapshot(),before);self.check(g,**cfg)
    def test_failure_after_branch_installation_rolls_back_recipe_and_allocation(self):
        cfg=dict(mode='replace_fail');g=game(**cfg);play(g,'producer_preset');before=g.snapshot()
        with self.assertRaises(ResolutionError):play(g,'producer_replace')
        self.assertEqual(g.snapshot(),before);self.check(g,**cfg)
    def test_terminal_after_replacement_preserves_installed_recipe(self):
        cfg=dict(mode='replace_terminal');g=game(**cfg);play(g,'producer_preset');play(g,'producer_replace')
        self.assertEqual(g.state.winner,1);self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'left');self.check(g,**cfg)
    def test_real_retry_reinstalls_branch_with_fresh_identity_and_one_payment(self):
        cfg=dict(mode='self_replace',retries=1);g=game(hand=('producer_preset',),**cfg);play(g,'producer_preset');old=self.power(g)
        self.use(g);first=self.power(g);g=self.check(g,**cfg);self.choose(g,'retry')
        self.assertNotIn(first,g.state.entities);self.assertGreater(self.power(g),first)
        self.assertEqual((g.state.hero_power_history[0].source_id,g.state.players[1].mana,self.armor(g)),(old,9,3))
        self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'left');self.check(g,**cfg)
    def test_retained_results_keep_captured_branch_after_first_outcome_replaces_slot(self):
        cfg=dict(mode='self_replace',retries=1);g=game(hand=('producer_preset',),board=('retainer',),**cfg);play(g,'producer_preset');old=self.power(g)
        self.use(g);self.assertEqual((self.armor(g),g.state.players[1].mana),(5,9))
        self.assertEqual(len(g.state.hero_power_history),1);self.assertEqual(g.state.hero_power_history[0].source_id,old)
        self.assertEqual(g.state.rewind_outcomes[0].completed,2);self.assertEqual(g.state.entities[self.power(g)].choose_branch.branch_id,'left');self.check(g,**cfg)
    def test_unbranched_capture_is_pure_and_invalid_authority_is_not_ignored(self):
        g=game(hand=(),primary='plain_power');g.apply(UseHeroPower(1,self.power(g)));before=g.snapshot()
        self.assertIsNone(capture_power_choose_branch(g.state,g.registry,1))
        for kw in (dict(origins=('hand',)),dict(combination='bad'),dict(origins=())):
            with self.assertRaises(ValueError):capture_power_choose_branch(g.state,g.registry,1,**kw)
        self.assertEqual(g.snapshot(),before);self.check(g)


if __name__=='__main__':unittest.main()
