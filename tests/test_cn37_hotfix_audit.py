"""Focused native boundaries linked to official 37.0.1 constructed fixes."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.nzoth_card import CARD as NZOTH
from hs_sim.cards.empire_cthun_cards import GOD, SKILLS, FAMILY
from hs_sim.engine import Attack, CardDefinition, CardType, Game, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseMinionAbility, Zone
from hs_sim.engine.effects import ChoiceOption, GainArmor, GrantDeathrattle, InvokeBehavior, RequestChoice, ReturnToHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.ability_families import completed_ids
from hs_sim.engine.model import CardClass,CardMetadata,SummonQuantitySpec,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_deathrattle_qualifications import KEY
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards

ROCKFANG, AGENT, COIN = 'BE_731','BE_541','GAME_005'
ARCHAEDAS,HAMMER,HEX,FIREBALL='BE_055','BE_055t','CORE_EX1_246','CS2_029'
HAMMER_CONTEXT='fixture.hotfix37.hammer'
BOUNCE = 'fixture.hotfix37.bounce'
GRANT, REPLAY, WATCH, FAIL, QUANTITY = ('fixture.hotfix37.'+x for x in ('grant','replay','watch','fail','quantity'))


@lru_cache(maxsize=None)
def registry(role='writer',mode='normal'):
    r=build_registry();r._version+='.hotfix37.audit.'+mode
    if mode=='hammer':
        pool=PoolDefinition('constructed.cards','native-target-boundary-v1',HAMMER_CONTEXT,
            'experimental',(PoolMember(HEX),),complete=True)
        r.register_pool(pool)
    meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    r.register_behavior(GRANT+'.death',lambda c:())
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('deliberate qualification observer failure')))
    scripts={BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        GRANT:lambda c:(GrantDeathrattle(c.target_id,GRANT+'.death',c.source_id),),
        REPLAY:lambda c:(ReplayWholeCards(c.player_id,c.source_id,
            WholeCardHistoryQuery(c.player_id,len(c.state.play_history)+1,kinds=(CardType.MINION,)),
            physical_profile=PROFILE),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta,
            targeting=TargetSpec(kinds=(CardType.MINION,))if cid in (BOUNCE,GRANT)else None))
    def watch(c):
        if c.event.target_id not in c.state.entities or c.state.entities[c.event.target_id].card_id!=ROCKFANG:return ()
        if dict(c.event.data).get('ability_kind')!='deathrattle':return ()
        if mode=='fail':return (InvokeBehavior(FAIL,c.source_id,c.player_id),)
        if mode=='return':return (ReturnToHand(c.event.target_id),)
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fail','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=5,metadata=meta,
        triggers=(TriggerSpec('ability_granted',WATCH),)))
    r.register_card(CardDefinition(QUANTITY,QUANTITY,CardType.MINION,health=5,metadata=meta,
        summon_quantities=(SummonQuantitySpec(factor=2,source_kinds=(CardType.SPELL,)),)))
    return r


class CN37HotfixNativeAuditTests(unittest.TestCase):
    def game(self,board=(),hand=(),enemy=(),mode='normal'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_02'if mode=='hammer'else 'HERO_05',board=board,hand=hand,deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),seed=394,
            generation_context=GenerationContext(HAMMER_CONTEXT,'experimental')if mode=='hammer'else None),registry(mode=mode))

    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target));return eid

    def cost(self,g):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==NZOTH)
        return g.quote_cost(eid).amount

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));reader=registry('reader',self.mode)
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        return saved

    def rehash(self,value):
        value['events_hash']=canonical_hash(value['events'])
        value['state_hash']=canonical_hash({k:v for k,v in value.items()
            if k not in ('schema_version','events','events_hash','state_hash')})

    def test_native_empty_domain_finishes_and_counts_one_used_skill_without_rng(self):
        g=self.game(board=(GOD,));before=g.snapshot()['rng_state'];eid=g.state.players[1].board[0]
        g.apply(UseMinionAbility(1,eid,SKILLS[1]))
        self.assertEqual(completed_ids(g.state,g.registry.ability_family_profiles[FAMILY],1),(SKILLS[1],))
        self.assertEqual(len(g.state.ability_trigger_history),1)
        self.assertTrue(g.state.ability_trigger_history[0].completed)
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_native_gaze_has_one_invocation_history_and_one_used_skill(self):
        g=self.game(board=(GOD,),enemy=(AGENT,));source=g.state.players[1].board[0]
        g.apply(UseMinionAbility(1,source,SKILLS[2],g.state.players[2].board[0]))
        self.assertEqual(completed_ids(g.state,g.registry.ability_family_profiles[FAMILY],1),(SKILLS[2],))
        self.assertEqual(len(g.state.ability_trigger_history),1)
        self.assertTrue(g.state.ability_trigger_history[0].completed)
        self.assertEqual(len([e for e in g._events if e.kind=='minion_ability_started']),1)
        self.assertFalse(g.state.cast_history);self.portable(g)

    def obtain_hammer_without_other_friendly_minions(self,g):
        source=self.play(g,ARCHAEDAS);q=g.state.pending_choice
        option=next(x for x in q.options if x.card_id==HEX)
        g.apply(SelectChoice(q.player_id,q.id,(option.id,)))
        weapon=self.play(g,HAMMER)
        self.play(g,FIREBALL,source)
        self.assertFalse(g.state.players[1].board)
        return weapon

    def assert_no_target_hammer_cast(self,g,weapon):
        cast=g.state.cast_history[-1]
        self.assertEqual((cast.card_id,cast.caster_id,cast.failure,cast.target_id),(HEX,weapon,'no_target',None))
        self.assertTrue(cast.completed);self.assertFalse(cast.payload_started)
        self.assertEqual(g.state.entities[weapon].durability,2);self.portable(g)

    def test_native_hammer_no_valid_minion_target_finishes_without_extra_payment(self):
        g=self.game(hand=(ARCHAEDAS,FIREBALL),mode='hammer')
        weapon=self.obtain_hammer_without_other_friendly_minions(g);mana=g.state.players[1].mana
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.assertEqual(g.state.players[1].mana,mana)
        self.assertEqual(len(g.state.cast_history),2);self.assert_no_target_hammer_cast(g,weapon)

    def test_native_hammer_does_not_cast_on_the_last_minion_killed_by_its_attack(self):
        g=self.game(hand=(ARCHAEDAS,FIREBALL),enemy=(ARCHAEDAS,),mode='hammer')
        weapon=self.obtain_hammer_without_other_friendly_minions(g);target=g.state.players[2].board[0]
        g.apply(Attack(1,g.state.players[1].hero_id,target))
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertFalse(g.state.players[2].board);self.assert_no_target_hammer_cast(g,weapon)

    def test_assembled_overridden_taunt_does_not_block_an_actual_attack(self):
        from test_assemble_card_faces import registry as assemble_registry,TOP
        from hs_sim.engine.model import Keyword
        r=assemble_registry()
        self.assertIn(Keyword.TAUNT,r.card('alpha').keywords)
        g=Game.from_scenario(Scenario((PlayerSetup('hero',board=('beta',)),
            PlayerSetup('hero',board=(TOP,)))),r)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[g.state.players[2].board[0]].keywords)
        g.apply(Attack(1,g.state.players[1].board[0],g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,56)

    def test_own_battlecry_gained_deathrattle_counts_once_and_return_preserves_discount(self):
        g=self.game(board=(AGENT,),hand=(NZOTH,ROCKFANG,BOUNCE))
        self.assertEqual(self.cost(g),15)
        source=self.play(g,ROCKFANG)
        self.assertTrue(any(a.kind=='deathrattle' for a in g.state.entities[source].abilities))
        self.assertEqual(self.cost(g),14)
        original=asdict(g.state.successful_summon_history[0])
        self.play(g,BOUNCE,source)
        self.assertEqual(self.cost(g),14)
        self.assertEqual(asdict(g.state.successful_summon_history[0]),original)
        self.portable(g)

    def test_empty_adjacent_deathrattle_pool_does_not_qualify_an_entry(self):
        g=self.game(hand=(NZOTH,ROCKFANG));self.play(g,ROCKFANG)
        self.assertEqual(self.cost(g),15);self.assertFalse(g.state.summon_deathrattle_qualifications)

    def test_two_grants_share_one_original_qualifying_entry(self):
        g=self.game(board=(AGENT,'CORE_EX1_096'),hand=(NZOTH,ROCKFANG))
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==ROCKFANG)
        g.apply(PlayCard(1,source,position=1))
        self.assertEqual(len([a for a in g.state.entities[source].abilities if a.kind=='deathrattle']),2)
        self.assertEqual(len(g.state.summon_deathrattle_qualifications),1);self.assertEqual(self.cost(g),14)

    def test_return_and_real_reentry_create_two_distinct_qualifications(self):
        g=self.game(board=(AGENT,),hand=(NZOTH,ROCKFANG,BOUNCE))
        source=self.play(g,ROCKFANG);self.play(g,BOUNCE,source);self.play(g,ROCKFANG)
        self.assertEqual(self.cost(g),13)
        self.assertEqual([q.summon_id for q in g.state.summon_deathrattle_qualifications],[1,2])
        self.assertEqual([r.entity_id for r in g.state.successful_summon_history],[source,source]);self.portable(g)

    def test_later_unrelated_grant_never_retroactively_qualifies_the_old_entry(self):
        g=self.game(hand=(NZOTH,ROCKFANG,GRANT));source=self.play(g,ROCKFANG)
        self.play(g,GRANT,source)
        self.assertEqual(self.cost(g),15);self.assertFalse(g.state.summon_deathrattle_qualifications)

    def test_actual_nzoth_payment_freezes_qualified_price_and_portable_prefix(self):
        g=self.game(board=(AGENT,),hand=(NZOTH,ROCKFANG));self.play(g,ROCKFANG)
        before=g.state.players[1].mana;self.play(g,NZOTH)
        self.assertEqual(g.state.players[1].mana,before-14)
        self.assertEqual(len(g.state.summon_deathrattle_qualifications),1);self.portable(g)

    def test_generated_physical_battlecry_qualifies_its_actual_primary_entry(self):
        g=self.game(board=(AGENT,),hand=(NZOTH,ROCKFANG,REPLAY))
        self.play(g,ROCKFANG);self.play(g,REPLAY)
        self.assertEqual(self.cost(g),13)
        qs=g.state.summon_deathrattle_qualifications;self.assertEqual(len(qs),2)
        bc=g.state.battlecry_history[qs[-1].battlecry_id-1]
        self.assertIsNotNone(bc.physical_child_id);self.portable(g)

    def test_quantity_extra_without_its_own_battlecry_does_not_gain_a_qualification(self):
        g=self.game(board=(QUANTITY,AGENT),hand=(NZOTH,ROCKFANG,REPLAY))
        self.play(g,ROCKFANG);self.play(g,REPLAY)
        self.assertEqual(len(g.state.successful_summon_history),3)
        self.assertEqual(len(g.state.summon_deathrattle_qualifications),2)
        self.assertEqual(self.cost(g),13)

    def test_immediate_grant_reaction_returns_the_minion_without_erasing_its_qualification(self):
        g=self.game(board=(WATCH,AGENT),hand=(NZOTH,ROCKFANG),mode='return')
        source=self.play(g,ROCKFANG)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        self.assertFalse(any(a.kind=='deathrattle'for a in g.state.entities[source].abilities))
        self.assertEqual(self.cost(g),14)
        self.assertEqual(len(g.state.summon_deathrattle_qualifications),1);self.portable(g)

    def test_native_grant_wait_retains_qualification_and_failed_resume_is_atomic(self):
        g=self.game(board=(WATCH,AGENT),hand=(NZOTH,ROCKFANG),mode='wait');self.play(g,ROCKFANG)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.cost(g),14)
        saved=self.portable(g);q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'deliberate qualification observer failure'):
            g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertEqual(g.snapshot(),saved)
        g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(len(g.state.summon_deathrattle_qualifications),1);self.portable(g)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for name in (KEY,'summon_deathrattle_qualifications','deathrattle_qualifications'):
                self.assertNotIn('"'+name+'"',public)

    def test_late_observer_failure_rolls_back_payment_grant_history_and_rng(self):
        g=self.game(board=(WATCH,AGENT),hand=(NZOTH,ROCKFANG),mode='fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate qualification observer failure'):self.play(g,ROCKFANG)
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.cost(g),15)

    def test_rehashed_history_or_joint_event_marker_erasure_is_rejected(self):
        g=self.game(board=(AGENT,),hand=(NZOTH,ROCKFANG));self.play(g,ROCKFANG);saved=g.snapshot()
        for erase_event in (False,True):
            bad=deepcopy(saved);bad['state']['summon_deathrattle_qualifications']=[]
            if erase_event:
                for event in bad['events']:event['data'].pop(KEY,None)
            self.rehash(bad)
            with self.subTest(erase_event=erase_event),self.assertRaisesRegex(SnapshotError,'qualification'):
                Game.from_snapshot(bad,registry('reader',self.mode))


if __name__=='__main__':unittest.main()
