"""Real native hand targets, random removal and new-carrier health semantics."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_native_buffs_removal_health_fragments import SOURCES,load_batch,register_assemble_native_buffs_removal_health_fragments
from hs_sim.cards.native_assemble_entry_cards import FETCHER,NURTURER,POOL_ID
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import ChoiceOption,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import Keyword
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import (fixture as base_fixture,META,DECK,COIN,UNIT,KILL,MUTE,COPY,BOUNCE,STEAL,WOUND)

BUFF,STATUE,TAUNT_BUFF,BOMB,SELF,OTHERS=SOURCES
FLY,LOOT,CURATOR,CAIRNE,EMBER,VULGAR='CORE_UNG_809','CORE_EX1_096','CORE_KAR_061','CORE_EX1_110','TLC_249','CORE_LOOT_013'
P='fixture.assemble_native_buffs_removal_health.'
BONUS,WATCH,FAULT=(P+x for x in ('bonus','watch','fault'))
CTX=GenerationContext('k400-reviewed-native-effect-fixture','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__();r._version+='.k400.'+mode
    r.register_card(CardDefinition(BONUS,BONUS,CardType.MINION,health=20,spell_damage=10,metadata=META))
    def fault(c):raise ResolutionError('deliberate native effect assembly observer fault')
    r.register_behavior(FAULT,fault)
    def watch(c):
        hit=c.health_result
        if hit is None or not (hit.source_card_id or '').startswith('assemble:') or hit.damage_dealt<=0:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('health_resolved',WATCH),)))
    members=(TAUNT_BUFF,CURATOR,CAIRNE)if mode=='fetcher'else (BOMB,OTHERS,CAIRNE)if mode=='mismatch'else (
        SELF,STATUE,OTHERS)if mode=='mismatch_self'else (EMBER,BUFF,LOOT)
    if mode=='missing':r._assemble_templates.pop(BUFF)
    if mode!='no_pool':
        r.register_pool(PoolDefinition(POOL_ID,'three-real-native-effects-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(x)for x in members),complete=True))
    return r


class AssembleNativeBuffRemovalHealthTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode='normal',hero='HERO_04'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),
            seed=400,generation_context=CTX),fixture(mode))

    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target));return eid

    def stored(self,g,cid):return next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
    def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
    def rows(self,g,cid):return [health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_card_id==cid]

    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def choose(self,g,primary,secondary,half):
        cid=AssembleRecipe(primary,secondary,half).card_id;q=g.state.pending_choice
        option=next(x for x in q.options if x.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(option.id,)));return cid

    def test_six_complete_sources_twelve_whole_primary_faces_and_unchanged_original_definitions(self):
        data=load_batch();r=build_registry();rows={x['record']['id']:x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows),SOURCES);self.assertEqual(len(data['official_observations']),12);seen=set()
        self.assertEqual(sha(Path(data['source']['file'])),data['source']['sha256'])
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale'])
            path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
            seen.add((obs['card_id'],obs['locale']))
        self.assertEqual(seen,{(cid,loc)for cid in SOURCES for loc in ('zh_CN','en_US')})
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        self.assertFalse(data['experimental_policy']['formal_pool_installed'])
        with self.assertRaises(UnsupportedDefinitionError):r.pool(POOL_ID,CTX)

    def test_every_halves_reconstruct_whole_sources_and_keep_the_primary_header(self):
        r=build_registry()
        for source in SOURCES:
            with self.subTest(source=source):
                d=r.card(source);same=r.card(AssembleRecipe(source,source,'top').card_id)
                self.assertEqual(asdict(d)|{'id':same.id},asdict(same))
                base=r.card(CURATOR);f=r.card(AssembleRecipe(CURATOR,source,'bottom').card_id)
                self.assertEqual((f.name,f.cost,f.attack,f.health,f.metadata,f.keywords),
                    (base.name,base.cost,base.attack,base.health,base.metadata,base.keywords))
                self.assertEqual(f.battlecry,d.battlecry or d.deathrattle)

    def test_each_paid_body_uses_actual_hand_scope_enemy_scope_or_new_physical_self(self):
        for source in SOURCES:
            with self.subTest(source=source):
                cid=AssembleRecipe(CURATOR,source,'bottom').card_id
                g=self.game(hand=(cid,VULGAR,FLY,COIN),board=(BONUS,UNIT),enemy=(UNIT,UNIT))
                before=g.state.players[1].mana;eid=self.play(g,cid)
                self.assertEqual(g.state.players[1].mana,before-g.registry.card(cid).cost)
                v,f=self.stored(g,VULGAR),self.stored(g,FLY)
                self.assertEqual((v.attack,v.health),(3,5)if source==BUFF else (4,6)if source==TAUNT_BUFF else (2,4))
                self.assertEqual((f.attack,f.health),(2,3)if source==BUFF else (1,2))
                self.assertEqual(len(g.state.players[2].board),1 if source in(STATUE,BOMB)else 2)
                rows=self.rows(g,cid)
                self.assertEqual(sum(x.damage_dealt for x in rows),4 if source==SELF else 8 if source==OTHERS else 0)
                self.assertTrue(all(x.source_id==eid and x.spell_bonus==0 for x in rows))
                self.assertEqual(g.state.entities[eid].health,g.registry.card(CURATOR).health-(4 if source==SELF else 0))
                if source==OTHERS:self.assertEqual(len({x.batch_id for x in rows}),1)
                self.assertFalse(g.state.cast_history)

    def test_real_nurturer_moves_hand_buff_to_death_and_does_not_draw_original_loot(self):
        g=self.game(hand=(NURTURER,KILL,VULGAR,FLY,COIN));self.play(g,NURTURER)
        cid=self.choose(g,EMBER,BUFF,'bottom');eid=self.play(g,cid)
        self.assertEqual(self.stored(g,VULGAR).attack,2);self.play(g,KILL,eid)
        self.assertEqual((self.stored(g,VULGAR).attack,self.stored(g,VULGAR).health),(3,5))
        self.assertEqual((self.stored(g,FLY).attack,self.stored(g,FLY).health),(2,3))
        self.assertFalse(g.state.draw_history);self.portable(g)

    def test_real_fetcher_taunt_hand_buff_keeps_only_current_taunt_recipients(self):
        g=self.game(hand=(FETCHER,KILL,VULGAR,FLY),mode='fetcher',hero='HERO_01');self.play(g,FETCHER)
        cid=self.choose(g,TAUNT_BUFF,CAIRNE,'top');eid=self.play(g,cid)
        self.assertEqual(g.state.entities[eid].keywords,set(g.registry.card(CAIRNE).keywords))
        self.assertEqual(self.stored(g,VULGAR).attack,2);self.play(g,KILL,eid)
        self.assertEqual((self.stored(g,VULGAR).attack,self.stored(g,VULGAR).health),(4,6))
        self.assertEqual((self.stored(g,FLY).attack,self.stored(g,FLY).health),(1,2))

    def test_real_mismatch_all_other_minions_damage_excludes_the_dead_source_and_both_heroes(self):
        g=self.game(hand=(MISMATCH,KILL),board=(UNIT,),enemy=(UNIT,),mode='mismatch',hero='HERO_05')
        ally=g.state.players[1].board[0];enemy=g.state.players[2].board[0]
        self.play(g,MISMATCH);cid=self.choose(g,BOMB,OTHERS,'bottom');eid=self.play(g,cid)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[eid].keywords);self.play(g,KILL,eid)
        self.assertEqual((g.state.entities[ally].health,g.state.entities[enemy].health),(18,18))
        self.assertEqual((self.hp(g),self.hp(g,2)),(30,30))
        self.assertTrue(all(x.target_id!=eid for x in self.rows(g,cid)))

    def test_native_lifesteal_self_damage_and_prefix_replacement_use_the_same_body(self):
        for cid,healed in ((SELF,True),(AssembleRecipe(SELF,CURATOR,'top').card_id,False)):
            with self.subTest(cid=cid):
                g=self.game(hand=(WOUND,cid));self.play(g,WOUND);self.assertEqual(self.hp(g),26)
                eid=self.play(g,cid);self.assertEqual(g.state.entities[eid].health,4)
                self.assertEqual(self.hp(g),30 if healed else 26)
                self.assertEqual(Keyword.LIFESTEAL in g.state.entities[eid].keywords,healed)

    def test_real_mismatch_lifesteal_prefix_heals_for_new_all_other_minion_damage(self):
        g=self.game(hand=(WOUND,MISMATCH),enemy=(UNIT,),mode='mismatch_self',hero='HERO_09')
        self.play(g,WOUND);cause=self.play(g,MISMATCH)
        cid=self.choose(g,SELF,OTHERS,'bottom');eid=self.play(g,cid)
        self.assertEqual(g.state.entities[eid].health,8);self.assertEqual(self.hp(g),30)
        self.assertIn(Keyword.LIFESTEAL,g.state.entities[eid].keywords);self.assertNotIn(Keyword.TAUNT,g.state.entities[eid].keywords)
        damage=[x for x in self.rows(g,cid)if x.damage_dealt]
        self.assertEqual(sum(x.damage_dealt for x in damage),4)
        self.assertEqual({x.target_id for x in damage},{cause,g.state.players[2].board[0]})

    def test_real_mismatch_self_damage_deathrattle_uses_stale_target_without_damage_or_healing(self):
        g=self.game(hand=(WOUND,MISMATCH,KILL),mode='mismatch_self',hero='HERO_09')
        self.play(g,WOUND);self.play(g,MISMATCH);cid=self.choose(g,SELF,STATUE,'top');eid=self.play(g,cid)
        self.assertEqual((g.state.entities[eid].health,self.hp(g)),(8,26));self.play(g,KILL,eid)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertFalse(self.rows(g,cid));self.assertEqual(self.hp(g),26)
        self.assertTrue(any(e.kind=='effect_skipped'and e.target_id==eid for e in g.events));self.portable(g)

    def test_empty_random_removal_preserves_rng_and_never_selects_a_hero(self):
        cid=AssembleRecipe(CURATOR,BOMB,'bottom').card_id;g=self.game(hand=(cid,))
        rng=g.snapshot()['rng_state'];eid=self.play(g,cid)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.hp(g,2),30)
        self.assertFalse(any(e.kind=='random_choice'and e.source_id==eid for e in g.events))
        self.assertTrue(any(e.kind=='random_choice_skipped'and e.source_id==eid for e in g.events))

    def test_wait_restore_failed_resume_and_batch_lifesteal_keep_exact_native_health_results(self):
        cid=AssembleRecipe(SELF,OTHERS,'bottom').card_id
        g=self.game(hand=(WOUND,cid),board=(WATCH,),enemy=(UNIT,),mode='wait')
        self.play(g,WOUND);eid=self.play(g,cid);saved=self.portable(g);q=g.state.pending_choice;self.assertIsNotNone(q)
        with self.assertRaisesRegex(ResolutionError,'native effect assembly observer fault'):
            g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),saved)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(self.hp(g),30);self.assertEqual(g.state.entities[eid].health,8)
        self.assertEqual(sum(x.damage_dealt for x in self.rows(g,cid)),4);self.portable(g)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for hidden in ('source_guard','source_sha256','definition_sha256','packet_index'):
                self.assertNotIn('"'+hidden+'"',visible)

    def test_stolen_random_deathrattle_samples_only_current_opponents_and_replays_same_rng(self):
        cid=AssembleRecipe(LOOT,STATUE,'bottom').card_id
        g=self.game(hand=(STEAL,KILL),board=(UNIT,),enemy=(cid,UNIT,UNIT));eid=g.state.players[2].board[0]
        candidates=set(g.state.players[2].board[1:]);ally=g.state.players[1].board[0]
        self.play(g,STEAL,eid);self.play(g,KILL,eid)
        self.assertEqual(g.state.entities[ally].zone,Zone.BOARD);self.assertEqual(len(g.state.players[2].board),1)
        events=[e for e in g.events if e.kind=='random_choice'and e.source_id==eid]
        self.assertEqual(len(events),1);self.assertIn(events[0].target_id,candidates);self.portable(g)

    def test_copy_silence_and_return_reset_preserve_the_new_hand_buff_deathrattle(self):
        cid=AssembleRecipe(LOOT,BUFF,'bottom').card_id
        g=self.game(board=(cid,),hand=(COPY,MUTE,KILL,BOUNCE,KILL,FLY));eid=g.state.players[1].board[0]
        self.play(g,COPY,eid);copy=next(i for i in g.state.players[1].board if i!=eid)
        self.assertEqual(g.state.entities[copy].card_id,cid);self.play(g,MUTE,copy);self.play(g,KILL,copy)
        self.assertEqual(self.stored(g,FLY).attack,1);self.play(g,BOUNCE,eid);self.play(g,cid);self.play(g,KILL,eid)
        self.assertEqual((self.stored(g,FLY).attack,self.stored(g,FLY).health),(2,3))

    def test_end_hand_buff_and_owner_start_self_damage_use_existing_native_clocks(self):
        end=AssembleRecipe(BUFF,'BE_152','top').card_id
        g=self.game(hand=(end,FLY));self.play(g,end);self.assertEqual(self.stored(g,FLY).attack,1)
        g.apply(EndTurn(1));self.assertEqual((self.stored(g,FLY).attack,self.stored(g,FLY).health),(2,3))
        start=AssembleRecipe(SELF,'BE_873','top').card_id
        g=self.game(hand=(start,));eid=self.play(g,start);g.apply(EndTurn(1));self.assertEqual(g.state.entities[eid].health,8)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[eid].health,4);self.assertEqual(self.hp(g),30)

    def test_missing_eligible_source_or_domain_rolls_back_payment_rng_and_offer(self):
        for mode in ('missing','no_pool'):
            with self.subTest(mode=mode):
                g=self.game(hand=(NURTURER,),mode=mode);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,NURTURER)
                self.assertEqual(g.snapshot(),saved)

    def test_all_complete_source_pins_are_checked_before_any_template_is_installed(self):
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        r._cards[STATUE]=replace(r.card(STATUE),health=9)
        with self.assertRaisesRegex(TargetValidationError,'complete original source'):
            register_assemble_native_buffs_removal_health_fragments(r)
        self.assertTrue(all(cid not in r.assemble_templates for cid in SOURCES))


if __name__=='__main__':unittest.main()
