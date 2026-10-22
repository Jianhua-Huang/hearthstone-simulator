"""Actual before-half healing keeps the native root and original checkpoints."""
from dataclasses import asdict,replace
from functools import lru_cache
import base64
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_prefix_healing_fragments import CARD,BEFORE,BODY,DEATH_BODY,load_batch,register_assemble_prefix_healing_fragments
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID as ASSEMBLY_POOL
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,UseHandAction,Zone
from hs_sim.engine.assemble_faces import (AssemblePrefix,AssembleRecipe,AssembleSuffix,BEFORE_PREFIX,
    before_behavior_id,printed_face,validate_template)
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import ChoiceOption,Damage,GainArmor,InvokeBehavior,RequestChoice,Summon,TriggerDeathrattles
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import CardClass,CardMetadata,DamageKind,HandActionSpec,Keyword,LimitedTriggerSpec,Rarity,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.registry import RuleContext,UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_summon_companion_equipment_fragments import fixture as base_fixture
from test_assemble_draw_armor_heal_fragments import META,DECK,COIN,UNIT,KILL,COPY,MUTE,BOUNCE

LOOT,CURATOR,CAIRNE,PRIMORDIAL,SNEED,HEAL,DOOM='CORE_EX1_096','CORE_KAR_061','CORE_EX1_110','CORE_UNG_848','CORE_GVG_114','EDR_971','CORE_NEW1_021'
P='fixture.assemble_prefix_healing.'
G6,G8,HURT,LETHAL_HURT,LIVE,WATCH,FAULT,MARK=(P+x for x in
    ('six','eight_legend','hurt','lethal_hurt','live','watch','fault','marker'))
CTX=GenerationContext('k408-reviewed-before-half-fixture','experimental')
SELF=AssembleRecipe(CARD,CARD,'top').card_id
HERO={CardClass.WARRIOR:'HERO_01',CardClass.SHAMAN:'HERO_02',CardClass.ROGUE:'HERO_03',CardClass.PALADIN:'HERO_04',
    CardClass.HUNTER:'HERO_05',CardClass.DRUID:'HERO_06',CardClass.WARLOCK:'HERO_07',CardClass.MAGE:'HERO_08',
    CardClass.PRIEST:'HERO_09',CardClass.DEMON_HUNTER:'HERO_10',CardClass.DEATH_KNIGHT:'HERO_11'}


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('no_general');r._version+='.k408.'+mode
    r.register_behavior(MARK,lambda c:(GainArmor(c.player_id,7),))
    for cid,cost,rarity in ((G6,6,Rarity.COMMON),(G8,8,Rarity.LEGENDARY)):
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=4,battlecry=MARK,
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),rarity,tribes=(),factions=(),subtypes=()))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    if mode!='no_general':r.register_pool(PoolDefinition('constructed.cards','two-complete-before-half-targets-v1',CTX.target_id,
        CTX.mode,(PoolMember(G6),PoolMember(G8)),complete=True))
    if mode=='missing':r._assemble_templates.pop(CARD)
    if mode!='no_assembly':r.register_pool(PoolDefinition(ASSEMBLY_POOL,'real-cheap-before-half-domain-v1',CTX.target_id,
        CTX.mode,tuple(PoolMember(x)for x in (LOOT,CARD,CAIRNE)),complete=True))
    for cid,amount in ((HURT,12),(LETHAL_HURT,24)):
        r.register_behavior(cid,lambda c,amount=amount:tuple(Damage(c.state.players[p].hero_id,amount,c.source_id,DamageKind.EFFECT)for p in(1,2)))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    r.register_behavior(LIVE,lambda c:(TriggerDeathrattles(c.target_id,c.source_id),))
    r.register_card(CardDefinition(LIVE,LIVE,CardType.SPELL,on_play=LIVE,metadata=META,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')))
    def fault(c):raise ResolutionError('deliberate before-half healing fault')
    r.register_behavior(FAULT,fault)
    r.register_trigger_condition(WATCH,lambda c:c.health_result is not None and c.health_result.healed>0 and
        c.health_result.target_id==c.state.players[c.player_id].hero_id)
    r.register_behavior(WATCH,lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
        ChoiceOption('fill','Fill board',tuple(Summon(c.player_id,UNIT)for _ in range(6))),
        ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        limited_triggers=(LimitedTriggerSpec('health_resolved',WATCH,condition_id=WATCH),)))
    return r


class AssemblePrefixHealingTests(unittest.TestCase):
    def game(self,hand=(),board=(),mode='normal',hero='HERO_08'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),seed=408,generation_context=CTX),fixture(mode))
    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target));return eid
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def choose_face(self,g,cid):self.choose(g,next(x.id for x in g.state.pending_choice.options if x.card_id==cid))
    def hero(self,g):return g.state.entities[g.state.players[1].hero_id]
    def outputs(self,g):return [g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id in (G6,G8)]
    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry);saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def test_complete_raw_two_primary_faces_exact_old_entry_and_whole_bridge(self):
        data=load_batch();row=data['existing_dependencies'][0];r=build_registry();d=r.card(CARD)
        self.assertEqual(canonical_digest(asdict(d)),row['definition_sha256']);self.assertEqual(len(data['official_observations']),2)
        for obs in data['official_observations']:
            check_face(row['record'],obs['face'],obs['locale']);path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
        t=r.assemble_templates[CARD];face=printed_face(d,t.prefix,t.suffix,CARD)
        self.assertEqual(t.original_deathrattle_id,d.deathrattle);self.assertEqual(replace(face,deathrattle=d.deathrattle),d)
        self.assertEqual(face.deathrattle,before_behavior_id(BEFORE,DEATH_BODY));self.assertEqual(recipe_options(r,CARD,CARD),())
        self.assertEqual(t.prefix.hand_actions,(HandActionSpec('prepare','prepare',1),))

    def test_original_and_split_whole_card_heal_then_summon_one_real_six_cost(self):
        for cid in (CARD,SELF):
            with self.subTest(cid=cid):
                g=self.game(hand=(HURT,KILL),board=(cid,));eid=g.state.players[1].board[0];self.play(g,HURT);self.play(g,KILL,eid)
                self.assertEqual(self.hero(g).health,24);self.assertEqual([x.card_id for x in self.outputs(g)],[G6]);self.assertEqual(self.hero(g).armor,0)
                healing=next(e.sequence for e in g.events if e.kind=='health_resolved'and health_result(e).flow=='healing')
                birth=next(e.sequence for e in g.events if e.kind=='minion_summoned'and e.target_id==self.outputs(g)[0].id)
                self.assertLess(healing,birth);self.assertEqual(len(g.state.deathrattle_history),1);self.assertTrue(g.state.deathrattle_history[-1].completed)

    def test_replacing_front_removes_its_healing_prepare_and_old_death_clock(self):
        cid=AssembleRecipe(CARD,PRIMORDIAL,'top').card_id
        g=self.game(hand=(HURT,cid));self.play(g,HURT);eid=self.play(g,cid)
        self.assertEqual(self.hero(g).health,18);self.assertEqual([x.card_id for x in self.outputs(g)],[G6]);self.assertFalse(g.registry.card(cid).hand_actions)
        self.assertFalse(g.registry.card(cid).deathrattle);self.assertTrue(g.state.battlecry_history[-1].completed)
        self.assertEqual(g.state.entities[eid].max_health,6)

    def test_borrowing_only_summon_suffix_does_not_inherit_healing_or_prepare(self):
        cid=AssembleRecipe(CURATOR,CARD,'bottom').card_id
        g=self.game(hand=(HURT,cid));self.play(g,HURT);before=g.state.players[1].mana;self.play(g,cid)
        self.assertEqual(g.state.players[1].mana,before-5);self.assertEqual(self.hero(g).health,18)
        self.assertEqual([x.card_id for x in self.outputs(g)],[G6]);self.assertFalse(g.registry.card(cid).hand_actions)

    def test_replacing_suffix_keeps_prefix_heal_but_only_summons_legendary(self):
        cid=AssembleRecipe(CARD,SNEED,'bottom').card_id
        g=self.game(hand=(HURT,KILL),board=(cid,));eid=g.state.players[1].board[0];self.play(g,HURT);self.play(g,KILL,eid)
        self.assertEqual(self.hero(g).health,24);self.assertEqual([x.card_id for x in self.outputs(g)],[G8])
        self.assertEqual(g.registry.card(cid).hand_actions,(HandActionSpec('prepare','prepare',1),));self.assertEqual(len(g.state.deathrattle_history),1)

    def test_real_mismatch_borrowed_front_has_prepare_taunt_heal_and_one_old_draw(self):
        cid=AssembleRecipe(LOOT,CARD,'top').card_id;cls=fixture().card(CARD).metadata.classes[0]
        g=self.game(hand=(MISMATCH,HURT,KILL),hero=HERO.get(cls,'HERO_08'));self.play(g,MISMATCH);self.choose_face(g,cid);self.play(g,HURT)
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid);before=g.state.players[1].mana
        g.apply(UseHandAction(1,eid,'prepare'));self.assertEqual(g.state.players[1].mana,before-1)
        with self.assertRaises(IllegalAction):self.play(g,cid)
        g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.state.players[1].mana;self.play(g,cid)
        self.assertEqual(g.state.players[1].mana,before);self.assertIn(Keyword.TAUNT,g.state.entities[eid].keywords)
        draws=len([x for x in g.state.draw_history if x.player_id==1]);self.play(g,KILL,eid)
        self.assertEqual(len([x for x in g.state.draw_history if x.player_id==1]),draws+1);self.assertEqual(self.hero(g).health,24);self.assertFalse(self.outputs(g))

    def test_heal_reaction_waits_before_summon_and_failed_resume_does_not_heal_twice(self):
        g=self.game(hand=(HURT,KILL),board=(WATCH,SELF));eid=g.state.players[1].board[1];self.play(g,HURT);self.play(g,KILL,eid)
        self.assertEqual(self.hero(g).health,24);self.assertFalse(self.outputs(g));saved=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'before-half healing fault'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok');self.assertEqual(self.hero(g).health,24)
        self.assertEqual([x.card_id for x in self.outputs(g)],[G6]);self.assertTrue(g.state.deathrattle_history[-1].completed)
        public=json.dumps(g.observe(2),ensure_ascii=False)
        for private in ('before_behavior_id','deathrattle_history','resolution_frame','candidate_card_ids'):self.assertNotIn(private,public)

    def test_heal_reaction_can_fill_capacity_before_original_summon_checkpoint(self):
        g=self.game(hand=(HURT,KILL),board=(WATCH,SELF));eid=g.state.players[1].board[1];self.play(g,HURT);self.play(g,KILL,eid)
        rng=g.snapshot()['rng_state'];self.choose(g,'fill');self.assertEqual(self.hero(g).health,24)
        self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(self.outputs(g));self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_live_deathrattle_and_repeats_keep_both_halves_in_each_original_activation(self):
        g=self.game(hand=(HURT,LIVE),board=('FP1_031',SELF));eid=g.state.players[1].board[1];self.play(g,HURT);self.play(g,LIVE,eid)
        self.assertEqual(self.hero(g).health,30);self.assertEqual([x.card_id for x in self.outputs(g)],[G6,G6])
        self.assertEqual(g.state.entities[eid].zone,Zone.BOARD);self.assertFalse(g.state.death_history)
        rows=g.state.deathrattle_history;self.assertEqual(len(rows),2);self.assertEqual([x.capture.repeat_index for x in rows],[1,2])
        self.assertTrue(all(x.completed and x.capture.origin=='effect'for x in rows))

    def test_healing_conversion_terminal_abandons_suffix_without_rng_or_extra_cast(self):
        g=self.game(hand=(LETHAL_HURT,KILL),board=('EX1_591',SELF));eid=g.state.players[1].board[1]
        self.play(g,LETHAL_HURT);rng=g.snapshot()['rng_state'];self.play(g,KILL,eid)
        self.assertEqual(g.state.status,'finished');self.assertEqual(g.state.winner,2);self.assertFalse(self.outputs(g));self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_body_alone_owner_start_and_end_summon_without_source_healing(self):
        for primary in (HEAL,DOOM):
            with self.subTest(primary=primary):
                cid=AssembleRecipe(primary,CARD,'bottom').card_id;g=self.game(hand=(HURT,cid));self.play(g,HURT);self.play(g,cid)
                g.apply(EndTurn(1))
                if primary==DOOM:g.apply(EndTurn(2))
                self.assertEqual([x.card_id for x in self.outputs(g)],[G6]);self.assertEqual(self.hero(g).health,18)

    def test_before_namespace_canonical_authorization_and_native_context_required(self):
        r=fixture();fp=r.fingerprint();bid=before_behavior_id(BEFORE,DEATH_BODY);body=r.behavior(bid)
        g=self.game(board=(SELF,));eid=g.state.players[1].board[0]
        with self.assertRaisesRegex(ValueError,'native Deathrattle context'):body(RuleContext(g.state,eid,1))
        for before,after in (('unreviewed.before',DEATH_BODY),(BEFORE,BODY)):
            with self.assertRaises(UnsupportedDefinitionError):r.behavior(before_behavior_id(before,after))
        with self.assertRaises(ValueError):before_behavior_id(BEFORE_PREFIX+'nested',DEATH_BODY)
        with self.assertRaises(UnsupportedDefinitionError):r.behavior(bid+'=')
        noncanonical=BEFORE_PREFIX+base64.urlsafe_b64encode(json.dumps(dict(before_behavior_id=BEFORE,behavior_id=DEATH_BODY)).encode()).decode().rstrip('=')
        with self.assertRaises(UnsupportedDefinitionError):r.behavior(noncanonical)
        with self.assertRaises(UnsupportedDefinitionError):r.behavior(BEFORE_PREFIX+'x'*8193)
        self.assertEqual(r.fingerprint(),fp)

    def test_prefix_and_original_bridge_reject_wrong_timing_condition_or_native_identity(self):
        r=build_registry();t=r.assemble_templates[CARD]
        for timing in ('end_turn','start_turn','battlecry_deathrattle'):
            with self.assertRaises(ValueError):AssemblePrefix(timing,before_behavior_id=BEFORE)
        with self.assertRaises(ValueError):AssemblePrefix('deathrattle',condition_id='always',before_behavior_id=BEFORE)
        with self.assertRaises(ValueError):replace(t,original_deathrattle_id=BEFORE_PREFIX+'fake')
        with self.assertRaises(ValueError):validate_template(r,replace(t,original_deathrattle_id='cards.native_end.terror'))
        with self.assertRaises(ValueError):AssembleSuffix(before_behavior_id(BEFORE,DEATH_BODY),('deathrattle',))
        with self.assertRaisesRegex(ValueError,'namespace is reserved'):r.register_behavior(BEFORE_PREFIX+'forged',lambda c:())

    def test_changed_whole_pin_missing_domain_and_fragment_rollback(self):
        for mode in ('no_assembly','missing'):
            cls=fixture().card(CARD).metadata.classes[0];g=self.game(hand=(MISMATCH,),mode=mode,hero=HERO.get(cls,'HERO_08'));saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,MISMATCH)
            self.assertEqual(g.snapshot(),saved)
        g=self.game(hand=(HURT,KILL),board=(SELF,),mode='no_general');self.play(g,HURT);saved=g.snapshot();eid=g.state.players[1].board[0]
        with self.assertRaises(ResolutionError):self.play(g,KILL,eid)
        self.assertEqual(g.snapshot(),saved)
        r=build_registry();r._assemble_templates.pop(CARD);r._cards[CARD]=replace(r.card(CARD),health=7)
        with self.assertRaisesRegex(TargetValidationError,'complete original Soothsayer'):register_assemble_prefix_healing_fragments(r)
        self.assertNotIn(CARD,r.assemble_templates)

    def test_silence_removes_prefix_and_return_restores_complete_new_face(self):
        g=self.game(hand=(HURT,MUTE,BOUNCE,KILL),board=(SELF,));eid=g.state.players[1].board[0];self.play(g,HURT)
        self.play(g,MUTE,eid);self.assertFalse(g.state.entities[eid].keywords);self.play(g,BOUNCE,eid);self.play(g,SELF)
        self.play(g,KILL,eid);self.assertEqual(self.hero(g).health,24);self.assertEqual([x.card_id for x in self.outputs(g)],[G6])


if __name__=='__main__':unittest.main()
