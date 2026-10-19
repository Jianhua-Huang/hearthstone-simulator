"""Real current-turn whole-card execution and its owed natural ending boundary."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.slice_and_dice_card import CARD,load_batch,register_slice_and_dice_card
from hs_sim.engine import (CardDefinition,CardMetadata,CardClass,CardType,Concede,EndTurn,EndTurnSpec,
    Game,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,SnapshotError,SpellRepeatSpec,
    TargetSpec,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,GainArmor,InvokeBehavior,RequestChoice,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.natural_turn_end import (FinishNaturalTurnEnd,NaturalTurnEndRequest,
    RequestNaturalTurnEnd,validate_record)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.turn_scheduling import QueueTurns
from hs_sim.targets import canonical_digest

P='slice.test.'
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)


def registry(mode=None):
    r=build_registry() if mode=='counter' else Registry('slice-and-dice-native-tests-v1')
    if CARD not in r.cards:register_slice_and_dice_card(r)
    r.register_card(CardDefinition(P+'hero','Hero',CardType.HERO,health=100,
        metadata=CardMetadata(False,(CardClass.MAGE,),Rarity.COMMON)))
    r.register_behavior(P+'mark',lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(P+'second',lambda c:(GainArmor(c.player_id,2),))
    r.register_behavior(P+'battlecry',lambda c:(GainArmor(c.player_id,3),))
    r.register_behavior(P+'combo',lambda c:(GainArmor(c.player_id,5),))
    r.register_behavior(P+'fail',lambda c:(AddToHand(c.player_id,'missing.slice'),))
    r.register_behavior(P+'bad',lambda c:(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if c.cast.origin=='effect' else ())
    r.register_behavior(P+'lethal',lambda c:(Damage(c.state.players[2].hero_id,200,c.source_id),)
        if c.cast.origin=='effect' else ())
    r.register_behavior(P+'extra',lambda c:(QueueTurns((c.player_id,),c.source_id),))
    r.register_behavior(P+'bolt',lambda c:(Damage(c.target_id,2,c.source_id),))
    for name in ('mark','second','bad','lethal','extra'):
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META))
    for name,relation in (('bolt','any'),('friendly','friendly')):
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+'bolt',metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,Zone.HERO),kinds=(CardType.MINION,CardType.HERO),relation=relation)))
    r.register_card(CardDefinition(P+'minion','Minion',CardType.MINION,cost=1,attack=2,health=3,
        on_play=P+'second',battlecry=P+'battlecry',combo=P+'combo',keywords=(Keyword.COMBO,),metadata=META))
    r.register_card(CardDefinition(P+'plain','Plain',CardType.MINION,attack=1,health=2,metadata=META))
    r.register_card(CardDefinition(P+'weapon','Weapon',CardType.WEAPON,cost=1,attack=1,durability=2,
        battlecry=P+'mark',metadata=META))
    r.register_card(CardDefinition(P+'location','Location',CardType.LOCATION,cost=1,durability=3,
        on_use=P+'mark',metadata=META))
    r.register_behavior(P+'power',lambda c:(CastSpell(c.player_id,P+'mark',c.source_id),Summon(c.player_id,P+'plain')))
    r.register_card(CardDefinition(P+'power','Power',CardType.HERO_POWER,on_use=P+'power'))
    r.register_card(CardDefinition(P+'hero_card','Hero card',CardType.HERO,cost=1,health=100,
        hero_card=True,hero_armor=4,initial_hero_power=P+'power',on_play=P+'mark',
        metadata=CardMetadata(True,(CardClass.ROGUE,),Rarity.LEGENDARY)))
    r.register_card(CardDefinition(P+'double','Double spells',CardType.MINION,health=20,
        spell_repeats=(SpellRepeatSpec(2),),metadata=META))
    if mode in ('paid_wait','end_wait','end_auto'):
        def watch(c):
            event=c.event
            if mode=='paid_wait':
                if event.source_id is None or c.state.entities[event.source_id].card_id!=CARD:return ()
            elif event.player_id!=1:return ()
            if mode=='end_auto':return (CastSpell(c.player_id,CARD,c.source_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        trigger=TriggerSpec('card_played',P+'watch') if mode=='paid_wait' else TriggerSpec('turn_ended',P+'watch',EndTurnSpec())
        r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=20,triggers=(trigger,),metadata=META))
    return r


class SliceAndDiceTests(unittest.TestCase):
    def game(self,hand=(CARD,),*,board=(),mode=None,double=False):
        self.mode=mode
        if mode in ('paid_wait','end_wait','end_auto'):board=(*board,P+'watch')
        if double:board=(*board,P+'double')
        enemy_hand=('CORE_EX1_287',) if mode=='counter' else (P+'mark',)
        return Game.from_scenario(Scenario((PlayerSetup(P+'hero',hand=hand,board=board,deck=(P+'mark',)*12,
            hero_power_card_id=P+'power',mana=30,max_mana=30,mana_cap=30),PlayerSetup(P+'hero',hand=enemy_hand,
            deck=(P+'mark',)*12,mana=30,max_mana=30,mana_cap=30)),seed=271),registry(mode))
    def play(self,g,cid=CARD,pid=1,target=None):
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target));return eid
    def armor(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].armor
    def ends(self,g):return [e for e in g.events if e.kind=='turn_ended']
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));r=registry(self.mode)
        other=Game.from_snapshot(saved,r);self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in ('natural_turn_end_requests','accepted_event','ended_event','resolution_frame','before_state'):
                self.assertNotIn('"'+field+'"',public)
        return other
    def rehash(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        return saved

    def test_a00_complete_original_source_primary_faces_and_central_metadata(self):
        row,=load_batch()['cards'];raw=row['record'];card=build_registry().card(CARD)
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertEqual((card.kind,card.cost),(CardType.SPELL,5));self.assertEqual(raw['tags']['DONT_PICK_FROM_SUBSETS'],1)
        self.assertEqual(len(load_batch()['official_observations']),2)

    def test_a01_empty_replay_still_pays_five_then_completes_play_and_normal_turn(self):
        g=self.game();source=self.play(g)
        self.assertEqual(g.state.players[1].mana,25);self.assertEqual((g.state.turn,g.state.active_player),(2,2))
        self.assertEqual(len(self.ends(g)),1);self.assertEqual(len(g.state.players[2].hand),2)
        row,=g.state.natural_turn_end_requests;self.assertEqual(row.status,'applied')
        played=next(e for e in g.events if e.kind=='card_played' and e.source_id==source)
        self.assertLess(played.sequence,row.ended_event);self.assertTrue(g.state.cast_history[-1].completed)
        self.assertFalse(g.state.whole_card_replay_ledger.stack);self.portable(g)

    def test_a02_duplicate_occurrences_replay_in_original_order_without_extra_payment(self):
        g=self.game((P+'mark',P+'second',P+'mark',CARD))
        for name in (P+'mark',P+'second',P+'mark'):self.play(g,name)
        self.play(g);self.assertEqual(self.armor(g),8);self.assertEqual(g.state.players[1].mana,25)
        root=g.state.whole_card_replay_ledger.roots[-1];self.assertEqual(len(root.selection.selected_ids),3)
        casts=[c.card_id for c in g.state.cast_history if c.origin=='effect']
        self.assertEqual(casts,[P+'mark',P+'second',P+'mark']);self.portable(g)

    def test_a03_enemy_targets_are_preferred_and_friendly_only_legal_targets_remain(self):
        for name in (P+'bolt',P+'friendly'):
            with self.subTest(name=name):
                g=self.game((name,CARD));own=g.state.players[1].hero_id;enemy=g.state.players[2].hero_id
                self.play(g,name,target=own);self.play(g)
                cast=next(c for c in g.state.cast_history if c.card_id==name and c.origin=='effect')
                self.assertEqual(cast.target_id,enemy if name==P+'bolt' else own)
                self.assertEqual(g.state.entities[enemy].health,98 if name==P+'bolt' else 100)

    def test_a04_all_four_physical_kinds_reenter_and_run_current_complete_bodies(self):
        names=(P+'minion',P+'weapon',P+'location',P+'hero_card');g=self.game((*names,CARD))
        for name in names:self.play(g,name)
        self.play(g);ledger=g.state.whole_card_replay_ledger
        self.assertEqual({c.kind for c in ledger.children},{CardType.MINION,CardType.WEAPON,CardType.LOCATION,CardType.HERO})
        self.assertTrue(all(c.status.value=='finished' for c in ledger.children))
        self.assertEqual(g.state.players[1].mana,21);self.assertEqual(len(self.ends(g)),1);self.portable(g)

    def test_a05_previous_turn_and_opponent_cards_do_not_enter_current_history(self):
        g=self.game((P+'mark',CARD));self.play(g,P+'mark');g.apply(EndTurn(1))
        self.play(g,P+'mark',pid=2);g.apply(EndTurn(2));self.play(g,P+'mark');self.play(g)
        self.assertEqual(self.armor(g),3);self.assertEqual(self.armor(g,2),1)
        self.assertEqual(len(g.state.whole_card_replay_ledger.roots[-1].selection.selected_ids),1)

    def test_a06_automatic_casts_and_summons_are_not_extra_paid_hand_occurrences(self):
        g=self.game();g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.play(g)
        self.assertEqual(self.armor(g),1);self.assertEqual(g.state.whole_card_replay_ledger.roots[-1].selection.selected_ids,())

    def test_a07_countered_same_face_is_excluded_and_does_not_recursively_replay(self):
        g=self.game((CARD,CARD),mode='counter');g.apply(EndTurn(1));self.play(g,'CORE_EX1_287',pid=2);g.apply(EndTurn(2))
        self.play(g);self.assertEqual(g.state.active_player,1);self.assertFalse(g.state.natural_turn_end_requests)
        self.play(g);self.assertEqual(g.state.whole_card_replay_ledger.roots[-1].selection.selected_ids,())
        self.assertEqual(len(g.state.natural_turn_end_requests),1);self.portable(g)

    def test_b00_two_real_cast_requests_end_the_original_interval_only_once(self):
        g=self.game((P+'mark',CARD),double=True);self.play(g,P+'mark');self.play(g)
        self.assertEqual(len([c for c in g.state.cast_history if c.card_id==CARD]),2)
        self.assertEqual([r.status for r in g.state.natural_turn_end_requests],['applied','stale'])
        self.assertEqual(len(self.ends(g)),1);self.assertEqual((g.state.turn,g.state.active_player),(2,2));self.portable(g)

    def test_b01_stale_duplicate_does_not_end_an_extra_turn_of_the_same_player(self):
        g=self.game((P+'extra',CARD),double=True);self.play(g,P+'extra');self.play(g)
        self.assertEqual((g.state.turn,g.state.active_player),(2,1));self.assertEqual(len(self.ends(g)),1)
        self.assertEqual([r.status for r in g.state.natural_turn_end_requests],['applied','stale']);self.portable(g)

    def test_b02_post_play_wait_retains_owed_end_and_restores_after_paid_completion(self):
        g=self.game((P+'mark',CARD),mode='paid_wait');self.play(g,P+'mark');self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(self.ends(g))
        self.assertEqual(g.state.natural_turn_end_requests[0].status,'pending');other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(self.ends(g)),1);self.assertEqual(g.state.active_player,2)

    def test_b03_natural_end_wait_preserves_applied_request_and_resumes_normal_start(self):
        g=self.game(mode='end_wait');self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.natural_turn_end_requests[0].status,'applied')
        self.assertEqual(g.state.active_player,1);other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.active_player,2);self.assertEqual(len(self.ends(g)),1)

    def test_b04_failed_replayed_body_rolls_back_payment_replay_rng_and_end_requests(self):
        g=self.game((P+'bad',CARD));self.play(g,P+'bad');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_b05_failed_post_play_choice_restores_original_pending_end_obligation(self):
        g=self.game(mode='paid_wait');self.play(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(len(self.ends(g)),1)

    def test_b06_lethal_replay_abandons_turn_end_instead_of_starting_a_new_turn(self):
        g=self.game((P+'lethal',CARD));self.play(g,P+'lethal');self.play(g)
        self.assertEqual(g.state.status,'finished');self.assertFalse(self.ends(g));self.assertFalse(g.state.natural_turn_end_requests)
        self.portable(g)

    def test_b07_concede_during_pending_end_closes_request_without_ending_the_turn(self):
        g=self.game(mode='paid_wait');self.play(g);g.apply(Concede(1))
        self.assertEqual(g.state.status,'finished');self.assertEqual(g.state.natural_turn_end_requests[0].status,'interrupted')
        self.assertFalse(self.ends(g));self.portable(g)

    def test_b08_automatic_replay_during_existing_end_does_not_end_the_next_turn(self):
        g=self.game((P+'mark',),mode='end_auto');self.play(g,P+'mark');g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player,2);self.assertEqual(len(self.ends(g)),1)
        self.assertFalse(g.state.natural_turn_end_requests);self.assertEqual(self.armor(g),2);self.portable(g)

    def test_c00_codec_and_player_projection_keep_the_original_request_private(self):
        g=self.game(mode='paid_wait');self.play(g);row,=g.state.natural_turn_end_requests
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(row)),row)
        self.assertEqual(codec.decode(codec.encode(FinishNaturalTurnEnd(row.cast_id))),FinishNaturalTurnEnd(row.cast_id))
        with self.assertRaises(ValueError):RequestNaturalTurnEnd(True)
        with self.assertRaises(ValueError):replace(row,owner_turn_id=0)
        with self.assertRaises(ValueError):NaturalTurnEndRequest(row.cast_id,row.owner_turn_id,0,status='applied')
        self.portable(g)

    def test_c01_saved_pending_obligation_cannot_lose_or_advance_its_real_tail(self):
        g=self.game(mode='paid_wait');self.play(g);saved=json.loads(json.dumps(g.snapshot()))
        tag='hs_sim.engine.natural_turn_end.FinishNaturalTurnEnd'
        def locate(value):
            if isinstance(value,list):
                for i,item in enumerate(value):
                    if isinstance(item,dict) and tag in item.values():return value,i
                    result=locate(item)
                    if result:return result
            elif isinstance(value,dict):
                for item in value.values():
                    result=locate(item)
                    if result:return result
        for mode in ('drop','advance','row'):
            with self.subTest(mode=mode):
                bad=deepcopy(saved)
                if mode=='row':bad['state']['natural_turn_end_requests'].clear()
                else:
                    found=locate(bad['resolution_frame']);self.assertIsNotNone(found);items,index=found
                    item=items.pop(index)
                    if mode=='advance':items.insert(0,item)
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry(self.mode))

    def test_c02_applied_request_requires_the_actual_owner_end_event_and_current_schema(self):
        g=self.game();source=self.play(g);saved=json.loads(json.dumps(g.snapshot()))
        event=next(e for e in g.events if e.kind=='card_played' and e.source_id==source)
        bad=deepcopy(saved);row=bad['state']['natural_turn_end_requests'][0]
        row['ended_event']=event.sequence;row['closed_event']=event.sequence
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry())
        bad=deepcopy(saved);bad['schema_version']=443
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())


if __name__=='__main__':unittest.main()
