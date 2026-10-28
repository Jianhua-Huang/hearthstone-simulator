"""Original hand-spell scope, return/cost, random replacement and recovery."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import original_spell_secret_effects as native
from hs_sim.cards.death_hand_return_secrets import KODO,register_death_hand_return_secrets
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.countered_spell_secrets import CounterReturnSpell,CounterReplaceSpell,pending_spell
from hs_sim.engine.costs import local_cost
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,GainArmor,
    InvokeBehavior,RandomDamage,RequestChoice)
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,DamageKind,Keyword,RewindSpec,SecretSpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.native_spell_values import bound_value
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

ICE,YOGG=native.LEAVES
P='k639.';CTX=GenerationContext('k639-explicit-fixture-domain','experimental')
ORIGINAL,ONE,TWO,BEAM,RETRY,AUTO,CHEAP,FILL,WATCH,FAIL,STEAL,KILL,TRANSFORM=(P+x for x in
    ('original','one','two','beam','retry','auto','cheap','fill','watch','fail','steal','kill','transform'))
GOOD1,GOOD3,TARGET,UNKNOWN=(P+x for x in ('good1','good3','target','unknown'))
PAUSE_ICE,PAUSE_YOGG=(P+x for x in ('pause_ice','pause_yogg'))


def armor(g,p=2):return g.state.entities[g.state.players[p].hero_id].armor


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_original_spell_secret_effects(r);register_death_hand_return_secrets(r)
    def fail(c):raise ResolutionError('K639 deliberate original-spell rollback')
    r.register_behavior(FAIL,fail)
    def prompt(c):
        recipient=c.player_id if mode=='fill_owner' else 3-c.player_id
        return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fill','Fill destination hand',(AddToHand(recipient,FILL,c.source_id),)*10),
            ChoiceOption('fail','Fail',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id)
    def watch(c):
        if mode in ('reveal','fill_owner'):
            e=c.state.entities.get(c.event.source_id)
            return (prompt(c),) if e is not None and e.card_id in native.LEAVES else ()
        if mode in ('arrival','observe'):
            entry=c.state.hand_entries[dict(c.event.data)['hand_entry_id']-1]
            if entry.reason!='return' or c.state.entities[entry.entity_id].kind!=CardType.SPELL:return ()
            return (GainArmor(c.player_id,local_cost(c.state.entities[entry.entity_id])[0]),) if mode=='observe' else (prompt(c),)
        if mode=='cast':
            cast=next((x for x in reversed(c.state.cast_history)if x.source_id==c.event.source_id),None)
            return (prompt(c),) if cast is not None and cast.origin=='effect' else ()
        if mode=='fail':return (RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        return ()
    r.register_behavior(P+'watch',watch)
    event='secret_revealed' if mode in ('reveal','fill_owner') else 'hand_card_entered' if mode in ('arrival','observe') else 'spell_cast_started' if mode=='cast' else 'spell_countered'
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,attack=0,health=20,triggers=(TriggerSpec(event,P+'watch'),),metadata=metadata(tribes=())))
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,attack=1,health=3,metadata=metadata(tribes=())))
    def cheap(c):
        card=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in (ORIGINAL,BEAM))
        return (ModifyStoredCost(CardReference.capture(card),CostSpec(set_to=1),c.source_id),)
    def transform(c):
        card=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==FILL)
        return (TransformStoredCard(CardReference.capture(card),ORIGINAL,c.source_id),)
    bodies={ORIGINAL:lambda c:(GainArmor(c.player_id,99),),ONE:lambda c:(GainArmor(c.player_id,99),),
        TWO:lambda c:(GainArmor(c.player_id,99),),RETRY:lambda c:(GainArmor(c.player_id,99),),
        BEAM:lambda c:(Damage(c.target_id,9,c.source_id,DamageKind.SPELL),),
        GOOD1:lambda c:(GainArmor(c.player_id,3),),GOOD3:lambda c:(GainArmor(c.player_id,5),),
        TARGET:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),CHEAP:cheap,
        STEAL:lambda c:(ChangeControl(c.target_id,c.player_id),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),TRANSFORM:transform}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);cost=1 if cid in (ONE,GOOD1) else 2 if cid==TWO else 3 if cid in (ORIGINAL,RETRY,BEAM,GOOD3,TARGET) else 0
        extra={}
        if cid in (BEAM,TARGET):extra['targeting']=TargetSpec(kinds=(CardType.MINION,CardType.HERO),zones=(Zone.BOARD,Zone.HERO))
        if cid in (STEAL,KILL):extra['targeting']=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,))
        if cid==RETRY:extra.update(keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        if cid==TRANSFORM:r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=0,health=3,battlecry=cid,metadata=metadata(tribes=())))
        else:r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,metadata=metadata(tribes=()),**extra))
    # A no-target candidate remains in the full fixture domain and fizzles normally.
    r.register_behavior(P+'no_target',lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),))
    r.register_card(CardDefinition(P+'no_target',P+'no_target',CardType.SPELL,cost=2,on_play=P+'no_target',
        targeting=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,)),metadata=metadata(tribes=())))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,ORIGINAL,c.source_id),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,attack=0,health=2,battlecry=AUTO,metadata=metadata(tribes=())))
    def paused(c,kind):
        w,p,e=pending_spell(c.state,c.event,c.player_id)
        return (prompt(c),kind(w.id,p.id,SourceAllocationFact.capture(c.state,e),SourceAllocationFact.capture(c.state,c.source)))
    for cid,kind in ((PAUSE_ICE,CounterReturnSpell),(PAUSE_YOGG,CounterReplaceSpell)):
        r.register_behavior(cid,lambda c,kind=kind:paused(c,kind))
        r.register_secret_condition(cid,lambda c:pending_spell(c.state,c.event,c.player_id)is not None)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,keywords=(Keyword.SECRET,),secret=SecretSpec(cid,('card_committed',),cid,cid),metadata=metadata(tribes=())))
    members=(ORIGINAL,)if mode=='self' else(TARGET,)if mode=='target'else(P+'no_target',)if mode=='no_target'else(GOOD1,GOOD3)
    for cid in members:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if mode=='unknown':
        r.register_pool_card(PoolCard.from_definition(CardDefinition(UNKNOWN,UNKNOWN,CardType.SPELL,cost=3,metadata=metadata(tribes=()))));members=(*members,UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards','k639-complete-explicit-fixture-v1',CTX.target_id,CTX.mode,tuple(PoolMember(c)for c in members),complete=True))
    r.validate();r.freeze();return r


@lru_cache(None)
def host_format():return build_cn37_local_pool_format()


def host():return host_format().registry


class OriginalSpellSecretTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand=(),*,other_hand=(ORIGINAL,),board=(),enemy=(),mode='normal',player=1,hand_cap=None,seed=639):
        self.mode=mode;ps=[PlayerSetup('mage.hero',hand=hand,board=board,deck=(FILL,)*15,mana=60,max_mana=60,mana_cap=60),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=(FILL,)*15,mana=60,max_mana=60,mana_cap=60,hand_cap=hand_cap)]
        if player==2:ps.reverse()
        return Game.from_scenario(Scenario(tuple(ps),active_player=player,seed=seed,generation_context=CTX),registry(mode))
    def arm(self,g,cid,p=1):eid=self.play(g,cid,player=p);g.apply(EndTurn(p));return eid
    def secrets(self,g,p=1):return [g.state.entities[i].card_id for i in g.state.players[p].secrets]
    def cast(self,g,cid=ORIGINAL,p=2,target=None):return self.play(g,cid,target,player=p)
    def settle(self,g):
        while g.state.pending_choice:self.choose(g)
    def wait_roundtrip(self,g):
        saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.settle(g);self.settle(other)
        self.assertEqual(g.snapshot(),other.snapshot())
    def public_fields(self,value):
        found=[]
        if isinstance(value,dict):
            if isinstance(value.get('fields'),dict)and set(value['fields'])=={'window_id','play_id','card','source'}:found.append(value['fields'])
            for x in value.values():found+=self.public_fields(x)
        elif isinstance(value,list):
            for x in value:found+=self.public_fields(x)
        return found
    def reject(self,saved):
        saved['events_hash']=canonical_hash(saved['events']);saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(self.mode,'independent-reader'))

    def test_three_complete_rows_four_faces_and_readonly_tax_evidence(self):
        d=native.load_batch();self.assertEqual((len(d['dependencies']),len(d['evidence_only']),len(d['official_observations'])),(2,1,4))
        self.assertNotIn('AV_226e',registry().cards);self.assertFalse(d['source_scope_bound']);self.assertFalse(d['cn_calibrated'])

    def test_two_real_paid_hidden_secrets_reject_duplicate_before_payment(self):
        for cid in native.LEAVES:
            g=self.game((cid,cid));mana=g.state.players[1].mana;self.play(g,cid)
            self.assertEqual(g.state.players[1].mana,mana-registry().card(cid).cost);saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved);self.assertNotIn(cid,json.dumps(g.for_player(2).observe()))

    def test_ice_returns_same_original_spell_with_tax_and_no_mana_refund(self):
        g=self.game((ICE,));self.arm(g,ICE);mana=g.state.players[2].mana;eid=self.cast(g)
        e=g.state.entities[eid];self.assertEqual((e.zone,local_cost(e)[0]),(Zone.HAND,4));self.assertEqual(g.state.players[2].mana,mana-3)
        self.assertEqual(armor(g),0);self.assertTrue(g.state.play_history[-1].countered);self.assertTrue(g.state.play_history[-1].completed)
        self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertFalse(g.state.death_history)

    def test_ice_clears_previous_hand_discount_before_adding_one(self):
        g=self.game((ICE,),other_hand=(CHEAP,ORIGINAL));g.apply(EndTurn(1));self.cast(g,CHEAP)
        self.assertEqual(local_cost(self.entity(g,ORIGINAL,2))[0],1);g.apply(EndTurn(2));self.arm(g,ICE)
        mana=g.state.players[2].mana;eid=self.cast(g)
        self.assertEqual(g.state.players[2].mana,mana-1);self.assertEqual(local_cost(g.state.entities[eid])[0],4)

    def test_repeated_ice_traps_reset_previous_tax_and_pay_each_original_price(self):
        g=self.game((ICE,ICE));self.arm(g,ICE);eid=self.cast(g);self.assertEqual(local_cost(g.state.entities[eid])[0],4)
        g.apply(EndTurn(2));self.arm(g,ICE);mana=g.state.players[2].mana;self.cast(g)
        self.assertEqual(g.state.players[2].mana,mana-4);self.assertEqual(local_cost(g.state.entities[eid])[0],4)

    def test_hand_arrival_observer_already_sees_tax(self):
        g=self.game((ICE,),board=(WATCH,),mode='observe');self.arm(g,ICE);self.cast(g)
        self.assertEqual(armor(g,1),4)

    def test_full_hand_after_reveal_burns_original_without_extra_death(self):
        g=self.game((ICE,),board=(WATCH,),mode='reveal');self.arm(g,ICE);eid=self.cast(g);epoch=g.state.entities[eid].zone_epoch
        self.choose(g,'fill');self.settle(g);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertGreater(g.state.entities[eid].zone_epoch,epoch);self.assertFalse(g.state.death_history);self.assertEqual(armor(g),0)

    def test_return_capacity_uses_recipient_override(self):
        g=self.game((ICE,),board=(WATCH,),mode='reveal',hand_cap=2);self.arm(g,ICE);eid=self.cast(g)
        self.choose(g,'fill');self.settle(g);self.assertEqual(len(g.state.players[2].hand),2);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)

    def test_yogg_casts_for_original_caster_and_charges_only_original_spell(self):
        g=self.game((YOGG,));self.arm(g,YOGG);mana=g.state.players[2].mana;eid=self.cast(g)
        self.assertEqual((armor(g),armor(g,1)),(5,0));self.assertEqual(g.state.players[2].mana,mana-3)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(len([c for c in g.state.cast_history if c.player_id==2]),2)
        self.assertEqual(sum(c.origin=='effect'for c in g.state.cast_history),1);self.assertTrue(g.state.play_history[-1].countered)

    def test_yogg_uses_original_submitted_discount_instead_of_printed_cost(self):
        g=self.game((YOGG,),other_hand=(CHEAP,ORIGINAL));g.apply(EndTurn(1));self.cast(g,CHEAP)
        g.apply(EndTurn(2));self.arm(g,YOGG);self.cast(g)
        replacement=next(c for c in g.state.cast_history if c.origin=='effect')
        self.assertEqual(replacement.card_id,GOOD1);self.assertEqual(armor(g),3)

    def test_yogg_rechooses_random_targets_instead_of_preserving_original_target(self):
        targets=set()
        for seed in (637,638,639,640):
            g=self.game((YOGG,),other_hand=(BEAM,),board=(FILL,),enemy=(FILL,),mode='target',seed=seed)
            self.arm(g,YOGG);original=g.state.players[1].hero_id;self.cast(g,BEAM,target=original)
            replacement=next(c for c in g.state.cast_history if c.origin=='effect');targets.add(replacement.target_id)
        self.assertGreater(len(targets),1);self.assertTrue(any(t!=original for t in targets))

    def test_yogg_keeps_same_spell_eligible_in_complete_fixture_domain(self):
        g=self.game((YOGG,),mode='self');self.arm(g,YOGG);eid=self.cast(g)
        self.assertEqual(armor(g),99);effect=next(c for c in g.state.cast_history if c.origin=='effect')
        self.assertEqual(effect.card_id,ORIGINAL);self.assertNotEqual(effect.source_id,eid)

    def test_yogg_no_legal_target_fizzles_without_dropping_candidate_or_reroll(self):
        g=self.game((YOGG,),other_hand=(TWO,),mode='no_target');self.arm(g,YOGG);self.cast(g,TWO)
        effect=next(c for c in g.state.cast_history if c.origin=='effect');self.assertEqual((effect.card_id,effect.failure),(P+'no_target','no_target'))
        self.assertEqual(armor(g),0);self.assertEqual(len([c for c in g.state.cast_history if c.player_id==2]),2)

    def test_yogg_unknown_complete_candidate_rolls_back_without_coverage_filter(self):
        g=self.game((YOGG,),mode='unknown');self.arm(g,YOGG);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g)
        self.assertEqual(g.snapshot(),saved);self.assertIn(YOGG,self.secrets(g))

    def test_owner_turn_and_minion_commit_keep_secret(self):
        for cid in native.LEAVES:
            g=self.game((cid,ORIGINAL),other_hand=(AUTO,));self.play(g,cid);self.play(g,ORIGINAL);self.assertIn(cid,self.secrets(g))
            g.apply(EndTurn(1));self.cast(g,AUTO);self.assertIn(cid,self.secrets(g));self.assertEqual(armor(g),99)

    def test_automatic_cast_does_not_open_an_opponent_hand_counter_window(self):
        for cid in native.LEAVES:
            g=self.game((cid,),other_hand=(AUTO,));self.arm(g,cid);self.cast(g,AUTO)
            self.assertEqual(armor(g),99);self.assertIn(cid,self.secrets(g))

    def test_first_counter_keeps_other_secret_and_replacement_is_not_a_new_hand_play(self):
        for first,second in ((ICE,YOGG),(YOGG,ICE)):
            g=self.game((first,second));self.play(g,first);self.arm(g,second);self.cast(g)
            self.assertEqual(self.secrets(g),[second]);self.assertEqual(sum(p.player_id==2 and p.kind==CardType.SPELL for p in g.state.play_history),1)

    def test_reveal_wait_restores_original_window_then_continues_each_native(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(WATCH,),mode='reveal');self.arm(g,cid);self.cast(g)
            self.assertIsNotNone(g.state.pending_choice);self.wait_roundtrip(g)

    def test_actual_return_arrival_wait_restores_countered_hand_source(self):
        g=self.game((ICE,),board=(WATCH,),mode='arrival');self.arm(g,ICE);eid=self.cast(g)
        self.assertEqual(g.state.entities[eid].zone,Zone.HAND);self.wait_roundtrip(g);self.assertEqual(local_cost(g.state.entities[eid])[0],4)

    def test_random_replacement_wait_restores_original_pending_hand_spell(self):
        g=self.game((YOGG,),board=(WATCH,),mode='cast');self.arm(g,YOGG);self.cast(g)
        self.assertIsNotNone(g.state.pending_choice);self.wait_roundtrip(g);self.assertEqual(armor(g),5)

    def test_queued_typed_operations_restore_clone_replay_and_continue(self):
        for cid in (PAUSE_ICE,PAUSE_YOGG):
            g=self.game((cid,));self.arm(g,cid);self.cast(g)
            self.assertTrue(any(type(x)in(CounterReturnSpell,CounterReplaceSpell)for x in g._frame.continuation))
            self.wait_roundtrip(g)

    def test_pending_typed_effect_rejects_wrong_play_window_and_original_residence(self):
        for cid in (PAUSE_ICE,PAUSE_YOGG):
            g=self.game((cid,));self.arm(g,cid);self.cast(g);saved=g.snapshot()
            for key,value in (('play_id',1),('play_id',999),('window_id',999)):
                bad=json.loads(json.dumps(saved));self.public_fields(bad)[0][key]=value;self.reject(bad)
            for key in ('zone_epoch','next_entity_id'):
                bad=json.loads(json.dumps(saved));self.public_fields(bad)[0]['card']['fields'][key]+=100;self.reject(bad)

    def test_public_effect_shapes_reject_bool_and_missing_original_facts(self):
        g=self.game((PAUSE_ICE,));self.arm(g,PAUSE_ICE);self.cast(g)
        work=next(x for x in g._frame.continuation if type(x)is CounterReturnSpell)
        for changes in ({'window_id':True},{'play_id':0},{'card':None},{'source':None},{'source':replace(work.source,controller=2)}):
            with self.assertRaises(ValueError):replace(work,**changes)

    def test_failed_counter_reaction_rolls_back_secret_payment_return_cast_and_rng(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(WATCH,),mode='fail');self.arm(g,cid);saved=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'K639 deliberate'):self.cast(g)
            self.assertEqual(g.snapshot(),saved)

    def test_countered_rewind_keeps_existing_no_offer_policy_without_double_effect(self):
        for cid in native.LEAVES:
            g=self.game((cid,),other_hand=(RETRY,));self.arm(g,cid);eid=self.cast(g,RETRY)
            self.assertIsNone(g.state.pending_choice);self.assertEqual(sum(x.card_id==RETRY for x in g.state.play_history),1)
            if cid==ICE:self.assertEqual((g.state.entities[eid].zone,local_cost(g.state.entities[eid])[0]),(Zone.HAND,4))
            else:self.assertEqual(sum(c.origin=='effect'for c in g.state.cast_history),1)
            self.portable(g)

    def test_reverse_actor_and_private_original_materials(self):
        for cid in native.LEAVES:
            g=self.game((cid,),player=2);self.arm(g,cid,2);self.cast(g,p=1)
            for player in (1,2):
                text=json.dumps((g.for_player(player).observe(),g.player_events(player)))
                for key in ('CounterReturnSpell','CounterReplaceSpell','SourceAllocationFact','resolution_frame','rng_state','submitted_cost','quote_input','next_entity_id'):self.assertNotIn('"'+key+'"',text)

    def test_original_transformed_hand_residence_returns_to_physical_owner(self):
        g=self.game((STEAL,KODO,TRANSFORM),other_hand=(KILL,ICE),enemy=(FILL,))
        eid=self.entity(g,FILL,2,'board').id;self.play(g,STEAL,eid);self.arm(g,KODO)
        self.cast(g,KILL,target=eid);self.play(g,ICE,player=2);g.apply(EndTurn(2));self.play(g,TRANSFORM)
        self.assertEqual((g.state.entities[eid].owner,g.state.entities[eid].controller),(2,1))
        self.assertGreater(g.state.entities[eid].zone_epoch,0);self.play(g,ORIGINAL)
        self.assertEqual((g.state.entities[eid].zone,g.state.entities[eid].owner,g.state.entities[eid].controller,local_cost(g.state.entities[eid])[0]),(Zone.HAND,2,2,4))
        self.assertEqual(g.state.play_history[-1].player_id,1);self.assertTrue(g.state.play_history[-1].countered)
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry(self.mode,'independent-reader')).snapshot(),saved)
        bad=json.loads(json.dumps(saved));bad['state']['death_history'][0]['copy_source']=None;self.reject(bad)

    def test_complete_host_real_fireball_returns_original_with_cost_five(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(ICE,),deck=('CS2_120',),mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=('CS2_029',),deck=('CS2_120',),mana=10,max_mana=10)),seed=639,generation_context=host_format().context),host())
        self.arm(g,ICE);eid=self.cast(g,'CS2_029',target=g.state.players[1].hero_id)
        self.assertEqual((g.state.entities[eid].zone,local_cost(g.state.entities[eid])[0]),(Zone.HAND,5));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,build_cn37_local_pool_format().registry).snapshot(),saved)

    def test_complete_host_coin_uses_full_standard_same_cost_source(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(YOGG,),board=('CS2_120',),deck=('CS2_120',),mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=('GAME_005',),deck=('CS2_120',),mana=10,max_mana=10)),seed=639,generation_context=host_format().context),host())
        self.arm(g,YOGG);self.cast(g,'GAME_005');self.assertTrue(g.state.play_history[-1].countered)
        replacement=next(c for c in g.state.cast_history if c.origin=='effect');self.assertEqual(host().card(replacement.card_id).cost,0)
        self.assertNotIn('WON_040',host().cards)

    def test_unbound_production_registry_does_not_guess_generation_context(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(YOGG,),deck=('CS2_120',),mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=('GAME_005',),deck=('CS2_120',),mana=10,max_mana=10)),seed=639),host())
        self.arm(g,YOGG);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'explicit context'):self.cast(g,'GAME_005')
        self.assertEqual(g.snapshot(),saved)

    def test_complete_host_growing_ignite_keeps_its_intrinsic_value_after_return(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('SW_110',),mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=(ICE,),deck=('CS2_120',),mana=10,max_mana=10)),seed=639,generation_context=host_format().context),host())
        self.play(g,'SW_110',g.state.players[2].hero_id);g.apply(EndTurn(1));self.play(g,ICE,player=2);g.apply(EndTurn(2))
        e=self.entity(g,'SW_110');value=bound_value(e);self.assertIsNotNone(value);self.assertEqual(value.amount,3);eid=self.play(g,'SW_110',g.state.players[2].hero_id)
        self.assertEqual((g.state.entities[eid].zone,local_cost(g.state.entities[eid])[0]),(Zone.HAND,3));self.assertEqual(bound_value(g.state.entities[eid]),value)
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,build_cn37_local_pool_format().registry).snapshot(),saved)


if __name__=='__main__':unittest.main()
