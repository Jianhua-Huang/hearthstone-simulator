"""Special generation exceptions and repeated discovery delivery (R-097)."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from hs_sim.engine import (ActivatedAbilitySpec, CardClass, CardDefinition, CardMetadata, CardType,
    DiscoverFromPool, Game, GenerateFromPool, GenerationContext, GenerationPolicy, Keyword,
    PlayCard, PlayerSetup, PoolQuery, Registry, ResolutionError, Ruleset, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, Zone, SpellRepeatSpec, RewindSpec)
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, GainArmor, InvokeBehavior,
    ReplaceHero, RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.model import AppendageSpec, CostSpec, Rarity
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.replay import build_replay,replay

CONTEXT=GenerationContext('test','experimental')


class DiscoveryDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('discovery-delivery-tests-v1')
        for hero,cls in (('mage',CardClass.MAGE),('warrior',CardClass.WARRIOR)):
            self.r.register_card(CardDefinition(hero,hero,CardType.HERO,health=30,
                metadata=CardMetadata(False,(cls,),None)))
        self.r.register_behavior('noop',lambda c:[])
        for name in ('a','b','c','d'):self.card(name)
        self.card('mage-card',classes=(CardClass.MAGE,))
        self.card('warrior-card',classes=(CardClass.WARRIOR,))
        self.card('titan',keywords=(Keyword.TITAN,),activated_abilities=tuple(ActivatedAbilitySpec(str(n),'noop') for n in range(3)))
        self.card('quest',kind=CardType.SPELL,keywords=(Keyword.QUEST,),executable=False)
        self.pool()

    def card(self,name,kind=CardType.MINION,classes=(CardClass.NEUTRAL,),executable=True,identity=None,**kw):
        fields=dict(cost=8,health=2 if kind==CardType.MINION else 0,attack=2 if kind==CardType.MINION else 0)
        fields.update(kw)
        definition=CardDefinition(name,name,kind,metadata=CardMetadata(True,classes,Rarity.COMMON),**fields)
        if executable:self.r.register_card(definition)
        self.r.register_pool_card(PoolCard.from_definition(definition,identity=identity))
    def pool(self,name='pool',members=('a','b','c','d'),excluded=(),context=CONTEXT):
        self.r.register_pool(PoolDefinition(name,'v1',context.target_id,context.mode,
            tuple(PoolMember(x) for x in members),excluded,context.mode!='experimental'))
    def script(self,fn=None,name='script',kind=CardType.SPELL,**kw):
        self.r.register_behavior('play.'+name,fn or (lambda c:[DiscoverFromPool(1,'pool',source_id=c.source_id)]))
        self.r.register_card(CardDefinition(name,name,kind,on_play='play.'+name,health=2 if kind==CardType.MINION else 0,**kw))
    def discover(self,**kw):self.script(lambda c:[DiscoverFromPool(1,'pool',source_id=c.source_id,**kw)])
    def watch(self,name,fn,event='choice_selected'):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.MINION,health=3,triggers=(TriggerSpec(event,name),)))
    def game(self,hand=('script',),board=(),enemy=(),context=CONTEXT,rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('mage',hand=hand,board=board,mana=10,max_mana=10),
            PlayerSetup('warrior',board=enemy)),seed=57,generation_context=context),self.r,rules)
    def play(self,g,name='script'):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(1,eid));return eid
    def choose(self,g,cid=None):
        choice=g.state.pending_choice;option=next(o for o in choice.options if cid is None or o.card_id==cid)
        g.apply(SelectChoice(choice.player_id,choice.id,(option.id,)));return option.card_id
    def hand(self,g):return [g.state.entities[i] for i in g.state.players[1].hand]
    def check(self,g):
        snap=g.snapshot();self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),self.r).snapshot(),snap)

    def test_default_bans_and_titan_only_exception_are_separate(self):
        self.pool('special',('a','titan','quest'))
        self.assertEqual([m.card_id for m in resolve_candidates(self.r,CONTEXT,'special',PoolQuery())],['a'])
        self.assertEqual([m.card_id for m in resolve_candidates(self.r,CONTEXT,'special',PoolQuery(),policy=GenerationPolicy((Keyword.TITAN,)))],['a','titan'])

    def test_keyword_filter_alone_does_not_override_generation_ban(self):
        self.pool('special',('titan',));query=PoolQuery(keywords_all=(Keyword.TITAN,))
        self.assertEqual(resolve_candidates(self.r,CONTEXT,'special',query),())

    def test_excluded_member_stays_excluded_even_with_exception(self):
        self.pool('special',('a','titan'),excluded=('titan',))
        self.assertEqual([m.card_id for m in resolve_candidates(self.r,CONTEXT,'special',PoolQuery(),policy=GenerationPolicy((Keyword.TITAN,)))],['a'])

    def test_unimplemented_special_candidate_fails_before_rng(self):
        self.pool('special',('quest',));self.script(lambda c:[GenerateFromPool(1,'special',policy=GenerationPolicy((Keyword.QUEST,)))])
        g=self.game();snap=g.snapshot()
        with patch('hs_sim.engine.pools.sample_candidates',side_effect=AssertionError('RNG before validation')):
            with self.assertRaisesRegex(ResolutionError,'quest'):self.play(g)
        self.assertEqual(g.snapshot(),snap)

    def test_titan_generation_preserves_cost_and_ability_instances(self):
        self.pool('special',('titan',));self.script(lambda c:[GenerateFromPool(1,'special',policy=GenerationPolicy((Keyword.TITAN,)),cost=CostSpec(set_to=1))])
        g=self.game();self.play(g);card=self.hand(g)[0]
        self.assertEqual(card.cost,1);self.assertEqual(len([a for a in card.abilities if a.kind=='activated']),3);self.check(g)

    def test_policy_rejects_unrelated_keywords_and_mutable_inputs(self):
        for value in ((Keyword.TAUNT,),[Keyword.TITAN],(Keyword.TITAN,Keyword.TITAN),('titan',)):
            with self.assertRaises(ValueError):GenerationPolicy(value)
        for factory in (GenerateFromPool,DiscoverFromPool):
            with self.assertRaises(ValueError):factory(1,'pool',policy=True)

    def test_exception_does_not_bypass_query_class_cost_or_collectibility(self):
        self.pool('special',('a','titan'))
        self.assertFalse(resolve_candidates(self.r,CONTEXT,'special',PoolQuery(max_cost=7),policy=GenerationPolicy((Keyword.TITAN,))))
        self.assertFalse(resolve_candidates(self.r,CONTEXT,'special',PoolQuery(include_neutral=False),policy=GenerationPolicy((Keyword.TITAN,))))

    def test_explicit_pool_cast_can_use_special_policy(self):
        from hs_sim.engine import CastFromPool
        self.card('special-spell',kind=CardType.SPELL,keywords=(Keyword.QUEST,),executable=False)
        self.pool('special',('special-spell',));self.script(lambda c:[CastFromPool(1,'special',policy=GenerationPolicy((Keyword.QUEST,)))])
        g=self.game();snap=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'special-spell'):self.play(g)
        self.assertEqual(g.snapshot(),snap)

    def test_after_all_defers_all_deliveries_until_final_selection(self):
        self.discover(discoveries=2,destination='board',delivery='after_all');g=self.game();self.play(g);self.choose(g)
        self.assertFalse(g.state.players[1].board);self.check(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].board),2);self.assertFalse(g.state.players[1].hand);self.check(g)

    def test_after_each_delivers_before_next_offer(self):
        self.discover(discoveries=2,destination='board');g=self.game();self.play(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].board),1);self.assertIsNotNone(g.state.pending_choice);self.check(g)
        self.choose(g);self.assertEqual(len(g.state.players[1].board),2);self.check(g)

    def test_replacement_allows_same_card_as_two_independent_entities(self):
        self.discover(discoveries=2,count=4,delivery='after_all');g=self.game();self.play(g);self.choose(g,'a');self.choose(g,'a')
        self.assertEqual([e.card_id for e in self.hand(g)],['a','a']);self.assertEqual(len({e.id for e in self.hand(g)}),2);self.check(g)

    def test_nonreplacement_removes_selected_generation_identity(self):
        self.discover(discoveries=2,count=4,replacement=False);g=self.game();self.play(g);self.choose(g,'a')
        self.assertNotIn('a',[o.card_id for o in g.state.pending_choice.options]);self.choose(g);self.check(g)

    def test_pool_aliases_never_duplicate_offer(self):
        self.card('alias-a',identity='same');self.card('alias-b',identity='same')
        self.pool('aliases',('alias-a','alias-b','a'));self.script(lambda c:[DiscoverFromPool(1,'aliases',count=3)])
        g=self.game();self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{'alias-a','a'});self.check(g)

    def test_exhausted_nonreplacement_pool_delivers_prior_deferred_selections(self):
        self.discover(discoveries=9,count=4,replacement=False,delivery='after_all');g=self.game();self.play(g)
        for cid in ('a','b','c','d'):self.choose(g,cid)
        self.assertIsNone(g.state.pending_choice);self.assertEqual([e.card_id for e in self.hand(g)],['a','b','c','d']);self.check(g)

    def test_new_round_resamples_offers_without_precreating_cards(self):
        self.discover(discoveries=2,count=1,delivery='after_all');g=self.game();self.play(g)
        before=g.state.next_entity_id;first=g.snapshot()['rng_state'];self.choose(g)
        self.assertNotEqual(first,g.snapshot()['rng_state']);self.assertEqual(g.state.next_entity_id,before);self.choose(g);self.check(g)

    def test_class_change_refreshes_next_offer_but_preserves_prior_receipt(self):
        self.pool('classes',('mage-card','warrior-card'))
        self.watch('change',lambda c:[ReplaceHero(1,'warrior')])
        self.script(lambda c:[DiscoverFromPool(1,'classes',PoolQuery(class_mode='current',include_neutral=False),discoveries=2,delivery='after_all')])
        g=self.game(board=('change',));self.play(g);self.choose(g,'mage-card')
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['warrior-card']);self.check(g)
        self.choose(g);self.assertEqual([e.card_id for e in self.hand(g)],['mage-card','warrior-card']);self.check(g)

    def test_source_destroyed_after_first_choice_does_not_cancel_second(self):
        self.script(lambda c:[DiscoverFromPool(1,'pool',source_id=c.source_id,discoveries=2,delivery='after_all')],kind=CardType.MINION)
        self.watch('kill',lambda c:[Destroy(c.event.source_id)])
        g=self.game(board=('kill',));source=self.play(g);self.choose(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.check(g);self.choose(g)
        self.assertEqual(len(self.hand(g)),2);self.check(g)

    def test_full_board_still_offers_choices_but_creates_no_minions(self):
        self.discover(discoveries=2,destination='board',delivery='after_all');g=self.game(board=('a',)*7)
        self.play(g);self.choose(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(any(e.kind=='minion_summoned' for e in g.events));self.check(g)

    def test_capacity_is_checked_for_each_delivery(self):
        self.discover(discoveries=2,destination='board',delivery='after_all');g=self.game(board=('a',)*6)
        self.play(g);self.choose(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(sum(e.kind=='minion_summoned' for e in g.events),1);self.check(g)

    def test_summon_reaction_can_free_space_for_next_deferred_delivery(self):
        self.watch('kill',lambda c:[Destroy(c.target_id)],event='minion_summoned')
        self.discover(discoveries=2,destination='board',delivery='after_all');g=self.game(board=('kill',)+('a',)*5)
        self.play(g);self.choose(g);self.choose(g)
        self.assertEqual(sum(e.kind=='minion_summoned' for e in g.events),2);self.assertEqual(len(g.state.players[1].board),6);self.check(g)

    def test_generated_minions_do_not_execute_battlecry(self):
        self.r.register_behavior('cry',lambda c:[GainArmor(1,9)]);self.card('cry',on_play='cry')
        self.pool('cry',('cry',));self.script(lambda c:[DiscoverFromPool(1,'cry',discoveries=2,destination='board')])
        g=self.game();self.play(g);self.choose(g);self.choose(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.check(g)

    def test_colossal_delivery_uses_shared_capacity(self):
        self.card('limb');self.card('colossal',keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec('limb'),))
        self.pool('big',('colossal',));self.script(lambda c:[DiscoverFromPool(1,'big',discoveries=2,destination='board',delivery='after_all')])
        g=self.game(board=('a',)*4);self.play(g);self.choose(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(g.state.colossal_history),2);self.check(g)

    def test_full_hand_burns_selected_cards_without_rerolling(self):
        self.discover(discoveries=2,count=4,delivery='after_all');g=self.game(hand=('script',)+('a',)*9)
        self.play(g);self.choose(g,'b');self.choose(g,'c')
        burned=[g.state.entities[e.target_id].card_id for e in g.events if e.kind=='card_burned']
        self.assertEqual(burned,['c']);self.assertEqual(len(self.hand(g)),10);self.check(g)

    def test_hand_deliveries_apply_cost_modifier(self):
        self.discover(discoveries=2,cost=CostSpec(set_to=1));g=self.game();self.play(g);self.choose(g);self.choose(g)
        self.assertEqual([e.cost for e in self.hand(g)],[1,1]);self.check(g)

    def test_deck_delivery_keeps_hidden_identity_and_position(self):
        self.discover(discoveries=2,count=4,destination='deck',delivery='after_all',position='bottom',cost=CostSpec(set_to=2))
        g=self.game();self.play(g);self.choose(g,'b');self.choose(g,'c')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],['b','c'])
        self.assertEqual([g.state.entities[i].cost for i in g.state.players[1].deck],[2,2]);self.check(g)

    def test_restoring_second_discovery_keeps_first_result(self):
        self.discover(discoveries=2,count=4,delivery='after_all');g=self.game();self.play(g);self.choose(g,'b');self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match,'c')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual([e.card_id for e in self.hand(g)],['b','c']);self.check(g)

    def test_nested_delivery_choice_keeps_pending_later_delivery(self):
        self.watch('pause',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',()),),c.source_id)],event='minion_summoned')
        self.discover(discoveries=2,destination='board',delivery='after_all');g=self.game(board=('pause',))
        self.play(g);self.choose(g);self.choose(g)
        while g.state.pending_choice:
            self.check(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].board),3);self.check(g)

    def test_opponent_cannot_see_deferred_selections_or_offer_identities(self):
        self.discover(discoveries=2,delivery='after_all');g=self.game();self.play(g);self.choose(g)
        other=g.observe(2);self.assertEqual(other['pending_choice'],{'player_id':1})
        self.assertFalse(any((e.get('target') or {}).get('card_id') in ('a','b','c','d') for e in g.player_events(2)))
        self.assertEqual(g.observe(1)['pending_choice']['purpose'],'pool_discovery');self.check(g)

    def test_missing_eligible_candidate_fails_before_offer_rng(self):
        self.card('missing',executable=False);self.pool('missing',('a','missing'))
        self.script(lambda c:[DiscoverFromPool(1,'missing',discoveries=2)]);g=self.game();snap=g.snapshot()
        with patch('hs_sim.engine.discovery.sample_candidates',side_effect=AssertionError('sampled too soon')):
            with self.assertRaisesRegex(ResolutionError,'missing'):self.play(g)
        self.assertEqual(g.snapshot(),snap)

    def test_invalid_destination_candidate_rolls_back(self):
        self.card('spell',kind=CardType.SPELL);self.pool('mixed',('a','spell'))
        self.script(lambda c:[DiscoverFromPool(1,'mixed',destination='board')]);g=self.game();snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),snap)

    def test_empty_pool_does_not_open_choices_or_consume_rng(self):
        self.pool('empty',());self.script(lambda c:[DiscoverFromPool(1,'empty',discoveries=2)])
        g=self.game();rng=g.snapshot()['rng_state'];self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g)

    def test_zero_discoveries_validates_context_without_randomness(self):
        self.discover(discoveries=0);g=self.game();rng=g.snapshot()['rng_state'];self.play(g)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(g.state.pending_choice);self.check(g)
        g=self.game(context=None);snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),snap)

    def test_huge_count_and_offer_limit_rejected_transactionally(self):
        self.discover(discoveries=9999);g=self.game(rules=Ruleset(max_resolution_steps=60));snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),snap)

    def test_choice_budget_is_cumulative_across_discoveries(self):
        self.discover(discoveries=30);g=self.game(rules=Ruleset(max_resolution_steps=40));self.play(g)
        for _ in range(30):
            snap=g.snapshot()
            try:self.choose(g)
            except ResolutionError:
                self.assertEqual(g.snapshot(),snap);break
        else:self.fail('Discovery continuation reset its budget')

    def test_late_delivery_error_restores_current_selection_only(self):
        self.watch('bad',lambda c:[GainArmor(1,-1)],event='card_added_to_hand')
        self.discover(discoveries=2,delivery='after_all');g=self.game(board=('bad',));self.play(g);self.choose(g);snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),snap);self.assertFalse(self.hand(g));self.check(g)

    def test_lethal_first_delivery_cancels_later_summon(self):
        self.watch('lethal',lambda c:[Damage(c.state.players[2].hero_id,50)],event='minion_summoned')
        self.discover(discoveries=2,destination='board',delivery='after_all');g=self.game(board=('lethal',))
        self.play(g);self.choose(g);self.choose(g)
        self.assertEqual(g.state.status,'finished');self.assertEqual(sum(e.kind=='minion_summoned' for e in g.events),1);self.check(g)

    def test_automatic_spell_random_choices_complete_all_rounds(self):
        from hs_sim.engine import CastSpell
        self.discover(discoveries=2,destination='board',delivery='after_all')
        self.script(lambda c:[CastSpell(1,'script',c.source_id)],name='auto')
        g=self.game(hand=('auto',));self.play(g,'auto');self.assertFalse(g.state.pending_choice)
        self.assertEqual(len(g.state.players[1].board),2);self.check(g)

    def test_automatic_player_choices_restore_sequence(self):
        from hs_sim.engine import CastSpell
        self.discover(discoveries=2);self.script(lambda c:[CastSpell(1,'script',c.source_id,choices='player')],name='auto')
        g=self.game(hand=('auto',));self.play(g,'auto');self.choose(g);self.check(g);self.choose(g)
        self.assertEqual(len(self.hand(g)),2);self.check(g)

    def test_spell_repeat_runs_fresh_discoveries_each_time(self):
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=3,spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        self.discover(discoveries=2);g=self.game(board=('repeat',));self.play(g)
        for _ in range(4):self.choose(g)
        self.assertFalse(g.state.pending_choice);self.assertEqual(len(self.hand(g)),4);self.check(g)

    def test_rewind_replaces_delivered_results_after_discoveries_finish(self):
        self.script(lambda c:[DiscoverFromPool(1,'pool',discoveries=2)],keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game();self.play(g);self.choose(g);self.choose(g)
        choice=g.state.pending_choice;retry=next(o.id for o in choice.options if 'retry' in o.id)
        g.apply(SelectChoice(1,choice.id,(retry,)));self.assertEqual(len(self.hand(g)),0)
        self.choose(g);self.choose(g);self.assertEqual(len(self.hand(g)),2);self.check(g)

    def test_player_port_uses_private_choice_refs_for_each_round(self):
        self.discover(discoveries=2);g=self.game();self.play(g)
        for _ in range(2):
            port=g.for_player(1);listing=port.legal_actions();action=next(a for a in listing['actions'] if a['type']=='select_choice')
            self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(len(self.hand(g)),2);self.check(g)

    def test_invalid_sequence_fields_rejected(self):
        for kw in ({'discoveries':True},{'discoveries':-1},{'delivery':'later'},{'replacement':1},
                   {'destination':'graveyard'},{'destination':'board','cost':CostSpec(set_to=1)},
                   {'position':'bottom'},{'policy':None}):
            with self.assertRaises(ValueError):DiscoverFromPool(1,'pool',**kw)

    def test_corrupt_pending_receipt_offer_and_batch_rejected(self):
        self.discover(discoveries=2,delivery='after_all');g=self.game();self.play(g);self.choose(g)
        def effects(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.ResolvePoolDiscovery'):yield value['fields']
                for child in value.values():yield from effects(child)
            elif isinstance(value,list):
                for child in value:yield from effects(child)
        mutations=(lambda row:row['selection']['fields'].update(card_id='quest'),
            lambda row:row.update(offered_card_ids={'tuple':['quest']}),
            lambda row:row['batch']['fields']['spec']['fields'].update(discoveries=0),
            lambda row:row['batch']['fields']['selections']['tuple'][0]['fields'].update(card_id='quest'))
        for mutate in mutations:
            snap=g.snapshot();rows=list(effects(snap));self.assertTrue(rows)
            for row in rows:mutate(row)
            with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)


class ExcavationGenerationRewardsTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    def game(self,hand,board=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=hand,board=board,mana=10,max_mana=10),
            PlayerSetup('HERO_08')),seed=57,generation_context=GenerationContext('local-2026-09-23','experimental')),self.r)
    def play(self,g,cid):
        g.apply(PlayCard(1,next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)))
    def choose(self,g,cid='TTN_724'):
        choice=g.state.pending_choice;g.apply(SelectChoice(1,choice.id,(next(o.id for o in choice.options if o.card_id==cid),)))
    def check(self,g):
        self.assertEqual(Game.from_snapshot(g.snapshot(),self.r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_hawk_generates_one_cost_titan_with_activated_abilities(self):
        g=self.game(('WW_001t24',));self.play(g,'WW_001t24');card=g.state.entities[g.state.players[1].hand[0]]
        self.assertEqual((card.card_id,card.cost),('TTN_903',1));self.play(g,'TTN_903')
        self.assertEqual(len([a for a in g.state.entities[card.id].abilities if a.kind=='activated']),3);self.check(g)

    def test_ox_discovers_twice_before_summoning_and_can_repeat_identity(self):
        g=self.game(('WW_001t27',));self.play(g,'WW_001t27');self.choose(g)
        self.assertEqual(len(g.state.players[1].board),1);self.check(g);self.choose(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],['WW_001t27','TTN_724','TTN_724'])
        self.assertEqual(g.state.players[1].mana,6);self.check(g)

    def test_ox_summons_colossal_and_respects_later_capacity(self):
        g=self.game(('WW_001t27',));self.play(g,'WW_001t27');self.choose(g,'TID_711');self.choose(g)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertNotIn('TTN_724',[g.state.entities[i].card_id for i in g.state.players[1].board]);self.check(g)

    def test_sample_pools_are_explicit_and_not_formal(self):
        from hs_sim.engine.representative import EXCAVATE_TITAN_POOL_ID,EXCAVATE_EIGHT_POOL_ID
        ctx=GenerationContext('local-2026-09-23','experimental')
        self.assertFalse(self.r.pool(EXCAVATE_TITAN_POOL_ID,ctx).complete);self.assertFalse(self.r.pool(EXCAVATE_EIGHT_POOL_ID,ctx).complete)
        self.assertEqual(len(self.r.pool(EXCAVATE_TITAN_POOL_ID,ctx).members),1)
        self.assertEqual(len(self.r.pool(EXCAVATE_EIGHT_POOL_ID,ctx).members),3)

    def test_all_class_rewards_have_explicit_adapters(self):
        from hs_sim.engine.representative import EXCAVATE_CLASS_REWARDS
        self.assertEqual(set(EXCAVATE_CLASS_REWARDS.values())-set(self.r.cards),set())


if __name__=='__main__':unittest.main()
