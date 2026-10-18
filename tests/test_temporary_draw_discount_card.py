"""Native temporary draw reduction, physical arrival and fixed source display proof."""
from copy import deepcopy
from functools import lru_cache
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.temporary_draw_discount_card import CARD,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,CastWhenDrawnSpec,EndTurn,
    Game,Keyword,PlayerSetup,PlayCard,Rarity,Scenario,SelectChoice,Zone)
from hs_sim.engine.effects import ChoiceOption,Draw,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_sequences import DrawWithCostReduction,DrawWithTemporaryCostReduction
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

P='lookout.test.';FIVE,ZERO,WATCH,AUTO,CAP,BAD,SAVE=(P+x for x in ('five','zero','watch','auto','cap','bad','save'))


@lru_cache(maxsize=None)
def registry(mode,role):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON)
    for cid,cost in ((FIVE,5),(ZERO,0)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=4,metadata=meta))
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.SPELL,cost=7,on_play=P+'armor',metadata=meta,
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec()))
    r.register_behavior(CAP,lambda c:(SetHandCapacity(c.player_id,1),))
    r.register_behavior(BAD,lambda c:(DrawWithTemporaryCostReduction(c.player_id,1,c.source_id,c.state.turn+1),))
    def save(c):
        original=c.state.draw_history[0].entity_id
        return (MoveCard(CardReference.capture(c.state.entities[original]),1,Zone.DECK,position='top'),)
    r.register_behavior(SAVE,save)
    for cid in (CAP,BAD,SAVE):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta))
    if mode:
        def fail(c):raise ResolutionError('Lookout deliberate draw continuation failure')
        r.register_behavior(P+'fail',fail)
        def watch(c):
            ref=CardReference.capture(c.state.entities[c.event.target_id])
            return (RequestChoice(1,(ChoiceOption('ok','Continue'),
                ChoiceOption('extra','Draw another',(Draw(1,source_id=c.source_id),)),
                ChoiceOption('cycle','Leave and redraw same card',(
                    MoveCard(ref,1,Zone.DECK,position='top'),Draw(1,source_id=c.source_id))),
                ChoiceOption('transfer','Give original to opponent',(MoveCard(ref,2,Zone.HAND),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
            limited_triggers=(LimitedTriggerSpec('card_drawn',P+'watch'),)))
    r.validate();r.freeze();return r


class TemporaryDrawDiscountTests(unittest.TestCase):
    def game(self,hand=(CARD,),deck=(FIVE,FIVE),mode=False,pid=1):
        self.mode=mode;self.pid=pid
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==pid else(),
            deck=deck if p==pid else(ZERO,)*10,board=(WATCH,)if p==1 and mode else(),
            mana=50,max_mana=50,mana_cap=50)for p in (1,2))
        g=Game.from_scenario(Scenario(setups,seed=223950),registry(mode,'writer'))
        if pid==2:g.apply(EndTurn(1))
        return g
    def play(self,g,cid=CARD):
        eid=next(i for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.pid,eid,position=0 if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def original(self,g):return g.state.entities[g.state.draw_history[0].entity_id]
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry(self.mode,'reader');self.assertIsNot(r,g.registry)
        self.assertEqual(r.fingerprint(),g.registry.fingerprint());s=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(s,r);self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('resolution_frame','rng_state','source_allocation','behavior_id'):
                self.assertNotIn('"'+key+'"',public)
        return other
    def test_a00_complete_two_rows_primary_faces_and_only_pinned_display_omissions(self):
        d=load_batch();raw=d['cards'][0]['record'];r=registry(False,'writer');card=r.card(CARD)
        self.assertEqual((card.cost,card.attack,card.health),(3,2,3));self.assertNotIn(CARD+'e',r.cards)
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'],d['display_normalizations'][CARD])
        self.assertFalse(d['policy']['formal_pool_complete']);self.assertFalse(d['policy']['cn_calibrated'])
    def test_a01_display_permission_rejects_rules_changes_other_rows_and_name_replacement(self):
        d=load_batch();raw=d['cards'][0]['record'];markers=d['display_normalizations'][CARD]
        for o in d['official_observations']:
            face=deepcopy(o['face']);face['text']=face['text'].replace('(1)','(2)').replace('（1）','（2）')
            self.assertNotEqual(face['text'],o['face']['text'])
            with self.assertRaises(ValueError):check_face(raw,face,o['locale'],markers)
            other=deepcopy(raw);other['id']='lookout.unreviewed'
            with self.assertRaises(ValueError):check_face(other,o['face'],o['locale'],markers)
            with self.assertRaises(ValueError):check_face(raw,o['face'],o['locale'],{'@':'','{5}':'a card'})
    def test_b00_actual_paid_battlecry_draws_once_and_reduces_only_original_arrival(self):
        g=self.game();self.play(g)
        self.assertEqual((len(g.state.draw_history),self.original(g).card_id,self.original(g).cost),(1,FIVE,4))
        self.assertEqual(g.state.players[1].mana,47)
        self.portable(g)
    def test_b01_existing_same_name_hand_card_is_not_discounted(self):
        g=self.game(hand=(FIVE,CARD));old=g.state.players[1].hand[0];self.play(g)
        self.assertNotEqual(self.original(g).id,old);self.assertEqual(g.state.entities[old].cost,5)
        self.assertEqual(self.original(g).cost,4);self.portable(g)
    def test_b02_current_global_turn_end_removes_only_temporary_discount(self):
        g=self.game();self.play(g);original=self.original(g).id;g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[original].cost,5);g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[original].cost,5);self.portable(g)
    def test_b03_zero_cost_draw_keeps_zero_floor_and_returns_to_printed_zero(self):
        g=self.game(deck=(ZERO,));self.play(g);self.assertEqual(self.original(g).cost,0)
        g.apply(EndTurn(1));self.assertEqual(self.original(g).cost,0);self.portable(g)
    def test_b04_playing_original_uses_reduced_actual_mana_payment(self):
        g=self.game();self.play(g);eid=self.original(g).id;g.apply(PlayCard(1,eid,position=1))
        self.assertEqual(g.state.players[1].mana,43);self.assertEqual(g.state.entities[eid].zone,Zone.BOARD);self.portable(g)
    def test_c00_wait_restore_failure_and_extra_draw_keep_original_subject(self):
        g=self.game(mode=True);self.play(g);original=self.original(g).id
        self.assertEqual(g.state.entities[original].cost,5);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game,'extra')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[original].cost,4)
        second=g.state.draw_history[1].entity_id;self.assertEqual(g.state.entities[second].cost,5);self.portable(g)
    def test_c01_same_card_leaving_and_redrawing_does_not_revive_original_hand_reference(self):
        g=self.game(mode=True);self.play(g);original=self.original(g).id;self.choose(g,'cycle')
        self.assertEqual(g.state.draw_history[1].entity_id,original);self.assertEqual(g.state.entities[original].cost,5);self.portable(g)
    def test_c02_transfer_during_draw_reaction_invalidates_old_hand_arrival(self):
        g=self.game(mode=True);self.play(g);original=self.original(g).id;self.choose(g,'transfer')
        self.assertIn(original,g.state.players[2].hand);self.assertEqual(g.state.entities[original].cost,5);self.portable(g)
    def test_c03_discount_in_deck_still_expires_on_original_global_turn(self):
        g=self.game(hand=(CARD,SAVE));self.play(g);original=self.original(g).id;self.play(g,SAVE)
        self.assertEqual((g.state.entities[original].zone,g.state.entities[original].cost),(Zone.DECK,4))
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[original].cost,5);self.portable(g)
    def test_d00_cast_when_drawn_replacement_does_not_inherit_original_discount(self):
        g=self.game(deck=(AUTO,FIVE));self.play(g)
        self.assertEqual([r.outcome for r in g.state.draw_history],['cast','hand'])
        self.assertEqual(g.state.entities[g.state.draw_history[1].entity_id].cost,5)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.portable(g)
    def test_d01_fatigue_and_burn_do_not_discount_unrelated_hand_cards(self):
        g=self.game(deck=());self.play(g);self.assertEqual(g.state.draw_history[0].outcome,'fatigue')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29);self.portable(g)
        g=self.game(hand=(CAP,CARD,FIVE));self.play(g,CAP);self.play(g)
        self.assertEqual(g.state.draw_history[0].outcome,'burned')
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].cost,5);self.portable(g)
    def test_d02_invalid_future_deadline_rolls_back_before_draw_and_payment(self):
        g=self.game(hand=(BAD,));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD)
        self.assertEqual(g.snapshot(),saved);self.portable(g)
    def test_d03_other_player_draw_has_same_turn_expiry_and_own_payment(self):
        g=self.game(pid=2);self.play(g)
        record=next(r for r in g.state.draw_history if r.source_id is not None)
        self.assertEqual((record.player_id,g.state.entities[record.entity_id].cost,g.state.players[2].mana),(2,4,47))
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[record.entity_id].cost,5);self.portable(g)
    def test_d04_temporary_request_is_strict_and_old_permanent_shape_is_unchanged(self):
        from dataclasses import fields
        self.assertEqual([f.name for f in fields(DrawWithCostReduction)],['player_id','reduction','source_id'])
        for args in ((1,1,1,True),(1,1,1,0),(1,-1,1,1),(1,1,0,1)):
            with self.assertRaises(ValueError):DrawWithTemporaryCostReduction(*args)
