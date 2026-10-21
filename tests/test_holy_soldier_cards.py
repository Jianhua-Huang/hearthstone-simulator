"""Real March/Oathbinder sources, original numerical costs and shared soldier entry."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.holy_soldier_cards import (MARCH,AURA,TOKEN,SPEC,load_batch,register_holy_soldier_cards)
from hs_sim.cards.amitut_card import CARD as AMITUT,register_amitut_card
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddCostModifier,ChoiceOption,Draw,GainArmor,InvokeBehavior,
    RequestChoice,SpendMana)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass,CardMetadata,CastWhenDrawnSpec,CostSpec,Keyword,
    SpellRepeatSpec,SpellSchool,SummonQuantitySpec)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_source_costs import SpellSourceCostObserverProfile
from hs_sim.engine.zones import CardReference,ModifyStoredCost,ReorderZone
from tools.card_batch import canonical,check_face

P='fixture.holy_soldier.'
PLAIN,HOLY,SHADOW,NATIVE,AUTO,OTHER,AUTO_HOLY,DISCOUNT,DRAIN,DRAW,TOP,DOUBLE,REPEAT,WATCH=(P+x for x in
    ('plain','holy','shadow','native','auto','other','auto_holy','discount','drain','draw','top','double','repeat','watch'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(maxsize=None)
def registry(mode=None,role='writer'):
    assert role in('writer','reader')
    r=build_registry();register_holy_soldier_cards(r);register_amitut_card(r)
    r.register_card(CardDefinition(PLAIN,PLAIN,CardType.MINION,health=12,metadata=META))
    for cid,school,native in((HOLY,SpellSchool.HOLY,False),(SHADOW,SpellSchool.SHADOW,False),(NATIVE,SpellSchool.HOLY,True)):
        r.register_behavior(cid,lambda c:(GainArmor(c.player_id,1),))
        kw=dict(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())if native else{}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=2,on_play=cid,spell_school=school,metadata=META,**kw))
    def discount(c):
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==MARCH)
        return(ModifyStoredCost(CardReference.capture(target),CostSpec(delta=-2),c.source_id),)
    def top(c):
        deck=c.state.players[c.player_id].deck
        target=next(i for i in deck if any(a.draw_cast is not None for a in c.state.entities[i].abilities))
        rest=[i for i in deck if i!=target]
        return(ReorderZone(c.player_id,Zone.DECK,(target,*rest)),)
    bodies={AUTO:lambda c:(CastSpell(c.player_id,MARCH,c.source_id),),
        OTHER:lambda c:(CastSpell(3-c.player_id,MARCH,c.source_id),),
        AUTO_HOLY:lambda c:(CastSpell(c.player_id,HOLY,c.source_id),),DISCOUNT:discount,
        DRAIN:lambda c:(SpendMana(c.player_id,3,c.source_id),),DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),TOP:top}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=12,metadata=META,
        summon_quantities=(SummonQuantitySpec(),)))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=12,metadata=META,
        spell_repeats=(SpellRepeatSpec(),)))
    def fail(c):raise ResolutionError('Holy soldier deliberate late failure')
    r.register_behavior(P+'fail',fail)
    if mode:
        event='minion_summoned'if mode=='entry_wait'else'spell_cast_finished'
        def watch(c):
            if mode=='entry_wait':
                if c.state.entities[c.event.target_id].card_id!=TOKEN:return()
            else:
                row=c.state.cast_history[dict(c.event.data)['cast_id']-1]
                if row.card_id!=HOLY:return()
            if mode=='cost_change':return(AddCostModifier(c.player_id,CostSpec(set_to=0),source_id=c.source_id),)
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=12,metadata=META,
            triggers=(TriggerSpec(event,WATCH),)))
    return r


class HolySoldierTests(unittest.TestCase):
    def game(self,mode=None,*,hand=(MARCH,),board=(),mana=10,enemy_mana=5,deck=(PLAIN,)*8,seat=1):
        self.mode=mode;self.seat=seat
        own=PlayerSetup('HERO_08',hand=hand,board=board+((WATCH,)if mode else()),deck=deck,
            mana=mana,max_mana=max(10,mana),mana_cap=max(10,mana))
        other=PlayerSetup('HERO_01',hand=(HOLY,),deck=(PLAIN,)*8,mana=enemy_mana,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=372),registry(mode))
    def play(self,g,cid=MARCH,pid=None):
        pid=self.seat if pid is None else pid
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def tokens(self,g,pid=None):
        return[g.state.entities[i]for i in g.state.players[self.seat if pid is None else pid].board
            if g.state.entities[i].card_id==TOKEN]
    def stats(self,g,pid=None):return[(e.attack,e.max_health)for e in self.tokens(g,pid)]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def finish(self,g):
        while g.state.pending_choice:self.choose(g)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=registry(self.mode,'reader')
        self.assertIsNot(r,g.registry)
        for other in(g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Original mana number, observed spell cost and Aura clock must restore')
        return Game.from_snapshot(s,r)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in('schema_version','events','events_hash','state_hash')});return s

    def test_three_complete_records_and_six_primary_faces_keep_exact_token(self):
        d=load_batch();rows={x['record']['id']:x for x in d['cards']+d['dependencies']}
        self.assertEqual(len(d['official_observations']),6)
        for x in rows.values():self.assertEqual(canonical(x['record']),x['record_sha256'])
        for o in d['official_observations']:check_face(rows[o['card_id']]['record'],o['face'],o['locale'],{'@':''}if o['card_id']==MARCH else None)
        token=registry().card(TOKEN);self.assertEqual((token.cost,token.attack,token.health),(1,1,1))
        self.assertEqual(token.keywords,(Keyword.DIVINE_SHIELD,))

    def test_march_pays_original_remaining_mana_and_summons_that_number(self):
        g=self.game(mana=7);source=self.play(g);self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual(self.stats(g),[(7,7)]);self.assertIn(Keyword.DIVINE_SHIELD,self.tokens(g)[0].keywords)
        self.assertEqual(g.state.entities[source].base_attack,0);self.assertEqual(g.state.cast_history[-1].source_cost.quote_input.base_cost,7);self.portable(g)

    def test_hand_quote_tracks_mana_without_inventing_spell_attack_or_mutating_on_query(self):
        g=self.game(hand=(MARCH,DRAIN),mana=7);self.play(g,DRAIN)
        entity=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==MARCH)
        self.assertEqual((entity.base_cost,entity.base_attack,entity.base_health),(4,0,0));before=g.snapshot()
        for _ in range(2):self.assertEqual(g.quote_cost(entity.id).amount,4);g.for_player(1).legal_actions()
        self.assertTrue(g.snapshot()==before)

    def test_local_discount_changes_payment_but_not_original_remaining_number(self):
        g=self.game(hand=(MARCH,DISCOUNT),mana=7);self.play(g,DISCOUNT);self.play(g)
        self.assertEqual(g.state.players[1].mana,2);self.assertEqual(self.stats(g),[(7,7)])
        quote=g.state.cast_history[-1].source_cost;self.assertEqual((quote.quote_input.base_cost,quote.amount),(7,5))

    def test_automatic_march_uses_acceptance_mana_without_a_hand_payment(self):
        g=self.game(hand=(AUTO,),mana=6);self.play(g,AUTO)
        self.assertEqual(g.state.players[1].mana,6);self.assertEqual(self.stats(g),[(6,6)])
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.cast_history[-1].origin,'effect');self.portable(g)

    def test_automatic_other_player_uses_actual_caster_number(self):
        g=self.game(hand=(OTHER,),mana=9,enemy_mana=5);self.play(g,OTHER)
        self.assertEqual(self.stats(g,2),[(5,5)]);self.assertFalse(self.tokens(g,1))
        self.assertEqual(g.state.cast_history[-1].source_cost.quote_input.player_id,2)

    def test_zero_mana_automatic_floor_is_explicit_internal_family_policy(self):
        g=self.game(hand=(AUTO,),mana=0);self.play(g,AUTO)
        self.assertEqual(self.stats(g),[(1,1)]);self.assertEqual(g.state.players[1].mana,0)
        self.assertFalse(load_batch()['cn_calibrated'])

    def test_native_hand_repetition_keeps_original_submitted_number(self):
        g=self.game(board=(REPEAT,),mana=6);self.play(g)
        self.assertEqual(self.stats(g),[(6,6),(6,6)]);self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual([c.source_cost.quote_input.base_cost for c in g.state.cast_history],[6,6]);self.portable(g)

    def test_summon_quantity_uses_same_frozen_number_and_one_spell_payment(self):
        g=self.game(board=(DOUBLE,),mana=6);self.play(g)
        self.assertEqual(self.stats(g),[(6,6),(6,6)]);self.assertEqual(len(g.state.cast_history),1)

    def test_march_full_board_still_pays_without_rng_or_delayed_body(self):
        g=self.game(board=(PLAIN,)*7,mana=6);rng=g._rng.getstate();self.play(g)
        self.assertFalse(self.tokens(g));self.assertEqual(g.state.players[1].mana,0);self.assertEqual(g._rng.getstate(),rng)

    def test_aura_installs_three_ends_and_observes_its_own_holy_cost(self):
        g=self.game(hand=(AURA,HOLY,SHADOW));source=self.play(g,AURA)
        effect,=g.state.players[1].player_effects
        self.assertEqual((effect.spec_id,effect.source_id,effect.remaining_turns),(SPEC,source,3))
        self.assertEqual(self.stats(g),[(3,3)]);self.play(g,HOLY);self.play(g,SHADOW)
        self.assertEqual(self.stats(g),[(3,3),(2,2)]);self.portable(g)

    def test_aura_ignores_opponent_holy_cast(self):
        g=self.game(hand=(AURA,));self.play(g,AURA);g.apply(EndTurn(1));self.play(g,HOLY,pid=2)
        self.assertEqual(self.stats(g),[(3,3)])

    def test_three_controller_ends_expire_and_opponent_ends_do_not_tick(self):
        g=self.game(hand=(AURA,));self.play(g,AURA)
        for expected in(2,2,1,1):
            g.apply(EndTurn(g.state.active_player));self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,expected)
        g.apply(EndTurn(1));self.assertFalse(g.state.players[1].player_effects);self.portable(g)

    def test_automatic_holy_cost_is_observed_even_though_no_mana_was_paid(self):
        g=self.game(hand=(AURA,AUTO_HOLY));self.play(g,AURA);mana=g.state.players[1].mana;self.play(g,AUTO_HOLY)
        self.assertEqual(g.state.players[1].mana,mana);self.assertEqual(self.stats(g),[(3,3),(2,2)])
        self.assertEqual(g.state.cast_history[-1].source_cost.amount,2)

    def test_printed_draw_cast_and_granted_amitut_copy_share_observed_cost(self):
        for native in(True,False):
            deck=(NATIVE,PLAIN)if native else(HOLY,PLAIN)
            hand=(AURA,DRAW)if native else(AURA,AMITUT,TOP,DRAW)
            g=self.game(hand=hand,deck=deck,mana=20);self.play(g,AURA)
            if not native:self.play(g,AMITUT);self.play(g,TOP)
            self.play(g,DRAW);self.assertEqual(self.stats(g),[(3,3),(2,2)])
            cast=next(c for c in g.state.cast_history if c.origin=='draw');self.assertEqual(cast.source_cost.amount,2)
            self.portable(g)

    def test_march_body_and_aura_use_different_original_numeric_operands(self):
        g=self.game(hand=(AURA,MARCH,DISCOUNT));self.play(g,AURA);self.play(g,DISCOUNT);self.play(g)
        self.assertEqual(self.stats(g),[(3,3),(7,7),(5,5)]);self.assertEqual(g.state.players[1].mana,2)

    def test_completed_quote_survives_earlier_completion_cost_change(self):
        g=self.game('cost_change',hand=(AURA,HOLY));self.play(g,AURA);self.play(g,HOLY)
        self.assertEqual(self.stats(g),[(3,3),(2,2)]);self.assertEqual(g.state.cast_history[-1].source_cost.amount,2)

    def test_independent_aura_instances_each_deliver_their_own_soldier(self):
        g=self.game(hand=(AURA,AURA,HOLY));self.play(g,AURA);self.play(g,AURA)
        self.assertEqual(len(g.state.players[1].player_effects),2);self.assertEqual(self.stats(g),[(3,3)]*3)
        self.play(g,HOLY);self.assertEqual(self.stats(g),[(3,3)]*3+[(2,2)]*2)

    def test_completion_wait_freezes_quote_then_restores_and_rolls_back_failed_choice(self):
        g=self.game('wait',hand=(AURA,HOLY));self.play(g,AURA);self.play(g,HOLY);before=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==before)
        self.finish(g);self.finish(other);self.assertTrue(g.snapshot()==other.snapshot())
        self.assertEqual(self.stats(g),[(3,3),(2,2)]);self.portable(g)

    def test_entry_wait_keeps_original_march_number_after_mana_is_spent(self):
        g=self.game('entry_wait',mana=6);self.play(g);self.assertEqual(g.state.players[1].mana,0)
        other=self.portable(g);self.finish(g);self.finish(other);self.assertTrue(g.snapshot()==other.snapshot())
        self.assertEqual(self.stats(g),[(6,6)])

    def test_failed_holy_completion_restores_payment_programs_history_and_rng(self):
        g=self.game('fail',hand=(AURA,HOLY));self.play(g,AURA);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,HOLY)
        self.assertTrue(g.snapshot()==before)

    def test_observer_is_typed_registered_and_cannot_borrow_other_program(self):
        with self.assertRaises(ValueError):SpellSourceCostObserverProfile(SPEC,SpellSchool.FIRE)
        r=build_registry();register_holy_soldier_cards(r)
        with self.assertRaises(ValueError):r.register_spell_source_cost_observer(SpellSourceCostObserverProfile(SPEC))
        r.register_spell_source_cost_observer(SpellSourceCostObserverProfile('missing.program'))
        with self.assertRaises(ValueError):r.freeze()

    def test_saved_original_cost_cannot_be_dropped_or_replaced_after_rehash(self):
        g=self.game('wait',hand=(AURA,HOLY));self.play(g,AURA);self.play(g,HOLY);before=g.snapshot()
        for mode in('missing','amount','base'):
            s=deepcopy(before);row=s['state']['cast_history'][-1]
            if mode=='missing':row['source_cost']=None
            elif mode=='amount':row['source_cost']['amount']+=1
            else:row['source_cost']['quote_input']['base_cost']+=1
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry(self.mode,'reader'))

    def test_second_seat_and_player_views_hide_original_cost_and_native_operands(self):
        g=self.game('wait',hand=(AURA,HOLY),seat=2);self.play(g,AURA);self.play(g,HOLY);before=g.snapshot()
        for pid in(1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid));g.for_player(pid).legal_actions()
            for key in('source_cost','quote_input','remaining_mana_card_id','spell_source_cost_observers'):
                self.assertNotIn('"'+key+'"',public)
        self.assertTrue(g.snapshot()==before);self.portable(g)
