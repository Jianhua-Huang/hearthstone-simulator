"""Versioned-pool summoning and portal generation/draw/growth compositions."""
from dataclasses import replace
import json
import unittest
from hs_sim.engine import (Game,Scenario,PlayerSetup,CardDefinition,CardMetadata,CardType,CardClass,Rarity,
    PlayCard,UseHeroPower,EndTurn,SelectChoice,TriggerSpec,Keyword,Zone,GenerationContext,PoolQuery,
    SummonFromPool,Imbue,imbue_value,CastSpell,CastStoredSpell,RewindSpec,ResolutionError,SnapshotError)
from hs_sim.engine.effects import (Draw,Summon,Damage,GainArmor,AddToHand,RequestChoice,ChoiceOption,
    ReplaceHeroPower,RefreshHeroPower,ReplaceHero,Destroy,InvokeBehavior,Silence)
from hs_sim.engine.zones import AddToDeck,CardReference,MoveCard,CopyCard,DrawMatching,ReorderZone
from hs_sim.engine.pools import PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.representative import build_registry,PORTAL_POOL_ID,PORTAL_SAMPLE_IDS
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
PORTAL='EDR_445pt3'
CTX=GenerationContext('local-2026-09-23','experimental')


class PortalFixtures:
    def setUp(self):
        self.r=build_registry()
        self.script('draw',lambda c:[Draw(c.player_id,source_id=c.source_id)])
        self.script('grow',lambda c:[Imbue(c.player_id,c.source_id,2)])
    def script(self,cid,fn,**kw):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,**kw))
    def watch(self,fn,event='card_drawn'):
        self.r.register_behavior('watch',fn)
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=5,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=()),triggers=(TriggerSpec(event,'watch'),)))
    def game(self,hand=('draw',),deck=(PORTAL,'CS2_182'),board=(),enemy=(),enemy_deck=('CS2_182',)*3,
             power='EDR_445p',context=CTX,hero='HERO_04'):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,deck=deck,board=board,
            hero_power_card_id=power,mana=10,max_mana=10),PlayerSetup('HERO_08',board=enemy,
            deck=enemy_deck,mana=10,max_mana=10)),seed=65,generation_context=context),self.r)
    def play(self,g,cid='draw',player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid));return eid
    def use(self,g):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
    def cards(self,g,zone='board',player=1):return [g.state.entities[i].card_id for i in getattr(g.state.players[player],zone)]
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def choose(self,g):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(c.options[0].id,)))
    def is_portal(self,c):return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==PORTAL
    def ref(self,c,zone='deck',p=1,index=0):return CardReference.capture(c.state.entities[getattr(c.state.players[p],zone)[index]])
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as caught:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(caught.exception))


class PoolSummonTests(PortalFixtures,unittest.TestCase):
    def summon(self,**kw):return SummonFromPool(1,PORTAL_POOL_ID,PoolQuery(min_cost=1,max_cost=1,tribes_any=('dragon',)),**kw)
    def test_named_pool_resolves_one_minion(self):
        self.script('pool',lambda c:[self.summon(source_id=c.source_id)])
        g=self.game(hand=('pool',));self.play(g,'pool');self.assertEqual(self.cards(g),['BRM_004']);self.check(g)
    def test_full_board_does_not_consume_randomness(self):
        self.script('pool',lambda c:[self.summon()]);g=self.game(hand=('pool',),board=('CS2_182',)*7)
        rng=g._rng.getstate();self.play(g,'pool');self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(self.cards(g)),7);self.check(g)
    def test_empty_pool_skip_preserves_rng_and_continues(self):
        self.script('pool',lambda c:[SummonFromPool(1,PORTAL_POOL_ID,PoolQuery(min_cost=50)),GainArmor(1,2)])
        g=self.game(hand=('pool',));rng=g._rng.getstate();self.play(g,'pool')
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.check(g)
    def test_empty_error_rolls_back(self):
        self.script('pool',lambda c:[SummonFromPool(1,PORTAL_POOL_ID,PoolQuery(min_cost=50),empty='error')])
        g=self.game(hand=('pool',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'pool')
        self.assertEqual(g.snapshot(),before)
    def test_missing_pool_errors_even_when_full(self):
        self.script('pool',lambda c:[SummonFromPool(1,'missing')]);g=self.game(hand=('pool',),board=('CS2_182',)*7);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'pool')
        self.assertEqual(g.snapshot(),before)
    def test_missing_context_errors(self):
        self.script('pool',lambda c:[self.summon()]);g=self.game(hand=('pool',),context=None);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'pool')
        self.assertEqual(g.snapshot(),before)
    def test_unadapted_eligible_minion_not_removed_on_full_board(self):
        d=CardDefinition('unadapted','unadapted',CardType.MINION,cost=1,health=2,
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('dragon',)))
        self.r.register_pool_card(PoolCard.from_definition(d))
        self.r.register_pool(PoolDefinition('missing','v1',CTX.target_id,CTX.mode,(PoolMember('BRM_004'),PoolMember('unadapted'))))
        self.script('pool',lambda c:[SummonFromPool(1,'missing')]);g=self.game(hand=('pool',),board=('CS2_182',)*7);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'pool')
        self.assertEqual(g.snapshot(),before)
    def test_sequential_calls_recheck_space_after_reactions(self):
        self.watch(lambda c:[Destroy(c.event.source_id)] if c.state.entities[c.event.source_id].card_id=='BRM_004' else [],'minion_summoned')
        self.script('pool',lambda c:[self.summon(),self.summon()])
        g=self.game(hand=('pool',),board=('watch',)+('CS2_182',)*5);self.play(g,'pool')
        self.assertEqual(len(g.state.death_history),2);self.assertEqual(len(self.cards(g)),6);self.check(g)
    def test_captured_query_does_not_change_after_choice_growth(self):
        self.script('capture',lambda c:[RequestChoice(1,(ChoiceOption('grow','grow',(Imbue(1,c.source_id,2),)),)),self.summon()])
        g=self.game(hand=('capture',));self.play(g,'capture');self.check(g);self.choose(g)
        self.assertEqual(imbue_value(g.state,1),2);self.assertEqual(self.cards(g),['BRM_004']);self.check(g)
    def test_pending_pool_source_and_query_survive_restore(self):
        self.script('wait',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok'),)),self.summon(source_id=c.source_id)])
        g=self.game(hand=('wait',));self.play(g,'wait');self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)
    def test_corrupt_pending_pool_rejected(self):
        self.script('wait',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok'),)),self.summon(source_id=c.source_id)])
        g=self.game(hand=('wait',));self.play(g,'wait');s=g.snapshot()
        def alter(v):
            if isinstance(v,dict):
                if v.get('type','').endswith('.SummonFromPool'):v['fields']['pool_id']='missing'
                for x in v.values():alter(x)
            elif isinstance(v,list):
                for x in v:alter(x)
        alter(s);self.reject(s)
    def test_invalid_summon_declarations(self):
        for kw in ({'query':{}},{'query':PoolQuery(kinds=(CardType.SPELL,))},{'empty':'whiteboard'},{'source_id':0}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):SummonFromPool(1,PORTAL_POOL_ID,**kw)


class ImbuePortalTests(PortalFixtures,unittest.TestCase):
    def test_skill_inserts_two_distinct_physical_portals(self):
        g=self.game(hand=(),deck=('CS2_182',));self.use(g)
        ids=[i for i in g.state.players[1].deck if g.state.entities[i].card_id==PORTAL]
        self.assertEqual(len(set(ids)),2);self.assertEqual(g.state.players[1].mana,9)
        self.assertFalse(g.state.draw_history);self.assertFalse(g.state.cast_history);self.check(g)
    def test_number_of_portals_does_not_grow_with_imbue(self):
        g=self.game(hand=('grow',),deck=());self.play(g,'grow');self.use(g)
        self.assertEqual(self.cards(g,'deck'),[PORTAL]*2);self.assertEqual(g.state.players[1].mana,9);self.check(g)
    def test_insertions_keep_order_of_existing_cards(self):
        g=self.game(hand=(),deck=('CS2_182','LOE_029','EDR_451'));before=g.state.players[1].deck;self.use(g)
        self.assertEqual([i for i in g.state.players[1].deck if i in before],before);self.check(g)
    def test_portal_insertion_hides_identity_and_position_from_both_views(self):
        g=self.game(hand=(),deck=());self.use(g)
        for p in (1,2):
            view=json.dumps(g.observe(p),ensure_ascii=False)
            self.assertNotIn(PORTAL,view)
            for e in g.player_events(p):
                if e['kind']=='card_added_to_deck':self.assertIsNone(e['target'])
        self.check(g)
    def test_portal_draw_summons_then_replaces_draw(self):
        g=self.game();portal=g.state.players[1].deck[0];self.play(g)
        self.assertEqual(self.cards(g),['BRM_004']);self.assertEqual(self.cards(g,'hand'),['CS2_182'])
        d=g.state.draw_history[0];self.assertEqual((d.outcome,d.entity_id),('cast',portal))
        c=g.state.cast_history[d.cast_id-1];self.assertEqual((c.origin,c.source_id),('draw',portal));self.check(g)
    def test_summoned_whelp_does_not_fire_battlecry(self):
        g=self.game(hand=('draw','EDR_451'));self.play(g)
        e=g.state.entities[g.state.players[1].board[0]];self.assertEqual(e.health,1);self.check(g)
    def test_growth_after_creation_changes_existing_portal_results(self):
        self.script('top',lambda c:[DrawMatching(1,PoolQuery(kinds=(CardType.SPELL,)),empty_deck='skip',selection='first')])
        g=self.game(hand=('grow','top'),deck=('CS2_182',));self.use(g);self.play(g,'grow');self.play(g,'top')
        self.assertIn('NEW1_023',self.cards(g));self.assertNotIn('BRM_004',self.cards(g));self.check(g)
    def test_progress_is_player_owned_after_skill_replacement(self):
        self.script('replace',lambda c:[Imbue(1,c.source_id,2),ReplaceHeroPower(1,'HERO_08bp'),Draw(1)])
        g=self.game(hand=('replace',));self.play(g,'replace')
        self.assertEqual(self.cards(g),['NEW1_023']);self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'HERO_08bp');self.check(g)
    def test_progress_survives_hero_class_replacement(self):
        self.script('replace',lambda c:[Imbue(1,c.source_id,2),ReplaceHero(1,'HERO_01'),Draw(1)])
        g=self.game(hand=('replace',));self.play(g,'replace');self.assertEqual(self.cards(g),['NEW1_023']);self.check(g)
    def test_draw_reaction_growth_precedes_payload_capture(self):
        self.watch(lambda c:[Imbue(1,c.source_id,2)] if self.is_portal(c) else [])
        g=self.game(board=('watch',));self.play(g);self.assertIn('NEW1_023',self.cards(g));self.check(g)
    def test_spell_start_reaction_growth_precedes_automatic_payload(self):
        self.watch(lambda c:[Imbue(1,c.source_id,2)] if c.state.entities[c.event.source_id].card_id==PORTAL else [],'spell_cast_started')
        g=self.game(board=('watch',));self.play(g);self.assertIn('NEW1_023',self.cards(g));self.check(g)
    def test_chained_portals_recompute_progress_individually(self):
        self.watch(lambda c:[Imbue(1,c.source_id,2)] if c.state.entities[c.event.source_id].card_id=='BRM_004' else [],'minion_summoned')
        g=self.game(deck=(PORTAL,PORTAL,'CS2_182'),board=('watch',));self.play(g)
        self.assertEqual(self.cards(g),['watch','BRM_004','NEW1_023']);self.assertEqual([d.outcome for d in g.state.draw_history],['cast','cast','hand']);self.check(g)
    def test_full_board_still_replaces_draw_without_random_roll(self):
        g=self.game(board=('CS2_182',)*7);rng=g._rng.getstate();self.play(g)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.cards(g,'hand'),['CS2_182']);self.assertEqual(len(self.cards(g)),7);self.check(g)
    def test_full_hand_burns_portal_without_cast_or_replacement(self):
        self.script('fill',lambda c:[AddToHand(1,'CS2_182'),Draw(1)])
        g=self.game(hand=('fill',)+('CS2_182',)*9);self.play(g,'fill')
        self.assertFalse(self.cards(g));self.assertEqual([d.outcome for d in g.state.draw_history],['burned'])
        self.assertEqual(self.cards(g,'deck'),['CS2_182']);self.check(g)
    def test_replacement_empty_deck_causes_fatigue(self):
        g=self.game(deck=(PORTAL,));self.play(g)
        self.assertEqual(self.cards(g),['BRM_004']);self.assertEqual(g.state.players[1].fatigue,1);self.check(g)
    def test_uncovered_cost_tier_keeps_replacement_draw(self):
        self.script('high',lambda c:[Imbue(1,c.source_id,4),Draw(1)])
        g=self.game(hand=('high',));self.play(g,'high')
        self.assertFalse(self.cards(g));self.assertEqual(self.cards(g,'hand'),['CS2_182']);self.check(g)
    def test_direct_skill_and_zero_growth_use_explicit_base_one(self):
        g=self.game();self.assertEqual(imbue_value(g.state,1),1);self.play(g)
        self.assertEqual(self.cards(g),['BRM_004']);self.check(g)
    def test_manual_portal_play_pays_without_replacement_draw(self):
        g=self.game(hand=(PORTAL,),deck=('CS2_182',));self.play(g,PORTAL)
        self.assertEqual(g.state.players[1].mana,9);self.assertFalse(g.state.draw_history)
        self.assertEqual(self.cards(g),['BRM_004']);self.assertEqual(self.cards(g,'deck'),['CS2_182']);self.check(g)
    def test_generated_automatic_cast_does_not_draw(self):
        self.script('auto',lambda c:[CastSpell(1,PORTAL,c.source_id)])
        g=self.game(hand=('auto',),deck=('CS2_182',));self.play(g,'auto')
        self.assertEqual(self.cards(g),['BRM_004']);self.assertFalse(g.state.draw_history);self.check(g)
    def test_moving_portal_to_hand_does_not_auto_cast(self):
        self.script('move',lambda c:[MoveCard(self.ref(c),1,Zone.HAND)])
        g=self.game(hand=('move',));self.play(g,'move');self.assertEqual(self.cards(g,'hand'),[PORTAL]);self.assertFalse(self.cards(g));self.check(g)
    def test_copied_portal_reads_recipient_progress(self):
        self.r.register_behavior('cast-copy',lambda c:[CastStoredSpell(self.ref(c,'hand',2),2,c.source_id)])
        self.script('copy',lambda c:[Imbue(2,c.source_id,2),CopyCard(self.ref(c),2),InvokeBehavior('cast-copy',c.source_id,2)])
        g=self.game(hand=('copy',));original=g.state.players[1].deck[0];self.play(g,'copy')
        self.assertEqual(self.cards(g,player=2),['NEW1_023']);self.assertFalse(self.cards(g,'hand',2))
        self.assertIn(original,g.state.players[1].deck);self.assertNotEqual(g.state.cast_history[-1].source_id,original);self.check(g)
    def test_transferred_deck_portal_uses_drawing_player_growth(self):
        self.script('transfer',lambda c:[Imbue(2,c.source_id,2),MoveCard(self.ref(c),2,Zone.DECK,'top'),Draw(2)])
        g=self.game(hand=('transfer',));original=g.state.players[1].deck[0];self.play(g,'transfer')
        self.assertEqual(self.cards(g,player=2),['NEW1_023']);self.assertEqual(g.state.entities[original].owner,1)
        self.assertEqual(g.state.cast_history[-1].player_id,2);self.check(g)
    def test_copy_current_does_not_freeze_generation_tier(self):
        self.script('copy',lambda c:[CopyCard(self.ref(c),1,Zone.DECK,position='top'),Imbue(1,c.source_id,2),Draw(1)])
        g=self.game(hand=('copy',));self.play(g,'copy');self.assertEqual(self.cards(g),['NEW1_023','NEW1_023']);self.check(g)
    def test_targeted_draw_preserves_original_portal_entity(self):
        self.script('target',lambda c:[DrawMatching(1,PoolQuery(kinds=(CardType.SPELL,)),empty_deck='skip',selection='first')])
        g=self.game(hand=('target',),deck=('CS2_182',PORTAL));eid=g.state.players[1].deck[-1];self.play(g,'target')
        self.assertEqual(g.state.draw_history[0].entity_id,eid);self.assertEqual(self.cards(g,'hand'),['CS2_182']);self.check(g)
    def test_historical_recast_recomputes_growth_without_replacement(self):
        from hs_sim.engine.spell_history import RecastSpell
        self.script('history',lambda c:[Imbue(1,c.source_id,2),RecastSpell(1,next(x.id for x in c.state.cast_history if x.card_id==PORTAL),c.source_id)])
        g=self.game(hand=('draw','history'));self.play(g);draws=len(g.state.draw_history);self.play(g,'history')
        self.assertEqual(self.cards(g),['BRM_004','NEW1_023']);self.assertEqual(len(g.state.draw_history),draws);self.check(g)
    def test_wisprider_installs_power_and_shuffles_twice(self):
        g=self.game(hand=('EDR_519',),deck=(),power=None);self.play(g,'EDR_519')
        self.assertEqual(self.cards(g,'deck'),[PORTAL]*2);self.assertEqual(g.state.hero_power_history[-1].origin,'effect')
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,0);self.check(g)
    def test_skill_replacement_between_insertions_does_not_cancel_second(self):
        self.watch(lambda c:[ReplaceHeroPower(1,'HERO_08bp')],'card_added_to_deck')
        g=self.game(hand=(),deck=(),board=('watch',));self.use(g)
        self.assertEqual(self.cards(g,'deck'),[PORTAL]*2);self.assertTrue(g.state.hero_power_history[0].completed);self.check(g)
    def test_pause_between_portal_insertions_restores_remaining_entity(self):
        self.watch(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok'),),c.source_id)],'card_added_to_deck')
        g=self.game(hand=(),deck=(),board=('watch',));self.use(g);self.assertEqual(len(g.state.players[1].deck),1);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):
            while match.state.pending_choice:self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.cards(g,'deck'),[PORTAL]*2);self.check(g)
    def test_pause_in_draw_chain_preserves_growth_and_original_card(self):
        self.watch(lambda c:[RequestChoice(1,(ChoiceOption('grow','grow',(Imbue(1,c.source_id,2),)),),c.source_id)] if self.is_portal(c) else [])
        g=self.game(board=('watch',));self.play(g);self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertIn('NEW1_023',self.cards(g));self.check(g)
    def test_failure_after_summon_rolls_back_deck_growth_rng_and_history(self):
        self.script('bad',lambda c:[Imbue(1,c.source_id,2),Draw(1),Summon(1,'missing')])
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)
    def test_lethal_summon_reaction_stops_replacement(self):
        self.watch(lambda c:[Damage(c.state.players[2].hero_id,50)],'minion_summoned')
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual(self.cards(g,'deck'),['CS2_182']);self.assertTrue(g.state.draw_history[0].interrupted);self.check(g)
    def test_portal_is_public_when_cast_but_other_deck_cards_stay_hidden(self):
        g=self.game();self.play(g)
        events=json.dumps(g.player_events(2),ensure_ascii=False)
        self.assertIn(PORTAL,events);self.assertNotIn('draw_id',events);self.assertNotIn('cast_id',events)
        own=next(p for p in g.observe(2)['players'] if p['id']==1);self.assertIsNone(own['hand'][0]['card_id']);self.check(g)
    def test_portal_summoned_goldpetal_deathrattle_grows_later_portals(self):
        self.script('three',lambda c:[Imbue(1,c.source_id,3),Draw(1)])
        self.script('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('three','kill'));self.play(g,'three');self.assertEqual(imbue_value(g.state,1),3)
        self.play(g,'kill');self.assertEqual(imbue_value(g.state,1),4);self.check(g)
    def test_whelp_manual_battlecry_checks_other_dragons_in_hand(self):
        g=self.game(hand=('BRM_004','NEW1_023'));eid=self.play(g,'BRM_004')
        self.assertEqual(g.state.entities[eid].health,3);self.check(g)
    def test_whelp_does_not_count_itself_or_board_dragon(self):
        g=self.game(hand=('BRM_004',),board=('NEW1_023',));eid=self.play(g,'BRM_004')
        self.assertEqual(g.state.entities[eid].health,1);self.check(g)
    def test_faerie_dragon_installs_elusive_ability(self):
        g=self.game(hand=('grow','draw'));self.play(g,'grow');self.play(g)
        e=g.state.entities[g.state.players[1].board[0]];self.assertIn(Keyword.ELUSIVE,e.keywords);self.check(g)
    def test_all_declared_imbue_powers_have_adapters(self):
        from hs_sim.engine.representative import IMBUE_CLASS_POWERS
        self.assertEqual({i for i in IMBUE_CLASS_POWERS.values() if i not in self.r.cards},set())
    def test_paladin_default_skill_not_silently_substituted(self):
        from hs_sim.engine import DeckSpec,DeckPolicy,validate_deck
        self.assertEqual(self.r.card('HERO_04').initial_hero_power,'HERO_04bp')
        report=validate_deck(DeckSpec('HERO_04','EDR_445p',CardClass.PALADIN,('CS2_182',)),self.r,
            DeckPolicy('test','test','experimental',('CS2_182',),deck_size=1))
        self.assertIn('hero_power',[i.code for i in report.issues])
    def test_old_snapshot64_is_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=64;self.reject(s)

    def test_rewind_restores_generated_portals_draws_and_growth(self):
        self.script('rewind',lambda c:[AddToDeck(1,PORTAL,position='top'),Imbue(1,c.source_id,2),Draw(1)],
            keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('rewind',),deck=('CS2_182',));self.play(g,'rewind');self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):
            choice=match.state.pending_choice
            match.apply(SelectChoice(1,choice.id,(next(o.id for o in choice.options if 'retry' in o.id),)))
            self.assertEqual(imbue_value(match.state,1),2)
            self.assertEqual(self.cards(match),['NEW1_023']);self.assertEqual(len(match.state.draw_history),2)
            self.assertEqual(self.cards(match,'hand'),['CS2_182']);self.assertFalse(match.state.players[1].deck)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_failed_choice_restores_pending_portal_chain(self):
        self.r.register_behavior('fail',lambda c:[Summon(1,'missing')])
        self.watch(lambda c:[RequestChoice(1,(ChoiceOption('bad','bad',(Imbue(1,c.source_id,2),
            SummonFromPool(1,PORTAL_POOL_ID,PoolQuery(min_cost=2,max_cost=2)),
            InvokeBehavior('fail',c.source_id,1))),),c.source_id)] if self.is_portal(c) else [])
        g=self.game(board=('watch',));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_portal_card_cost_does_not_set_dragon_tier(self):
        from hs_sim.engine import CostSpec
        from hs_sim.engine.effects import ModifyCost
        self.script('modify',lambda c:[ModifyCost(c.state.players[1].deck[0],CostSpec(set_to=8)),Draw(1)])
        g=self.game(hand=('modify',));self.play(g,'modify')
        self.assertEqual(self.cards(g),['BRM_004']);self.check(g)

    def test_player_port_example_restores_and_replays(self):
        from examples.imbue_portals import run
        g,s=run();self.assertEqual(s['schema_version'],265)
        self.assertEqual(sum(d.card_id==PORTAL for d in g.state.cast_history),2)


if __name__=='__main__':unittest.main()
