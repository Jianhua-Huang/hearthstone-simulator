"""Actual source bodies, native assembly and ordinary Reborn/choice lifetimes."""
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_draw_armor_heal_fragments import SOURCES,load_batch
from hs_sim.cards.native_assemble_entry_cards import FETCHER,POOL_ID
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,
    GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,DamageKind,Keyword,SpellSchool,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face,sha

GOLEM,SHOWER,BEETLE,TAELAN,DRYAD,VANGUARD,HAWK,KODO,CURATOR=(
    'BE_861','CORE_BAR_310','CORE_LOOT_413','CS3_024','EDR_485','RLK_511','TIME_601','BAR_551','CORE_KAR_061')
FLY,COIN='CORE_UNG_809','GAME_005'
P='fixture.assemble_draw_armor_heal.'
KILL,MUTE,SHIFT,COPY,BOUNCE,STEAL,WOUND,WATCH,FAULT,UNIT,BEAST,DRAGON,MURLOC,S1,S2,S3=(P+x for x in
    ('kill','mute','shift','copy','bounce','steal','wound','watch','fault','unit','beast','dragon','murloc','one','two','three'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
CTX=GenerationContext('k395-reviewed-draw-armor-heal-fixture','experimental')
DECK=(S1,DRAGON,S2,BEAST,S3,MURLOC)+(COIN,)*10
REBORN_ARMOR=AssembleRecipe(BEETLE,GOLEM,'top').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=build_registry();r._version+='.k395.'+mode
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),MUTE:lambda c:(Silence(c.target_id),),
        SHIFT:lambda c:(Transform(c.target_id,UNIT),),
        COPY:lambda c:(CopyMinion(c.target_id,c.player_id,mode='current'),),
        BOUNCE:lambda c:(ReturnToHand(c.target_id),),STEAL:lambda c:(ChangeControl(c.target_id,c.player_id),),
        WOUND:lambda c:tuple(Damage(i,4,c.source_id,DamageKind.SPELL)for i in
            (c.state.players[c.player_id].hero_id,*c.state.players[c.player_id].board))}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=None if cid==WOUND else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,health=20,metadata=META))
    for cid,tribe,cost in ((BEAST,'beast',1),(DRAGON,'dragon',7),(MURLOC,'murloc',3)):
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=5,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(tribe,)))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    r.register_behavior(P+'noop',lambda c:())
    for cid,school,cost in ((S1,SpellSchool.ARCANE,1),(S2,SpellSchool.FROST,2),(S3,SpellSchool.FIRE,3)):
        d=CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=P+'noop',spell_school=school,metadata=META)
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    def fault(c):raise ResolutionError('deliberate assembled draw observer fault')
    r.register_behavior(FAULT,fault)
    def watch(c):
        if c.event.player_id!=c.player_id:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=META,
        triggers=(TriggerSpec('card_drawn',WATCH),)))
    if mode=='missing':r._assemble_templates.pop(GOLEM)
    if mode!='no_pool':
        r.register_pool(PoolDefinition(POOL_ID,'three-real-sources-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(x)for x in (GOLEM,SHOWER,TAELAN)),complete=True))
    return r


class AssembleDrawArmorHealFragmentTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=DECK,mode='normal'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_09',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),
            seed=395,generation_context=CTX),fixture(mode))

    def play(self,g,cid,target=None):
        pid=g.state.active_player
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target_id=target));return eid

    def drawn(self,g,pid=1):return [r for r in g.state.draw_history if r.player_id==pid]

    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def assembled(self,g,half='bottom',secondary=SHOWER):
        self.play(g,FETCHER);cid=AssembleRecipe(GOLEM,secondary,half).card_id
        q=g.state.pending_choice;option=next(x for x in q.options if x.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(option.id,)));return cid

    def test_eleven_complete_sources_twenty_two_whole_primary_responses_and_original_bodies(self):
        data=load_batch();r=build_registry();rows={x['record']['id']:x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows),SOURCES);self.assertEqual(len(data['official_observations']),22)
        seen=set()
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale'])
            path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            body=json.loads(path.read_text('utf-8-sig'))
            self.assertEqual([x for x in body['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
            seen.add((obs['card_id'],obs['locale']))
        self.assertEqual(seen,{(cid,loc)for cid in SOURCES for loc in ('zh_CN','en_US')})
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            t=r.assemble_templates[cid]
            self.assertEqual(t.suffix.behavior_id,r.card(cid).battlecry or r.card(cid).deathrattle)
        self.assertFalse(data['experimental_policy']['formal_pool_installed'])
        with self.assertRaises(UnsupportedDefinitionError):r.pool(POOL_ID,CTX)

    def test_all_source_halves_reconstruct_complete_whole_minions_and_preserve_primary_headers(self):
        r=build_registry()
        for cid in SOURCES:
            with self.subTest(cid=cid):
                original=r.card(cid);same=r.card(AssembleRecipe(cid,cid,'top').card_id)
                self.assertEqual(asdict(original)|{'id':same.id},asdict(same))
                primary=FLY if original.cost<2 or cid==HAWK else HAWK
                face=r.card(AssembleRecipe(primary,cid,'bottom').card_id);base=r.card(primary)
                self.assertEqual((face.name,face.cost,face.attack,face.health,face.metadata),
                    (base.name,base.cost,base.attack,base.health,base.metadata))

    def test_each_real_suffix_executes_through_an_actual_paid_compiled_minion(self):
        expected_draws={TAELAN:[DRAGON],DRYAD:[DRAGON],VANGUARD:[S2],HAWK:[S1,DRAGON,S2],
            KODO:[S1,S2,S3],CURATOR:[BEAST,DRAGON,MURLOC],'KAR_061':[BEAST,DRAGON,MURLOC]}
        for source in SOURCES:
            with self.subTest(source=source):
                primary=FLY if fixture().card(source).cost<2 or source==HAWK else HAWK
                cid=AssembleRecipe(primary,source,'bottom').card_id
                g=self.game(hand=(cid,WOUND),board=(UNIT,));unit=g.state.players[1].board[0]
                self.play(g,WOUND);before=g.state.players[1].mana;self.play(g,cid)
                self.assertEqual(g.state.players[1].mana,before-fixture().card(primary).cost)
                self.assertEqual([x.card_id for x in self.drawn(g)],expected_draws.get(source,[]))
                hero=g.state.entities[g.state.players[1].hero_id]
                self.assertEqual(hero.health,29 if source==GOLEM else 30 if source in('BAR_310',SHOWER)else 26)
                self.assertEqual(g.state.entities[unit].health,20 if source in('BAR_310',SHOWER)else 16)
                self.assertEqual(hero.armor,3 if source==BEETLE else 0)

    def test_real_fetcher_retains_reborn_and_native_death_restores_one_health_only_once(self):
        g=self.game(hand=(FETCHER,KILL,KILL,WOUND));cid=self.assembled(g);source=self.play(g,cid)
        self.play(g,WOUND);self.assertEqual(g.state.entities[source].health,1)
        self.play(g,KILL,source)
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==cid]
        self.assertEqual(len(bodies),1);child=bodies[0]
        self.assertNotEqual(child.id,source);self.assertEqual(child.origin_entity_id,source)
        self.assertEqual((child.health,child.max_health),(1,5));self.assertNotIn(Keyword.REBORN,child.keywords)
        self.assertIn(Keyword.TAUNT,child.keywords)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.portable(g);self.play(g,KILL,child.id)
        self.assertFalse(any(g.state.entities[i].card_id==cid for i in g.state.players[1].board))

    def test_real_top_replacement_drops_reborn_and_preserves_the_original_heal_body(self):
        g=self.game(hand=(FETCHER,KILL,WOUND));cid=self.assembled(g,'top',TAELAN);source=self.play(g,cid)
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
        self.assertNotIn(Keyword.REBORN,g.state.entities[source].keywords)
        self.play(g,WOUND);self.play(g,KILL,source)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)
        self.assertFalse(any(g.state.entities[i].card_id==cid for i in g.state.players[1].board))
        self.assertFalse(self.drawn(g));self.portable(g)

    def test_current_copy_retains_consumed_reborn_and_hand_reset_restores_the_printed_face(self):
        g=self.game(board=(REBORN_ARMOR,),hand=(KILL,COPY,BOUNCE,KILL))
        source=g.state.players[1].board[0];self.play(g,KILL,source)
        child=g.state.players[1].board[0];self.play(g,COPY,child)
        bodies=[g.state.entities[i]for i in g.state.players[1].board]
        self.assertEqual(len(bodies),2);self.assertTrue(all(Keyword.REBORN not in x.keywords for x in bodies))
        copy=next(x.id for x in bodies if x.id!=child);self.play(g,KILL,copy)
        self.assertEqual(g.state.players[1].board,[child]);self.play(g,BOUNCE,child);self.play(g,REBORN_ARMOR)
        self.assertIn(Keyword.REBORN,g.state.entities[child].keywords)
        self.assertEqual(g.state.entities[child].health,3);self.portable(g)

    def test_silence_or_transform_removes_both_compiled_deathrattle_and_reborn(self):
        for action in (MUTE,SHIFT):
            with self.subTest(action=action):
                g=self.game(board=(REBORN_ARMOR,),hand=(action,KILL));source=g.state.players[1].board[0]
                self.play(g,action,source);self.play(g,KILL,source)
                self.assertFalse(g.state.players[1].board)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_control_change_uses_actual_deathrattle_controller_and_reborn_controller(self):
        g=self.game(enemy=(REBORN_ARMOR,),hand=(STEAL,KILL));source=g.state.players[2].board[0]
        self.play(g,STEAL,source);self.play(g,KILL,source)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0)
        child=g.state.players[1].board[0];self.assertEqual(g.state.entities[child].health,1)
        self.assertEqual(g.state.entities[child].controller,1);self.portable(g)

    def test_three_slot_draw_burns_overflow_and_does_not_reselect_a_physical_card(self):
        cid=AssembleRecipe(BEETLE,KODO,'bottom').card_id
        g=self.game(board=(cid,),hand=(KILL,)+(COIN,)*9);source=g.state.players[1].board[0]
        self.play(g,KILL,source);rows=self.drawn(g)
        self.assertEqual([x.card_id for x in rows],[S1,S2,S3])
        self.assertEqual(len({x.entity_id for x in rows}),3)
        self.assertEqual([g.state.entities[x.entity_id].zone for x in rows],[Zone.HAND,Zone.GRAVEYARD,Zone.GRAVEYARD])
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.players[1].deck),len(DECK)-3)

    def test_draw_wait_restore_replay_and_failed_resume_preserve_original_three_slots(self):
        cid=AssembleRecipe(HAWK,KODO,'bottom').card_id
        g=self.game(board=(WATCH,),hand=(cid,),mode='wait');self.play(g,cid)
        self.assertEqual([x.card_id for x in self.drawn(g)],[S1]);saved=self.portable(g);q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'assembled draw observer fault'):
            g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),saved)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual([x.card_id for x in self.drawn(g)],[S1,S2,S3]);self.portable(g)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for name in ('source_sha256','source_guard','draw_group_ledger','definition_sha256'):
                self.assertNotIn('"'+name+'"',visible)

    def test_end_and_owner_start_suffixes_reuse_the_original_draw_boundaries(self):
        end=AssembleRecipe(HAWK,'BE_152','top').card_id
        g=self.game(hand=(end,));self.play(g,end);self.assertFalse(self.drawn(g));g.apply(EndTurn(1))
        self.assertEqual([x.card_id for x in self.drawn(g)],[S1,DRAGON,S2])
        start=AssembleRecipe(DRYAD,'BE_873','top').card_id
        g=self.game(hand=(start,));self.play(g,start);g.apply(EndTurn(1));self.assertFalse(self.drawn(g))
        g.apply(EndTurn(2));self.assertEqual([x.card_id for x in self.drawn(g)],[DRAGON,S1]);self.portable(g)

    def test_missing_eligible_template_or_source_pool_rolls_back_payment_and_rng(self):
        for mode in ('missing','no_pool'):
            with self.subTest(mode=mode):
                g=self.game(hand=(FETCHER,),mode=mode);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,FETCHER)
                self.assertEqual(g.snapshot(),before)

    def test_changed_whole_source_definition_pin_is_rejected_before_template_registration(self):
        from dataclasses import replace
        from hs_sim.cards.assemble_draw_armor_heal_fragments import register_assemble_draw_armor_heal_fragments
        from hs_sim.targets import TargetValidationError
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        r._cards[GOLEM]=replace(r.card(GOLEM),health=6)
        with self.assertRaisesRegex(TargetValidationError,'whole|complete original'):
            register_assemble_draw_armor_heal_fragments(r)
        self.assertTrue(all(cid not in r.assemble_templates for cid in SOURCES))


if __name__=='__main__':unittest.main()
