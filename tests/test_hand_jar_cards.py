"""Actual Toru/Jar play and native frozen hand material use shared lifecycles."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.hand_jar_cards import CARD,JAR,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Destroy,InvokeBehavior,RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec,SummonStats,TargetSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,MoveCard
from test_infinite_cost_card import registry as base_registry,P,PLAIN

G='jar.test.'
ARCHER='CORE_CS2_189'
DORMANT='TIME_063'


def captive(entity):
    return next(a.deathrattle_memory.summon_copy for a in entity.abilities if a.kind=='deathrattle'
        and a.deathrattle_memory is not None and a.deathrattle_memory.spec.kind=='copy_summon')


@lru_cache(None)
def registry(role='writer',mode=None):
    r=base_registry.__wrapped__()
    r.register_behavior(G+'fill',lambda c:())
    r.register_card(CardDefinition(G+'fill','Filler',CardType.SPELL,on_play=G+'fill'))
    for name,expiry in (('buff',False),('temporary',True)):
        r.register_behavior(G+name,lambda c,expiry=expiry:(BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),
            2,3,c.source_id,expires_turn=c.state.turn if expiry else None,cost=CostSpec(delta=-2)),))
        r.register_card(CardDefinition(G+name,name,CardType.SPELL,on_play=G+name,
            targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')))
    if mode:
        def watch(c):
            entity=c.state.entities[c.event.target_id]
            if c.event.player_id!=c.player_id:return ()
            if mode in ('transform','fail_transform'):
                if entity.card_id!=JAR:return ()
                if captive(entity) is None:raise ResolutionError('Jar published before original native memory')
                if mode=='fail_transform':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
                remaining=next((c.state.entities[i] for i in c.state.players[c.player_id].hand
                    if c.state.entities[i].kind==CardType.MINION and c.state.entities[i].card_id!=JAR),None)
                options=[ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),)),
                    ChoiceOption('add','Late minion',(AddToHand(c.player_id,PLAIN,c.source_id),))]
                if remaining is not None:
                    ref=CardReference.capture(remaining)
                    options.extend((ChoiceOption('move','Move next original',(MoveCard(ref,c.player_id,Zone.DECK,position='top',source_id=c.source_id),)),
                        ChoiceOption('buff','Buff next original',(BuffStoredCard(ref,2,3,c.source_id),))))
                return (RequestChoice(c.player_id,tuple(options),c.source_id),)
            if mode=='instant_jar_death':
                return (Destroy(entity.id,c.source_id),) if entity.card_id==JAR else ()
            roots=c.state.card_summon_history
            if not roots or not isinstance(roots[-1].request.materials[0],CopyEntryMaterial) or roots[-1].request.materials[0].profile!='remembered_hand_copy':return ()
            if mode=='fail_release':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
        r.register_behavior(G+'watch',watch)
        event='stored_card_transformed' if mode in ('transform','fail_transform') else 'minion_summoned'
        r.register_card(CardDefinition(G+'watch','Observer',CardType.MINION,health=20,triggers=(TriggerSpec(event,G+'watch'),)))
    r.validate();r.freeze();return r


class HandJarCardTests(unittest.TestCase):
    def game(self,hand=(CARD,PLAIN,P+'kill'),*,board=(),deck=None,enemy_hand=(),mode=None,seat=1):
        own=PlayerSetup('HERO_08',hand=hand,board=(*((G+'watch',) if mode else ()),*board),
            deck=(G+'fill',)*20 if deck is None else deck,mana=50,max_mana=50,mana_cap=50)
        other=PlayerSetup('HERO_08',hand=enemy_hand,deck=(G+'fill',)*20,mana=50,max_mana=50,mana_cap=50)
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own),active_player=seat,seed=283),registry('writer',mode))
    def hand(self,g,cid):return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CARD,target=None,eid=None):
        player=g.state.active_player;eid=self.hand(g,cid) if eid is None else eid
        g.apply(PlayCard(player,eid,target));return eid
    def jars(self,g,zone=Zone.HAND,seat=None):
        seat=g.state.active_player if seat is None else seat
        return [i for i in getattr(g.state.players[seat],zone.value) if g.state.entities[i].card_id==JAR]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def drain(self,g):
        while g.state.pending_choice:self.choose(g)
    def release(self,g,jar=None):
        jar=self.play(g,JAR,eid=jar);self.play(g,P+'kill',jar)
        return jar
    def summons(self,g,cid=PLAIN,seat=None):
        seat=g.state.active_player if seat is None else seat
        return [i for i in g.state.players[seat].board if g.state.entities[i].card_id==cid]
    def portable(self,g,mode=None):
        snap=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snap,registry('reader',mode))
        self.assertEqual(other.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),snap);return other

    def test_a01_full_primary_data_native_empty_jar_and_original_body(self):
        d=load_batch();r=registry()
        self.assertEqual(len(d['official_observations']),4)
        self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(8,7,7))
        self.assertEqual((r.card(JAR).cost,r.card(JAR).attack,r.card(JAR).health),(1,0,1))
        self.assertIn('empty jar',d['dependencies'][0]['record']['text_en'])
        self.assertFalse(r.card(JAR).metadata.collectible)
        self.assertEqual(self.game().observe(1)['version'],'player-view-v101')

    def test_a02_paid_battlecry_replaces_original_hand_minions_in_place_only(self):
        g=self.game((PLAIN,CARD,ARCHER,G+'fill'),enemy_hand=(PLAIN,));old=list(g.state.players[1].hand);enemy=g.snapshot()['state']['players']['2']['hand']
        rng=g._rng.getstate();source=self.play(g)
        self.assertEqual(g.state.players[1].mana,42);self.assertIn(source,g.state.players[1].board)
        self.assertEqual(g.state.players[1].hand,[old[0],old[2],old[3]])
        self.assertEqual(self.jars(g),[old[0],old[2]]);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.snapshot()['state']['players']['2']['hand'],enemy)
        for eid in self.jars(g):self.assertEqual(g.quote_cost(eid).amount,1)

    def test_a03_actual_jar_play_and_death_release_new_original_minion_without_battlecry(self):
        g=self.game((CARD,ARCHER,P+'kill'));original=self.hand(g,ARCHER);self.play(g);jar=self.release(g,original)
        self.assertEqual(g.state.entities[jar].zone,Zone.GRAVEYARD)
        copies=self.summons(g,ARCHER);self.assertEqual(len(copies),1);self.assertNotEqual(copies[0],original)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.assertEqual(len(g.state.battlecry_history),1)

    def test_a04_current_hand_stats_cost_and_attachments_are_frozen_inside_plain_jar(self):
        g=self.game((CARD,PLAIN,G+'buff',P+'kill'));target=self.hand(g,PLAIN);self.play(g,G+'buff',target)
        before=g.state.entities[target];self.play(g)
        jar=g.state.entities[target];self.assertEqual((jar.attack,jar.health,g.quote_cost(target).amount),(0,1,1))
        self.assertEqual(captive(jar).local.base_attack,before.base_attack)
        self.release(g,target);copy=g.state.entities[self.summons(g)[0]]
        self.assertEqual((copy.attack,copy.max_health),(6,8))
        self.assertTrue(any(e.cost==-2 for e in copy.enchantments))

    def test_a05_empty_hand_and_nonminion_hand_do_not_create_fictitious_jars(self):
        for hand in ((CARD,),(CARD,G+'fill',P+'kill')):
            g=self.game(hand);rng=g._rng.getstate();self.play(g)
            self.assertFalse(self.jars(g));self.assertEqual(g._rng.getstate(),rng)

    def test_a06_full_hand_same_faces_have_separate_original_material_and_no_acquisitions(self):
        g=self.game((CARD,)+(PLAIN,)*9);originals=g.state.players[1].hand[1:];before=len(g.state.hand_entries)
        self.play(g);self.assertEqual(self.jars(g),originals);self.assertEqual(len(g.state.hand_entries),before)
        self.assertEqual([captive(g.state.entities[i]).origin.entity_id for i in originals],originals)
        self.assertEqual(len({next(a.id for a in g.state.entities[i].abilities if a.kind=='deathrattle') for i in originals}),9)

    def test_a07_source_dies_without_deleting_existing_jar_payload(self):
        g=self.game((CARD,PLAIN,P+'kill',P+'kill'));source=self.play(g);self.play(g,P+'kill',source)
        self.release(g);self.assertEqual(len(self.summons(g)),1)

    def test_a08_known_fresh_empty_jar_releases_nothing(self):
        g=self.game((JAR,P+'kill'));jar=self.hand(g,JAR);self.assertIsNone(captive(g.state.entities[jar]))
        self.release(g,jar);self.assertFalse(g.state.card_summon_history)

    def test_a09_silence_and_external_transform_remove_captive_payload(self):
        for operation in ('silence','face'):
            g=self.game((CARD,PLAIN,P+operation,P+'kill'));self.play(g);jar=self.jars(g)[0]
            if operation=='face':
                self.play(g,P+operation,jar);self.assertEqual(g.state.entities[jar].card_id,ARCHER)
            else:
                self.play(g,JAR,eid=jar);self.play(g,P+operation,jar);self.play(g,P+'kill',jar)
            self.assertFalse(g.state.card_summon_history)

    def test_a10_current_and_base_board_copies_keep_and_clear_the_native_memory(self):
        g=self.game((CARD,PLAIN,P+'copy',P+'base'));self.play(g);jar=self.play(g,JAR)
        self.play(g,P+'copy',jar);current=self.jars(g,Zone.BOARD)[-1]
        self.assertEqual(captive(g.state.entities[current]),captive(g.state.entities[jar]))
        self.play(g,P+'base',jar);base=self.jars(g,Zone.BOARD)[-1];self.assertIsNone(captive(g.state.entities[base]))

    def test_a11_bounce_resets_jar_to_known_empty_printed_state(self):
        g=self.game((CARD,PLAIN,P+'bounce',P+'kill'));self.play(g);jar=self.play(g,JAR)
        self.play(g,P+'bounce',jar);self.assertIsNone(captive(g.state.entities[jar]));self.release(g,jar)
        self.assertFalse(g.state.card_summon_history)

    def test_a12_current_hand_copy_keeps_independent_captive_payload(self):
        g=self.game((CARD,PLAIN,P+'hand_copy',P+'kill'));self.play(g);original=self.jars(g)[0]
        self.play(g,P+'hand_copy',original);copy=self.jars(g)[-1]
        self.assertNotEqual(original,copy);self.assertEqual(captive(g.state.entities[original]),captive(g.state.entities[copy]))
        self.release(g,copy);self.assertEqual(len(self.summons(g)),1);self.assertIn(original,g.state.players[1].hand)

    def test_a13_repeated_real_battlecry_nests_jars_instead_of_overwriting_first_captive(self):
        g=self.game((CARD,PLAIN,P+'kill',P+'kill'),board=(P+'double',));self.play(g)
        outer=self.jars(g)[0];self.assertEqual(captive(g.state.entities[outer]).card_id,JAR)
        self.release(g,outer);inner=self.jars(g,Zone.BOARD)[0]
        self.assertEqual(captive(g.state.entities[inner]).card_id,PLAIN)
        self.play(g,P+'kill',inner);self.assertEqual(len(self.summons(g)),1)

    def test_a14_transferred_jar_releases_for_actual_new_controller(self):
        g=self.game((CARD,PLAIN,P+'transfer'),enemy_hand=(P+'kill',));self.play(g);jar=self.jars(g)[0]
        self.play(g,P+'transfer',jar);g.apply(EndTurn(1));self.release(g,jar)
        self.assertEqual(len(self.summons(g,seat=2)),1);self.assertEqual(len(self.summons(g,seat=1)),0)

    def test_a15_summoned_jar_has_payload_before_immediate_entry_death(self):
        g=self.game(mode='instant_jar_death');self.play(g);jar=self.play(g,JAR)
        self.assertEqual(g.state.entities[jar].zone,Zone.GRAVEYARD);self.assertEqual(len(self.summons(g)),1)

    def test_a16_hand_origin_dormant_minion_uses_fresh_printed_dormancy(self):
        g=self.game((CARD,DORMANT,'CORE_EX1_302'));self.play(g);jar=self.play(g,JAR)
        self.play(g,'CORE_EX1_302',jar)
        copy=g.state.entities[self.summons(g,DORMANT)[0]]
        self.assertIsNotNone(copy.dormancy);self.assertEqual(copy.dormancy.remaining_turns,5)

    def test_a17_original_temporary_attachment_clock_does_not_restart_on_release(self):
        g=self.game((CARD,PLAIN,G+'temporary',P+'kill'));self.play(g,G+'temporary',self.hand(g,PLAIN));self.play(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.release(g)
        copy=g.state.entities[self.summons(g)[0]];self.assertEqual((copy.attack,copy.max_health),(4,5))

    def test_a18_pending_first_transform_recovers_clones_and_replays_with_remaining_originals(self):
        g=self.game((CARD,PLAIN,ARCHER),mode='transform');self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.jars(g)),1)
        other=self.portable(g,'transform');self.drain(g);self.drain(other)
        self.assertEqual(other.snapshot(),g.snapshot());self.assertEqual(len(self.jars(g)),2)

    def test_a19_late_acquisition_is_excluded_and_moved_original_is_not_retargeted(self):
        g=self.game((CARD,PLAIN,ARCHER),mode='transform');self.play(g);self.choose(g,'move');self.drain(g)
        self.assertEqual(len(self.jars(g)),1);self.assertEqual(g.state.entities[g.state.players[1].deck[0]].card_id,ARCHER)
        g=self.game((CARD,PLAIN),mode='transform');self.play(g);self.choose(g,'add');self.drain(g)
        self.assertEqual(len(self.jars(g)),1);self.assertIn(PLAIN,[g.state.entities[i].card_id for i in g.state.players[1].hand])

    def test_a20_each_actual_transformation_captures_its_then_current_original_material(self):
        g=self.game((CARD,PLAIN,ARCHER),mode='transform');self.play(g);self.choose(g,'buff');self.drain(g)
        second=captive(g.state.entities[self.jars(g)[1]])
        self.assertTrue(any(e.attack==2 and e.health==3 for e in second.local.enchantments))

    def test_a21_failed_first_transform_rolls_back_complete_paid_card_action(self):
        g=self.game(mode='fail_transform');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_a22_pending_failed_selection_and_release_wait_use_shared_recovery(self):
        g=self.game(mode='transform');self.play(g);snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),snap);self.drain(g)
        g=self.game(mode='release_wait');self.play(g);self.release(g);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g,'release_wait');self.drain(g);self.drain(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_a23_captive_names_only_are_visible_after_zone_authorization_for_both_seats(self):
        for seat in (1,2):
            g=self.game(seat=seat);self.play(g)
            own=json.dumps(g.observe(seat));enemy=json.dumps(g.observe(3-seat))
            self.assertIn('deathrattle_copies',own);self.assertIn(PLAIN,own);self.assertNotIn(PLAIN,enemy)
            for value in (own,enemy):
                for key in ('remembered_hand_copy','summon_copy','next_attachment_id','captured_action'):
                    self.assertNotIn(key,value)
            self.play(g,JAR)
            for viewer in (1,2):self.assertIn('deathrattle_copies',json.dumps(g.observe(viewer)))

    def test_a24_strict_hand_recipe_and_rehashed_future_native_memory_reject(self):
        g=self.game();original=g.state.entities[self.hand(g,PLAIN)]
        material=CopyEntryMaterial.capture(g.state,original,'remembered_hand_copy','current',registry=registry(),player_id=1)
        for changes in (dict(mode='base',local=None),dict(stats=SummonStats(1,1)),dict(dormant_entry=True)):
            with self.assertRaises(ValueError):replace(material,**changes)
        for zone in (Zone.DECK,Zone.BOARD):
            with self.assertRaises(ValueError):replace(material,origin=replace(material.origin,zone=zone))
        self.play(g);snap=g.snapshot();jar=self.jars(g)[0]
        row=next(a['deathrattle_memory'] for a in snap['state']['entities'][str(jar)]['abilities'] if a['deathrattle_memory'] is not None)
        row['summon_copy']['captured_action']=g.state.action_number+1
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises((SnapshotError,ValueError)) as error:Game.from_snapshot(snap,registry('reader'))
        self.assertIn('Future physical copy acceptance facts',str(error.exception))

    def test_a25_actual_repeated_early_deathrattle_and_full_board_use_shared_capacity(self):
        g=self.game((CARD,PLAIN,P+'trigger'));self.play(g);jar=self.play(g,JAR);self.play(g,P+'trigger',jar)
        self.assertEqual(len(self.summons(g)),2);self.assertIn(jar,g.state.players[1].board)
        g=self.game((CARD,PLAIN,P+'trigger'),board=(PLAIN,)*5);self.play(g);jar=self.play(g,JAR)
        rng=g._rng.getstate();self.play(g,P+'trigger',jar)
        self.assertEqual(len(self.summons(g)),5);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g._rng.getstate(),rng)

    def test_a26_failed_release_rolls_back_death_payment_material_and_player_information(self):
        g=self.game(mode='fail_release');self.play(g);jar=self.play(g,JAR);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g,P+'kill',jar)
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
