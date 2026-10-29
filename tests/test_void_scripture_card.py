"""Original discoveries, remaining Mana, stored material and ordinary CASTs."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import void_scripture_card as native
from hs_sim.engine import Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.costs import local_cost
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.discovered_spell_casts import CastAffordableDiscoveredSpell,CHECKED,QUEUED,QUERY
from hs_sim.engine.effects import (AddToHand,AddCostModifier,ChoiceOption,Damage,GainArmor,
    GainTemporaryMana,InvokeBehavior,RandomDamage,RequestChoice,SpendMana)
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,DamageKind,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spent_spells import ReturnSpentSpell
from hs_sim.engine.zones import CardReference,ModifyStoredCost,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

CARD=native.CARD;P='k652.'
A,B,Z,FRIEND,INNER,OTHER,WATCH,FAIL,AUTO,UNKNOWN=(P+x for x in
    ('one','five','zero','friendly','inner','other','watch','fail','auto','unknown'))
CTX=GenerationContext('k652-original-discovered-copies','experimental')


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='Original discovered-copy reaction')


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_void_scripture_card(r)
    def fail(c):raise ValueError('K652 deliberate failure')
    r.register_behavior(FAIL,fail)
    def damage(c):
        if mode=='body_fail':return (InvokeBehavior(FAIL,c.source_id,c.player_id),)
        return (Damage(c.target_id,100 if mode=='lethal' else local_cost(c.source)[0]+1,c.source_id,DamageKind.SPELL),)
    for cid,cost,hero in ((A,1,CardClass.MAGE),(B,5,CardClass.MAGE),(Z,0,CardClass.MAGE),
            (FRIEND,1,CardClass.MAGE),(INNER,1,CardClass.MAGE),(OTHER,1,CardClass.ROGUE)):
        body=(lambda c:(GainArmor(c.player_id,3),))if cid==Z else (
            lambda c:(DiscoverFromPool(c.player_id,P+'inner_pool',QUERY,source_id=c.source_id),))if cid==INNER else damage
        r.register_behavior(cid,body)
        card=CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,metadata=metadata(hero),
            targeting=TargetSpec(relation='friendly'if cid==FRIEND else'any')if cid not in(Z,INNER)else None)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=(PoolMember(A,2),PoolMember(B,5),PoolMember(Z),PoolMember(OTHER,9))
    if mode in('friendly',):members=(PoolMember(FRIEND),)
    if mode=='inner_discover':members=(PoolMember(INNER),)
    if mode in('discount','external_discount','gain','spend','transform','cycle','leave','burn','native_copy'):members=(PoolMember(B),)
    if mode=='empty':members=(PoolMember(OTHER),)
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,1,metadata(CardClass.MAGE)));members=(*members,PoolMember(UNKNOWN))
    r.register_pool(PoolDefinition('constructed.cards','k652.full-spell-fixture',CTX.target_id,CTX.mode,members,complete=True))
    r.register_pool(PoolDefinition(P+'inner_pool','k652.inner',CTX.target_id,CTX.mode,(PoolMember(Z),),complete=True))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,CARD,c.source_id),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.SPELL,on_play=AUTO,metadata=metadata()))
    def watch(c):
        event=c.event;source=c.state.entities.get(event.source_id)
        if event.kind=='spell_cast_started':
            cast=c.state.cast_history[dict(event.data)['cast_id']-1]
            if mode=='burn'and cast.card_id==CARD:return(AddToHand(c.player_id,'card.1',c.source_id),)
            if mode=='cast_wait'and cast.caster_id is not None and c.state.entities[cast.caster_id].card_id==CARD:return(prompt(c),)
            return ()
        if source is None or source.card_id!=CARD:return ()
        if event.kind=='card_added_to_hand':return(prompt(c),)if mode=='delivery_wait'else()
        if event.kind!='card_discovered':return ()
        if mode=='completed_fail':return(InvokeBehavior(FAIL,c.source_id,c.player_id),)
        if mode=='completed_wait':return(prompt(c),)
        if mode=='gain':return(GainTemporaryMana(c.player_id,3),)
        if mode=='spend':return(SpendMana(c.player_id,4,c.source_id),)
        if mode=='nested':return(DiscoverFromPool(c.player_id,P+'inner_pool',QUERY,source_id=c.source_id),)
        if mode=='return_source':return(ReturnSpentSpell(SourceAllocationFact.capture(c.state,source),c.player_id),)
        if mode=='burn':return ()
        e=c.state.entities[event.target_id];ref=CardReference.capture(e)
        if mode in('discount','native_copy'):return(ModifyStoredCost(ref,CostSpec(delta=-4),c.source_id),)
        if mode=='external_discount':return(AddCostModifier(c.player_id,CostSpec(delta=-4,card_types=(CardType.SPELL,)),uses_remaining=1,source_id=c.source_id),)
        if mode=='transform':return(TransformStoredCard(ref,Z,c.source_id),)
        if mode=='leave':return(MoveCard(ref,c.player_id,Zone.DECK,position='bottom',source_id=c.source_id),)
        if mode=='cycle':return(MoveCard(ref,c.player_id,Zone.DECK,position='bottom',source_id=c.source_id),
            MoveCard(replace(ref,zone=Zone.DECK,zone_epoch=ref.zone_epoch+1),c.player_id,Zone.HAND,source_id=c.source_id))
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=metadata(),
        triggers=tuple(TriggerSpec(e,WATCH)for e in('card_added_to_hand','card_discovered','spell_cast_started'))))
    return r


@lru_cache(maxsize=1)
def host():return build_cn37_local_pool_format()


def wires(value,name):
    if isinstance(value,dict):
        if value.get('type')==name:yield value
        for item in value.values():yield from wires(item,name)
    elif isinstance(value,list):
        for item in value:yield from wires(item,name)


class VoidScriptureTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)

    def game(self,*,mode='normal',mana=10,hand=(CARD,),watch=False,actor=1):
        self.mode=mode
        own=PlayerSetup('mage.hero',hand=hand,deck=('card.40',)*6,board=(WATCH,)if watch else(),mana=mana,max_mana=max(10,mana),mana_cap=max(10,mana))
        other=PlayerSetup('mage.hero',deck=('card.40',)*6,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if actor==1 else(other,own),active_player=actor,seed=652,generation_context=CTX),registry(mode))

    def select(self,g,cid):
        q=g.state.pending_choice;self.choose(g,next(o.id for o in q.options if o.card_id==cid))

    def checked(self,g):return [e for e in g.events if e.kind==CHECKED]
    def child(self,g):return next(v for v in g.state.cast_history if v.card_id!=CARD)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')});return s

    def test_complete_original_shadow_spell_and_two_primary_faces(self):
        d=native.load_batch();self.assertEqual(registry().card(CARD).cost,2);self.assertEqual(registry().card(CARD).spell_school.value,'shadow')
        self.assertEqual(len(d['official_observations']),2);self.assertFalse(d['new_standard_roots']or d['formal_pool_complete']or d['cn_calibrated'])

    def test_original_current_class_menu_and_separate_copy_leave_original_hand(self):
        g=self.game();source=self.play(g,CARD);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{A,B,Z});self.portable(g)
        self.select(g,A);original=self.entity(g,A);copy=g.state.entities[self.child(g).source_id]
        self.assertNotEqual(original.id,copy.id);self.assertEqual(copy.origin_entity_id,original.id);self.assertEqual(copy.zone,Zone.GRAVEYARD)
        self.assertEqual(self.child(g).caster_id,source);self.assertEqual(self.child(g).target_id,g.state.players[2].hero_id)
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage,2);self.portable(g)

    def test_exact_remaining_mana_boundary_and_insufficient_leave_card(self):
        for mana,casts in((6,1),(7,2)):
            with self.subTest(mana=mana):
                g=self.game(mana=mana);self.play(g,CARD);self.select(g,B)
                self.assertEqual(len(g.state.cast_history),casts);self.assertEqual(g.state.players[1].mana,mana-2);self.assertEqual(self.entity(g,B).zone,Zone.HAND)

    def test_zero_mana_still_casts_zero_cost_untargeted_copy(self):
        g=self.game(mana=2);self.play(g,CARD);self.select(g,Z)
        self.assertEqual(g.state.players[1].mana,0);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3);self.portable(g)

    def test_actual_post_delivery_mana_gain_and_spend(self):
        for mode,mana,casts in(('gain',4,2),('spend',7,1)):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,mana=mana,watch=True);self.play(g,CARD);self.select(g,B);self.assertEqual(len(g.state.cast_history),casts);self.portable(g)

    def test_current_discounted_material_is_copied_for_actual_payload(self):
        g=self.game(mode='native_copy',mana=3,watch=True);self.play(g,CARD);self.select(g,B)
        original=self.entity(g,B);copy=g.state.entities[self.child(g).source_id]
        self.assertEqual((local_cost(original)[0],local_cost(copy)[0]),(1,1));self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage,2)
        self.assertEqual(g.state.players[1].mana,1);self.portable(g)

    def test_full_external_quote_does_not_consume_next_spell_modifier(self):
        g=self.game(mode='external_discount',mana=3,watch=True);self.play(g,CARD);self.select(g,B)
        self.assertEqual(len(g.state.cast_history),2);self.assertEqual(len(g.state.players[1].cost_modifiers),1)
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining,1);self.assertEqual(g.state.players[1].mana,1);self.portable(g)

    def test_friendly_only_target_uses_existing_no_enemy_fallback(self):
        g=self.game(mode='friendly');self.play(g,CARD);self.select(g,FRIEND)
        self.assertEqual(self.child(g).target_id,g.state.players[1].hero_id);self.assertEqual(g.state.entities[g.state.players[1].hero_id].damage,2);self.portable(g)

    def test_automatic_discovery_uses_existing_random_choice(self):
        g=self.game(mode='inner_discover');self.play(g,CARD);self.select(g,INNER)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),2);self.assertEqual(self.entity(g,Z).zone,Zone.HAND);self.portable(g)

    def test_nested_observer_discovery_cannot_replace_original_selection(self):
        g=self.game(mode='nested',watch=True);self.play(g,CARD);self.select(g,A);self.select(g,Z)
        self.assertEqual(self.child(g).card_id,A);self.assertEqual(len(self.checked(g)),1);self.portable(g)

    def test_lost_transformed_and_reacquired_recipients_use_original_printed_policy(self):
        for mode in('transform','cycle','leave'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,mana=3,watch=True);self.play(g,CARD);self.select(g,B)
                self.assertEqual(len(g.state.cast_history),1);self.assertIsNone(dict(self.checked(g)[0].data)['material']);self.portable(g)

    def test_full_hand_burn_can_still_cast_printed_copy_without_new_hand_slot(self):
        g=self.game(mode='burn',hand=(CARD,)+('card.1',)*9,watch=True);self.play(g,CARD);self.select(g,B)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.cast_history),2)
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1);self.assertFalse(any(g.state.entities[i].card_id==B for i in g.state.players[1].hand));self.portable(g)

    def test_source_return_does_not_cancel_accepted_original_followup(self):
        g=self.game(mode='return_source',watch=True);source=self.play(g,CARD);self.select(g,A)
        self.assertIn(source,g.state.players[1].hand);self.assertEqual(self.child(g).caster_id,source);self.portable(g)

    def test_delivery_completion_and_cast_waits_restore_independently(self):
        for mode in('delivery_wait','completed_wait','cast_wait'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,watch=True);self.play(g,CARD);self.select(g,A)
                self.assertIsNotNone(g.state.pending_choice);r=self.portable(g);self.choose(g);self.choose(r)
                self.assertEqual(g.snapshot(),r.snapshot());self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_failure_after_random_reaction_rolls_back_wait_choice_and_rng(self):
        g=self.game(mode='delivery_wait',watch=True);self.play(g,CARD);self.select(g,A);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g)

    def test_payload_and_selection_failures_roll_back_original_discovery_choice(self):
        for mode in('body_fail','completed_fail'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,watch=True);self.play(g,CARD);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.select(g,A)
                self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_empty_domain_has_no_selection_or_fabricated_copy(self):
        g=self.game(mode='empty');self.play(g,CARD);self.assertEqual(len(g.state.cast_history),1);self.assertFalse(self.checked(g));self.portable(g)

    def test_unknown_eligible_spell_is_not_pruned(self):
        g=self.game(mode='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),before)

    def test_second_actor_keeps_original_player_and_enemy(self):
        g=self.game(actor=2);self.play(g,CARD,player=2);self.select(g,A)
        self.assertEqual((self.child(g).player_id,self.child(g).target_id),(2,g.state.players[1].hero_id));self.portable(g)

    def test_automatic_root_uses_original_automatic_discovery_and_copy(self):
        g=self.game(hand=(AUTO,));self.play(g,AUTO)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.checked(g)),1)
        root=next(c for c in g.state.cast_history if c.card_id==CARD);self.assertEqual(root.origin,'effect');self.portable(g)

    def test_lethal_copy_uses_normal_terminal_interruption_and_restoration(self):
        g=self.game(mode='lethal');self.play(g,CARD);self.select(g,A)
        self.assertEqual(g.state.winner,1);self.assertNotEqual(g.state.status,'playing');self.portable(g)

    def test_finite_spec_rejects_unsupported_extra_rewards_and_routes(self):
        spec=DiscoverFromPool(1,'constructed.cards',QUERY,source_id=1,cast_affordable_copy=True)
        for changes in({'discoveries':2},{'cost':CostSpec(delta=-1)},{'destination':'deck'},{'swap_costs':True},{'count':2}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(spec,**changes)

    def test_clipped_and_changed_original_followup_rejected_after_rehash(self):
        g=self.game(mode='delivery_wait',watch=True);self.play(g,CARD);self.select(g,A);saved=g.snapshot()
        name=CastAffordableDiscoveredSpell.__module__+'.'+CastAffordableDiscoveredSpell.__name__
        for change in('cast','clip'):
            with self.subTest(change=change):
                s=json.loads(json.dumps(saved));frame=s['resolution_frame']['fields']
                matches=list(wires([frame['prefix'],frame['continuation']],name));self.assertEqual(len(matches),1)
                if change=='cast':matches[0]['fields']['cast_id']=999
                else:
                    for key in('prefix','continuation'):
                        queue=frame[key]['tuple'];queue[:]=[v for v in queue if not list(wires(v,name))]
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry('delivery_wait','tamper'))

    def test_real_host_secret_copy_preserves_hidden_opponent_information(self):
        f=host();context=GenerationContext(f.context.target_id+'.k652-secret',f.context.mode);r=f.registry
        r.register_pool(PoolDefinition('constructed.cards','k652.real-secret',context.target_id,context.mode,(PoolMember('EX1_287'),),complete=True))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CARD,),mana=10,max_mana=10),PlayerSetup('HERO_08',mana=10,max_mana=10)),seed=652,generation_context=context),r)
        self.play(g,CARD);self.select(g,'EX1_287');self.assertEqual(len(g.state.players[1].secrets),1);self.assertEqual(self.entity(g,'EX1_287').zone,Zone.HAND)
        opponent=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        self.assertNotIn('EX1_287',opponent)
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in('discovered_spell_copy','CastAffordableDiscoveredSpell','accepted_event','rng_state'):
                self.assertNotIn(key,view)
        Game.from_snapshot(g.snapshot(),r);self.assertEqual(g.clone().snapshot(),g.snapshot())
