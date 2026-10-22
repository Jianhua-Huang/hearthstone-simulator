"""Nine real native end bodies keep original material, controllers and clocks."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_native_end_body_fragments import SOURCES,CHILD,load_batch,register_assemble_native_end_body_fragments
from hs_sim.cards.native_assemble_entry_cards import FETCHER,NURTURER,FLESH,POOL_ID
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import ChangeControl,ChoiceOption,Damage,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind,Keyword,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import (fixture as base_fixture,META,DECK,COIN,UNIT,KILL,MUTE,COPY,BOUNCE)

BUFF,BULWARK,KEEPER,DRAKE,RANDOM,MOSQUITO,CLOUD,HEAL,GOLEM=SOURCES
LOOT,RUST,CURATOR,KHADGAR='CORE_EX1_096','CORE_SW_072','CORE_KAR_061','CORE_DAL_575'
P='fixture.assemble_native_end.'
BONUS,HURT,GIVE,WATCH,FAULT=(P+x for x in('bonus','hurt','give','watch','fault'))
CTX=GenerationContext('k403-native-end-source-fixture','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__();r._version+='.k403.'+mode
    r.register_card(CardDefinition(BONUS,BONUS,CardType.MINION,health=20,spell_damage=10,metadata=META))
    r.register_behavior(HURT,lambda c:tuple(Damage(c.state.players[p].hero_id,4,c.source_id,DamageKind.EFFECT)for p in(1,2)))
    r.register_card(CardDefinition(HURT,HURT,CardType.SPELL,on_play=HURT,metadata=META))
    r.register_behavior(GIVE,lambda c:(ChangeControl(c.target_id,2),))
    r.register_card(CardDefinition(GIVE,GIVE,CardType.SPELL,on_play=GIVE,metadata=META,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')))
    def fault(c):raise ResolutionError('deliberate native end assembly observer fault')
    r.register_behavior(FAULT,fault)
    def watch(c):
        hit=c.health_result
        if hit is None or not (hit.source_card_id or '').startswith('assemble:') or hit.damage_dealt<=0:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('health_resolved',WATCH),)))
    members=(MOSQUITO,LOOT,RUST)if mode=='mosquito'else (LOOT,GOLEM,CLOUD)if mode=='flesh'else (
        CLOUD,BUFF,CURATOR)if mode=='fetcher'else (HEAL,BUFF,DRAKE)if mode=='mismatch'else (HEAL,LOOT,RUST)
    if mode=='missing':r._assemble_templates.pop(HEAL)
    if mode!='no_pool':
        r.register_pool(PoolDefinition(POOL_ID,'three-real-end-sources-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(x)for x in members),complete=True))
    return r


class AssembleNativeEndBodyTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode='normal',hero='HERO_08'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),
            seed=403,generation_context=CTX),fixture(mode))

    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target));return eid
    def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
    def own_draws(self,g):return [x for x in g.state.draw_history if x.player_id==1]
    def rows(self,g,cid):return [health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_card_id==cid]
    def next_turn(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))

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

    def test_ten_complete_records_twenty_full_primary_faces_and_original_native_callbacks(self):
        data=load_batch();rows={x['record']['id']:x for x in data['existing_dependencies']};r=build_registry();seen=set()
        self.assertEqual(tuple(rows),SOURCES+(CHILD,));self.assertEqual(len(data['official_observations']),20)
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale']);path=Path(obs['response_file'])
            self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
            seen.add((obs['card_id'],obs['locale']))
        self.assertEqual(seen,{(cid,loc)for cid in rows for loc in('zh_CN','en_US')})
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in SOURCES:self.assertEqual(r.assemble_templates[cid].suffix.behavior_id,r.card(cid).triggers[0].behavior_id)
        with self.assertRaises(UnsupportedDefinitionError):r.pool(POOL_ID,CTX)

    def test_all_nine_whole_cards_reconstruct_and_clocks_keywords_stay_with_prefix(self):
        r=build_registry()
        for source in SOURCES:
            d=r.card(source);f=r.card(AssembleRecipe(source,source,'top').card_id)
            self.assertEqual(asdict(d)|{'id':f.id},asdict(f))
            body=r.card(AssembleRecipe(CURATOR,source,'bottom').card_id);base=r.card(CURATOR)
            self.assertEqual((body.name,body.cost,body.attack,body.health,body.metadata,body.keywords),
                (base.name,base.cost,base.attack,base.health,base.metadata,base.keywords))
            self.assertEqual(body.triggers,());self.assertEqual(r.assemble_templates[source].prefix.end_turn,d.triggers[0].end_turn)

    def test_each_paid_battlecry_executes_one_native_body_without_original_end_clock(self):
        for source in SOURCES:
            with self.subTest(source=source):
                cid=AssembleRecipe(CURATOR,source,'bottom').card_id
                g=self.game(hand=(HURT,cid),board=(BONUS,UNIT),enemy=(UNIT,UNIT));self.play(g,HURT)
                before=g.state.players[1].mana;eid=self.play(g,cid);ally=g.state.entities[g.state.players[1].board[1]]
                self.assertEqual(g.state.players[1].mana,before-g.registry.card(CURATOR).cost)
                self.assertEqual((ally.attack,ally.health),(1,21)if source==BUFF else (1,20)if source==MOSQUITO else (0,20))
                self.assertEqual(g.state.entities[eid].health,g.registry.card(CURATOR).health)
                self.assertEqual((self.hp(g),self.hp(g,2)),(29,29)if source==HEAL else (26,24)if source==BULWARK else (26,22)if source==DRAKE else (26,26))
                rows=self.rows(g,cid);self.assertEqual(sum(x.damage_dealt for x in rows),6 if source==BULWARK else 4 if source==DRAKE else 5 if source==RANDOM else 0)
                self.assertTrue(all(x.source_id==eid and x.spell_bonus==0 for x in rows))
                self.assertEqual(Keyword.REBORN in g.state.entities[eid].keywords,source==GOLEM)
                self.assertEqual(Keyword.DIVINE_SHIELD in g.state.entities[g.state.players[1].hero_id].keywords,source==CLOUD)
                born=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==CHILD]
                self.assertEqual(len(born),1 if source==KEEPER else 0)
                if born:self.assertEqual((born[0].attack,born[0].health,set(born[0].keywords)),(6,6,{Keyword.DIVINE_SHIELD}))
                self.assertEqual(len(g.state.cast_history),1)

    def test_real_nurturer_replaces_mosquito_end_with_tradeable_immediate_battlecry(self):
        g=self.game(hand=(NURTURER,),board=(UNIT,),mode='mosquito',hero='HERO_11');self.play(g,NURTURER)
        ally=g.state.players[1].board[0];cid=self.choose(g,MOSQUITO,RUST,'top');eid=self.play(g,cid)
        self.assertEqual(g.state.entities[ally].attack,1);self.assertEqual(g.state.entities[eid].attack,1)
        self.assertEqual(g.registry.card(cid).triggers,());self.assertEqual(g.registry.card(cid).hand_actions[0].kind,'trade')

    def test_real_nurturer_controller_end_draw_does_not_keep_replaced_both_hero_healing(self):
        g=self.game(hand=(HURT,NURTURER));self.play(g,HURT);self.play(g,NURTURER)
        cid=self.choose(g,HEAL,LOOT,'bottom');self.play(g,cid);g.apply(EndTurn(1))
        self.assertEqual(len(self.own_draws(g)),1);self.assertEqual((self.hp(g),self.hp(g,2)),(26,26))
        g.apply(EndTurn(2));self.assertEqual(len(self.own_draws(g)),2)

    def test_real_deathrattle_source_either_end_prefix_draws_for_controller_on_both_ends(self):
        g=self.game(hand=(FLESH,),mode='flesh');self.play(g,FLESH)
        cid=self.choose(g,LOOT,GOLEM,'top');self.play(g,cid);g.apply(EndTurn(1))
        self.assertEqual(len(self.own_draws(g)),1);g.apply(EndTurn(2));self.assertEqual(len(self.own_draws(g)),3)

    def test_real_fetcher_elusive_prefix_keeps_hero_shield_body_and_not_donor_buff(self):
        g=self.game(hand=(FETCHER,HURT),board=(UNIT,),mode='fetcher',hero='HERO_06');self.play(g,FETCHER)
        ally=g.state.players[1].board[0];cid=self.choose(g,CLOUD,BUFF,'top');eid=self.play(g,cid)
        self.assertIn(Keyword.ELUSIVE,g.state.entities[eid].keywords);self.next_turn(g)
        self.assertEqual((g.state.entities[ally].attack,g.state.entities[ally].health),(0,20))
        hero=g.state.players[1].hero_id;self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[hero].keywords)
        self.play(g,HURT);self.assertEqual((self.hp(g),self.hp(g,2)),(30,26));self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[hero].keywords)

    def test_natural_death_damage_keeps_minion_ability_kind_and_dead_self_grant_does_not_revive(self):
        cid=AssembleRecipe(LOOT,BULWARK,'bottom').card_id
        g=self.game(board=(BONUS,cid),enemy=(UNIT,UNIT),hand=(KILL,));eid=g.state.players[1].board[1];self.play(g,KILL,eid)
        rows=self.rows(g,cid);self.assertEqual(sum(x.damage_dealt for x in rows),6)
        self.assertTrue(all(x.source_id==eid and x.spell_bonus==0 and x.damage_kind=='minion_ability'for x in rows))
        self.assertEqual(self.hp(g,2),28);self.assertFalse(g.state.draw_history)
        dead=AssembleRecipe(LOOT,GOLEM,'bottom').card_id;g=self.game(board=(dead,),hand=(KILL,));eid=g.state.players[1].board[0]
        self.play(g,KILL,eid);self.assertFalse(g.state.players[1].board)
        self.assertTrue(any(e.kind=='effect_skipped'and e.target_id==eid for e in g.events))

    def test_battlecry_granted_reborn_is_consumed_and_rebirth_does_not_repeat_battlecry(self):
        cid=AssembleRecipe(CURATOR,GOLEM,'bottom').card_id;g=self.game(hand=(cid,KILL,KILL));eid=self.play(g,cid)
        self.assertIn(Keyword.REBORN,g.state.entities[eid].keywords);self.play(g,KILL,eid)
        child=g.state.players[1].board[0];self.assertNotEqual(child,eid);self.assertEqual(g.state.entities[child].card_id,cid)
        self.assertEqual(g.state.entities[child].health,1);self.assertNotIn(Keyword.REBORN,g.state.entities[child].keywords)
        self.play(g,KILL,child);self.assertFalse(g.state.players[1].board)

    def test_either_end_after_control_change_uses_new_controller_and_silence_stops_body(self):
        cid=AssembleRecipe(GOLEM,DRAKE,'bottom').card_id;g=self.game(board=(cid,),hand=(GIVE,MUTE));eid=g.state.players[1].board[0]
        self.play(g,GIVE,eid);self.next_turn(g);self.assertEqual((self.hp(g),self.hp(g,2)),(22,30))
        self.play(g,MUTE,eid);self.next_turn(g);self.assertEqual((self.hp(g),self.hp(g,2)),(22,30))

    def test_native_damage_wait_restore_failed_resume_and_private_views_preserve_batch(self):
        cid=AssembleRecipe(CURATOR,BULWARK,'bottom').card_id
        g=self.game(hand=(cid,),board=(BONUS,WATCH),enemy=(UNIT,UNIT),mode='wait');self.play(g,cid)
        saved=self.portable(g);q=g.state.pending_choice;self.assertIsNotNone(q)
        with self.assertRaisesRegex(ResolutionError,'native end assembly observer fault'):g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),saved)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(sum(x.damage_dealt for x in self.rows(g,cid)),6);self.assertEqual(self.hp(g,2),28);self.portable(g)
        for pid in(1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for name in('source_guard','definition_sha256','source_sha256','card_summon_history'):
                self.assertNotIn('"'+name+'"',visible)

    def test_original_fixed_child_quantity_cause_and_full_board_use_public_summon_plan(self):
        cid=AssembleRecipe(CURATOR,KEEPER,'bottom').card_id
        g=self.game(hand=(cid,),board=(KHADGAR,UNIT,UNIT,UNIT,UNIT));eid=self.play(g,cid)
        root=g.state.card_summon_history[-1];self.assertEqual(root.plan.total,2)
        self.assertEqual((root.request.cause.source.entity_id,root.request.cause.source.card_id),(eid,cid))
        self.assertEqual([x.outcome for x in root.deliveries],['delivered','board_full'])
        child=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==CHILD)
        self.assertEqual((child.attack,child.health),(6,6));self.assertIn(Keyword.DIVINE_SHIELD,child.keywords);self.portable(g)

    def test_current_copy_silence_and_bounce_restore_printed_either_end_clock(self):
        cid=AssembleRecipe(LOOT,GOLEM,'top').card_id;g=self.game(board=(cid,),hand=(COPY,MUTE,BOUNCE));eid=g.state.players[1].board[0]
        self.play(g,COPY,eid);self.play(g,MUTE,eid);self.next_turn(g);self.assertEqual(len(self.own_draws(g)),3)
        self.play(g,BOUNCE,eid);self.play(g,cid);self.next_turn(g);self.assertEqual(len(self.own_draws(g)),8)

    def test_missing_pool_source_and_changed_child_pin_are_explicit_atomic_errors(self):
        for mode in('missing','no_pool'):
            with self.subTest(mode=mode):
                g=self.game(hand=(NURTURER,),mode=mode);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,NURTURER)
                self.assertEqual(g.snapshot(),saved)
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        r._cards[CHILD]=replace(r.card(CHILD),health=7)
        with self.assertRaisesRegex(TargetValidationError,'complete original source or child'):register_assemble_native_end_body_fragments(r)
        self.assertTrue(all(cid not in r.assemble_templates for cid in SOURCES))


if __name__=='__main__':unittest.main()
