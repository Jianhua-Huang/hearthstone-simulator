"""Flame Guardian's actual hand group, three-end clock and stored destruction."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.hand_buff_deadline_card import CARD,load_batch,register_hand_buff_deadline_card
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
                           Registry,Scenario,SelectChoice,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Destroy,Draw,GainArmor,
                                   InvokeBehavior,RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BattlecryRepeatSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.targets import canonical_digest

P='k203.'
HERO,A,B,S,PROBE,WATCH,BC2=(P+x for x in ('hero','a','b','spell','probe','watch','bc2'))


@lru_cache(None)
def registry(mode=None):
    r=Registry(P+str(mode));register_hand_buff_deadline_card(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=60))
    for cid,attack,health in ((A,1,2),(B,2,3)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health))
    r.register_card(CardDefinition(BC2,BC2,CardType.MINION,health=30,
        battlecry_repeats=(BattlecryRepeatSpec(2),)))
    r.register_behavior(P+'empty',lambda c:())
    r.register_card(CardDefinition(S,S,CardType.SPELL,cost=2,on_play=P+'empty'))
    r.register_behavior(P+'fail',lambda c:(_ for _ in ()).throw(ResolutionError('K203 deliberate failure')))
    def pause(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue'),
            ChoiceOption('add','Add later minion',(AddToHand(c.player_id,B,c.source_id),)),
            ChoiceOption('bad','Rollback',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    def destroyed(c):
        if c.destruction is None:
            raise ValueError('Stored native body lost actual destruction')
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',(GainArmor(c.player_id,2),)),
            ChoiceOption('bad','Rollback',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'destroyed',destroyed)
    r.register_card(CardDefinition(PROBE,PROBE,CardType.MINION,cost=1,attack=1,health=1,
        deathrattle=P+'empty',on_destroyed=P+'destroyed'))
    def ref(c):return CardReference.capture(c.state.entities[c.target_id])
    def roundtrip(c):
        original=ref(c)
        return (MoveCard(original,c.player_id,Zone.DECK,source_id=c.source_id),
                MoveCard(replace(original,zone=Zone.DECK,zone_epoch=original.zone_epoch+1),
                         c.player_id,Zone.HAND,source_id=c.source_id))
    scripts=dict(
        kill=lambda c:(Destroy(c.target_id,c.source_id),),
        current=lambda c:(CopyCard(ref(c),c.player_id,mode='current',source_id=c.source_id),),
        base=lambda c:(CopyCard(ref(c),c.player_id,mode='base',source_id=c.source_id),),
        give=lambda c:(MoveCard(ref(c),3-c.player_id,Zone.HAND,source_id=c.source_id),),
        stash=lambda c:(MoveCard(ref(c),c.player_id,Zone.DECK,source_id=c.source_id),),
        roundtrip=roundtrip,
        add=lambda c:(AddToHand(c.player_id,B,c.source_id),))
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        fields={} if name=='add' else dict(targeting=TargetSpec(
            zones=(Zone.BOARD,) if name=='kill' else (Zone.HAND,),kinds=(CardType.MINION,)))
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,**fields))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=CARD:return ()
        return (InvokeBehavior(P+'fail',c.source_id,c.player_id),) if mode=='fail' else pause(c)
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=(TriggerSpec('stored_card_buffed',P+'watch'),) if mode else ()))
    r.validate();return r


class HandBuffDeadlineCardTests(unittest.TestCase):
    def game(self,hand=(CARD,A,B),board=(),enemy_hand=(A,S),actor=1,mode=None):
        self.mode=mode
        own=PlayerSetup(HERO,hand=hand,board=board,deck=(S,)*10,mana=80,max_mana=80,mana_cap=80)
        other=PlayerSetup(HERO,hand=enemy_hand,deck=(S,)*10,mana=80,max_mana=80,mana_cap=80)
        return Game.from_scenario(Scenario((own,other)if actor==1 else(other,own),
            active_player=actor,seed=203),registry(mode))

    def eid(self,g,cid,zone='hand',player=None):
        p=g.state.active_player if player is None else player
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None):
        eid=self.eid(g,cid);g.apply(PlayCard(g.state.active_player,eid,target));return eid

    def end(self,g,n=1):
        for _ in range(n):g.apply(EndTurn(g.state.active_player))

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def stats(self,g,eid):
        e=g.state.entities[eid];return e.attack,e.max_health

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=registry.__wrapped__(self.mode)
        self.assertEqual(Game.from_snapshot(deepcopy(s),r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)

    def test_native_root_three_evidence_rows_and_two_primary_faces(self):
        data=load_batch();self.assertEqual(len(data['cards']),1)
        self.assertEqual([r['record']['id']for r in data['evidence_only']],['FIR_928e','FIR_928e2','FIR_928e3'])
        self.assertEqual(len(data['official_observations']),2)
        for r in data['cards']+data['evidence_only']:
            self.assertEqual(canonical_digest(r['record']),r['record_sha256'])
        self.assertTrue(all(r['record']['id']not in registry().cards for r in data['evidence_only']))
        c=registry().card(CARD);self.assertEqual((c.cost,c.attack,c.health),(5,5,5))

    def test_only_current_own_hand_minions_gain_three_and_share_original_scope(self):
        g=self.game((CARD,A,B,S),board=(A,));a=self.eid(g,A);b=self.eid(g,B)
        source=self.play(g,CARD)
        self.assertEqual((self.stats(g,a),self.stats(g,b),self.stats(g,source)),((4,5),(5,6),(5,5)))
        self.assertEqual(self.stats(g,self.eid(g,A,'board')),(1,2))
        self.assertEqual(self.stats(g,self.eid(g,A,player=2)),(1,2))
        root,=g.state.hand_deadlines
        self.assertEqual(tuple(r.entity_id for r in root.targets),(a,b))
        self.assertEqual((root.request.owner_ends,root.request.retirement,g.state.players[1].mana),(3,'destroy',75))
        self.portable(g)

    def test_empty_minion_scope_does_not_expand_to_later_cards(self):
        for hand in ((CARD,),(CARD,S,P+'add')):
            with self.subTest(hand=hand):
                g=self.game(hand);self.play(g,CARD)
                self.assertEqual(g.state.hand_deadlines[0].targets,())
                if P+'add' in hand:self.play(g,P+'add')
                self.end(g,5)
                self.assertEqual(g.state.hand_deadlines[0].removed,())

    def test_three_owner_ends_include_current_turn_and_ignore_opponent_ends(self):
        g=self.game();a=self.eid(g,A);self.play(g,CARD)
        for n in range(1,6):
            self.end(g)
            self.assertEqual(g.state.entities[a].zone,Zone.GRAVEYARD if n==5 else Zone.HAND)
        self.assertEqual(len(g.state.hand_deadlines[0].destruction_events),2)
        self.assertFalse(g.state.discard_history or g.state.death_history)
        self.portable(g)

    def test_played_buffed_minion_keeps_stats_and_escapes_hand_deadline(self):
        g=self.game((CARD,A));a=self.eid(g,A)
        self.play(g,CARD);self.play(g,A);self.end(g,5)
        self.assertEqual((g.state.entities[a].zone,self.stats(g,a)),(Zone.BOARD,(4,5)))
        self.assertEqual(g.state.hand_deadlines[0].removed,())

    def test_source_death_does_not_cancel_already_armed_deadline(self):
        g=self.game((CARD,A,P+'kill'));a=self.eid(g,A)
        source=self.play(g,CARD);self.play(g,P+'kill',source);self.end(g,5)
        self.assertEqual(g.state.entities[a].zone,Zone.GRAVEYARD)

    def test_stashed_and_reentered_cards_use_original_residence_guards(self):
        for move in ('stash','roundtrip'):
            with self.subTest(move=move):
                g=self.game((CARD,A,P+move));a=self.eid(g,A)
                self.play(g,CARD);self.play(g,P+move,a);self.end(g,5)
                self.assertEqual(g.state.entities[a].zone,Zone.DECK if move=='stash' else Zone.HAND)
                self.assertEqual(self.stats(g,a),(4,5))
                self.assertEqual(g.state.hand_deadlines[0].removed,())

    def test_transferred_card_retains_buff_without_original_holder_deadline(self):
        g=self.game((CARD,A,P+'give'));a=self.eid(g,A)
        self.play(g,CARD);self.play(g,P+'give',a);self.end(g,5)
        self.assertEqual((g.state.entities[a].controller,g.state.entities[a].zone,self.stats(g,a)),(2,Zone.HAND,(4,5)))

    def test_current_and_base_copies_do_not_join_original_target_group(self):
        g=self.game((CARD,A,P+'current',P+'base'));a=self.eid(g,A)
        self.play(g,CARD);self.play(g,P+'current',a);self.play(g,P+'base',a)
        copies=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==A and i!=a]
        self.assertEqual([self.stats(g,i)for i in copies],[(4,5),(1,2)])
        self.end(g,5)
        self.assertEqual(g.state.entities[a].zone,Zone.GRAVEYARD)
        self.assertTrue(all(g.state.entities[i].zone==Zone.HAND for i in copies))
        self.portable(g)

    def test_repeated_battlecry_stacks_buffs_and_keeps_distinct_nonduplicating_deadlines(self):
        g=self.game((CARD,A),board=(BC2,));a=self.eid(g,A)
        self.play(g,CARD);self.assertEqual(self.stats(g,a),(7,8))
        self.assertEqual(len(g.state.hand_deadlines),2)
        self.end(g,5)
        self.assertEqual([r.removed for r in g.state.hand_deadlines],[(a,),()])

    def test_second_seat_uses_its_own_hand_and_ends(self):
        g=self.game(actor=2);a=self.eid(g,A)
        self.play(g,CARD);self.end(g,5)
        self.assertEqual(g.state.entities[a].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.hand_deadlines[0].request.player_id,2)

    def test_first_buff_wait_preserves_full_original_scope_and_remaining_buffs(self):
        g=self.game(board=(WATCH,),mode='wait');a=self.eid(g,A);b=self.eid(g,B)
        self.play(g,CARD)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(tuple(r.entity_id for r in g.state.hand_deadlines[0].targets),(a,b))
        self.assertEqual(self.stats(g,a),(4,5));self.portable(g)
        self.choose(g,'add');later=g.state.players[1].hand[-1]
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g)
        self.assertEqual((self.stats(g,b),self.stats(g,later)),((5,6),(2,3)))
        self.end(g,5)
        self.assertEqual(g.state.entities[later].zone,Zone.HAND)

    def test_failed_buff_choice_restores_complete_waiting_state(self):
        g=self.game(board=(WATCH,),mode='wait');self.play(g,CARD);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.choose(g);self.choose(g)

    def test_immediate_buff_fault_rolls_back_card_payment_buffs_and_deadline(self):
        g=self.game(board=(WATCH,),mode='fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),before)

    def test_native_stored_destruction_wait_preserves_later_target_and_rolls_back_failure(self):
        g=self.game((CARD,PROBE,A));probe=self.eid(g,PROBE);a=self.eid(g,A)
        self.play(g,CARD);self.end(g,5)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((g.state.entities[probe].zone,g.state.entities[a].zone),(Zone.GRAVEYARD,Zone.HAND))
        self.assertFalse(g.state.death_history or g.state.discard_history)
        self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g)
        self.assertEqual(g.state.entities[a].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.portable(g)

    def test_private_receipts_are_hidden_and_queries_do_not_advance_clock(self):
        g=self.game();self.play(g,CARD);before=g.snapshot()
        for player in (1,2):
            visible=json.dumps(g.observe(player))+json.dumps(g.player_events(player))
            for key in ('owner_ends_at_accept','created_event','destruction_cursor','destruction_events'):
                self.assertNotIn('"'+key+'"',visible)
            g.for_player(player).legal_actions()
        self.assertEqual(g.snapshot(),before)
