"""Creation grants bind new spell entities before any acquisition reaction (R-134)."""
import json
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch
import test_m5_discovery_delivery as foundation
from hs_sim.engine import (CardSpellRepeatGrant as Grant, CardDefinition, CardType, CardClass,
    CardMetadata, Registry, DiscoverFromPool, GenerateFromPool, PoolQuery, Game,
    ResolutionError, SnapshotError, Ruleset, EndTurn, Keyword, RewindSpec, Zone)
from hs_sim.engine.effects import (AddToHand, GainArmor, Draw, Damage, Destroy,
    ChoiceOption, RequestChoice)
from hs_sim.engine.model import CostSpec
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard
from hs_sim.engine.serialization import canonical_hash


class CreationRepeatTests(unittest.TestCase):
    pool=foundation.DiscoveryDeliveryTests.pool
    card=foundation.DiscoveryDeliveryTests.card
    script=foundation.DiscoveryDeliveryTests.script
    watch=foundation.DiscoveryDeliveryTests.watch
    game=foundation.DiscoveryDeliveryTests.game
    play=foundation.DiscoveryDeliveryTests.play
    choose=foundation.DiscoveryDeliveryTests.choose
    hand=foundation.DiscoveryDeliveryTests.hand
    check=foundation.DiscoveryDeliveryTests.check

    def setUp(self):
        self.r=Registry('creation-repeat-tests-v1')
        for hero,cls in (('mage',CardClass.MAGE),('warrior',CardClass.WARRIOR)):
            self.r.register_card(CardDefinition(hero,hero,CardType.HERO,health=30,metadata=CardMetadata(False,(cls,),None)))
        for cid,amount in (('a',2),('b',3),('c',4)):
            self.r.register_behavior(cid,lambda c,n=amount:[GainArmor(c.player_id,n)])
            self.card(cid,kind=CardType.SPELL,cost=1,on_play=cid)
        self.card('filler',cost=1)
        self.pool(members=('a','b','c'))

    def discover(self,**kw):
        self.script(lambda c:[DiscoverFromPool(1,'pool',source_id=c.source_id,spell_repeat=Grant(),**kw)])
    def attached(self,e):return [a for a in e.abilities if a.kind=='card_spell_repeat']
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def generated(self,g):return [e for e in g.state.entities.values() if self.attached(e)]
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))
    def nodes(self,value,suffix):
        if isinstance(value,dict):
            if value.get('type','').endswith('.'+suffix):yield value['fields']
            for item in value.values():yield from self.nodes(item,suffix)
        elif isinstance(value,list):
            for item in value:yield from self.nodes(item,suffix)

    def test_direct_creation_only_new_same_name_copy_repeats(self):
        self.script(lambda c:[AddToHand(1,'a',c.source_id,spell_repeat=Grant(3))])
        g=self.game(hand=('script','a'));self.play(g);old,new=self.hand(g)
        self.assertFalse(self.attached(old));self.assertEqual(self.attached(new)[0].source_id,g.state.play_history[0].source_id)
        self.play(g,'a');self.assertEqual(self.armor(g),2);self.play(g,'a');self.assertEqual(self.armor(g),8);self.check(g)

    def test_created_and_added_reactions_see_cost_and_repeat(self):
        def inspect(c):
            e=c.state.entities[c.event.target_id]
            self.assertEqual(e.cost,0);self.assertEqual(self.attached(e)[0].spell_repeat.casts,3)
            return [GainArmor(1,1)]
        self.watch('create',inspect,'card_created');self.watch('added',inspect,'card_added_to_hand')
        self.script(lambda c:[AddToHand(1,'a',cost=CostSpec(set_to=0),spell_repeat=Grant(3))])
        g=self.game(board=('create','added'));self.play(g);self.assertEqual(self.armor(g),2)
        self.assertFalse(any(e.kind=='card_spell_repeat_added' for e in g.events));self.check(g)

    def test_acquisition_current_copy_inherits_independent_attachment(self):
        self.watch('copy',lambda c:[CopyCard(CardReference.capture(c.state.entities[c.event.target_id]),1)]
            if c.state.entities[c.event.target_id].origin_entity_id is None else [],'card_added_to_hand')
        self.script(lambda c:[AddToHand(1,'a',spell_repeat=Grant())])
        g=self.game(board=('copy',));self.play(g);a,b=self.hand(g)
        self.assertEqual([self.attached(e)[0].spell_repeat.casts for e in (a,b)],[2,2])
        self.assertNotEqual(self.attached(a)[0].id,self.attached(b)[0].id);self.check(g)

    def test_acquisition_transfer_preserves_new_instance_property(self):
        self.watch('move',lambda c:[MoveCard(CardReference.capture(c.state.entities[c.event.target_id]),2,Zone.HAND)],'card_added_to_hand')
        self.script(lambda c:[AddToHand(1,'a',spell_repeat=Grant())])
        g=self.game(board=('move',));self.play(g);e=self.generated(g)[0]
        self.assertEqual((e.controller,e.zone),(2,Zone.HAND));self.assertFalse(self.hand(g));self.check(g)

    def test_full_hand_attaches_burned_new_entity_without_touching_old(self):
        self.script(lambda c:[AddToHand(1,'filler'),AddToHand(1,'a',spell_repeat=Grant())])
        g=self.game(hand=('script','a'),rules=Ruleset(max_hand=2));self.play(g)
        old=self.hand(g)[0];burned=self.generated(g)[0]
        self.assertFalse(self.attached(old));self.assertNotEqual(old.id,burned.id);self.assertEqual(burned.zone,Zone.GRAVEYARD)
        self.assertEqual(sum(e.kind=='card_burned' for e in g.events),1);self.check(g)

    def test_deck_insertion_before_draw_has_property(self):
        self.script(lambda c:[AddToDeck(1,'a','top',c.source_id,spell_repeat=Grant()),Draw(1)])
        g=self.game();self.play(g);self.assertEqual(len(self.generated(g)),1)
        self.play(g,'a');self.assertEqual(self.armor(g),4);self.check(g)

    def test_cost_expiry_and_repeat_expiry_are_independent(self):
        self.script(lambda c:[AddToHand(1,'a',cost=CostSpec(set_to=0),expires_turn=1,spell_repeat=Grant(3,3))])
        g=self.game();self.play(g);g.apply(EndTurn(1));g.apply(EndTurn(2));e=self.hand(g)[0]
        self.assertEqual(e.cost,1);self.assertEqual(self.attached(e)[0].expires_turn,3)
        self.play(g,'a');self.assertEqual(self.armor(g),6);self.check(g)

    def test_repeat_expiry_does_not_remove_permanent_cost(self):
        self.script(lambda c:[AddToHand(1,'a',cost=CostSpec(set_to=0),spell_repeat=Grant(2,1))])
        g=self.game();self.play(g);g.apply(EndTurn(1));e=self.hand(g)[0]
        self.assertEqual(e.cost,0);self.assertFalse(self.attached(e));self.check(g)

    def test_repeat_expiry_without_cost_is_allowed(self):
        self.script(lambda c:[AddToHand(1,'a',spell_repeat=Grant(2,c.state.turn))])
        g=self.game();self.play(g);self.assertEqual(self.attached(self.hand(g)[0])[0].expires_turn,1);self.check(g)

    def test_old_cost_deadline_still_requires_cost(self):
        for factory,args in ((AddToHand,(1,'a')),(AddToDeck,(1,'a')),(GenerateFromPool,(1,'pool')),(DiscoverFromPool,(1,'pool'))):
            with self.subTest(factory=factory.__name__),self.assertRaises(ValueError):factory(*args,expires_turn=1,spell_repeat=Grant())

    def test_creation_carrier_rejects_minion_even_when_burning(self):
        self.script(lambda c:[AddToHand(1,'a'),AddToHand(1,'filler',spell_repeat=Grant())])
        g=self.game(hand=('script','a'),rules=Ruleset(max_hand=2));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_past_deadline_rejects_whole_creation(self):
        self.script(lambda c:[AddToHand(1,'a',spell_repeat=Grant(2,1))]);g=self.game()
        g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_unknown_source_rejects_without_created_identity(self):
        self.script(lambda c:[AddToHand(1,'a',99999,spell_repeat=Grant())]);g=self.game();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_strict_immutable_grant_values(self):
        for kw in ({'casts':True},{'casts':1},{'casts':2.0},{'expires_turn':True},{'expires_turn':0}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):Grant(**kw)
        spec=Grant()
        with self.assertRaises(FrozenInstanceError):spec.casts=3
        for factory,args in ((AddToHand,(1,'a')),(AddToDeck,(1,'a')),(GenerateFromPool,(1,'pool')),(DiscoverFromPool,(1,'pool'))):
            for value in (True,{'casts':2},(Grant(),)):
                with self.subTest(factory=factory.__name__,value=value),self.assertRaises(ValueError):factory(*args,spell_repeat=value)

    def test_board_delivery_rejected_at_declaration(self):
        for factory in (GenerateFromPool,DiscoverFromPool):
            with self.assertRaises(ValueError):factory(1,'pool',destination='board',spell_repeat=Grant())

    def test_random_generation_each_card_has_fresh_attachment(self):
        self.script(lambda c:[GenerateFromPool(1,'pool',count=3,replacement=False,spell_repeat=Grant(3))])
        g=self.game();self.play(g);cards=self.hand(g)
        self.assertEqual({e.card_id for e in cards},{'a','b','c'});self.assertEqual(len({self.attached(e)[0].id for e in cards}),3)
        for e in cards:self.play(g,e.card_id)
        self.assertEqual(self.armor(g),27);self.check(g)

    def test_random_generation_to_deck_keeps_source_and_position(self):
        self.script(lambda c:[GenerateFromPool(1,'pool',count=2,destination='deck',position='top',source_id=c.source_id,spell_repeat=Grant())])
        g=self.game();source=self.play(g);self.assertEqual(len(g.state.players[1].deck),2)
        self.assertTrue(all(e.zone==Zone.DECK and self.attached(e)[0].source_id==source for e in self.generated(g)));self.check(g)

    def test_incompatible_pool_rejected_before_rng_not_filtered(self):
        self.pool('mixed',('a','filler'))
        self.script(lambda c:[GenerateFromPool(1,'mixed',spell_repeat=Grant())]);g=self.game();before=g.snapshot()
        with patch('hs_sim.engine.pools.sample_candidates',side_effect=AssertionError('RNG too soon')):
            with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_explicit_query_can_select_compatible_subpool(self):
        self.pool('mixed',('a','filler'));self.script(lambda c:[GenerateFromPool(1,'mixed',PoolQuery(kinds=(CardType.SPELL,)),spell_repeat=Grant())])
        g=self.game();self.play(g);self.assertEqual([e.card_id for e in self.generated(g)],['a']);self.check(g)

    def test_missing_pool_content_is_not_skipped(self):
        self.card('unknown',kind=CardType.SPELL,executable=False);self.pool('unknown',('a','unknown'))
        self.script(lambda c:[DiscoverFromPool(1,'unknown',spell_repeat=Grant())]);g=self.game();before=g.snapshot()
        with patch('hs_sim.engine.discovery.sample_candidates',side_effect=AssertionError('RNG too soon')):
            with self.assertRaisesRegex(ResolutionError,'unknown'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_zero_discoveries_still_validate_carriers(self):
        self.pool('mixed',('a','filler'));self.script(lambda c:[DiscoverFromPool(1,'mixed',discoveries=0,spell_repeat=Grant())])
        g=self.game();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_empty_pool_does_not_allocate_attachment_or_consume_rng(self):
        self.pool('empty',());self.script(lambda c:[DiscoverFromPool(1,'empty',spell_repeat=Grant())])
        g=self.game();rng=g.snapshot()['rng_state'];before=g.state.next_attachment_id;self.play(g)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.next_attachment_id,before);self.check(g)

    def test_after_each_delivery_then_pause_restores_full_property(self):
        self.discover(discoveries=2);g=self.game();self.play(g);self.choose(g,'a')
        self.assertEqual(len(self.generated(g)),1);self.check(g)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        for match in (g,restored):self.choose(match,'b');self.play(match,'a');self.play(match,'b')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),10);self.check(g)

    def test_after_all_deferred_repeat_and_source_survive_pause(self):
        self.discover(discoveries=2,delivery='after_all');g=self.game();source=self.play(g);self.choose(g,'a')
        self.assertFalse(self.generated(g));self.check(g);self.choose(g,'a')
        self.assertEqual(len(self.generated(g)),2);self.assertTrue(all(self.attached(e)[0].source_id==source for e in self.generated(g)))
        self.assertEqual(len({self.attached(e)[0].id for e in self.generated(g)}),2);self.check(g)

    def test_discovery_without_replacement_exhausts_and_delivers(self):
        self.discover(discoveries=5,replacement=False,delivery='after_all');g=self.game();self.play(g)
        self.choose(g,'a');self.assertNotIn('a',[o.card_id for o in g.state.pending_choice.options]);self.choose(g,'b');self.choose(g,'c')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.generated(g)),3);self.check(g)

    def test_discovery_deck_delivery_survives_deferred_choice(self):
        self.discover(discoveries=2,delivery='after_all',destination='deck',position='bottom');g=self.game();self.play(g)
        self.choose(g,'b');self.check(g);self.choose(g,'a')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],['b','a'])
        self.assertTrue(all(self.attached(e) for e in self.generated(g)));self.check(g)

    def test_discovery_full_hand_burns_only_later_delivered_card(self):
        self.discover(discoveries=2,delivery='after_all');g=self.game(hand=('script','a'),rules=Ruleset(max_hand=2));self.play(g)
        self.choose(g,'a');self.choose(g,'a');cards=self.generated(g)
        self.assertEqual([e.zone for e in cards],[Zone.HAND,Zone.GRAVEYARD]);self.assertFalse(self.attached(self.hand(g)[0]));self.check(g)

    def test_acquisition_pause_saves_installed_state_and_remaining_delivery(self):
        self.watch('pause',lambda c:[RequestChoice(1,(ChoiceOption('ok','OK',()),))],'card_added_to_hand')
        self.discover(discoveries=2,delivery='after_all');g=self.game(board=('pause',));self.play(g)
        self.choose(g,'a');self.choose(g,'b');self.assertEqual(len(self.generated(g)),1);self.check(g)
        self.choose(g);self.assertEqual(len(self.generated(g)),2);self.check(g);self.choose(g);self.check(g)

    def test_late_delivery_failure_restores_choice_and_attachment_ids(self):
        self.watch('bad',lambda c:[GainArmor(1,-1)],'card_added_to_hand')
        self.discover(discoveries=2,delivery='after_all');g=self.game(board=('bad',));self.play(g);self.choose(g,'a');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'b')
        self.assertEqual(g.snapshot(),before);self.assertFalse(self.generated(g));self.check(g)

    def test_source_dies_after_selection_without_revoking_delivery(self):
        self.script(lambda c:[DiscoverFromPool(1,'pool',source_id=c.source_id,discoveries=2,delivery='after_all',spell_repeat=Grant())],kind=CardType.MINION)
        self.watch('kill',lambda c:[Destroy(c.event.source_id)] if c.event.source_id in c.state.players[1].board else [])
        g=self.game(board=('kill',));source=self.play(g);self.choose(g,'a');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.check(g);self.choose(g,'b');self.assertTrue(all(self.attached(e)[0].source_id==source for e in self.generated(g)));self.check(g)

    def test_lethal_first_acquisition_cancels_later_delivery(self):
        self.watch('lethal',lambda c:[Damage(c.state.players[2].hero_id,50)],'card_added_to_hand')
        self.discover(discoveries=2,delivery='after_all');g=self.game(board=('lethal',));self.play(g);self.choose(g,'a');self.choose(g,'b')
        self.assertEqual(g.state.winner,1);self.assertEqual(len(self.generated(g)),1);self.check(g)

    def test_automatic_source_discovery_can_create_hand_play_property(self):
        from hs_sim.engine import CastSpell
        self.discover(discoveries=2);self.script(lambda c:[CastSpell(1,'script',c.source_id)],name='auto')
        g=self.game(hand=('auto',));self.play(g,'auto');self.assertIsNone(g.state.pending_choice)
        cards=self.hand(g);expected=sum({'a':2,'b':3,'c':4}[e.card_id]*2 for e in cards)
        for e in cards:self.play(g,e.card_id)
        self.assertEqual(self.armor(g),expected);self.check(g)

    def test_rewind_removes_first_delivery_before_recreating(self):
        self.script(lambda c:[DiscoverFromPool(1,'pool',spell_repeat=Grant())],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game();self.play(g);self.choose(g,'a');self.assertEqual(len(self.generated(g)),1);self.check(g)
        from hs_sim.engine import SelectChoice
        g.apply(SelectChoice(1,g.state.pending_choice.id,('retry',)));self.assertFalse(self.generated(g));self.choose(g,'b')
        self.assertEqual([e.card_id for e in self.generated(g)],['b']);self.check(g)

    def test_owner_projection_shows_count_but_opponent_and_choices_hide_it(self):
        self.discover(discoveries=2);g=self.game();self.play(g);self.choose(g,'a')
        hand=g.observe(1)['players'][0]['hand'];self.assertEqual(hand[0]['card_spell_repeats'],[dict(casts=2,expires_turn=None)])
        self.assertNotIn('card_spell_repeat',json.dumps(g.observe(2)));self.assertNotIn('CardSpellRepeatGrant',json.dumps(g.for_player(1).observe()))
        self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1});self.check(g)

    def test_identity_reveal_does_not_reveal_created_modifiers(self):
        self.script(lambda c:[AddToHand(1,'a',revealed_to=(2,),spell_repeat=Grant(3))]);g=self.game();self.play(g)
        other=g.observe(2)['players'][0]['hand'][0];self.assertEqual(set(other),{'ref','card_id'});self.assertEqual(other['card_id'],'a');self.check(g)

    def test_pair_states_have_equal_opponent_logs_and_revision(self):
        # Build otherwise identical content packages whose private grant count differs.
        def run(casts):
            r=Registry('paired-creation-v1');r.register_card(CardDefinition('h','h',CardType.HERO,health=30))
            r.register_behavior('s',lambda c:[AddToHand(1,'a',spell_repeat=Grant(casts))])
            r.register_card(CardDefinition('s','s',CardType.SPELL,on_play='s'));r.register_card(CardDefinition('a','a',CardType.SPELL))
            from hs_sim.engine import Scenario,PlayerSetup,PlayCard
            g=Game.from_scenario(Scenario((PlayerSetup('h',hand=('s',)),PlayerSetup('h'))),r);g.apply(PlayCard(1,g.state.players[1].hand[0]));return g
        a,b=run(2),run(3);self.assertEqual(a.for_player(2).observe(),b.for_player(2).observe());self.assertEqual(a.player_events(2),b.player_events(2))

    def test_pending_spec_rejects_malformed_counts_and_extra_fields(self):
        self.discover(discoveries=2);g=self.game();self.play(g)
        for change in (lambda r:r.update(casts=True),lambda r:r.update(casts=1),lambda r:r.update(extra=1),lambda r:r.pop('expires_turn')):
            with self.subTest(change=change):
                s=g.snapshot();rows=list(self.nodes(s,'CardSpellRepeatGrant'));self.assertTrue(rows)
                for row in rows:change(row)
                self.reject(s)

    def test_pending_spec_rejects_missing_creation_field(self):
        self.discover();g=self.game();self.play(g);s=g.snapshot()
        for row in self.nodes(s,'DiscoverFromPool'):row.pop('spell_repeat')
        self.reject(s)

    def test_pending_spec_rejects_changed_carrier_pool(self):
        self.pool('mixed',('a','b','c','filler'));self.discover();g=self.game();self.play(g);s=g.snapshot()
        for row in self.nodes(s,'DiscoverFromPool'):row['pool_id']='mixed'
        self.reject(s)

    def test_nested_creation_rejects_wrong_carrier_on_restore(self):
        self.script(lambda c:[RequestChoice(1,(ChoiceOption('ok','OK',(AddToHand(1,'a',spell_repeat=Grant()),)),))])
        g=self.game();self.play(g);s=g.snapshot()
        for row in self.nodes(s,'AddToHand'):row['card_id']='filler'
        self.reject(s)

    def test_pending_expiry_and_missing_source_rejected_on_restore(self):
        self.discover();g=self.game();g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g)
        s=g.snapshot()
        for row in self.nodes(s,'CardSpellRepeatGrant'):row['expires_turn']=1
        self.reject(s);s=g.snapshot()
        for row in self.nodes(s,'DiscoverFromPool'):row['source_id']=99999
        self.reject(s)

    def test_schema_87_rejected_even_when_no_grant_is_live(self):
        self.discover();g=self.game();s=g.snapshot();self.assertEqual(s['schema_version'],265);s['schema_version']=87;self.reject(s)

    def test_burn_reaction_observes_property_on_burned_card(self):
        def inspect(c):
            e=c.state.entities[c.event.target_id]
            self.assertEqual(e.zone,Zone.GRAVEYARD);self.assertEqual(self.attached(e)[0].spell_repeat.casts,3)
            return [GainArmor(1,1)]
        self.watch('burn',inspect,'card_burned')
        self.script(lambda c:[AddToHand(1,'a'),AddToHand(1,'a',spell_repeat=Grant(3))])
        g=self.game(board=('burn',),rules=Ruleset(max_hand=1));self.play(g);self.assertEqual(self.armor(g),1);self.check(g)

    def test_deck_creation_reaction_can_move_fully_modified_card(self):
        self.watch('draw',lambda c:[MoveCard(CardReference.capture(c.state.entities[c.event.target_id]),1,Zone.HAND,draw=True)],'card_added_to_deck')
        self.script(lambda c:[AddToDeck(1,'a',spell_repeat=Grant(3))]);g=self.game(board=('draw',));self.play(g)
        self.assertEqual(len(self.hand(g)),1);self.play(g,'a');self.assertEqual(self.armor(g),6);self.check(g)

    def test_discovered_cost_and_repeat_have_separate_frozen_deadlines(self):
        self.script(lambda c:[DiscoverFromPool(1,'pool',cost=CostSpec(set_to=0),expires_turn=1,spell_repeat=Grant(3,3))])
        g=self.game();self.play(g);self.check(g);self.choose(g,'a');e=self.hand(g)[0]
        self.assertEqual((e.cost,e.enchantments[0].expires_turn,self.attached(e)[0].expires_turn),(0,1,3))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'a');self.assertEqual(self.armor(g),6);self.check(g)

    def test_empty_zero_discovery_still_rejects_expired_grant(self):
        self.pool('empty',());self.script(lambda c:[DiscoverFromPool(1,'empty',discoveries=0,spell_repeat=Grant(2,1))])
        g=self.game();g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_invalid_cost_rolls_back_deck_grant_before_insertion_rng(self):
        self.script(lambda c:[AddToDeck(1,'a',cost=CostSpec(card_types=(CardType.MINION,),set_to=0),spell_repeat=Grant())])
        g=self.game();before=g.snapshot()
        with patch('hs_sim.engine.zones.insertion_index',side_effect=AssertionError('RNG too soon')):
            with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_acquisition_failure_rolls_back_direct_creation_and_rng(self):
        self.watch('bad',lambda c:[GainArmor(1,-1)],'card_created')
        self.script(lambda c:[GenerateFromPool(1,'pool',spell_repeat=Grant())]);g=self.game(board=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_nested_payload_type_cannot_load_arbitrary_code(self):
        self.discover();g=self.game();self.play(g);s=g.snapshot()
        def tamper(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.CardSpellRepeatGrant'):value['type']='untrusted.Code'
                for v in value.values():tamper(v)
            elif isinstance(value,list):
                for v in value:tamper(v)
        tamper(s);self.reject(s)

    def test_synthetic_terminal_example(self):
        from examples.creation_repeats import run
        g,s=run();self.assertEqual(g.state.winner,1);self.assertEqual(s['schema_version'],265)


if __name__=='__main__':unittest.main()
