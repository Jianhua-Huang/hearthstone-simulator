"""Real stat halves retain current queries and the native draw-before-buff stage."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_stat_buff_fragments import SOURCES,DOVE,BEFORE,DOVE_BODY,load_batch,register_assemble_stat_buff_fragments
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,Zone
from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleRecipe,before_behavior_id,validate_template
from hs_sim.engine.effects import AddToHand,Buff,ChangeControl,Damage,TriggerDeathrattles
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import CardClass,DamageKind,Keyword,LimitedTriggerSpec,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.registry import RuleContext,UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture,META,COIN,KILL,MUTE,BOUNCE,WATCH,WOUND

PROTO,BRONTO,VINE,SMITH,_,ATTACK,HEALTH,SCION,INCUBATOR,SKULL=SOURCES
LOOT,HEAL,DOOM='CORE_EX1_096','EDR_971','CORE_NEW1_021'
P='fixture.assemble_stat_buff.'
A,B,C,WEAPON,BOOST,SHRINK,NICK,GIVE,FILL,LIVE=(P+x for x in
    ('small','large','two_attack','weapon','boost','shrink','nick','give','fill','live'))
CTX=GenerationContext('k409-reviewed-stat-sources','experimental')
DECK=(COIN,B,COIN,C,A,COIN,B)+(COIN,)*8
SELF_DOVE=AssembleRecipe(DOVE,DOVE,'top').card_id
HERO={CardClass.WARRIOR:'HERO_01',CardClass.SHAMAN:'HERO_02',CardClass.ROGUE:'HERO_03',
    CardClass.PALADIN:'HERO_04',CardClass.HUNTER:'HERO_05',CardClass.DRUID:'HERO_06',
    CardClass.WARLOCK:'HERO_07',CardClass.MAGE:'HERO_08',CardClass.PRIEST:'HERO_09',
    CardClass.DEMON_HUNTER:'HERO_10',CardClass.DEATH_KNIGHT:'HERO_11'}


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('no_pool');r._version+='.k409.'+mode
    for cid,attack,health in ((A,1,3),(B,4,6),(C,2,4)):
        d=CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,metadata=META)
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=1,attack=3,durability=2,metadata=META))
    bodies={BOOST:lambda c:(Buff(c.target_id,2,3,c.source_id),),
        SHRINK:lambda c:(Buff(c.target_id,attack=-2,source_id=c.source_id),),
        NICK:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),),
        GIVE:lambda c:(ChangeControl(c.target_id,2),),
        LIVE:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_trigger_condition(FILL,lambda c:c.state.entities[c.event.target_id].card_id==SELF_DOVE)
    r.register_behavior(FILL,lambda c:(AddToHand(c.player_id,COIN,c.source_id),))
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,health=10,metadata=META,
        limited_triggers=(LimitedTriggerSpec('minion_summoned',FILL,condition_id=FILL),)))
    if mode=='missing':r._assemble_templates.pop(DOVE)
    if mode!='no_assembly':r.register_pool(PoolDefinition(POOL_ID,'three-real-stat-sources-v1',CTX.target_id,
        CTX.mode,tuple(PoolMember(x)for x in(DOVE,'CORE_GVG_114','CORE_EX1_110')),complete=True))
    return r


class AssembleStatBuffTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),deck=DECK,mode='normal',hero='HERO_08'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),
            seed=409,generation_context=CTX),fixture(mode))
    def play(self,g,cid,target=None):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target_id=target));return eid
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry);saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved
    def entity(self,g,cid,zone='hand',pid=1):
        return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def stats(self,e):return e.attack,e.health,e.max_health

    def test_ten_complete_sources_twenty_full_primary_faces_and_explicit_prototype_zero(self):
        data=load_batch();rows={x['record']['id']:x for x in data['existing_dependencies']};r=build_registry()
        self.assertEqual(tuple(rows),SOURCES);self.assertEqual(len(data['official_observations']),20)
        self.assertIsNone(rows[PROTO]['record']['attack']);self.assertNotIn('ATK',rows[PROTO]['record']['tags'])
        self.assertEqual(data['numeric_normalizations'],{PROTO:{'attack':0}});self.assertEqual(r.card(PROTO).attack,0)
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale'],numeric_normalizations=data['numeric_normalizations'].get(obs['card_id']))
            path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])

    def test_all_whole_sources_reconstruct_with_only_the_exact_native_dove_bridge(self):
        r=build_registry();fp=r.fingerprint();count=len(r.cards)
        for cid in SOURCES:
            t=r.assemble_templates[cid];d=r.card(cid);face=r.card(AssembleRecipe(cid,cid,'top').card_id)
            if cid==DOVE:
                self.assertEqual(t.original_battlecry_id,d.battlecry);self.assertEqual(t.prefix.before_behavior_id,BEFORE)
                self.assertEqual(t.suffix.behavior_id,DOVE_BODY);face=replace(face,battlecry=d.battlecry)
            else:self.assertEqual(t.suffix.behavior_id,d.battlecry or d.deathrattle)
            self.assertEqual(asdict(face),asdict(d)|{'id':face.id})
        self.assertEqual((r.fingerprint(),len(r.cards)),(fp,count))

    def test_actual_paid_stored_buffs_keep_zone_type_and_top_three_order(self):
        for source in (PROTO,BRONTO,VINE,SMITH):
            with self.subTest(source=source):
                cid=AssembleRecipe(source,source,'top').card_id;g=self.game(hand=(cid,A,WEAPON,COIN,KILL,WOUND,WOUND))
                before={i:self.stats(g.state.entities[i])for i in (*g.state.players[1].hand,*g.state.players[1].deck)}
                deck_minions=[i for i in g.state.players[1].deck if g.state.entities[i].kind==CardType.MINION]
                mana=g.state.players[1].mana;eid=self.play(g,cid)
                self.assertEqual(g.state.players[1].mana,mana-g.registry.card(cid).cost)
                if source==PROTO:self.play(g,KILL,eid)
                if source==BRONTO:
                    saved=g.snapshot()
                    with self.assertRaises(IllegalAction):self.play(g,KILL,eid)
                    self.assertEqual(g.snapshot(),saved)
                    self.play(g,WOUND);self.play(g,WOUND)
                for i in (*g.state.players[1].hand,*g.state.players[1].deck):
                    e=g.state.entities[i];old=before[i];a=h=0
                    if source==PROTO and i in g.state.players[1].hand and e.kind==CardType.MINION:a=h=1
                    if source==BRONTO and e.kind==CardType.MINION:a=h=3
                    if source==VINE and i in deck_minions[:3]:a=h=4
                    if source==SMITH and i in g.state.players[1].hand and e.kind in(CardType.MINION,CardType.WEAPON):a=2
                    self.assertEqual(self.stats(e),(old[0]+a,old[1]+h,old[2]+h))
                if source==PROTO:
                    reborn=self.entity(g,cid,'board');self.assertEqual(reborn.health,1);self.assertNotEqual(reborn.id,eid)
                    self.assertEqual(self.entity(g,A).health,4)

    def test_dove_original_and_self_recipe_draw_the_same_minion_then_buff_new_and_old_hand(self):
        for cid in (DOVE,SELF_DOVE):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,A,WEAPON,COIN));mana=g.state.players[1].mana;self.play(g,cid)
                self.assertEqual(g.state.players[1].mana,mana-3);self.assertEqual(len(g.state.draw_history),1)
                self.assertEqual(self.stats(self.entity(g,A)),(1,5,5));self.assertEqual(self.stats(self.entity(g,B)),(4,8,8))
                self.assertEqual(self.entity(g,WEAPON).attack,3);self.assertEqual(len(g.state.battlecry_history),1)

    def test_borrowing_dove_suffix_never_draws_or_keeps_old_primary_payload(self):
        cid=AssembleRecipe('CORE_KAR_061',DOVE,'bottom').card_id;g=self.game(hand=(cid,A))
        deck=tuple(g.state.players[1].deck);self.play(g,cid)
        self.assertFalse(g.state.draw_history);self.assertEqual(tuple(g.state.players[1].deck),deck)
        self.assertEqual(self.entity(g,A).health,5)

    def test_dove_prefix_replans_a_captured_hand_buff_after_draw_so_new_card_is_not_lost(self):
        cid=AssembleRecipe(SMITH,DOVE,'top').card_id;g=self.game(hand=(cid,A,WEAPON));self.play(g,cid)
        self.assertEqual(self.entity(g,B).attack,6);self.assertEqual(self.entity(g,A).attack,3)
        self.assertEqual(self.entity(g,WEAPON).attack,5);self.assertEqual(self.entity(g,A).health,3)
        self.assertEqual(len(g.state.draw_history),1);self.assertEqual(len(g.state.battlecry_history),1)

    def test_draw_wait_restores_original_boundary_and_fault_does_not_draw_or_buff_twice(self):
        cid=AssembleRecipe(SMITH,DOVE,'top').card_id;g=self.game(hand=(cid,A),board=(WATCH,));self.play(g,cid)
        self.assertEqual(self.entity(g,B).attack,4);self.assertEqual(self.entity(g,A).attack,1)
        self.assertEqual(len(g.state.draw_history),1);saved=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'assembled draw observer fault'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok')
        self.assertEqual(self.entity(g,B).attack,6);self.assertEqual(self.entity(g,A).attack,3)
        self.assertEqual(len(g.state.draw_history),1);self.assertTrue(g.state.battlecry_history[-1].completed)
        public=json.dumps(g.observe(2),ensure_ascii=False)
        for private in('before_behavior_id','candidate_card_ids','resolution_frame','dove_draw_query'):self.assertNotIn(private,public)

    def test_dove_empty_matching_deck_still_buffs_hand_without_fatigue(self):
        g=self.game(hand=(SELF_DOVE,A),deck=(COIN,)*3);self.play(g,SELF_DOVE)
        self.assertEqual(self.entity(g,A).health,5);self.assertFalse(g.state.draw_history)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_real_brann_repeats_each_draw_then_buff_in_one_paid_play(self):
        g=self.game(hand=(SELF_DOVE,A),board=('LOE_077',),deck=(B,B,COIN));eid=self.play(g,SELF_DOVE)
        self.assertEqual(g.state.players[1].mana,27);self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual(self.entity(g,A).health,7)
        drawn=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==B]
        self.assertEqual(len({e.id for e in drawn}),2);self.assertEqual(sorted(e.health for e in drawn),[8,10])
        rows=g.state.battlecry_history;self.assertEqual(len(rows),2)
        self.assertEqual([x.repeat_index for x in rows],[1,2])
        self.assertTrue(all(x.completed and x.source_id==eid and x.failure is None for x in rows))

    def test_dove_full_hand_burn_keeps_draw_result_and_buffs_only_surviving_hand(self):
        g=self.game(hand=(SELF_DOVE,)+(A,)*9,board=(FILL,));self.play(g,SELF_DOVE)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.draw_history),1)
        burned=[e for e in g.state.entities.values()if e.card_id==B and e.zone==Zone.GRAVEYARD]
        self.assertEqual(len(burned),1);self.assertEqual(burned[0].health,6)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[1].hand if g.state.entities[i].kind==CardType.MINION],[5]*9)

    def test_current_stat_doubles_use_new_carrier_and_remaining_health_on_owner_end(self):
        for donor in(ATTACK,HEALTH):
            with self.subTest(donor=donor):
                cid=AssembleRecipe(HEAL,donor,'bottom').card_id;g=self.game(hand=(cid,BOOST,NICK));eid=self.play(g,cid)
                self.play(g,BOOST,eid);self.play(g,NICK,eid);old=self.stats(g.state.entities[eid]);g.apply(EndTurn(1))
                e=g.state.entities[eid]
                self.assertEqual(self.stats(e),(old[0]*2,old[1],old[2])if donor==ATTACK else(old[0],old[1]*2,old[2]+old[1]))
                self.assertEqual(e.health<e.max_health,True);self.assertNotIn(Keyword.RUSH,e.keywords)

    def test_dead_self_double_fizzles_but_active_live_deathrattle_uses_current_stats(self):
        cid=AssembleRecipe(LOOT,ATTACK,'bottom').card_id;g=self.game(hand=(BOOST,LIVE,KILL),board=(cid,));eid=g.state.players[1].board[0]
        self.assertEqual(g.state.entities[eid].attack,2);self.play(g,BOOST,eid);self.assertEqual(g.state.entities[eid].attack,4)
        self.play(g,LIVE,eid);self.assertEqual(g.state.entities[eid].attack,8)
        self.play(g,KILL,eid);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[eid].attack,8)
        self.assertFalse(g.state.draw_history)

    def test_dynamic_wounded_count_and_hand_count_read_the_actual_new_execution_window(self):
        cid=AssembleRecipe(SCION,SCION,'top').card_id;g=self.game(hand=(cid,NICK,NICK),board=(A,B),enemy=(C,))
        self.play(g,NICK,g.state.players[1].board[0]);self.play(g,NICK,g.state.players[2].board[0]);eid=self.play(g,cid)
        self.assertEqual(self.stats(g.state.entities[eid]),(6,10,10))
        cid=AssembleRecipe(SKULL,DOVE,'top').card_id;g=self.game(hand=(cid,A,COIN));eid=self.play(g,cid)
        self.assertEqual(len(g.state.players[1].hand),3);self.assertEqual(g.state.entities[eid].health,4)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[eid].keywords)

    def test_incubator_uses_current_low_attack_other_friends_and_original_references(self):
        cid=AssembleRecipe(INCUBATOR,INCUBATOR,'top').card_id
        g=self.game(hand=(cid,BOOST,SHRINK),board=(A,B,C),enemy=(A,));a,b,c=g.state.players[1].board
        self.play(g,BOOST,a);self.play(g,SHRINK,b);eid=self.play(g,cid)
        self.assertEqual(self.stats(g.state.entities[a]),(3,6,6));self.assertNotIn(Keyword.TAUNT,g.state.entities[a].keywords)
        for i,expected in((b,(3,7,7)),(c,(3,5,5))):
            self.assertEqual(self.stats(g.state.entities[i]),expected);self.assertIn(Keyword.TAUNT,g.state.entities[i].keywords)
        self.assertEqual(g.state.entities[eid].health,3);self.assertNotIn(Keyword.TAUNT,g.state.entities[eid].keywords)
        self.assertEqual(self.entity(g,A,'board',2).health,3)

    def test_new_controlled_death_uses_new_controller_hand_and_no_old_draw_or_reborn(self):
        cid=AssembleRecipe(LOOT,PROTO,'bottom').card_id;g=self.game(hand=(GIVE,KILL,A),board=(cid,),enemy_hand=(A,));eid=g.state.players[1].board[0]
        self.play(g,GIVE,eid);self.play(g,KILL,eid)
        self.assertEqual(self.stats(self.entity(g,A)),(1,3,3));self.assertEqual(self.stats(self.entity(g,A,pid=2)),(2,4,4))
        self.assertFalse(g.state.draw_history);self.assertFalse(g.state.players[2].board)

    def test_owner_start_stored_buff_keeps_owner_clock_and_new_recipe_return_material(self):
        cid=AssembleRecipe(DOOM,BRONTO,'bottom').card_id;g=self.game(hand=(A,),board=(cid,));aid=self.entity(g,A).id
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[aid].health,3)
        g.apply(EndTurn(2));self.assertEqual(self.stats(g.state.entities[aid]),(4,6,6))
        self.assertEqual(len(g.state.players[1].board),1)
        cid=AssembleRecipe(SMITH,PROTO,'top').card_id;g=self.game(hand=(A,WEAPON,KILL,KILL),board=(cid,));eid=g.state.players[1].board[0]
        self.play(g,KILL,eid);reborn=self.entity(g,cid,'board');self.assertEqual(reborn.health,1)
        self.play(g,KILL,reborn.id);self.assertEqual(self.entity(g,A).attack,5);self.assertEqual(self.entity(g,A).health,3)
        self.assertEqual(self.entity(g,WEAPON).attack,7);self.assertFalse(g.state.players[1].board)

    def test_actual_mismatch_entry_selects_dove_suffix_then_native_death_and_return_keep_it(self):
        hero=HERO.get(fixture().card(DOVE).metadata.classes[0],'HERO_08')
        g=self.game(hand=(MISMATCH,A,KILL,BOUNCE,MUTE),hero=hero);self.play(g,MISMATCH)
        cid=AssembleRecipe(DOVE,'CORE_EX1_110','top').card_id;q=g.state.pending_choice
        self.choose(g,next(o.id for o in q.options if o.card_id==cid));eid=self.play(g,cid)
        self.assertFalse(g.state.draw_history);self.play(g,MUTE,eid);self.play(g,BOUNCE,eid);self.play(g,cid);self.play(g,KILL,eid)
        self.assertEqual(self.entity(g,A).health,5);self.assertFalse(g.state.draw_history)

    def test_before_battlecry_requires_reviewed_timing_native_record_and_exact_original_bridge(self):
        r=fixture();bid=before_behavior_id(BEFORE,DOVE_BODY);g=self.game(board=(SELF_DOVE,));eid=g.state.players[1].board[0]
        with self.assertRaisesRegex(ValueError,'native Battlecry context'):r.behavior(bid)(RuleContext(g.state,eid,1))
        with self.assertRaises(UnsupportedDefinitionError):r.behavior(before_behavior_id(BEFORE,'unreviewed.suffix'))
        t=r.assemble_templates[DOVE]
        for timing in('deathrattle','end_turn','start_turn'):
            with self.assertRaises(ValueError):validate_template(r,replace(t,prefix=replace(t.prefix,timing=timing)))
        with self.assertRaises(ValueError):AssemblePrefix('battlecry',condition_id='always',before_behavior_id=BEFORE)
        with self.assertRaises(ValueError):validate_template(r,replace(t,original_battlecry_id='cards.conditional_battlecry.skull'))

    def test_missing_eligible_source_and_changed_complete_pin_or_query_never_partially_install(self):
        hero=HERO.get(fixture().card(DOVE).metadata.classes[0],'HERO_08')
        for mode in('missing','no_assembly'):
            g=self.game(hand=(MISMATCH,),mode=mode,hero=hero);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,MISMATCH)
            self.assertEqual(g.snapshot(),saved)
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        r._cards[SMITH]=replace(r.card(SMITH),health=6)
        with self.assertRaisesRegex(TargetValidationError,'complete original source'):register_assemble_stat_buff_fragments(r)
        self.assertFalse(set(SOURCES)&set(r.assemble_templates))
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        data=load_batch();data['dove_draw_query']['min_cost']=99
        with patch('hs_sim.cards.assemble_stat_buff_fragments.load_batch',return_value=data):
            with self.assertRaisesRegex(TargetValidationError,'Dove draw query'):register_assemble_stat_buff_fragments(r)
        self.assertFalse(set(SOURCES)&set(r.assemble_templates))


if __name__=='__main__':unittest.main()
