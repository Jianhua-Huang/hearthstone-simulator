"""Rat Burglar uses original current hand residents, not stale acquisition rows."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.opponent_hand_entry_theft_card import CARD, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy, Draw,
    GainArmor, InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_history import hand_entry
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec, EndTurnSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.spell_casts import CastStoredSpell
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.engine.cross_zone import TransformStoredCard

P='rat.theft.test.'
FILL, OTHER, OLD, NEW=(P+x for x in ('fill','other','old','new'))
DRAW, REFILL, GIFT, USE, BUFF, TRANSFORM, ROUNDTRIP, REMOVE=(P+x for x in (
    'draw','refill','gift','use','buff','transform','roundtrip','remove'))
SILENCE, DESTROY, DORMANT, CONTROL=(P+x for x in ('silence','destroy','dormant','control'))
WAIT, FAIL, KILL=(P+x for x in ('wait','fail','kill'))


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer','reader')
    r=build_registry()
    def first(c):return c.state.entities[c.state.players[3-c.player_id].hand[-1]]
    def root(c):return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
    r.register_behavior(DRAW,lambda c:(Draw(3-c.player_id,3,c.source_id),))
    r.register_behavior(REFILL,lambda c:(Draw(c.player_id,3,c.source_id),))
    r.register_behavior(GIFT,lambda c:(AddToHand(3-c.player_id,'GAME_005',c.source_id),))
    r.register_behavior(USE,lambda c:(CastStoredSpell(CardReference.capture(first(c)),3-c.player_id,c.source_id),))
    r.register_behavior(BUFF,lambda c:(BuffStoredCard(CardReference.capture(first(c)),attack=4,health=5,
        cost=CostSpec(delta=-1),source_id=c.source_id),))
    r.register_behavior(TRANSFORM,lambda c:(TransformStoredCard(CardReference.capture(first(c)),NEW,source_id=c.source_id),))
    def move(c,where):
        e=first(c);ref=CardReference.capture(e)
        return (MoveCard(ref,3-c.player_id,where,position='top',source_id=c.source_id),)
    r.register_behavior(REMOVE,lambda c:move(c,Zone.DECK))
    def roundtrip(c):return (*move(c,Zone.DECK),Draw(3-c.player_id,1,c.source_id))
    r.register_behavior(ROUNDTRIP,roundtrip)
    r.register_behavior(SILENCE,lambda c:(Silence(root(c)),))
    r.register_behavior(DESTROY,lambda c:(Destroy(root(c)),))
    r.register_behavior(DORMANT,lambda c:(MakeDormant(root(c),1,c.source_id),))
    r.register_behavior(CONTROL,lambda c:(ChangeControl(root(c),3-c.player_id),))
    def failure(c):raise ResolutionError('Rat Burglar deliberate failure')
    r.register_behavior(P+'failure',failure)
    def watch(c,fail=False):
        source=c.state.entities.get(c.event.source_id)
        entries=[x for x in c.state.hand_entries if x.player_id==c.player_id and x.turn==c.state.turn and x.from_zone==Zone.HAND]
        if source is None or source.card_id!=CARD or c.event.player_id!=c.player_id or len(entries)!=1:return ()
        if fail:return (GainArmor(c.player_id,1),InvokeBehavior(P+'failure',c.source_id,c.player_id))
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'failure',c.source_id,c.player_id),))),source_id=c.source_id),)
    r.register_behavior(WAIT,watch);r.register_behavior(FAIL,lambda c:watch(c,True))
    r.register_behavior(KILL,lambda c:(Destroy(root(c)),))
    for cid,event in ((WAIT,'card_moved_to_hand'),(FAIL,'card_moved_to_hand'),(KILL,'turn_ended')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=0,health=5,
            triggers=(TriggerSpec(event,cid,EndTurnSpec()if event=='turn_ended'else None),)))
    for cid,cost,atk,hp in ((FILL,2,2,3),(OTHER,3,3,4),(OLD,1,1,2),(NEW,8,7,8)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp))
    for cid in (DRAW,REFILL,GIFT,USE,BUFF,TRANSFORM,ROUNDTRIP,REMOVE,SILENCE,DESTROY,DORMANT,CONTROL):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    r.validate();r.freeze();return r


class RatBurglarTests(unittest.TestCase):
    def game(self,hand=(CARD,DRAW),*,enemy_hand=(OLD,),enemy_deck=None,board=(),capacity=10,active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(FILL,)*25,mana=10,max_mana=10,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(FILL,OTHER,FILL)*10 if enemy_deck is None else enemy_deck,
                mana=10,max_mana=10,hero_power_card_id='HERO_08bp')),active_player=active,seed=257205),
            registry('writer'),Ruleset(max_hand=capacity))
    def play(self,g,cid=CARD):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def eligible(self,g,pid=1):
        return [i for i in g.state.players[3-pid].hand if hand_entry(g.state,g.state.entities[i].hand_entry_id).turn==g.state.turn]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=registry('reader');other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s);return other

    def test_a00_full_original_neutral_body_and_two_current_official_faces(self):
        data=load_batch();raw=data['cards'][0]['record']
        self.assertEqual((raw['cost'],raw['attack'],raw['health']),(4,2,6))
        self.assertEqual(len(data['official_observations']),2)
        self.assertTrue(all(x['url'].startswith('https://playhearthstone.com/')for x in data['official_observations']))
        self.assertEqual(registry('writer').card(CARD).metadata.tribes,())

    def test_a01_actual_paid_root_steals_only_current_opponent_hand_acquisitions(self):
        g=self.game();old=g.state.players[2].hand[0];self.play(g);self.play(g,DRAW)
        selected=self.eligible(g);self.assertEqual(len(selected),3);rng=g._rng.getstate();self.end(g)
        self.assertEqual(g.state.players[1].hand,selected);self.assertIn(old,g.state.players[2].hand)
        self.assertTrue(all(g.state.entities[i].owner==2 and g.state.entities[i].controller==1 for i in selected))
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(g.state.play_history),2);self.portable(g)

    def test_a02_acquisition_before_root_enters_play_is_included(self):
        g=self.game();self.play(g,DRAW);selected=self.eligible(g);self.play(g);self.end(g)
        self.assertEqual(g.state.players[1].hand,selected)

    def test_a03_current_turn_policy_does_not_take_past_own_turn_entries(self):
        g=self.game();self.play(g,DRAW);old=self.eligible(g);self.end(g);self.end(g)
        self.play(g);self.end(g)
        self.assertTrue(all(i in g.state.players[2].hand for i in old))
        self.assertFalse(any(i in g.state.players[1].hand for i in old));self.portable(g)

    def test_a04_opponent_natural_draw_and_opening_cards_are_not_stolen(self):
        g=self.game(hand=(CARD,));self.play(g);self.end(g);self.end(g);self.end(g)
        self.assertEqual(len(g.state.players[2].hand),3)
        self.assertFalse(any(g.state.entities[i].owner==2 for i in g.state.players[1].hand))

    def test_a05_second_actor_on_first_global_turn_does_not_use_turn_parity(self):
        g=self.game(hand=(OLD,),enemy_hand=(CARD,DRAW),active=2);self.play(g);self.play(g,DRAW)
        selected=self.eligible(g,2);self.end(g)
        self.assertEqual(g.state.players[2].hand,selected)
        self.assertTrue(all(g.state.entities[i].controller==2 for i in selected));self.portable(g)

    def test_b00_generated_spell_is_transferred_as_original_without_cast_or_copy(self):
        g=self.game((CARD,GIFT));self.play(g);self.play(g,GIFT);eid=self.eligible(g)[0]
        casts=len(g.state.cast_history);before=g.state.entities[eid].zone_epoch;self.end(g)
        self.assertIn(eid,g.state.players[1].hand);self.assertEqual(g.state.entities[eid].zone_epoch,before+1)
        self.assertEqual(len(g.state.cast_history),casts)

    def test_b01_already_cast_card_is_not_retrieved_from_stale_hand_history(self):
        g=self.game((CARD,GIFT,USE));self.play(g);self.play(g,GIFT);eid=self.eligible(g)[0]
        self.play(g,USE);self.end(g)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertNotIn(eid,g.state.players[1].hand);self.assertEqual(g.state.cast_history[-1].player_id,2)

    def test_b02_current_transformed_face_and_material_are_taken(self):
        g=self.game((CARD,DRAW,TRANSFORM));self.play(g);self.play(g,DRAW);eid=self.eligible(g)[-1]
        old_entry=g.state.entities[eid].hand_entry_id;self.play(g,TRANSFORM)
        self.assertEqual(g.state.entities[eid].hand_entry_id,old_entry)
        self.end(g);self.assertIn(eid,g.state.players[1].hand);self.assertEqual(g.state.entities[eid].card_id,NEW)
        self.portable(g)

    def test_b03_original_buffs_costs_and_physical_identity_are_preserved(self):
        from hs_sim.engine.costs import local_cost
        g=self.game((CARD,DRAW,BUFF));self.play(g);self.play(g,DRAW);eid=self.eligible(g)[-1];self.play(g,BUFF)
        e=g.state.entities[eid];before=(e.attack,e.health,local_cost(e)[0]);self.end(g);e=g.state.entities[eid]
        self.assertEqual((e.attack,e.health,local_cost(e)[0]),before);self.assertIn(eid,g.state.players[1].hand)

    def test_b04_left_hand_card_is_excluded_and_returned_card_is_taken_once(self):
        for operation in (REMOVE,ROUNDTRIP):
            with self.subTest(operation=operation):
                g=self.game((CARD,DRAW,operation));self.play(g);self.play(g,DRAW);eid=self.eligible(g)[-1]
                self.play(g,operation);selected=self.eligible(g);self.end(g)
                self.assertEqual(sum(i==eid for i in g.state.players[1].hand),int(operation==ROUNDTRIP))
                self.assertTrue(all(i in g.state.players[1].hand for i in selected))

    def test_c00_overflow_removes_all_opponent_cards_and_burns_only_excess(self):
        for cap in (4,10):
            with self.subTest(cap=cap):
                g=self.game((CARD,DRAW)+(FILL,)*(cap-2),enemy_hand=(),capacity=cap)
                self.play(g);self.play(g,DRAW);ids=self.eligible(g);self.end(g)
                self.assertEqual(g.state.players[1].hand[-2:],ids[:2])
                self.assertEqual((g.state.entities[ids[2]].zone,g.state.entities[ids[2]].controller),(Zone.GRAVEYARD,1))
                self.assertEqual(g.state.discard_history,[])
                self.assertTrue(any(e.kind=='card_burned'and e.target_id==ids[2] for e in g.events))
                self.assertTrue(all(i not in g.state.players[2].hand for i in ids))

    def test_c01_fully_occupied_recipient_still_removes_all_qualified_cards(self):
        g=self.game((CARD,DRAW,REFILL)+(FILL,)*7,enemy_hand=());self.play(g);self.play(g,DRAW)
        selected=self.eligible(g);self.play(g,REFILL);self.assertEqual(len(g.state.players[1].hand),10);self.end(g)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in selected));self.portable(g)

    def test_c02_original_defining_shifter_rearms_in_new_owner_hand(self):
        g=self.game(enemy_deck=('TIME_876',FILL,OTHER));self.play(g);self.play(g,DRAW)
        eid=next(i for i in self.eligible(g)if g.state.entities[i].card_id=='TIME_876')
        old=next(a for a in g.state.entities[eid].abilities if a.kind=='defining_hand_source')
        self.end(g);e=g.state.entities[eid]
        current=next(a for a in e.abilities if a.kind=='defining_hand_source')
        self.assertNotEqual(current.id,old.id);self.assertEqual(current.defining_card_id,'TIME_876')
        self.assertEqual((e.owner,e.controller),(2,1));self.portable(g)
        self.end(g);e=g.state.entities[eid]
        current=next(a for a in e.abilities if a.kind=='defining_hand_source')
        self.assertEqual(current.progress_completions,1);self.assertIn(e.card_id,(OLD,FILL,OTHER))
        self.assertTrue(all(g.events[int(k.split(':')[1])-1].player_id==1 for k in current.progress_keys))
        self.portable(g)

    def test_c03_native_hand_mirror_rebinds_existing_new_opponent_view(self):
        g=self.game(enemy_deck=('DINO_407',FILL,OTHER));self.play(g);self.play(g,DRAW)
        eid=next(i for i in self.eligible(g)if any(a.kind=='hand_mirror'for a in g.state.entities[i].abilities))
        self.assertEqual(g.state.entities[eid].card_id,CARD);self.end(g)
        e=g.state.entities[eid];binding=next(a.hand_mirror for a in e.abilities if a.kind=='hand_mirror')
        self.assertEqual((e.card_id,binding.player_id,binding.play_id),('DINO_407',1,None));self.portable(g)

    def test_d00_source_silence_death_dormancy_or_transfer_before_capture_prevents_trigger(self):
        for operation in (SILENCE,DESTROY,DORMANT,CONTROL):
            with self.subTest(operation=operation):
                g=self.game((CARD,DRAW,operation));self.play(g);self.play(g,DRAW);ids=self.eligible(g)
                self.play(g,operation);self.end(g);self.assertTrue(all(i in g.state.players[2].hand for i in ids))

    def test_d01_passive_summoned_root_works_and_accepted_body_survives_source_death(self):
        for board,hand in (((CARD,),(DRAW,)),((KILL,),(CARD,DRAW))):
            with self.subTest(board=board):
                g=self.game(hand,board=board)
                if CARD in hand:self.play(g)
                self.play(g,DRAW);ids=self.eligible(g);self.end(g)
                self.assertTrue(all(i in g.state.players[1].hand for i in ids));self.portable(g)

    def test_d02_real_pending_transfer_choice_restores_clones_replays_and_resumes_once(self):
        g=self.game(board=(WAIT,));self.play(g);self.play(g,DRAW);ids=self.eligible(g);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].hand,[ids[0]])
        other=self.portable(g);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertEqual(g.snapshot(),before)
        for game in (g,other):
            q=game.state.pending_choice;game.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].hand,ids)

    def test_d03_late_transfer_reaction_error_rolls_back_end_ids_information_and_rng(self):
        g=self.game(board=(FAIL,));self.play(g);self.play(g,DRAW);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertEqual(g.snapshot(),before)

    def test_e00_no_eligible_card_is_rng_neutral_and_private_hand_history_is_not_exposed(self):
        g=self.game((CARD,));self.play(g);rng=g._rng.getstate();self.end(g);self.assertEqual(g._rng.getstate(),rng)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('"hand_entries"','"hand_entry_id"','"owner_turn_history"','"rng_state"'):
                self.assertNotIn(key,wire)


if __name__=='__main__':unittest.main()
