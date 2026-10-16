"""Real native play listeners: original recipient, qualification, RNG and lifecycle."""
from dataclasses import replace
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.played_minion_keyword_cards import load_batch
from hs_sim.engine import Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,TriggerSpec,UseHeroPower,Zone
from hs_sim.engine.bonus_effects import BONUS_EFFECTS
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import AddToHand,Destroy,InvokeBehavior,ReturnToHand,Silence,Summon,Transform
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference
from hs_sim.engine.play_history import play_record
from hs_sim.targets import canonical_digest

OVERSEER='JAIL_880';RAPTOR='EDR_849';DR='CORE_CFM_120';YETI='CORE_CS2_182'


def registry():
    r=build_registry()
    bodies=dict(empty=lambda c:(),kill=lambda c:(Destroy(c.target_id,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        summon=lambda c:(Summon(c.player_id,DR,c.source_id),),die=lambda c:(Destroy(c.source_id,c.source_id),),
        change=lambda c:(Transform(c.source_id,YETI),),
        bounce=lambda c:(ReturnToHand(c.source_id),InvokeBehavior('k60.resummon',c.source_id,c.player_id)),
        resummon=lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.source_id]),c.player_id),),
        fail=lambda c:(AddToHand(c.player_id,'k60.missing',c.source_id),))
    for key,body in bodies.items():r.register_behavior('k60.'+key,body)
    def earlier(c,transform=False):
        row=play_record(c.state,dict(c.event.data)['play_id'])
        if row.kind!=CardType.MINION or row.source_id==c.source_id:return ()
        return(Transform(row.source_id,YETI),)if transform else(ReturnToHand(row.source_id),InvokeBehavior('k60.resummon',row.source_id,row.player_id))
    for name,transform in [('returner',False),('shifter',True)]:
        r.register_behavior('k60.'+name,lambda c,t=transform:earlier(c,t))
        r.register_card(CardDefinition('k60.'+name,name,CardType.MINION,health=3,triggers=(TriggerSpec('card_played','k60.'+name),)))
    for key in ('kill','silence','summon'):
        r.register_card(CardDefinition('k60.'+key,key,CardType.SPELL,on_play='k60.'+key,requires_target=key!='summon'))
    for key in ('die','change','bounce'):
        r.register_card(CardDefinition('k60.'+key,key,CardType.MINION,attack=1,health=2,battlecry='k60.'+key,deathrattle='k60.empty'))
    r.register_card(CardDefinition('k60.bad_listener','Rollback-only listener',CardType.MINION,health=3,triggers=(TriggerSpec('card_played','k60.fail'),)))
    return r


class PlayedMinionKeywordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),seed=1060):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_05',hero_power_card_id='HERO_05bp',hand=hand,board=board,deck=(YETI,)*5,mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=enemy_hand,board=enemy,deck=(YETI,)*5,mana=20,max_mana=20,mana_cap=20)),seed=seed),self.r)
    def entity(self,g,cid,p=1,zone='board'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        eid=self.entity(g,cid,p,zone='hand').id;g.apply(PlayCard(p,eid,target));return eid
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(s,registry()).snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
    def test_complete_original_rows_and_two_expected_scripts(self):
        d=load_batch();self.assertEqual([x['record']['id']for x in d['cards']],[OVERSEER,RAPTOR])
        for x in d['cards']:self.assertEqual(canonical_digest(x['record']),x['record_sha256'])
    def test_overseer_grants_real_played_deathrattle_minion_rush(self):
        g=self.game((DR,),(OVERSEER,));eid=self.play(g,DR);self.assertIn(Keyword.RUSH,g.state.entities[eid].keywords);self.portable(g)
    def test_overseer_ignores_plain_minion(self):
        g=self.game((YETI,),(OVERSEER,));eid=self.play(g,YETI);self.assertNotIn(Keyword.RUSH,g.state.entities[eid].keywords)
    def test_overseer_ignores_effect_summon(self):
        g=self.game(('k60.summon',),(OVERSEER,));self.play(g,'k60.summon');self.assertNotIn(Keyword.RUSH,self.entity(g,DR).keywords)
    def test_overseer_ignores_opponents_paid_minion(self):
        g=self.game(board=(OVERSEER,),enemy_hand=(DR,));g.apply(EndTurn(1));eid=self.play(g,DR,p=2);self.assertNotIn(Keyword.RUSH,g.state.entities[eid].keywords)
    def test_overseer_silence_prevents_following_grant(self):
        g=self.game(('k60.silence',DR),(OVERSEER,));self.play(g,'k60.silence',self.entity(g,OVERSEER).id);eid=self.play(g,DR);self.assertNotIn(Keyword.RUSH,g.state.entities[eid].keywords)
    def test_granted_rush_enables_minion_attack_but_not_hero_attack(self):
        g=self.game((DR,),(OVERSEER,),enemy=(YETI,));eid=self.play(g,DR)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,eid,g.state.players[2].hero_id))
        g.apply(Attack(1,eid,self.entity(g,YETI,2).id));self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
    def test_two_overseers_keep_independent_grant_sources(self):
        g=self.game((DR,),(OVERSEER,OVERSEER));eid=self.play(g,DR);s=g.state
        grants=[x for x in s.entities[eid].abilities if x.kind=='keyword'and x.keyword==Keyword.RUSH]
        self.assertEqual({x.source_id for x in grants},set(s.players[1].board)-{eid});self.portable(g)
    def test_silence_on_rewarded_minion_removes_granted_rush(self):
        g=self.game((DR,'k60.silence'),(OVERSEER,));eid=self.play(g,DR);self.play(g,'k60.silence',eid);self.assertNotIn(Keyword.RUSH,g.state.entities[eid].keywords)
    def test_original_submitted_deathrattle_qualifies_after_same_residence_transform(self):
        g=self.game(('k60.change',),(OVERSEER,));eid=self.play(g,'k60.change');self.assertEqual(g.state.entities[eid].card_id,YETI);self.assertIn(Keyword.RUSH,g.state.entities[eid].keywords);self.portable(g)
    def test_dead_played_body_gets_no_reward(self):
        g=self.game(('k60.die',),(OVERSEER,RAPTOR));before=g.snapshot()['rng_state'];eid=self.play(g,'k60.die');self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(g.snapshot()['rng_state'],before)
    def test_original_body_reentry_is_not_rebound_for_rush(self):
        g=self.game(('k60.bounce',),(OVERSEER,));eid=self.play(g,'k60.bounce');self.assertEqual(g.state.entities[eid].zone,Zone.BOARD);self.assertEqual(sum(x.entity_id==eid for x in g.state.successful_summon_history),2);self.assertNotIn(Keyword.RUSH,g.state.entities[eid].keywords);self.portable(g)
    def test_raptor_uses_one_existing_bonus_effect(self):
        g=self.game((YETI,),(RAPTOR,));eid=self.play(g,YETI);self.assertEqual(len(g.state.entities[eid].keywords),1);self.assertTrue(g.state.entities[eid].keywords<=set(BONUS_EFFECTS));self.portable(g)
    def test_raptor_does_not_reward_its_own_play(self):
        g=self.game((RAPTOR,));eid=self.play(g,RAPTOR);self.assertEqual(g.state.entities[eid].keywords,set())
    def test_second_raptor_is_rewarded_only_by_first(self):
        g=self.game((RAPTOR,),(RAPTOR,));old=self.entity(g,RAPTOR).id;eid=self.play(g,RAPTOR);self.assertEqual(len(g.state.entities[eid].keywords),1);self.assertEqual(g.state.entities[old].keywords,set())
    def test_raptor_does_not_reward_spell_or_its_effect_summon(self):
        g=self.game(('k60.summon',),(RAPTOR,));before=g.snapshot()['rng_state'];self.play(g,'k60.summon');self.assertEqual(self.entity(g,DR).keywords,set());self.assertEqual(g.snapshot()['rng_state'],before)
    def test_raptor_does_not_reward_enemy_play(self):
        g=self.game(board=(RAPTOR,),enemy_hand=(YETI,));g.apply(EndTurn(1));eid=self.play(g,YETI,p=2);self.assertEqual(g.state.entities[eid].keywords,set())
    def test_raptor_does_not_reward_hero_power(self):
        g=self.game(board=(RAPTOR,));before=g.snapshot()['rng_state'];g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(g.snapshot()['rng_state'],before)
    def test_two_raptors_grant_two_distinct_eligible_bonus_effects(self):
        g=self.game((YETI,),(RAPTOR,RAPTOR));eid=self.play(g,YETI);self.assertEqual(len(g.state.entities[eid].keywords),2);self.portable(g)
    def test_raptor_silence_prevents_following_reward(self):
        g=self.game(('k60.silence',YETI),(RAPTOR,));self.play(g,'k60.silence',self.entity(g,RAPTOR).id);eid=self.play(g,YETI);self.assertEqual(g.state.entities[eid].keywords,set())
    def test_raptor_does_not_rebind_a_reentered_played_body(self):
        g=self.game(('k60.bounce',),(RAPTOR,));before=g.snapshot()['rng_state'];eid=self.play(g,'k60.bounce');self.assertEqual(g.state.entities[eid].keywords,set());self.assertEqual(g.snapshot()['rng_state'],before)
    def test_prior_completed_play_reaction_cannot_rebind_either_recipient(self):
        for listener in (OVERSEER,RAPTOR):
            with self.subTest(listener=listener):
                g=self.game((DR,),('k60.returner',listener));before=g.snapshot()['rng_state'];eid=self.play(g,DR)
                self.assertEqual(g.state.entities[eid].keywords,set());self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)
    def test_prior_completed_play_transform_keeps_original_board_residence(self):
        for listener in (OVERSEER,RAPTOR):
            with self.subTest(listener=listener):
                g=self.game((DR,),('k60.shifter',listener));eid=self.play(g,DR);self.assertEqual(g.state.entities[eid].card_id,YETI)
                self.assertIn(Keyword.RUSH,g.state.entities[eid].keywords)if listener==OVERSEER else self.assertEqual(len(g.state.entities[eid].keywords),1)
                self.portable(g)
    def test_same_seed_and_native_actions_are_reproducible(self):
        a=self.game((YETI,),(RAPTOR,),seed=204);b=self.game((YETI,),(RAPTOR,),seed=204);self.play(a,YETI);self.play(b,YETI);self.assertEqual(a.snapshot(),b.snapshot())
    def test_both_real_sources_can_reward_one_actual_paid_deathrattle_minion(self):
        g=self.game((DR,),(OVERSEER,RAPTOR));eid=self.play(g,DR);keys=g.state.entities[eid].keywords;self.assertIn(Keyword.RUSH,keys);self.assertEqual(len(keys),2);self.portable(g)
    def test_player_queries_leave_rng_and_private_state_unchanged(self):
        g=self.game((YETI,),(RAPTOR,OVERSEER),enemy_hand=(DR,));s=g.snapshot()
        for p in (1,2):g.for_player(p).observe();g.for_player(p).legal_actions()
        self.assertEqual(g.snapshot(),s)
    def test_failed_later_listener_rolls_back_new_bonus_and_rng(self):
        g=self.game((YETI,),(RAPTOR,'k60.bad_listener'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,YETI)
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
