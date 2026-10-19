"""Real Champion gains in board/stored/material paths and shared lifecycle."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_stat_gain_card import CARD,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,SnapshotError,SummonCause,TriggerSpec,Zone)
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dark_gifts import GrantDarkGift
from hs_sim.engine.deck_stat_distribution import DistributeDeckStatPairs
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,CopyMinion,Damage,DoubleStats,
    InvokeBehavior,RequestChoice,SetStats)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import AuraSpec,CostSpec,Keyword,SummonStats,TargetSpec
from hs_sim.engine.native_stat_gains import EVENT,LABEL,RewardNativeStatGain
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,DiscardCard,ModifyStoredCost
from test_infinite_cost_card import registry as base_registry,P,PLAIN

G='champion.test.'


@lru_cache(None)
def registry(role='writer',mode=None):
    r=base_registry.__wrapped__()
    r.register_behavior(G+'fill',lambda c:());r.register_card(CardDefinition(G+'fill','Filler',CardType.SPELL,on_play=G+'fill'))
    def change(c,attack,health,temporary=False):
        e=c.state.entities[c.target_id];expiry=c.state.turn if temporary else None
        return (Buff(e.id,attack,health,c.source_id,expires_turn=expiry),) if e.zone==Zone.BOARD else (
            BuffStoredCard(CardReference.capture(e),attack,health,c.source_id,expires_turn=expiry),)
    scripts={
        'both':lambda c:change(c,2,2), 'attack':lambda c:change(c,2,0), 'health':lambda c:change(c,0,2),
        'negative':lambda c:change(c,-1,0), 'zero':lambda c:change(c,0,0), 'mixed':lambda c:change(c,2,-1),
        'temporary':lambda c:change(c,2,2,True),
        'set_up':lambda c:(SetStats(c.target_id,6,7,c.source_id),),
        'set_down':lambda c:(SetStats(c.target_id,2,2,c.source_id),),
        'double':lambda c:(DoubleStats(c.target_id,attack=True,health=True,source_id=c.source_id),),
        'hurt':lambda c:(Damage(c.target_id,1,c.source_id),Damage(c.target_id,1,c.source_id)),
        'two':lambda c:(Buff(c.target_id,1,1,c.source_id),Buff(c.target_id,1,1,c.source_id)),
        'gift':lambda c:(GrantDarkGift(CardReference.capture(c.state.entities[c.target_id]),'EDR_100t1',c.source_id),),
        'price':lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(delta=-1),c.source_id),),
        'fixed_copy':lambda c:(CopyMinion(c.target_id,c.player_id,stats=SummonStats(8,8)),),
        'fixed_attributed':lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c),stats=SummonStats(8,8)),),
        'discard':lambda c:(DiscardCard(CardReference.capture(c.state.entities[c.target_id]),c.source_id),),
    }
    for name,body in scripts.items():
        r.register_behavior(G+name,body)
        zones=(Zone.HAND,) if name in ('gift','price','discard') else (Zone.BOARD,) if name in ('set_up','set_down','double','hurt','two','fixed_copy','fixed_attributed','mixed') else (Zone.HAND,Zone.BOARD)
        r.register_card(CardDefinition(G+name,name,CardType.SPELL,on_play=G+name,
            targeting=TargetSpec(zones=zones,kinds=(CardType.MINION,),relation='any' if zones==(Zone.BOARD,) else 'friendly')))
    def deck(c):
        entity=next(c.state.entities[i] for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==CARD)
        return (BuffStoredCard(CardReference.capture(entity),2,2,c.source_id),)
    r.register_behavior(G+'deck',deck)
    r.register_behavior(G+'grave',lambda c:(BuffStoredCard(c.state.discard_history[-1],2,2,c.state.discard_history[-1].entity_id),))
    r.register_behavior(G+'new',lambda c:(AddToHand(c.player_id,CARD,c.source_id,minion_grant=CreatedMinionGrant(2,2)),))
    r.register_behavior(G+'distribute',lambda c:(DistributeDeckStatPairs(c.player_id,4,c.source_id),))
    for name in ('deck','grave','new','distribute'):
        r.register_card(CardDefinition(G+name,name,CardType.SPELL,on_play=G+name))
    r.register_card(CardDefinition(G+'aura','Continuous aura',CardType.MINION,health=20,auras=(AuraSpec(2,health=3),)))
    if mode:
        def watch(c):
            e=c.state.entities.get(c.event.target_id)
            if e is None or e.card_id!=CARD:return ()
            attachment_id=dict(c.event.data).get('enchantment_id')
            is_extra=(any(a.id==attachment_id and a.label==LABEL for a in e.enchantments)
                if attachment_id is not None else c.event.source_id==e.id)
            if is_extra!=(mode=='reward_wait'):return ()
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(G+'watch',watch)
        event='stored_card_buffed' if mode=='reward_wait' else 'stats_changed'
        r.register_card(CardDefinition(G+'watch','Observer',CardType.MINION,health=20,triggers=(TriggerSpec(event,G+'watch'),)))
    r.validate();r.freeze();return r


class NativeStatGainTests(unittest.TestCase):
    def game(self,hand=(G+'both',),*,board=(CARD,),deck=None,enemy_hand=(),enemy_board=(),mode=None,seat=1):
        own=PlayerSetup('HERO_08',hand=hand,board=(*((G+'watch',) if mode else ()),*board),
            deck=(G+'fill',)*20 if deck is None else deck,mana=50,max_mana=50,mana_cap=50)
        other=PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=(G+'fill',)*20,mana=50,max_mana=50,mana_cap=50)
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own),active_player=seat,seed=285),registry('writer',mode))
    def hand(self,g,cid):return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)
    def target(self,g,zone=Zone.BOARD,seat=None):
        seat=g.state.active_player if seat is None else seat
        return next(i for i in getattr(g.state.players[seat],zone.value) if g.state.entities[i].card_id==CARD)
    def play(self,g,cid,target=None,eid=None):
        pid=g.state.active_player;eid=self.hand(g,cid) if eid is None else eid;g.apply(PlayCard(pid,eid,target));return eid
    def stats(self,g,eid):e=g.state.entities[eid];return (e.attack,e.max_health)
    def rewards(self,g):return [e for e in g.events if e.kind==EVENT]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def drain(self,g):
        while g.state.pending_choice:self.choose(g)
    def portable(self,g,mode=None):
        snap=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snap,registry('reader',mode))
        self.assertEqual(other.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),snap);return other

    def test_a01_complete_real_card_keywords_and_single_removable_native_source(self):
        d=load_batch();r=registry();self.assertEqual(len(d['official_observations']),2)
        self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(4,3,3))
        self.assertEqual(set(r.card(CARD).keywords),{Keyword.DIVINE_SHIELD,Keyword.TAUNT})
        g=self.game();self.assertEqual(sum(a.kind=='native_stat_gain' for a in g.state.entities[self.target(g)].abilities),1)

    def test_a02_real_paid_play_does_not_invent_stat_gain_on_entry(self):
        g=self.game((CARD,),board=());rng=g._rng.getstate();eid=self.play(g,CARD)
        self.assertEqual(self.stats(g,eid),(3,3));self.assertEqual(g.state.players[1].mana,46)
        self.assertFalse(self.rewards(g));self.assertEqual(g._rng.getstate(),rng)

    def test_a03_combined_attack_and_health_gain_awards_once_without_self_recursion(self):
        g=self.game();target=self.target(g);self.play(g,G+'both',target)
        self.assertEqual(self.stats(g,target),(6,6));self.assertEqual(len(self.rewards(g)),1)
        self.assertEqual(sum(e.label==LABEL for e in g.state.entities[target].enchantments),1)

    def test_a04_attack_only_health_only_and_mixed_signed_gains_each_award_once(self):
        for spell,expected in (('attack',(6,4)),('health',(4,6)),('mixed',(6,3))):
            g=self.game((G+spell,));target=self.target(g);self.play(g,G+spell,target)
            self.assertEqual(self.stats(g,target),expected);self.assertEqual(len(self.rewards(g)),1)

    def test_a05_actual_power_word_shield_receives_health_only_bonus(self):
        g=self.game(('CORE_CS2_004',));target=self.target(g);self.play(g,'CORE_CS2_004',target)
        self.assertEqual(self.stats(g,target),(4,6));self.assertEqual(len(self.rewards(g)),1)
        self.assertEqual(len(g.state.draw_history),1)

    def test_a06_actual_holy_spell_uses_same_stat_and_divine_shield_executors(self):
        g=self.game(('TLC_241t',));target=self.target(g);self.play(g,'TLC_241t',target)
        self.assertEqual(self.stats(g,target),(6,6));self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords)
        self.assertEqual(len(self.rewards(g)),1)

    def test_a07_negative_zero_cost_only_and_unrelated_minion_do_not_award(self):
        for spell,expected in (('negative',(2,3)),('zero',(3,3))):
            g=self.game((G+spell,));target=self.target(g);self.play(g,G+spell,target)
            self.assertEqual(self.stats(g,target),expected);self.assertFalse(self.rewards(g))
        g=self.game((G+'price',CARD),board=());self.play(g,G+'price',self.hand(g,CARD));self.assertFalse(self.rewards(g))
        g=self.game(board=(PLAIN,));self.play(g,G+'both',g.state.players[1].board[0]);self.assertFalse(self.rewards(g))

    def test_a08_stat_set_up_gains_once_and_later_set_down_does_not(self):
        g=self.game((G+'set_up',G+'set_down'));target=self.target(g)
        self.play(g,G+'set_up',target);self.assertEqual(self.stats(g,target),(7,8))
        self.play(g,G+'set_down',target);self.assertEqual(self.stats(g,target),(2,2));self.assertEqual(len(self.rewards(g)),1)

    def test_a09_doubling_and_two_separate_real_buffs_count_actual_operations(self):
        g=self.game((G+'double',));target=self.target(g);self.play(g,G+'double',target)
        self.assertEqual(self.stats(g,target),(7,7));self.assertEqual(len(self.rewards(g)),1)
        g=self.game((G+'two',));target=self.target(g);self.play(g,G+'two',target)
        self.assertEqual(self.stats(g,target),(7,7));self.assertEqual(len(self.rewards(g)),2)

    def test_a10_stored_hand_gain_keeps_bonus_when_played_without_second_reward(self):
        g=self.game((CARD,G+'both'),board=());target=self.hand(g,CARD);self.play(g,G+'both',target)
        self.assertEqual(self.stats(g,target),(6,6));self.play(g,CARD,eid=target)
        self.assertEqual(self.stats(g,target),(6,6));self.assertEqual(len(self.rewards(g)),1)

    def test_a11_original_deck_gain_and_draw_use_same_entity_without_another_reward(self):
        g=self.game((G+'deck',P+'draw'),board=(),deck=(CARD,));target=g.state.players[1].deck[0]
        self.play(g,G+'deck');self.assertEqual(self.stats(g,target),(6,6))
        self.play(g,P+'draw');self.assertIn(target,g.state.players[1].hand);self.assertEqual(len(self.rewards(g)),1)

    def test_a12_retained_discard_material_grows_in_grave_without_resurrection(self):
        g=self.game((CARD,G+'discard',G+'grave'),board=());target=self.hand(g,CARD)
        self.play(g,G+'discard',target);self.play(g,G+'grave')
        self.assertEqual(self.stats(g,target),(6,6));self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertFalse(g.state.death_history);self.assertEqual(len(self.rewards(g)),1)

    def test_a13_real_dark_gift_positive_attachment_uses_same_native_gain_window(self):
        g=self.game((CARD,G+'gift'),board=());target=self.hand(g,CARD);self.play(g,G+'gift',target)
        self.assertEqual(self.stats(g,target),(6,6));self.assertIn(Keyword.ELUSIVE,g.state.entities[target].keywords)
        self.assertEqual(len(self.rewards(g)),1)

    def test_a14_initial_created_grant_is_new_gain_but_plain_birth_is_not(self):
        g=self.game((G+'new',),board=());self.play(g,G+'new');target=self.hand(g,CARD)
        self.assertEqual(self.stats(g,target),(6,6));self.assertEqual(len(self.rewards(g)),1)

    def test_a15_current_and_base_copies_do_not_recount_frozen_material(self):
        g=self.game((G+'both',P+'copy',P+'base'));target=self.target(g);self.play(g,G+'both',target)
        self.play(g,P+'copy',target);current=g.state.players[1].board[-1]
        self.assertEqual(self.stats(g,current),(6,6));self.assertEqual(len(self.rewards(g)),1)
        self.play(g,P+'base',target);base=g.state.players[1].board[-1]
        self.assertEqual(self.stats(g,base),(3,3));self.assertEqual(len(self.rewards(g)),1)

    def test_a16_stored_current_copy_keeps_bonus_without_new_gain(self):
        g=self.game((CARD,G+'both',P+'hand_copy'),board=());target=self.hand(g,CARD);self.play(g,G+'both',target)
        self.play(g,P+'hand_copy',target);copy=g.state.players[1].hand[-1]
        self.assertNotEqual(copy,target);self.assertEqual(self.stats(g,copy),(6,6));self.assertEqual(len(self.rewards(g)),1)

    def test_a17_explicit_copy_stat_override_is_separate_from_inherited_material(self):
        for name in ('fixed_copy','fixed_attributed'):
            g=self.game((G+name,));target=self.target(g);self.play(g,G+name,target)
            copy=g.state.players[1].board[-1];self.assertEqual(self.stats(g,copy),(9,9))
            self.assertEqual(self.stats(g,target),(3,3));self.assertEqual(len(self.rewards(g)),1)

    def test_a18_silence_removes_native_rule_current_copy_stays_silent_base_rebuilds(self):
        g=self.game((P+'silence',G+'both',P+'copy',P+'base',G+'both'));target=self.target(g)
        self.play(g,P+'silence',target);self.play(g,G+'both',target);self.assertEqual(self.stats(g,target),(5,5))
        self.play(g,P+'copy',target);self.assertFalse(any(a.kind=='native_stat_gain' for a in g.state.entities[g.state.players[1].board[-1]].abilities))
        self.play(g,P+'base',target);base=g.state.players[1].board[-1];self.play(g,G+'both',base)
        self.assertEqual(self.stats(g,base),(6,6));self.assertEqual(len(self.rewards(g)),1)

    def test_a19_aura_refresh_removal_and_pure_queries_are_not_new_gains(self):
        g=self.game((G+'aura',P+'kill'));target=self.target(g);aura=self.play(g,G+'aura')
        self.assertEqual(self.stats(g,target),(5,6));self.assertFalse(self.rewards(g));before=g.snapshot()
        g.observe(1);g.observe(2);g.legal_actions();self.assertEqual(g.snapshot(),before)
        self.play(g,P+'kill',aura);self.assertEqual(self.stats(g,target),(3,3));self.assertFalse(self.rewards(g))

    def test_a20_original_temporary_buff_expires_without_restarting_or_removing_permanent_extra(self):
        g=self.game((G+'temporary',));target=self.target(g);self.play(g,G+'temporary',target)
        self.assertEqual(self.stats(g,target),(6,6));g.apply(EndTurn(1));self.assertEqual(self.stats(g,target),(4,4))
        self.assertEqual(len(self.rewards(g)),1)

    def test_a21_hand_bounce_reset_rebuilds_native_rule_without_old_buffs(self):
        g=self.game((G+'both',P+'bounce',G+'both'));target=self.target(g);self.play(g,G+'both',target)
        self.play(g,P+'bounce',target);self.assertEqual(self.stats(g,target),(3,3))
        self.play(g,G+'both',target);self.assertEqual(self.stats(g,target),(6,6));self.assertEqual(len(self.rewards(g)),2)

    def test_a22_failure_and_waiting_resume_keep_original_payment_and_gain_receipts(self):
        g=self.game(mode='fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g,G+'both',self.target(g))
        self.assertEqual(g.snapshot(),before)
        g=self.game(mode='wait');self.play(g,G+'both',self.target(g));self.assertIsNotNone(g.state.pending_choice)
        snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),snap);other=self.portable(g,'wait');self.drain(g);self.drain(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_a23_real_deck_batch_wait_contains_second_typed_reward_and_replays_exactly(self):
        g=self.game((G+'distribute',),board=(),deck=(CARD,CARD),mode='reward_wait');self.play(g,G+'distribute')
        self.assertIsNotNone(g.state.pending_choice);pending=[w for w in (*g._frame.prefix,*g._frame.continuation) if isinstance(w,RewardNativeStatGain)]
        self.assertEqual(len(pending),1);self.assertEqual(len(self.rewards(g)),1)
        other=self.portable(g,'reward_wait');self.drain(g);self.drain(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.rewards(g)),2)
        self.assertEqual([self.stats(g,i) for i in g.state.players[1].deck],[(6,6),(6,6)])

    def test_a24_future_and_duplicated_pending_reward_reject_after_full_rehash(self):
        g=self.game((G+'distribute',),board=(),deck=(CARD,CARD),mode='reward_wait');self.play(g,G+'distribute')
        pending=next(w for w in (*g._frame.prefix,*g._frame.continuation) if isinstance(w,RewardNativeStatGain))
        future=replace(pending,original=replace(pending.original,id=g.state.next_attachment_id))
        frames=(replace(g._frame,continuation=(*g._frame.continuation,pending)),
            replace(g._frame,prefix=tuple(future if w is pending else w for w in g._frame.prefix),
                continuation=tuple(future if w is pending else w for w in g._frame.continuation)))
        for frame in frames:
            bad=g.snapshot();bad['resolution_frame']=FrameCodec(g.mechanics,g.registry).encode(frame)
            bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(bad,registry('reader','reward_wait'))
        with self.assertRaises(ValueError):replace(pending,original=replace(pending.original,label=LABEL))

    def test_a25_both_players_hide_native_ability_and_private_deck_gain_material(self):
        for seat in (1,2):
            g=self.game((G+'deck',),board=(),deck=(CARD,),seat=seat);self.play(g,G+'deck')
            for viewer in (1,2):
                value=json.dumps(g.observe(viewer))
                for name in ('native_stat_gain_card_id','before_attack','before_health',EVENT):self.assertNotIn(name,value)
            self.assertNotIn(CARD,json.dumps(g.observe(3-seat)))


if __name__=='__main__':unittest.main()
