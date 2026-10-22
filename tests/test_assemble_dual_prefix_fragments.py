"""Actual dual text uses independent native Battlecry and Deathrattle windows."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_dual_prefix_fragments import SOURCES,load_batch
from hs_sim.cards.native_assemble_entry_cards import FLESH,POOL_ID
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.engine import CardDefinition,CardType,Game,PlayCard,PlayerSetup,Scenario,SelectChoice
from hs_sim.engine.assemble_faces import (AssembleRecipe,AssemblePrefix,AssembleSuffix,DUAL_TIMING,
    compatible,printed_face)
from hs_sim.engine.assemble_offers import ResolveAssemble,recipe_options
from hs_sim.engine.effects import ChangeControl
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import EndTurnSpec
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import (fixture as base_fixture,DECK,KILL,COPY,MUTE,STEAL,
    WATCH,DRAGON,S1,S2,S3,META,TAELAN,CURATOR,HAWK,COIN)

TOLVIR,UNDERKING,OLD_UNDERKING,BARON=SOURCES
LOOT,BEETLE,DRAIN,TARGET,BRANN='CORE_EX1_096','CORE_LOOT_413','CORE_GIL_622','CORE_UNG_084','LOE_077'
RAISE,GIVE='fixture.dual_prefix.raise','fixture.dual_prefix.give'
CTX=GenerationContext('k396-dual-native-fixture','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__();r._version+='.k396.'+mode
    for cid,body in ((RAISE,lambda c:(ResurrectMinion(c.player_id,c.state.death_history[-1].id,source_id=c.source_id),)),
            (GIVE,lambda c:(ChangeControl(c.target_id,3-c.player_id),))):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            requires_target=cid==GIVE))
    members=(PoolMember(TOLVIR,1000),PoolMember(LOOT),PoolMember(DRAIN))if mode=='flesh'else tuple(
        PoolMember(cid)for cid in(TOLVIR,TAELAN,CURATOR))
    if mode=='missing':r._assemble_templates.pop(TOLVIR)
    if mode!='no_pool':r.register_pool(PoolDefinition(POOL_ID,'three-real-dual-fixture-v1',CTX.target_id,
        CTX.mode,members,complete=True))
    return r


class AssembleDualPrefixTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=DECK,mode='normal'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(S2,S3)+(COIN,)*10,mana=30,max_mana=30,mana_cap=30)),
            seed=396,generation_context=CTX),fixture(mode))

    def play(self,g,cid,target=None):
        pid=g.state.active_player
        source=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,source,target_id=target));return source

    def drawn(self,g,pid=1):return [r for r in g.state.draw_history if r.player_id==pid]

    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def offer(self,g):return next(e.offer for o in g._frame.options for e in o.effects if isinstance(e,ResolveAssemble))

    def choose_card(self,g,cid):
        q=g.state.pending_choice;option=next(o for o in q.options if o.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(option.id,)))

    def test_four_complete_sources_eight_primary_faces_and_both_original_callback_identities(self):
        data=load_batch();r=build_registry();rows={x['record']['id']:x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows),SOURCES);self.assertEqual(len(data['official_observations']),8)
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale'])
            path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']
                if x['id']==row['record']['dbf_id']],[obs['face']])
        for cid,row in rows.items():
            d=r.card(cid);t=r.assemble_templates[cid]
            self.assertEqual(canonical_digest(asdict(d)),row['definition_sha256'])
            self.assertEqual(t.prefix.timing,DUAL_TIMING)
            self.assertEqual(printed_face(d,t.prefix,t.suffix,cid),d)
            self.assertEqual(t.suffix.behavior_id,d.battlecry)
            self.assertEqual(t.suffix.deathrattle_behavior_id or t.suffix.behavior_id,d.deathrattle)
        self.assertNotEqual(r.card(UNDERKING).battlecry,r.card(UNDERKING).deathrattle)
        with self.assertRaises(UnsupportedDefinitionError):r.pool(POOL_ID,CTX)

    def test_real_mismatch_assembly_preserves_both_windows_and_pays_primary_cost_once(self):
        g=self.game(hand=(MISMATCH,KILL),deck=(DRAGON,DRAGON)+(COIN,)*10)
        self.play(g,MISMATCH);offer=self.offer(g)
        self.assertEqual(offer.primary_card_id,TOLVIR);self.assertEqual(set(offer.secondary_card_ids),{TAELAN,CURATOR})
        cid=AssembleRecipe(TOLVIR,TAELAN,'bottom').card_id;self.choose_card(g,cid)
        before=g.state.players[1].mana;source=self.play(g,cid)
        self.assertEqual(g.state.players[1].mana,before-g.registry.card(TOLVIR).cost)
        self.assertEqual([x.card_id for x in self.drawn(g)],[DRAGON])
        self.play(g,KILL,source);self.assertEqual([x.card_id for x in self.drawn(g)],[DRAGON,DRAGON])
        self.assertEqual(len({x.entity_id for x in self.drawn(g)}),2);self.portable(g)

    def test_real_top_replacement_removes_battlecry_without_losing_the_original_deathrattle(self):
        g=self.game(hand=(MISMATCH,KILL));self.play(g,MISMATCH)
        cid=AssembleRecipe(TOLVIR,TAELAN,'top').card_id;self.choose_card(g,cid);source=self.play(g,cid)
        self.assertIsNone(g.registry.card(cid).battlecry)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.play(g,KILL,source);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3)
        self.assertFalse(self.drawn(g))

    def test_real_flesh_deathrattle_filter_includes_the_dual_prefix_and_preserves_accepted_rng(self):
        g=self.game(hand=(FLESH,KILL),mode='flesh');self.play(g,FLESH);offer=self.offer(g)
        self.assertEqual(set(offer.primary_candidates),{TOLVIR,LOOT});self.assertEqual(offer.primary_card_id,TOLVIR)
        self.assertNotIn(DRAIN,offer.primary_candidates);self.portable(g)
        cid=AssembleRecipe(TOLVIR,LOOT,'bottom').card_id;self.choose_card(g,cid)
        source=self.play(g,cid);self.play(g,KILL,source)
        self.assertEqual(len(self.drawn(g)),2)
        self.assertEqual(g.state.card_discovery_history,[])
        self.assertEqual(offer.rng_after,g._rng.getstate())

    def test_each_real_dual_prefix_executes_one_paid_battlecry_and_one_natural_deathrattle(self):
        for donor in SOURCES:
            with self.subTest(donor=donor):
                cid=AssembleRecipe(LOOT,donor,'top').card_id
                g=self.game(hand=(cid,KILL));source=self.play(g,cid)
                self.assertEqual(len(self.drawn(g)),1)
                self.assertEqual(len([b for b in g.state.battlecry_history if b.card_id==cid]),1)
                self.play(g,KILL,source);self.assertEqual(len(self.drawn(g)),2)

    def test_each_dual_source_suffix_selects_its_real_single_battlecry_or_deathrattle_entry(self):
        for donor in SOURCES:
            for timing,primary in (('battlecry',HAWK),('deathrattle',LOOT)):
                with self.subTest(donor=donor,timing=timing):
                    cid=AssembleRecipe(primary,donor,'bottom').card_id
                    g=self.game(hand=(cid,KILL));d=g.registry.card(cid)
                    self.assertEqual(getattr(d,timing),getattr(g.registry.card(donor),timing))
                    source=self.play(g,cid)
                    if timing=='deathrattle':
                        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
                        self.assertFalse(self.drawn(g));self.play(g,KILL,source)
                    self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,
                        3 if donor==TOLVIR else 6 if donor in(UNDERKING,OLD_UNDERKING)else 0)
                    self.assertEqual(len(self.drawn(g)),1 if donor==BARON else 0)

    def test_bronzebeard_repeats_only_the_battlecry_not_the_future_natural_deathrattle(self):
        cid=AssembleRecipe(LOOT,TOLVIR,'top').card_id
        g=self.game(hand=(cid,KILL),board=(BRANN,));source=self.play(g,cid)
        self.assertEqual(len(self.drawn(g)),2)
        self.assertEqual(len([b for b in g.state.battlecry_history if b.card_id==cid]),2)
        self.play(g,KILL,source);self.assertEqual(len(self.drawn(g)),3)

    def test_current_copy_and_real_resurrection_do_not_reexecute_the_battlecry(self):
        cid=AssembleRecipe(LOOT,TOLVIR,'top').card_id
        g=self.game(hand=(cid,COPY,KILL,RAISE,KILL));source=self.play(g,cid);self.play(g,COPY,source)
        self.assertEqual(len(self.drawn(g)),1)
        clone=next(i for i in g.state.players[1].board if i!=source);self.play(g,KILL,clone)
        self.assertEqual(len(self.drawn(g)),2);self.play(g,RAISE)
        self.assertEqual(len(self.drawn(g)),2)
        returned=next(i for i in g.state.players[1].board if i!=source);self.play(g,KILL,returned)
        self.assertEqual(len(self.drawn(g)),3)

    def test_silence_removes_the_remaining_deathrattle_after_a_completed_battlecry(self):
        cid=AssembleRecipe(LOOT,TOLVIR,'top').card_id
        g=self.game(hand=(cid,MUTE,KILL));source=self.play(g,cid)
        self.play(g,MUTE,source);self.play(g,KILL,source)
        self.assertEqual(len(self.drawn(g)),1)

    def test_control_change_preserves_completed_battlecry_but_changes_deathrattle_receiver(self):
        cid=AssembleRecipe(LOOT,TOLVIR,'top').card_id
        g=self.game(hand=(cid,GIVE,KILL));source=self.play(g,cid)
        self.play(g,GIVE,source);self.play(g,KILL,source)
        self.assertEqual(len(self.drawn(g)),1);self.assertEqual([x.card_id for x in self.drawn(g,2)],[S2])

    def test_both_native_windows_restore_replay_and_failed_resume_keeps_the_original_boundary(self):
        cid=AssembleRecipe(LOOT,TOLVIR,'top').card_id
        g=self.game(hand=(cid,KILL),board=(WATCH,));source=self.play(g,cid)
        for phase in ('battlecry','deathrattle'):
            if phase=='deathrattle':self.play(g,KILL,source)
            saved=self.portable(g);q=g.state.pending_choice;self.assertIsNotNone(q)
            with self.assertRaisesRegex(ResolutionError,'assembled draw observer fault'):
                g.apply(SelectChoice(q.player_id,q.id,('fault',)))
            self.assertEqual(g.snapshot(),saved);g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(len(self.drawn(g)),2);self.portable(g)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for name in ('deathrattle_behavior_id','definition_sha256','source_guard'):
                self.assertNotIn('"'+name+'"',public)

    def test_dual_timing_requires_both_compatibilities_and_never_turns_an_arrow_into_a_deathrattle(self):
        from hs_sim.engine.assembled_powers import passive_minion
        r=build_registry();target=r.assemble_templates[TARGET].suffix;dual=AssemblePrefix(DUAL_TIMING)
        self.assertFalse(compatible(dual,target))
        options=recipe_options(r,TOLVIR,TARGET);self.assertNotIn('bottom',[x[0]for x in options])
        with self.assertRaises(UnsupportedDefinitionError):r.card(AssembleRecipe(TOLVIR,TARGET,'bottom').card_id)
        with self.assertRaises(ValueError):passive_minion(r.card(AssembleRecipe(LOOT,TOLVIR,'top').card_id))
        with self.assertRaises(ValueError):AssemblePrefix(DUAL_TIMING,end_turn=EndTurnSpec())
        with self.assertRaises(ValueError):AssemblePrefix('battlecry_end_turn')
        with self.assertRaises(ValueError):AssembleSuffix('native.bc',('battlecry',),deathrattle_behavior_id='native.dr')
        with self.assertRaises(ValueError):AssembleSuffix('native.bc',('deathrattle',),
            deathrattle_behavior_id='assemble.owner_start:native.dr')

    def test_unknown_native_deathrattle_entry_is_rejected_before_registering_the_template(self):
        r=build_registry();t=r._assemble_templates.pop(UNDERKING)
        bad=replace(t,suffix=replace(t.suffix,deathrattle_behavior_id='fixture.dual_prefix.unknown'))
        with self.assertRaises(UnsupportedDefinitionError):r.register_assemble_template(bad)
        self.assertNotIn(UNDERKING,r.assemble_templates)

    def test_missing_source_template_or_domain_rolls_back_the_whole_paid_entry(self):
        for mode in ('missing','no_pool'):
            with self.subTest(mode=mode):
                g=self.game(hand=(MISMATCH,),mode=mode);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,MISMATCH)
                self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
