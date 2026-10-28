"""Actual growing spell material across casts, physical copies and recovery."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import ignite_card as native
from hs_sim.engine import Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Draw,GrantKeyword,InvokeBehavior,RandomDamage,RequestChoice)
from hs_sim.engine.growing_spell_damage import (DamageGrowingSpell,GrowingDamageProfile,ShuffleGrowingSpell,validate_value)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CostSpec,DamageKind,GrowingSpellDamageValue,
    HealthFlow,HealthLayer,HealthOp,HealthRule,Keyword,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.native_spell_values import bound_value,public_value
from hs_sim.engine.retained_spell_damage import ReturningDamageProfile
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell,CastStoredSpell
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

CARD=native.CARD;P='k629.'
BIG,SHIELD,BONUS,WAIT,FAIL,DRAW,CURRENT,BASE,LOCAL,DISCOUNT,AUTO,FRESH,GENERATED,FIRST,LAST=(P+x for x in
    ('big','shield','bonus','wait','fail','draw','current','base','local','discount','auto','fresh','generated','first','last'))


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_ignite_card(r)
    for cid,extra in ((BIG,{}),(SHIELD,{'keywords':(Keyword.DIVINE_SHIELD,)}),(BONUS,{'spell_damage':3})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=100,metadata=metadata(tribes=()),**extra))
    if mode in ('double','prevent'):
        rule=HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE if mode=='double' else HealthOp.PREVENT,
            2 if mode=='double' else 0,layer=HealthLayer.TARGET,damage_kinds=(DamageKind.SPELL,))
        r.register_card(CardDefinition(P+'rule',P+'rule',CardType.MINION,health=100,health_rules=(rule,),metadata=metadata(tribes=())))
    def ref(c):return CardReference.capture(c.state.entities[c.target_id])
    def history(c,first):
        roots=tuple(p.id for p in c.state.play_history if p.id<c.play.id and p.card_id==CARD)
        selected=roots[0] if first else roots[-1]
        query=WholeCardHistoryQuery(c.player_id,c.play.id,kinds=(CardType.SPELL,),
            exclude_play_ids=tuple(p.id for p in c.state.play_history if p.id<c.play.id and p.id!=selected))
        return (ReplayWholeCards(c.player_id,c.source_id,query),)
    bodies={DRAW:lambda c:(Draw(c.player_id,source_id=c.source_id),),
        CURRENT:lambda c:(CopyCard(ref(c),c.player_id,mode='current',source_id=c.source_id),),
        BASE:lambda c:(CopyCard(ref(c),c.player_id,mode='base',source_id=c.source_id),),
        LOCAL:lambda c:(GrantStoredSpellDamage(ref(c),2,c.source_id),),
        DISCOUNT:lambda c:(ModifyStoredCost(ref(c),CostSpec(set_to=0),source_id=c.source_id),),
        AUTO:lambda c:(CastStoredSpell(ref(c),c.player_id,c.source_id,
            target_id=c.state.players[2].hero_id,targeting='explicit'),),
        FRESH:lambda c:(AddToHand(c.player_id,CARD,c.source_id),),
        GENERATED:lambda c:(CastSpell(c.player_id,CARD,c.source_id,target_id=c.state.players[2].hero_id,targeting='explicit'),),
        FIRST:lambda c:history(c,True),LAST:lambda c:history(c,False)}
    for cid,body in bodies.items():
        extra={'targeting':TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,),relation='friendly')} if cid in (CURRENT,BASE,LOCAL,DISCOUNT,AUTO) else {}
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            metadata=metadata(CardClass.MAGE,tribes=()),**extra))
    def fail(c):raise ResolutionError('K629 deliberate rollback after RNG')
    r.register_behavior(FAIL,fail)
    event={'damage':'damage_dealt','created':'card_created','deck':'card_added_to_deck',
        'counter':'card_committed','counter_second':'card_committed'}.get(mode)
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id);target=c.state.entities.get(e.target_id)
        if mode in ('created','deck'):
            if target is None or target.card_id!=CARD:return ()
            if public_value(target) is None:raise ResolutionError('Successor was published before installing its native value')
        else:
            if source is None or source.card_id!=CARD:return ()
            if mode in ('counter','counter_second'):
                if mode=='counter_second' and sum(p.card_id==CARD for p in c.state.play_history)<2:return ()
                return (CounterSpell(dict(e.data)['window_id']),)
        options=(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
            RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        return (RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WAIT,watch)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,health=100,metadata=metadata(tribes=()),
        triggers=(TriggerSpec(event,WAIT),) if event else ()))
    r.validate();r.freeze();return r


class IgniteCardTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand,*,board=(),enemy=(BIG,),deck=(),mode='normal'):
        self.mode=mode
        if mode in ('damage','created','deck','counter','counter_second'):board=(*board,WAIT)
        if mode in ('double','prevent'):board=(*board,P+'rule')
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',board=enemy,deck=(BIG,)*5,mana=10,max_mana=10)),seed=629),registry(mode))
    def target(self,g):return g.state.players[2].hero_id
    def cast(self,g):return self.play(g,CARD,self.target(g))
    def children(self,g):return [g.state.entities[i] for i in g.state.players[1].deck if g.state.entities[i].card_id==CARD]
    def hits(self,g):return [d.health_result for d in g.state.damage_history if d.health_result.source_card_id==CARD]
    def amount(self,entity):return public_value(entity)
    def resolve_wait(self,g):
        while g.state.pending_choice is not None:
            g=self.portable(g);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'fail')
            self.assertEqual(g.snapshot(),saved);self.choose(g)
        return g
    def rehash(self,saved):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def test_complete_original_script_number_and_two_primary_faces(self):
        d=native.load_batch();row=d['dependencies'][0]['record'];self.assertEqual(row['tags']['TAG_SCRIPT_DATA_NUM_1'],2)
        for o in d['official_observations']:batch.check_face(row,o['face'],o['locale'],display_normalizations=d['display_normalizations'][CARD])
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['source_scope_bound'])

    def test_printed_spell_deals_two_and_shuffles_a_new_three_damage_entity(self):
        g=self.game((CARD,));source=self.cast(g);child=self.children(g)[0]
        self.assertNotEqual(child.id,source);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual((self.hits(g)[0].damage_dealt,self.amount(child),child.cost),(2,3,2))
        self.assertEqual(bound_value(child).parent_cast_id,g.state.cast_history[0].id);self.assertEqual(g.state.players[1].mana,8);self.portable(g)

    def test_drawn_successors_increase_only_their_own_frozen_base(self):
        g=self.game((CARD,DRAW,DRAW,DRAW))
        for expected in (2,3,4,5):
            if expected!=2:self.play(g,DRAW)
            self.cast(g);self.assertEqual(self.hits(g)[-1].damage_dealt,expected)
            self.assertEqual(self.amount(self.children(g)[0]),expected+1)
        self.assertEqual([h.damage_dealt for h in self.hits(g)],[2,3,4,5]);self.portable(g)

    def test_second_printed_copy_stays_two_after_first_copy_shuffles_three(self):
        g=self.game((CARD,CARD));self.cast(g);self.cast(g)
        self.assertEqual([h.damage_dealt for h in self.hits(g)],[2,2]);self.assertEqual([self.amount(e) for e in self.children(g)],[3,3])

    def test_global_spell_damage_is_not_written_into_successor_base(self):
        g=self.game((CARD,DRAW),board=(BONUS,));self.cast(g);self.play(g,DRAW);self.cast(g)
        self.assertEqual([h.damage_dealt for h in self.hits(g)],[5,6]);self.assertEqual(self.amount(self.children(g)[0]),4)

    def test_local_bonus_and_discount_do_not_transfer_to_new_successor(self):
        g=self.game((CARD,LOCAL,DISCOUNT),board=(BONUS,));source=self.entity(g,CARD).id
        self.play(g,LOCAL,source);self.play(g,DISCOUNT,source);self.cast(g);child=self.children(g)[0]
        self.assertEqual(self.hits(g)[0].damage_dealt,7);self.assertEqual((self.amount(child),child.cost),(3,2))
        self.assertEqual([a.kind for a in child.abilities],['on_play','spell_base_value']);self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_recipient_multiplier_does_not_increase_next_base(self):
        g=self.game((CARD,),mode='double');self.cast(g)
        self.assertEqual((self.hits(g)[0].damage_dealt,self.amount(self.children(g)[0])),(4,3))

    def test_prevented_damage_still_shuffles_base_plus_one(self):
        g=self.game((CARD,),mode='prevent');self.cast(g)
        self.assertEqual((self.hits(g)[0].damage_dealt,self.amount(self.children(g)[0])),(0,3));self.portable(g)

    def test_divine_shield_does_not_turn_successor_into_one_damage(self):
        g=self.game((CARD,),enemy=(SHIELD,));target=g.state.players[2].board[0];self.play(g,CARD,target)
        self.assertEqual((self.hits(g)[0].damage_dealt,self.amount(self.children(g)[0])),(0,3))

    def test_friendly_minion_and_both_heroes_are_ordinary_legal_targets(self):
        for side,kind in ((1,'board'),(1,'hero'),(2,'hero')):
            g=self.game((CARD,),board=(BIG,));target=g.state.players[side].board[0] if kind=='board' else g.state.players[side].hero_id
            self.play(g,CARD,target);self.assertEqual(self.hits(g)[0].target_id,target);self.assertEqual(self.amount(self.children(g)[0]),3)

    def test_missing_target_rolls_back_before_any_payment_or_shuffle(self):
        g=self.game((CARD,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,CARD)
        self.assertEqual(g.snapshot(),saved)

    def test_current_copy_preserves_three_without_upgrading_its_sibling(self):
        g=self.game((CARD,DRAW,CURRENT));self.cast(g);self.play(g,DRAW);original=self.entity(g,CARD).id;self.play(g,CURRENT,original)
        copies=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD];self.assertEqual(len(copies),2)
        self.assertEqual([self.amount(g.state.entities[i]) for i in copies],[3,3]);self.cast(g)
        sibling=next(i for i in copies if g.state.entities[i].zone==Zone.HAND)
        self.assertEqual((self.amount(g.state.entities[sibling]),self.amount(self.children(g)[0])),(3,4));self.portable(g)

    def test_base_copy_and_fresh_creation_use_printed_two(self):
        for helper in (BASE,FRESH):
            g=self.game((CARD,DRAW,helper));self.cast(g);self.play(g,DRAW);original=self.entity(g,CARD).id
            self.play(g,helper,original if helper==BASE else None)
            fresh=next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD and i!=original)
            self.assertIsNone(bound_value(fresh));self.assertEqual(self.amount(g.state.entities[original]),3)

    def test_automatic_stored_cast_uses_its_actual_material_without_second_payment(self):
        g=self.game((CARD,DRAW,AUTO));self.cast(g);self.play(g,DRAW);original=self.entity(g,CARD).id;self.play(g,AUTO,original)
        self.assertEqual([h.damage_dealt for h in self.hits(g)],[2,3]);self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(self.amount(self.children(g)[0]),4);self.portable(g)

    def test_fresh_automatic_generated_cast_can_use_printed_default(self):
        g=self.game((GENERATED,));self.play(g,GENERATED)
        self.assertEqual([h.damage_dealt for h in self.hits(g)],[2]);self.assertEqual(self.amount(self.children(g)[0]),3)
        self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_whole_card_replay_keeps_first_printed_and_last_generated_occurrences_distinct(self):
        for helper,amount in ((FIRST,2),(LAST,3)):
            g=self.game((CARD,DRAW,helper));self.cast(g);self.play(g,DRAW);self.cast(g);self.play(g,helper)
            self.assertEqual(self.hits(g)[-1].damage_dealt,amount)
            self.assertEqual(sorted(self.amount(e) for e in self.children(g)),sorted((4,amount+1)));self.portable(g)

    def test_countered_original_pays_but_never_shuffles_a_successor(self):
        g=self.game((CARD,),mode='counter');self.cast(g)
        self.assertEqual(g.state.players[1].mana,8);self.assertFalse(self.children(g));self.assertFalse(self.hits(g));self.portable(g)

    def test_countered_generated_occurrence_keeps_native_three_for_history_replay(self):
        g=self.game((CARD,DRAW,LAST),mode='counter_second');self.cast(g);self.play(g,DRAW);self.cast(g)
        self.assertEqual([h.damage_dealt for h in self.hits(g)],[2]);self.assertFalse(self.children(g))
        self.play(g,LAST);self.assertEqual(self.hits(g)[-1].damage_dealt,3);self.assertEqual(self.amount(self.children(g)[0]),4);self.portable(g)

    def test_damage_wait_recovers_original_base_and_successor_after_failed_choice(self):
        g=self.game((CARD,),mode='damage');self.cast(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(self.children(g))
        g=self.resolve_wait(g);self.assertEqual(self.amount(self.children(g)[0]),3);self.portable(g)

    def test_creation_and_deck_entry_observers_already_see_complete_native_material(self):
        for mode in ('created','deck'):
            g=self.game((CARD,),mode=mode);self.cast(g);self.assertIsNotNone(g.state.pending_choice)
            self.assertEqual(self.amount(self.children(g)[0]),3);g=self.resolve_wait(g);self.portable(g)

    def test_full_runtime_deck_uses_original_capacity_without_allocating_or_rng(self):
        g=self.game((CARD,),deck=(BIG,)*99);saved=g.snapshot();next_id=g.state.next_entity_id;self.cast(g)
        self.assertEqual(len(g.state.players[1].deck),99);self.assertFalse(self.children(g))
        self.assertEqual(g.state.next_entity_id,next_id);self.assertEqual(g.snapshot()['rng_state'],saved['rng_state']);self.portable(g)

    def test_private_ancestry_is_not_exposed_by_existing_base_damage_projection(self):
        g=self.game((CARD,DRAW));self.cast(g);self.play(g,DRAW)
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())
            for private in ('parent_cast_id','spell_base_value','native_spell_value','GrowingSpellDamageValue','rng_state','resolution_frame'):
                self.assertNotIn('"'+private+'"',view)
        self.assertEqual(self.amount(self.entity(g,CARD)),3)

    def test_native_shape_and_profile_policy_cannot_alias_returning_damage(self):
        self.assertNotEqual(asdict(GrowingDamageProfile(CARD,2)),asdict(ReturningDamageProfile(CARD,2)))
        for changes in ({'policy':'return_same_card'},{'policy':True},{'initial_amount':True}):
            with self.assertRaises(ValueError):replace(GrowingDamageProfile(CARD,2),**changes)
        for changes in ({'amount':True},{'amount':0},{'parent_cast_id':True},{'parent_cast_id':0}):
            with self.assertRaises(ValueError):replace(GrowingSpellDamageValue(CARD,3,1),**changes)

    def test_parent_value_rejects_wrong_amount_unknown_cast_and_unexecuted_parent(self):
        g=self.game((CARD,));self.cast(g);value=bound_value(self.children(g)[0])
        for changes in ({'amount':4},{'parent_cast_id':999},{'card_id':BIG}):
            with self.assertRaises(ValueError):validate_value(g.state,g.registry,replace(value,**changes))
        g=self.game((CARD,),mode='counter');self.cast(g)
        with self.assertRaises(ValueError):validate_value(g.state,g.registry,GrowingSpellDamageValue(CARD,3,1))

    def test_recomputed_snapshot_hash_does_not_permit_wrong_native_amount_or_parent(self):
        g=self.game((CARD,));self.cast(g);child=self.children(g)[0];saved=g.snapshot()
        for key,value in (('amount',99),('parent_cast_id',999),('parent_cast_id',True),('source_id',g.state.players[2].hero_id)):
            corrupt=deepcopy(saved);ability=next(a for a in corrupt['state']['entities'][str(child.id)]['abilities'] if a['kind']=='spell_base_value')
            if key=='source_id':ability[key]=value
            else:ability['spell_base_value'][key]=value
            self.rehash(corrupt)
            with self.assertRaises(SnapshotError):Game.from_snapshot(corrupt,registry(self.mode,'corrupt-reader'))

    def test_original_cast_ancestry_cannot_point_to_itself(self):
        g=self.game((CARD,DRAW));self.cast(g);self.play(g,DRAW);self.cast(g)
        child=self.children(g)[0];saved=g.snapshot();corrupt=deepcopy(saved)
        value=corrupt['state']['cast_history'][-1]['native_spell_value']['spell_base_value'];value['parent_cast_id']=g.state.cast_history[-1].id
        self.rehash(corrupt)
        with self.assertRaises(SnapshotError):Game.from_snapshot(corrupt,registry(self.mode,'cycle-reader'))

    def test_pending_requests_require_the_actual_active_cast(self):
        g=self.game((CARD,));self.cast(g)
        for request in (DamageGrowingSpell(1),ShuffleGrowingSpell(1)):
            with self.assertRaises(ValueError):request.validate_in_state(g.state,g.registry)

    def test_old_schema_is_rejected_even_for_an_otherwise_current_snapshot(self):
        g=self.game((CARD,));self.cast(g);saved=g.snapshot();saved['schema_version']-=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(self.mode,'old-schema-reader'))

    def test_complete_host_real_entry_shuffles_a_new_bound_three(self):
        fmt=build_cn37_local_pool_format();r=fmt.registry
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CARD,),mana=10,max_mana=10),PlayerSetup('HERO_08')),
            generation_context=fmt.context,seed=629),r)
        source=self.cast(g);self.assertEqual(self.hits(g)[0].damage_dealt,2)
        child=self.children(g)[0];self.assertEqual(self.amount(child),3);self.assertNotEqual(child.id,source)
        self.assertIn(CARD,r.pool_cards)


if __name__=='__main__':unittest.main()
