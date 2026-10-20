import json
import unittest
from dataclasses import asdict
from functools import lru_cache

from hs_sim.cards import build_registry
from hs_sim.cards.neptulon_entry_stat_card import NEPTULON, LIGHTSPAWN, PROGRAM, load_batch
from hs_sim.engine import (AppendageSpec, CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.effects import Buff, ChoiceOption, Damage, Destroy, GrantKeyword, RequestChoice, Silence, Transform
from hs_sim.engine.model import CardClass, CardMetadata, Keyword
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_entry_stats import ACCEPTED, APPLIED
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

COIN, FLY, YETI = 'GAME_005', 'CORE_UNG_809', 'CORE_CS2_182'
P = 'fixture.neptulon_entry.'
SUMMON, COPY, RECRUIT, KILL, SILENCE, MORPH, BOOST, HURT, REBORN, TARGET, UNKNOWN, WATCH, GIANT, LIMB = (
    P+x for x in ('summon','copy','recruit','kill','silence','morph','boost','hurt','reborn','target','unknown','watch','giant','limb'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r = build_registry(); target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    def summon(c, card=FLY):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(card),), SummonCause.capture(c)),)
    def copy(c):
        material = CopyEntryMaterial.capture(c.state,c.state.entities[c.target_id], 'board_copy','current',registry=r,player_id=c.player_id)
        return (SummonByCard(c.player_id,(material,),SummonCause.capture(c)),)
    def recruit(c):
        entry = next((c.state.entities[i]for i in c.state.players[c.player_id].deck if c.state.entities[i].kind==CardType.MINION),None)
        return () if entry is None else (SummonStoredCard(CardReference.capture(entry),c.player_id),)
    bodies={SUMMON:lambda c:summon(c,UNKNOWN if mode=='unknown'else FLY),COPY:copy,RECRUIT:recruit,
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),
        MORPH:lambda c:(Transform(c.target_id,FLY),),BOOST:lambda c:(Buff(c.target_id,2,3,c.source_id),),
        HURT:lambda c:(Damage(c.target_id,3,c.source_id),),REBORN:lambda c:(GrantKeyword(c.target_id,Keyword.REBORN,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,'Explicit ordinary preparation',CardType.SPELL,
            metadata=META,on_play=cid,targeting=None if cid in(SUMMON,RECRUIT)else target))
    r.register_card(CardDefinition(TARGET,'Visible damage recipient',CardType.MINION,attack=1,health=20,metadata=META))
    r.register_card(CardDefinition(UNKNOWN,'Explicit unknown tribe',CardType.MINION,attack=2,health=3,
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None)))
    elemental=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('elemental',))
    r.register_card(CardDefinition(LIMB,'Actual elemental appendage',CardType.MINION,attack=1,health=2,metadata=elemental))
    r.register_card(CardDefinition(GIANT,'Actual elemental colossal entry',CardType.MINION,cost=1,attack=9,health=9,
        metadata=elemental,keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec(LIMB),)))
    if mode in('wait','fail','limb_wait'):
        def observe(c):
            e=c.state.entities.get(c.event.target_id)
            if e is None or e.card_id!=(LIMB if mode=='limb_wait'else FLY) or e.controller!=c.player_id:return()
            if(e.attack,e.health)!=(5,5):raise AssertionError('Elemental must be 5/5 before summon notification')
            if mode=='fail':raise ResolutionError('Explicit late observer failure')
            return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),c.source_id),)
        r.register_behavior(WATCH,observe);r.register_card(CardDefinition(WATCH,'Actual summon boundary observer',CardType.MINION,
            health=20,metadata=META,triggers=(TriggerSpec('minion_summoned',WATCH),)))
    return r


class NeptulonEntryStatTests(unittest.TestCase):
    readers={}

    def game(self,hand=(),board=(),enemy=(TARGET,),mode='normal',other_hand=()):
        if mode in('wait','fail','limb_wait'):board=(WATCH,)+board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=hand,
            board=board,deck=(COIN,FLY)+(COIN,)*8,mana=10,max_mana=10),
            PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=other_hand,board=enemy,
                deck=(COIN,)*10,mana=10,max_mana=10)),seed=0),fixture(mode))

    def play(self,g,cid,target=None,player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid,target_id=target));return eid

    def next_turn(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))

    def body(self,g,cid=FLY,player=1):
        return next(g.state.entities[i]for i in reversed(g.state.players[player].board)if g.state.entities[i].card_id==cid)

    def portable(self,g,mode='normal'):
        if mode not in self.readers:self.readers[mode]=fixture.__wrapped__(mode)
        r=self.readers[mode];saved=g.snapshot()
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)),r).snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for p in(1,2):
            data=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in(ACCEPTED,APPLIED,'enchantment_id','rng_state','battlecry_history'):
                self.assertNotIn('"'+key+'"',data)

    def test_full_root_real_representative_and_two_enchantment_evidence_rows(self):
        d=load_batch();r=fixture()
        self.assertEqual(len(d['official_observations']),4)
        self.assertEqual(len(d['evidence_only']),2)
        self.assertEqual(canonical_digest(asdict(r.card(LIGHTSPAWN))),d['existing_dependencies'][0]['definition_sha256'])
        self.assertEqual((r.card(NEPTULON).cost,r.card(NEPTULON).attack,r.card(NEPTULON).health),(7,7,7))

    def test_real_lightspawn_sees_five_health_before_its_actual_battlecry(self):
        g=self.game((NEPTULON,LIGHTSPAWN),(FLY,));old=g.state.players[1].board[0]
        nept=self.play(g,NEPTULON);self.assertEqual(g.state.entities[nept].attack,7)
        self.assertEqual((g.state.entities[old].attack,g.state.entities[old].health),(1,2))
        self.next_turn(g);target=g.state.players[2].board[0];source=self.play(g,LIGHTSPAWN,target)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(5,5))
        self.assertEqual(g.state.entities[target].health,15)
        applied=next(e.sequence for e in g.events if e.kind==APPLIED and e.target_id==source)
        hit=next(e.sequence for e in g.events if e.kind=='damage_dealt' and e.source_id==source)
        self.assertLess(applied,hit);self.portable(g)

    def test_only_future_elemental_entries_change_hand_deck_and_non_elementals_do_not(self):
        g=self.game((NEPTULON,SUMMON,YETI,FLY));self.play(g,NEPTULON)
        held=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==FLY)
        deck=next(g.state.entities[i]for i in g.state.players[1].deck if g.state.entities[i].card_id==FLY)
        self.assertEqual((held.attack,held.health,deck.attack,deck.health),(1,2,1,2))
        self.next_turn(g);yeti=self.play(g,YETI);self.play(g,SUMMON)
        self.assertEqual((g.state.entities[yeti].attack,g.state.entities[yeti].health),(4,5))
        self.assertEqual((self.body(g).attack,self.body(g).health),(5,5))

    def test_effect_summon_does_not_execute_firefly_battlecry(self):
        g=self.game((NEPTULON,SUMMON));self.play(g,NEPTULON);self.play(g,SUMMON)
        self.assertEqual((self.body(g).attack,self.body(g).health),(5,5));self.assertFalse(g.state.players[1].hand)

    def test_current_copy_material_finishes_before_program_set_and_damage_reset(self):
        g=self.game((NEPTULON,SUMMON,COPY,BOOST,HURT));self.play(g,NEPTULON);self.play(g,SUMMON)
        first=self.body(g).id;self.play(g,BOOST,first);self.play(g,HURT,first);self.play(g,COPY,first)
        self.assertEqual((g.state.entities[first].attack,g.state.entities[first].health),(7,5))
        copied=self.body(g);self.assertNotEqual(copied.id,first);self.assertEqual((copied.attack,copied.health),(5,5));self.portable(g)

    def test_original_deck_minion_physical_recruit_gets_program_at_entry(self):
        g=self.game((NEPTULON,RECRUIT));self.play(g,NEPTULON)
        original=next(i for i in g.state.players[1].deck if g.state.entities[i].card_id==FLY)
        self.play(g,RECRUIT);self.assertEqual(self.body(g).id,original)
        self.assertEqual((self.body(g).attack,self.body(g).health),(5,5));self.portable(g)

    def test_program_survives_original_source_death(self):
        g=self.game((NEPTULON,KILL,SUMMON));source=self.play(g,NEPTULON);self.play(g,KILL,source);self.play(g,SUMMON)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual((self.body(g).attack,self.body(g).health),(5,5));self.portable(g)

    def test_silence_source_does_not_remove_permanent_player_program(self):
        g=self.game((NEPTULON,SILENCE,SUMMON));source=self.play(g,NEPTULON);self.play(g,SILENCE,source);self.play(g,SUMMON)
        self.assertEqual((self.body(g).attack,self.body(g).health),(5,5))

    def test_transform_is_not_another_summon_and_current_set_is_silence_removable(self):
        g=self.game((NEPTULON,MORPH,SUMMON,SILENCE),(YETI,));old=g.state.players[1].board[0]
        self.play(g,NEPTULON);self.play(g,MORPH,old)
        self.assertEqual((g.state.entities[old].attack,g.state.entities[old].health),(1,2))
        self.play(g,SUMMON);new=self.body(g).id;self.play(g,SILENCE,new)
        self.assertEqual((g.state.entities[new].attack,g.state.entities[new].health),(1,2))

    def test_actual_recipient_player_controls_entry_not_original_copy_owner(self):
        g=self.game((NEPTULON,COPY),enemy=(FLY,),other_hand=(SUMMON,))
        self.play(g,NEPTULON);self.play(g,COPY,g.state.players[2].board[0])
        self.assertEqual((self.body(g).attack,self.body(g).health),(5,5))
        g.apply(EndTurn(1));self.play(g,SUMMON,player=2)
        self.assertEqual((self.body(g,player=2).attack,self.body(g,player=2).health),(1,2))

    def test_second_real_program_is_independent_and_does_not_add_stats(self):
        g=self.game((NEPTULON,NEPTULON,SUMMON));self.play(g,NEPTULON);self.next_turn(g)
        second=self.play(g,NEPTULON);self.assertEqual((g.state.entities[second].attack,g.state.entities[second].health),(5,5))
        self.play(g,SUMMON);self.assertEqual((self.body(g).attack,self.body(g).health),(5,5))
        self.assertEqual(len([x for x in g.state.players[1].player_effects if x.spec_id==PROGRAM]),2);self.portable(g)

    def test_reborn_actual_entry_uses_program_after_original_one_health_material(self):
        g=self.game((NEPTULON,SUMMON,REBORN,KILL));self.play(g,NEPTULON);self.play(g,SUMMON)
        old=self.body(g).id;self.play(g,REBORN,old);self.play(g,KILL,old)
        self.assertNotEqual(self.body(g).id,old);self.assertEqual((self.body(g).attack,self.body(g).health),(5,5));self.portable(g)

    def test_full_board_does_not_create_or_apply_an_entry(self):
        g=self.game((NEPTULON,SUMMON),(YETI,)*6);self.play(g,NEPTULON);before=len([e for e in g.events if e.kind==APPLIED])
        self.play(g,SUMMON);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(len([e for e in g.events if e.kind==APPLIED]),before)

    def test_waiting_actual_summon_already_has_stats_and_restores_program_proof(self):
        g=self.game((NEPTULON,SUMMON),mode='wait');self.play(g,NEPTULON);self.play(g,SUMMON)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g,'wait')
        choice=g.state.pending_choice;g.apply(SelectChoice(choice.player_id,choice.id,('continue',)));self.portable(g,'wait')

    def test_late_failure_and_unknown_current_tribe_roll_back_whole_entry(self):
        for mode in('fail','unknown'):
            with self.subTest(mode=mode):
                g=self.game((NEPTULON,SUMMON),mode=mode);self.play(g,NEPTULON);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,SUMMON)
                self.assertEqual(g.snapshot(),saved)

    def test_rehashed_acceptance_instance_forgery_is_rejected(self):
        g=self.game((NEPTULON,SUMMON));self.play(g,NEPTULON);self.play(g,SUMMON);saved=g.snapshot()
        event=next(e for e in saved['events']if e['kind']==ACCEPTED)
        data=dict(event['data']);data['instance_id']+=100;event['data']=tuple(data.items())
        saved['events_hash']=canonical_hash(saved['events'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture())

    def test_direct_colossal_appendage_notification_and_resumed_root_apply_once(self):
        g=self.game((NEPTULON,GIANT),mode='limb_wait');self.play(g,NEPTULON);root=self.play(g,GIANT)
        self.assertIsNotNone(g.state.pending_choice)
        limb=self.body(g,LIMB)
        self.assertEqual((g.state.entities[root].attack,g.state.entities[root].health,limb.attack,limb.health),(5,5,5,5))
        self.portable(g,'limb_wait');c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('continue',)))
        self.assertEqual(len([e for e in g.events if e.kind==APPLIED and e.target_id==root]),1)
        self.assertEqual(len([e for e in g.events if e.kind==APPLIED and e.target_id==limb.id]),1)
        self.portable(g,'limb_wait')


if __name__=='__main__':unittest.main()
