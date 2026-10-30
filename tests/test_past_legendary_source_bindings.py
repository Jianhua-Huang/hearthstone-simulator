"""Original sources, real profile bindings and complete-host integration."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_legendary_source_bindings as native
from hs_sim.engine import Game,PlayerSetup,ResolutionError,Scenario,SelectChoice,SnapshotError
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.card_packs import OPENED,STEP,FINISHED
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,DestroyBatch,
    GainArmor,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.infused_battlecries import value
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CostSpec,Keyword,Rarity,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,sample_candidates
from hs_sim.engine.registry import Registry
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

BRIGHT,SNEED,DEN,AVATAR=native.ROOTS;INFUSED=native.INFUSED
A='CORE_CS2_182';UNIT='TRL_348t';ALAKIR='CORE_NEW1_010';FANDRAL='CORE_OG_044'
P='k695.';KILL=P+'kill';DOUBLE=P+'double';HURT=P+'hurt';CURRENT=P+'current';BASE=P+'base'
DISCOUNT=P+'discount';BOUNCE=P+'bounce';HUSH=P+'hush';NATURAL=P+'natural';FILL_TRIGGER=P+'fill_trigger'
POWER=P+'spell_power';FAIL=P+'fail';WATCH=P+'watch';PROGRESS_WATCH=P+'progress_watch'
DAMAGE_WATCH=P+'damage_watch';SUMMON_WATCH=P+'summon_watch';CREATE_WATCH=P+'create_watch'
PACK_UNIT,PACK_SPELL,PACK_WEAPON,PACK_LOCATION,PACK_HERO,PACK_POWER=(P+x for x in('pack_unit','pack_spell','pack_weapon','pack_location','pack_hero','pack_power'))
MOVE=P+'move';RETIRE=P+'retire';UNKNOWN=P+'missing'
PACK_MEMBERS=(PACK_UNIT,PACK_SPELL,PACK_WEAPON,PACK_LOCATION,PACK_HERO)
HELPERS=(KILL,DOUBLE,HURT,CURRENT,BASE,DISCOUNT,BOUNCE,HUSH,NATURAL,FILL_TRIGGER,POWER,
    PROGRESS_WATCH,DAMAGE_WATCH,SUMMON_WATCH,CREATE_WATCH,*PACK_MEMBERS,PACK_POWER,MOVE,RETIRE)
CTX=GenerationContext('k695-explicit-complete-test-domains','experimental')


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=replace(metadata(collectible=False),tribes=())
    def held(c):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in(DEN,INFUSED))
    def issuer(c):return next(e for e in c.state.entities.values()if e.card_id==AVATAR)
    def fill_trigger(c):
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==BRIGHT)
        return(*(AddToHand(c.player_id,UNIT,c.source_id)for _ in range(10)),TriggerBattlecry(MinionReference.capture(target),c.source_id))
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        DOUBLE:lambda c:(DestroyBatch(tuple(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==UNIT)[:2],c.source_id),),
        HURT:lambda c:(Damage(c.state.players[c.player_id].hero_id,10,c.source_id),),
        CURRENT:lambda c:(CopyCard(CardReference.capture(held(c)),c.player_id,mode='current',source_id=c.source_id),),
        BASE:lambda c:(CopyCard(CardReference.capture(held(c)),c.player_id,mode='base',source_id=c.source_id),),
        DISCOUNT:lambda c:(ModifyStoredCost(CardReference.capture(held(c)),CostSpec(set_to=1),c.source_id),),
        BOUNCE:lambda c:(ReturnToHand(c.target_id),),HUSH:lambda c:(Silence(c.target_id),),
        NATURAL:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(BRIGHT),),SummonCause.capture(c)),),
        FILL_TRIGGER:fill_trigger,MOVE:lambda c:(ChangeControl(issuer(c).id,2),),RETIRE:lambda c:(Destroy(issuer(c).id,c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,metadata=replace(meta,collectible=cid in(MOVE,RETIRE)),
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,BOUNCE,HUSH)else None))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K695 deliberate original-source rollback')))
    r.register_behavior(PACK_SPELL,lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,cost=1,health=4,spell_damage=3,metadata=meta))
    r.register_card(CardDefinition(PACK_UNIT,PACK_UNIT,CardType.MINION,cost=3,attack=1,health=20,
        battlecry=FAIL,combo=FAIL,keywords=(Keyword.COMBO,),metadata=replace(meta,collectible=True)))
    r.register_card(CardDefinition(PACK_SPELL,PACK_SPELL,CardType.SPELL,cost=3,on_play=PACK_SPELL,metadata=replace(meta,collectible=True)))
    r.register_card(CardDefinition(PACK_WEAPON,PACK_WEAPON,CardType.WEAPON,cost=3,attack=2,durability=3,battlecry=FAIL,metadata=replace(meta,collectible=True)))
    r.register_card(CardDefinition(PACK_LOCATION,PACK_LOCATION,CardType.LOCATION,cost=3,durability=3,on_use=FAIL,metadata=replace(meta,collectible=True)))
    r.register_card(CardDefinition(PACK_POWER,PACK_POWER,CardType.HERO_POWER,cost=2,on_use=PACK_SPELL,metadata=metadata(CardClass.WARLOCK,collectible=False)))
    r.register_card(CardDefinition(PACK_HERO,PACK_HERO,CardType.HERO,cost=3,health=30,hero_card=True,hero_armor=5,
        initial_hero_power=PACK_POWER,battlecry=FAIL,metadata=metadata(CardClass.WARLOCK)))
    def watch(c):
        source=c.state.entities.get(c.event.source_id);target=c.state.entities.get(c.event.target_id)
        if c.event.kind=='hand_progressed':
            if target is None or target.card_id not in(DEN,INFUSED):return()
        elif c.event.kind=='damage_dealt':
            if source is None or source.card_id not in(DEN,INFUSED):return()
        elif c.event.kind=='minion_summoned':
            if target is None or not any(root.request.cause.source.card_id in(SNEED,AVATAR)and
                    root.request.cause.source.entity_id!=target.id and
                    any(d.outcome=='delivered'and d.entity.entity_id==target.id for d in root.deliveries)
                    for root in c.state.card_summon_history):return()
        elif source is None or source.card_id!=BRIGHT:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail after RNG',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((PROGRESS_WATCH,'hand_progressed'),(DAMAGE_WATCH,'damage_dealt'),(SUMMON_WATCH,'minion_summoned'),(CREATE_WATCH,'card_created')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,metadata=meta,triggers=(TriggerSpec(event,WATCH),)))
    r.validate();return h


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    full=host(role).registry;r=Registry('k695-native-source-fixture-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    ids=tuple('CORE_'+x for x in native.ROOTS)+(INFUSED,'TIME_013','HERO_08','HERO_08bp',A,UNIT,ALAKIR,FANDRAL,*HELPERS)
    for cid in ids:
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    for cid in('CORE_REV_906',INFUSED):r.register_infused_battlecry_profile(full.infused_battlecry_profiles[cid])
    r.register_standard_pack_profile(full._standard_pack_profiles['CORE_WON_145'])
    native.register_past_legendary_source_bindings(r)
    for cid in (*PACK_MEMBERS,MOVE,RETIRE):
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,3,replace(metadata(),rarity=Rarity.LEGENDARY,tribes=())))
    legends=(ALAKIR,FANDRAL,'CORE_EX1_189','CORE_GVG_114')+((UNKNOWN,)if mode=='unknown_generation'else())
    r.register_pool(PoolDefinition('constructed.cards','k695-complete-explicit-legendary-domain-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(x)for x in legends),complete=True))
    members={'unit':(PACK_UNIT,),'move':(MOVE,PACK_UNIT),'retire':(RETIRE,PACK_UNIT),'unknown_pack':(UNKNOWN,)}.get(mode,PACK_MEMBERS)
    r.register_pool(PoolDefinition('constructed.standard_pack','k695-complete-explicit-pack-domain-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(x)for x in members),complete=True));r.validate();return r


def experimental_seed(mode,predicate):
    r=fixture(mode);members=tuple(sorted(r.pool('constructed.standard_pack',CTX).members,key=lambda x:x.card_id))
    for seed in range(10000):
        if predicate(sample_candidates(Random(seed),members,5,replacement=True)):return seed
    raise AssertionError('No bounded pure seed for the complete experimental domain')


class PastLegendarySourceBindingTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(mode,role))
    def game(self,hand=(),*,board=(),enemy=(),extra_hand=(),mode='normal',player=1,seed=695,context=True):
        self.mode=mode;h=host('writer');r=h.registry if mode=='host'else fixture(mode)
        return Game.from_scenario(Scenario(tuple(PlayerSetup('HERO_08',hand=hand+extra_hand if p==player else(),
            board=board if p==player else enemy,deck=(UNIT,)*8,hero_power_card_id='HERO_08bp',mana=30,max_mana=30,mana_cap=30)
            for p in(1,2)),active_player=player,seed=seed,generation_context=(h.context if mode=='host'else CTX)if context else None),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def finish(self,g):
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;ids=[x.id for x in q.options]
            g.apply(SelectChoice(q.player_id,q.id,('continue',)if'continue'in ids else tuple(ids[:q.min_count])))
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def rows(self,g,kind):return[e for e in g.events if e.kind==kind]
    def assert_pack(self,g,source):
        self.assertEqual(len(self.rows(g,OPENED)),1);self.assertEqual(len(self.rows(g,STEP)),5);self.assertEqual(len(self.rows(g,FINISHED)),1)
        request=json.loads(dict(self.rows(g,OPENED)[0].data)['request'])
        self.assertEqual((request['profile_card_id'],request['source']['card_id'],request['source']['entity_id']),(AVATAR,AVATAR,source))
    def fault_and_restore(self,g):
        before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);return g

    def test_complete_four_sources_exact_profiles_and_original_child_are_pinned(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),12);self.assertEqual(len(d['original_candidate_ids']),732)
        r=fixture()
        for row,core in zip(d['cards'],d['existing_dependencies']):
            native.semantic_pair(row['record'],core['record']);cid=row['record']['id']
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256']);self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        self.assertEqual(len(r.infused_battlecry_profiles),3);self.assertEqual(len(r._standard_pack_profiles),2)
        self.assertEqual(r.infused_battlecry_profiles[DEN].upgrade_card_id,INFUSED)

    def test_all_four_actual_paid_entries_keep_original_printed_faces(self):
        for cid in native.ROOTS:
            g=self.game((cid,));source=self.play(g,cid);self.finish(g);card=g.registry.card(cid)
            self.assertEqual((g.state.entities[source].card_id,g.state.entities[source].attack,g.state.entities[source].health),(cid,card.attack,card.health))
            self.assertEqual(g.state.players[1].mana,30-card.cost)

    def test_original_brightwing_generates_one_legendary_and_excludes_its_core_family(self):
        g=self.game((BRIGHT,));source=self.play(g,BRIGHT);made=self.created(g,source);self.assertEqual(len(made),1)
        c=g.registry.pool_card(made[0].card_id);self.assertEqual(c.kind,CardType.MINION);self.assertEqual(c.metadata.rarity,Rarity.LEGENDARY)
        self.assertNotEqual(c.generation_identity,g.registry.pool_card(BRIGHT).generation_identity)

    def test_original_brightwing_natural_summon_has_no_battlecry_or_pool_requirement(self):
        g=self.game((NATURAL,),context=False);self.play(g,NATURAL)
        self.assertEqual(self.unit(g,BRIGHT).card_id,BRIGHT);self.assertFalse(g.state.players[1].hand)

    def test_original_brightwing_full_hand_burns_one_real_generation(self):
        g=self.game((FILL_TRIGGER,),board=(BRIGHT,));source=self.unit(g,BRIGHT).id;self.play(g,FILL_TRIGGER)
        self.assertEqual(len(g.state.players[1].hand),10);made=self.created(g,source);self.assertEqual(len(made),1);self.assertEqual(made[0].zone,Zone.GRAVEYARD)

    def test_original_legendary_unknowns_reject_complete_generation_and_death_transaction(self):
        for death in(False,True):
            g=self.game((KILL,)if death else(BRIGHT,),board=(SNEED,)if death else(),mode='unknown_generation');before=g.snapshot()
            with self.assertRaises((ResolutionError,ValueError)):
                self.play(g,KILL,self.unit(g,SNEED).id)if death else self.play(g,BRIGHT)
            self.assertEqual(g.snapshot(),before)

    def test_original_sneed_natural_death_keeps_original_side_slot_and_source_family(self):
        g=self.game((KILL,),board=(A,SNEED,A));source=self.unit(g,SNEED).id;self.play(g,KILL,source)
        board=g.state.players[1].board;self.assertEqual([g.state.entities[i].card_id for i in(board[0],board[-1])],[A,A])
        generated=g.state.entities[board[1]];self.assertEqual(g.registry.card(generated.card_id).metadata.rarity,Rarity.LEGENDARY)
        self.assertNotEqual(g.registry.pool_card(generated.card_id).generation_identity,g.registry.pool_card(SNEED).generation_identity)
        self.assertEqual(g.state.death_history[0].card_id,SNEED);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_original_sneed_silence_prevents_generation(self):
        g=self.game((HUSH,KILL),board=(SNEED,));source=self.unit(g,SNEED).id;self.play(g,HUSH,source);self.play(g,KILL,source)
        self.assertFalse(g.state.players[1].board)

    def test_original_sneed_summon_wait_restores_once_and_rolls_back_rng(self):
        g=self.game((KILL,),board=(A,SNEED,SUMMON_WATCH));self.play(g,KILL,self.unit(g,SNEED).id);g=self.fault_and_restore(g);self.finish(g)
        self.assertEqual(len(g.state.players[1].board),3);self.portable(g)

    def test_original_denathrius_five_nonspell_packets_heal_actual_damage_without_spell_bonus(self):
        g=self.game((HURT,POWER,DEN));self.play(g,HURT);self.play(g,POWER);self.play(g,DEN)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(25,25));self.assertEqual(g.state.players[1].mana,18)

    def test_original_denathrius_first_and_repeating_stages_follow_actual_deaths(self):
        g=self.game((DEN,)+(KILL,)*4,board=(UNIT,)*4);source=self.entity(g,DEN).id
        for deaths in range(1,5):
            self.play(g,KILL,self.unit(g,UNIT).id);e=g.state.entities[source];progress=progress_ability(e)
            self.assertEqual((e.card_id,value(e),progress.progress_value),(DEN if deaths<2 else INFUSED,5+deaths//2,deaths%2))
        self.portable(g)

    def test_original_and_core_denathrius_have_independent_physical_progress(self):
        g=self.game((DEN,'CORE_REV_906',DOUBLE),board=(UNIT,UNIT));ids=g.state.players[1].hand[:2];self.play(g,DOUBLE)
        self.assertEqual([(g.state.entities[i].card_id,value(g.state.entities[i]))for i in ids],[(INFUSED,6),(INFUSED,6)])
        self.assertNotEqual(ids[0],ids[1]);self.portable(g)

    def test_original_denathrius_enemy_deaths_and_outside_hand_do_not_infuse(self):
        g=self.game((DEN,KILL,KILL),enemy=(UNIT,UNIT));source=self.entity(g,DEN).id
        for _ in range(2):self.play(g,KILL,self.unit(g,UNIT,2).id)
        self.assertEqual((g.state.entities[source].card_id,value(g.state.entities[source])),(DEN,5))
        g=self.game((DOUBLE,),board=(DEN,UNIT,UNIT));source=self.unit(g,DEN).id;self.play(g,DOUBLE);self.assertEqual(value(g.state.entities[source]),5)

    def test_original_denathrius_current_copy_keeps_partial_progress_and_advances_independently(self):
        g=self.game((DEN,KILL,CURRENT,KILL),board=(UNIT,UNIT));source=self.entity(g,DEN).id
        self.play(g,KILL,self.unit(g,UNIT).id);self.play(g,CURRENT);copies=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==DEN]
        self.assertEqual(len(copies),2);self.play(g,KILL,self.unit(g,UNIT).id)
        self.assertEqual([(g.state.entities[i].card_id,value(g.state.entities[i]))for i in copies],[(INFUSED,6),(INFUSED,6)]);self.assertIn(source,copies)

    def test_original_denathrius_discount_survives_real_upgrade_and_payload_uses_six(self):
        g=self.game((DEN,DISCOUNT,DOUBLE),board=(UNIT,UNIT));source=self.entity(g,DEN).id;self.play(g,DISCOUNT);self.play(g,DOUBLE)
        self.assertEqual(g.quote_cost(source).amount,1);self.play(g,INFUSED);self.assertEqual(self.hero(g,2).health,24)
        self.assertEqual(g.state.play_history[-1].battlecries[0].infused_damage,6);self.portable(g)

    def test_original_denathrius_progress_wait_restores_accepted_witnesses_and_upgrade(self):
        g=self.game((DEN,DOUBLE),board=(UNIT,UNIT,PROGRESS_WATCH));source=self.entity(g,DEN).id;self.play(g,DOUBLE);g=self.fault_and_restore(g)
        self.choose(g);self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.finish(g)
        self.assertEqual((g.state.entities[source].card_id,value(g.state.entities[source])),(INFUSED,6));self.portable(g)

    def test_original_denathrius_split_wait_keeps_original_budget_payment_and_lifesteal(self):
        g=self.game((HURT,DEN),board=(DAMAGE_WATCH,));self.play(g,HURT);self.play(g,DEN);g=self.fault_and_restore(g);self.finish(g)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(25,25));self.assertEqual(g.state.players[1].mana,19);self.portable(g)

    def test_original_pack_plays_five_kinds_with_own_profile_no_child_payment_or_battlecries(self):
        seed=experimental_seed('normal',lambda ids:set(ids)==set(PACK_MEMBERS));g=self.game((AVATAR,),seed=seed);source=self.play(g,AVATAR)
        self.assert_pack(g,source);self.assertEqual({g.registry.card(dict(e.data)['card_id']).kind for e in self.rows(g,STEP)},
            {CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION,CardType.HERO})
        self.assertEqual(g.state.players[1].mana,21);self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_original_pack_full_hand_has_five_slots_and_no_added_hand_cards(self):
        g=self.game((AVATAR,),extra_hand=(UNIT,)*9,mode='unit');source=self.play(g,AVATAR);self.assert_pack(g,source)
        self.assertEqual(len(g.state.players[1].hand),9);self.assertEqual(len(g.state.play_history),1)

    def test_original_pack_full_board_consumes_five_failed_occurrences_once(self):
        g=self.game((AVATAR,),board=(UNIT,)*6,mode='unit');source=self.play(g,AVATAR);self.assert_pack(g,source)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.state.players[1].mana,21)

    def test_original_pack_later_occurrences_follow_original_issuer_current_controller(self):
        seed=experimental_seed('move',lambda ids:ids[0]==MOVE and ids[1:]==(PACK_UNIT,)*4)
        g=self.game((AVATAR,),mode='move',seed=seed);source=self.play(g,AVATAR);self.assert_pack(g,source)
        self.assertEqual(g.state.entities[source].controller,2);self.assertEqual([e.player_id for e in self.rows(g,STEP)],[1,2,2,2,2]);self.portable(g)

    def test_original_pack_accepted_tail_continues_after_issuer_death(self):
        seed=experimental_seed('retire',lambda ids:ids[0]==RETIRE and ids[1:]==(PACK_UNIT,)*4)
        g=self.game((AVATAR,),mode='retire',seed=seed);source=self.play(g,AVATAR);self.assert_pack(g,source)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].board),4);self.portable(g)

    def test_original_pack_wait_restores_one_opening_cursor_and_atomic_failure(self):
        g=self.game((AVATAR,),board=(SUMMON_WATCH,),mode='unit');source=self.play(g,AVATAR);g=self.fault_and_restore(g);self.finish(g)
        self.assert_pack(g,source);self.assertEqual(g.state.players[1].mana,21);self.portable(g)

    def test_original_pack_unknown_complete_domain_or_missing_context_is_not_silently_trimmed(self):
        for mode,context in(('unknown_pack',True),('unit',False)):
            g=self.game((AVATAR,),mode=mode,context=context);before=g.snapshot()
            with self.assertRaises((ValueError,ResolutionError)):self.play(g,AVATAR)
            self.assertEqual(g.snapshot(),before)

    def test_original_pack_rehashed_wrong_native_source_profile_rejects(self):
        g=self.game((AVATAR,),board=(SUMMON_WATCH,),mode='unit');self.play(g,AVATAR);snapshot=g.snapshot()
        event=next(x for x in snapshot['events']if x['kind']==OPENED);request=json.loads(event['data']['request'])
        request['profile_card_id']='missing-original-profile';event['data']['request']=json.dumps(request,sort_keys=True,separators=(',',':'))
        snapshot['events_hash']=canonical_hash(snapshot['events']);snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,fixture('unit','independent-reader'))

    def test_actual_full_standard_host_original_legendary_sources_keep_complete_domain(self):
        for death in(False,True):
            g=self.game((KILL,)if death else(BRIGHT,),board=(SNEED,)if death else(),mode='host')
            if death:self.play(g,KILL,self.unit(g,SNEED).id);card=g.state.entities[g.state.players[1].board[0]].card_id
            else:source=self.play(g,BRIGHT);card=self.created(g,source)[0].card_id
            self.assertEqual(g.registry.card(card).metadata.rarity,Rarity.LEGENDARY);self.portable(g)

    def test_actual_full_standard_pack_original_source_uses_all_five_native_kind_paths(self):
        from test_standard_pack_inventory import RECIPES
        kinds=set()
        for first,(seed,expected)in RECIPES.items():
            g=self.game((AVATAR,),mode='host',seed=seed);source=self.play(g,AVATAR);self.finish(g);self.assert_pack(g,source)
            self.assertEqual(tuple(dict(self.rows(g,OPENED)[0].data)['drawn']),expected);kinds.add(g.registry.card(first).kind)
            self.assertEqual(g.state.players[1].mana,21)
        self.assertEqual(len(kinds),5);self.portable(g)

    def test_actual_full_standard_pack_original_wait_preserves_private_domain_and_replay(self):
        g=self.game((AVATAR,),board=(SUMMON_WATCH,),mode='host',seed=248);source=self.play(g,AVATAR);g=self.fault_and_restore(g)
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe())
            for key in('rng_before','rng_after','candidates','drawn','profile_card_id'):self.assertNotIn('"'+key+'"',view)
        self.finish(g);self.assert_pack(g,source);self.portable(g)
