"""Real linked-face actions and separate natural named-child cycles."""
from dataclasses import asdict
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_legendary_linked_printings as native
from hs_sim.engine import Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,
    InvokeBehavior,RandomDamage,RequestChoice,Silence,TriggerDeathrattles)
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.registry import Registry
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

DEATHWING,ACID,ANUB=native.ROOTS;NERUB=native.NERUBIAN
OLD_ANUB,OLD_NERUB='AT_036','AT_036t'
P='k696.';A=P+'plain';SHIELD=P+'shield';IMMUNE=P+'immune'
KILL=P+'kill';HIT=P+'hit';ZERO=P+'zero';AREA=P+'area';HUSH=P+'hush'
TAKE=P+'take';GROW=P+'grow';TRIGGER=P+'trigger';FAIL=P+'fail'
DEATH_WATCH=P+'death_watch';DISCARD_WATCH=P+'discard_watch';SUMMON_WATCH=P+'summon_watch'
HELPERS=(A,SHIELD,IMMUNE,KILL,HIT,ZERO,AREA,HUSH,TAKE,GROW,TRIGGER,DEATH_WATCH,DISCARD_WATCH,SUMMON_WATCH)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    for cid,keywords in((A,()),(SHIELD,(Keyword.DIVINE_SHIELD,)),(IMMUNE,(Keyword.IMMUNE,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=20,keywords=keywords,metadata=meta))
    def area(c):
        return(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.SPELL)for p in(1,2)
            for i in c.state.players[p].board if c.state.entities[i].active)),)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        ZERO:lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.SPELL),),AREA:area,
        HUSH:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,c.player_id),),
        GROW:lambda c:(Buff(c.target_id,3,3,c.source_id),),TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),)}
    board=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,
            on_play=cid,metadata=meta,targeting=None if cid==AREA else board))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K696 deliberate continuation failure')))
    def watch(c):
        if c.event.kind=='minion_summoned':
            e=c.state.entities.get(c.event.target_id)
            if e is None or e.card_id not in(ANUB,NERUB):return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail after random work',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
            InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    for cid,event in((DEATH_WATCH,'minion_died'),(DISCARD_WATCH,'card_discarded'),(SUMMON_WATCH,'minion_summoned')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=30,metadata=meta,
            triggers=(TriggerSpec(event,P+'watch'),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k696-complete-linked-printings-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in tuple(native.COUNTERPARTS.values())+('TIME_013','HERO_08','HERO_08bp',*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_legendary_linked_printings(r);r.validate();return r


class PastLegendaryLinkedPrintingTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),watch=None,real_host=False):
        self.mode='host'if real_host else'small';h=host('writer')
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(A,)*6,mana=30,max_mana=30,mana_cap=30,
                weapon_card_id=watch,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',board=enemy,deck=(A,)*6,hero_power_card_id='HERO_08bp')),
            seed=696,generation_context=h.context if real_host else None),h.registry if real_host else fixture('writer'))

    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hand(self,g):return[g.state.entities[i].card_id for i in g.state.players[1].hand]
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault_atomic(self,g):
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_complete_raw_primary_copy_child_and_existing_full_definitions(self):
        d=native.load_batch();r=fixture();self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['official_observations']),12)
        for row in d['cards']+d['dependencies']:
            raw=row['record'];cid=raw['id'];other=native.COUNTERPARTS[cid]
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual((r.card(cid).cost,r.card(cid).attack,r.card(cid).health),(raw['cost'],raw['attack'],raw['health']))
            if cid in(DEATHWING,ACID):
                self.assertEqual((r.card(cid).battlecry,r.card(cid).triggers),(r.card(other).battlecry,r.card(other).triggers))
        for row in d['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(r.card(row['record']['id']))),row['definition_sha256'])
        self.assertFalse(d['complete_past_legendary_source_bound']);self.assertFalse(d['formal_pool_complete'])

    def test_each_linked_root_real_hand_entry_pays_once_and_keeps_printed_face(self):
        for cid in native.ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,));source=self.play(g,cid);self.finish(g);card=g.registry.card(cid)
                self.assertEqual((g.state.entities[source].card_id,g.state.entities[source].attack,g.state.entities[source].health),
                    (cid,card.attack,card.health));self.assertEqual(g.state.players[1].mana,30-card.cost)
                self.assertEqual(len(g.state.play_history),1)

    def test_deathwing_destroys_both_sides_and_discards_only_actual_original_count(self):
        g=self.game((DEATHWING,)+(A,)*4,board=(A,),enemy=(SHIELD,IMMUNE));source=self.play(g,DEATHWING)
        self.assertEqual(self.board(g),[DEATHWING]);self.assertEqual(self.board(g,2),[])
        self.assertEqual(len(self.hand(g)),1);self.assertEqual(g.state.entities[source].health,12)
        self.assertEqual(g.state.players[1].mana,20);self.portable(g)

    def test_deathwing_empty_original_batch_does_not_discard_or_consume_rng(self):
        g=self.game((DEATHWING,A));before=g.snapshot()['rng_state'];self.play(g,DEATHWING)
        self.assertEqual(self.hand(g),[A]);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_deathwing_keeps_both_printings_new_children_and_excludes_them_from_count(self):
        g=self.game((DEATHWING,)+(A,)*3,board=(ANUB,),enemy=(OLD_ANUB,));self.play(g,DEATHWING)
        self.assertEqual(self.board(g),[NERUB,DEATHWING]);self.assertEqual(self.board(g,2),[OLD_NERUB])
        self.assertEqual(self.hand(g),[A]);self.assertEqual(len(g.state.death_history),2)

    def test_deathwing_death_wait_keeps_actual_linked_source_and_recovers(self):
        g=self.game((DEATHWING,A,A),enemy=(A,),watch=DEATH_WATCH);self.play(g,DEATHWING)
        g=self.portable(g);self.fault_atomic(g)
        self.assertEqual(g.state.death_history[0].cause.source_card_id,DEATHWING)
        self.finish(g);self.assertEqual(self.hand(g),[A]);self.portable(g)

    def test_deathwing_discard_wait_restores_original_count_and_rng_rollback(self):
        g=self.game((DEATHWING,A,A,A),enemy=(A,A),watch=DISCARD_WATCH);self.play(g,DEATHWING)
        g=self.portable(g);self.fault_atomic(g);self.finish(g)
        self.assertEqual(self.hand(g),[A]);self.assertEqual(len(g.state.death_history),2);self.portable(g)

    def test_acidmaw_positive_damage_destroys_enemy_and_keeps_friendly(self):
        g=self.game((HIT,HIT),board=(ACID,A),enemy=(A,));friendly=self.unit(g,A).id;enemy=self.unit(g,A,2).id
        self.play(g,HIT,friendly);self.play(g,HIT,enemy)
        self.assertEqual(g.state.entities[friendly].health,19);self.assertEqual(g.state.entities[enemy].zone,Zone.GRAVEYARD)

    def test_acidmaw_zero_shield_and_immune_do_not_create_destruction(self):
        g=self.game((ZERO,HIT,AREA),board=(ACID,),enemy=(A,SHIELD,IMMUNE))
        for spell,cid in((ZERO,A),(HIT,SHIELD)):
            target=self.unit(g,cid,2).id;self.play(g,spell,target);self.assertEqual(g.state.entities[target].zone,Zone.BOARD)
        self.assertEqual(g.state.death_history,[])
        target=self.unit(g,IMMUNE,2).id;self.play(g,AREA)
        self.assertEqual((g.state.entities[target].zone,g.state.entities[target].health),(Zone.BOARD,20))

    def test_acidmaw_silence_retires_existing_listener(self):
        g=self.game((HUSH,HIT),board=(ACID,),enemy=(A,));self.play(g,HUSH,self.unit(g,ACID).id)
        target=self.unit(g,A,2).id;self.play(g,HIT,target);self.assertEqual(g.state.entities[target].health,19)

    def test_acidmaw_new_controller_defines_current_enemy_side(self):
        g=self.game((TAKE,HIT,HIT),board=(A,),enemy=(ACID,A));self.play(g,TAKE,self.unit(g,ACID,2).id)
        friend=self.unit(g,A).id;enemy=self.unit(g,A,2).id;self.play(g,HIT,friend);self.play(g,HIT,enemy)
        self.assertEqual(g.state.entities[friend].health,19);self.assertEqual(g.state.entities[enemy].zone,Zone.GRAVEYARD)

    def test_acidmaw_area_destroys_both_enemy_recipients_after_actual_damage(self):
        g=self.game((AREA,),board=(ACID,A),enemy=(A,A));self.play(g,AREA)
        self.assertEqual(self.board(g,2),[]);self.assertEqual(self.unit(g,ACID).health,1);self.assertEqual(self.unit(g,A).health,19)
        self.portable(g)

    def test_acidmaw_destruction_wait_restores_and_rejects_failed_continuation(self):
        g=self.game((HIT,),board=(ACID,),enemy=(A,),watch=DEATH_WATCH);self.play(g,HIT,self.unit(g,A,2).id)
        g=self.portable(g);self.fault_atomic(g);self.finish(g);self.assertEqual(self.board(g,2),[])

    def test_new_anubarak_cycle_returns_own_fresh_face_and_never_old_printing(self):
        g=self.game((KILL,KILL),board=(ANUB,));source=self.unit(g,ANUB).id;self.play(g,KILL,source)
        child=self.unit(g,NERUB).id;self.assertNotEqual(child,source);self.assertEqual(self.hand(g),[KILL])
        self.play(g,KILL,child);body=self.unit(g,ANUB)
        self.assertEqual((body.attack,body.health),(8,4));self.assertNotIn(body.id,(source,child));self.assertEqual(self.hand(g),[])
        self.assertNotIn(OLD_ANUB,self.board(g));self.portable(g)

    def test_both_named_cycles_preserve_original_same_side_middle_slot(self):
        g=self.game((KILL,KILL),board=(A,ANUB,A),enemy=(A,OLD_ANUB,A))
        self.play(g,KILL,self.unit(g,ANUB).id);self.play(g,KILL,self.unit(g,OLD_ANUB,2).id)
        self.assertEqual(self.board(g),[A,NERUB,A]);self.assertEqual(self.board(g,2),[A,OLD_NERUB,A])

    def test_anubarak_buffs_do_not_leak_to_named_child_or_fresh_cycle_body(self):
        g=self.game((GROW,KILL,GROW,KILL),board=(ANUB,));self.play(g,GROW,self.unit(g,ANUB).id)
        self.play(g,KILL,self.unit(g,ANUB).id);self.assertEqual((self.unit(g,NERUB).attack,self.unit(g,NERUB).health),(4,4))
        self.play(g,GROW,self.unit(g,NERUB).id);self.play(g,KILL,self.unit(g,NERUB).id)
        self.assertEqual((self.unit(g,ANUB).attack,self.unit(g,ANUB).health),(8,4))

    def test_stolen_anubarak_child_uses_current_controller_and_silence_breaks_cycle(self):
        g=self.game((TAKE,KILL,HUSH,KILL),enemy=(ANUB,));self.play(g,TAKE,self.unit(g,ANUB,2).id)
        self.play(g,KILL,self.unit(g,ANUB).id);child=self.unit(g,NERUB).id
        self.assertEqual(self.board(g,2),[]);self.play(g,HUSH,child);self.play(g,KILL,child);self.assertEqual(self.board(g),[])

    def test_live_deathrattle_capacity_uses_normal_delivery_without_removing_source(self):
        for slots in(5,6):
            g=self.game((TRIGGER,),board=(ANUB,)+(A,)*slots);source=self.unit(g,ANUB).id;self.play(g,TRIGGER,source)
            self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertEqual(len(self.board(g)),7)
            self.assertEqual(self.board(g).count(NERUB),1 if slots==5 else 0)

    def test_new_child_and_parent_summon_waits_restore_their_own_cycle(self):
        g=self.game((KILL,KILL),board=(ANUB,),watch=SUMMON_WATCH);self.play(g,KILL,self.unit(g,ANUB).id)
        g=self.portable(g);self.fault_atomic(g);self.finish(g);self.play(g,KILL,self.unit(g,NERUB).id)
        g=self.portable(g);self.finish(g);self.assertEqual(self.board(g),[ANUB]);self.portable(g)

    def test_complete_standard_host_real_linked_entries_and_named_child_execution(self):
        g=self.game((DEATHWING,A),enemy=(A,),real_host=True);self.play(g,DEATHWING)
        self.assertEqual(self.board(g),[DEATHWING]);self.assertEqual(self.hand(g),[])
        g=self.game((ACID,HIT),enemy=(A,),real_host=True);self.play(g,ACID);self.play(g,HIT,self.unit(g,A,2).id)
        self.assertEqual(self.board(g,2),[])
        g=self.game((ANUB,KILL,KILL),real_host=True);self.play(g,ANUB);self.play(g,KILL,self.unit(g,ANUB).id)
        self.play(g,KILL,self.unit(g,NERUB).id);self.assertEqual(self.board(g),[ANUB]);self.portable(g)


if __name__=='__main__':unittest.main()
