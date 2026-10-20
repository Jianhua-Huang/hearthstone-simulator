"""Real Phoenix hand selection, successful discard and ordinary copy entry."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.destructive_phoenix_card import CARD, load_batch, register_destructive_phoenix_card
from hs_sim.cards.native_discard_summon_cards import CARD as MALORIAK, register_native_discard_summon_cards
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Registry, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, Destroy, InvokeBehavior,
    RequestChoice, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_deadlines import ScheduleHandRemoval
from hs_sim.engine.model import BattlecryRepeatSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.turn_scheduling import QueueTurns, SkipTurns
from hs_sim.engine.zones import CardReference, CopyCard, DiscardCard, MoveCard

P = 'phoenix.test.'
HERO, BLANK, UNIT, WATCH, REPEAT, OWN = (P+x for x in ('hero','blank','unit','watch','repeat','own'))


@lru_cache(maxsize=12)
def registry(mode='plain', role='writer'):
    r = Registry('destructive-phoenix-native-v1')
    register_destructive_phoenix_card(r)
    register_native_discard_summon_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=200))
    r.register_card(CardDefinition(BLANK, BLANK, CardType.SPELL))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=2, health=3))
    r.register_card(CardDefinition(REPEAT, REPEAT, CardType.MINION, health=8,
                                  battlecry_repeats=(BattlecryRepeatSpec(2,(CardType.MINION,)),)))
    r.register_behavior(P+'own', lambda c:(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id),))
    r.register_card(CardDefinition(OWN, OWN, CardType.MINION, attack=1, health=2, on_discard=P+'own'))
    def ref(c): return CardReference.capture(c.state.entities[c.target_id])
    def roundtrip(c):
        old=ref(c)
        return (MoveCard(old,c.player_id,Zone.DECK),
                MoveCard(replace(old,zone=Zone.DECK,zone_epoch=old.zone_epoch+1),c.player_id,Zone.HAND))
    scripts = dict(discard=lambda c:(DiscardCard(ref(c),c.source_id),), roundtrip=roundtrip,
        copy=lambda c:(CopyCard(ref(c),c.player_id,mode='current',source_id=c.source_id),),
        give=lambda c:(MoveCard(ref(c),3-c.player_id,Zone.HAND,source_id=c.source_id),),
        kill=lambda c:(Destroy(c.target_id,c.source_id),),
        buff=lambda c:(Buff(c.target_id,4,4,c.source_id),),
        change=lambda c:(Transform(c.target_id,UNIT),),
        extra=lambda c:(QueueTurns((c.player_id,),c.source_id),),
        skip=lambda c:(SkipTurns(3-c.player_id,1,c.source_id),))
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        kw={} if name in ('extra','skip') else dict(targeting=TargetSpec(
            zones=(Zone.BOARD,) if name in ('kill','buff','change') else (Zone.HAND,),
            kinds=(CardType.MINION,CardType.SPELL)))
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,target_rule='any_entity',**kw))
    r.register_behavior(P+'fail',lambda c:(_ for _ in ()).throw(ResolutionError('native Phoenix fixture failure')))
    def watch(c):
        if mode in ('plain',):return ()
        event=c.event
        wanted = ('hand_deadline_destruction_step' if mode=='pre' else
                  'minion_summoned' if mode=='summon' else 'card_discarded')
        if event.kind!=wanted:return ()
        if wanted=='minion_summoned' and (not c.state.discard_history or
                c.state.entities[event.target_id].card_id!=CARD):return ()
        if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode=='terminal':return (Damage(c.state.players[3-c.player_id].hero_id,999,c.source_id),)
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=50,triggers=tuple(
        TriggerSpec(kind,P+'watch') for kind in ('card_discarded','hand_deadline_destruction_step','minion_summoned'))))
    r.validate()
    return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in
        ('schema_version','events','events_hash','state_hash')})
    return s


class PhoenixTests(unittest.TestCase):
    def game(self, hand=(CARD,BLANK), board=(), mode='plain', player=1):
        self.mode=mode
        setups=[PlayerSetup(HERO,hand=hand,board=board,deck=(BLANK,)*12,max_mana=10,mana=10),
                PlayerSetup(HERO,deck=(BLANK,)*12,max_mana=10,mana=10)]
        if player==2:setups.reverse()
        return Game.from_scenario(Scenario(tuple(setups),active_player=player),registry(mode))

    def eid(self,g,cid,zone='hand',player=None):
        pid=g.state.active_player if player is None else player
        return next(i for i in getattr(g.state.players[pid],zone) if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None):
        i=self.eid(g,cid);g.apply(PlayCard(g.state.active_player,i,target));return i

    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(str(key),)))

    def ignite(self,g,cid=BLANK):
        target=self.eid(g,cid);source=self.play(g,CARD);self.choose(g,target);return source,target

    def end(self,g,count=1):
        for _ in range(count):g.apply(EndTurn(g.state.active_player))

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=registry(self.mode,'reader')
        self.assertEqual(Game.from_snapshot(deepcopy(s),other).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),other).snapshot(),s)

    def test_a01_pinned_body_and_actual_paid_choice_then_three_owner_ends(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),2)
        self.assertEqual(d['evidence_only'][0]['record']['id'],CARD+'e')
        g=self.game();target=self.eid(g,BLANK);source=self.play(g,CARD)
        self.assertEqual(g.state.players[1].mana,6);self.assertFalse(g.state.hand_deadlines)
        self.portable(g);self.choose(g,target)
        self.assertEqual(g.state.hand_deadlines[0].targets[0].entity_id,target)
        self.end(g,4);self.assertEqual(g.state.entities[target].zone,Zone.HAND)
        self.end(g);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.discard_history),1)
        self.assertEqual(g.state.discard_history[0].source_id,source)
        self.assertEqual(len([i for i in g.state.players[1].board if g.state.entities[i].card_id==CARD]),2)
        self.assertEqual(len(g.state.hand_deadlines),1)  # Summoning is not another battlecry.
        self.portable(g)

    def test_a02_empty_hand_creates_no_choice_or_deadline(self):
        g=self.game((CARD,));self.play(g,CARD)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.hand_deadlines)

    def test_a03_marked_card_is_not_offered_for_second_phoenix(self):
        g=self.game((CARD,CARD,BLANK));_,target=self.ignite(g)
        self.play(g,CARD);q=g.state.pending_choice
        self.assertIsNone(q);self.assertEqual(len(g.state.hand_deadlines),1)
        self.assertEqual(g.state.hand_deadlines[0].targets[0].entity_id,target)

    def test_a04_repeated_battlecry_recomputes_unmarked_candidates(self):
        g=self.game((CARD,BLANK,UNIT),board=(REPEAT,));self.ignite(g)
        q=g.state.pending_choice;self.assertEqual([o.entity_id for o in q.options],[self.eid(g,UNIT)])
        self.choose(g,q.options[0].id);self.assertEqual(len(g.state.hand_deadlines),2)
        self.portable(g);self.end(g,5);self.assertEqual(len(g.state.discard_history),2)
        self.assertEqual(sum(g.state.entities[i].card_id==CARD for i in g.state.players[1].board),3)

    def test_b01_played_or_previously_discarded_card_does_not_summon(self):
        for operation in ('play','discard'):
            with self.subTest(operation=operation):
                g=self.game((CARD,BLANK,P+'discard'));self.ignite(g)
                if operation=='play':self.play(g,BLANK)
                else:self.play(g,P+'discard',self.eid(g,BLANK))
                self.end(g,5);self.assertEqual(len(g.state.players[1].board),1)
                self.assertEqual(g.state.hand_deadlines[0].removed,())
                self.portable(g)

    def test_b02_departure_and_return_does_not_extend_original_residence(self):
        g=self.game((CARD,BLANK,P+'roundtrip'));_,target=self.ignite(g)
        self.play(g,P+'roundtrip',target);self.end(g,5)
        self.assertEqual(g.state.entities[target].zone,Zone.HAND)
        self.assertEqual(len(g.state.players[1].board),1);self.portable(g)

    def test_b03_transfer_keeps_original_controller_binding(self):
        g=self.game((CARD,BLANK,P+'give'));_,target=self.ignite(g)
        self.play(g,P+'give',target);self.end(g,5)
        self.assertIn(target,g.state.players[2].hand);self.assertFalse(g.state.discard_history)

    def test_b04_current_hand_copy_does_not_copy_external_deadline(self):
        g=self.game((CARD,UNIT,P+'copy'));_,target=self.ignite(g,UNIT)
        self.play(g,P+'copy',target);new=self.eid(g,UNIT)
        copies=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==UNIT and i!=target]
        self.assertEqual(len(copies),1);self.end(g,5)
        self.assertIn(copies[0],g.state.players[1].hand);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)

    def test_c01_source_death_or_transform_preserves_original_base_recipe(self):
        for op in ('kill','change'):
            with self.subTest(operation=op):
                g=self.game((CARD,BLANK,P+op));source,_=self.ignite(g)
                self.play(g,P+op,source);self.end(g,5)
                copies=[i for i in g.state.players[1].board if g.state.entities[i].card_id==CARD]
                self.assertEqual(len(copies),1);e=g.state.entities[copies[0]]
                self.assertEqual((e.attack,e.max_health),(5,5));self.portable(g)

    def test_c02_source_buff_is_not_part_of_reported_printed_base_copy_policy(self):
        g=self.game((CARD,BLANK,P+'buff'));source,_=self.ignite(g)
        self.play(g,P+'buff',source);self.end(g,5)
        new=next(i for i in g.state.players[1].board if i!=source)
        self.assertEqual((g.state.entities[new].attack,g.state.entities[new].max_health),(5,5))
        self.assertEqual(g.state.entities[source].attack,9)

    def test_c03_full_board_still_discards_and_records_failed_summon(self):
        g=self.game(board=(UNIT,)*6);_,target=self.ignite(g);self.end(g,5)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(sum(e.kind=='summon_failed' for e in g.events),1);self.portable(g)

    def test_c04_successful_discard_executes_original_native_body_once(self):
        g=self.game((CARD,OWN));self.ignite(g,OWN);self.end(g,5)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,199)
        self.assertEqual(len(g.state.discard_history),1);self.portable(g)

    def test_c05_real_maloriak_reacts_through_original_discard_capture(self):
        g=self.game((CARD,UNIT),board=(MALORIAK,));self.ignite(g,UNIT);self.end(g,5)
        units=[g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id==UNIT]
        self.assertEqual(len(units),1);self.assertEqual((units[0].attack,units[0].max_health),(2,3))
        self.portable(g)

    def test_d01_original_discard_and_summon_waits_are_portable(self):
        for mode in ('pre','wait','summon'):
            with self.subTest(mode=mode):
                g=self.game(board=(WATCH,),mode=mode);self.ignite(g);self.end(g,5)
                self.assertIsNotNone(g.state.pending_choice);self.portable(g)
                before=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'bad')
                self.assertEqual(g.snapshot(),before)
                self.choose(g,'ok');self.assertIsNotNone(g.state.hand_deadlines[0].expired_event)
                self.assertEqual(len(g.state.discard_history),1);self.portable(g)

    def test_d02_discard_reaction_failure_rolls_back_whole_natural_end(self):
        g=self.game(board=(WATCH,),mode='fail');self.ignite(g);self.end(g,4);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertEqual(g.snapshot(),before)

    def test_d03_terminal_discard_stops_copy_and_false_closure(self):
        g=self.game(board=(WATCH,),mode='terminal');self.ignite(g);self.end(g,5)
        self.assertNotEqual(g.state.status,'playing')
        self.assertEqual(sum(g.state.entities[i].card_id==CARD for i in g.state.players[1].board),1)
        self.assertIsNone(g.state.hand_deadlines[0].expired_event);self.portable(g)

    def test_e01_extra_and_skipped_opponent_turns_use_actual_owner_ends(self):
        for operation in ('extra','skip'):
            with self.subTest(operation=operation):
                g=self.game((CARD,BLANK,P+operation));_,target=self.ignite(g)
                self.play(g,P+operation);self.end(g,4)
                self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
                self.assertEqual(len(g.state.discard_history),1);self.portable(g)

    def test_e02_second_player_has_independent_clock_and_source(self):
        g=self.game(player=2);source,target=self.ignite(g);self.end(g,5)
        self.assertEqual(g.state.discard_history[0].player_id,2)
        self.assertEqual(g.state.discard_history[0].source_id,source)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.portable(g)

    def test_f01_full_rehash_rejects_cropped_recipe_and_copy_receipt(self):
        g=self.game();self.ignite(g);self.end(g,5);s=g.snapshot()
        for change in ('clock','source','result','copy'):
            bad=deepcopy(s)
            if change=='clock':bad['state']['hand_deadlines'][0]['request']['owner_ends']=2
            elif change=='source':bad['state']['hand_deadlines'][0]['source_card_id']=UNIT
            elif change=='result':bad['state']['hand_deadlines'][0]['removed']=[]
            else:
                event=next(e for e in bad['events'] if e['kind']=='hand_deadline_copy_accepted')
                event['data']['card_id']=UNIT
            with self.subTest(change=change),self.assertRaises((SnapshotError,ValueError)):
                Game.from_snapshot(rehash(bad),registry())

    def test_f02_player_views_hide_deadline_receipts_and_opponent_hand(self):
        g=self.game();self.ignite(g);before=g.snapshot()
        for pid in (1,2):
            rendered=json.dumps(g.for_player(pid).observe())
            self.assertNotIn('hand_deadline_copy_accepted',rendered)
            self.assertNotIn('owner_ends_at_accept',rendered)
            self.assertNotIn('zone_epoch',rendered)
        self.assertEqual(g.snapshot(),before)

    def test_f03_discard_copy_requires_exactly_one_original_hand_reference(self):
        for cards in (None,()):
            with self.assertRaises(ValueError):ScheduleHandRemoval(1,3,1,'discard_copy',cards)

    def test_f04_waiting_snapshot_cannot_drop_or_retarget_owed_copy(self):
        g=self.game(board=(WATCH,),mode='wait');self.ignite(g);self.end(g,5)
        for change in ('drop','step'):
            bad=deepcopy(g.snapshot());count=[0]
            def mutate(value):
                if isinstance(value,list):
                    for item in list(value):
                        if isinstance(item,dict) and item.get('type','').endswith('.SummonHandDeadlineCopy'):
                            count[0]+=1
                            if change=='drop':value.remove(item)
                            else:item['fields']['step_event']+=1
                        else:mutate(item)
                elif isinstance(value,dict):
                    for item in value.values():mutate(item)
            # Only active work is mutated; captured choice provenance is separate.
            fields=bad['resolution_frame']['fields']
            mutate(fields['prefix']);mutate(fields['continuation'])
            self.assertEqual(count[0],1)
            with self.subTest(change=change),self.assertRaises((SnapshotError,ValueError)):
                Game.from_snapshot(rehash(bad),registry('wait'))


if __name__ == '__main__':
    unittest.main()
