"""Six real damage halves keep their native damage, timing and source identity."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_native_damage_fragments import SOURCES,load_batch,register_assemble_native_damage_fragments
from hs_sim.cards.native_assemble_entry_cards import NURTURER,POOL_ID
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import ChoiceOption,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import Keyword,Zone
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import (fixture as base_fixture,META,DECK,COIN,UNIT,
    KILL,MUTE,COPY,BOUNCE,STEAL)

IMP,VULGAR,ERADICATOR,SEWER,EMBER,ORIGINAL=SOURCES
LOOT='CORE_EX1_096'
P='fixture.assemble_native_damage.'
BONUS,WATCH,FAULT=(P+x for x in ('bonus','watch','fault'))
CTX=GenerationContext('k398-reviewed-native-damage-fixture','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__();r._version+='.k398.'+mode
    r.register_card(CardDefinition(BONUS,BONUS,CardType.MINION,health=20,spell_damage=10,metadata=META))
    def fault(c):raise ResolutionError('deliberate assembled damage observer fault')
    r.register_behavior(FAULT,fault)
    def watch(c):
        hit=c.health_result
        if hit is None or not (hit.source_card_id or '').startswith('assemble:') or hit.damage_dealt<=0:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('health_resolved',WATCH),)))
    members=(LOOT,ERADICATOR,SEWER)if mode=='mismatch'else (EMBER,VULGAR,LOOT)if mode=='ember'else (IMP,VULGAR,LOOT)
    if mode=='missing':r._assemble_templates.pop(IMP)
    if mode!='no_pool':
        r.register_pool(PoolDefinition(POOL_ID,'three-real-damage-sources-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(x)for x in members),complete=True))
    return r


class AssembleNativeDamageTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode='normal',hero='HERO_07'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),
            seed=398,generation_context=CTX),fixture(mode))

    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target));return eid

    def hp(self,g,pid):return g.state.entities[g.state.players[pid].hero_id].health
    def rows(self,g,cid):return [health_result(e)for e in g.events
        if e.kind=='health_resolved'and health_result(e).source_card_id==cid]

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

    def test_six_complete_sources_twelve_whole_primary_faces_and_original_health_bodies(self):
        data=load_batch();r=build_registry();rows={x['record']['id']:x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows),SOURCES);self.assertEqual(len(data['official_observations']),12)
        seen=set()
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale'])
            path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']
                if x['id']==row['record']['dbf_id']],[obs['face']]);seen.add((obs['card_id'],obs['locale']))
        self.assertEqual(seen,{(cid,loc)for cid in SOURCES for loc in ('zh_CN','en_US')})
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            t=r.assemble_templates[cid];self.assertEqual(t.suffix.behavior_id,r.card(cid).battlecry or r.card(cid).deathrattle)
            self.assertEqual(t.suffix.allowed_timings,('battlecry','deathrattle','end_turn','start_turn'))
        self.assertFalse(data['experimental_policy']['formal_pool_installed'])
        with self.assertRaises(UnsupportedDefinitionError):r.pool(POOL_ID,CTX)

    def test_all_six_reconstruct_original_whole_cards_and_borrow_only_the_authored_body(self):
        r=build_registry()
        for source in SOURCES:
            with self.subTest(source=source):
                original=r.card(source);same=r.card(AssembleRecipe(source,source,'top').card_id)
                self.assertEqual(asdict(original)|{'id':same.id},asdict(same))
                cid=AssembleRecipe('CORE_UNG_809',source,'bottom').card_id;face=r.card(cid);base=r.card('CORE_UNG_809')
                self.assertEqual((face.name,face.cost,face.attack,face.health,face.metadata,face.keywords),
                    (base.name,base.cost,base.attack,base.health,base.metadata,base.keywords))

    def test_each_real_suffix_executes_as_one_paid_battlecry_without_spell_amplification(self):
        for source in SOURCES:
            with self.subTest(source=source):
                cid=AssembleRecipe('CORE_UNG_809',source,'bottom').card_id
                g=self.game(hand=(cid,),board=(BONUS,),enemy=(UNIT,UNIT));targets=tuple(g.state.players[2].board)
                before=g.state.players[1].mana;eid=self.play(g,cid);rows=self.rows(g,cid)
                self.assertEqual(g.state.players[1].mana,before-g.registry.card(cid).cost)
                total=2 if source==EMBER else 18 if source==ERADICATOR else 6 if source==SEWER else 2 if source==VULGAR else 3
                self.assertEqual(sum(x.damage_dealt for x in rows),total)
                self.assertTrue(all(x.source_id==eid and x.damage_kind=='effect'and x.spell_bonus==0 for x in rows))
                self.assertEqual(self.hp(g,1),28 if source==VULGAR else 27 if source in(IMP,ORIGINAL)else 30)
                if source==ERADICATOR:
                    self.assertEqual([g.state.entities[i].health for i in targets],[11,11]);self.assertEqual(self.hp(g,2),30)
                if source==SEWER:
                    self.assertEqual([g.state.entities[i].health for i in targets],[18,18]);self.assertEqual(self.hp(g,2),28)
                self.assertFalse(g.state.cast_history)

    def test_real_nurturer_replaces_imp_damage_with_draw_or_moves_it_to_natural_death(self):
        for half in ('bottom','top'):
            with self.subTest(half=half):
                g=self.game(hand=(NURTURER,KILL));self.play(g,NURTURER)
                cid=self.choose(g,IMP,LOOT,half);eid=self.play(g,cid)
                self.assertEqual(self.hp(g,1),30)
                if half=='bottom':
                    self.assertEqual(len(g.state.draw_history),1);self.assertIsNone(g.registry.card(cid).deathrattle)
                else:
                    self.assertFalse(g.state.draw_history);self.play(g,KILL,eid)
                    self.assertEqual(self.hp(g,1),27);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)

    def test_real_nurturer_moves_split_damage_to_taunt_battlecry_without_a_deathrattle(self):
        g=self.game(hand=(NURTURER,KILL),enemy=(UNIT,),mode='ember');self.play(g,NURTURER)
        cid=self.choose(g,EMBER,VULGAR,'top');eid=self.play(g,cid)
        self.assertIn(Keyword.TAUNT,g.state.entities[eid].keywords);self.assertIsNone(g.registry.card(cid).deathrattle)
        self.assertEqual(sum(x.damage_dealt for x in self.rows(g,cid)),2)
        self.play(g,KILL,eid);self.assertEqual(sum(x.damage_dealt for x in self.rows(g,cid)),2)

    def test_real_mismatch_borrows_nine_damage_without_importing_donor_taunt(self):
        g=self.game(hand=(MISMATCH,KILL),enemy=(UNIT,UNIT),mode='mismatch',hero='HERO_02')
        self.play(g,MISMATCH);cid=self.choose(g,LOOT,ERADICATOR,'bottom');eid=self.play(g,cid)
        self.assertEqual(g.registry.card(cid).cost,2);self.assertNotIn(Keyword.TAUNT,g.state.entities[eid].keywords)
        self.assertFalse(self.rows(g,cid));self.play(g,KILL,eid)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[11,11])
        self.assertEqual(self.hp(g,2),30);self.assertEqual(len({x.batch_id for x in self.rows(g,cid)}),1)
        self.portable(g)

    def test_split_wait_restore_failed_resume_and_rng_continue_the_original_two_packets(self):
        cid=AssembleRecipe('CORE_UNG_809',EMBER,'bottom').card_id
        g=self.game(hand=(cid,),board=(BONUS,WATCH),enemy=(UNIT,));eid=self.play(g,cid)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.rows(g,cid)),1)
        saved=self.portable(g);q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'assembled damage observer fault'):
            g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),saved)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        rows=self.rows(g,cid);self.assertEqual([x.damage_dealt for x in rows],[1,1])
        self.assertTrue(all(x.source_id==eid for x in rows));self.portable(g)
        randoms=[e for e in g.events if e.kind=='random_choice'and e.source_id==eid]
        self.assertEqual(len(randoms),2)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for hidden in ('source_guard','definition_sha256','source_sha256','packet_index'):
                self.assertNotIn('"'+hidden+'"',visible)

    def test_current_copy_silence_and_return_reset_preserve_the_new_death_body(self):
        cid=AssembleRecipe(LOOT,SEWER,'bottom').card_id
        g=self.game(board=(cid,),enemy=(UNIT,),hand=(COPY,MUTE,KILL,BOUNCE,KILL));source=g.state.players[1].board[0]
        self.play(g,COPY,source);child=next(i for i in g.state.players[1].board if i!=source)
        self.assertEqual(g.state.entities[child].card_id,cid);self.assertFalse(self.rows(g,cid))
        self.play(g,MUTE,child);self.play(g,KILL,child);self.assertFalse(self.rows(g,cid))
        self.play(g,BOUNCE,source);self.play(g,cid);self.play(g,KILL,source)
        self.assertEqual(self.hp(g,2),28);self.assertEqual(sum(x.damage_dealt for x in self.rows(g,cid)),4)

    def test_stolen_deathrattle_uses_actual_controller_for_all_enemies_and_source(self):
        cid=AssembleRecipe(LOOT,SEWER,'bottom').card_id
        g=self.game(enemy=(cid,),board=(UNIT,),hand=(STEAL,KILL));source=g.state.players[2].board[0]
        self.play(g,STEAL,source);self.play(g,KILL,source)
        self.assertEqual((g.state.entities[source].owner,g.state.entities[source].controller),(2,1))
        self.assertEqual((self.hp(g,1),self.hp(g,2)),(30,28))
        self.assertEqual([(x.source_id,x.source_controller,x.target_controller)for x in self.rows(g,cid)],[(source,1,2)])

    def test_end_and_owner_start_timing_reuse_the_same_native_self_damage_body(self):
        end=AssembleRecipe(IMP,'BE_152','top').card_id
        g=self.game(hand=(end,));self.play(g,end);self.assertEqual(self.hp(g,1),30)
        g.apply(EndTurn(1));self.assertEqual(self.hp(g,1),27)
        start=AssembleRecipe(IMP,'BE_873','top').card_id
        g=self.game(hand=(start,));self.play(g,start);g.apply(EndTurn(1));self.assertEqual(self.hp(g,1),30)
        g.apply(EndTurn(2));self.assertEqual(self.hp(g,1),27);self.portable(g)

    def test_missing_eligible_source_or_domain_rolls_back_payment_rng_and_offer(self):
        for mode in ('missing','no_pool'):
            with self.subTest(mode=mode):
                g=self.game(hand=(NURTURER,),mode=mode);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,NURTURER)
                self.assertEqual(g.snapshot(),saved)

    def test_whole_original_definition_pin_is_checked_before_installing_any_fragment(self):
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        r._cards[IMP]=replace(r.card(IMP),health=8)
        with self.assertRaisesRegex(TargetValidationError,'whole original'):
            register_assemble_native_damage_fragments(r)
        self.assertTrue(all(cid not in r.assemble_templates for cid in SOURCES))


if __name__=='__main__':unittest.main()
