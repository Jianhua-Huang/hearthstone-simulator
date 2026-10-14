"""Historical candidates, recasts and sequential pool execution (R-090)."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CastFromPool,
    CastSpell, CastWhenDrawnSpec, DiscoverSpellHistory, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Rarity, RecastFromHistory, RecastSpell, ResolutionError, ResolutionLimitExceeded,
    Ruleset, Scenario, SelectChoice, SnapshotError, SpellHistoryQuery, SpellSchool, TargetSpec,
    TriggerSpec, Zone, cast_spells, spell_history_candidates)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Draw, GainArmor,
    ReplaceHero, RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.secrets import SetSecret

CONTEXT=GenerationContext('history-test','experimental')


class SpellHistoryTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('body','body',CardType.MINION,attack=2,health=5,
            metadata=self.meta()))
        self.spell('armor',lambda c:[GainArmor(c.player_id,3)],cost=2)
        self.spell('hit',lambda c:[Damage(c.target_id,2,c.source_id)],cost=1,requires_target=True,spell_school=SpellSchool.FIRE)
        self.spell('plain',lambda c:[])
    def meta(self,cls=CardClass.NEUTRAL):return CardMetadata(True,(cls,),Rarity.COMMON)
    def spell(self,name,fn,**kw):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,
            metadata=kw.pop('metadata',self.meta()),**kw))
    def game(self,hand=('armor','script'),*,board=(),enemy=(),rules=None,seed=319,context=CONTEXT):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01',hand=hand,board=board,deck=('plain',)*10,max_mana=10,mana=10),
            PlayerSetup('HERO_08',board=enemy,deck=('plain',)*10,max_mana=10,mana=10)),
            seed=seed,generation_context=context),self.r,ruleset=rules)
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def find(self,g,name,zone='hand',p=1):return next(i for i in getattr(g.state.players[p],zone) if g.state.entities[i].card_id==name)
    def play(self,g,name='script',target=None):
        eid=self.find(g,name);g.apply(PlayCard(1,eid,target));return eid
    def cards(self,g,zone='hand',p=1):return [g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def choose(self,g,index=0):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(c.options[index].id,)))
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snap)
    def reject(self,snap):
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as raised:Game.from_snapshot(snap,self.r)
        self.assertNotIn('digest mismatch',str(raised.exception))
    def script(self,fn):self.spell('script',fn)
    def choice_spell(self,name='choice'):
        self.spell(name,lambda c:[RequestChoice(c.player_id,(
            ChoiceOption('one','one',(GainArmor(c.player_id,1),)),
            ChoiceOption('four','four',(GainArmor(c.player_id,4),))),source_id=c.source_id)])
    def pool(self,ids=('armor',),*,weights=None,aliases=None):
        for card_id in ids:
            self.r.register_pool_card(PoolCard.from_definition(self.r.card(card_id),identity=(aliases or {}).get(card_id)))
        self.r.register_pool(PoolDefinition('pool','history-test-v1',CONTEXT.target_id,CONTEXT.mode,
            tuple(PoolMember(i,(weights or {}).get(i,1)) for i in ids)))
    def history_query(self,**kw):return SpellHistoryQuery(cards=PoolQuery(exclude_card_ids=('script',)),**kw)
    def history_casts(self,g):return cast_spells(g.state,1,origin='history')

    def test_recast_uses_new_base_entity_and_preserves_original_link(self):
        self.script(lambda c:[RecastSpell(1,1,c.source_id)])
        g=self.game();old=self.play(g,'armor');source=self.play(g)
        record=self.history_casts(g)[0]
        self.assertEqual(self.hero(g).armor,6);self.assertNotEqual(record.source_id,old)
        self.assertEqual((record.recast_id,record.caster_id),(1,source))
        self.assertEqual(g.state.entities[record.source_id].origin_entity_id,old)
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(len(g.state.play_history),2);self.check(g)

    def test_query_distinguishes_success_completed_and_attempted(self):
        self.script(lambda c:[SetSecret(2,'EX1_287')]);g=self.game(('script','armor'))
        self.play(g);self.play(g,'armor')
        successful=spell_history_candidates(g.state,self.r,1)
        self.assertEqual([c.card_id for c in successful],['script'])
        for outcomes in ('completed','attempts'):
            self.assertEqual(len(spell_history_candidates(g.state,self.r,1,SpellHistoryQuery(outcomes=outcomes))),2)
        self.check(g)

    def test_query_side_origins_turn_and_bound(self):
        self.script(lambda c:[CastSpell(2,'armor',c.source_id),CastSpell(1,'armor',c.source_id)])
        g=self.game(('script',));self.play(g)
        q=SpellHistoryQuery(side='enemy',origins=('effect',),min_turn=1,max_turn=1,before_id=3)
        self.assertEqual([c.id for c in spell_history_candidates(g.state,self.r,1,q)],[2])
        self.assertEqual(len(spell_history_candidates(g.state,self.r,1,SpellHistoryQuery(side='both'))),3)
        self.assertFalse(spell_history_candidates(g.state,self.r,1,replace(q,exclude_cast_ids=(2,))))
        self.check(g)

    def test_query_printed_cost_school_and_source_exclusion(self):
        self.script(lambda c:[]);g=self.game(('hit','armor','script'))
        self.play(g,'hit',self.hero(g,2).id);self.play(g,'armor');source=self.play(g)
        q=SpellHistoryQuery(cards=PoolQuery(min_cost=1,max_cost=1,spell_schools=(SpellSchool.FIRE,)))
        self.assertEqual([c.card_id for c in spell_history_candidates(g.state,self.r,1,q)],['hit'])
        q=SpellHistoryQuery(cards=PoolQuery(exclude_source=True))
        self.assertEqual(len(spell_history_candidates(g.state,self.r,1,q,source)),2)
        with self.assertRaises(ResolutionError):spell_history_candidates(g.state,self.r,1,q)

    def test_query_pending_attempt_excluded_from_success(self):
        self.choice_spell();g=self.game(('choice',));self.play(g,'choice')
        self.assertFalse(spell_history_candidates(g.state,self.r,1))
        self.assertEqual(len(spell_history_candidates(g.state,self.r,1,SpellHistoryQuery(outcomes='attempts'))),1);self.check(g)

    def test_discover_history_creates_copy_without_recasting(self):
        self.script(lambda c:[DiscoverSpellHistory(1,source_id=c.source_id)])
        g=self.game();self.play(g,'armor');self.play(g);self.check(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['armor'])
        self.choose(g);self.assertEqual(self.cards(g),['armor']);self.assertEqual(self.hero(g).armor,3)
        self.assertEqual(len(g.state.cast_history),2);self.assertEqual(g.state.hand_entries[-1].reason,'created');self.check(g)

    def test_discover_empty_history_skips_without_choice(self):
        self.script(lambda c:[DiscoverSpellHistory(1,source_id=c.source_id)])
        g=self.game(('script',));before=g.snapshot()['rng_state'];self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],before);self.check(g)

    def test_discover_card_distinctness_does_not_weight_repeated_casts(self):
        self.script(lambda c:[DiscoverSpellHistory(1,count=5,source_id=c.source_id)])
        g=self.game(('armor','armor','plain','script'));self.play(g,'armor');self.play(g,'armor');self.play(g,'plain');self.play(g)
        self.assertEqual(sorted(o.card_id for o in g.state.pending_choice.options),['armor','plain']);self.choose(g);self.check(g)

    def test_discover_occurrence_policy_can_offer_same_face(self):
        self.script(lambda c:[DiscoverSpellHistory(1,distinct='cast',source_id=c.source_id)])
        g=self.game(('armor','armor','script'));self.play(g,'armor');self.play(g,'armor');self.play(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['armor','armor']);self.check(g)

    def test_discover_generation_identity_collapses_aliases(self):
        self.spell('armor_alias',lambda c:[GainArmor(1,3)],cost=2)
        self.pool(('armor','armor_alias'),aliases={'armor':'same','armor_alias':'same'})
        self.script(lambda c:[DiscoverSpellHistory(1,distinct='identity',source_id=c.source_id)])
        g=self.game(('armor','armor_alias','script'));self.play(g,'armor');self.play(g,'armor_alias');self.play(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['armor']);self.check(g)

    def test_discovery_options_are_private_and_resolve_via_player_port(self):
        self.script(lambda c:[DiscoverSpellHistory(1,source_id=c.source_id)])
        g=self.game();self.play(g,'armor');self.play(g)
        self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1})
        port=g.for_player(1);listing=port.legal_actions();action=next(a for a in listing['actions'] if a['type']=='select_choice')
        port.submit({'revision':listing['revision'],'action':action});self.check(g)

    def test_discover_can_copy_opponent_history(self):
        self.script(lambda c:[CastSpell(2,'armor',c.source_id),DiscoverSpellHistory(1,SpellHistoryQuery(side='enemy'),source_id=c.source_id)])
        g=self.game(('script',));self.play(g);self.choose(g)
        self.assertEqual(self.cards(g),['armor']);self.assertEqual(self.hero(g,2).armor,3);self.check(g)

    def test_discovered_copy_burns_when_hand_becomes_full(self):
        self.script(lambda c:[*[AddToHand(1,'plain') for _ in range(10)],DiscoverSpellHistory(1,source_id=c.source_id)])
        g=self.game();self.play(g,'armor');self.play(g);self.choose(g)
        self.assertEqual(self.cards(g),['plain']*10);self.assertTrue(any(e.kind=='card_burned' for e in g.events));self.check(g)

    def test_recast_original_target(self):
        self.script(lambda c:[RecastSpell(1,1,c.source_id,targeting='original')])
        g=self.game(('hit','script'));target=self.hero(g,2).id;self.play(g,'hit',target);self.play(g)
        self.assertEqual(self.hero(g,2).health,26);self.assertEqual(self.history_casts(g)[0].target_id,target);self.check(g)

    def test_recast_original_dead_target_fizzles_without_retarget(self):
        self.script(lambda c:[RecastSpell(1,1,c.source_id,targeting='original')])
        g=self.game(('hit','hit','hit','script'),enemy=('body',));target=self.find(g,'body','board',2)
        for _ in range(3):self.play(g,'hit',target)
        self.play(g);self.assertEqual(self.history_casts(g)[0].failure,'invalid_target');self.assertEqual(self.hero(g,2).health,30);self.check(g)

    def test_recast_explicit_new_target(self):
        self.script(lambda c:[RecastSpell(1,1,c.source_id,c.state.players[1].hero_id,'explicit')])
        g=self.game(('hit','script'));self.play(g,'hit',self.hero(g,2).id);self.play(g)
        self.assertEqual(self.hero(g).health,28);self.assertEqual(self.hero(g,2).health,28);self.check(g)

    def test_recast_recomputes_conditions_and_choices(self):
        self.choice_spell();self.script(lambda c:[RecastSpell(1,1,c.source_id,choices='player')])
        g=self.game(('choice','script'));self.play(g,'choice');self.choose(g,1);self.play(g);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match,0)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g).armor,5);self.check(g)

    def test_random_recast_choice_does_not_suspend(self):
        self.choice_spell();self.script(lambda c:[RecastSpell(1,1,c.source_id)])
        g=self.game(('choice','script'));self.play(g,'choice');self.choose(g);self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertIn(self.hero(g).armor,(2,5));self.check(g)

    def test_history_batch_freezes_records_before_new_casts(self):
        self.script(lambda c:[RecastFromHistory(1,source_id=c.source_id)])
        g=self.game(('armor','plain','script'));self.play(g,'armor');self.play(g,'plain');self.play(g)
        self.assertEqual([c.recast_id for c in self.history_casts(g)],[1,2]);self.assertEqual(self.hero(g).armor,6);self.check(g)

    def test_history_batch_newest_order(self):
        self.script(lambda c:[RecastFromHistory(1,selection='newest',source_id=c.source_id)])
        g=self.game(('armor','plain','script'));self.play(g,'armor');self.play(g,'plain');self.play(g)
        self.assertEqual([c.recast_id for c in self.history_casts(g)],[2,1]);self.check(g)

    def test_history_batch_distinct_card_removes_all_occurrences(self):
        self.script(lambda c:[RecastFromHistory(1,distinct='card',source_id=c.source_id)])
        g=self.game(('armor','armor','plain','script'));self.play(g,'armor');self.play(g,'armor');self.play(g,'plain');self.play(g)
        self.assertEqual([c.recast_id for c in self.history_casts(g)],[1,3]);self.assertEqual(self.hero(g).armor,9);self.check(g)

    def test_history_random_batch_is_deterministic_with_replacement(self):
        self.script(lambda c:[RecastFromHistory(1,count=5,selection='random',replacement=True,source_id=c.source_id)])
        g=self.game();self.play(g,'armor');self.play(g)
        self.assertEqual([c.recast_id for c in self.history_casts(g)],[1]*5);self.assertEqual(self.hero(g).armor,18);self.check(g)

    def test_history_no_replacement_stops_at_candidate_exhaustion(self):
        self.script(lambda c:[RecastFromHistory(1,count=5,source_id=c.source_id)])
        g=self.game();self.play(g,'armor');self.play(g);self.assertEqual(len(self.history_casts(g)),1);self.check(g)

    def test_history_multiple_choices_preserve_frozen_batch(self):
        self.choice_spell();self.script(lambda c:[RecastFromHistory(1,count=2,replacement=True,choices='player',source_id=c.source_id)])
        g=self.game(('choice','script'));self.play(g,'choice');self.choose(g);self.play(g);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match);self.choose(match,1)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g).armor,6);self.check(g)

    def test_history_can_recast_failed_attempt_when_explicitly_requested(self):
        self.spell('targeted',lambda c:[],targeting=TargetSpec(kinds=(CardType.MINION,)))
        self.script(lambda c:[CastSpell(1,'targeted',c.source_id),Summon(1,'body'),
            RecastFromHistory(1,SpellHistoryQuery(origins=('effect',),outcomes='attempts'),source_id=c.source_id)])
        g=self.game(('script',));self.play(g)
        self.assertEqual(g.state.cast_history[1].failure,'no_target');self.assertIsNone(self.history_casts(g)[0].failure);self.check(g)

    def test_enemy_history_recast_uses_current_player_and_new_owner(self):
        self.script(lambda c:[CastSpell(2,'armor',c.source_id),RecastFromHistory(1,SpellHistoryQuery(side='enemy'),source_id=c.source_id)])
        g=self.game(('script',));self.play(g);row=self.history_casts(g)[0]
        self.assertEqual(self.hero(g).armor,3);self.assertEqual(g.state.entities[row.source_id].owner,1);self.check(g)

    def test_history_of_history_links_immediate_original(self):
        self.script(lambda c:[RecastSpell(1,1,c.source_id),RecastFromHistory(1,SpellHistoryQuery(origins=('history',)),source_id=c.source_id)])
        g=self.game();self.play(g,'armor');self.play(g)
        self.assertEqual([c.recast_id for c in self.history_casts(g)],[1,3]);self.assertEqual(self.hero(g).armor,9);self.check(g)

    def test_history_budget_rejects_before_mutation(self):
        self.script(lambda c:[RecastFromHistory(1,count=1001,replacement=True,source_id=c.source_id)])
        g=self.game();self.play(g,'armor');before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_pool_batch_casts_without_hand_or_payment(self):
        self.pool();self.script(lambda c:[CastFromPool(1,'pool',count=3,source_id=c.source_id)])
        g=self.game(('script',));self.play(g)
        self.assertEqual(self.hero(g).armor,9);self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.cast_history),4);self.assertFalse(self.cards(g));self.check(g)

    def test_pool_batch_implicitly_filters_spells(self):
        self.pool(('armor','body'));self.script(lambda c:[CastFromPool(1,'pool',count=3,source_id=c.source_id)])
        g=self.game(('script',));self.play(g);self.assertEqual(self.hero(g).armor,9);self.assertFalse(g.state.players[1].board);self.check(g)

    def test_pool_no_replacement_removes_generation_identity(self):
        self.spell('alias',lambda c:[GainArmor(1,3)],cost=2)
        self.pool(('armor','alias'),aliases={'armor':'same','alias':'same'})
        self.script(lambda c:[CastFromPool(1,'pool',count=5,replacement=False,source_id=c.source_id)])
        g=self.game(('script',));self.play(g);self.assertEqual(self.hero(g).armor,3);self.assertEqual(len(g.state.cast_history),2);self.check(g)

    def test_pool_batch_choice_resume_and_replay(self):
        self.choice_spell();self.pool(('choice',))
        self.script(lambda c:[CastFromPool(1,'pool',count=2,choices='player',refresh='frozen',source_id=c.source_id)])
        g=self.game(('script',));self.play(g);self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match);self.choose(match,1)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g).armor,5);self.check(g)

    def test_pool_missing_eligible_definition_is_not_filtered(self):
        self.r.register_pool_card(PoolCard('missing',CardType.SPELL,0,self.meta()))
        self.r.register_pool(PoolDefinition('pool','v1',CONTEXT.target_id,CONTEXT.mode,(PoolMember('missing'),)))
        self.script(lambda c:[CastFromPool(1,'pool',source_id=c.source_id)])
        g=self.game(('script',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_pool_missing_context_is_explicit_error(self):
        self.pool();self.script(lambda c:[CastFromPool(1,'pool',source_id=c.source_id)])
        g=self.game(('script',),context=None);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_empty_filtered_pool_has_no_cast_or_rng(self):
        self.pool();self.script(lambda c:[CastFromPool(1,'pool',query=PoolQuery(min_cost=8),source_id=c.source_id)])
        g=self.game(('script',));rng=g.snapshot()['rng_state'];self.play(g)
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g)

    def test_zero_pool_count_does_not_sample(self):
        self.pool();self.script(lambda c:[CastFromPool(1,'pool',count=0,source_id=c.source_id)])
        g=self.game(('script',));rng=g.snapshot()['rng_state'];self.play(g);self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g)

    def test_zero_history_count_does_not_sample(self):
        self.script(lambda c:[RecastFromHistory(1,count=0,source_id=c.source_id)])
        g=self.game();self.play(g,'armor');rng=g.snapshot()['rng_state'];self.play(g)
        self.assertFalse(self.history_casts(g));self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g)

    def test_pool_counts_failures_and_continues(self):
        self.spell('targeted',lambda c:[],targeting=TargetSpec(kinds=(CardType.MINION,)))
        self.pool(('targeted',));self.script(lambda c:[CastFromPool(1,'pool',count=3,source_id=c.source_id)])
        g=self.game(('script',));self.play(g)
        self.assertEqual([c.failure for c in g.state.cast_history[1:]],['no_target']*3);self.check(g)

    def test_lethal_pool_cast_stops_remaining_batch(self):
        self.spell('lethal',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id)])
        self.pool(('lethal',));self.script(lambda c:[CastFromPool(1,'pool',count=3,source_id=c.source_id)])
        g=self.game(('script',));self.play(g);self.assertEqual(len(g.state.cast_history),2)
        self.assertTrue(g.state.cast_history[-1].interrupted);self.check(g)

    def test_pool_error_restores_rng_and_state(self):
        def fail(c):raise RuntimeError('payload failed')
        self.spell('fail',fail);self.pool(('fail',));self.script(lambda c:[CastFromPool(1,'pool',count=2,source_id=c.source_id)])
        g=self.game(('script',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_pool_huge_count_rejected(self):
        self.pool();self.script(lambda c:[CastFromPool(1,'pool',count=1001,source_id=c.source_id)])
        g=self.game(('script',));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_pool_refresh_observes_changed_hero_class(self):
        self.spell('become_mage',lambda c:[ReplaceHero(1,'HERO_08')],metadata=self.meta(CardClass.WARRIOR))
        self.spell('mage_armor',lambda c:[GainArmor(1,7)],metadata=self.meta(CardClass.MAGE))
        self.pool(('become_mage','mage_armor'))
        self.script(lambda c:[CastFromPool(1,'pool',query=PoolQuery(class_mode='current',include_neutral=False),count=2,source_id=c.source_id)])
        g=self.game(('script',));self.play(g)
        self.assertEqual([c.card_id for c in g.state.cast_history[1:]],['become_mage','mage_armor'])
        self.assertEqual(self.hero(g).armor,7);self.check(g)

    def test_frozen_pool_retains_initial_class_candidates(self):
        self.spell('become_mage',lambda c:[ReplaceHero(1,'HERO_08')],metadata=self.meta(CardClass.WARRIOR))
        self.spell('mage_armor',lambda c:[GainArmor(1,7)],metadata=self.meta(CardClass.MAGE))
        self.pool(('become_mage','mage_armor'))
        self.script(lambda c:[CastFromPool(1,'pool',query=PoolQuery(class_mode='current',include_neutral=False),count=2,refresh='frozen',source_id=c.source_id)])
        g=self.game(('script',));self.play(g)
        self.assertEqual([c.card_id for c in g.state.cast_history[1:]],['become_mage']*2);self.check(g)

    def test_pool_default_survives_caster_departure(self):
        self.spell('destroy_caster',lambda c:[Destroy(c.cast.caster_id)])
        self.pool(('destroy_caster',));self.script(lambda c:[CastFromPool(1,'pool',count=2,source_id=c.state.players[1].board[0])])
        g=self.game(('script',),board=('body',));self.play(g)
        self.assertEqual(len(g.state.cast_history),3);self.assertFalse(g.state.players[1].board);self.check(g)

    def test_pool_explicit_source_liveness_stops_batch(self):
        self.spell('destroy_caster',lambda c:[Destroy(c.cast.caster_id)])
        self.pool(('destroy_caster',));self.script(lambda c:[CastFromPool(1,'pool',count=2,source_id=c.state.players[1].board[0],while_source_in_play=True)])
        g=self.game(('script',),board=('body',));self.play(g)
        self.assertEqual(len(g.state.cast_history),2);self.check(g)

    def test_history_cast_link_cannot_point_to_itself(self):
        self.script(lambda c:[RecastSpell(1,1,c.source_id)]);g=self.game();self.play(g,'armor');self.play(g)
        snap=g.snapshot();row=snap['state']['cast_history'][-1];row['recast_id']=row['id'];self.reject(snap)

    def test_history_cast_original_card_must_match(self):
        self.script(lambda c:[RecastSpell(1,1,c.source_id)]);g=self.game();self.play(g,'armor');self.play(g)
        snap=g.snapshot();snap['state']['cast_history'][-1]['recast_id']=2;self.reject(snap)

    def test_nonhistorical_origin_cannot_keep_recast_link(self):
        self.script(lambda c:[RecastSpell(1,1,c.source_id)]);g=self.game();self.play(g,'armor');self.play(g)
        snap=g.snapshot();snap['state']['cast_history'][-1]['origin']='effect';self.reject(snap)

    def test_history_unknown_record_rolls_back(self):
        self.script(lambda c:[RecastSpell(1,999,c.source_id)]);g=self.game(('script',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_strict_declarations(self):
        bad=(lambda:SpellHistoryQuery(side='owner'),lambda:SpellHistoryQuery(origins=('bad',)),
            lambda:SpellHistoryQuery(outcomes='all'),lambda:SpellHistoryQuery(min_turn=2,max_turn=1),
            lambda:SpellHistoryQuery(exclude_cast_ids=(1,1)),lambda:SpellHistoryQuery(cards=PoolQuery(kinds=(CardType.MINION,))),
            lambda:RecastSpell(1,True),lambda:RecastSpell(1,1,targeting='original',target_id=3),
            lambda:RecastFromHistory(1,count=-1),lambda:RecastFromHistory(1,distinct='whatever'),
            lambda:DiscoverSpellHistory(1,count=0),lambda:CastFromPool(1,'pool',while_source_in_play=True),
            lambda:CastFromPool(1,'pool',refresh='unknown'),lambda:CastFromPool(1,'pool',replacement=1))
        for fn in bad:
            with self.assertRaises(ValueError):fn()

    def test_recast_recomputes_combo_in_current_context(self):
        self.spell('combo',lambda c:[GainArmor(1,5 if c.spell_conditions.combo else 1)])
        self.script(lambda c:[RecastSpell(1,1,c.source_id)])
        g=self.game(('combo','script'));self.play(g,'combo');self.play(g)
        self.assertFalse(g.state.cast_history[0].combo);self.assertTrue(self.history_casts(g)[0].combo)
        self.assertEqual(self.hero(g).armor,6);self.check(g)

    def test_nested_history_payload_does_not_expand_outer_candidates(self):
        self.spell('nested',lambda c:[CastSpell(1,'armor',c.source_id)] if c.cast.origin=='history' else [])
        self.script(lambda c:[RecastFromHistory(1,source_id=c.source_id)])
        g=self.game(('nested','plain','script'));self.play(g,'nested');self.play(g,'plain');self.play(g)
        self.assertEqual([c.recast_id for c in self.history_casts(g)],[1,2])
        self.assertEqual(self.hero(g).armor,3);self.assertEqual(len(g.state.cast_history),6);self.check(g)

    def test_history_lethal_payload_stops_remaining_records(self):
        self.spell('later_lethal',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id)] if c.cast.origin=='history' else [])
        self.script(lambda c:[RecastFromHistory(1,source_id=c.source_id)])
        g=self.game(('later_lethal','armor','script'));self.play(g,'later_lethal');self.play(g,'armor');self.play(g)
        self.assertEqual([c.recast_id for c in self.history_casts(g)],[1]);self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_history_without_source_is_valid(self):
        self.script(lambda c:[RecastFromHistory(1)]);g=self.game();self.play(g,'armor');self.play(g)
        self.assertIsNone(self.history_casts(g)[0].caster_id);self.check(g)

    def test_discovery_inside_automatic_spell_uses_automatic_choice(self):
        self.spell('discover',lambda c:[DiscoverSpellHistory(c.player_id,source_id=c.source_id)])
        self.script(lambda c:[CastSpell(1,'discover',c.source_id)])
        g=self.game();self.play(g,'armor');self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.cards(g),['armor']);self.check(g)

    def test_history_discovery_excludes_all_copies_of_source_definition(self):
        self.spell('discover',lambda c:[DiscoverSpellHistory(1,SpellHistoryQuery(cards=PoolQuery(exclude_source=True)),source_id=c.source_id)])
        g=self.game(('discover','armor','discover'));self.play(g,'discover');self.play(g,'armor');self.play(g,'discover')
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['armor']);self.choose(g);self.check(g)

    def test_recast_draw_keyword_does_not_trigger_replacement(self):
        self.spell('draw_spell',lambda c:[GainArmor(1,1)],keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        self.script(lambda c:[RecastSpell(1,1,c.source_id)])
        g=self.game(('draw_spell','script'));self.play(g,'draw_spell');self.play(g)
        self.assertFalse(g.state.draw_history);self.assertEqual(len(g.state.players[1].deck),10);self.check(g)

    def test_pool_draw_keyword_does_not_trigger_replacement(self):
        self.spell('draw_spell',lambda c:[GainArmor(1,1)],keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        self.pool(('draw_spell',));self.script(lambda c:[CastFromPool(1,'pool',count=2,source_id=c.source_id)])
        g=self.game(('script',));self.play(g);self.assertFalse(g.state.draw_history);self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_recast_echo_isolation_and_twinspell_derivative(self):
        from hs_sim.engine import HandRepeatSpec, HandDerivativeSpec
        self.spell('echo',lambda c:[],keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec())
        self.spell('twin',lambda c:[],keywords=(Keyword.TWINSPELL,),hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL,'plain'),))
        self.script(lambda c:[RecastFromHistory(1,source_id=c.source_id)])
        g=self.game(('echo','twin','script'));self.play(g,'echo');self.play(g,'twin');self.play(g)
        self.assertEqual(self.cards(g).count('echo'),1);self.assertEqual(self.cards(g).count('plain'),2);self.check(g)

    def test_bad_candidate_not_sampled_is_still_rejected(self):
        self.r.register_pool_card(PoolCard.from_definition(self.r.card('armor')))
        self.r.register_pool_card(PoolCard('missing',CardType.SPELL,0,self.meta()))
        self.r.register_pool(PoolDefinition('pool','v1',CONTEXT.target_id,CONTEXT.mode,(PoolMember('armor',100000),PoolMember('missing'))))
        self.script(lambda c:[CastFromPool(1,'pool',source_id=c.source_id)])
        g=self.game(('script',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_missing_ineligible_minion_does_not_block_spell_pool(self):
        self.r.register_pool_card(PoolCard.from_definition(self.r.card('armor')))
        self.r.register_pool_card(PoolCard('missing_minion',CardType.MINION,0,self.meta()))
        self.r.register_pool(PoolDefinition('pool','v1',CONTEXT.target_id,CONTEXT.mode,(PoolMember('armor'),PoolMember('missing_minion'))))
        self.script(lambda c:[CastFromPool(1,'pool',source_id=c.source_id)])
        g=self.game(('script',));self.play(g);self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_history_recursion_hits_budget_and_rolls_back(self):
        self.spell('recursive',lambda c:[RecastSpell(1,c.cast.id,c.source_id)])
        g=self.game(('recursive',),rules=Ruleset(max_resolution_steps=70));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,'recursive')
        self.assertEqual(g.snapshot(),before)

    def test_pool_choice_resumes_through_public_player_actions(self):
        self.choice_spell();self.pool(('choice',));self.script(lambda c:[CastFromPool(1,'pool',count=2,choices='player',source_id=c.source_id)])
        g=self.game(('script',));port=g.for_player(1);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='play_card');reply=port.submit({'revision':listing['revision'],'action':action})
        self.assertTrue(reply['accepted']);self.check(g)
        for _ in range(2):
            listing=port.legal_actions();action=next(a for a in listing['actions'] if a['type']=='select_choice')
            self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertIsNone(g.state.pending_choice);self.check(g)

    def pending_sequence(self,kind):
        self.choice_spell()
        if kind=='pool':
            self.pool(('choice',));self.script(lambda c:[CastFromPool(1,'pool',count=2,choices='player',refresh='frozen',source_id=c.source_id)])
            g=self.game(('script',));self.play(g);label='ContinuePoolCasts'
        else:
            self.script(lambda c:[RecastFromHistory(1,count=2,replacement=True,choices='player',source_id=c.source_id)])
            g=self.game(('choice','script'));self.play(g,'choice');self.choose(g);self.play(g);label='ContinueHistoryCasts'
        snap=g.snapshot();queue=snap['resolution_frame']['fields']['continuation']['tuple']
        work=next(w['fields'] for w in queue if w.get('type','').endswith(label))
        return snap,work

    def test_frozen_history_candidate_cannot_cross_cutoff(self):
        snap,work=self.pending_sequence('history');work['cast_ids']['tuple']=[len(snap['state']['cast_history'])];self.reject(snap)

    def test_frozen_history_boundary_cannot_be_in_future(self):
        snap,work=self.pending_sequence('history');work['before_id']=999;self.reject(snap)

    def test_frozen_pool_cannot_delete_eligible_candidate(self):
        snap,work=self.pending_sequence('pool');work['candidates']['tuple']=[];self.reject(snap)

    def test_frozen_pool_weight_must_match_inventory(self):
        snap,work=self.pending_sequence('pool');work['candidates']['tuple'][0]['fields']['weight']=99;self.reject(snap)

    def test_pool_batch_remaining_count_cannot_grow(self):
        snap,work=self.pending_sequence('pool');work['remaining']=999;self.reject(snap)


if __name__=='__main__':unittest.main()
