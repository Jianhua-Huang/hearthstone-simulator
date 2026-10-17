"""Bilateral native summons and complete independent named-family consumers."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p70_cards as cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.simple_followup_p70_cards import (MULTIVERSE, BRIBE, TINY, GREEN, EXPLORER,
    WARCHIEF, MINDFLAYER, CALAMITOUS, MURLOC, ARCHMAGE, SHEEP, PARENT, GIANT,
    ROOTS, FAMILY, PREFIX, POOL_ID, load_batch, register_simple_followup_p70_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    PlayCard, PlayerSetup, Rarity, Ruleset, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (ChoiceOption, Destroy, InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChoicePurpose, LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, DiscardCard
from hs_sim.targets import canonical_digest

TEST='p70.test.'
M0,M1,M2,M3,M6,M20,FAKE,WATCH=(TEST+s for s in ('m0','m1','m2','m3','m6','m20','fake','watch'))
KILL,NOOP,UNKNOWN=TEST+'kill',TEST+'noop',TEST+'unknown'
COLOSSAL='CATA_139'
YETI='CORE_CS2_182'
CONTEXT=GenerationContext('p70-complete-explicit-fixture','experimental')
MEMBERS=((M2,1),(M3,1))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()


def meta():return CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p70_cards(r)
    elif not all(present):raise AssertionError('P70 requires its complete assigned assembly')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None,members=MEMBERS):
    r=batch_registry()
    for cid,cost,atk,hp in((M0,0,0,2),(M1,1,1,5),(M2,2,2,7),(M3,3,3,9),(M6,6,6,12),(M20,20,20,20),(FAKE,2,1,4)):
        r.register_card(CardDefinition(cid,'Rafaam impostor'if cid==FAKE else cid,CardType.MINION,cost=cost,attack=atk,health=hp,metadata=meta()))
    r.register_behavior(KILL,lambda c:(Destroy(c.target_id,c.source_id),));r.register_behavior(NOOP,lambda c:())
    for cid in(KILL,NOOP):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
        targeting=TargetSpec()if cid==KILL else None,metadata=meta()))
    r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,2,meta(),battlecry=False,deathrattle=False,choose_one=False))
    for cid,_ in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID,'p70-complete-finite-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid,w)for cid,w in members),complete=True))
    def fail(c):raise ResolutionError('P70 deliberate continuation failure')
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),)
    r.register_behavior(TEST+'fail',fail);r.register_behavior(TEST+'reenter',reenter)
    if mode:
        event={'summon':'minion_summoned','transform':'transformed','buff':'stats_changed','armor':'armor_gained',
            'source_death':'battlecry_started'}[mode]
        def eligible(c):
            if mode=='armor':return c.event.player_id==1 and c.event.amount==5
            if mode=='source_death':return c.state.entities[c.event.source_id].card_id==MINDFLAYER
            e=c.state.entities[c.event.target_id]
            return e.controller==1 and e.card_id in({'summon':(M2,M6),'transform':(M2,),'buff':(TINY,)}[mode])
        def wait(c):
            options=[ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))]
            if mode=='summon':options.append(ChoiceOption('kill','Destroy original delivery',(Destroy(c.event.target_id,c.source_id),)))
            if mode=='source_death':options.append(ChoiceOption('kill','Destroy original source',(Destroy(c.event.source_id,c.source_id),)))
            if mode in('buff','transform'):
                cid=SHEEP if mode=='buff'else M2
                target=next(i for i in reversed(c.state.players[1].board)if c.state.entities[i].card_id==cid)
                options.append(ChoiceOption('cycle','Later recipient leaves and reenters',(
                    ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target))))
            if mode=='armor':
                ref=next(CardReference.capture(c.state.entities[i])for i in c.state.players[1].hand if c.state.entities[i].card_id==SHEEP)
                options.append(ChoiceOption('discard','Discard other Rafaam',(DiscardCard(ref,c.source_id),)))
            return(RequestChoice(1,tuple(options),c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'wait',wait)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=40,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),),metadata=meta()))
    r.validate();return r


@lru_cache(maxsize=None)
def fixture_registry(mode,members,role,pin):
    if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Incomplete immutable fixture key')
    r=registry(mode,members);r.freeze();return r


class SimpleFollowupP70Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=(YETI,)*12,enemy_hand=(),mode=None,members=MEMBERS,active=1,cap=None,limit=7):
        self.config=mode,members
        if mode:enemy=(WATCH,)+enemy
        return Game.from_scenario(Scenario((PlayerSetup('HERO_10',hand=hand,board=board,deck=deck,
            mana=40,max_mana=40,mana_cap=40,hand_cap=cap),PlayerSetup('HERO_10',hand=enemy_hand,
            board=enemy,deck=(YETI,)*12,mana=40,max_mana=40,mana_cap=40)),active_player=active,
            seed=7070,generation_context=CONTEXT),fixture_registry(mode,members,'writer',SOURCE_PIN),ruleset=Ruleset(max_board=limit))
    def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,pid=1):
        e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,
            position=len(g.state.players[pid].board)if e.kind in(CardType.MINION,CardType.LOCATION)else None));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def keep(self,g):
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.REWIND);self.choose(g,'keep')
    def count(self,g,cid,zone='hand',pid=1):return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[pid],zone))
    def hero(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id]
    def portable(self,g):
        r=fixture_registry(*self.config,'reader',SOURCE_PIN);self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint())
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,r)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for pid in(1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in('rng_state','resolution_frame','behavior_id','source_allocation','card_summon_history','original_entities'):
                self.assertNotIn('"'+key+'"',public)
        return other






    def test_b0_bribe_both_players_summon_then_entire_original_own_board_transforms(self):
        g=self.game((BRIBE,),board=(M1,));old=self.first(g,M1,'board').id;source=self.play(g,BRIBE)
        self.assertEqual(g.state.entities[old].card_id,M2);self.assertEqual(self.count(g,M3,'board'),2)
        self.assertEqual(self.count(g,M2,'board',2),2);self.assertEqual(len(g.state.cast_history),1)
        self.assertTrue(all(r.spec.cause.source.entity_id==source for r in g.state.pool_summon_history));self.portable(g)

    def test_b1_bribe_summon_wait_restores_and_future_transform_captures_actual_remaining_board(self):
        g=self.game((BRIBE,),mode='summon');self.play(g,BRIBE);self.portable(g);self.choose(g,'kill')
        self.assertEqual(self.count(g,M3,'board'),1);self.assertEqual(self.count(g,M2,'board',2),2);self.portable(g)

    def test_b2_bribe_later_original_transform_recipient_reentry_is_not_adopted(self):
        g=self.game((BRIBE,),board=(M1,),mode='transform');self.play(g,BRIBE)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g,'cycle')
        self.assertEqual(self.count(g,M2,'board'),2);self.assertEqual(self.count(g,M3,'board'),1);self.portable(g)

    def test_b3_unknown_eligible_two_cost_pool_rolls_back_even_with_both_boards_full(self):
        g=self.game((BRIBE,),board=(M1,)*7,enemy=(M1,)*7,members=((UNKNOWN,1),));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BRIBE)
        self.assertEqual(g.snapshot(),saved)

    def test_b4_both_full_boards_keep_physical_occupants_and_transform_only_own_seven(self):
        g=self.game((BRIBE,),board=(M1,)*7,enemy=(M1,)*7);own=set(g.state.players[1].board);other=set(g.state.players[2].board)
        self.play(g,BRIBE);self.assertEqual(set(g.state.players[1].board),own);self.assertEqual(set(g.state.players[2].board),other)
        self.assertEqual(self.count(g,M2,'board'),7);self.assertEqual(self.count(g,M1,'board',2),7);self.portable(g)

    def test_c0_tiny_battlecry_and_deathrattle_draw_original_family_entities_including_sheep(self):
        g=self.game((TINY,KILL),deck=(SHEEP,GREEN,M2));originals=set(g.state.players[1].deck)
        source=self.play(g,TINY);self.play(g,KILL,source)
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].hand},{SHEEP,GREEN})
        self.assertTrue(set(g.state.players[1].hand)<=originals);self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_c1_tiny_empty_named_pool_skips_and_full_hand_draw_burns_without_substitution(self):
        g=self.game((TINY,),deck=(M2,));self.play(g,TINY);self.assertFalse(g.state.draw_history);self.assertEqual(self.hero(g).health,30);self.portable(g)
        g=self.game((NOOP,NOOP),board=(TINY,),deck=(SHEEP,),enemy_hand=(KILL,),active=2,cap=2)
        self.play(g,KILL,self.first(g,TINY,'board').id,pid=2)
        self.assertEqual(self.count(g,SHEEP),0);self.assertFalse(g.state.players[1].deck)
        self.assertTrue(any(e.kind=='card_burned'for e in g.events));self.portable(g)

    def test_c2_green_exact_family_hand_board_not_self_deck_enemy_or_named_impostor(self):
        g=self.game((GREEN,GREEN,TINY),board=(TINY,SHEEP,FAKE),enemy=(TINY,),deck=(GREEN,))
        source=self.play(g,GREEN);self.assertEqual(g.state.entities[source].attack,2)
        for cid in(TINY,GREEN):self.assertEqual(self.first(g,cid).attack,3 if cid==TINY else 4)
        self.assertEqual(self.first(g,TINY,'board').attack,3);self.assertEqual(self.first(g,SHEEP,'board').attack,3)
        self.assertEqual(self.first(g,FAKE,'board').attack,1);self.assertEqual(self.first(g,TINY,'board',2).attack,1)
        self.assertEqual(self.first(g,GREEN,'deck').attack,2);self.portable(g)

    def test_c3_green_later_captured_recipient_reentry_skips_delayed_buff(self):
        g=self.game((GREEN,),board=(TINY,SHEEP),mode='buff');self.play(g,GREEN);self.portable(g);self.choose(g,'cycle')
        self.assertEqual(self.first(g,TINY,'board').attack,3);self.assertEqual(self.first(g,SHEEP,'board').attack,1);self.portable(g)

    def test_d0_explorer_native_sampled_choice_takes_one_original_deck_card_without_draw(self):
        g=self.game((EXPLORER,),deck=(TINY,SHEEP,GREEN,M2,FAKE));originals=set(g.state.players[1].deck)
        self.play(g,EXPLORER);q=g.state.pending_choice;self.assertEqual(len(q.options),3)
        self.assertEqual({o.card_id for o in q.options},{TINY,SHEEP,GREEN});self.portable(g);self.choose(g,q.options[0].id)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertTrue(set(g.state.players[1].hand)<=originals)
        self.assertFalse(g.state.draw_history);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_d1_explorer_no_named_cards_skips_without_fallback_or_exposing_nonfamily_cards(self):
        g=self.game((EXPLORER,),deck=(M2,FAKE));old=tuple(g.state.players[1].deck);self.play(g,EXPLORER)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.players[1].hand)
        self.assertEqual(tuple(g.state.players[1].deck),old);self.assertFalse(g.state.draw_history);self.portable(g)

    def test_e0_warchief_two_separate_armor_operations_and_post_first_reaction_hand_condition(self):
        g=self.game((WARCHIEF,SHEEP));self.play(g,WARCHIEF);self.assertEqual(self.hero(g).armor,10)
        self.assertEqual([e.amount for e in g.events if e.kind=='armor_gained'],[5,5]);self.portable(g)
        g=self.game((WARCHIEF,SHEEP),mode='armor');self.play(g,WARCHIEF);self.assertEqual(self.hero(g).armor,5)
        self.portable(g);self.choose(g,'discard');self.assertEqual(self.hero(g).armor,5);self.assertEqual(self.count(g,SHEEP),0);self.portable(g)

    def test_e1_mindflayer_current_copy_retains_green_buff_without_battlecry_recursion(self):
        g=self.game((GREEN,MINDFLAYER,SHEEP));self.play(g,GREEN);self.play(g,MINDFLAYER)
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==MINDFLAYER]
        self.assertEqual([(e.attack,e.health)for e in bodies],[(9,9),(9,9)]);self.assertEqual(len(g.state.card_summon_history),1);self.portable(g)
        g=self.game((MINDFLAYER,));self.play(g,MINDFLAYER);self.assertEqual(self.count(g,MINDFLAYER,'board'),1);self.assertFalse(g.state.card_summon_history);self.portable(g)

    def test_e2_mindflayer_full_board_keeps_original_and_native_unselected_copy_plan(self):
        g=self.game((MINDFLAYER,SHEEP),board=(M1,)*6);self.play(g,MINDFLAYER)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.count(g,MINDFLAYER,'board'),1)
        self.assertIsNone(g.state.card_summon_history[0].selected);self.portable(g)

    def test_e3_mindflayer_source_destroyed_before_body_skips_copy_without_rebinding(self):
        g=self.game((MINDFLAYER,SHEEP),mode='source_death');source=self.play(g,MINDFLAYER)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g,'kill')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.count(g,MINDFLAYER,'board'),0)
        self.assertFalse(g.state.card_summon_history);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_f0_calamitous_native_six_damage_both_boards_excludes_all_real_rafaams(self):
        g=self.game((CALAMITOUS,),board=(M2,TINY),enemy=(M3,SHEEP));self.play(g,CALAMITOUS)
        self.assertEqual(self.first(g,M2,'board').health,1);self.assertEqual(self.first(g,M3,'board',2).health,3)
        self.assertEqual(self.first(g,TINY,'board').health,1);self.assertEqual(self.first(g,SHEEP,'board',2).health,1)
        self.assertEqual(self.first(g,CALAMITOUS,'board').health,6);self.portable(g)

    def test_f1_archmage_transforms_both_original_nonfamily_entities_to_actual_rafaam_sheep(self):
        g=self.game((ARCHMAGE,),board=(M2,TINY),enemy=(FAKE,SHEEP));friend=self.first(g,M2,'board').id;enemy=self.first(g,FAKE,'board',2).id
        self.play(g,ARCHMAGE)
        for eid in(friend,enemy):self.assertEqual((g.state.entities[eid].card_id,g.state.entities[eid].attack,g.state.entities[eid].health),(SHEEP,1,1))
        self.assertEqual(self.count(g,SHEEP,'board',2),2);self.assertEqual(self.count(g,TINY,'board'),1);self.portable(g)

    def test_g0_murloc_native_one_use_named_cost_ignores_other_cards_then_pays_and_consumes_once(self):
        g=self.game((MURLOC,M2,MINDFLAYER,SHEEP));self.play(g,MURLOC)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.first(g,M2)).amount,2);self.play(g,M2)
        self.assertEqual(len(g.state.players[1].cost_modifiers),1)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.first(g,MINDFLAYER)).amount,4);self.play(g,MINDFLAYER)
        self.assertFalse(g.state.players[1].cost_modifiers);self.assertEqual(g.state.players[1].mana,31)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.first(g,SHEEP)).amount,1);self.portable(g)

    def test_g1_murloc_exact_eleven_identity_filter_keeps_zero_floor_and_ignores_named_impostor(self):
        g=self.game((MURLOC,SHEEP,FAKE));self.play(g,MURLOC)
        self.assertEqual(set(g.state.players[1].cost_modifiers[0].spec.card_ids),set(FAMILY))
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.first(g,FAKE)).amount,2)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.first(g,SHEEP)).amount,0);self.play(g,SHEEP)
        self.assertEqual(g.state.players[1].mana,37);self.assertFalse(g.state.players[1].cost_modifiers);self.portable(g)

    def test_z0_complete_sources_and_registration_work_before_or_after_central_assembly(self):
        from tools.card_batch import check_face
        d=load_batch();self.assertEqual(len(d['official_observations']),26);self.assertEqual(len(d['exact_parent_child_links']),20)
        raws={x['record']['id']:x['record']for k in('cards','dependencies','evidence_only')for x in d[k]}
        for o in d['official_observations']:check_face(raws[o['card_id']],o['face'],o['locale'],d['display_normalizations'].get(o['card_id']))
        before,after=build_registry(),batch_registry()
        for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
        for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards));self.assertTrue(set(ROOTS)<=set(after.cards))
        self.assertEqual(before.fabled,after.fabled);self.assertEqual(before.generation_families,after.generation_families)
        for cid in(PARENT,GIANT,MULTIVERSE):self.assertEqual(cid in after.cards,cid in before.cards)
        self.assertEqual(set(d['rafaam_family_ids']),set(FAMILY));self.assertIn(SHEEP,FAMILY)


if __name__=='__main__':unittest.main()
