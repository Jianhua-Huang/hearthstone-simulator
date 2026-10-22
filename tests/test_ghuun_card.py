"""Actual G'huun payment, completed Blood Runes and original lowest-health steps."""
from copy import deepcopy
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards.ghuun_card import CARD, load_batch, register_ghuun_card, theft_amount
from hs_sim.engine import (BattlecryRepeatSpec, CardDefinition, CardType, EndTurn, Game,
    PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Damage, Destroy,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_theft import StealHealthToMinion, StealLowestEnemyHealthToMinion
from hs_sim.engine.health_loss import SetHeroHealth
from hs_sim.engine.model import CardClass, CardMetadata, Keyword, Rarity, Runes, TargetSpec, Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference
from hs_sim.engine.colossal import SummonStoredCard
from tools.card_batch import canonical, check_face

P = 'fixture.ghuun.'
META = CardMetadata(True, (CardClass.DEATH_KNIGHT,), Rarity.COMMON)
ONE, TWO, THREE, OTHER, ZERO, UNKNOWN, ACQUIRE, NATURAL, AUTO, HIT, ALTER, AGAIN, DIRECT = (
    P+n for n in ('one','two','three','other','zero','unknown','acquire','natural','auto','hit','alter','again','direct'))
ARMOR, SET_HERO = P+'armor', P+'set-hero'
SMALL, MEDIUM, BIG, SHIELD, IMMUNE, DORMANT, LOCATION, REPEAT, WATCH, EGG, RUNE_MINION, BENEF = (
    P+n for n in ('small','medium','big','shield','immune','dormant','location','repeat','watch','egg','rune-minion','benef'))


@lru_cache(maxsize=None)
def fixture(mode='normal', role='writer'):
    assert role in ('writer','reader')
    r = build_registry(); register_ghuun_card(r)
    r.register_behavior(P+'noop', lambda c: ())
    for cid, runes in ((ONE,Runes(1,0,0)),(TWO,Runes(2,0,0)),(THREE,Runes(3,0,0)),(OTHER,Runes(0,1,1)),(ZERO,None)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=P+'noop',
            metadata=CardMetadata(True,(CardClass.DEATH_KNIGHT,),Rarity.COMMON,runes=runes)))
    r.register_card(CardDefinition(UNKNOWN,UNKNOWN,CardType.SPELL,on_play=P+'noop'))
    r.register_behavior(P+'hatch',lambda c:(Summon(c.player_id,SMALL),))
    for cid,hp,kw,extra in ((SMALL,2,(),{}),(MEDIUM,5,(),{}),(BIG,10,(),{}),(BENEF,8,(),{}),
            (SHIELD,10,(Keyword.DIVINE_SHIELD,),{}),(IMMUNE,10,(Keyword.IMMUNE,),{}),
            (DORMANT,1,(),{'dormant_turns':3}),(REPEAT,10,(),{'battlecry_repeats':(BattlecryRepeatSpec(),)}),
            (EGG,2,(),{'deathrattle':P+'hatch'}),(RUNE_MINION,10,(),{})):
        meta = CardMetadata(True,(CardClass.DEATH_KNIGHT,),Rarity.COMMON,runes=Runes(3,0,0)) if cid==RUNE_MINION else META
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=hp,keywords=kw,metadata=meta,**extra))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=3,on_use=P+'noop',metadata=META))
    def direct(c):
        recipient = next(c.state.entities[i] for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==BENEF)
        return (StealHealthToMinion(MinionReference.capture(recipient),c.state.players[2].hero_id,3,c.source_id),)
    bodies = {ACQUIRE:lambda c:(AddToHand(c.player_id,CARD,c.source_id),),
        NATURAL:lambda c:(Summon(c.player_id,RUNE_MINION),),
        AUTO:lambda c:(CastSpell(c.player_id,THREE,source_id=c.source_id),),
        HIT:lambda c:(Damage(c.target_id,3,c.source_id),),
        ALTER:lambda c:(Transform(c.target_id,BIG),),
        AGAIN:lambda c:(TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id,choices='random'),),
        DIRECT:direct, ARMOR:lambda c:(GainArmor(2,100),),
        SET_HERO:lambda c:(SetHeroHealth(c.state.players[2].hero_id,3,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=TargetSpec() if cid==HIT else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')
                if cid in (ALTER,AGAIN) else None))
    def fail(c): raise ResolutionError('Deliberate Ghuun reaction failure')
    def reenter(c): return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),1),)
    r.register_behavior(P+'fail',fail);r.register_behavior(P+'reenter',reenter)
    if mode!='normal':
        hero_mode = mode in ('wait_hero','atomic_hero')
        event = 'max_health_lost' if hero_mode else 'stats_changed'
        def eligible(c):
            source = c.state.entities.get(c.event.source_id)
            return (source is not None and source.card_id==CARD and
                (hero_mode or dict(c.event.data).get('health_delta')==-1))
        def watch(c):
            if not eligible(c): return ()
            source = c.event.source_id
            if mode in ('atomic_minion','atomic_hero'):
                donor = c.state.entities[c.event.target_id];receiver=c.state.entities[source]
                assert donor.health+receiver.health==(31 if hero_mode else 11)
                return ()
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='bounce':return (ReturnToHand(source),InvokeBehavior(P+'reenter',c.source_id,1,source))
            if mode=='control':return (ChangeControl(source,2),)
            if mode=='kill':return (Destroy(source,c.source_id),)
            return (RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=META,
            triggers=(TriggerSpec(event,WATCH),)))
    return r


class GhuunTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode='normal',seed=382):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(BIG,)*15,
            mana=40,max_mana=40,mana_cap=40),PlayerSetup('HERO_01',hand=enemy_hand,board=enemy,deck=(BIG,)*15,
            mana=40,max_mana=40,mana_cap=40)),seed=seed),fixture(mode))
    def entity(self,g,cid,zone='hand',pid=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[pid],zone) if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,pid=1):
        eid=self.entity(g,cid,pid=pid).id;g.apply(PlayCard(pid,eid,target));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def drain(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def portable(self,g,mode='normal'):
        other=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),fixture(mode,'reader'))
        self.assertEqual(other.state_hash(),g.state_hash());self.assertEqual(g.clone().state_hash(),g.state_hash())
        self.assertEqual(replay(build_replay(g),fixture(mode,'reader')).state_hash(),g.state_hash());return other
    def hero(self,g,pid=2):return g.state.entities[g.state.players[pid].hero_id]
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in ('schema_version','events','events_hash','state_hash')})

    def test_complete_source_two_primary_faces_keep_at_marker_and_explicit_six(self):
        d=load_batch();row,=d['cards'];raw=row['record']
        self.assertEqual(canonical(raw),row['record_sha256']);self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'],{'@':''})
        self.assertIn('@',raw['text']);self.assertEqual(raw['tags']['TAG_SCRIPT_DATA_NUM_1'],6)
        card=fixture().card(CARD);self.assertEqual((card.cost,card.attack,card.health),(8,8,1))
        self.assertEqual(card.metadata.runes,Runes(3,0,0));self.assertFalse(d['cn_calibrated'])

    def test_fresh_real_card_pays_eight_steals_six_and_excludes_its_own_three_runes(self):
        g=self.game(hand=(CARD,));self.assertEqual(theft_amount(g.state,1),6)
        eid=self.play(g,CARD)
        self.assertEqual((g.state.players[1].mana,g.state.entities[eid].health,self.hero(g).health),(32,7,24))
        self.assertEqual((self.hero(g).max_health,self.hero(g).damage),(24,0))
        self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_each_completed_blood_rune_counts_including_multi_rune_cards(self):
        g=self.game(hand=(ONE,TWO,THREE,OTHER,ZERO,CARD))
        for cid in (ONE,TWO,THREE,OTHER,ZERO):self.play(g,cid)
        self.assertEqual(theft_amount(g.state,1),12);eid=self.play(g,CARD)
        self.assertEqual((g.state.entities[eid].health,self.hero(g).health),(13,18));self.portable(g)

    def test_history_before_drawing_this_card_counts_without_a_held_progress_counter(self):
        g=self.game(hand=(THREE,ACQUIRE));self.play(g,THREE);self.play(g,ACQUIRE)
        self.assertEqual(theft_amount(g.state,1),9);eid=self.play(g,CARD)
        self.assertEqual(g.state.entities[eid].health,10);self.portable(g)

    def test_opponent_runes_and_unknown_opponent_metadata_do_not_contribute(self):
        g=self.game(hand=(CARD,),enemy_hand=(THREE,UNKNOWN));g.apply(EndTurn(1))
        self.play(g,THREE,pid=2);self.play(g,UNKNOWN,pid=2);g.apply(EndTurn(2))
        eid=self.play(g,CARD);self.assertEqual(g.state.entities[eid].health,7);self.portable(g)

    def test_automatic_cast_and_natural_summon_do_not_create_rune_hand_roots(self):
        g=self.game(hand=(AUTO,NATURAL,CARD));self.play(g,AUTO);self.play(g,NATURAL)
        self.assertEqual(theft_amount(g.state,1),6);eid=self.play(g,CARD)
        self.assertEqual(g.state.entities[eid].health,7);self.portable(g)

    def test_actual_rune_minion_play_uses_frozen_runes_after_its_face_changes(self):
        g=self.game(hand=(RUNE_MINION,ALTER,CARD));eid=self.play(g,RUNE_MINION);self.play(g,ALTER,eid)
        self.assertEqual(g.state.entities[eid].card_id,BIG);self.assertEqual(theft_amount(g.state,1),9)
        source=self.play(g,CARD);self.assertEqual(g.state.entities[source].health,10);self.portable(g)

    def test_countered_completed_blood_spell_still_contributes_three(self):
        g=self.game(hand=(THREE,CARD),enemy_hand=('EX1_287',));g.apply(EndTurn(1))
        self.play(g,'EX1_287',pid=2);g.apply(EndTurn(2));self.play(g,THREE)
        self.assertEqual(theft_amount(g.state,1),9);eid=self.play(g,CARD)
        self.assertEqual(g.state.entities[eid].health,10);self.portable(g)

    def test_unknown_own_original_rune_metadata_explicitly_rejects_and_rolls_back(self):
        g=self.game(hand=(UNKNOWN,CARD));self.play(g,UNKNOWN);before=g.state_hash()
        with self.assertRaisesRegex(ValueError,'Blood Rune metadata is unknown'):self.play(g,CARD)
        self.assertEqual(g.state_hash(),before)

    def test_second_real_ghuun_counts_the_completed_first_but_neither_counts_its_current_root(self):
        g=self.game(hand=(CARD,CARD));first=self.play(g,CARD);second=self.play(g,CARD)
        self.assertEqual((g.state.entities[first].health,g.state.entities[second].health,self.hero(g).health),(7,10,15))
        self.assertEqual(g.state.players[1].mana,24);self.portable(g)

    def test_repeated_battlecry_in_the_same_unfinished_play_keeps_six_and_pays_once(self):
        g=self.game(hand=(CARD,),board=(REPEAT,));eid=self.play(g,CARD)
        self.assertEqual((g.state.entities[eid].health,self.hero(g).health,g.state.players[1].mana),(13,18,32))
        self.assertEqual(len(g.state.battlecry_history),2);self.portable(g)

    def test_later_indirect_trigger_reads_the_current_completed_prefix_without_new_play(self):
        g=self.game(hand=(CARD,AGAIN));eid=self.play(g,CARD);self.play(g,AGAIN,eid)
        self.assertEqual((g.state.entities[eid].health,self.hero(g).health),(16,15))
        self.assertEqual(len(g.state.play_history),2);self.portable(g)

    def test_current_lowest_minion_dies_then_remaining_budget_moves_to_the_next_lowest(self):
        g=self.game(hand=(CARD,),enemy=(SMALL,MEDIUM));small=self.entity(g,SMALL,'board',2).id
        eid=self.play(g,CARD);self.assertEqual(g.state.entities[small].zone,Zone.GRAVEYARD)
        self.assertEqual((self.entity(g,MEDIUM,'board',2).health,self.hero(g).health,g.state.entities[eid].health),(1,30,7))
        self.assertEqual(g.state.death_history[0].cause.source_id,eid);self.portable(g)

    def test_damaged_minion_uses_remaining_health_instead_of_maximum_and_no_healing_packet(self):
        g=self.game(hand=(HIT,HIT,CARD),enemy=(MEDIUM,SMALL));target=self.entity(g,MEDIUM,'board',2).id
        self.play(g,HIT,target);eid=self.play(g,CARD)
        self.assertFalse(g.state.players[2].board);self.assertEqual((self.hero(g).health,g.state.entities[eid].health),(28,7))
        original_tie=next(e for e in g.events if e.kind=='random_choice')
        self.assertEqual(len(dict(original_tie.data)['candidates']),2)
        self.assertFalse(any(e.kind=='healed' for e in g.events));self.portable(g)

    def test_tied_lowest_characters_have_one_physical_weight_and_requery_after_each_point(self):
        g=self.game(hand=(CARD,),enemy=(MEDIUM,MEDIUM));ids=tuple(g.state.players[2].board)
        before=g._rng.getstate();rng=Random();rng.setstate(before);selected=rng.choice(tuple(sorted(ids)))
        eid=self.play(g,CARD);draws=[e for e in g.events if e.kind=='random_choice']
        self.assertEqual(len(draws),1);self.assertEqual(draws[0].target_id,selected)
        self.assertEqual(tuple(dict(draws[0].data)['candidates']),tuple(sorted(ids)))
        self.assertEqual(g.state.entities[selected].zone,Zone.GRAVEYARD)
        other=next(i for i in ids if i!=selected);self.assertEqual(g.state.entities[other].health,4)
        self.assertEqual(g.state.entities[eid].health,7);self.portable(g)

    def test_non_targeted_transfer_preserves_shield_and_ignores_damage_immunity(self):
        for cid,keyword in ((SHIELD,Keyword.DIVINE_SHIELD),(IMMUNE,Keyword.IMMUNE)):
            with self.subTest(cid=cid):
                g=self.game(hand=(CARD,),enemy=(cid,));eid=self.play(g,CARD);donor=self.entity(g,cid,'board',2)
                self.assertEqual((donor.health,g.state.entities[eid].health),(4,7));self.assertIn(keyword,donor.keywords)
                self.assertFalse(any(e.kind=='damage_dealt' for e in g.events));self.portable(g)

    def test_dormant_minions_and_locations_are_not_lowest_living_character_donors(self):
        g=self.game(hand=(CARD,),enemy=(DORMANT,LOCATION));eid=self.play(g,CARD)
        self.assertEqual((self.hero(g).health,g.state.entities[eid].health),(24,7))
        self.assertEqual(len(g.state.players[2].board),2);self.portable(g)

    def test_deathrattle_new_lowest_enemy_is_seen_by_later_points(self):
        g=self.game(hand=(CARD,),enemy=(EGG,));eid=self.play(g,CARD)
        self.assertFalse(g.state.players[2].board);self.assertEqual((self.hero(g).health,g.state.entities[eid].health),(28,7))
        self.assertEqual(len(g.state.death_history),2);self.portable(g)

    def test_hero_armor_is_preserved_and_damage_deficit_is_not_restored(self):
        g=self.game(hand=(HIT,ARMOR,CARD));self.play(g,HIT,self.hero(g).id);self.play(g,ARMOR)
        eid=self.play(g,CARD);self.assertEqual((self.hero(g).health,self.hero(g).max_health,self.hero(g).damage),(21,24,3))
        self.assertEqual(self.hero(g).armor,100);self.assertEqual(g.state.entities[eid].health,7);self.portable(g)

    def test_hero_reaching_zero_stops_unspent_units_through_the_normal_terminal_pipeline(self):
        g=self.game(hand=(SET_HERO,CARD));self.play(g,SET_HERO);eid=self.play(g,CARD)
        self.assertEqual(self.hero(g).health,0);self.assertEqual(g.state.entities[eid].health,4)
        self.assertEqual(g.state.status,'finished');self.portable(g)

    def test_public_hero_to_minion_transfer_preserves_beneficiary_damage_instead_of_healing(self):
        g=self.game(hand=(HIT,DIRECT),board=(BENEF,));eid=self.entity(g,BENEF,'board').id
        self.play(g,HIT,eid);self.play(g,DIRECT);receiver=g.state.entities[eid]
        self.assertEqual((receiver.health,receiver.max_health,receiver.damage),(8,11,3))
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(27,27));self.portable(g)

    def test_both_sides_are_committed_before_minion_or_hero_notifications(self):
        for mode,enemy in (('atomic_minion',(BIG,)),('atomic_hero',())):
            with self.subTest(mode=mode):
                g=self.game(hand=(CARD,),board=(WATCH,),enemy=enemy,mode=mode);eid=self.play(g,CARD)
                self.assertEqual(g.state.entities[eid].health,7);self.portable(g,mode)

    def test_original_recipient_departure_control_or_death_stops_remaining_units(self):
        for mode in ('bounce','control','kill'):
            with self.subTest(mode=mode):
                g=self.game(hand=(CARD,),board=(WATCH,),enemy=(BIG,),mode=mode);eid=self.play(g,CARD)
                self.assertEqual(self.entity(g,BIG,'board',2).health,9)
                if mode=='bounce':self.assertEqual((g.state.entities[eid].zone,g.state.entities[eid].health),(Zone.BOARD,1))
                if mode=='control':self.assertEqual(g.state.entities[eid].controller,2)
                if mode=='kill':self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
                self.portable(g,mode)

    def test_hero_and_minion_waits_keep_remaining_units_restore_replay_and_failed_resume(self):
        for mode,enemy in (('wait_minion',(BIG,)),('wait_hero',())):
            with self.subTest(mode=mode):
                g=self.game(hand=(CARD,),board=(WATCH,),enemy=enemy,mode=mode);eid=self.play(g,CARD)
                self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,mode);before=g.state_hash()
                with self.assertRaisesRegex(ResolutionError,'Deliberate'):self.choose(g,'fail')
                self.assertEqual(g.state_hash(),before);self.drain(g);self.drain(other)
                self.assertEqual(g.state_hash(),other.state_hash());self.assertEqual(g.state.entities[eid].health,7);self.portable(g,mode)

    def test_failed_first_transfer_reaction_rolls_back_paid_source_histories_and_rng(self):
        g=self.game(hand=(CARD,),board=(WATCH,),enemy=(BIG,),mode='fail');before=g.state_hash()
        with self.assertRaisesRegex(ResolutionError,'Deliberate'):self.play(g,CARD)
        self.assertEqual(g.state_hash(),before)

    def test_new_hero_donor_and_lowest_step_requests_roundtrip_and_reject_invalid_values(self):
        g=self.game(board=(BENEF,));recipient=MinionReference.capture(self.entity(g,BENEF,'board'))
        codec=FrameCodec(g.mechanics,g.registry)
        for req in (StealHealthToMinion(recipient,self.hero(g).id,3,recipient.entity_id),
                StealLowestEnemyHealthToMinion(recipient,6,recipient.entity_id)):
            self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(req)))),req)
        for amount in (True,-1,1.5):
            with self.assertRaises(ValueError):StealLowestEnemyHealthToMinion(recipient,amount,recipient.entity_id)
        with self.assertRaises(ValueError):StealHealthToMinion(recipient,True,1,recipient.entity_id)

    def test_rehashed_wait_cannot_change_remaining_unit_to_boolean(self):
        g=self.game(hand=(CARD,),board=(WATCH,),enemy=(BIG,),mode='wait_minion');self.play(g,CARD)
        saved=json.loads(json.dumps(g.snapshot()));found=[]
        def corrupt(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.StealLowestEnemyHealthToMinion'):
                    value['fields']['amount']=True;found.append(True)
                for child in value.values():corrupt(child)
            elif isinstance(value,list):
                for child in value:corrupt(child)
        corrupt(saved['resolution_frame']);self.assertTrue(found);self.rehash(saved)
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture('wait_minion','reader'))

    def test_combat_query_and_private_original_rune_rows_do_not_leak_an_enemy_hand(self):
        g=self.game(hand=(THREE,CARD),enemy_hand=(CARD,));self.play(g,THREE);self.play(g,CARD)
        own=json.dumps(g.observe(1));enemy=json.dumps(g.observe(2))
        self.assertNotIn('played_face',own+enemy);self.assertNotIn('play_history',own+enemy)
        for pid in (1,2):
            public=json.dumps(g.player_events(pid));self.assertNotIn('blood_rune_ids',public)
        self.portable(g)


if __name__=='__main__':unittest.main()
