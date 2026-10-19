"""Real Picklock roots and native numbers across ordinary payment/lifecycle."""
from copy import deepcopy
from functools import lru_cache
import json,unittest
from hs_sim.cards.remaining_mana_numbers_card import CARD,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.battlecry_sources import BattlecryHistoryQuery,RepeatBattlecries,TriggerBattlecry
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChoiceOption,GainTemporaryMana,InvokeBehavior,RequestChoice,
    SpendMana,Summon,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import CostSpec,PaymentType,TargetSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from test_infinite_cost_card import registry as base_registry,P,PLAIN

G='picklock.test.'


@lru_cache(None)
def registry(role='writer',mode=None):
    r=base_registry.__wrapped__()
    r.register_card(CardDefinition(G+'big','Large target',CardType.MINION,attack=1,health=100))
    bodies={
        'fill':lambda c:(), 'one':lambda c:(),
        'gain':lambda c:(GainTemporaryMana(c.player_id,3),),
        'spend':lambda c:(SpendMana(c.player_id,3,c.source_id),),
        'summon':lambda c:(Summon(c.player_id,CARD),),
        'buff':lambda c:(BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),2,3,c.source_id),),
        'health':lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(payment=PaymentType.HEALTH),c.source_id),),
        'morph':lambda c:(Transform(c.target_id,PLAIN),),
        'trigger':lambda c:(TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id,
            target_id=c.state.players[3-c.player_id].board[0],targeting='explicit'),),
        'history':lambda c:(RepeatBattlecries(c.player_id,c.state.players[c.player_id].board[0],
            BattlecryHistoryQuery(origins=('effect',))),),
    }
    for name,body in bodies.items():
        r.register_behavior(G+name,body)
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly') if name in ('buff','health') else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)) if name in ('morph','trigger') else None
        r.register_card(CardDefinition(G+name,name,CardType.SPELL,cost=1 if name=='one' else 0,on_play=G+name,targeting=targeting))
    if mode:
        def watch(c):
            source=c.state.entities[c.event.source_id]
            if source.card_id!=CARD:return ()
            if mode=='counter':return (CounterMinion(dict(c.event.data)['window_id']),)
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            others=[c.state.entities[i].base_cost for i in c.state.players[c.player_id].hand if i!=source.id and c.state.entities[i].card_id==CARD]
            if (source.base_cost,source.base_attack,source.base_health)!=(c.event.amount,)*3 or others!=[1]:
                raise ResolutionError('Payment capture lost accepted source or other live hand numbers')
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(G+'watch',watch)
        r.register_card(CardDefinition(G+'watch','Observer',CardType.MINION,health=30,
            triggers=(TriggerSpec('minion_counter_check' if mode=='counter' else 'mana_spent',G+'watch'),)))
    r.validate();r.freeze();return r


class RemainingManaNumbersTests(unittest.TestCase):
    def game(self,hand=(CARD,),*,mana=7,board=(),deck=None,enemy_board=(G+'big',),enemy_mana=4,mode=None,seat=1):
        own=PlayerSetup('HERO_08',hand=hand,board=(*((G+'watch',) if mode else ()),*board),
            deck=(G+'fill',)*20 if deck is None else deck,mana=mana,max_mana=max(7,mana),mana_cap=30)
        other=PlayerSetup('HERO_08',board=enemy_board,deck=(G+'fill',)*20,mana=enemy_mana,max_mana=7,mana_cap=30)
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own),active_player=seat,seed=286),registry('writer',mode))
    def hand(self,g,cid):return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,eid=None):
        eid=self.hand(g,cid) if eid is None else eid;g.apply(PlayCard(g.state.active_player,eid,target));return eid
    def victim(self,g):return g.state.players[3-g.state.active_player].board[0]
    def raw(self,g,eid):e=g.state.entities[eid];return e.base_cost,e.base_attack,e.base_health
    def stats(self,g,eid):e=g.state.entities[eid];return e.attack,e.max_health
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        snap=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snap,registry('reader',mode))
        self.assertEqual(other.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),snap);return other
    def rehash(self,snap):
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')});return snap

    def test_a01_complete_real_source_and_hand_floor_at_zero_one_seven_and_fifteen(self):
        d=load_batch();self.assertEqual(len(d['cards']),1);self.assertEqual(len(d['official_observations']),2)
        for mana in (0,1,7,15):
            g=self.game(mana=mana);eid=self.hand(g,CARD);self.assertEqual(self.raw(g,eid),(max(1,mana),)*3)
            self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,max(1,mana))

    def test_a02_quotes_legal_actions_and_both_observations_are_pure(self):
        g=self.game();before=g.snapshot();eid=self.hand(g,CARD)
        self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,7)
        g.legal_actions();g.observe(1);g.observe(2);self.assertEqual(g.snapshot(),before)

    def test_a03_actual_paid_minion_freezes_prepaid_stats_and_battlecry_damage(self):
        g=self.game();victim=self.victim(g);eid=self.play(g,CARD,victim)
        self.assertEqual(self.raw(g,eid),(7,7,7));self.assertEqual(g.state.entities[victim].damage,7)
        self.assertEqual(g.state.players[1].mana,0);self.assertEqual(len(g.state.cost_use_history),1)
        self.assertEqual(g.state.battlecry_history[0].payload.remaining_mana_number,7);self.portable(g)

    def test_a04_zero_mana_cannot_pay_the_printed_minimum(self):
        g=self.game(mana=0);before=g.snapshot()
        with self.assertRaises((IllegalAction,ResolutionError)):self.play(g,CARD,self.victim(g))
        self.assertEqual(g.snapshot(),before)

    def test_a05_optional_empty_enemy_minion_target_and_illegal_targets(self):
        g=self.game(enemy_board=());eid=self.play(g,CARD);self.assertEqual(self.stats(g,eid),(7,7))
        for friendly in (True,False):
            g=self.game(board=(PLAIN,));before=g.snapshot();target=g.state.players[1].board[0] if friendly else g.state.players[2].hero_id
            with self.assertRaises((IllegalAction,ResolutionError)):self.play(g,CARD,target)
            self.assertEqual(g.snapshot(),before)

    def test_a06_ordinary_explicit_consumption_updates_held_numbers_without_playing(self):
        g=self.game((CARD,G+'spend'));eid=self.hand(g,CARD);self.play(g,G+'spend')
        self.assertEqual(self.raw(g,eid),(4,4,4));self.assertFalse(g.state.battlecry_history)

    def test_a07_temporary_mana_can_increase_numbers_above_permanent_crystals(self):
        g=self.game((CARD,G+'gain'));eid=self.hand(g,CARD);self.play(g,G+'gain')
        self.assertEqual((g.state.players[1].mana,g.state.players[1].max_mana),(10,7));self.assertEqual(self.raw(g,eid),(10,10,10))

    def test_a08_other_card_payment_updates_current_held_numbers(self):
        g=self.game((CARD,G+'one'));eid=self.hand(g,CARD);self.play(g,G+'one')
        self.assertEqual(self.raw(g,eid),(6,6,6));self.assertFalse(g.state.battlecry_history)

    def test_a09_local_discount_does_not_reduce_frozen_stats_or_battlecry_number(self):
        g=self.game((CARD,P+'discount'));eid=self.hand(g,CARD);victim=self.victim(g);self.play(g,P+'discount',eid)
        self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,4);self.play(g,CARD,victim)
        self.assertEqual(self.stats(g,eid),(6,6));self.assertEqual(g.state.entities[victim].damage,6);self.assertEqual(g.state.players[1].mana,2)

    def test_a10_local_zero_price_keeps_raw_number_and_spends_zero(self):
        g=self.game((CARD,P+'zero'));eid=self.hand(g,CARD);self.play(g,P+'zero',eid);self.play(g,CARD,self.victim(g))
        self.assertEqual(g.state.play_history[-1].cost,0);self.assertEqual(self.stats(g,eid),(6,6));self.assertEqual(g.state.players[1].mana,6)

    def test_a11_health_payment_keeps_mana_operand_and_common_payment_projection(self):
        g=self.game((CARD,G+'health'));eid=self.hand(g,CARD);self.play(g,G+'health',eid);self.play(g,CARD,self.victim(g))
        self.assertEqual(g.state.play_history[-1].payment,PaymentType.HEALTH);self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,23);self.assertEqual(self.stats(g,eid),(7,7));self.portable(g)

    def test_a12_ordered_local_hand_buffs_follow_native_base_policy(self):
        g=self.game((CARD,G+'buff',G+'spend'));eid=self.hand(g,CARD);self.play(g,G+'buff',eid)
        self.assertEqual(self.stats(g,eid),(9,10));self.play(g,G+'spend');self.assertEqual(self.stats(g,eid),(6,7))
        self.play(g,CARD,self.victim(g));self.assertEqual(g.state.battlecry_history[-1].payload.remaining_mana_number,4)

    def test_a13_two_originals_only_freeze_the_one_that_was_actually_played(self):
        g=self.game((CARD,CARD));eid=self.hand(g,CARD);self.play(g,CARD,self.victim(g));other=self.hand(g,CARD)
        self.assertEqual(self.raw(g,eid),(7,7,7));self.assertEqual(self.raw(g,other),(1,1,1))

    def test_a14_countered_minion_keeps_original_payment_without_battlecry(self):
        g=self.game(mode='counter');eid=self.play(g,CARD,self.victim(g))
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].mana,0)
        self.assertFalse(g.state.battlecry_history);self.assertEqual(g.state.play_history[-1].minion_result,'countered');self.portable(g,'counter')

    def test_a15_payment_wait_freezes_one_source_but_normalizes_other_hands_and_restores(self):
        g=self.game((CARD,CARD),mode='wait');eid=self.play(g,CARD,self.victim(g));self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[eid].zone,Zone.PLAY);self.assertEqual(self.raw(g,eid),(7,7,7));self.assertEqual(self.raw(g,self.hand(g,CARD)),(1,1,1))
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'wait');self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[self.victim(g)].damage,7)

    def test_a16_board_current_copy_keeps_number_base_copy_rebuilds_one(self):
        g=self.game((CARD,G+'gain',P+'copy',P+'base'));eid=self.play(g,CARD,self.victim(g));self.play(g,G+'gain')
        self.assertEqual(self.stats(g,eid),(7,7));self.play(g,P+'copy',eid);current=g.state.players[1].board[-1]
        self.assertEqual(self.stats(g,current),(7,7));self.play(g,P+'base',eid);self.assertEqual(self.stats(g,g.state.players[1].board[-1]),(1,1))
        self.assertEqual(len(g.state.battlecry_history),1)

    def test_a17_bounce_rebuilds_live_hand_numbers_then_next_play_captures_fresh_value(self):
        g=self.game((CARD,G+'gain',P+'bounce',P+'zero'));eid=self.play(g,CARD,self.victim(g));self.play(g,G+'gain')
        self.play(g,P+'bounce',eid);self.assertEqual(self.raw(g,eid),(2,2,2));self.play(g,P+'zero',eid)
        self.play(g,CARD,self.victim(g));self.assertEqual([b.payload.remaining_mana_number for b in g.state.battlecry_history],[7,1])

    def test_a18_hand_transfer_uses_receiving_players_actual_remaining_mana(self):
        g=self.game((CARD,P+'transfer'));eid=self.hand(g,CARD);self.play(g,P+'transfer',eid)
        self.assertIn(eid,g.state.players[2].hand);self.assertEqual(self.raw(g,eid),(4,4,4));self.portable(g)

    def test_a19_silence_removes_native_stats_and_base_copy_remains_independent(self):
        g=self.game((CARD,P+'zero',P+'silence',G+'gain'));eid=self.hand(g,CARD);self.play(g,P+'zero',eid);self.play(g,CARD,self.victim(g))
        self.play(g,P+'silence',eid);self.assertEqual(self.stats(g,eid),(1,1));self.play(g,G+'gain')
        self.assertEqual(self.stats(g,eid),(1,1));self.assertFalse(any(a.kind=='remaining_mana_numbers' for a in g.state.entities[eid].abilities))

    def test_a20_plain_summon_has_printed_stats_and_no_battlecry(self):
        g=self.game((G+'summon',));self.play(g,G+'summon');eid=g.state.players[1].board[-1]
        self.assertEqual(self.raw(g,eid),(1,1,1));self.assertFalse(g.state.battlecry_history)

    def test_a21_draw_from_deck_starts_live_numbers_only_after_physical_hand_entry(self):
        g=self.game((P+'draw',),deck=(CARD,));eid=g.state.players[1].deck[0];self.assertEqual(self.raw(g,eid),(1,1,1))
        self.play(g,P+'draw');self.assertIn(eid,g.state.players[1].hand);self.assertEqual(self.raw(g,eid),(6,6,6));self.portable(g)

    def test_a22_effect_battlecry_and_later_history_keep_original_number_after_transform(self):
        g=self.game((CARD,G+'trigger',G+'morph',G+'history'));eid=self.play(g,CARD,self.victim(g))
        self.play(g,G+'trigger',eid);self.play(g,G+'morph',eid);self.play(g,G+'history')
        self.assertEqual([b.payload.remaining_mana_number for b in g.state.battlecry_history],[7,7,7])
        self.assertEqual(g.state.entities[self.victim(g)].damage,21);self.portable(g)

    def test_a23_rehashed_hand_cache_and_original_payload_tampering_are_rejected(self):
        g=self.game();eid=self.hand(g,CARD);bad=g.snapshot();bad['state']['entities'][str(eid)]['base_attack']=8
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(self.rehash(bad),registry('reader'))
        self.play(g,CARD,self.victim(g));bad=g.snapshot();bad['state']['play_history'][0]['battlecries'][0]['remaining_mana_number']=None
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(self.rehash(bad),registry('reader'))

    def test_a24_failure_rolls_back_payment_and_both_players_hide_internal_number_material(self):
        g=self.game(mode='fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g,CARD,self.victim(g))
        self.assertEqual(g.snapshot(),before)
        for seat in (1,2):
            g=self.game(seat=seat)
            for viewer in (1,2):
                value=json.dumps(g.observe(viewer));self.assertNotIn('remaining_mana_card_id',value);self.assertNotIn('remaining_mana_number',value)
            self.assertNotIn(CARD,json.dumps(g.observe(3-seat)))

    def test_a25_temporary_cleanup_and_next_actual_turn_refresh_held_numbers(self):
        g=self.game((CARD,G+'gain'));eid=self.hand(g,CARD);self.play(g,G+'gain')
        self.assertEqual(self.raw(g,eid),(10,10,10));g.apply(EndTurn(1))
        self.assertEqual(self.raw(g,eid),(7,7,7));g.apply(EndTurn(2))
        self.assertEqual((g.state.players[1].mana,g.state.players[1].max_mana),(8,8));self.assertEqual(self.raw(g,eid),(8,8,8))


if __name__=='__main__':unittest.main()
