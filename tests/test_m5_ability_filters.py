"""Structural card conditions across physical, generated and frozen candidates."""
import json
import unittest
from dataclasses import replace
import test_m5_cross_zone as foundation
import test_m5_battlecries as battlecry_helpers
from hs_sim.engine import (Game, Scenario, PlayerSetup, CardDefinition, CardType, Zone, Keyword,
    CardAbilityCondition, PoolQuery, GenerationContext, MinionScope, BuffMinionsInZones,
    TransformMinionsInZones, TransformCapturedMinion, minion_references, CardReference,
    SelectChoice, ResolutionError, SnapshotError, CostSpec, CostAuraSpec, RewindSpec,
    UpgradeHandCard, RandomBuffStoredMinion, SummonFromZone, DeathQuery, Resurrect,
    ChooseFromPools, PoolOfferGroup, UnsupportedDefinitionError, MakeDormant)
from hs_sim.engine.effects import (GainArmor, Silence, Destroy, Transform, CopyMinion,
    ReturnToHand, Summon, RequestChoice, ChoiceOption, InvokeBehavior, AddToHand)
from hs_sim.engine.zones import (DrawMatching, DiscardMatching, DestroyDeckMatching,
    ChooseFromZone, MoveCard)
from hs_sim.engine.pools import (PoolCard, resolve_candidates, GenerateFromPool,
    DiscoverFromPool, matches_metadata)
from hs_sim.engine.card_conditions import matches_ability_values
from hs_sim.engine.summon_sources import death_candidates
from hs_sim.engine.spell_history import SpellHistoryQuery, spell_history_candidates

CTX=foundation.CTX


class AbilityFilterTests(unittest.TestCase):
    card=foundation.CrossZoneTests.card
    pool=foundation.CrossZoneTests.pool
    script=foundation.CrossZoneTests.script
    watch=foundation.CrossZoneTests.watch
    play=foundation.CrossZoneTests.play
    cards=foundation.CrossZoneTests.cards
    choose=foundation.CrossZoneTests.choose
    check=foundation.CrossZoneTests.check
    nested=battlecry_helpers.BattlecryTests.nested

    def setUp(self):
        foundation.CrossZoneTests.setUp(self)
        self.r.register_behavior('cry',lambda c:[GainArmor(c.player_id,1)])
        self.card('cry',cost=2,battlecry='cry',tribes=('beast',))
        self.card('plain',cost=2)
        self.card('generic',cost=2,on_play='cry')
        self.pool('ability',('cry','plain','generic'))

    def query(self,**kw):return PoolQuery(ability=CardAbilityCondition(**kw))
    def scope(self,**kw):return MinionScope(query=self.query(**kw))
    def game(self,hand=('script','cry','plain'),deck=('cry','plain'),board=('cry','plain'),enemy=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage',hand=hand,deck=deck,board=board,mana=10,max_mana=10),
            PlayerSetup('warrior',hand=('plain',),deck=('plain',),board=enemy,mana=10,max_mana=10)),
            seed=79,generation_context=CTX),self.r)
    def refs(self,g,**kw):return minion_references(g.state,self.r,1,self.scope(**kw))
    def candidates(self,query=None,pool='ability'):
        return tuple(m.card_id for m in resolve_candidates(self.r,CTX,pool,query or self.query()))
    def buff(self):self.script(lambda c:[BuffMinionsInZones(1,1,1,self.scope(),c.source_id)])
    def reject(self,s):
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)

    def test_filter_buffs_three_zones_only_matching_cards(self):
        self.buff();g=self.game(enemy=('cry',));self.play(g)
        for zone in ('hand','deck','board'):
            self.assertEqual([(c.card_id,c.attack,c.health) for c in self.cards(g,zone)],[('cry',3,5),('plain',2,4)])
        self.assertEqual(self.cards(g,'board',2)[0].attack,2);self.check(g)

    def test_current_condition_distinguishes_silenced_duplicate(self):
        self.script(lambda c:[Silence(c.state.players[1].board[0]),BuffMinionsInZones(1,1,1,self.scope())])
        g=self.game(board=('cry','cry'));self.play(g)
        self.assertEqual([c.attack for c in self.cards(g,'board')],[2,3]);self.check(g)

    def test_printed_condition_matches_silenced_duplicate(self):
        self.script(lambda c:[Silence(c.state.players[1].board[0]),BuffMinionsInZones(1,1,1,self.scope(basis='printed'))])
        g=self.game(board=('cry','cry'));self.play(g)
        self.assertEqual([c.attack for c in self.cards(g,'board')],[3,3]);self.check(g)

    def test_negative_condition_includes_silenced_but_not_live_battlecry(self):
        self.script(lambda c:[Silence(c.state.players[1].board[0]),BuffMinionsInZones(1,1,1,self.scope(present=False))])
        g=self.game(board=('cry','cry','generic'));self.play(g)
        self.assertEqual([c.attack for c in self.cards(g,'board')],[3,2,3]);self.check(g)

    def test_generic_on_play_is_not_structural_battlecry(self):
        self.buff();g=self.game(hand=('script','generic'),deck=(),board=());self.play(g)
        self.assertEqual(self.cards(g,'hand')[0].attack,2);self.check(g)

    def test_ability_condition_intersects_tribe_and_cost(self):
        self.card('other',cost=2,battlecry='cry')
        q=replace(self.query(),tribes_any=('beast',),min_cost=2,max_cost=2)
        self.script(lambda c:[BuffMinionsInZones(1,1,1,MinionScope(query=q))])
        g=self.game(hand=('script','other','cry'));self.play(g)
        self.assertEqual([c.attack for c in self.cards(g,'hand')],[2,3]);self.check(g)

    def test_exclude_physical_source_keeps_same_card_elsewhere(self):
        self.r.register_behavior('batch',lambda c:[BuffMinionsInZones(1,1,1,
            MinionScope(query=self.query(),exclude_source=True),c.source_id)])
        self.card('batch',cost=2,battlecry='batch')
        g=self.game(hand=('batch','batch'),deck=('batch',),board=());self.play(g,'batch')
        self.assertEqual(self.cards(g,'board')[0].attack,2)
        self.assertEqual(self.cards(g,'hand')[0].attack,3);self.assertEqual(self.cards(g,'deck')[0].attack,3);self.check(g)

    def test_dormant_matching_minion_is_not_live_board_target(self):
        self.script(lambda c:[MakeDormant(c.state.players[1].board[0],None),BuffMinionsInZones(1,1,1,self.scope())])
        g=self.game();self.play(g);self.assertEqual(self.cards(g,'board')[0].attack,2);self.check(g)

    def test_upgrade_changes_stored_identity_before_selection(self):
        self.script(lambda c:[UpgradeHandCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),'cry'),
            BuffMinionsInZones(1,1,1,self.scope())])
        g=self.game(hand=('script','plain'),deck=(),board=());self.play(g)
        self.assertEqual((self.cards(g,'hand')[0].card_id,self.cards(g,'hand')[0].attack),('cry',3));self.check(g)

    def test_transform_changes_identity_before_selection(self):
        self.script(lambda c:[Transform(c.state.players[1].board[0],'plain'),BuffMinionsInZones(1,1,1,self.scope())])
        g=self.game();self.play(g);self.assertEqual(self.cards(g,'board')[0].attack,2);self.check(g)

    def test_current_copy_of_silenced_card_does_not_match(self):
        self.script(lambda c:[Silence(c.state.players[1].board[0]),CopyMinion(c.state.players[1].board[0],1),
            CopyMinion(c.state.players[1].board[0],1,mode='base'),BuffMinionsInZones(1,1,1,self.scope())])
        g=self.game(board=('cry',));self.play(g)
        self.assertEqual([c.attack for c in self.cards(g,'board')],[2,2,3]);self.check(g)

    def test_captured_batch_does_not_recheck_later_silence(self):
        self.watch(lambda c:[Silence(c.state.players[1].board[-1])],event='stored_card_buffed')
        self.buff();g=self.game(board=('watch','cry'),deck=());self.play(g)
        self.assertTrue(self.cards(g,'board')[-1].silenced)
        self.assertEqual(self.cards(g,'board')[-1].attack,3);self.check(g)

    def test_captured_batch_skips_transformed_later_target(self):
        self.watch(lambda c:[Transform(c.state.players[1].board[-1],'plain')],event='stored_card_buffed')
        self.buff();g=self.game(board=('watch','cry'),deck=());self.play(g)
        self.assertEqual((self.cards(g,'board')[-1].card_id,self.cards(g,'board')[-1].attack),('plain',2));self.check(g)

    def test_captured_batch_skips_departed_and_returned_stored_card(self):
        def move(c):
            entity=c.state.entities[c.state.players[1].deck[0]]
            return [MoveCard(CardReference.capture(entity),1,Zone.HAND),InvokeBehavior('return',c.source_id,1)]
        self.r.register_behavior('return',lambda c:[MoveCard(CardReference.capture(c.state.entities[c.state.players[1].hand[-1]]),1,Zone.DECK)])
        self.watch(move,event='stored_card_buffed');self.buff()
        g=self.game(hand=('script','cry'),deck=('cry',),board=('watch',));self.play(g)
        self.assertEqual(self.cards(g,'deck')[0].attack,2);self.check(g)

    def test_new_matching_summon_not_added_to_captured_batch(self):
        self.watch(lambda c:[Summon(1,'cry')],event='stored_card_buffed');self.buff()
        g=self.game(hand=('script','cry'),deck=(),board=('watch',));self.play(g)
        self.assertEqual(self.cards(g,'board')[-1].attack,2);self.check(g)

    def test_mid_batch_choice_restores_remaining_physical_targets(self):
        self.watch(lambda c:[RequestChoice(1,(ChoiceOption('ok','OK'),),c.source_id)],event='stored_card_buffed')
        self.buff();g=self.game(board=('watch','cry'));self.play(g);self.check(g);other=g.clone()
        for match in (g,other):
            while match.state.pending_choice:self.choose(match)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.cards(g,'board')[-1].attack,3);self.check(g)

    def test_late_failure_rolls_back_already_buffed_target(self):
        seen=[]
        def fail(c):
            seen.append(c.state.entities[c.event.target_id].attack)
            return [AddToHand(1,'missing')]
        self.watch(fail,event='stored_card_buffed');self.buff();g=self.game(board=('watch',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition: missing'):self.play(g)
        self.assertEqual(seen,[3]);self.assertEqual(g.snapshot(),before)

    def test_empty_matching_set_does_not_consume_rng(self):
        self.buff();g=self.game(hand=('script','plain'),deck=('plain',),board=());before=g.snapshot()['rng_state']
        self.play(g);self.assertEqual(g.snapshot()['rng_state'],before);self.check(g)

    def test_hidden_buff_match_does_not_leak_to_opponent(self):
        self.buff();a=self.game(hand=('script','cry'),deck=('cry',),board=())
        b=self.game(hand=('script','plain'),deck=('plain',),board=());self.play(a);self.play(b)
        self.assertEqual(a.observe(2),b.observe(2));self.assertEqual(a.for_player(2).legal_actions(),b.for_player(2).legal_actions())
        self.assertFalse(any(e['kind']=='stored_card_buffed' for e in a.player_events(2)));self.check(a)

    def test_draw_matching_uses_condition(self):
        self.script(lambda c:[DrawMatching(1,self.query(),'skip',selection='first')]);g=self.game(hand=('script',),deck=('plain','cry'),board=())
        self.play(g);self.assertEqual([c.card_id for c in self.cards(g,'hand')],['cry']);self.check(g)

    def test_discard_matching_uses_condition(self):
        self.script(lambda c:[DiscardMatching(1,self.query(),selection='first')]);g=self.game();self.play(g)
        self.assertEqual([c.card_id for c in self.cards(g,'hand')],['plain']);self.check(g)

    def test_destroy_deck_matching_uses_condition(self):
        self.script(lambda c:[DestroyDeckMatching(1,self.query(),selection='first')]);g=self.game();self.play(g)
        self.assertEqual([c.card_id for c in self.cards(g,'deck')],['plain']);self.check(g)

    def test_random_buff_preselects_matching_candidates(self):
        self.script(lambda c:[RandomBuffStoredMinion(1,attack=1,query=self.query())]);g=self.game();self.play(g)
        self.assertEqual([c.attack for c in self.cards(g,'hand')],[3,2]);self.check(g)

    def test_recruit_matching_does_not_execute_battlecry(self):
        self.script(lambda c:[SummonFromZone(1,query=self.query(),selection='first')]);g=self.game(board=());self.play(g)
        self.assertEqual([c.card_id for c in self.cards(g,'board')],['cry'])
        self.assertEqual(g.state.battlecry_history,[]);self.check(g)

    def test_zone_choice_filters_and_restores(self):
        self.script(lambda c:[ChooseFromZone(1,1,Zone.DECK,self.query(),operation='draw',distinct='entity')])
        g=self.game();self.play(g);self.assertEqual([o.card_id for o in g.state.pending_choice.options],['cry']);self.check(g)
        other=g.clone();self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.check(g)

    def test_fresh_pool_queries_positive_and_negative(self):
        self.assertEqual(self.candidates(),('cry',));self.assertEqual(self.candidates(self.query(present=False)),('generic','plain'))
        self.assertEqual(self.candidates(self.query(basis='printed')),('cry',))

    def test_pool_condition_does_not_consult_live_silence(self):
        self.script(lambda c:[Silence(c.state.players[1].board[0]),GenerateFromPool(1,'ability',self.query())])
        g=self.game(hand=('script',),deck=(),board=('cry',));self.play(g)
        self.assertEqual(self.cards(g,'hand')[0].card_id,'cry');self.check(g)

    def test_unimplemented_known_nonmatch_can_be_filtered_explicitly(self):
        self.card('missing',cost=2,executable=False);self.pool('partial',('cry','missing'))
        self.assertEqual(self.candidates(pool='partial'),('cry',))

    def test_unimplemented_matching_candidate_fails_before_sampling(self):
        self.card('missing',cost=2,battlecry='cry',executable=False);self.pool('partial',('cry','missing'))
        self.script(lambda c:[GenerateFromPool(1,'partial',self.query())]);g=self.game();before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition: missing'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_unknown_ability_inventory_is_not_false(self):
        self.r.register_pool_card(PoolCard('unknown',CardType.MINION,2,self.r.card('cry').metadata))
        self.pool('unknown',('unknown',))
        for condition in (self.query(),self.query(present=False),self.query(basis='printed')):
            with self.assertRaisesRegex(ValueError,'Unknown candidate'):self.candidates(condition,'unknown')

    def test_declared_exclusion_can_remove_unknown_inventory(self):
        self.r.register_pool_card(PoolCard('unknown',CardType.MINION,2,self.r.card('cry').metadata));self.pool('unknown',('unknown','cry'))
        self.assertEqual(self.candidates(replace(self.query(),exclude_card_ids=('unknown',)),'unknown'),('cry',))

    def test_other_filter_can_rule_out_unknown_ability(self):
        self.r.register_pool_card(PoolCard('unknown',CardType.MINION,8,self.r.card('cry').metadata));self.pool('unknown',('unknown','cry'))
        self.assertEqual(self.candidates(replace(self.query(),max_cost=2),'unknown'),('cry',))

    def test_inventory_disagreement_rejected(self):
        self.r._pool_cards['cry']=replace(self.r.pool_card('cry'),battlecry=False)
        with self.assertRaisesRegex(ValueError,'differs'):self.r.validate()

    def test_aliases_cannot_hide_different_ability_identities(self):
        self.card('alias',cost=2,tribes=('beast',))
        self.r._pool_cards['cry']=replace(self.r.pool_card('cry'),identity='same')
        self.r._pool_cards['alias']=replace(self.r.pool_card('alias'),identity='same');self.pool('alias',('cry','alias'))
        with self.assertRaisesRegex(ValueError,'Conflicting generation aliases'):self.r.validate()

    def test_discover_condition_is_preserved_across_rounds_and_restore(self):
        self.script(lambda c:[DiscoverFromPool(1,'ability',self.query(),discoveries=2)])
        g=self.game();self.play(g);self.check(g);other=g.clone()
        for match in (g,other):
            for _ in range(2):
                self.assertEqual([o.card_id for o in match.state.pending_choice.options],['cry']);self.choose(match)
        self.assertEqual(g.snapshot(),other.snapshot());self.check(g)

    def test_grouped_offer_uses_filter_with_aura_affordability(self):
        self.card('web',cost_auras=(CostAuraSpec(CostSpec(delta=9,ability=CardAbilityCondition()),'any'),))
        self.script(lambda c:[ChooseFromPools(1,(PoolOfferGroup('ability',self.query()),),affordable=True)])
        g=self.game(board=('web',));self.play(g);self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_transformation_pool_and_physical_scope_both_use_condition(self):
        self.card('result',cost=4,battlecry='cry');self.pool('transform',('c','result'))
        self.script(lambda c:[TransformMinionsInZones(1,'transform',2,scope=self.scope(),query=replace(self.query(),kinds=(CardType.MINION,)))])
        g=self.game();self.play(g)
        for zone in ('hand','deck','board'):self.assertEqual([c.card_id for c in self.cards(g,zone)],['result','plain'])
        self.check(g)

    def test_death_current_identity_uses_frozen_attachments(self):
        self.script(lambda c:[Silence(c.state.players[1].board[0]),Destroy(c.state.players[1].board[0]),Destroy(c.state.players[1].board[1])])
        g=self.game(board=('cry','cry'));self.play(g)
        current=death_candidates(g.state,self.r,1,DeathQuery(cards=self.query()))
        printed=death_candidates(g.state,self.r,1,DeathQuery(cards=self.query(basis='printed')))
        self.assertEqual([d.id for d in current],[2]);self.assertEqual(len(printed),2);self.check(g)

    def test_filtered_resurrection_restores_base_definition(self):
        self.script(lambda c:[Silence(c.state.players[1].board[0]),Destroy(c.state.players[1].board[0]),
            Resurrect(1,query=DeathQuery(cards=self.query(basis='printed')))])
        g=self.game(board=('cry',));self.play(g);self.assertFalse(self.cards(g,'board')[0].silenced)
        self.assertTrue(any(a.kind=='battlecry' for a in self.cards(g,'board')[0].abilities));self.check(g)

    def test_spell_history_does_not_silently_ignore_ability_condition(self):
        self.script(lambda c:[]);g=self.game();self.play(g)
        self.assertEqual(spell_history_candidates(g.state,self.r,1,SpellHistoryQuery(cards=self.query())),())
        self.assertEqual(len(spell_history_candidates(g.state,self.r,1,SpellHistoryQuery(cards=self.query(present=False)))),1)

    def test_missing_query_context_raises_instead_of_ignoring_filter(self):
        with self.assertRaisesRegex(ValueError,'Unknown candidate'):
            matches_metadata(self.query(),card_id='cry',kind=CardType.MINION,cost=2,meta=self.r.card('cry').metadata,spell_school=None,keywords=())

    def test_invalid_query_and_inventory_types_rejected(self):
        for value in (True,{'ability':'battlecry'},'battlecry'):
            with self.assertRaises(ValueError):PoolQuery(ability=value)
        with self.assertRaises(ValueError):PoolCard('bad',CardType.MINION,2,self.r.card('cry').metadata,battlecry=1)
        with self.assertRaises(ValueError):PoolCard('bad',CardType.SPELL,2,self.r.card('cry').metadata,battlecry=True)
        with self.assertRaises(ValueError):matches_ability_values(CardAbilityCondition(),printed=True,current=1)

    def pending(self):
        self.script(lambda c:[RequestChoice(1,(ChoiceOption('ok','OK',
            (BuffMinionsInZones(1,1,1,self.scope()),)),))]);g=self.game();self.play(g);return g

    def test_suspended_query_restores_before_execution(self):
        g=self.pending();self.check(g);other=g.clone();self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.cards(g,'hand')[0].attack,3);self.check(g)

    def test_corrupt_suspended_ability_condition_rejected(self):
        g=self.pending();s=g.snapshot();self.nested(s['resolution_frame'],'CardAbilityCondition')['fields']['basis']='guess';self.reject(s)

    def test_missing_suspended_ability_field_rejected(self):
        g=self.pending();s=g.snapshot();del self.nested(s['resolution_frame'],'PoolQuery')['fields']['ability'];self.reject(s)

    def test_rewind_repeats_filter_without_accumulating_undone_buffs(self):
        self.script(lambda c:[BuffMinionsInZones(1,1,1,self.scope())],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game();self.play(g);choice=g.state.pending_choice
        g.apply(SelectChoice(1,choice.id,('retry',)))
        self.assertEqual(self.cards(g,'hand')[0].attack,3);self.check(g)

    def test_old_snapshot_schema_is_rejected(self):
        self.buff();s=self.game().snapshot();s['schema_version']=77;self.reject(s)

    def test_real_snapdragon_repeated_batch_restores_and_replays(self):
        from examples.ability_filtered_batches import run
        game,snapshot=run();self.assertIsNotNone(snapshot['state']['pending_choice'])
        self.assertEqual(len(game.state.battlecry_history),4)


if __name__=='__main__':unittest.main()
