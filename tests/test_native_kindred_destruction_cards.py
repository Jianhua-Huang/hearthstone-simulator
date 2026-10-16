"""Real Devilsaur destroys once and rewards its original numeric material."""
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_kindred_destruction_cards import DEVILSAUR, load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    IllegalAction,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,InvokeBehavior,
    RequestChoice,ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P='k104.';BEAST='BAR_024';YETI='CORE_CS2_182';CHALLENGER='TLC_251'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry()
    def source(c):
        return next((c.state.entities[i]for p in(1,2)for i in c.state.players[p].board
            if c.state.entities[i].card_id==DEVILSAUR),None)
    def kill_source(c):
        e=source(c);return()if e is None else(Destroy(e.id,c.source_id),)
    def bounce_source(c):
        e=source(c)
        return()if e is None else(ReturnToHand(e.id),InvokeBehavior(P+'reenter',c.source_id,e.controller,e.id))
    def wait(c):
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('fail','Fail after death',(InvokeBehavior(P+'fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior(P+'kill_source',kill_source);r.register_behavior(P+'bounce_source',bounce_source)
    r.register_behavior(P+'wait',wait)
    r.register_behavior(P+'reenter',lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),))
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('Deliberate original destruction reward failure')))
    for name in('victim','kill_source','bounce_source','wait','shield','reborn'):
        kw={}
        if name in('kill_source','bounce_source','wait'):kw['deathrattle']=P+name
        if name=='shield':kw['keywords']=(Keyword.DIVINE_SHIELD,)
        if name=='reborn':kw['keywords']=(Keyword.REBORN,)
        r.register_card(CardDefinition(P+name,name,CardType.MINION,attack=5,health=8,metadata=META,**kw))
    for name,body in [('injure',lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),)),
            ('kill',lambda c:(Destroy(c.target_id,c.source_id),))]:
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=META))
    r.validate();return r


class NativeKindredDestructionCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(BEAST,DEVILSAUR),board=(),enemy=(P+'victim',),active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand if active==1 else(),board=board if active==1 else enemy,
                deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=hand if active==2 else(),board=board if active==2 else enemy,
                deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        ),active_player=active,seed=104),self.r)
    def find(self,g,cid=DEVILSAUR,p=None,zone='hand'):
        return next(i for i in getattr(g.state.players[p or g.state.active_player],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=DEVILSAUR,target=None):
        p=g.state.active_player;i=self.find(g,cid)
        g.apply(PlayCard(p,i,target,position=len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return i
    def cycle(self,g):
        p=g.state.active_player;g.apply(EndTurn(p));g.apply(EndTurn(3-p))
    def qualified(self,**kwargs):
        g=self.game(**kwargs);self.play(g,BEAST);self.cycle(g);return g
    def target(self,g,cid=P+'victim'):return self.find(g,cid,3-g.state.active_player,'board')
    def stats(self,g,i):
        e=g.state.entities[i];return(e.attack,e.health,e.max_health)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            text=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for private in('KindredActivation','MinionReference','first_death_id','owner_turn_history','resolution_frame'):
                self.assertNotIn(private,text)
        return other

    def test_full_raw_metadata_and_real_mixed_profile(self):
        row=load_batch()['cards'][0];card=self.r.card(DEVILSAUR)
        self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(card.metadata,replace(metadata_from_record(row['record']),deck_identity=DEVILSAUR))
        self.assertEqual((card.cost,card.attack,card.health),(7,3,3))
        p=self.r.kindred_profiles[DEVILSAUR];self.assertIsNotNone(p.prepare);self.assertIsNotNone(p.active)
        self.assertIsNotNone(card.battlecry);self.assertNotIn(DEVILSAUR,self.r.kindred_target_profiles)

    def test_inactive_still_destroys_once_without_stat_reward(self):
        g=self.game();target=self.target(g);source=self.play(g,target=target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(self.stats(g,source),(3,3,3))
        self.assertEqual(g.state.kindred_history[-1].plan,('prepare',));self.assertEqual(len(g.state.death_history),1)
        self.assertEqual(g.state.players[1].mana,33)

    def test_ordinary_target_requirement_stays_active_when_kindred_false(self):
        g=self.game();before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_active_gains_original_attack_and_health_after_actual_death(self):
        g=self.qualified();target=self.target(g);source=self.play(g,target=target)
        self.assertEqual(self.stats(g,source),(8,11,11));death=g.state.death_history[-1]
        self.assertEqual((death.entity_id,death.cause.kind,death.cause.source_id),(target,'destroy',source))
        self.assertEqual(g.state.kindred_history[-1].plan,('prepare','active'));self.portable(g)

    def test_injured_victim_uses_original_remaining_health_policy(self):
        g=self.qualified(hand=(BEAST,P+'injure',DEVILSAUR));target=self.target(g);self.play(g,P+'injure',target)
        self.assertEqual(g.state.entities[target].health,6);source=self.play(g,target=target)
        self.assertEqual(self.stats(g,source),(8,9,9))

    def test_friendly_original_minion_is_a_legal_victim(self):
        g=self.qualified(board=(P+'victim',),enemy=());target=self.find(g,P+'victim',1,'board')
        source=self.play(g,target=target);self.assertEqual(self.stats(g,source),(8,11,11))
        self.assertEqual(g.state.death_history[-1].controller,1)

    def test_no_initial_minion_target_allows_plain_body(self):
        g=self.game(hand=(DEVILSAUR,),enemy=());source=self.play(g)
        self.assertEqual(self.stats(g,source),(3,3,3));self.assertFalse(g.state.death_history)

    def test_target_domain_rejects_heroes_and_hand_without_payment(self):
        g=self.game();before=g.snapshot()
        for target in(g.state.players[2].hero_id,self.find(g,BEAST)):
            with self.subTest(target=target),self.assertRaises(IllegalAction):self.play(g,target=target)
            self.assertEqual(g.snapshot(),before)

    def test_real_next_kindred_duplicates_only_reward_not_destruction(self):
        g=self.qualified(hand=(BEAST,CHALLENGER,DEVILSAUR));self.play(g,CHALLENGER);target=self.target(g)
        before=g.state.players[1].mana;source=self.play(g,target=target)
        self.assertEqual(self.stats(g,source),(13,19,19));self.assertEqual(len(g.state.death_history),1)
        self.assertEqual(g.state.kindred_history[-1].plan,('prepare','active','active'))
        self.assertEqual(g.state.players[1].mana,before-7)

    def test_repeated_battlecry_does_not_reward_already_dead_target_twice(self):
        g=self.qualified(board=('TIME_064',));target=self.target(g);source=self.play(g,target=target)
        self.assertEqual(self.stats(g,source),(8,11,11));self.assertEqual(len(g.state.death_history),1)
        self.assertEqual(len([r for r in g.state.kindred_history if r.card_id==DEVILSAUR]),2)

    def test_destroy_bypasses_shield_and_does_not_copy_keywords(self):
        g=self.qualified(enemy=(P+'shield',));target=self.target(g,P+'shield');source=self.play(g,target=target)
        self.assertEqual(self.stats(g,source),(8,11,11));self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)

    def test_reborn_new_body_does_not_replace_original_reward_material(self):
        g=self.qualified(enemy=(P+'reborn',));target=self.target(g,P+'reborn');source=self.play(g,target=target)
        self.assertEqual(self.stats(g,source),(8,11,11));self.assertEqual(len(g.state.players[2].board),1)
        self.assertNotEqual(g.state.players[2].board[0],target)

    def test_victim_deathrattle_kills_original_beneficiary_no_reward(self):
        g=self.qualified(enemy=(P+'kill_source',));source=self.play(g,target=self.target(g,P+'kill_source'))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertFalse(g.state.entities[source].enchantments);self.assertEqual(len(g.state.death_history),2)

    def test_return_and_reentry_is_not_original_beneficiary(self):
        g=self.qualified(enemy=(P+'bounce_source',));source=self.play(g,target=self.target(g,P+'bounce_source'))
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertEqual(self.stats(g,source),(3,3,3))

    def test_wait_keeps_injured_original_stats_through_restore(self):
        g=self.qualified(hand=(BEAST,P+'injure',DEVILSAUR),enemy=(P+'wait',))
        target=self.target(g,P+'wait');self.play(g,P+'injure',target);source=self.play(g,target=target)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.stats(g,source),(3,3,3))
        other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.stats(g,source),(8,9,9));self.portable(g)

    def test_failed_death_choice_preserves_wait_then_one_actual_reward(self):
        g=self.qualified(enemy=(P+'wait',));source=self.play(g,target=self.target(g,P+'wait'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.stats(g,source),(8,11,11))
        self.assertTrue(g.state.kindred_history[-1].completed)

    def test_second_player_uses_actual_own_previous_turn(self):
        g=self.qualified(active=2);source=self.play(g,target=self.target(g));self.assertEqual(self.stats(g,source),(8,11,11))


if __name__=='__main__':unittest.main()
