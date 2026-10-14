"""Necessary real sources, independent candidate inventory and composition (R-130)."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from hs_sim.targets import canonical_digest,load_baseline,TargetValidationError
from hs_sim.engine import (Game,Scenario,PlayerSetup,GenerationContext,CardDefinition,CardType,
    Keyword,TriggerSpec,PlayCard,EndTurn,SelectChoice,Zone,SpellRepeatSpec,RewindSpec,
    CounterMinion,CounterSpell,UnsupportedDefinitionError,ResolutionError)
from hs_sim.engine.effects import (Summon,Destroy,Silence,ChangeControl,CopyMinion,ReturnToHand,
    GainArmor,Damage,AddToHand,RequestChoice,ChoiceOption,InvokeBehavior)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.pools import PoolQuery,PoolMember,PoolCard,resolve_candidates
from hs_sim.engine.representative import (build_registry,COMBO_POOL_ID,COMBO_SOURCE_INVENTORY_HASH,
    CARD_LIMITATIONS,EXPECTED_CARD_HASHES,metadata_from_record)
from hs_sim.engine.replay import replay,build_replay

CONTEXT=GenerationContext('local-2026-09-23','experimental')
ROOT=Path(__file__).resolve().parents[1]


class ComboSourceTests(unittest.TestCase):
    def setUp(self):self.r=build_registry()
    def script(self,cid,fn):
        self.r.register_behavior(cid,fn);self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    def watch(self,cid,event,fn):
        self.r.register_behavior(cid,fn);self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,triggers=(TriggerSpec(event,cid),)))
    def game(self,hand=(),board=(),enemy=(),hero='HERO_03',context=CONTEXT):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=('CS2_182',)*5,mana=10,max_mana=10),
            PlayerSetup('HERO_01',board=enemy,deck=('CS2_182',)*5)),seed=89,generation_context=context),self.r)
    def play(self,g,cid,target=None):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,i,target));return i
    def choose(self,g,cid=None,option_id=None):
        c=g.state.pending_choice;o=next(o for o in c.options if (cid is None or o.card_id==cid) and (option_id is None or o.id==option_id))
        g.apply(SelectChoice(c.player_id,c.id,(o.id,)));return o.card_id
    def pause(self,c):return RequestChoice(c.player_id,(ChoiceOption('ok','OK',()),),source_id=c.source_id)
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def board(self,g,p=1):return [g.state.entities[i] for i in g.state.players[p].board]
    def mods(self,g):return g.state.players[1].combo_modifiers
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def cast_comet(self,g,cid='EX1_131'):
        self.play(g,'GDB_873');self.choose(g,cid)
    def pool(self,**kw):
        key=(COMBO_POOL_ID,CONTEXT.target_id,CONTEXT.mode)
        self.r._pools[key]=replace(self.r.pools[key],**kw)

    def test_sources_and_token_use_pinned_stats_and_explicit_scopes(self):
        s=self.r.card('TRL_092');self.assertEqual((s.cost,s.attack,s.health),(4,0,3))
        self.assertEqual(s.battlecry_repeats[0].kinds,(CardType.MINION,));self.assertEqual(s.combo_repeats[0].kinds,(CardType.MINION,))
        self.assertEqual(s.timed_keywords[0].keyword,Keyword.STEALTH)
        self.assertEqual((self.r.card('EX1_131').attack,self.r.card('EX1_131t').health),(3,1))
        for cid in ('TRL_092','GDB_873','EX1_131','EX1_131t'):
            self.assertIn(cid,EXPECTED_CARD_HASHES);self.assertIn('R-130',CARD_LIMITATIONS[cid])

    def test_raw_inventory_has_unimplemented_candidates_without_claiming_full_pool(self):
        inventory=json.loads((ROOT/'data/support/combo-source-inventory.json').read_text(encoding='utf-8'))
        self.assertEqual(canonical_digest(inventory),COMBO_SOURCE_INVENTORY_HASH)
        self.assertEqual(len(inventory['raw_combo_minions']),56);self.assertFalse(inventory['complete'])
        self.assertTrue(any(r['data']['id'] not in self.r.cards for r in inventory['raw_combo_minions']))
        self.assertEqual(len(inventory['experimental_pool']['members']),6)

    def test_pool_filter_excludes_spell_reference_keyword_and_token(self):
        values=resolve_candidates(self.r,CONTEXT,COMBO_POOL_ID,PoolQuery(kinds=(CardType.MINION,),collectible=True,keywords_all=(Keyword.COMBO,)))
        self.assertEqual([v.card_id for v in values],['EX1_131','EX1_134','EX1_613'])
        self.assertNotIn(Keyword.COMBO,self.r.pool_card('TRL_092').keywords)
        self.assertIn(Keyword.COMBO,self.r.pool_card('EX1_124').keywords)
        self.assertFalse(self.r.pool_card('EX1_131t').metadata.collectible)

    def test_tampered_frozen_inventory_rejected(self):
        original=Path.read_text
        def corrupt(path,*args,**kwargs):
            text=original(path,*args,**kwargs)
            return text.replace('representative-combo-minions-v1','changed-pool') if path.name=='combo-source-inventory.json' else text
        with patch.object(Path,'read_text',corrupt),self.assertRaisesRegex(TargetValidationError,'Combo source inventory'):build_registry()

    def test_added_eligible_unknown_candidate_is_not_silently_filtered(self):
        inventory=json.loads((ROOT/'data/support/combo-source-inventory.json').read_text(encoding='utf-8'))
        raw=next(r['data'] for r in inventory['raw_combo_minions'] if r['data']['id']=='AT_028')
        self.r.register_pool_card(PoolCard(raw['id'],CardType.MINION,raw['cost'],metadata_from_record(raw),keywords=(Keyword.COMBO,)))
        key=(COMBO_POOL_ID,CONTEXT.target_id,CONTEXT.mode)
        self.pool(members=(*self.r.pools[key].members,PoolMember(raw['id'])))
        g=self.game(hand=('GDB_873',));before=g.snapshot()
        with patch('hs_sim.engine.discovery.sample_candidates',side_effect=AssertionError('RNG must not run')):
            with self.assertRaisesRegex(ResolutionError,'AT_028'):self.play(g,'GDB_873')
        self.assertEqual(g.snapshot(),before)

    def test_no_formal_pool_or_context_does_not_fall_back_to_experiment(self):
        for context in (None,GenerationContext(CONTEXT.target_id,'standard'),GenerationContext(CONTEXT.target_id,'wild')):
            g=self.game(hand=('GDB_873',),context=context);before=g.snapshot()
            with self.assertRaises((ValueError,UnsupportedDefinitionError)):self.play(g,'GDB_873')
            self.assertEqual(g.snapshot(),before)

    def test_shark_hand_play_has_stealth_then_expires_without_losing_auras(self):
        g=self.game(hand=('TRL_092',));i=self.play(g,'TRL_092');self.assertIn(Keyword.STEALTH,g.state.entities[i].keywords)
        self.cycle(g);e=g.state.entities[i];self.assertNotIn(Keyword.STEALTH,e.keywords)
        self.assertEqual({a.kind for a in e.abilities},{'battlecry_repeat','combo_repeat'});self.check(g)

    def test_shark_summon_installs_timed_stealth_without_hand_play(self):
        self.script('summon',lambda c:[Summon(1,'TRL_092')]);g=self.game(hand=('summon',));self.play(g,'summon')
        self.assertIn(Keyword.STEALTH,self.board(g)[0].keywords);self.assertEqual(g.state.combo_history,[]);self.check(g)

    def test_shark_repeats_actual_summoning_combo(self):
        g=self.game(hand=('GAME_005','EX1_131'),board=('TRL_092',));self.play(g,'GAME_005');self.play(g,'EX1_131')
        self.assertEqual([e.card_id for e in self.board(g)],['TRL_092','EX1_131','EX1_131t','EX1_131t'])
        self.assertEqual(len(g.state.combo_history),2);self.assertEqual(len(g.state.play_history),2);self.check(g)

    def test_unprimed_defias_has_no_token_even_with_shark(self):
        g=self.game(hand=('EX1_131',),board=('TRL_092',));self.play(g,'EX1_131')
        self.assertEqual(len(self.board(g)),2);self.assertEqual(g.state.combo_history,[]);self.check(g)

    def test_repeated_summon_uses_live_capacity(self):
        g=self.game(hand=('GAME_005','EX1_131'),board=('TRL_092',)+('CS2_182',)*4)
        self.play(g,'GAME_005');self.play(g,'EX1_131');self.assertEqual(len(self.board(g)),7)
        self.assertEqual(sum(e.card_id=='EX1_131t' for e in self.board(g)),1)
        self.assertEqual(len(g.state.combo_history),2);self.assertEqual(sum(e.kind=='summon_failed' for e in g.events),1);self.check(g)

    def test_shark_damage_combo_and_original_target(self):
        g=self.game(hand=('GAME_005','EX1_134'),board=('TRL_092',));self.play(g,'GAME_005')
        self.play(g,'EX1_134',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24);self.check(g)

    def test_shark_and_brann_use_max_battlecry_count(self):
        g=self.game(hand=('LOE_029',),board=('TRL_092','LOE_077'));self.play(g,'LOE_029')
        self.choose(g);self.assertIsNotNone(g.state.pending_choice);self.choose(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.battlecry_history),2);self.check(g)

    def test_multiple_sharks_do_not_multiply_combo_count(self):
        g=self.game(hand=('GAME_005','EX1_131'),board=('TRL_092','TRL_092'));self.play(g,'GAME_005');self.play(g,'EX1_131')
        self.assertEqual(len(g.state.combo_history),2);self.check(g)

    def test_shark_does_not_repeat_weapon_battlecry_or_combo(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(1,1)])
        self.r.register_card(CardDefinition('weapon','weapon',CardType.WEAPON,attack=1,durability=2,
            battlecry='armor',combo='armor',keywords=(Keyword.COMBO,)))
        g=self.game(hand=('GAME_005','weapon'),board=('TRL_092',));self.play(g,'GAME_005');self.play(g,'weapon')
        self.assertEqual(self.armor(g),2);self.assertEqual((len(g.state.battlecry_history),len(g.state.combo_history)),(1,1));self.check(g)

    def test_shark_silence_dormancy_death_or_enemy_control_disable_auras(self):
        operations=(Silence,lambda i:MakeDormant(i,None),Destroy,lambda i:ChangeControl(i,2))
        for n,operation in enumerate(operations):self.script('disable'+str(n),lambda c,op=operation:[op(c.state.players[1].board[0])])
        for n in range(4):
            with self.subTest(n=n):
                g=self.game(hand=('disable'+str(n),'EX1_131'),board=('TRL_092',));self.play(g,'disable'+str(n));self.play(g,'EX1_131')
                self.assertEqual(len(g.state.combo_history),1);self.check(g)

    def test_real_shark_current_copy_keeps_deadline(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],2)])
        g=self.game(hand=('copy',),board=('TRL_092',));self.play(g,'copy')
        clocks=[next(a.keyword_expiry for a in self.board(g,p)[0].abilities if a.timed_keyword) for p in (1,2)]
        self.assertEqual(clocks[0],clocks[1]);self.cycle(g)
        self.assertNotIn(Keyword.STEALTH,self.board(g,2)[0].keywords);self.check(g)

    def test_comet_choice_is_private_and_policy_is_granted_after_delivery(self):
        g=self.game(hand=('GDB_873',));self.play(g,'GDB_873');self.assertEqual(self.mods(g),[])
        self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1});self.check(g)
        self.choose(g,'EX1_131');self.assertEqual(len(self.mods(g)),1)
        kinds=[e.kind for e in g.events];self.assertLess(kinds.index('card_added_to_hand'),kinds.index('combo_modifier_added'));self.check(g)

    def test_comet_discovery_paused_restore_delivers_once(self):
        g=self.game(hand=('GDB_873',));self.play(g,'GDB_873');restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match,'EX1_131');self.play(match,'EX1_131')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(sum(bool(r.modifiers) for r in g.state.combo_policy_receipts),1);self.check(g)

    def test_comet_policy_repeats_next_combo_only_once(self):
        g=self.game(hand=('GDB_873','EX1_134'));self.cast_comet(g);self.play(g,'EX1_131')
        self.play(g,'EX1_134',g.state.players[2].hero_id)
        self.assertEqual([b.plan.repetitions for b in g.state.combo_batches],[2,1]);self.assertEqual(self.mods(g),[]);self.check(g)

    def test_comet_policy_survives_turn_change_but_consumes_unprimed_card(self):
        g=self.game(hand=('GDB_873',));self.cast_comet(g);self.cycle(g)
        self.assertEqual(len(self.mods(g)),1);self.play(g,'EX1_131')
        self.assertEqual(self.mods(g),[]);self.assertEqual(g.state.combo_history,[])
        self.assertEqual(g.state.combo_policy_receipts[0].phase,'play');self.check(g)

    def test_noncombo_minion_and_combo_spell_do_not_consume_comet_policy(self):
        g=self.game(hand=('GDB_873','CS2_182','EX1_124'));self.cast_comet(g)
        self.play(g,'CS2_182');self.play(g,'EX1_124',g.state.players[2].hero_id)
        self.assertEqual(len(self.mods(g)),1);self.assertEqual([r for r in g.state.combo_policy_receipts if r.modifiers],[]);self.check(g)

    def test_weapon_combo_does_not_consume_comet_policy(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(1,1)])
        self.r.register_card(CardDefinition('weapon','weapon',CardType.WEAPON,attack=1,durability=2,
            combo='armor',keywords=(Keyword.COMBO,)))
        g=self.game(hand=('GDB_873','weapon'));self.cast_comet(g);self.play(g,'weapon')
        self.assertEqual(len(self.mods(g)),1);self.assertEqual(len(g.state.combo_history),1);self.check(g)

    def test_comet_policy_and_shark_overlap_by_maximum(self):
        g=self.game(hand=('GDB_873',),board=('TRL_092',));self.cast_comet(g);self.play(g,'EX1_131')
        self.assertEqual(len(g.state.combo_history),2);self.assertEqual(self.mods(g),[]);self.check(g)

    def test_two_comets_both_consume_without_multiplying(self):
        g=self.game(hand=('GDB_873','GDB_873'));self.cast_comet(g);self.cast_comet(g)
        self.assertEqual(len(self.mods(g)),2);self.play(g,'EX1_131')
        self.assertEqual(len(g.state.combo_history),2);self.assertEqual(self.mods(g),[])
        self.assertEqual(len(g.state.combo_policy_receipts[0].modifiers),2);self.check(g)

    def test_comet_countered_spell_never_discovers_or_grants(self):
        from hs_sim.engine.secrets import SetSecret
        self.script('arm',lambda c:[SetSecret(2,'EX1_287')])
        g=self.game(hand=('arm','GDB_873'));self.play(g,'arm');self.play(g,'GDB_873')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.mods(g),[]);self.check(g)

    def test_countered_next_combo_still_consumes_play_policy(self):
        self.watch('counter','minion_counter_check',lambda c:[CounterMinion(dict(c.event.data)['window_id'])])
        g=self.game(hand=('GDB_873',),enemy=('counter',));self.cast_comet(g);self.play(g,'EX1_131')
        self.assertEqual(self.mods(g),[]);self.assertEqual(g.state.combo_history,[]);self.assertTrue(g.state.play_history[-1].countered);self.check(g)

    def test_empty_eligible_pool_still_grants_next_policy(self):
        self.pool(members=(PoolMember('TRL_092'),PoolMember('EX1_124'),PoolMember('EX1_131t')))
        g=self.game(hand=('GDB_873',));self.play(g,'GDB_873');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_discovery_burn_still_grants_policy(self):
        self.watch('fill','choice_selected',lambda c:[AddToHand(1,'CS2_182')])
        g=self.game(hand=('GDB_873',)+('CS2_182',)*9,board=('fill',));self.cast_comet(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(self.mods(g)),1)
        self.assertEqual(sum(e.kind=='card_burned' for e in g.events),1);self.check(g)

    def test_delivery_reactions_happen_before_policy_grant(self):
        self.watch('observe','card_added_to_hand',lambda c:[GainArmor(1,1+len(c.state.players[1].combo_modifiers))])
        g=self.game(hand=('GDB_873',),board=('observe',));self.cast_comet(g)
        self.assertEqual(self.armor(g),1);self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_delivery_terminal_prevents_policy_grant(self):
        self.watch('lethal','card_added_to_hand',lambda c:[Damage(c.state.players[2].hero_id,100)])
        g=self.game(hand=('GDB_873',),board=('lethal',));self.cast_comet(g)
        self.assertEqual(g.state.winner,1);self.assertEqual(self.mods(g),[]);self.check(g)

    def test_delivery_failure_restores_pending_choice_without_grant(self):
        self.watch('fail','card_added_to_hand',lambda c:[Summon(1,'missing')])
        g=self.game(hand=('GDB_873',),board=('fail',));self.play(g,'GDB_873');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'missing'):self.choose(g,'EX1_131')
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.mods(g),[]);self.check(g)

    def test_foreign_hero_uses_explicit_keyword_pool_policy(self):
        g=self.game(hand=('GDB_873',),hero='HERO_08');self.cast_comet(g)
        self.assertEqual(len(self.mods(g)),1);self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].card_id,'EX1_131');self.check(g)

    def test_spell_repeat_discovers_twice_and_grants_separate_policies(self):
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=3,spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        g=self.game(hand=('GDB_873',),board=('repeat',));self.play(g,'GDB_873');self.choose(g,'EX1_131')
        self.assertEqual(len(self.mods(g)),1);self.assertIsNotNone(g.state.pending_choice);self.check(g)
        self.choose(g,'EX1_134');self.assertEqual(len(self.mods(g)),2);self.play(g,'EX1_131')
        self.assertEqual(self.mods(g),[]);self.assertEqual(len(g.state.combo_history),2);self.check(g)

    def test_actual_shark_comet_policy_with_retained_combo_results(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(1,1)])
        self.r.register_card(CardDefinition('rewind','rewind',CardType.MINION,health=3,combo='armor',
            keywords=(Keyword.COMBO,Keyword.REWIND),rewind=RewindSpec(1)))
        self.r.register_card(CardDefinition('retain','retain',CardType.MINION,health=3,retain_rewind_outcomes=True))
        g=self.game(hand=('GDB_873','rewind'),board=('TRL_092','retain'));self.cast_comet(g);self.play(g,'rewind')
        self.assertEqual(self.armor(g),4);self.assertEqual(sum(bool(r.modifiers) for r in g.state.combo_policy_receipts),1)
        self.assertEqual([b.repeat_index for b in g.state.combo_history],[1,2,1,2]);self.check(g)

    def test_independent_scarab_choices_restore_under_real_shark(self):
        g=self.game(hand=('LOE_029',),board=('TRL_092',));self.play(g,'LOE_029');self.choose(g)
        self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_card_source_policies_do_not_leak_inventory_or_internal_ids(self):
        g=self.game(hand=('GDB_873',));self.cast_comet(g);view=g.observe(2)
        row=view['players'][0]['combo_modifiers'][0]
        self.assertEqual(row['trigger'],'play');self.assertEqual(row['uses_remaining'],1)
        self.assertFalse({'source_id','source_card_id','id'}&row.keys())
        self.assertNotIn('raw_combo_minions',json.dumps(view));self.check(g)

    def test_native_source_example_restores_and_fills_board_without_overflow(self):
        from examples.combo_sources import run
        g,s=run();self.assertEqual(s['schema_version'],266)
        self.assertEqual((len(g.history),len(g.state.combo_history),len(g.state.battlecry_history)),(12,6,2))


if __name__=='__main__':unittest.main()
