"""Actual improvement bodies, Colossal stat gains and repeatable rewards."""
from functools import lru_cache
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p68_cards as cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.simple_followup_p68_cards import (SOUL, SCYTHE, VOIDSCALE, BLAST,
    AMIRDRASSIL, WICKERFANG, QUEST, CAVE, OSK_HEALTH, OSK_TENDRILS, TENDRIL,
    ROOTS, PREFIX, LEGS, POOL_ID, load_batch, register_simple_followup_p68_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    TargetSpec, TriggerSpec, UseLocation, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, SetStats)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.model import DamageKind, LimitedTriggerSpec, SummonQuantitySpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST='p68.test.'
D1,D2,D10,MURLOC,ALL,MIXED,BEAST,VICTIM,DOUBLE,WATCH=(TEST+s for s in ('d1','d2','d10','murloc','all','mixed','beast','victim','double','watch'))
S1,S2,S10,KILL,BUFF,SET,NEGATIVE,NOOP,WAVE,CLEAR=(TEST+s for s in ('s1','s2','s10','kill','buff','set','negative','noop','wave','clear'))
UNKNOWN_DEMON,UNKNOWN_SPELL=TEST+'unknown_demon',TEST+'unknown_spell'
YETI='CORE_CS2_182'
CONTEXT=GenerationContext('p68-complete-explicit-fixture','experimental')
MEMBERS=((D1,1),(D2,1),(D10,1),(S1,1),(S2,1),(S10,1))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()


def meta(tribes=()):return CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=tribes)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p68_cards(r)
    elif not all(present):raise AssertionError('P68 requires its complete assigned assembly')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None,members=MEMBERS):
    r=batch_registry()
    for cid,cost,attack,health,tribes in ((D1,1,1,2,('demon',)),(D2,2,2,3,('demon',)),(D10,10,10,12,('demon',)),
            (MURLOC,1,1,1,('murloc',)),(ALL,1,1,1,('all',)),(MIXED,1,1,1,('murloc','beast')),
            (BEAST,1,1,1,('beast',)),(VICTIM,1,3,7,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,metadata=meta(tribes)))
    def kill(c):return(Destroy(c.target_id,c.source_id),)
    def wave(c):
        request=SummonByCard(c.player_id,(SummonEntryMaterial(MURLOC),),SummonCause.capture(c))
        return(request,)*6
    scripts={S1:lambda c:(GainArmor(c.player_id,1),),S2:lambda c:(GainArmor(c.player_id,2),),S10:lambda c:(GainArmor(c.player_id,10),),
        KILL:kill,BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),),
        NEGATIVE:lambda c:(Buff(c.target_id,-2,3,c.source_id),),SET:lambda c:(SetStats(c.target_id,attack=4,health=8,source_id=c.source_id),),
        NOOP:lambda c:(),WAVE:wave,CLEAR:lambda c:tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board
            if c.state.entities[i].kind==CardType.MINION)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost={S1:1,S2:2,S10:10}.get(cid,0),on_play=cid,
            targeting=TargetSpec()if cid in(KILL,BUFF,NEGATIVE,SET)else None,metadata=meta()))
    r.register_card(CardDefinition(DOUBLE,'Actual quantity source',CardType.MINION,health=20,
        summon_quantities=(SummonQuantitySpec(2),),metadata=meta()))
    r.register_pool_card(PoolCard(UNKNOWN_DEMON,CardType.MINION,1,meta(('demon',)),battlecry=False,deathrattle=False,choose_one=False))
    r.register_pool_card(PoolCard(UNKNOWN_SPELL,CardType.SPELL,1,meta(),battlecry=False,deathrattle=False,choose_one=False))
    for cid,_ in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID,'p68-complete-finite-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid,w)for cid,w in members),complete=True))
    def fail(c):raise ResolutionError('P68 deliberate continuation failure')
    def reenter(c):
        # The public ordinary Colossal route is distinct from attributed
        # ordinary-minion copy material. This fixture has no quantity source.
        return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),)
    r.register_behavior(TEST+'fail',fail);r.register_behavior(TEST+'reenter',reenter)
    if mode:
        event={'summon':'minion_summoned','spell':'spell_cast_finished','stat':'stats_changed'}[mode]
        def eligible(c):
            if mode=='summon':return c.state.entities[c.event.target_id].card_id==D1
            if mode=='stat':return c.state.entities[c.event.target_id].card_id in LEGS
            row=cast_record(c.state,dict(c.event.data)['cast_id'])
            return row.card_id==S1 and row.caster_id is not None
        def wait(c):
            options=[ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))]
            if mode=='spell':target=cast_record(c.state,dict(c.event.data)['cast_id']).caster_id
            else:target=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==(
                AMIRDRASSIL if mode=='summon'else WICKERFANG))
            death=DestroyLocation(target,c.source_id)if mode=='summon'else Destroy(target,c.source_id)
            options.append(ChoiceOption('kill','Kill original source',(death,)))
            if mode=='stat':options.append(ChoiceOption('cycle','Original body leaves and reenters',(
                ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target))))
            return(RequestChoice(1,tuple(options),c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'wait',wait)
        r.register_card(CardDefinition(WATCH,'One-use real checkpoint',CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),),metadata=meta()))
    r.validate();return r


@lru_cache(maxsize=None)
def fixture_registry(mode,members,role,pin):
    if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Incomplete immutable fixture key')
    r=registry(mode,members);r.freeze();return r


class SimpleFollowupP68Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),deck=(YETI,)*16,weapon=None,mode=None,members=MEMBERS,hand_cap=None):
        self.config=mode,members
        if mode:board=(WATCH,)+board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_10',hand=hand,board=board,deck=deck,
            weapon_card_id=weapon,mana=40,max_mana=40,mana_cap=40,hand_cap=hand_cap),
            PlayerSetup('HERO_10',hand=enemy_hand,board=enemy,deck=(YETI,)*16,mana=40,max_mana=40,mana_cap=40)),
            seed=6868,generation_context=CONTEXT),fixture_registry(mode,members,'writer',SOURCE_PIN))

    def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,pid=1):
        e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,
            position=len(g.state.players[pid].board)if e.kind in(CardType.MINION,CardType.LOCATION)else None));return e.id
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def count(self,g,family,pid=1):return sum(e.spec_id==PREFIX+family for e in g.state.players[pid].player_effects)
    def portable(self,g):
        reader=fixture_registry(*self.config,'reader',SOURCE_PIN)
        self.assertIsNot(reader,g.registry);self.assertEqual(reader.fingerprint(),g.registry.fingerprint())
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for pid in(1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in('rng_state','resolution_frame','behavior_id','source_allocation','draw_history','hand_entries'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a0_tendril_native_random_cast_then_shared_improvement_survives_source_death_wait_restore(self):
        g=self.game((TENDRIL,TENDRIL),mode='spell');source=self.play(g,TENDRIL)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.count(g,'tendril_progress'),0);self.portable(g)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'kill');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(self.count(g,'tendril_progress'),1);self.play(g,TENDRIL)
        self.assertEqual([r.card_id for r in g.state.cast_history],[S1,S2]);self.assertEqual(self.count(g,'tendril_progress'),2);self.portable(g)

    def test_a1_location_actual_frozen_four_operations_across_two_physical_sources(self):
        g=self.game((AMIRDRASSIL,AMIRDRASSIL));first=self.play(g,AMIRDRASSIL);g.apply(UseLocation(1,first))
        second=self.play(g,AMIRDRASSIL);g.apply(UseLocation(1,second))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3)
        self.assertEqual(len(g.state.draw_history),3);self.assertEqual(g.state.players[1].mana,33)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board if g.state.entities[i].kind==CardType.MINION],[D1,D2])
        self.assertEqual(self.count(g,'location_progress'),2);self.assertFalse(g.state.cast_history)
        self.assertTrue(all(row.spec.cause.cast_id is None and row.spec.cause.source.kind==CardType.LOCATION for row in g.state.pool_summon_history));self.portable(g)

    def test_a2_location_summon_wait_precedes_other_operations_and_source_destruction_does_not_cancel(self):
        g=self.game((AMIRDRASSIL,),mode='summon');source=self.play(g,AMIRDRASSIL);g.apply(UseLocation(1,source))
        self.assertEqual(self.count(g,'location_progress'),0);self.assertFalse(g.state.draw_history)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.portable(g)
        self.choose(g,'kill');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(self.count(g,'location_progress'),1);self.assertEqual(len(g.state.draw_history),1);self.portable(g)

    def test_b0_void_soul_two_real_casts_generate_exact_cost_demons_and_owner_progress(self):
        g=self.game((SOUL,SOUL));self.play(g,SOUL);self.play(g,SOUL)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[D1,D2])
        self.assertEqual(self.count(g,'soul_progress'),2);self.assertEqual(self.count(g,'soul_progress',2),0)
        self.assertEqual([r.card_id for r in g.state.cast_history],[SOUL,SOUL]);self.assertTrue(all(r.spec.cause.cast_id is not None for r in g.state.pool_summon_history));self.portable(g)

    def test_b1_void_progress_empty_tiers_and_full_board_still_improve_and_cap_is_explicit(self):
        g=self.game((SOUL,)*11,board=(D1,)*7,hand_cap=20)
        for _ in range(11):self.play(g,SOUL)
        self.assertEqual(self.count(g,'soul_progress'),11);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual([r.spec.basis.query.min_cost for r in g.state.pool_summon_history],[1,2,3,4,5,6,7,8,9,10,10]);self.portable(g)

    def test_b2_scythe_last_durability_and_voidscale_only_actual_death_produce_souls(self):
        g=self.game((VOIDSCALE,KILL),weapon=SCYTHE);source=self.play(g,VOIDSCALE)
        self.assertEqual(sum(g.state.entities[i].card_id==SOUL for i in g.state.players[1].hand),0)
        self.play(g,KILL,source);self.assertEqual(sum(g.state.entities[i].card_id==SOUL for i in g.state.players[1].hand),1)
        hero=g.state.players[1].hero_id;enemy=g.state.players[2].hero_id
        for n in range(3):
            if n:g.apply(EndTurn(1));g.apply(EndTurn(2))
            g.apply(Attack(1,hero,enemy))
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(sum(g.state.entities[i].card_id==SOUL for i in g.state.players[1].hand),4);self.portable(g)

    def test_b3_void_blast_original_damage_death_is_required_and_spell_damage_is_native(self):
        g=self.game((BLAST,),enemy=(MURLOC,));target=self.first(g,MURLOC,'board',2).id;self.play(g,BLAST,target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(self.first(g,SOUL).zone,Zone.HAND);self.portable(g)
        g=self.game((BLAST,),enemy=(VICTIM,));self.play(g,BLAST,self.first(g,VICTIM,'board',2).id)
        self.assertFalse(g.state.players[1].hand);self.assertFalse(g.state.death_history);self.portable(g)

    def test_c0_wickerfang_native_colossal_four_complete_legs_and_end_turn_real_gains(self):
        g=self.game((WICKERFANG,));source=self.play(g,WICKERFANG)
        self.assertEqual(len(g.state.players[1].board),5);self.assertEqual(len(g.state.colossal_history),1)
        self.assertEqual({g.state.entities[i].card_id for i in g.state.colossal_history[0].limbs},set(LEGS))
        g.apply(EndTurn(1));e=g.state.entities[source];self.assertEqual((e.attack,e.health),(4,9));self.portable(g)

    def test_c1_wickerfang_positive_buff_and_positive_set_stat_differences_not_negative_attack(self):
        g=self.game((NEGATIVE,SET),board=(WICKERFANG,LEGS[0]));leg=self.first(g,LEGS[0],'board').id
        source=self.first(g,WICKERFANG,'board').id;self.play(g,NEGATIVE,leg)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(0,8))
        self.play(g,SET,leg);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(4,11));self.portable(g)

    def test_c2_wickerfang_original_body_reentry_does_not_adopt_delayed_gain(self):
        g=self.game((BUFF,),board=(WICKERFANG,LEGS[0]),mode='stat');source=self.first(g,WICKERFANG,'board').id
        self.play(g,BUFF,self.first(g,LEGS[0],'board').id);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'cycle')
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(0,5));self.portable(g)

    def test_c3_wickerfang_enemy_named_legs_do_not_grant_and_friendly_independent_legs_do(self):
        g=self.game((BUFF,BUFF),board=(WICKERFANG,LEGS[1]),enemy=(LEGS[2],));source=self.first(g,WICKERFANG,'board').id
        self.play(g,BUFF,self.first(g,LEGS[2],'board',2).id);self.assertEqual(g.state.entities[source].attack,0)
        self.play(g,BUFF,self.first(g,LEGS[1],'board').id);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,8));self.portable(g)

    def test_d0_repeatable_quest_six_summons_reward_then_fresh_cycles_stack_actual_murloc_grants(self):
        g=self.game((QUEST,WAVE,MURLOC,CLEAR,WAVE,MURLOC));quest=self.play(g,QUEST);old=g.state.entities[quest].quest_progress.id
        self.play(g,WAVE);self.assertEqual(self.count(g,'cave'),1);self.assertNotEqual(g.state.entities[quest].quest_progress.id,old)
        self.assertTrue(all(g.state.entities[i].attack==1 for i in g.state.players[1].board))
        first=self.play(g,MURLOC);self.assertEqual((g.state.entities[first].attack,g.state.entities[first].health),(2,2))
        self.play(g,CLEAR);self.play(g,WAVE)
        self.assertEqual(self.count(g,'cave'),2);self.assertEqual(g.state.entities[quest].zone,Zone.QUEST)
        second=self.play(g,MURLOC);self.assertEqual((g.state.entities[second].attack,g.state.entities[second].health),(3,3));self.portable(g)

    def test_d1_cave_actual_reward_spell_stacks_and_all_and_dual_current_tribes_count_once(self):
        g=self.game((CAVE,CAVE,ALL,MIXED,BEAST));self.play(g,CAVE);self.play(g,CAVE)
        for cid in(ALL,MIXED):
            eid=self.play(g,cid);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(3,3))
        eid=self.play(g,BEAST);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(1,1));self.portable(g)

    def test_d2_quest_playing_enemy_or_nonmurloc_is_not_own_progress(self):
        g=self.game((QUEST,BEAST),enemy_hand=(MURLOC,));quest=self.play(g,QUEST);self.play(g,BEAST)
        self.assertEqual(g.state.entities[quest].quest_progress.value,0)
        g.apply(EndTurn(1));self.play(g,MURLOC,pid=2)
        self.assertEqual(g.state.entities[quest].quest_progress.value,0);self.portable(g)

    def test_e0_osk_actual_remaining_enemy_health_gates_minion_and_hero_health_gain(self):
        g=self.game((OSK_HEALTH,),enemy=(VICTIM,));target=self.first(g,VICTIM,'board',2).id
        source=self.play(g,OSK_HEALTH,target);e=g.state.entities[source];hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((e.attack,e.health),(6,13));self.assertEqual((hero.health,hero.max_health),(37,37));self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.portable(g)

    def test_e1_osk_actual_custom_hand_capacity_creates_full_real_tendrils_without_overflow(self):
        g=self.game((OSK_TENDRILS,NOOP),hand_cap=4);source=self.play(g,OSK_TENDRILS)
        self.assertEqual(len(g.state.players[1].hand),4)
        self.assertEqual(sum(g.state.entities[i].card_id==TENDRIL for i in g.state.players[1].hand),3)
        self.assertEqual(sum(e.kind=='card_created'and e.source_id==source for e in g.events),3);self.assertFalse(any(e.kind=='card_burned'for e in g.events));self.portable(g)

    def test_e2_tendrils_cap_independent_from_void_souls_and_no_eligible_spell_still_improves(self):
        g=self.game((TENDRIL,)*11+(CLEAR,),hand_cap=20)
        for _ in range(11):
            if len(g.state.players[1].board)==7:self.play(g,CLEAR)
            self.play(g,TENDRIL)
        self.assertEqual(self.count(g,'soul_progress'),0);self.assertEqual(self.count(g,'tendril_progress'),11)
        self.assertEqual([r.card_id for r in g.state.cast_history if r.caster_id is not None],[S1,S2,S10,S10]);self.portable(g)

    def test_f0_eligible_unknown_pool_definitions_reject_and_rollback_without_deletion(self):
        for cid,unknown in((SOUL,UNKNOWN_DEMON),(TENDRIL,UNKNOWN_SPELL)):
            with self.subTest(cid=cid):
                g=self.game((cid,),members=MEMBERS+((unknown,1),));saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved)

    def test_f1_complete_raw_primary_parent_links_dependencies_and_old_registry_rows_preserved(self):
        from tools.card_batch import check_face
        d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(7,4,32))
        self.assertEqual(len(d['exact_parent_child_links']),20);self.assertEqual(d['necessary_cross_format_collectibles'],[TENDRIL])
        self.assertFalse(d['parents_implemented']);self.assertFalse(d['formal_pool_complete']or d['cn_calibrated']or d['reachability_complete'])
        records={x['record']['id']:x['record']for key in('cards','dependencies','existing_dependencies','evidence_only')for x in d[key]}
        for obs in d['official_observations']:
            cid=obs['card_id'];check_face(records[cid],obs['face'],obs['locale'],d['display_normalizations'].get(cid),numeric_normalizations=d['numeric_normalizations'].get(cid))
        before,after=build_registry(),batch_registry()
        for cid,value in before.cards.items():self.assertEqual(after.card(cid),value)
        for cid,value in before.pool_cards.items():self.assertEqual(after.pool_card(cid),value)
        self.assertEqual(before.fabled,after.fabled);self.assertEqual(before.generation_families,after.generation_families)
        for cid,pin in d['existing_dependency_definition_pins'].items():self.assertEqual(canonical_digest(asdict(after.card(cid))),pin['sha256'])


if __name__=='__main__':unittest.main()
