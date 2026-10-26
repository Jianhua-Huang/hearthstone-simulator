"""Actual location-use history, native prices and retained original quotes."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest
from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, FILLER
from hs_sim.cards.seaside_location_card import CARD, load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,IllegalAction,PlayerSetup,
    ResolutionError,Scenario,SnapshotError,TargetSpec,UseLocation,Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand,ChoiceOption,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand)
from hs_sim.engine.locations import PlaceLocation,RefreshLocation
from hs_sim.engine.location_uses import CONDITION,HISTORY_PROFILE
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.zones import CardReference,CopyCard
from tools import card_batch as batch

S='k562.'
LOC,LAST=S+'location',S+'last'
CTX=GenerationContext('k562-seaside-location-activation-test','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','native-seaside-test-v1',CTX.target_id,CTX.mode,
        (PoolMember(CARD),),complete=True))
    def fail(c):raise ResolutionError('k562 deliberate resume failure')
    def body(c):
        held=next((c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==CARD),None)
        amount=0 if held is None else quote_unselected_cost(c.state,r,held).amount
        if mode=='body_cost':return (GainArmor(c.player_id,amount),)
        if mode=='body_wait':
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue',(GainArmor(c.player_id,amount),)),
                ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    def copy_other(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==CARD)
        return (CopyCard(CardReference.capture(source),3-c.player_id,mode='current',source_id=c.source_id),)
    scripts={'body':body,'fail':fail,'place':lambda c:(PlaceLocation(c.player_id,LOC),),
        'refresh':lambda c:(RefreshLocation(c.target_id,c.source_id),),
        'give':lambda c:(AddToHand(c.player_id,CARD,c.source_id),),
        'copy_other':copy_other,'bounce':lambda c:(ReturnToHand(c.target_id),)}
    for name,fn in scripts.items():
        r.register_behavior(S+name,fn)
        if name not in ('body','fail'):
            targeting=(TargetSpec(kinds=(CardType.LOCATION,))if name=='refresh'else
                TargetSpec(kinds=(CardType.MINION,))if name=='bounce'else None)
            r.register_card(CardDefinition(S+name,name,CardType.SPELL,on_play=S+name,targeting=targeting))
    for cid,durability in ((LOC,7),(LAST,1)):
        r.register_card(CardDefinition(cid,'Diagnostic location',CardType.LOCATION,cost=2,durability=durability,on_use=S+'body'))
    r.validate();return replace(fmt,context=CTX)


def walk(v):
    if isinstance(v,dict):
        yield v
        for x in v.values():yield from walk(x)
    elif isinstance(v,list):
        for x in v:yield from walk(x)


def rehash(v):
    v['state_hash']=canonical_hash({k:x for k,x in v.items()if k not in ('schema_version','events','events_hash','state_hash')})
    return v


class SeasideLocationCardTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand=(CARD,),*,board=(LOC,),other=(),enemy=(),mode='normal',mana=10):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=(FILLER,)*5,mana=mana,max_mana=mana,mana_cap=max(10,mana)),
            PlayerSetup('HERO_08',hand=other,board=enemy,deck=(FILLER,)*5,mana=10,max_mana=10)),
            seed=562,generation_context=CTX),fixture(mode).registry)

    def price(self,g,player=1):
        e=self.entity(g,CARD,player=player)
        return quote_unselected_cost(g.state,g.registry,e).amount

    def use(self,g,cid=LOC,player=1):
        identity=self.entity(g,cid,player=player,zone='board').id
        g.apply(UseLocation(player,identity));return identity

    def test_complete_original_row_two_primary_faces_and_finite_intrinsic_declaration(self):
        data=load_batch();raw=data['cards'][0]['record']
        self.assertEqual(batch.sha(data['source']),data['source_sha256'])
        self.assertEqual(raw,next(r for r in batch.read(data['source'])if r['id']==CARD))
        for face in data['official_faces']:batch.check_face(raw,face['face'],face['locale'])
        r=fixture().registry;card=r.card(CARD)
        self.assertEqual((card.cost,card.attack,card.health),(10,8,8))
        self.assertEqual((card.intrinsic_costs[0].condition,card.intrinsic_costs[0].delta,
            card.intrinsic_costs[0].history_profile_id),(CONDITION,-2,HISTORY_PROFILE))
        self.assertIn(CARD,r.pool_cards);self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])
        with self.assertRaises(ValueError):replace(card.intrinsic_costs[0],delta=-1)
        with self.assertRaises(ValueError):replace(card.intrinsic_costs[0],history_profile_id='owner-turn.latest-closed-v1')

    def test_actual_location_use_reduces_two_then_real_native_minion_pays_eight(self):
        g=self.game();location=self.use(g);self.assertEqual(self.price(g),8);source=self.play(g,CARD)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(8,2))
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(8,8))
        fact=g.state.play_history[-1].submitted_cost.quote.intrinsic.condition_facts[0]
        self.assertEqual((fact.quantity,fact.selected_ids),(1,(1,)))
        self.assertEqual(fact.records[0].source.entity_id,location);self.portable(g)

    def test_each_activation_of_same_location_counts_once_and_floor_is_zero(self):
        g=self.game((CARD,)+(S+'refresh',)*5)
        for count in range(1,7):
            identity=self.use(g);self.assertEqual(self.price(g),max(0,10-2*count))
            self.assertEqual(len(g.state.location_use_history),count)
            if count<6:self.play(g,S+'refresh',identity)
        self.play(g,CARD);self.assertEqual(g.state.play_history[-1].cost,0)

    def test_printed_location_play_placement_and_refresh_are_not_activations(self):
        g=self.game((CARD,LOC,S+'place',S+'refresh'),board=())
        self.play(g,LOC);self.play(g,S+'place');self.play(g,S+'refresh',self.entity(g,LOC,zone='board').id)
        self.assertFalse(g.state.location_use_history);self.assertEqual(self.price(g),10)
        self.assertEqual(sum(e.kind=='location_activated'for e in g.events),0)

    def test_rejected_cooldown_activation_rolls_back_and_does_not_count(self):
        g=self.game();identity=self.use(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(UseLocation(1,identity))
        self.assertEqual(g.snapshot(),saved);self.assertEqual(self.price(g),8)

    def test_last_use_counts_even_after_original_location_leaves_board(self):
        g=self.game(board=(LAST,));identity=self.use(g,LAST)
        self.assertEqual(g.state.entities[identity].zone,Zone.GRAVEYARD)
        self.assertEqual((self.price(g),g.state.location_use_history[-1].remaining_durability),(8,0));self.portable(g)

    def test_body_captures_price_including_its_already_accepted_activation(self):
        g=self.game(mode='body_cost');self.use(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,8)
        self.assertEqual(self.price(g),8)

    def test_waiting_body_has_one_use_before_completion_restore_and_atomic_bad_choice(self):
        g=self.game(mode='body_wait');self.use(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual((len(g.state.location_use_history),self.price(g)),(1,8))
        self.assertFalse(any(e.kind=='location_used'for e in g.events));saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.location_use_history),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,8)

    def test_only_actual_payers_own_uses_count_and_whole_opponent_prefix_is_retained(self):
        g=self.game(other=(CARD,),enemy=(LOC,));self.use(g);g.apply(EndTurn(1));self.use(g,player=2)
        self.assertEqual((self.price(g),self.price(g,2)),(8,8))
        source=self.play(g,CARD,player=2);self.assertEqual(g.state.play_history[-1].cost,8)
        fact=g.state.play_history[-1].submitted_cost.quote.intrinsic.condition_facts[0]
        self.assertEqual(([r.player_id for r in fact.records],fact.selected_ids),([1,2],(2,)))
        self.assertEqual(g.state.entities[source].controller,2);self.portable(g)

    def test_generated_later_native_card_reads_existing_whole_game_uses(self):
        g=self.game((S+'give',S+'refresh'));identity=self.use(g);self.play(g,S+'refresh',identity);self.use(g)
        self.play(g,S+'give');self.assertEqual(self.price(g),6)
        source=self.play(g,CARD);self.assertEqual(g.state.play_history[-1].cost,6)
        self.assertEqual(g.state.entities[source].base_cost,10)

    def test_current_copy_to_other_player_requotes_their_history_instead_of_baking_discount(self):
        g=self.game((CARD,S+'copy_other'));self.use(g);self.play(g,S+'copy_other')
        self.assertEqual((self.price(g),self.price(g,2)),(8,10));self.portable(g)

    def test_bounce_reuses_game_history_and_preserves_original_printed_cost(self):
        g=self.game((CARD,S+'bounce'));self.use(g);source=self.play(g,CARD);self.play(g,S+'bounce',source)
        self.assertEqual((self.price(g),g.state.entities[source].base_cost),(8,10))
        self.assertEqual(len(g.state.location_use_history),1);self.portable(g)

    def test_later_activation_does_not_rewrite_original_paid_quote(self):
        g=self.game((CARD,S+'refresh'));location=self.use(g);self.play(g,CARD)
        before=g.state.play_history[-1].submitted_cost;self.play(g,S+'refresh',location);self.use(g)
        row=next(p for p in g.state.play_history if p.card_id==CARD)
        self.assertEqual(row.submitted_cost,before);self.assertEqual(row.cost,8)
        self.assertEqual((row.submitted_cost.quote.intrinsic.condition_facts[0].quantity,len(g.state.location_use_history)),(1,2))
        self.portable(g)

    def test_same_player_uses_persist_across_real_turns_and_new_turn_refresh(self):
        g=self.game();self.use(g);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(self.price(g),8);g.apply(EndTurn(1));g.apply(EndTurn(2));self.use(g)
        self.assertEqual(self.price(g),6)

    def test_rehashed_missing_fake_foreign_and_changed_activation_rows_are_rejected(self):
        g=self.game();self.use(g);self.play(g,CARD);saved=g.snapshot()
        for mode in ('missing','duplicate','player','durability','future','source'):
            with self.subTest(mode=mode):
                bad=deepcopy(saved);state=next(x for x in walk(bad)if 'location_use_history'in x);history=state['location_use_history'];row=history[0]
                if mode=='missing':history.clear()
                elif mode=='duplicate':history.append(deepcopy(row))
                elif mode=='player':row['player_id']=2
                elif mode=='durability':row['remaining_durability']+=1
                elif mode=='future':row['event_sequence']+=100000
                else:row['source']['card_id']=CARD
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('normal','reader').registry)

    def test_rehashed_original_price_selection_count_and_old_schema_are_rejected(self):
        g=self.game();self.use(g);self.play(g,CARD);saved=g.snapshot()
        for mode in ('quantity','selected','face','crop'):
            with self.subTest(mode=mode):
                bad=deepcopy(saved);matches=[x for x in walk(bad)if 'selected_ids'in x and 'records'in x and x.get('quantity')==1]
                self.assertTrue(matches)
                for match in matches:
                    if mode=='quantity':match['quantity']=2
                    elif mode=='selected':match['selected_ids']=[2]
                    elif mode=='face':match['records'][0]['source']['card_id']='unknown.location'
                    else:match['records']=[]
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('normal','reader').registry)
        bad=deepcopy(saved);bad['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,fixture().registry)

    def test_real_frontier_discovery_retains_set_one_cost_and_waiting_generated_price_facts(self):
        r=fixture().registry;members=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=r.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual([(m.card_id,m.weight)for m in members],[(CARD,1)])
        g=self.game(('GDB_857',),mana=60);self.use(g);self.play(g,'GDB_857');other=self.portable(g)
        for game in (g,other):
            self.choose(game,next(o.id for o in game.state.pending_choice.options if o.card_id==CARD))
            self.assertEqual(self.price(game),1);self.play(game,CARD);self.assertEqual(game.state.play_history[-1].cost,1)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_price_queries_and_player_projection_are_pure_and_hide_original_history(self):
        g=self.game();self.use(g);saved=g.snapshot()
        for _ in range(2):
            self.assertEqual(self.price(g),8)
            for player in (1,2):
                view=json.dumps(g.for_player(player).observe())
                self.assertNotIn('"location_use_history"',view)
                self.assertNotIn('"selected_ids"',view)
                self.assertNotIn('"remaining_durability"',view)
        self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
