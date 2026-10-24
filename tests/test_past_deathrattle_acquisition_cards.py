"""Actual Surfer chains and single-death complete Devourer acquisition."""
from copy import deepcopy
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_deathrattle_acquisition_cards import (SURFER,DEVOURER,SURF,
    load_batch,register_past_deathrattle_acquisition_cards)
from hs_sim.cards.native_deathrattle_memory_cards import register_native_deathrattle_memory_cards
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,
    Game,Keyword,PlayerSetup,Registry,RewindSpec,Scenario,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.deathrattle_inheritance import GainDeathrattlesFromDeath,inherited
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Destroy,
    DestroyBatch,GainArmor,GrantDeathrattle,InvokeBehavior,RequestChoice,
    ReturnToHand,Silence,Transform,TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from tools import card_batch as batch

P='k489.'
HERO,POWER,A,B,R1,R2,WATCH=(P+x for x in ('hero','power','a','b','r1','r2','watch'))
EGG,WHELP,PLAT='CATA_210','CATA_210t','TLC_603'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def rattles(entity):return tuple(a for a in entity.abilities if a.kind=='deathrattle'and not a.consumed)


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_past_deathrattle_acquisition_cards(r)
    register_native_deathrattle_memory_cards(r)
    r.register_behavior(P+'empty',lambda c:())
    r.register_behavior(P+'marker',lambda c:(GainArmor(c.player_id,2),))
    r.register_behavior(P+'marker2',lambda c:(GainArmor(c.player_id,5),))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,initial_hero_power=POWER,metadata=META))
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,on_use=P+'empty',metadata=META))
    for cid,health,extra in ((A,4,{}),(B,6,{}),(P+'suppressor',8,dict(keywords=(Keyword.DEATHRATTLE_SUPPRESSOR,))),
            (R1,3,dict(deathrattle=P+'marker')),(R2,3,dict(deathrattle=P+'marker2'))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=health,metadata=META,**extra))
    def fail(c):raise ResolutionError('K489 deliberate grant reaction failure')
    r.register_behavior(P+'fail',fail)
    bodies=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),
        trigger=lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        silence=lambda c:(Silence(c.target_id),),bounce=lambda c:(ReturnToHand(c.target_id),),
        transform=lambda c:(Transform(c.target_id,A),),
        give=lambda c:(ChangeControl(c.target_id,3-c.state.entities[c.target_id].controller),),
        sleep=lambda c:(MakeDormant(c.target_id,2,c.source_id),),
        copy=lambda c:(CopyMinion(c.target_id,c.player_id),),
        base=lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        grant=lambda c:(GrantDeathrattle(c.target_id,P+'marker2',c.source_id),),
        rewind=lambda c:(Destroy(c.target_id,c.source_id),))
    def queued(c):
        death=next(d for d in c.state.death_history if d.card_id==R1)
        ref=MinionReference.capture(c.state.entities[c.target_id])
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('leave','Return original',(ReturnToHand(ref.entity_id),))),c.source_id),
            GainDeathrattlesFromDeath(death.id,ref))
    bodies['queue']=queued
    for key,body in bodies.items():
        extra=dict(keywords=(Keyword.REWIND,),rewind=RewindSpec())if key=='rewind'else{}
        r.register_behavior(P+key,body)
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),**extra))
    r.register_behavior(P+'clear',lambda c:(DestroyBatch(tuple(i for p in c.state.players.values()for i in p.board),c.source_id),))
    r.register_card(CardDefinition(P+'clear','clear',CardType.SPELL,on_play=P+'clear',metadata=META))
    def watch(c):
        if c.event.kind!='ability_granted' or dict(c.event.data).get('ability_kind')!='deathrattle':return ()
        if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode=='kill_recipient':return(Destroy(c.event.target_id,c.source_id),)
        if mode!='wait':return ()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),)),
            ChoiceOption('silence','Silence original',(Silence(c.event.target_id),)),
            ChoiceOption('bounce','Return original',(ReturnToHand(c.event.target_id),))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=META,
        triggers=(TriggerSpec('ability_granted',WATCH),)))
    r.validate();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in
        ('schema_version','events','events_hash','state_hash')})
    return saved


class PastDeathrattleAcquisitionTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(),mode='normal',seed=489):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=tuple(hand),board=tuple(board),
            deck=(A,)*10,mana=40,max_mana=40,mana_cap=40),PlayerSetup(HERO,board=tuple(enemy),
            deck=(A,)*10,mana=40,max_mana=40,mana_cap=40)),seed=seed),fixture(mode),Ruleset(max_hand=40))

    def board(self,g,cid,player=1):return self.entity(g,cid,player,zone='board')
    def armor(self,g,player=1):return g.state.entities[g.state.players[player].hero_id].armor

    def test_complete_original_rows_four_primary_faces_and_pinned_metadata(self):
        data=load_batch();rows={x['record']['id']:x['record']for x in data['dependencies']}
        self.assertEqual(tuple(rows),(SURFER,DEVOURER));self.assertEqual(len(data['official_observations']),4)
        for o in data['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256'])
            batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        r=fixture()
        self.assertEqual((r.card(SURFER).cost,r.card(SURFER).attack,r.card(SURFER).health),(1,1,1))
        self.assertEqual((r.card(DEVOURER).cost,r.card(DEVOURER).attack,r.card(DEVOURER).health),(1,1,3))
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_full_constructed_assembly_adds_only_two_reachable_leaves(self):
        from hs_sim.cards import build_registry
        r=batch.registration_prefix(build_registry,
            'hs_sim.cards.past_deathrattle_acquisition_cards.register_past_deathrattle_acquisition_cards',
            register_past_deathrattle_acquisition_cards,after=True)
        self.assertEqual(len(r.cards),2684)
        self.assertEqual(r.card(SURFER),fixture().card(SURFER));self.assertEqual(r.card(DEVOURER),fixture().card(DEVOURER))

    def test_actual_paid_surfer_has_no_battlecry(self):
        g=self.game((SURFER,),board=(A,));eid=self.play(g,SURFER)
        self.assertEqual(len(rattles(g.state.entities[eid])),1)
        self.assertFalse(rattles(self.board(g,A)));self.assertEqual(self.board(g,A).attack,1);self.portable(g)

    def test_natural_surfer_grants_one_other_friendly_minion(self):
        g=self.game((P+'kill',),board=(SURFER,A));source=self.board(g,SURFER).id
        self.play(g,P+'kill',source);target=self.board(g,A)
        self.assertEqual((target.attack,target.max_health),(2,5))
        self.assertEqual(tuple(a.behavior_id for a in rattles(target)),(SURF,))
        self.assertEqual(len(g.state.death_history),1);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_any_includes_enemy_and_chain_returns_from_enemy_carrier(self):
        g=self.game((P+'kill',P+'kill',A),board=(SURFER,),enemy=(B,))
        self.play(g,P+'kill',self.board(g,SURFER).id);enemy=self.board(g,B,2)
        self.assertEqual((enemy.attack,enemy.max_health),(2,7));self.assertEqual(len(rattles(enemy)),1)
        self.play(g,A);self.play(g,P+'kill',enemy.id)
        self.assertEqual((self.board(g,A).attack,self.board(g,A).max_health),(2,5));self.portable(g)

    def test_active_invocation_excludes_its_live_self_without_fake_death(self):
        g=self.game((P+'trigger',),board=(SURFER,A));source=self.board(g,SURFER).id
        self.play(g,P+'trigger',source);self.assertEqual(len(rattles(self.board(g,A))),1)
        self.assertEqual(len(rattles(g.state.entities[source])),1);self.assertFalse(g.state.death_history)
        self.assertEqual(g.state.deathrattle_history[-1].capture.origin,'effect');self.portable(g)

    def test_surfer_passes_this_body_without_other_granted_deathrattles(self):
        g=self.game((P+'grant',P+'kill'),board=(SURFER,A));source=self.board(g,SURFER).id
        self.play(g,P+'grant',source);self.play(g,P+'kill',source)
        self.assertEqual(tuple(a.behavior_id for a in rattles(self.board(g,A))),(SURF,))
        self.assertEqual(self.armor(g),5);self.portable(g)

    def test_no_other_minion_has_no_random_draw_or_extra_choice(self):
        g=self.game((P+'kill',),board=(SURFER,));rng=g._rng.getstate();next_choice=g.state.next_choice_id
        self.play(g,P+'kill',self.board(g,SURFER).id)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.next_choice_id,next_choice);self.portable(g)

    def test_dormant_minion_is_excluded(self):
        g=self.game((P+'sleep',P+'kill'),board=(SURFER,A));self.play(g,P+'sleep',self.board(g,A).id)
        rng=g._rng.getstate();self.play(g,P+'kill',self.board(g,SURFER).id)
        self.assertFalse(rattles(self.board(g,A)));self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_single_sample_uses_complete_both_player_physical_domain(self):
        g=self.game((P+'kill',),board=(SURFER,A,A),enemy=(B,));source=self.board(g,SURFER).id
        candidates=sorted(i for p in g.state.players.values()for i in p.board if i!=source)
        rng=Random();rng.setstate(g._rng.getstate());expected=rng.sample(candidates,1)[0]
        self.play(g,P+'kill',source)
        self.assertEqual([i for i in candidates if rattles(g.state.entities[i])],[expected])
        self.assertEqual(g._rng.getstate(),rng.getstate());self.portable(g)

    def test_surfer_silence_removes_buff_and_granted_body(self):
        g=self.game((P+'kill',P+'silence'),board=(SURFER,A));self.play(g,P+'kill',self.board(g,SURFER).id)
        self.play(g,P+'silence',self.board(g,A).id);target=self.board(g,A)
        self.assertEqual((target.attack,target.max_health),(1,4));self.assertFalse(rattles(target));self.portable(g)

    def test_surfer_current_copy_keeps_chain_and_base_copy_does_not(self):
        g=self.game((P+'kill',P+'copy',P+'base'),board=(SURFER,A))
        self.play(g,P+'kill',self.board(g,SURFER).id);target=self.board(g,A).id
        self.play(g,P+'copy',target);self.play(g,P+'base',target)
        bodies=[g.state.entities[i]for i in g.state.players[1].board]
        self.assertEqual([len(rattles(e))for e in bodies],[1,1,0])
        self.assertEqual([e.attack for e in bodies],[2,2,1]);self.portable(g)

    def test_exact_new_friendly_death_does_not_reacquire_prior_deaths(self):
        g=self.game((P+'kill',P+'kill',P+'kill'),board=(DEVOURER,R1,A,R2));dev=self.board(g,DEVOURER).id
        self.play(g,P+'kill',self.board(g,R1).id);first=rattles(g.state.entities[dev]);self.assertEqual(len(first),1)
        self.play(g,P+'kill',self.board(g,A).id);self.assertEqual(rattles(g.state.entities[dev]),first)
        self.play(g,P+'kill',self.board(g,R2).id)
        self.assertEqual(tuple(a.behavior_id for a in rattles(g.state.entities[dev])),(P+'marker',P+'marker2'));self.portable(g)

    def test_enemy_death_and_ordinary_return_do_not_acquire(self):
        g=self.game((P+'kill',P+'bounce'),board=(DEVOURER,R1),enemy=(R2,))
        self.play(g,P+'kill',self.board(g,R2,2).id);self.play(g,P+'bounce',self.board(g,R1).id)
        self.assertFalse(rattles(self.board(g,DEVOURER)));self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_silenced_dead_minion_provides_no_deathrattle(self):
        g=self.game((P+'silence',P+'kill'),board=(DEVOURER,R1));target=self.board(g,R1).id
        self.play(g,P+'silence',target);self.play(g,P+'kill',target)
        self.assertFalse(rattles(self.board(g,DEVOURER)));self.portable(g)

    def test_dead_minion_complete_multiple_grants_keep_independent_identities(self):
        g=self.game((P+'grant',P+'grant',P+'kill'),board=(DEVOURER,R1));target=self.board(g,R1).id
        self.play(g,P+'grant',target);self.play(g,P+'grant',target);old=rattles(g.state.entities[target])
        self.play(g,P+'kill',target);grants=rattles(self.board(g,DEVOURER));self.assertEqual(len(grants),3)
        death=g.state.death_history[-1]
        for original,grant in zip(old,grants):
            self.assertEqual(grant,inherited(original,identity=grant.id,source_id=self.board(g,DEVOURER).id,
                grant_card_id=DEVOURER,death_id=death.id));self.assertGreater(grant.id,original.id)
        self.portable(g)

    def test_actual_devourer_death_executes_each_acquired_body_once(self):
        g=self.game((P+'kill',P+'kill',P+'kill'),board=(DEVOURER,R1,R2))
        self.play(g,P+'kill',self.board(g,R1).id);self.play(g,P+'kill',self.board(g,R2).id)
        before=self.armor(g);self.play(g,P+'kill',self.board(g,DEVOURER).id)
        self.assertEqual(self.armor(g)-before,7);self.portable(g)

    def test_silence_and_bounce_remove_acquired_material(self):
        for key in ('silence','bounce','transform'):
            with self.subTest(key=key):
                g=self.game((P+'kill',P+key),board=(DEVOURER,R1));target=self.board(g,DEVOURER).id
                self.play(g,P+'kill',self.board(g,R1).id);self.play(g,P+key,target)
                self.assertFalse(rattles(g.state.entities[target]));self.portable(g)

    def test_current_copy_retains_exact_death_material_with_new_ids(self):
        g=self.game((P+'kill',P+'copy',P+'base'),board=(DEVOURER,R1))
        self.play(g,P+'kill',self.board(g,R1).id);source=self.board(g,DEVOURER).id
        original=rattles(g.state.entities[source])[0]
        self.play(g,P+'copy',source);current=g.state.entities[g.state.players[1].board[-1]]
        copied=rattles(current)[0];self.assertNotEqual(copied.id,original.id)
        self.assertEqual(copied.deathrattle_inherited_from,original.deathrattle_inherited_from)
        self.play(g,P+'base',source);self.assertFalse(rattles(g.state.entities[g.state.players[1].board[-1]]));self.portable(g)

    def test_same_batch_death_does_not_grant_to_dead_devourer(self):
        g=self.game((P+'clear',),board=(DEVOURER,R1));target=self.board(g,DEVOURER).id
        self.play(g,P+'clear');self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertFalse(rattles(g.state.entities[target]));self.assertEqual(len(g.state.death_history),2);self.portable(g)

    def test_control_at_death_and_actual_new_devourer_controller(self):
        g=self.game((P+'give',P+'kill'),board=(DEVOURER,),enemy=(R1,));target=self.board(g,DEVOURER).id
        self.play(g,P+'give',target);self.play(g,P+'kill',self.board(g,R1,2).id)
        self.assertEqual(len(rattles(g.state.entities[target])),1)
        self.assertEqual(rattles(g.state.entities[target])[0].deathrattle_inherited_from[0],g.state.death_history[-1].id);self.portable(g)

    def test_native_grown_egg_keeps_frozen_parameters_and_real_summon(self):
        g=self.game((P+'kill',P+'kill'),board=(DEVOURER,EGG));g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.play(g,P+'kill',self.board(g,EGG).id);ability=rattles(self.board(g,DEVOURER))[0]
        self.assertEqual(ability.deathrattle_memory.growth_steps,1);self.portable(g)
        self.play(g,P+'kill',self.board(g,DEVOURER).id)
        tokens=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==WHELP]
        self.assertEqual([(e.attack,e.max_health)for e in tokens],[(3,2),(3,2)]);self.portable(g)

    def test_native_draw_memory_is_acquired_under_global_deathrattle_prohibition(self):
        g=self.game((DEVOURER,PLAT,P+'kill',P+'silence',P+'kill'),board=(P+'suppressor',))
        self.play(g,DEVOURER);plat=self.play(g,PLAT);memory=rattles(g.state.entities[plat])[0].deathrattle_memory
        self.assertEqual(len(memory.draws),1);drawn=memory.draws[0].entity_id
        self.play(g,P+'kill',plat);self.assertTrue(g.state.death_history[-1].deathrattles_blocked)
        self.assertEqual(rattles(self.board(g,DEVOURER))[0].deathrattle_memory,memory)
        self.assertIn(drawn,g.state.players[1].hand);self.portable(g)
        self.play(g,P+'silence',self.board(g,P+'suppressor').id)
        self.play(g,P+'kill',self.board(g,DEVOURER).id)
        self.assertNotIn(drawn,g.state.players[1].hand);self.assertEqual(g.state.discard_history[-1].card.entity_id,drawn);self.portable(g)

    def test_sparse_real_rewind_death_id_uses_original_row_not_list_index(self):
        g=self.game((P+'rewind',),board=(DEVOURER,R1));self.play(g,P+'rewind',self.board(g,R1).id)
        self.assertIsNotNone(g.state.pending_choice);self.choose(g,'retry')
        death=g.state.death_history[-1];self.assertGreater(death.id,len(g.state.death_history))
        self.assertEqual(rattles(self.board(g,DEVOURER))[0].deathrattle_inherited_from[0],death.id);self.portable(g)

    def test_all_death_material_installed_before_first_grant_wait(self):
        g=self.game((P+'grant',P+'kill'),board=(DEVOURER,R1,WATCH),mode='wait');target=self.board(g,R1).id
        self.play(g,P+'grant',target);self.choose(g)
        self.play(g,P+'kill',target);self.assertEqual(len(rattles(self.board(g,DEVOURER))),2)
        restored=self.portable(g)
        self.choose(g,'continue');self.choose(restored,'continue');self.assertEqual(g.snapshot(),restored.snapshot())
        self.choose(g,'continue');self.choose(restored,'continue');self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_surfer_grant_wait_restores_before_original_buff(self):
        g=self.game((P+'kill',),board=(SURFER,),enemy=(WATCH,),mode='wait')
        self.play(g,P+'kill',self.board(g,SURFER).id);target=self.board(g,WATCH,2)
        self.assertEqual((len(rattles(target)),target.attack,target.max_health),(1,0,10))
        restored=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual((self.board(g,WATCH,2).attack,self.board(g,WATCH,2).max_health),(1,11));self.portable(g)

    def test_grant_reaction_return_does_not_buff_original_new_hand_residence(self):
        g=self.game((P+'kill',),board=(SURFER,),enemy=(WATCH,),mode='wait')
        self.play(g,P+'kill',self.board(g,SURFER).id);target=self.board(g,WATCH,2).id
        self.choose(g,'bounce');self.assertEqual(g.state.entities[target].zone,Zone.HAND)
        self.assertFalse(rattles(g.state.entities[target]));self.assertEqual(g.state.entities[target].attack,0);self.portable(g)

    def test_late_grant_failure_rolls_back_paid_death_and_rng(self):
        g=self.game((P+'kill',),board=(SURFER,),enemy=(WATCH,),mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'kill',self.board(g,SURFER).id)
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_waiting_acquisition_rejects_rehashed_changed_payload_or_missing_death(self):
        g=self.game((P+'kill',),board=(DEVOURER,R1,WATCH),mode='wait')
        self.play(g,P+'kill',self.board(g,R1).id);saved=g.snapshot();dev=self.board(g,DEVOURER).id
        for kind in ('payload','death'):
            bad=deepcopy(saved)
            if kind=='payload':
                row=bad['state']['entities'][str(dev)]
                next(a for a in row['abilities']if a['kind']=='deathrattle')['behavior_id']=P+'marker2'
            else:bad['state']['death_history']=[]
            with self.subTest(kind=kind),self.assertRaises(SnapshotError)as caught:
                Game.from_snapshot(rehash(bad),fixture('wait','reader-forgery'))
            self.assertNotIn('digest mismatch',str(caught.exception))
        self.portable(g)

    def test_original_friendly_death_effect_rejects_opponent_binding(self):
        g=self.game((P+'kill',),board=(DEVOURER,),enemy=(R1,))
        self.play(g,P+'kill',self.board(g,R1,2).id)
        request=GainDeathrattlesFromDeath(g.state.death_history[-1].id,MinionReference.capture(self.board(g,DEVOURER)))
        with self.assertRaises(ValueError):request.validate_in_state(g.state)

    def test_independent_surfer_bodies_repeat_without_regranting_other_bodies(self):
        g=self.game((P+'kill',P+'kill',P+'trigger',A),board=(SURFER,SURFER,B))
        self.play(g,P+'kill',self.board(g,SURFER).id)
        # The other live Surfer is eligible, so use its received material or B's.
        self.play(g,P+'kill',self.board(g,SURFER).id)
        carrier=self.board(g,B);count=len(rattles(carrier));self.assertEqual(count,2)
        self.play(g,A);self.play(g,P+'trigger',carrier.id)
        self.assertEqual(len(rattles(self.board(g,A))),2)
        self.assertEqual((self.board(g,A).attack,self.board(g,A).max_health),(3,6));self.portable(g)

    def test_queued_exact_death_request_round_trips_and_keeps_original_beneficiary(self):
        for branch in ('continue','leave'):
            with self.subTest(branch=branch):
                g=self.game((P+'kill',P+'queue'),board=(A,R1));target=self.board(g,A).id
                self.play(g,P+'kill',self.board(g,R1).id);self.play(g,P+'queue',target)
                self.assertIn('GainDeathrattlesFromDeath',json.dumps(g.snapshot()['resolution_frame']))
                other=self.portable(g);self.choose(g,branch);self.choose(other,branch)
                self.assertEqual(g.snapshot(),other.snapshot())
                self.assertEqual(len(rattles(g.state.entities[target])),1 if branch=='continue'else 0);self.portable(g)
