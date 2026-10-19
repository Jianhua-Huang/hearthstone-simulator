"""Real Runi and original future hand delivery through genuine turn starts."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.temporal_hand_return_card import CARD,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,
    ModifyCost,RequestChoice,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.future_hand_returns import ReturnFutureHands,SendHandMinionsFuture,validate_boundary
from hs_sim.engine.hand_upgrades import BuffStoredCard,UpgradeHandCard
from hs_sim.engine.model import CostSpec,RewindSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P='future.hand.test.';A=P+'a';B=P+'b';FILL=P+'filler';WATCH=P+'watch'


@lru_cache(maxsize=None)
def registry(role,mode=None):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    for cid,atk,hp in ((A,2,3),(B,4,4)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=atk,health=hp,keywords=(Keyword.DIVINE_SHIELD,),metadata=meta))
    r.register_card(CardDefinition(FILL,FILL,CardType.SPELL,metadata=meta))
    def first(c):return c.state.entities[c.state.players[c.player_id].hand[0]]
    scripts={
        'buff':lambda c:(BuffStoredCard(CardReference.capture(first(c)),2,1,c.source_id),ModifyCost(first(c).id,CostSpec(delta=-1))),
        'add':lambda c:(AddToHand(c.player_id,FILL,c.source_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'future':lambda c:(SendHandMinionsFuture(c.player_id,c.target_id),),
        'extra':lambda c:(QueueTurns((c.player_id,),c.source_id),),
        'skip':lambda c:(SkipTurns(3-c.player_id,1,c.source_id),),
        'early':lambda c:(ReturnFutureHands(),),
        'lethal':lambda c:(Damage(c.state.players[3-c.player_id].hero_id,100,c.source_id),),
        'fill':lambda c:tuple(AddToHand(c.player_id,FILL,c.source_id)for _ in range(3)),
        'later':lambda c:(AddToHand(c.player_id,A,c.source_id),),
        'stage':lambda c:(AddToHand(c.player_id,CARD,c.source_id),AddToHand(c.player_id,B,c.source_id)),
        'summon':lambda c:(Summon(c.player_id,CARD),),
        'latefail':lambda c:(SendHandMinionsFuture(c.player_id,c.target_id),AddToHand(c.player_id,'missing.future.card',c.source_id)),
        'retryfuture':lambda c:(SendHandMinionsFuture(c.player_id,c.target_id),),
        'upgrade':lambda c:(UpgradeHandCard(CardReference.capture(first(c)),B,c.source_id),),
    }
    for key,callback in scripts.items():
        r.register_behavior(P+key,callback)
        extra=dict(keywords=(Keyword.REWIND,),rewind=RewindSpec())if key=='retryfuture'else{}
        r.register_card(CardDefinition(P+key,P+key,CardType.SPELL,on_play=P+key,requires_target=key in('kill','future','latefail','retryfuture'),metadata=meta,**extra))
    def fail(c):raise ResolutionError('Runi deliberate delivery failure')
    r.register_behavior(P+'fail',fail)
    if mode=='burn':
        r.register_behavior(P+'burn_bonus',lambda c:(GainArmor(c.player_id,7),))
        r._cards[B]=replace(r.card(B),on_destroyed=P+'burn_bonus')
    if mode in('save','return'):
        def watch(c):
            if c.event.player_id!=1:return ()
            if mode=='save' and c.event.kind!='future_hand_saved':return ()
            if mode=='return' and(c.event.kind!='card_moved_to_hand'or c.state.entities[c.event.target_id].card_id!=A):return ()
            return (RequestChoice(1,(ChoiceOption('ok','Continue',(GainArmor(1,1),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=meta,
            triggers=(TriggerSpec('future_hand_saved'if mode=='save'else'card_moved_to_hand',WATCH),)))
    r.validate();r.freeze();return r


class TemporalHandReturnTests(unittest.TestCase):
    def game(self,hand=(CARD,A,B,FILL),*,mode=None,pid=1,board=()):
        self.mode=mode
        players=[PlayerSetup('HERO_08',deck=(FILL,)*8,mana=50,max_mana=50,mana_cap=50)for _ in range(2)]
        players[pid-1]=replace(players[pid-1],hand=hand,board=(*board,*((WATCH,)if mode in('save','return')else())))
        return Game.from_scenario(Scenario(tuple(players),seed=230998,active_player=pid),registry('writer',mode))
    def entity(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CARD,target=None,pid=1):
        e=self.entity(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
    def advance(self,g,count=2):
        for _ in range(count):g.apply(EndTurn(g.state.active_player))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry('reader'if g.registry is registry('writer',self.mode)else'writer',self.mode);self.assertIsNot(r,g.registry)
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('future_hands','FutureHandReturn','originals','resolution_frame','rng_state'):self.assertNotIn(key,wire)
        return other
    def test_a00_real_paid_runi_saves_only_original_minions_and_returns_before_draw(self):
        g=self.game();ids=tuple(self.entity(g,cid).id for cid in(A,B));source=self.play(g)
        self.assertEqual(g.state.players[1].mana,45);root,=g.state.future_hands
        self.assertEqual(tuple(r.entity_id for r in root.originals),ids)
        self.assertTrue(all(g.state.entities[i].zone==Zone.SETASIDE for i in ids));self.assertEqual(g.state.players[1].board,[source])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[FILL]);self.assertFalse(g.state.death_history)
        self.advance(g,1);self.assertEqual(g.state.future_hands[0].phase,'active')
        self.advance(g,1);self.assertEqual(g.state.future_hands[0].phase,'completed')
        self.assertEqual(tuple(g.state.players[1].hand[1:3]),ids)
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].max_health)for i in ids],[(7,8),(9,9)])
        events=[e.kind for e in g.events];self.assertLess(events.index('future_hand_returned'),len(events)-1-events[::-1].index('turn_started'))
        self.assertFalse([e for e in g.events if e.kind in('minion_died','card_discarded')and e.target_id in ids]);self.portable(g)
    def test_a01_complete_raw_and_two_strict_primary_faces(self):
        d=load_batch();row,=d['cards'];self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(len(d['official_observations']),2)
        c=registry('writer').card(CARD);self.assertEqual((c.cost,c.attack,c.health),(5,5,5));self.assertEqual(c.metadata.tribes,('draenei',))
    def test_b00_save_wait_restores_and_failed_choice_rolls_back_only_choice(self):
        g=self.game(mode='save');self.play(g);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.advance(other)
        self.assertEqual(other.state.future_hands[0].phase,'completed');self.portable(other)
    def test_b01_return_wait_sees_whole_buffed_group_and_preserves_startup_work(self):
        g=self.game(mode='return');ids=tuple(self.entity(g,cid).id for cid in(A,B));self.play(g);self.advance(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(all(i in g.state.players[1].hand for i in ids))
        self.assertEqual([g.state.entities[i].attack for i in ids],[7,9]);self.assertEqual(len(g.state.draw_history),1)
        other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other)
        self.assertEqual(len(other.state.draw_history),2);self.portable(other)
    def test_c00_early_return_rejected_without_changing_original_saved_group(self):
        g=self.game(hand=(CARD,A,P+'early'));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'early')
        self.assertEqual(g.snapshot(),before);self.portable(g)
    def test_c01_tampered_saved_epoch_or_private_return_phase_is_rejected(self):
        g=self.game();self.play(g)
        for mutate in (lambda s:s['state']['future_hands'][0]['originals'][0].update(zone_epoch=99),
                       lambda s:s['state']['future_hands'][0].update(phase='completed')):
            s=json.loads(json.dumps(g.snapshot()));mutate(s);s['state_hash']=canonical_hash(s['state'])
            with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry('reader'))

    def test_d00_empty_group_and_nonminion_hand_do_not_consume_rng(self):
        for hand in ((CARD,),(CARD,FILL,FILL)):
            g=self.game(hand=hand);rng=g._rng.getstate();self.play(g);self.assertEqual(g.state.future_hands[0].originals,())
            self.advance(g);self.assertEqual(g.state.future_hands[0].phase,'completed');self.assertEqual(g._rng.getstate(),rng)
            self.assertEqual(len(g.state.draw_history),2)
        self.portable(g)

    def test_d01_original_buffs_cost_keyword_identity_and_acquisition_are_preserved(self):
        g=self.game(hand=(A,P+'buff',CARD,FILL));eid=self.entity(g,A).id;self.play(g,P+'buff')
        e=g.state.entities[eid];abilities=tuple(a.id for a in e.abilities);old_entry=e.hand_entry_id;old_enchant=tuple(e.enchantments)
        self.play(g);self.advance(g);e=g.state.entities[eid]
        self.assertEqual((e.attack,e.max_health),(9,9));self.assertEqual(tuple(a.id for a in e.abilities),abilities)
        self.assertTrue(all(a in e.enchantments for a in old_enchant));self.assertGreater(e.hand_entry_id,old_entry)
        self.assertIn(Keyword.DIVINE_SHIELD,e.keywords)
        self.assertEqual(g.quote_cost(eid).amount,1);self.portable(g)

    def test_d02_source_death_does_not_cancel_original_future_return(self):
        g=self.game(hand=(CARD,A,P+'kill'));eid=self.entity(g,A).id;source=self.play(g);self.play(g,P+'kill',source)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.advance(g)
        self.assertIn(eid,g.state.players[1].hand);self.assertEqual(g.state.entities[eid].attack,7);self.portable(g)

    def test_d03_later_acquired_same_name_minion_is_not_part_of_saved_group(self):
        g=self.game(hand=(CARD,A,P+'later'));old=self.entity(g,A).id;self.play(g);self.play(g,P+'later')
        new=self.entity(g,A).id;self.assertNotEqual(old,new);self.advance(g)
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].max_health)for i in(new,old)],[(2,3),(7,8)])
        self.assertLess(g.state.players[1].hand.index(new),g.state.players[1].hand.index(old));self.portable(g)

    def test_d04_original_order_partial_capacity_and_native_burn_reward(self):
        g=self.game(hand=(CARD,A,B,P+'fill')+(FILL,)*6,mode='burn');a=self.entity(g,A).id;b=self.entity(g,B).id
        self.play(g);self.play(g,P+'fill');self.assertEqual(len(g.state.players[1].hand),9);self.advance(g)
        root=g.state.future_hands[0];self.assertEqual(root.returned,(a,));self.assertEqual(root.burned,(b,))
        self.assertEqual(g.state.entities[b].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,7)
        self.assertFalse(g.state.death_history);self.assertEqual(len(g.state.players[1].hand),10);self.portable(g)

    def test_d05_second_seat_uses_the_same_two_real_start_clock(self):
        g=self.game(pid=2);eid=self.entity(g,A,pid=2).id;self.play(g,pid=2);self.advance(g)
        self.assertEqual(g.state.active_player,2);self.assertIn(eid,g.state.players[2].hand)
        self.assertEqual(g.state.future_hands[0].due_turn,3);self.portable(g)

    def test_d06_extra_turn_is_one_future_start_not_the_whole_two_turn_wait(self):
        g=self.game(hand=(CARD,A,P+'extra'));eid=self.entity(g,A).id;self.play(g);self.play(g,P+'extra')
        self.advance(g,1);self.assertEqual((g.state.turn,g.state.active_player),(2,1));self.assertEqual(g.state.entities[eid].zone,Zone.SETASIDE)
        self.advance(g,1);self.assertEqual((g.state.turn,g.state.active_player),(3,2));self.assertIn(eid,g.state.players[1].hand);self.portable(g)

    def test_d07_skipped_slot_does_not_advance_the_real_future_clock(self):
        g=self.game(hand=(CARD,A,P+'skip'));eid=self.entity(g,A).id;self.play(g);self.play(g,P+'skip')
        self.advance(g,1);self.assertEqual((g.state.turn,g.state.active_player),(2,1));self.assertEqual(g.state.entities[eid].zone,Zone.SETASIDE)
        self.assertEqual(len([e for e in g.events if e.kind=='turn_skipped']),1)
        self.advance(g,1);self.assertIn(eid,g.state.players[1].hand);self.portable(g)

    def test_e00_two_original_groups_keep_independent_accepted_work_during_return_wait(self):
        g=self.game(hand=(CARD,A,P+'stage'),mode='return');a=self.entity(g,A).id;self.play(g);self.play(g,P+'stage')
        b=self.entity(g,B).id;self.play(g);self.assertEqual(len(g.state.future_hands),2);self.advance(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual([r.phase for r in g.state.future_hands],['completed','active'])
        other=self.portable(g);bad=other.clone()
        bad._frame=replace(bad._frame,continuation=tuple(w for w in bad._frame.continuation if type(w)is not ReturnFutureHands))
        with self.assertRaises(ValueError):validate_boundary(bad)
        self.choose(other);self.assertEqual([r.phase for r in other.state.future_hands],['completed','completed'])
        self.assertLess(other.state.players[1].hand.index(a),other.state.players[1].hand.index(b));self.portable(other)

    def test_e01_terminal_game_closes_future_group_without_returning_or_buffing(self):
        g=self.game(hand=(CARD,A,P+'lethal'));eid=self.entity(g,A).id;self.play(g);self.play(g,P+'lethal')
        self.assertEqual(g.state.status,'finished');self.assertEqual(g.state.future_hands[0].phase,'ended')
        self.assertEqual((g.state.entities[eid].zone,g.state.entities[eid].attack),(Zone.SETASIDE,2));self.portable(g)

    def test_e02_late_failure_rolls_back_private_storage_and_all_allocations(self):
        from hs_sim.engine.registry import UnsupportedDefinitionError
        g=self.game(hand=(A,P+'latefail'),board=(CARD,));source=self.entity(g,CARD,'board').id;before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'missing.future.card')as raised:self.play(g,P+'latefail',source)
        self.assertIsInstance(raised.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),before);self.assertFalse(g.state.future_hands);self.portable(g)

    def test_e03_summoning_runi_does_not_execute_its_battlecry(self):
        g=self.game(hand=(A,P+'summon'));eid=self.entity(g,A).id;self.play(g,P+'summon')
        self.assertFalse(g.state.future_hands);self.assertIn(eid,g.state.players[1].hand)
        self.assertEqual(self.entity(g,CARD,'board').attack,5);self.portable(g)

    def test_e04_missing_original_receipt_or_duplicate_saved_identity_is_rejected(self):
        g=self.game();self.play(g);other=g.clone();other._events=[e for e in other._events if e.kind!='future_hand_saved']
        with self.assertRaises(ValueError):validate_boundary(other)
        root=g.state.future_hands[0]
        with self.assertRaises(ValueError):replace(root,originals=(root.originals[0],)*2)
        with self.assertRaises(ValueError):SendHandMinionsFuture(True,1)

    def test_e05_actual_rewind_retires_old_private_storage_and_replays_one_original_group(self):
        g=self.game(hand=(A,P+'retryfuture'),board=(CARD,));eid=self.entity(g,A).id;source=self.entity(g,CARD,'board').id
        self.play(g,P+'retryfuture',source);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g)
        self.choose(other,'retry');self.assertEqual(len(other.state.future_hands),1)
        self.assertEqual(tuple(r.entity_id for r in other.state.future_hands[0].originals),(eid,))
        self.assertEqual(len([e for e in other.events if e.kind=='future_hand_saved']),2)
        self.advance(other);self.assertIn(eid,other.state.players[1].hand)
        self.assertEqual(other.state.entities[eid].attack,7);self.portable(other)

    def test_e06_previously_upgraded_hand_face_keeps_original_identity_and_new_face(self):
        g=self.game(hand=(A,P+'upgrade',CARD));eid=self.entity(g,A).id;entry=g.state.entities[eid].hand_entry_id
        self.play(g,P+'upgrade');self.assertEqual(g.state.entities[eid].card_id,B)
        self.assertEqual(g.state.entities[eid].hand_entry_id,entry);self.play(g);self.advance(g)
        self.assertIn(eid,g.state.players[1].hand);self.assertEqual(g.state.entities[eid].card_id,B)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].max_health),(9,9));self.portable(g)
