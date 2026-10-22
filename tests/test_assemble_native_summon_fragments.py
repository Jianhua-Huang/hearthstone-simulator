"""Original summon halves keep fixed children, ordered stages and public lifetimes."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_native_summon_fragments import SOURCES,EXISTING_CHILDREN,load_batch,register_assemble_native_summon_fragments
from hs_sim.cards.native_assemble_entry_cards import FETCHER,NURTURER,POOL_ID
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import ChoiceOption,GainArmor,InvokeBehavior,RequestChoice,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Keyword
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import (fixture as base_fixture,META,DECK,COIN,UNIT,KILL,MUTE,COPY,BOUNCE,STEAL)

BEAR,VOID,EGG,DUCK,PARADOX,FIN,SKY,KEEPER=SOURCES
FLY,LOOT,CAIRNE,CURATOR,EMBER,KHADGAR='CORE_UNG_809','CORE_EX1_096','CORE_EX1_110','CORE_KAR_061','TLC_249','CORE_DAL_575'
CHILDREN={BEAR:('AV_337t',2),VOID:('CS2_065',3),EGG:('DINO_130t',1),DUCK:('EDR_492t',3),
    PARADOX:(PARADOX,2),FIN:(EMBER,1),SKY:('TLC_237t',4),KEEPER:('TLC_443t',1)}
P='fixture.assemble_native_summon.'
WATCH,FAULT=(P+x for x in ('watch','fault'))
CTX=GenerationContext('k399-reviewed-native-summon-fixture','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__();r._version+='.k399.'+mode
    def fault(c):raise ResolutionError('deliberate assembled summon observer fault')
    r.register_behavior(FAULT,fault)
    def watch(c):
        if c.state.entities[c.event.target_id].card_id not in {x[0]for x in CHILDREN.values()}:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('add','Add a later ally',(Summon(c.player_id,UNIT),)),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('minion_summoned',WATCH),)))
    members=(EMBER,FIN,LOOT)if mode=='nurturer'else (LOOT,VOID,CAIRNE)if mode=='mismatch'else (DUCK,CAIRNE,CURATOR)
    if mode=='missing':r._assemble_templates.pop(DUCK)
    if mode!='no_pool':
        r.register_pool(PoolDefinition(POOL_ID,'three-real-summon-sources-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(x)for x in members),complete=True))
    return r


class AssembleNativeSummonTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode='normal',hero='HERO_06'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),
            seed=399,generation_context=CTX),fixture(mode))

    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target));return eid

    def children(self,g,cid,pid=1):return [g.state.entities[i]for i in g.state.players[pid].board if g.state.entities[i].card_id==cid]
    def hp(self,g,pid):return g.state.entities[g.state.players[pid].hero_id].health

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

    def test_fifteen_complete_records_thirty_full_primary_faces_and_exact_existing_children(self):
        data=load_batch();r=build_registry();rows={x['record']['id']:x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows),SOURCES+EXISTING_CHILDREN)
        self.assertEqual(sha(Path(data['source']['file'])),data['source']['sha256'])
        self.assertEqual(len(data['official_observations']),30);seen=set()
        for obs in data['official_observations']:
            row=rows[obs['card_id']]
            check_face(row['record'],obs['face'],obs['locale'],numeric_normalizations=data['numeric_normalizations'].get(obs['card_id']))
            path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
            seen.add((obs['card_id'],obs['locale']))
        self.assertEqual(seen,{(cid,loc)for cid in rows for loc in ('zh_CN','en_US')})
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertFalse(data['experimental_policy']['formal_pool_installed'])
        with self.assertRaises(UnsupportedDefinitionError):r.pool(POOL_ID,CTX)

    def test_eight_halves_reconstruct_entire_original_cards_and_borrow_no_donor_keywords(self):
        r=build_registry()
        for source in SOURCES:
            with self.subTest(source=source):
                d=r.card(source);same=r.card(AssembleRecipe(source,source,'top').card_id)
                self.assertEqual(asdict(d)|{'id':same.id},asdict(same))
                face=r.card(AssembleRecipe(FLY,source,'bottom').card_id);base=r.card(FLY)
                self.assertEqual((face.name,face.cost,face.attack,face.health,face.metadata,face.keywords),
                    (base.name,base.cost,base.attack,base.health,base.metadata,base.keywords))
                self.assertEqual(face.battlecry,d.battlecry or d.deathrattle)

    def test_each_paid_compiled_battlecry_summons_fixed_printed_children_without_child_battlecries(self):
        for source,(child,count) in CHILDREN.items():
            with self.subTest(source=source):
                cid=AssembleRecipe(FLY,source,'bottom').card_id
                g=self.game(hand=(cid,),board=(UNIT,));before=g.state.players[1].mana;eid=self.play(g,cid)
                bodies=self.children(g,child);self.assertEqual(len(bodies),count)
                self.assertEqual(g.state.players[1].mana,before-g.registry.card(cid).cost)
                printed=g.registry.card(child);extra=1 if source==EGG else 0
                self.assertTrue(all((e.attack,e.health,e.owner,e.controller)==(printed.attack+extra,printed.health+extra,1,1)for e in bodies))
                self.assertTrue(all(set(printed.keywords)<=e.keywords for e in bodies))
                self.assertEqual(len(g.state.players[1].board),count+2)
                self.assertEqual(g.state.entities[eid].attack,g.registry.card(FLY).attack+extra)
                self.assertFalse(g.state.cast_history)
                if source==PARADOX:
                    self.assertTrue(all(e.card_id==PARADOX and e.card_id!=cid for e in bodies))
                    self.assertTrue(all(Keyword.ELUSIVE in e.keywords for e in bodies))

    def test_real_nurturer_summons_original_ember_and_its_deathrattle_still_deals_two(self):
        g=self.game(hand=(NURTURER,KILL,KILL),mode='nurturer',hero='HERO_02');self.play(g,NURTURER)
        cid=self.choose(g,EMBER,FIN,'bottom');eid=self.play(g,cid);self.assertFalse(self.children(g,EMBER))
        self.play(g,KILL,eid);children=self.children(g,EMBER);self.assertEqual(len(children),1)
        self.assertEqual(children[0].card_id,EMBER);self.assertEqual(self.hp(g,2),30)
        self.play(g,KILL,children[0].id);self.assertEqual(self.hp(g,2),28);self.portable(g)

    def test_real_fetcher_moves_three_rush_ducks_from_battlecry_to_natural_death(self):
        g=self.game(hand=(FETCHER,KILL));self.play(g,FETCHER)
        cid=self.choose(g,DUCK,CAIRNE,'top');eid=self.play(g,cid)
        self.assertFalse(self.children(g,'EDR_492t'));self.assertIsNone(g.registry.card(cid).battlecry)
        self.play(g,KILL,eid);bodies=self.children(g,'EDR_492t')
        self.assertEqual(len(bodies),3);self.assertTrue(all(Keyword.RUSH in e.keywords for e in bodies))

    def test_real_mismatch_uses_available_slots_for_original_voidwalkers_and_their_taunt(self):
        g=self.game(hand=(MISMATCH,KILL),board=(UNIT,)*4,mode='mismatch',hero='HERO_07')
        self.play(g,MISMATCH);cid=self.choose(g,LOOT,VOID,'bottom');eid=self.play(g,cid)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[eid].keywords);self.play(g,KILL,eid)
        bodies=self.children(g,'CS2_065');self.assertEqual(len(bodies),2)
        self.assertTrue(all((e.attack,e.health)==(1,3)and Keyword.TAUNT in e.keywords for e in bodies))
        self.assertEqual(len(g.state.players[1].board),7)

    def test_ordered_summon_wait_restore_failed_resume_and_later_buff_use_current_allies(self):
        cid=AssembleRecipe(FLY,EGG,'bottom').card_id
        g=self.game(hand=(cid,),board=(WATCH,),mode='wait');eid=self.play(g,cid)
        child=self.children(g,'DINO_130t')[0];self.assertEqual((child.attack,child.health),(3,3))
        saved=self.portable(g);q=g.state.pending_choice;self.assertIsNotNone(q)
        with self.assertRaisesRegex(ResolutionError,'assembled summon observer fault'):
            g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),saved)
        g.apply(SelectChoice(q.player_id,q.id,('add',)))
        child=self.children(g,'DINO_130t')[0];ally=self.children(g,UNIT)[0]
        self.assertEqual((child.attack,child.health),(4,4));self.assertEqual((ally.attack,ally.health),(1,21))
        self.assertEqual(g.state.entities[eid].attack,g.registry.card(FLY).attack+1)
        self.portable(g)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for hidden in ('source_guard','definition_sha256','source_sha256','card_summon_history'):
                self.assertNotIn('"'+hidden+'"',visible)

    def test_actual_khadgar_sees_new_causing_face_and_three_independent_native_requests(self):
        cid=AssembleRecipe(FLY,DUCK,'bottom').card_id
        g=self.game(hand=(cid,),board=(KHADGAR,));eid=self.play(g,cid)
        roots=g.state.card_summon_history;self.assertEqual(len(roots),3)
        self.assertTrue(all(x.plan.total==2 and x.status=='completed'for x in roots))
        self.assertTrue(all((x.request.cause.source.entity_id,x.request.cause.source.card_id,x.request.cause.player_id,x.request.cause.origin)==
            (eid,cid,1,'card_effect')for x in roots))
        self.assertEqual(sum(d.outcome=='delivered'for x in roots for d in x.deliveries),5)
        self.assertEqual(sum(d.outcome=='board_full'for x in roots for d in x.deliveries),1)
        self.assertEqual(len(self.children(g,'EDR_492t')),5);self.assertFalse(g.state.cast_history);self.portable(g)

    def test_reborn_prefix_is_kept_or_replaced_without_changing_the_fixed_summons(self):
        keep=AssembleRecipe(KEEPER,BEAR,'bottom').card_id
        g=self.game(hand=(KILL,),board=(keep,));eid=g.state.players[1].board[0];self.play(g,KILL,eid)
        self.assertEqual(len(self.children(g,'AV_337t')),2);reborn=self.children(g,keep)
        self.assertEqual(len(reborn),1);self.assertEqual(reborn[0].health,1);self.assertNotIn(Keyword.REBORN,reborn[0].keywords)
        drop=AssembleRecipe(KEEPER,LOOT,'top').card_id
        g=self.game(hand=(KILL,),board=(drop,));self.play(g,KILL,g.state.players[1].board[0])
        self.assertEqual(len(self.children(g,'TLC_443t')),1);self.assertFalse(self.children(g,drop))

    def test_copy_silence_and_return_reset_keep_the_new_summon_body(self):
        cid=AssembleRecipe(LOOT,SKY,'bottom').card_id
        g=self.game(board=(cid,),hand=(COPY,MUTE,KILL,BOUNCE,KILL));eid=g.state.players[1].board[0]
        self.play(g,COPY,eid);copy=next(i for i in g.state.players[1].board if i!=eid)
        self.assertEqual(g.state.entities[copy].card_id,cid);self.play(g,MUTE,copy);self.play(g,KILL,copy)
        self.assertFalse(self.children(g,'TLC_237t'));self.play(g,BOUNCE,eid);self.play(g,cid);self.play(g,KILL,eid)
        self.assertEqual(len(self.children(g,'TLC_237t')),4)

    def test_stolen_deathrattle_creates_new_children_for_controller_and_keeps_child_effect(self):
        cid=AssembleRecipe(LOOT,FIN,'bottom').card_id
        g=self.game(enemy=(cid,),hand=(STEAL,KILL,KILL));eid=g.state.players[2].board[0]
        self.play(g,STEAL,eid);self.play(g,KILL,eid);child=self.children(g,EMBER)[0]
        self.assertEqual((g.state.entities[eid].owner,g.state.entities[eid].controller),(2,1))
        self.assertEqual((child.owner,child.controller),(1,1));self.assertFalse(self.children(g,EMBER,2))
        self.play(g,KILL,child.id);self.assertEqual((self.hp(g,1),self.hp(g,2)),(30,28))

    def test_end_and_owner_start_timing_keep_original_summons_without_playing_their_battlecry(self):
        for secondary in ('BE_152','BE_873'):
            with self.subTest(secondary=secondary):
                cid=AssembleRecipe(PARADOX,secondary,'top').card_id
                g=self.game(hand=(cid,));self.play(g,cid);self.assertFalse(self.children(g,PARADOX))
                g.apply(EndTurn(1))
                if secondary=='BE_873':
                    self.assertFalse(self.children(g,PARADOX));g.apply(EndTurn(2))
                self.assertEqual(len(self.children(g,PARADOX)),2)

    def test_missing_eligible_source_or_domain_rolls_back_payment_rng_and_offer(self):
        for mode in ('missing','no_pool'):
            with self.subTest(mode=mode):
                g=self.game(hand=(FETCHER,),mode=mode);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,FETCHER)
                self.assertEqual(g.snapshot(),saved)

    def test_complete_source_and_child_pins_are_checked_before_installing_any_template(self):
        for changed in (BEAR,'TLC_237t'):
            with self.subTest(changed=changed):
                r=build_registry()
                for cid in SOURCES:r._assemble_templates.pop(cid)
                r._cards[changed]=replace(r.card(changed),health=r.card(changed).health+1)
                with self.assertRaisesRegex(TargetValidationError,'complete original source or child'):
                    register_assemble_native_summon_fragments(r)
                self.assertTrue(all(cid not in r.assemble_templates for cid in SOURCES))


if __name__=='__main__':unittest.main()
