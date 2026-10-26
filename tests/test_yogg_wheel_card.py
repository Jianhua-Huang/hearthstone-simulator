"""All six real wheel entries and the minimum ordinary-effect extensions."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.yogg_wheel_card import CARD,OUTCOMES,PYRO,load_batch,register_yogg_wheel_card
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,PlayerSetup,ResolutionError,
    ResolutionLimitExceeded,Ruleset,Scenario,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.destruction_resources import DestroyMinionsForStats
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,Draw,GainArmor,GrantKeyword,
    InvokeBehavior,RequestChoice,ReturnToHand,Transform)
from hs_sim.engine.model import BoardPresenceReference,CardClass,CardMetadata,CostSpec,Rarity
from hs_sim.engine.pools import FillHandFromPool,GenerateFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.random_control import TakeRandomEnemyMinions
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_history import personal_hand_spell_count
from hs_sim.engine.terminal_spell_loops import CastSpellUntilHeroDies
from tools import card_batch as batch

S='k566.'
GROW,ARMOR,ALLY,ENEMY,TOKEN,DORMANT,IMMUNE,HELP_HUNGER,HELP_HURT,HELP_LOOP,HELP_CONTROL=(S+x for x in
 ('grow','armor','ally','enemy','token','dormant','immune','hunger','hurt','loop','control'))
CTX=GenerationContext('k566-all-six-native-wheel-outcomes','experimental')
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)
WEIGHTS=(19,19,19,19,19,5)
MODES=('spin_wait','death_wait','loop_wait','kill_source','control_wait')


def seed_for(index):
    return next(seed for seed in range(1000)if Random(seed).choices(range(6),weights=WEIGHTS,k=1)[0]==index)


def wheel_source(c):
    return next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    if mode not in('normal','frontier','unbound'):return fixture('normal',role)
    if mode=='frontier':
        from test_nefarian_native_dependencies import fixture as base_fixture
        r=base_fixture.__wrapped__('normal',role).registry
    else:
        r=build_registry();register_yogg_wheel_card(r)
    def fail(c):raise ResolutionError('k566 deliberate resume failure')
    r.register_behavior(S+'fail',fail)
    r.register_behavior(GROW,lambda c:(Draw(c.player_id,1,c.source_id),))
    r.register_behavior(ARMOR,lambda c:(GainArmor(c.player_id,3),))
    for cid,cost in ((GROW,0),(ARMOR,4)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,metadata=META))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid,attack,health,kw,dormant in ((ALLY,2,3,(),0),(ENEMY,3,4,(),0),
            (TOKEN,1,2,(),0),(DORMANT,5,5,(),2),(IMMUNE,1,3,(Keyword.IMMUNE,),0)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,keywords=kw,
            dormant_turns=dormant,metadata=META))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(HELP_HUNGER,lambda c:(DestroyMinionsForStats(c.player_id,wheel_source(c).id,
        BoardPresenceReference.capture(c.state,wheel_source(c).id)),))
    r.register_behavior(HELP_HURT,lambda c:(Damage(c.target_id,2,c.source_id),))
    r.register_behavior(HELP_LOOP,lambda c:(CastSpellUntilHeroDies(c.player_id,PYRO,wheel_source(c).id),))
    r.register_behavior(HELP_CONTROL,lambda c:(TakeRandomEnemyMinions(c.player_id,c.source_id),))
    for cid in (HELP_HUNGER,HELP_HURT,HELP_LOOP,HELP_CONTROL):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=cid==HELP_HURT))
    r.register_card(CardDefinition(S+'immune_hero','Immune loop diagnostic',CardType.HERO,health=30,keywords=(Keyword.IMMUNE,)))
    for observer_mode in MODES:
        def observe(c,observer_mode=observer_mode):
            event=c.event;source=None
            if observer_mode=='spin_wait':
                if event.kind!='random_choice' or dict(event.data).get('producer')!='effect_branch':return()
                source=c.state.entities[event.source_id]
                if source.card_id!=CARD:return()
            elif observer_mode in ('loop_wait','kill_source'):
                if event.kind!='spell_cast_started':return()
                row=next(r for r in c.state.cast_history if r.id==dict(event.data)['cast_id'])
                if row.card_id!=PYRO or row.caster_id is None:return()
                source=c.state.entities[row.caster_id]
                if sum(r.card_id==PYRO for r in c.state.cast_history)!=1:return()
                if observer_mode=='kill_source':return(Destroy(source.id,c.source_id),)
            elif observer_mode=='death_wait':
                if event.kind!='minion_died':return()
                matched=[d for d in c.state.death_history if d.cause.kind=='destroy' and
                    c.state.entities[d.cause.source_id].card_id==CARD]
                if not matched or event.target_id!=matched[0].entity_id:return()
                source=c.state.entities[matched[0].cause.source_id]
            else:
                if event.kind!='control_changed':return()
                owned=[i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==ENEMY]
                if len(owned)!=1:return()
                source=c.state.entities[event.target_id]
            more=()
            if observer_mode=='control_wait':
                changes=tuple(Transform(i,TOKEN)for i in c.state.players[3-c.player_id].board)
                more=(ChoiceOption('change','Change remaining original enemies',changes),)
            elif observer_mode in ('death_wait','spin_wait'):
                more=(ChoiceOption('bounce','Return original source',(ReturnToHand(source.id),)),)
            return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),)),*more),c.source_id),)
        behavior=S+'watch.'+observer_mode;r.register_behavior(behavior,observe)
        events=('random_choice',)if observer_mode=='spin_wait'else('minion_died',)if observer_mode=='death_wait'else(
            'control_changed',)if observer_mode=='control_wait'else('spell_cast_started',)
        r.register_card(CardDefinition(behavior,behavior,CardType.WEAPON,durability=10,
            triggers=tuple(TriggerSpec(event,behavior)for event in events)))
    if mode!='unbound':
        r.register_pool(PoolDefinition('constructed.cards','wheel-complete-diagnostic-v1',CTX.target_id,CTX.mode,
            (PoolMember(ARMOR),PoolMember(TOKEN)),complete=True))
    if mode=='frontier':
        r.register_pool(PoolDefinition('constructed.past.cards','wheel-native-only-diagnostic-v1',CTX.target_id,CTX.mode,
            (PoolMember(CARD),),complete=True))
    r.validate();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
    return saved


class YoggWheelCardTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(fixture)

    def game(self,index=0,*,board=(),enemy=(),mode='normal',player=1,hand=(GROW,CARD),rules=None,immune_heroes=False):
        self.mode=mode;seed=seed_for(index)
        own=PlayerSetup(S+'immune_hero'if immune_heroes else'HERO_08',hand=hand,board=board,deck=(GROW,)*12,
            mana=60,max_mana=60,mana_cap=60,weapon_card_id=S+'watch.'+mode if mode in MODES else None)
        other=PlayerSetup(S+'immune_hero'if immune_heroes else'HERO_01',board=enemy,deck=(TOKEN,)*8,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if player==1 else(other,own),active_player=player,
            seed=seed,generation_context=CTX),fixture('frontier'if mode=='frontier'else'unbound'if mode=='unbound'else'normal'),ruleset=rules)

    def prepare(self,g,count=10,player=1):
        for _ in range(count):self.play(g,GROW,player=player)

    def spins(self,g):return[e for e in g.events if e.kind=='random_choice' and dict(e.data).get('producer')=='effect_branch']

    def test_complete_ten_original_rows_primary_threshold_forms_and_six_nonphysical_labels(self):
        data=load_batch();raw={x['id']:x for x in batch.read(data['source'])}
        for row in data['cards']+data['choice_only']+data['existing_dependencies']+data['evidence_only']:
            self.assertEqual(row['record'],raw[row['record']['id']])
        for face in data['official_faces']:
            batch.check_face(raw[CARD],face['face'],face['locale'],data['display_normalizations'][CARD])
        r=fixture();self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(10,7,5))
        self.assertTrue(all(r.card(cid).choice_only and not r.card(cid).hand_playable for cid in OUTCOMES))
        self.assertTrue(all(cid not in r.pool_cards for cid in OUTCOMES))
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_nine_then_ten_real_personal_roots_gate_actual_spinning_without_early_rng(self):
        g=self.game(index=1,hand=(GROW,CARD,CARD));self.prepare(g,9);rng=g._rng.getstate();self.play(g,CARD)
        self.assertFalse(self.spins(g));self.assertEqual(g._rng.getstate(),rng)
        self.play(g,GROW);self.play(g,CARD);self.assertEqual(len(self.spins(g)),1)
        self.assertEqual(tuple(dict(self.spins(g)[0].data)['weights']),WEIGHTS)
        self.assertEqual(dict(self.spins(g)[0].data)['selected'],OUTCOMES[1])

    def test_native_mysterybox_uses_actual_original_count_and_normal_free_automatic_spells(self):
        g=self.game(0);self.prepare(g);source=self.play(g,CARD)
        rows=[r for r in g.state.cast_history if r.origin=='effect' and r.caster_id==source]
        self.assertEqual(dict(self.spins(g)[0].data)['selected'],OUTCOMES[0]);self.assertEqual(len(rows),10)
        self.assertTrue(all(r.card_id==ARMOR and r.completed for r in rows))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,30)
        self.assertEqual((g.state.players[1].mana,len(g.state.play_history)),(50,11));self.portable(g)

    def test_native_hand_of_fate_fills_actual_capacity_and_zero_cost_expires_this_turn(self):
        g=self.game(1);self.prepare(g);self.play(g,CARD)
        cards=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==ARMOR]
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(cards),9)
        self.assertTrue(all(quote_unselected_cost(g.state,g.registry,e).amount==0 for e in cards))
        self.portable(g);g.apply(EndTurn(1))
        self.assertTrue(all(quote_unselected_cost(g.state,g.registry,g.state.entities[e.id]).amount==4 for e in cards))

    def test_native_curse_fills_both_real_boards_then_grants_only_live_friendly_rush(self):
        g=self.game(2,board=(ALLY,DORMANT),enemy=(ENEMY,));self.prepare(g);source=self.play(g,CARD)
        self.assertEqual([len(g.state.players[p].board)for p in(1,2)],[7,7])
        for p in(1,2):
            for eid in g.state.players[p].board:
                e=g.state.entities[eid]
                self.assertEqual(Keyword.RUSH in e.keywords,p==1 and e.active)
        self.assertIn(Keyword.RUSH,g.state.entities[source].keywords)
        roots=g.state.pool_summon_history;self.assertEqual([r.spec.basis.player_id for r in roots],[1,2])
        self.assertTrue(all(r.spec.cause.player_id==1 for r in roots));self.portable(g)

    def test_native_goggles_samples_original_distinct_enemy_entities_then_transfers_them(self):
        g=self.game(3,board=(ALLY,),enemy=(ENEMY,)*4);original=set(g.state.players[2].board)
        self.prepare(g);self.play(g,CARD)
        selected=next(e for e in g.events if e.kind=='random_choice' and dict(e.data).get('producer')=='enemy_control')
        ids=tuple(dict(selected.data)['selected']);self.assertEqual(len(set(ids)),3)
        self.assertTrue(set(ids)<original);self.assertTrue(all(g.state.entities[i].controller==1 for i in ids))
        self.assertEqual(len(g.state.players[2].board),1);self.portable(g)

    def test_native_hunger_joins_actual_deaths_to_the_original_surviving_source(self):
        g=self.game(4,board=(ALLY,),enemy=(ENEMY,));self.prepare(g);source=self.play(g,CARD)
        self.assertEqual(g.state.players[1].board,[source]);self.assertFalse(g.state.players[2].board)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(12,12))
        self.assertEqual(len(g.state.death_history),2);self.portable(g)

    def test_native_rod_uses_real_pyroblast_until_a_hero_dies_even_after_source_dies(self):
        g=self.game(5,mode='kill_source');self.prepare(g);source=self.play(g,CARD)
        rows=[r for r in g.state.cast_history if r.card_id==PYRO]
        self.assertEqual((g.state.status,g.state.entities[source].zone),('finished',Zone.GRAVEYARD))
        self.assertGreaterEqual(len(rows),2);self.assertTrue(all(r.origin=='effect' and r.caster_id==source for r in rows))
        self.assertEqual(g.state.players[1].mana,50);self.portable(g)

    def test_selected_wheel_branch_survives_wait_restore_without_a_second_draw(self):
        g=self.game(1,mode='spin_wait');self.prepare(g);self.play(g,CARD);rng=g._rng.getstate()
        self.assertEqual(len(self.spins(g)),1);self.assertIsNotNone(g.state.pending_choice)
        restored=self.portable(g);saved=restored.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate resume failure'):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        for game in(g,restored):self.choose(game)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(len(self.spins(g)),1)
        self.assertNotEqual(g._rng.getstate(),rng);self.portable(g)

    def test_hunger_wait_restore_and_original_source_bounce_skip_stale_buff(self):
        g=self.game(4,board=(ALLY,),enemy=(ENEMY,),mode='death_wait');self.prepare(g);source=self.play(g,CARD)
        self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        saved=restored.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate resume failure'):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        self.choose(restored,'bounce');self.assertEqual(restored.state.entities[source].zone,Zone.HAND)
        self.assertEqual((restored.state.entities[source].attack,restored.state.entities[source].health),(7,5))
        self.choose(g);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(12,12))
        self.portable(restored);self.portable(g)

    def test_terminal_loop_wait_restores_same_next_cast_and_bad_resume_is_atomic(self):
        g=self.game(5,mode='loop_wait');self.prepare(g);self.play(g,CARD);self.assertIsNotNone(g.state.pending_choice)
        restored=self.portable(g);saved=restored.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate resume failure'):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        for game in(g,restored):self.choose(game)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.status,'finished');self.portable(g)

    def test_control_group_wait_keeps_original_references_and_does_not_replace_stale_targets(self):
        g=self.game(3,enemy=(ENEMY,)*4,mode='control_wait');self.prepare(g);self.play(g,CARD)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        self.choose(g,'change')
        self.assertEqual(sum(g.state.entities[i].card_id==ENEMY for i in g.state.players[1].board),1)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board],[TOKEN]*3);self.portable(g)

    def test_new_stat_reward_uses_damaged_remaining_health_and_excludes_dormant_body(self):
        g=self.game(board=(CARD,ALLY),enemy=(ENEMY,DORMANT),hand=(HELP_HURT,HELP_HUNGER))
        source=self.entity(g,CARD,zone='board').id;ally=self.entity(g,ALLY,zone='board').id
        self.play(g,HELP_HURT,ally);self.play(g,HELP_HUNGER)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(12,10))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board],[DORMANT]);self.portable(g)

    def test_nonterminating_immune_rod_hits_engine_budget_and_rolls_back_instead_of_winning(self):
        g=self.game(board=(CARD,),hand=(HELP_LOOP,),immune_heroes=True,rules=Ruleset(max_resolution_steps=50))
        saved=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,HELP_LOOP)
        self.assertEqual(g.snapshot(),saved)

    def test_random_control_ignores_dormant_but_keeps_nontargeted_immune_minion(self):
        g=self.game(enemy=(ENEMY,IMMUNE,DORMANT),hand=(HELP_CONTROL,));self.play(g,HELP_CONTROL)
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].board},{ENEMY,IMMUNE})
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board],[DORMANT])

    def test_original_repeated_battlecry_has_two_independent_wheel_draws_after_source_modifier_dies(self):
        g=self.game(4,board=('LOE_077',));self.prepare(g);source=self.play(g,CARD)
        self.assertEqual(len(self.spins(g)),2);self.assertEqual(personal_hand_spell_count(g.state,g.registry,1),10)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.portable(g)

    def test_second_seat_keeps_own_threshold_fill_and_original_caster(self):
        g=self.game(0,player=2);self.prepare(g,player=2);source=self.play(g,CARD,player=2)
        rows=[r for r in g.state.cast_history if r.origin=='effect' and r.caster_id==source]
        self.assertEqual(len(rows),10);self.assertTrue(all(r.player_id==2 for r in rows))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,30)

    def test_missing_selected_domain_fails_whole_play_without_removing_that_wheel_outcome(self):
        g=self.game(0,mode='unbound');self.prepare(g);saved=g.snapshot()
        with self.assertRaises(Exception):self.play(g,CARD)
        self.assertEqual(g.snapshot(),saved)

    def test_weighted_request_requires_complete_positive_integer_weights_and_preserves_all_outcomes(self):
        options=(ChoiceOption('a','A'),ChoiceOption('b','B'))
        for weights in ((1,),(),(19,5)):
            if not weights or len(weights)==2:ChooseRandomEffects(1,1,options,weights)
            else:
                with self.assertRaises(ValueError):ChooseRandomEffects(1,1,options,weights)
        for weights in ((1,0),(1,-1),(True,2),(1,1.5),[1,2]):
            with self.assertRaises(ValueError):ChooseRandomEffects(1,1,options,weights)
        q=GenerateFromPool(1,'constructed.cards',PoolQuery(kinds=(CardType.SPELL,),collectible=True),
            source_id=1,cost=CostSpec(set_to=1),expires_turn=1)
        with self.assertRaises(ValueError):FillHandFromPool(q)

    def test_waiting_private_effects_and_rng_stay_hidden_and_old_schema_rejects(self):
        g=self.game(1,mode='spin_wait');self.prepare(g);self.play(g,CARD);saved=g.snapshot()
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in('resolution_frame','rng_state','CompleteDestroyedResources','CastSpellUntilHeroDies','CastFromPool'):
                self.assertNotIn('"'+key+'"',view)
        self.assertEqual(g.snapshot(),saved);bad=deepcopy(saved);bad['schema_version']=596
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,fixture())
        self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION)

    def test_full_frontier_discovery_wait_restores_set_one_card_and_real_ten_spell_gate(self):
        g=self.game(1,mode='frontier',hand=(GROW,'GDB_857'));self.prepare(g,9);self.play(g,'GDB_857')
        restored=self.portable(g)
        for game in(g,restored):
            self.choose(game,next(o.id for o in game.state.pending_choice.options if o.card_id==CARD))
            self.play(game,CARD);self.assertEqual(game.state.play_history[-1].cost,1)
            self.assertEqual(len(self.spins(game)),1)
            self.assertEqual(tuple(dict(self.spins(game)[0].data)['candidates']),OUTCOMES)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)


if __name__=='__main__':unittest.main()
