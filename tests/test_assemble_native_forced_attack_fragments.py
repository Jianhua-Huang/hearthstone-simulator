"""Real text halves preserve ordered combat, lifesteal and original residences."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_native_forced_attack_fragments import CARD,load_batch,register_assemble_native_forced_attack_fragments
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import FLESH,POOL_ID
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,Destroy,Freeze,GainArmor,
    InvokeBehavior,RequestChoice,ReturnToHand,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,EndTurnSpec,Keyword,LimitedTriggerSpec,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture,META,DECK,COIN,UNIT,KILL

RUST,LOOT,DOOM,CAIRNE,KEEPER='CORE_SW_072','CORE_EX1_096','CORE_NEW1_021','CORE_EX1_110','CATA_476'
P='fixture.assemble_forced.'
A,B,C,HEAVY,TAUNT,HURT,ICE,GIVE,WATCH,FAULT,REENTER,EARLY=(P+x for x in
    ('one','two','three','heavy','taunt','hurt','ice','give','watch','fault','reenter','early'))
CTX=GenerationContext('k405-reviewed-native-forced-fixture','experimental')
SELF=AssembleRecipe(CARD,CARD,'top').card_id
PAID=AssembleRecipe(RUST,CARD,'bottom').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('no_pool');r._version+='.k405.'+mode
    for cid,attack in ((A,1),(B,2),(C,3),(HEAVY,4),(TAUNT,0)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=20,metadata=META,
            keywords=(Keyword.TAUNT,)if cid==TAUNT else()))
    for cid,body in {HURT:lambda c:tuple(Damage(c.state.players[p].hero_id,12,c.source_id,DamageKind.EFFECT)for p in(1,2)),
            ICE:lambda c:(Freeze(c.target_id),),GIVE:lambda c:(ChangeControl(c.target_id,2),)}.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=None if cid==HURT else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    def fault(c):raise ResolutionError('deliberate assembled forced-combat fault')
    r.register_behavior(FAULT,fault)
    def reenter(c):
        e=c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(e),e.controller),)
    r.register_behavior(REENTER,reenter)
    def bounce(c,eid):return (ReturnToHand(eid),InvokeBehavior(REENTER,c.source_id,c.player_id,eid))
    def watch(c):
        event=c.event;target=event.target_id;attacker=event.source_id
        if not c.state.entities[target].card_id.startswith('assemble:'):return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('defender','Return defender',bounce(c,target)),
            ChoiceOption('attacker','Return attacker',bounce(c,attacker)),
            ChoiceOption('shift','Transform defender',(Transform(target,UNIT),)),
            ChoiceOption('give','Transfer defender',(ChangeControl(target,2),)),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        limited_triggers=(LimitedTriggerSpec('attack_declared',WATCH),)))
    def early(c):
        return tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id in (CARD,SELF))
    r.register_behavior(EARLY,early)
    r.register_card(CardDefinition(EARLY,EARLY,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('turn_ended',EARLY,EndTurnSpec()),)))
    primary=LOOT if mode=='loot'else DOOM if mode=='doom'else CAIRNE if mode=='flesh'else RUST
    if mode=='missing':r._assemble_templates.pop(CARD)
    if mode!='no_pool':r.register_pool(PoolDefinition(POOL_ID,'three-real-forced-attack-sources-v1',
        CTX.target_id,CTX.mode,tuple(PoolMember(x)for x in(primary,CARD,KEEPER)),complete=True))
    return r


class AssembleNativeForcedAttackTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode='normal'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_10',hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),seed=405,generation_context=CTX),fixture(mode))
    def play(self,g,cid,target=None):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target_id=target));return eid
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def select_face(self,g,cid):self.choose(g,next(x.id for x in g.state.pending_choice.options if x.card_id==cid))
    def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
    def attacks(self,g):return [e for e in g.events if e.kind=='attack_declared']
    def completed(self,g):return [x for x in g.state.character_attack_history if x.terminal is not None and x.terminal.status=='completed']
    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def test_complete_source_two_primary_faces_and_exact_original_body(self):
        data=load_batch();row=data['existing_dependencies'][0];r=build_registry();d=r.card(CARD)
        self.assertEqual(canonical_digest(asdict(d)),row['definition_sha256']);self.assertEqual((d.cost,d.attack,d.health),(7,4,10))
        self.assertEqual(len(data['official_observations']),2)
        for obs in data['official_observations']:
            check_face(row['record'],obs['face'],obs['locale']);path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
        t=r.assemble_templates[CARD];self.assertEqual(t.suffix.behavior_id,d.triggers[0].behavior_id)
        self.assertEqual(t.prefix.keywords,(Keyword.LIFESTEAL,));self.assertEqual(t.prefix.end_turn,d.triggers[0].end_turn)

    def test_whole_face_reconstructs_and_query_does_not_mutate_registry(self):
        r=build_registry();d=r.card(CARD);before=r.fingerprint();face=r.card(SELF)
        self.assertEqual(asdict(face),asdict(d)|{'id':SELF})
        payload=r.card(PAID);self.assertNotIn(Keyword.LIFESTEAL,payload.keywords);self.assertFalse(payload.triggers)
        prefix=r.card(AssembleRecipe(LOOT,CARD,'top').card_id)
        self.assertEqual(prefix.keywords,(Keyword.LIFESTEAL,));self.assertFalse(prefix.deathrattle)
        self.assertEqual(r.fingerprint(),before)
        with self.assertRaises(UnsupportedDefinitionError):r.pool(POOL_ID,CTX)

    def test_native_and_assembled_end_order_lifesteal_and_forced_opportunities(self):
        for cid in (CARD,SELF):
            with self.subTest(cid=cid):
                g=self.game(board=(cid,TAUNT),enemy=(A,B,C),hand=(HURT,ICE));eid=g.state.players[1].board[0]
                enemies=tuple(g.state.players[2].board);self.play(g,HURT);self.play(g,ICE,enemies[0]);g.apply(EndTurn(1))
                self.assertEqual([x.source_id for x in self.attacks(g)],list(enemies));self.assertTrue(all(x.target_id==eid for x in self.attacks(g)))
                self.assertEqual(g.state.entities[eid].health,4);self.assertEqual(self.hp(g),30)
                self.assertEqual([g.state.entities[i].health for i in enemies],[16,16,16])
                self.assertEqual(len(self.completed(g)),3);self.assertTrue(all(x.declaration.forced for x in self.completed(g)))
                self.assertTrue(all(g.state.entities[i].attacks_this_turn==0 for i in enemies))

    def test_real_mismatch_paid_body_has_no_lifesteal_and_stales_later_attack_after_source_death(self):
        g=self.game(hand=(MISMATCH,HURT),enemy=(HEAVY,B));self.play(g,MISMATCH);self.select_face(g,PAID);self.play(g,HURT)
        before=g.state.players[1].mana;enemies=tuple(g.state.players[2].board);eid=self.play(g,PAID)
        self.assertEqual(g.state.players[1].mana,before-3);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(len(self.attacks(g)),1);self.assertEqual(len(self.completed(g)),1)
        self.assertEqual([g.state.entities[i].health for i in enemies],[17,20]);self.assertEqual(self.hp(g),18)
        self.assertTrue(g.state.battlecry_history[-1].completed);self.assertNotIn(Keyword.LIFESTEAL,g.registry.card(PAID).keywords)

    def test_real_mismatch_borrowed_lifesteal_end_prefix_only_draws(self):
        cid=AssembleRecipe(LOOT,CARD,'top').card_id
        g=self.game(hand=(MISMATCH,HURT),enemy=(A,),mode='loot');self.play(g,MISMATCH);self.select_face(g,cid)
        self.play(g,HURT);eid=self.play(g,cid);g.apply(EndTurn(1))
        self.assertEqual(len([x for x in g.state.draw_history if x.player_id==1]),1)
        self.assertFalse(self.attacks(g));self.assertEqual(self.hp(g),18);self.assertIn(Keyword.LIFESTEAL,g.state.entities[eid].keywords)

    def test_real_flesh_dead_self_deathrattle_has_no_lifesteal_or_fabricated_attacks(self):
        cid=AssembleRecipe(CAIRNE,CARD,'bottom').card_id
        g=self.game(hand=(FLESH,KILL),enemy=(A,B),mode='flesh');self.play(g,FLESH);self.select_face(g,cid)
        eid=self.play(g,cid);self.assertEqual(g.state.entities[eid].max_health,7);self.play(g,KILL,eid)
        self.assertFalse(self.attacks(g));self.assertFalse(self.completed(g));self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].board,[]);self.assertTrue(g.state.deathrattle_history[-1].completed)
        self.assertEqual(g.registry.card(cid).keywords,(Keyword.TAUNT,))

    def test_real_mismatch_owner_start_body_has_no_end_clock_or_lifesteal(self):
        cid=AssembleRecipe(DOOM,CARD,'bottom').card_id
        g=self.game(hand=(MISMATCH,HURT),enemy=(A,),mode='doom');self.play(g,MISMATCH);self.select_face(g,cid)
        self.play(g,HURT);eid=self.play(g,cid);g.apply(EndTurn(1));self.assertFalse(self.attacks(g));g.apply(EndTurn(2))
        self.assertEqual(len(self.completed(g)),1);self.assertEqual(g.state.entities[eid].health,6);self.assertEqual(self.hp(g),18)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,20)

    def test_waiting_failed_resume_restoration_and_defender_reentry_stale_all_old_references(self):
        g=self.game(hand=(MISMATCH,HURT),board=(WATCH,),enemy=(A,B));self.play(g,MISMATCH);self.select_face(g,PAID)
        self.play(g,HURT);eid=self.play(g,PAID);saved=self.portable(g);original=g.state.entities[eid].entered_order
        with self.assertRaisesRegex(ResolutionError,'assembled forced-combat fault'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'defender')
        self.assertGreater(g.state.entities[eid].entered_order,original);self.assertEqual(g.state.entities[eid].health,4)
        self.assertEqual(len(self.attacks(g)),1);self.assertFalse(self.completed(g));self.assertEqual(self.hp(g),18)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[20,20])
        self.assertTrue(g.state.battlecry_history[-1].completed)
        enemy=json.dumps(g.observe(2),ensure_ascii=False)
        for private in ('attack_target_presence','character_attack_history','resolution_frame','rng_state'):self.assertNotIn(private,enemy)

    def test_attacker_reentry_cancels_only_its_original_attack_and_next_enemy_continues(self):
        g=self.game(hand=(PAID,),board=(WATCH,),enemy=(A,B));enemies=tuple(g.state.players[2].board)
        eid=self.play(g,PAID);self.choose(g,'attacker')
        self.assertEqual(len(self.attacks(g)),2);self.assertEqual(len(self.completed(g)),1)
        self.assertEqual([g.state.entities[i].health for i in enemies],[20,17]);self.assertEqual(g.state.entities[eid].health,2)

    def test_transform_in_same_defender_residence_uses_current_stats_for_all_exchanges(self):
        g=self.game(hand=(PAID,),board=(WATCH,),enemy=(A,B));eid=self.play(g,PAID);presence=g.state.entities[eid].entered_order
        self.choose(g,'shift');self.assertEqual(g.state.entities[eid].card_id,UNIT)
        self.assertEqual(g.state.entities[eid].entered_order,presence);self.assertEqual(g.state.entities[eid].health,17)
        self.assertEqual(len(self.completed(g)),2);self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[20,20])

    def test_transfer_during_first_attack_cancels_friendly_combat_and_later_pairs(self):
        g=self.game(hand=(PAID,),board=(WATCH,),enemy=(A,B));eid=self.play(g,PAID);self.choose(g,'give')
        self.assertEqual(g.state.entities[eid].controller,2);self.assertFalse(self.completed(g));self.assertEqual(len(self.attacks(g)),1)
        self.assertTrue(g.state.battlecry_history[-1].completed)

    def test_empty_enemy_body_has_no_attack_or_rng_consumption(self):
        g=self.game(hand=(PAID,));saved=g.snapshot()['rng_state'];eid=self.play(g,PAID)
        self.assertFalse(self.attacks(g));self.assertEqual(g.state.entities[eid].health,4)
        self.assertEqual(g.snapshot()['rng_state'],saved)

    def test_new_controller_owns_end_clock_and_retaliation_lifesteal(self):
        g=self.game(hand=(GIVE,HURT),board=(SELF,A));eid=g.state.players[1].board[0]
        self.play(g,HURT);self.play(g,GIVE,eid);g.apply(EndTurn(1));self.assertFalse(self.attacks(g));g.apply(EndTurn(2))
        self.assertEqual(len(self.completed(g)),1);self.assertEqual(g.state.entities[eid].health,9)
        self.assertEqual((self.hp(g),self.hp(g,2)),(18,22))

    def test_earlier_end_destruction_does_not_use_old_live_defender_material(self):
        g=self.game(board=(EARLY,SELF),enemy=(A,));eid=g.state.players[1].board[1];g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertFalse(self.attacks(g))
        roots=[x for x in g.state.end_turn_history if x.capture.subject.source_id==eid]
        self.assertEqual(len(roots),1);self.assertTrue(roots[0].completed)

    def test_missing_domain_fragment_or_changed_complete_pin_rolls_back(self):
        for mode in ('no_pool','missing'):
            g=self.game(hand=(MISMATCH,),mode=mode);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,MISMATCH)
            self.assertEqual(g.snapshot(),saved)
        r=build_registry();r._assemble_templates.pop(CARD);r._cards[CARD]=replace(r.card(CARD),health=11)
        with self.assertRaisesRegex(TargetValidationError,'complete original Terror'):register_assemble_native_forced_attack_fragments(r)
        self.assertNotIn(CARD,r.assemble_templates)


if __name__=='__main__':unittest.main()
