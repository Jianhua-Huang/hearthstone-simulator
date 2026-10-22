"""Explicit postlaunch printed editions coexist with preserved prelaunch evidence."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.time_lord_nozdormu_card import (CARD,BODY,PRELAUNCH_POLICY,POSTLAUNCH_POLICY,
    POSTLAUNCH_BODY,POSTLAUNCH_HASH,load_batch,load_postlaunch_policy,register_time_lord_nozdormu_card)
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import ChoiceOption,GainArmor,InvokeBehavior,RequestChoice,Summon,Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import ReplayError,build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import sha

NEW,SPELL,WEAPON,LOCATION,TOKEN='BE_207','BE_842','BE_000','BE_251','BE_349t'
OLD,JAIL,MINI='CORE_CS2_182','JAIL_202','CAP_006'
P='fixture.cn37_postlaunch.'
WATCH,FAULT,UNKNOWN=(P+x for x in('watch','fault','unknown'))


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer',policy=POSTLAUNCH_POLICY):
    r=build_registry()
    if policy==PRELAUNCH_POLICY:
        old=r._cards.pop(CARD);r._pool_cards.pop(CARD);r._behaviors.pop(old.dormant_triggers[0].behavior_id)
        register_time_lord_nozdormu_card(r,policy_id=PRELAUNCH_POLICY)
    elif policy!=POSTLAUNCH_POLICY:raise ValueError('Unknown fixture target')
    # Deliberately the same version for both targets: the policy itself must bind.
    r._version+='.k411.'+mode
    def fault(c):raise ResolutionError('postlaunch fixed policy deliberate failure')
    r.register_behavior(FAULT,fault)
    r.register_behavior(UNKNOWN,lambda c:(GainArmor(c.player_id,3),))
    r.register_card(CardDefinition(UNKNOWN,UNKNOWN,CardType.SPELL,cost=1,on_play=UNKNOWN))
    if mode!='normal':
        event=('minion_summoned'if mode in('forward','reverse')else
            'turn_ended'if mode in('auto','summon')else'dormancy_progressed'if mode=='after'else'card_played')
        def watch(c):
            if c.event.player_id!=c.player_id:return()
            if mode=='auto':return(CastSpell(c.player_id,SPELL,c.source_id,
                target_id=c.state.players[3-c.player_id].hero_id,targeting='explicit'),)
            if mode=='summon':return(Summon(c.player_id,NEW),)
            if mode in('forward','reverse'):
                original,result=(NEW,OLD)if mode=='forward'else(OLD,NEW)
                target=c.state.entities.get(c.event.target_id)
                return(Transform(target.id,result),)if target is not None and target.card_id==original else()
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('fault','Fail',(
                GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,triggers=(TriggerSpec(event,WATCH),)))
    r.validate();return r


class CN37PostlaunchPrintedExpansionTests(unittest.TestCase):
    def game(self,hand=(),board=(CARD,),enemy_hand=(),mode='normal',seat=1,registry_override=None):
        self.mode=mode
        own=PlayerSetup('HERO_08',hand=hand,board=(*((WATCH,)if mode!='normal'else()),*board),
            deck=(OLD,)*10,mana=40,max_mana=40,mana_cap=40)
        other=PlayerSetup('HERO_08',hand=enemy_hand,board=(OLD,),deck=(OLD,)*10,mana=40,max_mana=40,mana_cap=40)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=411),
            fixture(mode)if registry_override is None else registry_override)
    def source(self,g,pid=None):
        pid=g.state.active_player if pid is None else pid
        return next(g.state.entities[i]for i in g.state.players[pid].board if g.state.entities[i].card_id==CARD)
    def play(self,g,cid):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        target=g.state.players[3-pid].hero_id if cid in(SPELL,MINI)else None
        d=g.registry.card(cid);g.apply(PlayCard(pid,eid,target_id=target,
            position=len(g.state.players[pid].board)if d.kind in(CardType.MINION,CardType.LOCATION)else None));return eid
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry);saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def test_complete_original_inventory_and_full_cn_evidence_bind_one_explicit_postlaunch_policy(self):
        base=load_batch();policy=load_postlaunch_policy(base)
        self.assertEqual(base['latest_expansion']['card_set_id'],1988)
        self.assertEqual(policy['card_set_id'],1994);self.assertEqual(policy['name'],'黑暗帝国的统治')
        self.assertEqual(policy['printed_inventory_count'],23452)
        self.assertEqual(policy['printed_inventory_sha256'],canonical_digest(base['printed_card_sets']))
        evidence=policy['release_evidence'];root=Path(__file__).resolve().parents[1]
        self.assertEqual(sha(root/evidence['response_file']),evidence['response_sha256'])
        self.assertEqual(evidence['publication_date'],'2026-10-21')
        self.assertEqual(canonical_digest(policy),POSTLAUNCH_HASH)
        self.assertFalse(policy['formal_m0_complete']);self.assertFalse(policy['cn_timing_calibrated'])
        self.assertEqual(fixture().card(CARD).dormant_triggers[0].behavior_id,POSTLAUNCH_BODY)
        current=fixture().card(CARD);legacy=fixture(policy=PRELAUNCH_POLICY).card(CARD)
        self.assertEqual(replace(current,dormant_triggers=legacy.dormant_triggers),legacy)

    def test_current_minion_spell_weapon_location_and_noncollectible_each_count_then_awaken(self):
        g=self.game(hand=(NEW,SPELL,WEAPON,LOCATION,TOKEN));eid=self.source(g).id
        for cid,left in zip((NEW,SPELL,WEAPON,LOCATION),(4,3,2,1)):
            self.play(g,cid);self.assertEqual(self.source(g).dormancy.remaining_turns,left)
        self.assertFalse(g.registry.card(TOKEN).metadata.collectible);self.play(g,TOKEN)
        self.assertTrue(g.state.entities[eid].active);self.assertEqual(g.state.entities[eid].attack,8)
        self.assertEqual(len(g.state.play_history),5)

    def test_old_jail_miniset_and_core_plays_no_longer_advance_current_target(self):
        g=self.game(hand=(JAIL,MINI,OLD));base=load_batch()
        self.assertEqual(base['printed_card_sets'][MINI],1988)
        for cid in(JAIL,MINI,OLD):
            self.play(g,cid);self.assertEqual(self.source(g).dormancy.remaining_turns,5)

    def test_owner_and_second_seat_use_the_same_selected_current_expansion(self):
        g=self.game(enemy_hand=(NEW,));g.apply(EndTurn(1));self.play(g,NEW)
        self.assertEqual(self.source(g,1).dormancy.remaining_turns,5)
        g=self.game(hand=(NEW,),seat=2);self.play(g,NEW)
        self.assertEqual(self.source(g,2).dormancy.remaining_turns,4)

    def test_original_printed_edition_survives_physical_transform_in_both_directions(self):
        for mode,cid,actual,left in(('forward',NEW,OLD,4),('reverse',OLD,NEW,5)):
            with self.subTest(mode=mode):
                g=self.game(hand=(cid,),mode=mode);eid=self.play(g,cid)
                self.assertEqual(g.state.entities[eid].card_id,actual)
                self.assertEqual(g.state.play_history[-1].card_id,cid)
                self.assertEqual(self.source(g).dormancy.remaining_turns,left)

    def test_matching_automatic_cast_and_natural_summon_never_invent_a_hand_play(self):
        for mode in('auto','summon'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);g.apply(EndTurn(1))
                self.assertFalse(g.state.play_history);self.assertEqual(self.source(g,1).dormancy.remaining_turns,5)
                if mode=='auto':self.assertEqual(len(g.state.cast_history),1)
                else:self.assertTrue(any(g.state.entities[i].card_id==NEW for i in g.state.players[1].board))

    def test_countered_completed_current_spell_still_counts_as_one_real_play(self):
        g=self.game(hand=(SPELL,),enemy_hand=('CORE_EX1_287',))
        g.apply(EndTurn(1));self.play(g,'CORE_EX1_287');g.apply(EndTurn(2));self.play(g,SPELL)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.source(g).dormancy.remaining_turns,3)

    def test_wait_before_and_after_progress_restore_exact_policy_and_failed_resume_is_atomic(self):
        for mode,left in(('before',5),('after',4)):
            with self.subTest(mode=mode):
                g=self.game(hand=(NEW,),mode=mode);self.play(g,NEW)
                self.assertEqual(self.source(g).dormancy.remaining_turns,left);saved=self.portable(g)
                with self.assertRaisesRegex(ResolutionError,'fixed policy deliberate failure'):self.choose(g,'fault')
                self.assertEqual(g.snapshot(),saved);self.choose(g,'ok')
                self.assertEqual(self.source(g).dormancy.remaining_turns,4)
                public=json.dumps(g.observe(2),ensure_ascii=False)
                for hidden in('printed_card_sets','release_evidence','source_record_count',POSTLAUNCH_HASH):self.assertNotIn(hidden,public)

    def test_same_content_version_cannot_hide_policy_difference_in_snapshot_or_replay(self):
        post=fixture.__wrapped__();pre=fixture.__wrapped__(policy=PRELAUNCH_POLICY)
        self.assertEqual(post.version,pre.version);self.assertNotEqual(post.fingerprint(),pre.fingerprint())
        self.assertEqual(pre.card(CARD).dormant_triggers[0].behavior_id,BODY)
        self.assertIn(POSTLAUNCH_HASH,post.card(CARD).dormant_triggers[0].behavior_id)
        g=self.game(hand=(NEW,),registry_override=post);self.play(g,NEW)
        with self.assertRaises(SnapshotError):Game.from_snapshot(g.snapshot(),pre)
        with self.assertRaises(ReplayError):replay(build_replay(g),pre)

    def test_unknown_raw_and_assembled_editions_remain_explicit_and_rollback_the_play(self):
        derived=AssembleRecipe('CORE_EX1_096','CORE_GVG_114','bottom').card_id
        for cid in(UNKNOWN,derived):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,));saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved)

    def test_bad_policy_inventory_set_evidence_and_unknown_selector_cannot_partially_install(self):
        base=load_batch();valid=load_postlaunch_policy(base);r=build_registry();fp=r.fingerprint()
        with self.assertRaises(TargetValidationError):register_time_lord_nozdormu_card(r,policy_id='machine-date-latest')
        self.assertEqual(r.fingerprint(),fp)
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'bad.json'
            for kind in('inventory','set'):
                bad=deepcopy(valid)
                if kind=='inventory':bad['printed_inventory_sha256']='0'*64
                else:bad['set_id_evidence']['entry']['name']='Unreviewed set'
                path.write_text(json.dumps(bad),encoding='utf-8')
                with patch('hs_sim.cards.time_lord_nozdormu_card.POSTLAUNCH_PATH',path),patch(
                        'hs_sim.cards.time_lord_nozdormu_card.POSTLAUNCH_HASH',canonical_digest(bad)):
                    with self.assertRaises(TargetValidationError):load_postlaunch_policy(base)
                    with self.assertRaises(TargetValidationError):register_time_lord_nozdormu_card(r,policy_id=POSTLAUNCH_POLICY)
                    self.assertEqual(r.fingerprint(),fp)

    def test_multiple_current_timelords_and_natural_clock_keep_independent_original_instances(self):
        g=self.game(hand=(NEW,),board=(CARD,CARD));ids=list(g.state.players[1].board);self.play(g,NEW)
        self.assertEqual([g.state.entities[i].dormancy.remaining_turns for i in ids],[4,4])
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual([g.state.entities[i].dormancy.remaining_turns for i in ids],[3,3])


if __name__=='__main__':unittest.main()
