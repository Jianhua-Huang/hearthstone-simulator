"""Real printed keyword consumers through ordinary entry, combat and lifecycle."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as build_registry
from hs_sim.cards import past_legendary_keywords as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (ChoiceOption,CopyMinion,Damage,InvokeBehavior,RandomDamage,
    RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest

KRUSH,MAEXXNA,BURN,REPRINT,ICE=native.ROOTS
P='k682.';A=P+'plain';SHIELD=P+'shield';HURT=P+'hurt';BOUNCE=P+'bounce';HUSH=P+'hush';COPY=P+'copy';WATCH=P+'watch';FAIL=P+'fail'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=build_registry();native.register_past_legendary_keywords(r)
    target=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    for cid,keys in((A,()),(SHIELD,(Keyword.DIVINE_SHIELD,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=40,keywords=keys,metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(HURT,lambda c:(Damage(c.state.players[c.player_id].hero_id,8,c.source_id),))
    r.register_card(CardDefinition(HURT,HURT,CardType.SPELL,on_play=HURT,metadata=metadata(collectible=False)))
    bodies={BOUNCE:lambda c:(ReturnToHand(c.target_id),),HUSH:lambda c:(Silence(c.target_id),),
        COPY:lambda c:(CopyMinion(c.target_id,c.player_id),)}
    for cid in native.ROOTS:bodies[P+'transform.'+cid]=lambda c,cid=cid:(Transform(c.target_id,cid),)
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=target,metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K682 deliberate combat choice rollback')))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in(BURN,REPRINT)or source.controller!=c.player_id:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,triggers=(TriggerSpec('damage_dealt',WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class PastLegendaryKeywordTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(A,),player=1,watch=False):
        self.mode='small';board=board+((WATCH,)if watch else())
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else(),board=board if p==player else enemy,deck=('card.1',)*20,mana=10,max_mana=10)
            for p in(1,2)),active_player=player,seed=682),fixture('writer'))

    def cycle(self,g,player=1):g.apply(EndTurn(player));g.apply(EndTurn(3-player))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')

    def test_five_complete_faces_and_both_reprints_preserve_raw_roles_and_metadata(self):
        d=native.load_batch();r=fixture()
        self.assertEqual(len(d['cards']),5);self.assertEqual(len(d['official_observations']),14)
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertFalse(d['complete_past_legendary_source_bound'])
        for row in d['cards']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        self.assertNotEqual(r.card(BURN).metadata.deck_identity,r.card(REPRINT).metadata.deck_identity)
        with patch.object(native,'BATCH_HASH',''):
            with self.assertRaises(TargetValidationError):native.load_batch()

    def test_all_five_real_paid_hand_entries_use_full_printed_stats_and_keywords(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,));self.play(g,cid);c=g.registry.card(cid);e=self.unit(g,cid)
                self.assertEqual((e.attack,e.health),(c.attack,c.health));self.assertEqual(g.state.players[1].mana,10-c.cost)
                self.assertTrue(set(native.KEYWORDS[cid])<=set(e.keywords));self.assertEqual([x.card_id for x in g.state.play_history],[cid])

    def test_real_krush_charges_enemy_hero_immediately_and_has_one_normal_attack(self):
        g=self.game((KRUSH,),enemy=());self.play(g,KRUSH);own=self.unit(g,KRUSH).id;hero=self.hero(g,2).id
        g.apply(Attack(1,own,hero));self.assertEqual(self.hero(g,2).health,22)
        saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,own,hero))
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_icehowl_charges_minions_but_cannot_attack_hero_before_or_after_waiting_a_turn(self):
        g=self.game((ICE,));self.play(g,ICE);own=self.unit(g,ICE).id;enemy=self.unit(g,A,2).id;hero=self.hero(g,2).id
        for wait in(False,True):
            if wait:self.cycle(g)
            saved=deepcopy(g.snapshot())
            with self.assertRaises(IllegalAction):g.apply(Attack(1,own,hero))
            self.assertEqual(g.snapshot(),saved)
        g.apply(Attack(1,own,enemy));self.assertEqual((g.state.entities[enemy].health,g.state.entities[own].health),(30,9));self.portable(g)

    def test_silence_removes_icehowl_restriction_and_bounce_reinstalls_printed_charge_and_policy(self):
        g=self.game((ICE,HUSH,BOUNCE),enemy=());self.play(g,ICE);own=self.unit(g,ICE).id
        self.play(g,HUSH,own);self.cycle(g);g.apply(Attack(1,own,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,20)
        self.play(g,BOUNCE,own);self.cycle(g);self.play(g,ICE);saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,own,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),saved);self.assertIn(Keyword.CHARGE,g.state.entities[own].keywords);self.portable(g)

    def test_poisonous_real_maexxna_kills_a_large_minion_only_after_actual_damage(self):
        g=self.game((MAEXXNA,));self.play(g,MAEXXNA);own=self.unit(g,MAEXXNA).id;enemy=self.unit(g,A,2).id
        self.cycle(g);g.apply(Attack(1,own,enemy));self.assertEqual(g.state.entities[enemy].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[own].health,7);self.portable(g)

    def test_divine_shield_prevents_poisonous_until_later_actual_damage(self):
        g=self.game((MAEXXNA,),enemy=(SHIELD,));self.play(g,MAEXXNA);own=self.unit(g,MAEXXNA).id;enemy=self.unit(g,SHIELD,2).id
        self.cycle(g);g.apply(Attack(1,own,enemy));self.assertEqual(g.state.entities[enemy].health,40)
        self.assertEqual(g.state.entities[enemy].zone,Zone.BOARD);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[enemy].keywords)
        self.cycle(g);g.apply(Attack(1,own,enemy));self.assertEqual(g.state.entities[enemy].zone,Zone.GRAVEYARD)

    def test_poisonous_does_not_destroy_an_enemy_hero(self):
        g=self.game((MAEXXNA,),enemy=());self.play(g,MAEXXNA);self.cycle(g)
        g.apply(Attack(1,self.unit(g,MAEXXNA).id,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,28)

    def test_both_real_burnbristles_absorb_return_damage_and_heal_actual_combat_damage(self):
        for cid in(BURN,REPRINT):
            with self.subTest(card=cid):
                g=self.game((HURT,cid));self.play(g,HURT);self.play(g,cid);self.cycle(g)
                own=self.unit(g,cid).id;enemy=self.unit(g,A,2).id;g.apply(Attack(1,own,enemy))
                self.assertEqual((self.hero(g).health,g.state.entities[own].health),(25,3))
                self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[own].keywords)

    def test_burnbristle_lifesteal_heals_zero_when_target_shield_absorbs_all_damage(self):
        g=self.game((HURT,BURN),enemy=(SHIELD,));self.play(g,HURT);self.play(g,BURN);self.cycle(g)
        g.apply(Attack(1,self.unit(g,BURN).id,self.unit(g,SHIELD,2).id));self.assertEqual(self.hero(g).health,22)

    def test_actual_taunt_blocks_wrong_target_until_burnbristle_is_silenced(self):
        g=self.game((HUSH,),board=(A,),enemy=(BURN,));own=self.unit(g,A).id;hero=self.hero(g,2).id
        saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,own,hero))
        self.assertEqual(g.snapshot(),saved);self.play(g,HUSH,self.unit(g,BURN,2).id)
        g.apply(Attack(1,own,hero));self.assertEqual(self.hero(g,2).health,29)

    def test_current_copies_preserve_real_charge_and_icehowl_hero_policy(self):
        g=self.game((ICE,COPY),enemy=(A,));self.play(g,ICE);original=self.unit(g,ICE).id;self.play(g,COPY,original)
        own=[i for i in g.state.players[1].board if g.state.entities[i].card_id==ICE];self.assertEqual(len(own),2)
        copied=next(i for i in own if i!=original);saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,copied,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),saved);g.apply(Attack(1,copied,self.unit(g,A,2).id));self.portable(g)

    def test_each_native_face_transforms_through_existing_kernel_without_losing_printed_keywords(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((P+'transform.'+cid,),board=(A,),enemy=());own=self.unit(g,A).id
                self.play(g,P+'transform.'+cid,own);e=g.state.entities[own];c=g.registry.card(cid)
                self.assertEqual((e.card_id,e.attack,e.health),(cid,c.attack,c.health));self.assertTrue(set(c.keywords)<=set(e.keywords))
                if cid==ICE:
                    saved=deepcopy(g.snapshot())
                    with self.assertRaises(IllegalAction):g.apply(Attack(1,own,self.hero(g,2).id))
                    self.assertEqual(g.snapshot(),saved)

    def test_real_lifesteal_combat_wait_restores_and_failed_choice_rolls_back_rng_and_state(self):
        g=self.game((HURT,BURN),watch=True);self.play(g,HURT);self.play(g,BURN);self.cycle(g)
        g.apply(Attack(1,self.unit(g,BURN).id,self.unit(g,A,2).id));self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(self.hero(g).health,25);self.portable(g)

    def test_second_player_real_krush_uses_correct_payment_and_enemy_hero(self):
        g=self.game((KRUSH,),enemy=(),player=2);self.play(g,KRUSH,player=2)
        g.apply(Attack(2,self.unit(g,KRUSH,2).id,self.hero(g,1).id));self.assertEqual(self.hero(g,1).health,22)
        self.assertEqual(g.state.players[2].mana,1);self.portable(g)

    def test_real_standard_host_can_normally_use_new_past_dependency_without_claiming_parent_pool_bound(self):
        self.mode='host';h=host('writer')
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(KRUSH,),deck=('CORE_CS2_120',)*8,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=('CORE_CS2_120',),deck=('CORE_CS2_120',)*8,mana=10,max_mana=10)),seed=682,generation_context=h.context),h.registry)
        self.play(g,KRUSH);own=self.unit(g,KRUSH).id;enemy=g.state.players[2].board[0]
        g.apply(Attack(1,own,enemy));self.assertEqual(g.state.entities[enemy].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].mana,1);self.assertNotIn('MIS_701',g.registry.cards);self.portable(g)
