"""Warptooth uses original damage packets and original stored physical cards."""
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.warptooth_card import CARD, load_batch, register_warptooth_card
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Damage, DamageBatch,
    Destroy, InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest

P = 'warptooth.test.'
FILL, SHIELD, IMMUNE, WATCH = (P+x for x in ('fill','shield','immune','watch'))
ONE, HERO, BATCH, THREE, REPEAT, OTHER, CONTROL, CYCLE, CLEAR, ADD = (
    P+x for x in ('one','hero','batch','three','repeat','other','control','cycle','clear','add'))
OPS = (ONE,HERO,BATCH,THREE,REPEAT,OTHER,CONTROL,CYCLE,CLEAR,ADD)


def registry(mode=None):
    r = Registry('warptooth-native-tests-v1.'+str(mode)); register_warptooth_card(r)
    r.register_card(CardDefinition(P+'avatar','Hero',CardType.HERO,health=100))
    for cid, flags in ((FILL,()),(SHIELD,(Keyword.DIVINE_SHIELD,)),(IMMUNE,(Keyword.IMMUNE,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=20,keywords=flags))
    def group(c, owner, hero):
        board = c.state.players[owner].board[:3]
        ids = (*board, *((c.state.players[owner].hero_id,) if hero else ()))
        return (DamageBatch(tuple(Damage(i,1,c.source_id) for i in ids)),)
    def reenter(c):
        return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,
            cause=SummonCause.capture(c)),)
    r.register_behavior(P+'reenter',reenter)
    bodies = {
        ONE:lambda c:(Damage(c.target_id,1,c.source_id),),
        HERO:lambda c:(Damage(c.state.players[c.player_id].hero_id,1,c.source_id),),
        BATCH:lambda c:group(c,c.player_id,True), THREE:lambda c:group(c,c.player_id,False),
        REPEAT:lambda c:tuple(Damage(c.target_id,1,c.source_id) for _ in range(4)),
        OTHER:lambda c:group(c,3-c.player_id,True),
        CONTROL:lambda c:(ChangeControl(c.target_id,3-c.state.entities[c.target_id].controller),),
        CYCLE:lambda c:(ReturnToHand(c.target_id),InvokeBehavior(P+'reenter',c.source_id,c.player_id,c.target_id)),
        CLEAR:lambda c:(Destroy(c.target_id,c.source_id),),
        ADD:lambda c:(AddToHand(c.player_id,CARD),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1 if cid==BATCH else 0,on_play=cid,
            targeting=TargetSpec() if cid in (ONE,REPEAT,CONTROL,CYCLE,CLEAR) else None))
    def fail(c):raise ResolutionError('Warptooth deliberate reaction failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        if mode == 'prefix':
            h = health_result(c.event)
            first = next((row.health_result for row in c.state.damage_history if row.health_result.batch_id==h.batch_id),None)
            held = [i for i in (*c.state.players[c.player_id].hand,*c.state.players[c.player_id].deck)
                    if c.state.entities[i].card_id==CARD]
            if h != first or not held:return ()
            source = c.state.entities[held[0]]
        else:
            source = c.state.entities.get(c.event.target_id)
            if source is None or source.card_id != CARD:return ()
        if mode == 'fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        options = (ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),)))
        if source.zone==Zone.HAND:
            options += (ChoiceOption('move','Move original to deck',
                (MoveCard(CardReference.capture(source),c.player_id,Zone.DECK),)),)
        return (RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(P+'watch',watch)
    event = 'health_resolved' if mode=='prefix' else 'hand_progressed' if mode=='progress' else 'minion_summoned'
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=50,
        triggers=(TriggerSpec(event,P+'watch'),)))
    r.validate();return r


class WarptoothTests(unittest.TestCase):
    def game(self, hand=(CARD,), deck=None, board=(FILL,FILL,FILL), mode=None, pid=1, active=None, armor=0):
        self.mode,self.pid = mode,pid
        actor = PlayerSetup(P+'avatar',deck=(FILL,)*8 if deck is None else deck,
            hand=(*hand,*OPS,*OPS),board=(*board,*((WATCH,) if mode else ())),
            mana=30,max_mana=30,mana_cap=30,hand_cap=40,armor=armor)
        other = PlayerSetup(P+'avatar',deck=(FILL,)*8,hand=OPS,board=(FILL,),
            mana=30,max_mana=30,mana_cap=30,hand_cap=40)
        return Game.from_scenario(Scenario((actor,other) if pid==1 else (other,actor),
            active_player=pid if active is None else active,seed=23),registry(mode))

    def play(self,g,cid=BATCH,target=None):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target_id=target));return eid

    def stored(self,g):
        p = g.state.players[self.pid]
        return [i for i in (*p.hand,*p.deck) if g.state.entities[i].card_id==CARD]

    def bodies(self,g):
        return [i for i in g.state.players[self.pid].board if g.state.entities[i].card_id==CARD]

    def select(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));r=registry(self.mode)
        restored=Game.from_snapshot(saved,r)
        self.assertEqual(restored.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in ('damage_history','health_result','resolution_frame','progress_keys','zone_epoch','rng_state'):
                self.assertNotIn('"'+field+'"',visible)
        return restored

    def test_a00_complete_source_faces_actual_metadata_and_no_battlecry(self):
        d=load_batch();row,=d['cards'];raw=row['record'];c=build_registry().card(CARD)
        self.assertEqual(canonical_digest(raw),row['record_sha256'])
        self.assertEqual((c.cost,c.attack,c.health,c.keywords,c.battlecry),(4,3,3,(Keyword.CHARGE,),None))
        self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual(raw['name_en'],'Warptooth')
        self.assertEqual(c.hand_progress.zones,(Zone.HAND,Zone.DECK));self.assertEqual(len(d['official_observations']),2)

    def test_a01_four_actual_characters_include_armored_hero_and_original_hand_body_can_charge(self):
        g=self.game(armor=10);source,=self.stored(g);rng=g.snapshot()['rng_state'];self.play(g)
        self.assertEqual(self.bodies(g),[source]);self.assertEqual(g.state.players[1].mana,29)
        self.assertEqual(g.state.entities[source].card_id,CARD)
        self.assertEqual(g.snapshot()['rng_state'],rng)
        hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.health,hero.armor),(100,9))
        self.assertEqual(len(g.state.play_history),1);self.assertFalse(g.state.battlecry_history)
        target=g.state.players[2].hero_id;g.apply(Attack(1,source,target))
        self.assertEqual(g.state.entities[target].health,97);self.portable(g)

    def test_a02_non_top_deck_source_moves_the_original_entity_without_draw_or_payment(self):
        g=self.game(hand=(),deck=(FILL,CARD,FILL));source,=self.stored(g);before=tuple(g.state.players[1].deck)
        self.play(g);self.assertEqual(self.bodies(g),[source])
        self.assertEqual(tuple(g.state.players[1].deck),tuple(i for i in before if i!=source))
        self.assertFalse(g.state.draw_history);self.assertEqual(g.state.players[1].mana,29);self.portable(g)

    def test_a03_four_hits_on_one_body_do_not_replace_four_distinct_characters(self):
        g=self.game();first=g.state.players[1].board[0];self.play(g,REPEAT,first)
        self.assertFalse(self.bodies(g));self.play(g,THREE);self.assertFalse(self.bodies(g))
        self.play(g,HERO);self.assertEqual(len(self.bodies(g)),1)

    def test_a04_shield_and_immunity_do_not_contribute_actual_damage(self):
        g=self.game(board=(FILL,SHIELD,IMMUNE,FILL));ids=list(g.state.players[1].board);self.play(g)
        self.assertFalse(self.bodies(g));self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[ids[1]].keywords)
        self.play(g,ONE,ids[1]);self.assertFalse(self.bodies(g))
        self.play(g,ONE,ids[3]);self.assertEqual(len(self.bodies(g)),1)

    def test_a05_opponent_turn_and_old_wounds_do_not_supply_current_own_turn_credit(self):
        g=self.game(active=2);source,=self.stored(g);self.play(g,OTHER);self.assertFalse(self.bodies(g))
        g.apply(EndTurn(2));self.play(g,THREE);self.assertFalse(self.bodies(g))
        self.play(g,HERO);self.assertEqual(self.bodies(g),[source])

    def test_a06_ordinary_hand_play_pays_four_and_board_body_does_not_listen(self):
        g=self.game();source=self.play(g,CARD);self.assertEqual(g.state.players[1].mana,26)
        self.play(g);self.assertEqual(self.bodies(g),[source]);self.assertFalse(self.stored(g))
        self.assertEqual(sum(p.card_id==CARD for p in g.state.play_history),1)

    def test_a07_all_original_hand_and_deck_copies_enter_once_in_existing_physical_order(self):
        g=self.game(deck=(FILL,CARD,CARD,FILL));original=self.stored(g);self.play(g)
        self.assertEqual(self.bodies(g),original);self.assertEqual(len(set(original)),3)
        self.assertFalse(self.stored(g));self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_a08_friendly_damage_uses_original_controller_before_later_transfer(self):
        g=self.game();first=g.state.players[1].board[0];self.play(g,THREE);self.play(g,CONTROL,first)
        self.play(g,HERO);self.assertEqual(len(self.bodies(g)),1)
        g=self.game();enemy=g.state.players[2].board[0];self.play(g,ONE,enemy);self.play(g,CONTROL,enemy)
        self.play(g,THREE);self.assertFalse(self.bodies(g))
        self.play(g,HERO);self.assertEqual(len(self.bodies(g)),1)

    def test_b00_wait_at_first_batch_event_does_not_anticipate_later_committed_packets(self):
        g=self.game(mode='prefix');source,=self.stored(g);self.play(g)
        self.assertEqual(len(g.state.damage_history),4)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        restored=self.portable(g);self.select(g);self.select(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.bodies(g),[source]);self.portable(g)

    def test_b01_old_accepted_hand_listener_does_not_follow_transfer_to_deck(self):
        g=self.game(mode='progress');source,=self.stored(g);self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.select(g,'move')
        self.assertEqual(g.state.entities[source].zone,Zone.DECK);self.assertFalse(self.bodies(g))
        self.play(g,HERO);self.assertEqual(self.bodies(g),[source]);self.portable(g)

    def test_b02_real_entry_wait_restores_without_repeating_native_summon(self):
        g=self.game(mode='entry');source,=self.stored(g);self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.bodies(g),[source])
        restored=self.portable(g);self.select(g);self.select(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.bodies(g),[source]);self.portable(g)

    def test_b03_failed_entry_rolls_back_damage_payment_positions_and_listener_work(self):
        g=self.game(mode='fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_b04_failed_choice_preserves_complete_original_prefix_and_resumes_once(self):
        g=self.game(mode='progress');source,=self.stored(g);self.play(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.select(g,'bad')
        self.assertEqual(g.snapshot(),before);self.select(g);self.assertEqual(self.bodies(g),[source])

    def test_b05_full_board_keeps_hidden_original_and_later_damage_can_retry(self):
        g=self.game(board=(FILL,)*7);source,=self.stored(g);self.play(g)
        self.assertFalse(self.bodies(g));self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        self.assertNotIn(CARD,json.dumps(g.for_player(2).observe()))
        self.portable(g);last=g.state.players[1].board[-1];self.play(g,CLEAR,last)
        self.assertFalse(self.bodies(g));self.play(g,HERO);self.assertEqual(self.bodies(g),[source])

    def test_b06_new_acquisition_after_threshold_waits_for_later_actual_damage(self):
        g=self.game(hand=());self.play(g);self.play(g,ADD);source,=self.stored(g)
        self.assertFalse(self.bodies(g));self.play(g,HERO);self.assertEqual(self.bodies(g),[source])

    def test_c00_new_residency_is_distinct_while_repeated_same_residency_is_not(self):
        g=self.game(hand=(CARD,ONE),board=(FILL,FILL));a,b=g.state.players[1].board
        self.play(g,ONE,a);self.play(g,CYCLE,a);self.play(g,ONE,a)
        self.assertFalse(self.bodies(g));self.play(g,ONE,b);self.assertFalse(self.bodies(g))
        self.play(g,HERO);self.assertEqual(len(self.bodies(g)),1);self.portable(g)

    def test_c01_second_player_uses_own_original_turn_and_storage(self):
        g=self.game(pid=2,hand=(),deck=(FILL,CARD));source,=self.stored(g);self.play(g)
        self.assertEqual(self.bodies(g),[source]);self.assertEqual(g.state.players[2].mana,29);self.portable(g)


if __name__=='__main__':unittest.main()
