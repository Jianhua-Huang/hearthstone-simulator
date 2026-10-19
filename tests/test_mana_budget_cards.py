"""Fyrakk's real native entry, printed budget, ordinary casts and school immunity."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.mana_budget_cards import CARD, IMMUNITY, POOL_ID, load_batch, register_mana_budget_cards
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CostSpec, EndTurn,
    Game, HealthOp, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Registry, Ruleset, Scenario,
    SelectChoice, SnapshotError, SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddCostModifier, ChangeControl, ChoiceOption, Damage, DamageBatch,
    Destroy, InvokeBehavior, RequestChoice, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError, ResolutionLimitExceeded
from hs_sim.engine.model import DamageKind, SpellManaBudgetLink
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_mana_budget import CastManaWorth, query
from hs_sim.engine.zones import MinionReference, CopyCard
from hs_sim.targets import canonical_digest

P='budget.test.'
FIVE, THREE, SEVEN, ZERO, HUGE = (P+x for x in ('fire5','fire3','fire7','fire0','fire16'))
CTX=GenerationContext('native-spell-budget-experiment','experimental')


def registry(mode=None,pool=(FIVE,),unknown=None):
    r=Registry('fyrakk-tests-v1.'+str((mode,pool,unknown)));register_mana_budget_cards(r)
    r.register_card(CardDefinition(P+'avatar','Hero',CardType.HERO,health=100,
        metadata=CardMetadata(False,(CardClass.MAGE,),Rarity.NONE)))
    r.register_card(CardDefinition(P+'plain','Plain',CardType.MINION,attack=1,health=12))
    r.register_behavior(P+'noop',lambda c:())
    def spell(cid,cost,body,school=SpellSchool.FIRE,target=True):
        r.register_behavior(cid,body)
        targeting=(TargetSpec(kinds=(CardType.MINION,),relation='friendly')
            if cid==FIVE and mode=='destroy' else TargetSpec()) if target else None
        d=CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,
            spell_school=school,targeting=targeting,
            metadata=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    def body(c):
        if mode=='lethal':return (Damage(c.state.players[3-c.player_id].hero_id,200,c.source_id,DamageKind.SPELL),)
        if mode=='destroy':return (Destroy(c.target_id,c.source_id),)
        if mode in ('control','silence','transform'):
            source=c.cast.caster_id
            return ((ChangeControl(source,3-c.player_id),) if mode=='control' else
                (Silence(source),) if mode=='silence' else (Transform(source,P+'plain'),))
        return (Damage(c.target_id,1,c.source_id,DamageKind.SPELL),)
    for cid,cost in ((FIVE,5),(THREE,3),(SEVEN,7),(ZERO,0),(HUGE,16)):
        spell(cid,cost,(lambda c:()) if cid==ZERO else body,target=cid!=ZERO)
    spell(P+'frost',0,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),SpellSchool.FROST)
    spell(P+'hit_fire',0,lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),))
    spell(P+'hit_effect',0,lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.EFFECT),))
    spell(P+'fire_destroy',0,lambda c:(Destroy(c.target_id,c.source_id),))
    def aoe(c):
        return (DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)
            for i in c.state.players[3-c.player_id].board)),)
    spell(P+'aoe',0,aoe,target=False)
    for name,body_fn in (
        ('discount',lambda c:(AddCostModifier(c.player_id,CostSpec(set_to=0,card_types=(CardType.SPELL,))),)),
        ('increase',lambda c:(AddCostModifier(c.player_id,CostSpec(set_to=99,card_types=(CardType.SPELL,))),)),
        ('copy',lambda c:(CopyCard(MinionReference.capture(c.state.entities[c.target_id]),c.player_id),)),
        ('silence',lambda c:(Silence(c.target_id),)),
        ('summon',lambda c:(Summon(c.player_id,CARD,c.source_id),))):
        r.register_behavior(P+name,body_fn)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,
            targeting=TargetSpec(kinds=(CardType.MINION,)) if name in ('copy','silence') else None))
    def fail(c):raise ResolutionError('Fyrakk deliberate reaction failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        cast=c.state.cast_history[dict(c.event.data)['cast_id']-1]
        if cast.mana_budget is None:return ()
        if mode=='nested':return (CastSpell(c.player_id,P+'frost',c.source_id),)
        if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=50,
        triggers=(TriggerSpec('spell_cast_finished' if mode=='wait_finish' else 'spell_cast_started',P+'watch'),)))
    members=(*pool,P+'frost')
    if unknown is not None:
        r.register_pool_card(PoolCard(P+'unknown',CardType.SPELL,unknown,
            CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON),spell_school=SpellSchool.FIRE))
        members=(*members,P+'unknown')
    r.register_pool(PoolDefinition(POOL_ID,'budget-fixture-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid) for cid in members),complete=True))
    r.validate();return r


OPS=tuple(P+x for x in ('frost','hit_fire','hit_effect','fire_destroy','aoe','discount','increase','copy','silence','summon'))


class ManaBudgetTests(unittest.TestCase):
    def game(self,mode=None,pool=(FIVE,),unknown=None,pid=1,board=(),enemy_board=(P+'plain',),rules=None):
        self.mode,self.pool,self.unknown,self.pid=mode,pool,unknown,pid
        actor=PlayerSetup(P+'avatar',hand=(CARD,*OPS),hand_cap=30,deck=(P+'plain',)*5,
            board=(*board,*((P+'watch',) if mode in ('wait_start','wait_finish','nested','fail') else ())),
            mana=20,max_mana=20,mana_cap=20)
        other=PlayerSetup(P+'avatar',hand=OPS,hand_cap=30,deck=(P+'plain',)*5,board=enemy_board,
            mana=20,max_mana=20,mana_cap=20)
        return Game.from_scenario(Scenario((actor,other) if pid==1 else (other,actor),
            active_player=pid,generation_context=CTX,seed=31),registry(mode,pool,unknown),ruleset=rules)

    def play(self,g,cid=CARD,target=None,pid=None):
        pid=self.pid if pid is None else pid
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target));return eid

    def casts(self,g):return [c for c in g.state.cast_history if c.mana_budget is not None]

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(saved,registry(self.mode,self.pool,self.unknown))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(self.mode,self.pool,self.unknown)).snapshot(),saved)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('mana_budget','previous_cast_id','pool_id','rng_state','resolution_frame'):
                self.assertNotIn('"'+key+'"',visible)
        return other

    def reject(self,snapshot):
        snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,registry(self.mode,self.pool,self.unknown))

    def test_a00_original_ten_mana_dragon_and_all_33_fire_sources(self):
        data=load_batch();r=build_registry();raw=data['cards'][0]['record'];c=r.card(CARD)
        self.assertEqual((c.cost,c.attack,c.health,c.health_rules),(10,7,7,(IMMUNITY,)))
        self.assertEqual(c.metadata,metadata_from_record(raw));self.assertNotIn(Keyword.IMMUNE,c.keywords)
        self.assertEqual(len(data['official_observations']),2);self.assertEqual(len(data['existing_dependencies']),33)
        for row in data['existing_dependencies']:
            raw=row['record'];d=r.card(raw['id'])
            self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual(d.spell_school,SpellSchool.FIRE);self.assertEqual(d.cost,raw['cost'])
            self.assertEqual(d.metadata,replace(metadata_from_record(raw),deck_identity=raw['id'].removeprefix('CORE_')))

    def test_a01_paid_real_battlecry_casts_three_physical_five_cost_spells(self):
        g=self.game();eid=self.play(g);casts=self.casts(g)
        self.assertEqual([(c.card_id,c.player_id,c.caster_id,c.origin) for c in casts],[(FIVE,1,eid,'effect')]*3)
        self.assertEqual([c.mana_budget.remaining for c in casts],[15,10,5])
        self.assertEqual([c.mana_budget.previous_cast_id for c in casts],[None,1,2])
        self.assertTrue(all(c.completed for c in casts));self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len({c.source_id for c in casts}),3)
        self.assertTrue(all(c.source_id!=eid for c in casts))

    def test_a02_mixed_printed_costs_sum_to_fifteen_and_use_new_remainders(self):
        g=self.game(pool=(THREE,FIVE,SEVEN));self.play(g);casts=self.casts(g)
        self.assertEqual(sum(g.registry.pool_card(c.card_id).cost for c in casts),15)
        remaining=15
        for c in casts:
            self.assertEqual(c.mana_budget.remaining,remaining)
            remaining-=g.registry.pool_card(c.card_id).cost
        self.assertEqual(remaining,0);self.portable(g)

    def test_a03_player_hand_discount_or_price_increase_does_not_change_printed_budget(self):
        for name in ('discount','increase'):
            with self.subTest(name=name):
                g=self.game();self.play(g,P+name);self.play(g)
                self.assertEqual(len(self.casts(g)),3)
                self.assertEqual([c.mana_budget.remaining for c in self.casts(g)],[15,10,5])
                self.assertEqual(g.state.players[1].mana,10)

    def test_a04_enemy_preference_preserves_complete_target_domain(self):
        g=self.game();self.play(g)
        self.assertTrue(all(g.state.entities[c.target_id].controller==2 for c in self.casts(g)))

    def test_a05_required_friendly_target_and_no_target_attempts_still_spend_budget(self):
        g=self.game(mode='destroy',enemy_board=());source=self.play(g);casts=self.casts(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual([c.failure for c in casts],[None,'no_target','no_target'])
        self.assertEqual([c.mana_budget.remaining for c in casts],[15,10,5]);self.portable(g)

    def test_a06_source_silence_control_or_transform_keeps_original_accepted_sequence(self):
        for mode in ('silence','control','transform'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);source=self.play(g)
                self.assertEqual(len(self.casts(g)),3)
                self.assertTrue(all(c.player_id==1 and c.caster_id==source and c.mana_budget.source_card_id==CARD for c in self.casts(g)))
                self.assertEqual(g.state.entities[source].card_id,P+'plain' if mode=='transform' else CARD)

    def test_a07_sparse_pool_stops_without_inventing_a_cost_one_spell(self):
        g=self.game(pool=(SEVEN,));self.play(g)
        self.assertEqual(len(self.casts(g)),2);self.assertEqual([c.mana_budget.remaining for c in self.casts(g)],[15,8])
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_a08_empty_eligible_pool_does_not_consume_rng(self):
        g=self.game(pool=(HUGE,));before=g.snapshot()['rng_state'];self.play(g)
        self.assertFalse(self.casts(g));self.assertEqual(g.snapshot()['rng_state'],before)

    def test_a09_unknown_eligible_candidate_rolls_back_root_before_sampling(self):
        g=self.game(unknown=5);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_a10_unknown_printed_cost_above_remaining_is_not_an_eligible_candidate(self):
        g=self.game(unknown=20);self.play(g);self.assertEqual(len(self.casts(g)),3)

    def test_a11_zero_cost_not_filtered_and_original_interpreter_budget_bounds_an_empty_cost_loop(self):
        g=self.game(pool=(ZERO,),rules=Ruleset(max_resolution_steps=60));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_a12_first_cast_and_completed_last_cast_waiting_restore_clone_replay(self):
        for mode in ('wait_start','wait_finish'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.play(g);restored=self.portable(g)
                count=0
                while g.state.pending_choice is not None:
                    before=g.snapshot()
                    with self.assertRaises(ResolutionError):self.choose(g,'bad')
                    self.assertEqual(g.snapshot(),before)
                    for match in (g,restored):self.choose(match)
                    self.assertEqual(g.snapshot(),restored.snapshot());count+=1
                self.assertEqual(count,3);self.assertEqual(len(self.casts(g)),3);self.portable(g)

    def test_a13_nested_independent_casts_do_not_spend_or_reparent_budget(self):
        g=self.game(mode='nested');self.play(g);casts=self.casts(g)
        self.assertEqual([c.id for c in casts],[1,3,5]);self.assertEqual([c.mana_budget.previous_cast_id for c in casts],[None,1,3])
        self.assertEqual(len(g.state.cast_history),6);self.portable(g)

    def test_a14_reaction_failure_rolls_back_payment_rng_and_all_actual_casts(self):
        g=self.game(mode='fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_a15_second_seat_keeps_original_caster_and_enemy_preference(self):
        g=self.game(pid=2);source=self.play(g)
        self.assertTrue(all(c.player_id==2 and c.caster_id==source and
            g.state.entities[c.target_id].controller==1 for c in self.casts(g)))

    def test_a16_fire_spell_damage_prevented_but_frost_and_effect_damage_are_not(self):
        g=self.game(board=(CARD,));source=g.state.players[1].board[0]
        self.play(g,P+'hit_fire',source);self.assertEqual(g.state.entities[source].health,7)
        self.play(g,P+'frost',source);self.assertEqual(g.state.entities[source].health,6)
        self.play(g,P+'hit_effect',source);self.assertEqual(g.state.entities[source].health,4)

    def test_a17_enemy_manual_fire_target_excluded_but_other_school_target_remains(self):
        g=self.game(enemy_board=(CARD,));target=g.state.players[2].board[0];before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,P+'hit_fire',target)
        self.assertEqual(g.snapshot(),before)
        self.play(g,P+'frost',target);self.assertEqual(g.state.entities[target].health,6)

    def test_a18_untargeted_enemy_fire_damage_is_prevented_and_own_fire_destroy_is_allowed(self):
        g=self.game(enemy_board=(CARD,));target=g.state.players[2].board[0]
        self.play(g,P+'aoe');self.assertEqual(g.state.entities[target].health,7)
        g=self.game(board=(CARD,));source=g.state.players[1].board[0]
        self.play(g,P+'fire_destroy',source);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)

    def test_a19_silence_removes_school_immunity_and_a_current_copy_preserves_it(self):
        g=self.game(board=(CARD,));source=g.state.players[1].board[0]
        self.play(g,P+'copy',source);copied=g.state.players[1].hand[-1]
        self.assertEqual([a.health_rule for a in g.state.entities[copied].abilities if a.kind=='health_rule'],[IMMUNITY])
        self.play(g,P+'silence',source);self.play(g,P+'hit_fire',source)
        self.assertEqual(g.state.entities[source].health,5)

    def test_a20_school_immunity_does_not_prevent_normal_combat(self):
        g=self.game(board=(CARD,),enemy_board=(P+'plain',));source=g.state.players[1].board[0]
        target=g.state.players[2].board[0];g.apply(Attack(1,source,target))
        self.assertEqual(g.state.entities[source].health,6)

    def test_a21_summoning_the_dragon_does_not_execute_its_battlecry(self):
        g=self.game();self.play(g,P+'summon');self.assertFalse(self.casts(g))
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id,CARD)

    def test_a22_malformed_budget_or_immunity_profiles_are_rejected(self):
        link=SpellManaBudgetLink(POOL_ID,SpellSchool.FIRE,15,15,CARD)
        for fields in ({'budget':True},{'remaining':0},{'remaining':16},{'remaining':5},{'school':'fire'}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(link,**fields)
        for fields in ({'target_relation':'friendly'},{'damage_kinds':()},{'schools':()}, {'amount':1}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(IMMUNITY,**fields)
        with self.assertRaises(ValueError):CastManaWorth(1,POOL_ID,SpellSchool.FIRE,15,None,CARD)

    def test_a23_rehashed_cast_budget_fields_and_missing_continuation_are_rejected(self):
        g=self.game(mode='wait_start');self.play(g);original=g.snapshot()
        for field,value in (('remaining',5),('school','frost'),('previous_cast_id',1),('source_card_id',P+'frost')):
            s=deepcopy(original);s['state']['cast_history'][0]['mana_budget'][field]=value
            with self.subTest(field=field):self.reject(s)
        s=deepcopy(original)
        def drop(v):
            if isinstance(v,dict):
                for x in v.values():drop(x)
            elif isinstance(v,list):
                v[:]=[x for x in v if not (isinstance(x,dict) and x.get('type','').endswith('.ContinueSpellManaWorth'))]
                for x in v:drop(x)
        drop(s);self.reject(s)

    def test_a24_complete_contextual_candidate_pool_does_not_use_adapter_filtering(self):
        r=build_registry();data=load_batch();names=tuple(x['record']['id'] for x in data['existing_dependencies'])
        from hs_sim.cards.candidate_generation_catalog import load_batch as candidate_catalog
        all_roots=tuple(candidate_catalog()['candidate_root_ids'])
        r.register_pool(PoolDefinition(POOL_ID,'cn37-all-root-experiment-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid) for cid in all_roots),complete=False))
        rows=resolve_candidates(r,CTX,POOL_ID,query(SpellSchool.FIRE,15),source_card_id=CARD,player_id=1,exclude_source_by_rule=True)
        self.assertEqual({m.card_id for m in rows},set(names));self.assertEqual(len(rows),33)

    def test_a25_terminal_game_interrupts_remaining_budget_and_restores_its_actual_prefix(self):
        g=self.game(mode='lethal');self.play(g)
        self.assertNotEqual(g.state.status,'playing');self.assertEqual(len(self.casts(g)),1)
        self.assertIsNone(g.state.pending_choice);self.portable(g)


if __name__=='__main__':unittest.main()
