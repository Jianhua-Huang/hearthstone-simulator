"""Muradin's actual named weapon retrieval and original-material Deathrattle."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from test_muradin_fabled_hammer_cards import family_registry, production_registry
from hs_sim.cards.muradin_fabled_hammer_cards import ROOT, HAMMER, AVATAR, load_batch
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    TriggerSpec, Zone)
from hs_sim.engine.consumed_cards import ConsumptionProfile, ConsumedCardRecord, validate_profile
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Destroy,
    GainArmor, InvokeBehavior, ModifyWeapon, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.fabled_decks import expand_fabled_cards
from hs_sim.engine.growing_weapon_shuffles import permanent_attack
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import FillHandWithCard
from hs_sim.targets import canonical_digest

P='muradin.test.'; FILL=P+'filler'; WATCH=P+'watch'; VICTIM=P+'victim'


@lru_cache(maxsize=None)
def registry(role, mode=None):
    assert role in ('writer','reader')
    r=family_registry()
    meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    r.register_card(CardDefinition(FILL,FILL,CardType.SPELL,metadata=meta))
    r.register_card(CardDefinition(VICTIM,VICTIM,CardType.MINION,attack=1,health=20,metadata=meta))
    def spell(name,body,target=False):
        cid=P+name;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=target,metadata=meta))
    spell('kill',lambda c:(Destroy(c.target_id,c.source_id),),True)
    spell('silence',lambda c:(Silence(c.target_id),),True)
    spell('bounce',lambda c:(ReturnToHand(c.target_id),),True)
    spell('transform',lambda c:(Transform(c.target_id,VICTIM),),True)
    spell('copy',lambda c:(CopyMinion(c.target_id,c.player_id),),True)
    spell('steal',lambda c:(ChangeControl(c.target_id,c.player_id),),True)
    spell('fill',lambda c:(FillHandWithCard(c.player_id,FILL,c.source_id),))
    def weapon(c):return c.state.players[c.player_id].weapon_id
    spell('break',lambda c:(ModifyWeapon(weapon(c),durability=-99,source_id=c.source_id),))
    spell('buff',lambda c:(ModifyWeapon(weapon(c),attack=8,durability=2,source_id=c.source_id),))
    def fail(c):raise ResolutionError('Muradin deliberate failure')
    r.register_behavior(P+'fail',fail)
    if mode is not None:
        def watch(c):
            e=c.state.entities.get(c.event.target_id)
            wanted=HAMMER if mode=='return_wait' else ROOT
            if e is None or e.card_id!=wanted:return ()
            if mode=='take_fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        event='card_added_to_hand' if mode=='return_wait' else 'stats_changed'
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,
            triggers=(TriggerSpec(event,WATCH),),metadata=meta))
    r.validate();r.freeze();return r


class MuradinNativeTests(unittest.TestCase):
    def game(self, hand=(ROOT,P+'kill'), *, deck_hammer=True, equipped=False,
             mode=None, enemy_hand=(), enemy_weapon=False, enemy_board=()):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,deck=((HAMMER,) if deck_hammer else ())+(FILL,)*8,
                board=(WATCH,) if mode else (),weapon_card_id=HAMMER if equipped else None,
                mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(FILL,)*8,board=enemy_board,
                weapon_card_id=HAMMER if enemy_weapon else None,mana=50,max_mana=50,mana_cap=50)),
            seed=232209),registry('writer',mode))
    def play(self,g,cid,target=None):
        pid=g.state.active_player
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target_id=target));return eid
    def hand(self,g,pid=1,cid=HAMMER):
        return [g.state.entities[i] for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry('reader' if g.registry is registry('writer',self.mode) else 'writer',self.mode)
        self.assertIsNot(r,g.registry)
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('consumed_card_history','held_fabled_weapon','CopyLocalState','rng_state','resolution_frame'):
                self.assertNotIn(key,wire)
        return other
    def test_a00_exact_real_source_family_and_existing_avatar_preserved(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),6)
        self.assertEqual(sum(len(d[k]) for k in ('cards','dependencies','existing_dependencies','evidence_only')),5)
        for key in ('cards','dependencies','existing_dependencies','evidence_only'):
            for row in d[key]:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        r=registry('writer');full=production_registry()
        for cid in (ROOT,HAMMER,AVATAR):self.assertEqual(r.card(cid),full.card(cid))
        self.assertEqual(r.card(ROOT).metadata.classes,(CardClass.SHAMAN,))
        self.assertEqual(expand_fabled_cards((ROOT,),r),(ROOT,HAMMER,AVATAR))
        self.assertEqual(r.fabled[ROOT],full.fabled[ROOT])
        for cid in ('TIME_209e','TIME_209t2e'):self.assertNotIn(cid,r.cards)
    def test_a01_paid_hand_retrieval_gains_stats_and_windfury_but_not_weapon_deathrattle(self):
        g=self.game(hand=(ROOT,HAMMER,P+'kill'),deck_hammer=False)
        original=self.hand(g)[0].id;mid=self.play(g,ROOT);m=g.state.entities[mid]
        self.assertEqual((m.attack,m.max_health),(6,6));self.assertEqual(g.state.players[1].mana,45)
        self.assertTrue({Keyword.RUSH,Keyword.WINDFURY}<=m.keywords)
        self.assertEqual(g.state.entities[original].zone,Zone.SETASIDE);self.assertFalse(self.hand(g))
        self.assertFalse(any(a.behavior_id==g.registry.card(HAMMER).deathrattle for a in m.abilities))
        self.assertEqual(len(g.state.death_history),0);self.assertEqual(len(g.state.consumed_card_history),1)
        self.play(g,P+'kill',mid);returned=self.hand(g)
        self.assertEqual(len(returned),1);self.assertNotEqual(returned[0].id,original)
        self.assertEqual((returned[0].attack,returned[0].durability,returned[0].base_cost),(3,4,6))
        self.assertEqual(permanent_attack(returned[0]),0);self.portable(g)
    def test_a02_deck_retrieval_removes_original_without_draw_or_weapon_death(self):
        g=self.game();original=g.state.players[1].deck[0];mid=self.play(g,ROOT)
        row=g.state.consumed_card_history[0]
        self.assertEqual((row.card.origin.entity_id,row.card.origin.zone),(original,Zone.DECK))
        self.assertEqual(len(g.state.players[1].deck),8);self.assertFalse(g.state.death_history)
        self.assertFalse([e for e in g.events if e.kind=='card_drawn'])
        self.play(g,P+'kill',mid);self.assertEqual(len(self.hand(g)),1);self.portable(g)
    def test_a03_equipped_used_weapon_moves_without_death_and_returns_its_captured_wear(self):
        g=self.game(equipped=True,deck_hammer=False);original=g.state.players[1].weapon_id
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        mid=self.play(g,ROOT);self.assertEqual((g.state.entities[mid].attack,g.state.entities[mid].max_health),(6,5))
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,0)
        self.assertNotIn(Keyword.WINDFURY,g.state.entities[g.state.players[1].hero_id].keywords)
        self.assertFalse(g.state.death_history);self.assertEqual(g.state.entities[original].zone,Zone.SETASIDE)
        self.play(g,P+'kill',mid);self.assertEqual(self.hand(g)[0].durability,3);self.portable(g)
    def test_a04_missing_named_weapon_never_creates_one_or_consumes_rng(self):
        g=self.game(deck_hammer=False);rng=g.snapshot()['rng_state'];mid=self.play(g,ROOT)
        self.assertEqual((g.state.entities[mid].attack,g.state.entities[mid].max_health),(3,2))
        self.assertNotIn(Keyword.WINDFURY,g.state.entities[mid].keywords)
        self.play(g,P+'kill',mid);self.assertFalse(self.hand(g));self.assertFalse(g.state.consumed_card_history)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
    def test_a05_opponent_hand_and_equipment_are_not_eligible(self):
        g=self.game(deck_hammer=False,enemy_hand=(HAMMER,),enemy_weapon=True)
        equipment=g.state.players[2].weapon_id;mid=self.play(g,ROOT)
        self.assertEqual(g.state.entities[mid].attack,3);self.assertEqual(g.state.players[2].weapon_id,equipment)
        self.assertEqual(len(self.hand(g,2)),1);self.assertFalse(g.state.consumed_card_history);self.portable(g)
    def test_b00_multiple_companions_follow_explicit_equipped_then_hand_then_deck_local_policy(self):
        for equipped in (True,False):
            with self.subTest(equipped=equipped):
                g=self.game(hand=(ROOT,HAMMER),equipped=equipped)
                expected=g.state.players[1].weapon_id if equipped else self.hand(g)[0].id
                rng=g.snapshot()['rng_state'];self.play(g,ROOT)
                self.assertEqual(g.state.consumed_card_history[0].card.origin.entity_id,expected)
                self.assertEqual(len(g.state.consumed_card_history),1);self.assertEqual(g.snapshot()['rng_state'],rng)
    def test_b01_actual_weapon_growth_survives_take_return_and_next_weapon_death(self):
        g=self.game(hand=(HAMMER,P+'break',ROOT,P+'kill',P+'break'),deck_hammer=False)
        wid=self.play(g,HAMMER);self.play(g,P+'break');self.assertEqual(g.state.entities[wid].attack,5)
        mid=self.play(g,ROOT);self.assertEqual((g.state.entities[mid].attack,g.state.entities[mid].max_health),(8,6))
        self.play(g,P+'kill',mid);returned=self.hand(g)[0]
        self.assertEqual((returned.attack,permanent_attack(returned)),(5,2))
        copy_id=self.play(g,HAMMER);self.play(g,P+'break')
        self.assertEqual((g.state.entities[copy_id].zone,g.state.entities[copy_id].attack),(Zone.DECK,7));self.portable(g)
    def test_b02_current_equipped_buffs_and_durability_are_frozen_for_return(self):
        g=self.game(hand=(P+'buff',ROOT,P+'kill'),equipped=True,deck_hammer=False)
        self.play(g,P+'buff');mid=self.play(g,ROOT)
        self.assertEqual((g.state.entities[mid].attack,g.state.entities[mid].max_health),(14,8))
        self.play(g,P+'kill',mid);weapon=self.hand(g)[0]
        self.assertEqual((weapon.attack,weapon.durability),(11,6));self.portable(g)
    def test_c00_silence_keeps_held_stats_and_windfury_but_removes_return_payload(self):
        g=self.game(hand=(ROOT,P+'silence',P+'kill'));mid=self.play(g,ROOT)
        self.play(g,P+'silence',mid);m=g.state.entities[mid]
        self.assertEqual((m.attack,m.max_health),(6,6));self.assertIn(Keyword.WINDFURY,m.keywords)
        self.assertNotIn(Keyword.RUSH,m.keywords);self.play(g,P+'kill',mid)
        self.assertFalse(self.hand(g));self.portable(g)
    def test_c01_ordinary_bounce_resets_held_material_and_second_play_has_no_phantom_hammer(self):
        g=self.game(hand=(ROOT,P+'bounce',P+'kill'));mid=self.play(g,ROOT);self.play(g,P+'bounce',mid)
        m=g.state.entities[mid];self.assertEqual((m.zone,m.attack,m.max_health),(Zone.HAND,3,2))
        self.assertNotIn(Keyword.WINDFURY,m.keywords);self.assertEqual(self.play(g,ROOT),mid)
        self.assertEqual(g.state.entities[mid].attack,3);self.play(g,P+'kill',mid)
        self.assertFalse(self.hand(g));self.assertEqual(len(g.state.consumed_card_history),1);self.portable(g)
    def test_c02_ordinary_transform_retires_return_without_touching_private_original(self):
        g=self.game(hand=(ROOT,P+'transform',P+'kill'));mid=self.play(g,ROOT)
        origin=g.state.consumed_card_history[0].card.origin.entity_id
        self.play(g,P+'transform',mid);self.assertEqual(g.state.entities[mid].card_id,VICTIM)
        self.play(g,P+'kill',mid);self.assertFalse(self.hand(g))
        self.assertEqual(g.state.entities[origin].zone,Zone.SETASIDE);self.portable(g)
    def test_c03_current_copy_retains_material_and_each_actual_death_delivers_independently(self):
        g=self.game(hand=(ROOT,P+'copy',P+'kill',P+'kill'));mid=self.play(g,ROOT)
        self.play(g,P+'copy',mid);copy=next(i for i in g.state.players[1].board if i!=mid)
        self.assertEqual((g.state.entities[copy].attack,g.state.entities[copy].max_health),(6,6))
        self.play(g,P+'kill',copy);self.play(g,P+'kill',mid)
        self.assertEqual(len(self.hand(g)),2);self.assertEqual(len(g.state.consumed_card_history),1)
        self.assertNotEqual(self.hand(g)[0].id,self.hand(g)[1].id);self.portable(g)
    def test_c04_transferred_source_returns_material_to_actual_deathrattle_controller(self):
        g=self.game(enemy_hand=(P+'steal',P+'kill'));mid=self.play(g,ROOT);g.apply(EndTurn(1))
        self.play(g,P+'steal',mid);self.play(g,P+'kill',mid)
        self.assertFalse(self.hand(g,1));self.assertEqual(len(self.hand(g,2)),1);self.portable(g)
    def test_c05_full_hand_uses_existing_created_overflow_burn(self):
        g=self.game(hand=(ROOT,P+'fill')+(FILL,)*8,enemy_hand=(P+'kill',))
        mid=self.play(g,ROOT);self.play(g,P+'fill');self.assertEqual(len(g.state.players[1].hand),10)
        g.apply(EndTurn(1));self.play(g,P+'kill',mid)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(self.hand(g))
        burns=[e for e in g.events if e.kind=='card_burned' and g.state.entities[e.target_id].card_id==HAMMER]
        self.assertEqual(len(burns),1);self.portable(g)
    def test_d00_take_notification_wait_is_complete_and_portable_and_failed_choice_rolls_back(self):
        g=self.game(mode='take_wait');mid=self.play(g,ROOT);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((g.state.entities[mid].attack,g.state.entities[mid].max_health),(6,6))
        self.assertIn(Keyword.WINDFURY,g.state.entities[mid].keywords)
        other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.portable(other)
    def test_d01_return_notification_wait_has_original_material_and_portable_death_tail(self):
        g=self.game(mode='return_wait');mid=self.play(g,ROOT);self.play(g,P+'kill',mid)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual((self.hand(g)[0].attack,self.hand(g)[0].durability),(3,4))
        other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.portable(other)
    def test_d02_late_take_reaction_failure_rolls_back_payment_removal_material_and_history(self):
        g=self.game(mode='take_fail',equipped=True);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,ROOT)
        self.assertEqual(g.snapshot(),before);self.portable(g)
    def test_d03_invalid_fabled_profile_and_equipped_nonweapon_material_rejected(self):
        r=registry('writer')
        with self.assertRaises(ValueError):validate_profile(r,ConsumptionProfile(VICTIM,'fabled_weapon'))
        g=self.game(equipped=True);self.play(g,ROOT);row=g.state.consumed_card_history[0]
        with self.assertRaises(ValueError):replace(row.card,origin=replace(row.card.origin,kind=CardType.MINION))
        with self.assertRaises(ValueError):replace(row,after_epoch=row.after_epoch+1)


if __name__=='__main__':unittest.main()
