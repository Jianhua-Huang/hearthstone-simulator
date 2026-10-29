"""Actual closed-own CAST pricing, three fresh pulses and original copy groups."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_warrior_nature_source as native
from hs_sim.cards.simple_followup_p89_cards import WO,NATURE_PAST_POOL,QUERIES,WARRIOR_NATURE_PAST_POOL
from hs_sim.engine import EndTurn,Game,PlayCard,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_cost,quote_generated_cost,capture_generated_quote_fact
from hs_sim.engine.effects import (ChoiceOption,Damage,DamageBatch,GainArmor,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Summon,Transform)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.intrinsic_costs import capture_intrinsic_stage
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CostSpec,PreviousOwnerSpellCastMatch,SpellSchool,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import PoolMember,resolve_candidates
from hs_sim.engine.previous_turn_spell_costs import validate_prefix
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest

P='k667.'
A,B,C,RATTLE,TOKEN,FIRE,NONE,NEEDS,HIGH,WOUND,WOUNDALL,LOCAL,AUTO,BAD,DIRECT,COUNTER,WDAMAGE,WSUMMON,FAIL=(P+x for x in
    ('a','b','c','rattle','token','fire','unschooled','enemy-target','high','wound','woundall','local','automatic','failed-automatic','direct','counter','damage-watch','summon-watch','fault'))
AFTER,BLOOD=native.ROOTS


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();native.register_past_warrior_nature_cards(r)
    for cid,attack,health in ((A,2,8),(B,3,6),(C,1,10),(TOKEN,1,4)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=attack,health=health,metadata=metadata()))
    r.register_behavior(RATTLE,lambda c:(Summon(c.player_id,TOKEN),))
    r.register_card(CardDefinition(RATTLE,RATTLE,CardType.MINION,health=1,deathrattle=RATTLE,metadata=metadata()))
    r.register_behavior(FIRE,lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(NONE,lambda c:())
    r.register_behavior(NEEDS,lambda c:())
    r.register_behavior(HIGH,lambda c:())
    r.register_behavior(WOUND,lambda c:(Damage(c.target_id,2,c.source_id),))
    r.register_behavior(WOUNDALL,lambda c:(DamageBatch(tuple(Damage(eid,1,c.source_id)for eid in c.state.players[c.player_id].board)),))
    r.register_behavior(LOCAL,lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[next(eid for eid in c.state.players[c.player_id].hand
        if c.state.entities[eid].card_id==AFTER)]),CostSpec(delta=-1),c.source_id),))
    for cid,school,cost,target in ((FIRE,SpellSchool.FIRE,0,None),(NONE,None,0,None),(NEEDS,SpellSchool.ARCANE,0,
            TargetSpec(relation='enemy',zones=(Zone.BOARD,),kinds=(CardType.MINION,))),
            (HIGH,None,8,None),(WOUND,None,0,TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))),
            (WOUNDALL,None,0,None),(LOCAL,None,0,None)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,spell_school=school,targeting=target,metadata=metadata(collectible=False)))
    for cid,body in ((AUTO,lambda c:(CastSpell(c.player_id,FIRE,c.source_id),)),
            (BAD,lambda c:(CastSpell(c.player_id,NEEDS,c.source_id),)),
            (DIRECT,lambda c:(InvokeBehavior(FIRE,c.source_id,c.player_id),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,health=4,battlecry=cid,metadata=metadata(collectible=False)))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].kind==CardType.SPELL else())
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=6,triggers=(TriggerSpec('card_committed',COUNTER),),metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K667 deliberate rollback')))
    def watch(c,kind):
        if kind=='damage':
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id!=AFTER:return()
        options=[ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))]
        if kind=='summon':
            target=next((eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id==B),None)
            if target is not None:
                options.extend((ChoiceOption('transform','Transform original remaining target',(Transform(target,C),)),
                    ChoiceOption('depart','Return original remaining target',(ReturnToHand(target),))))
        return(RequestChoice(c.player_id,tuple(options),c.source_id),)
    for cid,kind,event in ((WDAMAGE,'damage','damage_dealt'),(WSUMMON,'summon','minion_summoned')):
        r.register_behavior(cid,lambda c,kind=kind:watch(c,kind))
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,triggers=(TriggerSpec(event,cid),),metadata=metadata(collectible=False)))
    r.validate();return r


class WarriorNatureSourceTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),other_hand=(),deck=('card.1',)*15,watch=None):
        self.mode='small';board=board+((WDAMAGE if watch=='damage'else WSUMMON,)if watch else())
        return Game.from_scenario(Scenario((PlayerSetup('warrior.hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('mage.hero',hand=other_hand,board=enemy,deck=('card.2',)*15,mana=10,max_mana=10)),seed=667),fixture())

    def actual(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*20
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=('CORE_EX1_169',),board=(WO,),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10)),seed=667,generation_context=h.context),h.registry)

    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def price(self,g):return quote_cost(g.state,g.registry,self.entity(g,AFTER)).amount
    def match(self,g):return capture_intrinsic_stage(g.state,g.registry,1,AFTER,4).condition_facts[0]
    def ids(self,g,player=1):return[g.state.entities[eid].card_id for eid in g.state.players[player].board]
    def finish(self,g):
        for _ in range(40):
            q=g.state.pending_choice
            if q is None:return
            self.choose(g,'continue'if any(o.id=='continue'for o in q.options)else q.options[0].id)
        self.fail('Unbounded ordinary checkpoint continuation')

    def test_full_raw_native_existing_shared_face_and_eight_primary_faces(self):
        d=native.load_batch();h=host();native.checked_native(h.registry,d)
        self.assertEqual((len(d['cards']),len(d['existing_dependencies']),len(d['official_observations'])),(2,2,8))
        for row in d['cards']+d['existing_dependencies']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(canonical_digest(asdict(h.registry.card(row['record']['id']))),row['definition_sha256'])
        self.assertEqual(h.registry.card(BLOOD).cost,4);self.assertIn('Summon',d['cards'][1]['record']['text_en'])
        self.assertFalse(d['new_standard_roots']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_separate_complete_three_ordered_view_keeps_old_95_container(self):
        h=host();d=native.load_batch();p=h.registry.pool(WARRIOR_NATURE_PAST_POOL,h.context)
        self.assertEqual(p.members,tuple(PoolMember(cid)for cid in native.MEMBERS))
        values=resolve_candidates(h.registry,h.context,p.id,QUERIES[WO],current_class=CardClass.WARRIOR,source_card_id=WO,exclude_source_by_rule=True)
        self.assertEqual([v.card_id for v in values],d['member_ids']);self.assertEqual([v.weight for v in values],[1]*3)
        self.assertEqual(len(h.registry.pool(NATURE_PAST_POOL,h.context).members),95)

    def test_source_rejects_missing_shared_member_order_weight_or_borrowed_pool(self):
        h=host();p=h.registry.pool(WARRIOR_NATURE_PAST_POOL,h.context)
        class Proxy:
            def __getattr__(self,key):return getattr(h.registry,key)
            def pool(self,*args):return self.changed
        for patch in ({'members':p.members[:-1]},{'members':tuple(reversed(p.members))},
                {'members':(replace(p.members[0],weight=2),)+p.members[1:]},{'version':'borrowed'},{'complete':False}):
            q=Proxy();q.changed=replace(p,**patch)
            with self.assertRaises(TargetValidationError):native.register_scope(q,h.context)

    def test_first_and_same_current_turn_spells_cannot_discount_previous_turn_price(self):
        g=self.game((AFTER,FIRE));self.assertEqual(self.price(g),4);self.play(g,FIRE)
        self.assertEqual(self.price(g),4);f=self.match(g);self.assertIsNone(f.owner_turn);self.assertEqual(f.rows,())

    def test_any_school_and_unschooled_actual_prior_spell_reduce_to_two(self):
        for spell in (FIRE,NONE):
            with self.subTest(spell=spell):
                g=self.game((AFTER,spell));self.play(g,spell);self.cycle(g)
                self.assertEqual(self.price(g),2);f=self.match(g);self.assertIsInstance(f,PreviousOwnerSpellCastMatch)
                self.assertTrue(f.matched);self.assertEqual(len(f.rows),1);self.assertEqual(f.rows[0].card_id,spell)
        self.portable(g)

    def test_actual_automatic_cast_from_minion_counts_without_a_hand_spell_play(self):
        g=self.game((AFTER,AUTO));self.play(g,AUTO);self.assertEqual([p.kind for p in g.state.play_history],[CardType.MINION])
        self.assertEqual(g.state.cast_history[0].origin,'effect');self.cycle(g);self.assertEqual(self.price(g),2)
        self.play(g,AFTER);self.assertEqual(g.state.players[1].mana,8);self.portable(g)

    def test_failed_automatic_cast_and_direct_behavior_are_not_successful_casts(self):
        for helper in (BAD,DIRECT):
            with self.subTest(helper=helper):
                g=self.game((AFTER,helper));self.play(g,helper);self.cycle(g)
                self.assertEqual(self.price(g),4);self.assertFalse(self.match(g).matched)
                if helper==BAD:self.assertEqual(g.state.cast_history[0].failure,'no_target')
                else:self.assertEqual(g.state.cast_history,[])

    def test_countered_original_hand_spell_is_retained_but_not_qualified(self):
        g=self.game((AFTER,FIRE),enemy=(COUNTER,));self.play(g,FIRE);self.cycle(g)
        f=self.match(g);self.assertEqual(self.price(g),4);self.assertFalse(f.matched)
        self.assertEqual((f.rows[0].failure,f.rows[0].payload_started),('countered',False));self.portable(g)

    def test_opponent_previous_turn_cast_does_not_borrow_our_empty_interval(self):
        g=self.game((AFTER,),other_hand=(FIRE,));g.apply(EndTurn(1));self.play(g,FIRE,player=2);g.apply(EndTurn(2))
        self.assertEqual(self.price(g),4);self.assertFalse(self.match(g).matched)

    def test_latest_empty_own_interval_replaces_older_positive_cast_history(self):
        g=self.game((AFTER,FIRE));self.play(g,FIRE);self.cycle(g);self.assertEqual(self.price(g),2)
        self.cycle(g);self.assertEqual(self.price(g),4);f=self.match(g)
        self.assertEqual(f.owner_turn.turn,3);self.assertEqual(len(f.rows),1);self.assertFalse(f.matched);self.portable(g)

    def test_discount_precedes_local_cost_and_actual_three_pulses_pay_only_once(self):
        g=self.game((AFTER,FIRE,LOCAL),board=(A,));self.play(g,FIRE);self.cycle(g);self.play(g,LOCAL)
        self.assertEqual(self.price(g),1);mana=g.state.players[1].mana;self.play(g,AFTER)
        self.assertEqual(g.state.players[1].mana,mana-1);self.assertEqual(self.entity(g,A,zone='board').health,5)
        self.assertEqual(sum(r.card_id==AFTER for r in g.state.cast_history),1);self.portable(g)

    def test_discount_is_used_for_real_legal_payment_with_only_two_mana_left(self):
        g=self.game((AFTER,FIRE,HIGH));self.play(g,FIRE);self.cycle(g);self.play(g,HIGH)
        self.assertEqual(g.state.players[1].mana,2);self.play(g,AFTER);self.assertEqual(g.state.players[1].mana,0)

    def test_generated_quote_uses_same_previous_cast_fact_without_allocating_entities(self):
        g=self.game((AFTER,FIRE));self.play(g,FIRE);self.cycle(g);saved=deepcopy(g.snapshot())
        self.assertEqual(quote_generated_cost(g.state,g.registry,1,AFTER).amount,2)
        fact=capture_generated_quote_fact(g.state,g.registry,1,AFTER)
        self.assertTrue(fact.intrinsic.condition_facts[0].matched);self.assertEqual(g.snapshot(),saved)

    def test_three_actual_spell_batches_damage_both_sides_and_none_of_the_heroes(self):
        g=self.game((AFTER,),board=(A,),enemy=(B,));self.play(g,AFTER)
        self.assertEqual((self.entity(g,A,zone='board').health,self.entity(g,B,2,'board').health),(5,3))
        self.assertEqual(g.state.players[1].mana,6)
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in(1,2)],[30,30]);self.portable(g)

    def test_later_pulses_hit_real_deathrattle_spawn_after_ordinary_checkpoint(self):
        g=self.game((AFTER,),board=(RATTLE,));self.play(g,AFTER)
        self.assertEqual(self.ids(g),[TOKEN]);self.assertEqual(self.entity(g,TOKEN,zone='board').health,2)
        self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_no_minions_has_three_empty_bodies_without_extra_rng(self):
        g=self.game((AFTER,));rng=g.snapshot()['rng_state'];self.play(g,AFTER)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.players[1].mana,6)

    def test_paid_discount_and_new_cost_payload_survive_damage_wait_and_failed_resume(self):
        g=self.game((AFTER,FIRE),board=(A,),watch='damage');self.play(g,FIRE);self.cycle(g);self.play(g,AFTER)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,8)
        self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g);self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(self.entity(g,A,zone='board').health,5);self.portable(g)

    def test_compact_cast_fact_binds_complete_closed_prefix_and_frame_codec(self):
        g=self.game((AFTER,FIRE));self.play(g,FIRE);self.cycle(g);f=self.match(g)
        validate_prefix(f,g.state,g.registry)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);self.assertEqual(codec.decode(codec.encode(f)),f)
        cropped=replace(f,rows=(),matched=False)
        with self.assertRaises(ValueError):validate_prefix(cropped,g.state,g.registry)
        with self.assertRaises(ValueError):replace(f,matched=False)
        with self.assertRaises(ValueError):replace(f,rows=(f.rows[0],f.rows[0]))
        with self.assertRaises(ValueError):replace(f,player_id=2)

    def test_rehashed_saved_price_cannot_rewrite_original_cast_school_or_aggregate(self):
        g=self.game((AFTER,FIRE));self.play(g,FIRE);self.cycle(g);self.play(g,AFTER);saved=g.snapshot()
        def find(value):
            if type(value)is dict:
                if set(value)=={'player_id','boundary','owner_turn','next_entity_id','rows','matched'}and value['rows']:return value
                for v in value.values():
                    got=find(v)
                    if got is not None:return got
            elif type(value)is list:
                for v in value:
                    got=find(v)
                    if got is not None:return got
        for mutation in ('school','matched'):
            s=deepcopy(saved);f=find(s);self.assertIsNotNone(f)
            if mutation=='school':f['rows'][0]['spell_school']='nature'
            else:f['matched']=False
            s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(s,fixture())

    def test_blood_warriors_summons_only_original_damaged_friendly_current_copies(self):
        g=self.game((BLOOD,WOUND,WOUND),board=(A,B),enemy=(C,));a=self.entity(g,A,zone='board').id;c=self.entity(g,C,2,'board').id
        self.play(g,WOUND,a);self.play(g,WOUND,c);before=set(g.state.players[1].board);self.play(g,BLOOD)
        copies=[g.state.entities[i]for i in g.state.players[1].board if i not in before]
        self.assertEqual([e.card_id for e in copies],[A]);self.assertEqual(copies[0].attack,g.state.entities[a].attack)
        self.assertEqual(self.ids(g).count(B),1);self.assertEqual(self.ids(g,2),[C]);self.assertEqual(g.state.players[1].mana,6);self.portable(g)

    def test_blood_group_does_not_recapture_new_damaged_copies(self):
        g=self.game((BLOOD,WOUNDALL),board=(A,B));self.play(g,WOUNDALL);self.play(g,BLOOD)
        self.assertEqual(self.ids(g),[A,B,A,B]);self.portable(g)

    def test_blood_original_residence_copies_current_transformed_face_at_wait(self):
        g=self.game((BLOOD,WOUNDALL),board=(A,B),watch='summon');self.play(g,WOUNDALL);self.play(g,BLOOD)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'transform');self.finish(g)
        self.assertEqual(self.ids(g).count(A),2);self.assertEqual(self.ids(g).count(B),0);self.assertEqual(self.ids(g).count(C),2);self.portable(g)

    def test_blood_original_remaining_target_departure_does_not_rebind_its_copy(self):
        g=self.game((BLOOD,WOUNDALL),board=(A,B),watch='summon');self.play(g,WOUNDALL);self.play(g,BLOOD)
        self.assertIsNotNone(g.state.pending_choice);self.choose(g,'depart');self.finish(g)
        self.assertEqual(self.ids(g).count(A),2);self.assertEqual(self.ids(g).count(B),0)
        self.assertEqual(sum(g.state.entities[eid].card_id==B for eid in g.state.players[1].hand),1);self.portable(g)

    def test_blood_no_damaged_group_or_full_board_has_no_new_allocation_or_rng(self):
        for board,damaged in (((A,B),False),((A,)*7,True)):
            g=self.game((BLOOD,WOUNDALL)if damaged else(BLOOD,),board=board)
            if damaged:self.play(g,WOUNDALL)
            nextid=g.state.next_entity_id;rng=g.snapshot()['rng_state'];self.play(g,BLOOD)
            self.assertEqual(g.state.next_entity_id,nextid);self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.players[1].mana,6)

    def test_real_warrior_wo_discovers_complete_three_then_generated_aftershock_uses_current_price(self):
        g=self.actual();self.play(g,'CORE_EX1_169');q=g.state.pending_choice
        self.assertEqual({o.card_id for o in q.options},set(native.MEMBERS));self.portable(g)
        self.choose(g,next(o.id for o in q.options if o.card_id==AFTER))
        self.assertNotIn(AFTER,json.dumps(g.for_player(2).observe()));mana=g.state.players[1].mana;self.play(g,AFTER)
        self.assertEqual(g.state.players[1].mana,mana-4);self.finish(g);self.portable(g)


if __name__=='__main__':unittest.main()
