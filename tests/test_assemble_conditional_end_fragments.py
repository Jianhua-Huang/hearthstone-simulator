"""The authored end condition uses the late native view and stays on its prefix."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_conditional_end_fragments import CARD,CONDITION,BODY,load_batch,register_assemble_conditional_end_fragments
from hs_sim.cards.native_assemble_entry_cards import FETCHER,CARETAKER,FLESH,POOL_ID
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone
from hs_sim.engine.assemble_faces import (AssemblePrefix,AssembleRecipe,CheckAssembledEndCondition,
    CONDITION_PREFIX,condition_behavior_id,printed_face,validate_template)
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import Buff,ChangeControl,ChoiceOption,Damage,Destroy,GainArmor,Heal,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,EndTurnSpec,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import RuleContext,UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import (fixture as base_fixture,META,DECK,COIN,BEAST,DRAGON,MURLOC,
    KILL,MUTE,COPY,BOUNCE,WATCH as DRAW_WATCH)

CURATOR,CAIRNE,LOOT,RUST,DOOM,ACOLYTE='CORE_KAR_061','CORE_EX1_110','CORE_EX1_096','CORE_SW_072','CORE_NEW1_021','CATA_304'
P='fixture.assemble_conditional_end.'
HIT,PLUS,GIVE,PRELUDE,OBS,FAULT,BAD=(P+x for x in('hit','plus','give','prelude','observer','fault','bad_gate'))
CTX=GenerationContext('k404-reviewed-conditional-end-fixture','experimental')
SELF=AssembleRecipe(CARD,CARD,'top').card_id
DRAW=AssembleRecipe(CARD,CURATOR,'bottom').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('no_pool');r._version+='.k404.'+mode
    for cid,body in {
        HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),),
        PLUS:lambda c:(Buff(c.target_id,health=5,source_id=c.source_id),),
        GIVE:lambda c:(ChangeControl(c.target_id,2),)}.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')))
    def fault(c):raise ResolutionError('deliberate conditional end observer fault')
    r.register_behavior(FAULT,fault)
    def bad(c):
        saved=next(x for x in c.state.end_turn_history if x.capture.subject.behavior_id.startswith(CONDITION_PREFIX))
        return (CheckAssembledEndCondition(saved.capture.id,saved.capture.subject.source_id,
            saved.capture.subject.player_id,CONDITION,BODY if mode=='self' else fixture_body(c)),)
    def fixture_body(c):
        return r.assemble_templates[CURATOR].suffix.behavior_id
    r.register_behavior(BAD,bad)
    def prelude(c):
        source=next((i for i in c.state.players[c.player_id].board if
            c.state.entities[i].card_id==CARD or c.state.entities[i].card_id.startswith('assemble:')),None)
        if source is None:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('heal','Heal',(Heal(source,1,c.source_id),)),
            ChoiceOption('hit','Wound',(Damage(source,1,c.source_id,DamageKind.EFFECT),)),
            ChoiceOption('destroy','Destroy',(Destroy(source,c.source_id),)),
            ChoiceOption('bad','Wrong accepted root',(InvokeBehavior(BAD,c.source_id,c.player_id),)),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(PRELUDE,prelude)
    r.register_card(CardDefinition(PRELUDE,PRELUDE,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('turn_ended',PRELUDE,EndTurnSpec()),)))
    def observe(c):
        if mode=='beast' and c.event.kind=='minion_summoned':
            target=c.state.entities[c.event.target_id]
            if not target.card_id.startswith('assemble:'):return ()
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('hit','Wound',
                (Damage(target.id,1,c.source_id,DamageKind.EFFECT),))),c.source_id),)
        if mode=='react' and c.health_result is not None and c.health_result.healed:
            target=c.state.entities[c.health_result.target_id]
            if target.card_id==CARD or target.card_id.startswith('assemble:'):
                return (Damage(target.id,1,c.source_id,DamageKind.EFFECT),)
        return ()
    r.register_behavior(OBS,observe)
    r.register_card(CardDefinition(OBS,OBS,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('minion_summoned',OBS),TriggerSpec('health_resolved',OBS))))
    if mode=='truthy':r._trigger_conditions[CONDITION]=lambda c:1
    if mode=='missing':r._assemble_templates.pop(CARD)
    members=(RUST,CARD,CURATOR)if mode=='beast'else (LOOT,RUST,CARD)if mode=='flesh'else(CARD,CURATOR,CAIRNE)
    if mode!='no_pool':r.register_pool(PoolDefinition(POOL_ID,'three-real-conditional-end-sources-v1',
        CTX.target_id,CTX.mode,tuple(PoolMember(x)for x in members),complete=True))
    return r


class AssembleConditionalEndTests(unittest.TestCase):
    def game(self,hand=(),board=(),mode='normal'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_09',hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),seed=404,generation_context=CTX),fixture(mode))

    def play(self,g,cid,target=None):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target_id=target));return eid
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def choose_face(self,g,cid):
        self.choose(g,next(x.id for x in g.state.pending_choice.options if x.card_id==cid))
    def draws(self,g):return [x for x in g.state.draw_history if x.player_id==1]
    def hp(self,g,eid):return (g.state.entities[eid].health,g.state.entities[eid].max_health)
    def roots(self,g,eid):return [x for x in g.state.end_turn_history if x.capture.subject.source_id==eid]
    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def test_complete_source_primary_faces_and_exact_native_end_bridge(self):
        data=load_batch();row=data['existing_dependencies'][0];r=build_registry();d=r.card(CARD)
        self.assertEqual(canonical_digest(asdict(d)),row['definition_sha256'])
        self.assertEqual(len(data['official_observations']),2)
        for obs in data['official_observations']:
            check_face(row['record'],obs['face'],obs['locale']);path=Path(obs['response_file'])
            self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
        t=r.assemble_templates[CARD];face=printed_face(d,t.prefix,t.suffix,CARD)
        self.assertEqual(replace(face,triggers=d.triggers),d)
        self.assertEqual(t.original_end_turn_id,d.triggers[0].behavior_id)
        self.assertEqual(t.prefix.end_turn,EndTurnSpec())
        self.assertTrue(face.triggers[0].behavior_id.startswith(CONDITION_PREFIX))
        self.assertEqual(recipe_options(r,CARD,CARD),())

    def test_bridge_rejects_wrong_native_identity_policy_or_other_timing(self):
        r=build_registry();t=r.assemble_templates[CARD]
        with self.assertRaises(ValueError):replace(t,original_end_turn_id=CONDITION_PREFIX+BODY)
        with self.assertRaises(ValueError):replace(t,prefix=AssemblePrefix('battlecry',condition_id=CONDITION))
        with self.assertRaises(ValueError):replace(t,original_battlecry_id='cards.native_end.matriarch')
        for updated in (replace(t,original_end_turn_id='cards.native_end.caretaker'),
                replace(t,prefix=replace(t.prefix,end_turn=EndTurnSpec('either')))):
            with self.assertRaises(ValueError):validate_template(r,updated)
        for timing in ('deathrattle','start_turn'):
            with self.assertRaises(ValueError):AssemblePrefix(timing,condition_id=CONDITION)

    def test_condition_queries_are_pure_and_reject_unaccepted_manual_context(self):
        r=fixture();before=r.fingerprint();cards=len(r.cards)
        bid=condition_behavior_id(CONDITION,BODY);body=r.behavior(bid)
        g=self.game(board=(SELF,));eid=g.state.players[1].board[0]
        with self.assertRaisesRegex(ValueError,'native Battlecry or end-turn'):body(RuleContext(g.state,eid,1))
        with self.assertRaises(UnsupportedDefinitionError):r.behavior(condition_behavior_id('always',BODY))
        for _ in range(3):r.card(SELF);r.card(DRAW);r.behavior(bid)
        self.assertEqual((r.fingerprint(),len(r.cards)),(before,cards))

    def test_native_and_assembled_gate_see_earlier_heal_instead_of_frozen_wound(self):
        for cid in (CARD,SELF):
            with self.subTest(cid=cid):
                g=self.game(board=(PRELUDE,cid),hand=(HIT,));eid=g.state.players[1].board[1]
                self.play(g,HIT,eid);g.apply(EndTurn(1));self.assertEqual(self.hp(g,eid),(2,3))
                self.choose(g,'heal');self.assertEqual(self.hp(g,eid),(6,6))
                self.assertTrue(self.roots(g,eid)[0].completed)

    def test_native_and_assembled_gate_see_earlier_damage_instead_of_frozen_full_health(self):
        for cid in (CARD,SELF):
            with self.subTest(cid=cid):
                g=self.game(board=(PRELUDE,cid));eid=g.state.players[1].board[1]
                g.apply(EndTurn(1));self.choose(g,'hit');self.assertEqual(self.hp(g,eid),(2,3))
                self.assertEqual(len(self.roots(g,eid)),1);self.assertTrue(self.roots(g,eid)[0].completed)

    def test_healing_reaction_completes_before_late_condition(self):
        g=self.game(board=(PRELUDE,SELF,OBS),hand=(HIT,),mode='react');eid=g.state.players[1].board[1]
        self.play(g,HIT,eid);g.apply(EndTurn(1));self.choose(g,'heal')
        self.assertEqual(self.hp(g,eid),(2,3));self.assertTrue(self.roots(g,eid)[0].completed)

    def test_real_fetcher_wait_restore_failed_resume_and_conditional_draw(self):
        g=self.game(hand=(FETCHER,HIT),board=(PRELUDE,));self.play(g,FETCHER);self.portable(g)
        self.choose_face(g,DRAW);before=g.state.players[1].mana;eid=self.play(g,DRAW)
        self.assertEqual(g.state.players[1].mana,before-4);self.play(g,HIT,eid);g.apply(EndTurn(1))
        saved=self.portable(g)
        for key,message in (('fault','conditional end observer fault'),('bad','running accepted subject')):
            with self.assertRaisesRegex(ResolutionError,message):self.choose(g,key)
            self.assertEqual(g.snapshot(),saved)
        self.choose(g,'heal');self.assertEqual([x.card_id for x in self.draws(g)],[BEAST,DRAGON,MURLOC])
        self.assertEqual(self.hp(g,eid),(3,3));self.assertEqual(len(self.roots(g,eid)),1)
        enemy=json.dumps(g.observe(2),ensure_ascii=False)
        for private in ('end_turn_history','end_turn_batches','source_sha256','rng_before','frame'):self.assertNotIn(private,enemy)

    def test_real_caretaker_borrowed_body_has_no_full_health_gate_or_end_clock(self):
        cid=AssembleRecipe(RUST,CARD,'bottom').card_id
        g=self.game(hand=(CARETAKER,),board=(OBS,),mode='beast');self.play(g,CARETAKER);self.choose_face(g,cid)
        eid=self.play(g,cid);self.assertIsNotNone(g.state.pending_choice)
        self.choose(g,'hit');self.assertEqual(self.hp(g,eid),(6,7))
        self.assertEqual(g.registry.card(cid).battlecry,BODY);self.assertFalse(g.registry.card(cid).triggers)
        self.assertEqual(g.state.battlecry_history[-1].source_id,eid)

    def test_real_flesh_borrowed_prefix_keeps_gate_but_only_draws(self):
        cid=AssembleRecipe(LOOT,CARD,'top').card_id
        g=self.game(hand=(FLESH,),mode='flesh');self.play(g,FLESH);self.choose_face(g,cid)
        eid=self.play(g,cid);self.assertEqual(self.hp(g,eid),(3,3));g.apply(EndTurn(1))
        self.assertEqual(len(self.draws(g)),1);self.assertEqual(self.hp(g,eid),(3,3))
        self.assertFalse(g.registry.card(cid).deathrattle);self.assertEqual(self.roots(g,eid)[0].capture.subject.player_id,1)

    def test_ungated_body_uses_native_start_window_and_dead_self_deathrattle_skip(self):
        start=AssembleRecipe(DOOM,CARD,'bottom').card_id
        g=self.game(board=(start,),hand=(HIT,));eid=g.state.players[1].board[0];self.play(g,HIT,eid)
        g.apply(EndTurn(1));self.assertEqual(self.hp(g,eid),(6,7));g.apply(EndTurn(2))
        self.assertEqual(self.hp(g,eid),(9,10))
        death=AssembleRecipe(LOOT,CARD,'bottom').card_id
        g=self.game(board=(death,),hand=(KILL,));eid=g.state.players[1].board[0];self.play(g,KILL,eid)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(self.hp(g,eid),(1,1))
        self.assertTrue(g.state.deathrattle_history[-1].completed)

    def test_extra_rechecks_health_after_first_payload_without_new_end_root(self):
        cid=AssembleRecipe(CARD,ACOLYTE,'bottom').card_id
        g=self.game(hand=(cid,PLUS),board=('ICC_901',));eid=self.play(g,cid);self.play(g,PLUS,eid)
        self.assertEqual(self.hp(g,eid),(8,8));g.apply(EndTurn(1))
        self.assertEqual(self.hp(g,eid),(4,8));roots=self.roots(g,eid)
        self.assertEqual([x.capture.repeat_index for x in roots],[0,1]);self.assertTrue(all(x.completed for x in roots))
        self.assertEqual(len({x.capture.batch_id for x in roots}),1)
        g=self.game(board=('ICC_901',SELF));eid=g.state.players[1].board[1];g.apply(EndTurn(1))
        self.assertEqual(self.hp(g,eid),(9,9));self.assertEqual(len(self.roots(g,eid)),2)

    def test_real_maul_active_end_uses_accepted_condition_without_advancing_turn(self):
        for wound,expected in ((False,(6,6)),(True,(2,3))):
            with self.subTest(wound=wound):
                g=self.game(board=(SELF,),hand=('CATA_472','CATA_472',HIT));eid=g.state.players[1].board[0]
                if wound:self.play(g,HIT,eid)
                self.play(g,'CATA_472');self.play(g,'CATA_472')
                self.assertEqual(self.hp(g,eid),expected);self.assertEqual((g.state.turn,g.state.active_player),(1,1))
                self.assertEqual(len(self.roots(g,eid)),1);self.assertTrue(self.roots(g,eid)[0].completed)
                self.assertEqual(g.state.end_turn_batches[-1].activation.kind,'effect')

    def test_accepted_condition_after_earlier_destruction_keeps_native_stale_self_policy(self):
        g=self.game(board=(PRELUDE,SELF));eid=g.state.players[1].board[1]
        g.apply(EndTurn(1));self.choose(g,'destroy')
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(self.hp(g,eid),(3,3))
        self.assertEqual(len(self.roots(g,eid)),1);self.assertTrue(self.roots(g,eid)[0].completed)

    def test_current_copy_silence_and_return_reset_keep_conditional_printed_face(self):
        g=self.game(board=(SELF,),hand=(COPY,MUTE,BOUNCE));original=g.state.players[1].board[0]
        self.play(g,COPY,original);copied=g.state.players[1].board[-1];self.play(g,MUTE,original)
        g.apply(EndTurn(1));self.assertEqual(self.hp(g,original),(3,3));self.assertEqual(self.hp(g,copied),(6,6))
        g.apply(EndTurn(2));self.play(g,BOUNCE,original);self.play(g,SELF);g.apply(EndTurn(1))
        self.assertEqual(self.hp(g,original),(6,6));self.assertEqual(self.hp(g,copied),(9,9))

    def test_current_controller_owns_the_condition_clock_and_payload(self):
        g=self.game(board=(SELF,),hand=(GIVE,));eid=g.state.players[1].board[0];self.play(g,GIVE,eid)
        g.apply(EndTurn(1));self.assertEqual(self.hp(g,eid),(3,3));g.apply(EndTurn(2))
        self.assertEqual(self.hp(g,eid),(6,6));self.assertEqual(self.roots(g,eid)[0].capture.subject.player_id,2)

    def test_deferred_reference_codec_rejects_wrong_subject_and_completed_activation(self):
        g=self.game(board=(DRAW,DRAW_WATCH));eid=g.state.players[1].board[0];g.apply(EndTurn(1))
        saved=self.portable(g);root=self.roots(g,eid)[0];body=g.registry.assemble_templates[CURATOR].suffix.behavior_id
        request=CheckAssembledEndCondition(root.capture.id,eid,1,CONDITION,body)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);self.assertEqual(codec.decode(codec.encode(request)),request)
        for bad in (replace(request,activation_id=999),replace(request,source_id=g.state.players[1].board[1]),
                replace(request,player_id=2),replace(request,behavior_id=BODY),replace(request,condition_id='always')):
            with self.assertRaises(ValueError):codec.encode(bad)
        self.assertEqual(g.snapshot(),saved)
        while g.state.pending_choice:self.choose(g,'ok')
        with self.assertRaisesRegex(ValueError,'running accepted subject'):request.validate_in_state(g.state,g.registry)

    def test_non_boolean_condition_rolls_back_the_entire_end_action(self):
        g=self.game(board=(SELF,),mode='truthy');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'explicit boolean'):g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(),saved)

    def test_missing_domain_source_pin_and_old_wire_versions_fail_explicitly(self):
        for mode in ('no_pool','missing'):
            g=self.game(hand=(FETCHER,),mode=mode);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,FETCHER)
            self.assertEqual(g.snapshot(),saved)
        r=build_registry();r._assemble_templates.pop(CARD);r._cards[CARD]=replace(r.card(CARD),health=4)
        with self.assertRaisesRegex(TargetValidationError,'complete original Matriarch'):register_assemble_conditional_end_fragments(r)
        self.assertNotIn(CARD,r.assemble_templates)
        g=self.game(board=(SELF,));saved=g.snapshot();saved['schema_version']=539
        with self.assertRaisesRegex(ValueError,'schema'):Game.from_snapshot(saved,g.registry)
        saved=g.snapshot();saved['mechanics_version']='core-effects-v659'
        with self.assertRaisesRegex(ValueError,'Mechanics version'):Game.from_snapshot(saved,g.registry)


if __name__=='__main__':unittest.main()
