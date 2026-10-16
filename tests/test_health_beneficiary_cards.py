"""Real health rewards and whole-group physical draw beneficiaries."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.health_beneficiary_cards import PREFIX,load_batch
from hs_sim.engine import (CardDefinition,CardType,Game,Keyword,PlayCard,PlayerSetup,
    Scenario,SelectChoice,TriggerSpec)
from hs_sim.engine.draw_beneficiaries import (ContinueMatchingDraws,DrawMatchingWithFollowup,FinishMatchingDraws)
from hs_sim.engine.effects import (AddToHand,ChangeManaCrystals,ChoiceOption,Damage,
    Destroy,Draw,GainArmor,InvokeBehavior,RequestChoice,Summon)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind,SummonQuantitySpec,Zone
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.targets import canonical_digest

BOND='EDR_262';SPARK='END_014';ROD='TIME_212';SWARM='TLC_221';STORY='TLC_231';RECIPE='JAIL_866'
WOLF='EDR_850pe';EMBER='TLC_249';YETI='CORE_CS2_182';ROOTS=(BOND,SPARK,ROD,SWARM,STORY,RECIPE)


def registry():
    r=build_registry();meta=replace(r.card(YETI).metadata,collectible=False,tribes=(),deck_identity=None)
    for key,attack,health,extra in(
        ('five',5,7,{}),('four',4,8,{}),('huge',1,40,{}),('small',1,2,{}),
        ('reborn',1,2,dict(keywords=(Keyword.REBORN,))),
        ('shield',1,40,dict(keywords=(Keyword.DIVINE_SHIELD,))),
        ('sleep',1,40,dict(dormant_turns=3)),('bonus',1,2,dict(spell_damage=1)),
        ('double',1,40,dict(summon_quantities=(SummonQuantitySpec(),))),
    ):
        r.register_card(CardDefinition('h42.'+key,key,CardType.MINION,attack=attack,health=health,metadata=meta,**extra))
    r.register_behavior('h42.fail',lambda c:(AddToHand(c.player_id,'missing.h42'),))
    def wrong_finish(c,future=False):
        row=c.state.draw_history[-1];ref=CardReference.capture(c.state.entities[row.entity_id])
        if future:ref=replace(ref,zone_epoch=ref.zone_epoch+10)
        return (FinishMatchingDraws(c.player_id,PoolQuery(kinds=(CardType.MINION,)),c.source_id,PREFIX+'story_reward',((row.id,ref),)),)
    scripts=dict(noop=lambda c:(),kill=lambda c:(Destroy(c.target_id,c.source_id),),
        cap=lambda c:(SetHandCapacity(c.player_id,1),),
        indirect=lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL,PREFIX+'bond_result'),),
        bad_finish=lambda c:wrong_finish(c),future_finish=lambda c:wrong_finish(c,True),
        wrong_draw=lambda c:(Draw(c.player_id,1,c.state.players[c.player_id].hero_id),InvokeBehavior('h42.bad_finish',c.source_id,c.player_id)),
        future_draw=lambda c:(Draw(c.player_id,1,c.source_id),InvokeBehavior('h42.future_finish',c.source_id,c.player_id)))
    for key,body in scripts.items():
        r.register_behavior('h42.'+key,body)
        if not key.endswith('finish'):r.register_card(CardDefinition('h42.'+key,key,CardType.SPELL,
            on_play='h42.'+key,requires_target=key in('kill','indirect'),metadata=meta))
    def choice(c,ok=()):
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',ok),
            ChoiceOption('bad','Rollback',(InvokeBehavior('h42.fail',c.source_id,c.player_id),))),c.source_id),)
    def damage_wait(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None:return ()
        if source.card_id==ROD and c.state.entities[c.event.target_id].controller==c.player_id:
            return choice(c,(Summon(2,'h42.huge'),))
        if source.card_id==SWARM:return choice(c)
        if source.card_id=='h42.indirect':return (Destroy(c.event.target_id,c.source_id),)
        return ()
    def draw_wait(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in(STORY,RECIPE):return ()
        ref=CardReference.capture(c.state.entities[c.event.target_id])
        options=(ChoiceOption('ok','Continue',()),ChoiceOption('extra','Unrelated draw',(Draw(1,1,c.source_id),)),
            ChoiceOption('cycle','Leave and redraw',(MoveCard(ref,1,Zone.DECK,position='top'),Draw(1,1,c.source_id))),
            ChoiceOption('cycle_only','Return to deck',(MoveCard(ref,1,Zone.DECK,position='top'),)),
            ChoiceOption('buff','Increase original Attack',(BuffStoredCard(ref,attack=1,source_id=c.source_id),)),
            ChoiceOption('bad','Rollback',(InvokeBehavior('h42.fail',c.source_id,c.player_id),)))
        return (RequestChoice(c.player_id,options,c.source_id),)
    def change_mana(c):
        source=c.state.entities.get(c.event.source_id)
        return (ChangeManaCrystals(c.player_id,-2),)if source is not None and source.card_id==RECIPE and c.state.players[c.player_id].max_mana==10 else ()
    for key,event,body in(('wait','damage_dealt',damage_wait),('draw_wait','card_drawn',draw_wait),('mana_watch','stored_card_buffed',change_mana)):
        r.register_behavior('h42.'+key,body);r.register_card(CardDefinition('h42.'+key,key,CardType.MINION,health=40,metadata=meta,
            triggers=(TriggerSpec(event,'h42.'+key),)))
    return r


class HealthBeneficiaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),deck=(),max_mana=30,mana=None,temporary=0):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=max_mana if mana is None else mana,
                max_mana=max_mana,mana_cap=40,temporary_mana=temporary),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6)),seed=811),self.registry)
    def play(self,g,cid,target=None):
        s=g.state;eid=next(i for i in s.players[1].hand if s.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,key='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def rows(self,g,cid):return [health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_card_id==cid]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def cards(self,g,player=1,zone='board'):
        s=g.state;return [s.entities[i]for i in getattr(s.players[player],zone)]

    def test_complete_six_roots_real_wolf_and_existing_cinder(self):
        data=load_batch();self.assertEqual(len(data['cards']),7)
        self.assertEqual({x['record']['id']for x in data['cards']if x['recipe']['root']},set(ROOTS))
        for row in data['cards']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        wolf=self.registry.card(WOLF);self.assertEqual((wolf.attack,wolf.health),(3,2));self.assertIn(Keyword.RUSH,wolf.keywords)
        self.assertFalse(wolf.metadata.collectible);self.assertIsNotNone(self.registry.card(EMBER).deathrattle)

    def test_bond_direct_death_summons_real_attributed_rush_wolf(self):
        g=self.game((BOND,),enemy=('h42.small',));self.play(g,BOND,g.state.players[2].board[0])
        wolf=self.cards(g)[0];self.assertEqual((wolf.card_id,wolf.attack,wolf.health),(WOLF,3,2))
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.card_id,BOND)

    def test_bond_reborn_original_death_still_rewards_but_shield_does_not(self):
        for target,expected in(('h42.reborn',1),('h42.shield',0),('h42.huge',0)):
            with self.subTest(target=target):
                g=self.game((BOND,),enemy=(target,));self.play(g,BOND,g.state.players[2].board[0])
                self.assertEqual(sum(e.card_id==WOLF for e in self.cards(g)),expected)

    def test_bond_friendly_death_frees_slot_and_full_board_preserves_damage(self):
        g=self.game((BOND,),board=('h42.small',)+('h42.huge',)*6);self.play(g,BOND,g.state.players[1].board[0])
        self.assertEqual(len(self.cards(g)),7);self.assertEqual(sum(e.card_id==WOLF for e in self.cards(g)),1)
        g=self.game((BOND,),board=('h42.huge',)*7,enemy=('h42.small',));self.play(g,BOND,g.state.players[2].board[0])
        self.assertEqual(len(self.cards(g)),7);self.assertFalse(self.cards(g,2))

    def test_bond_does_not_reward_unrelated_trigger_destruction(self):
        g=self.game(('h42.indirect',),board=('h42.wait',),enemy=('h42.huge',))
        self.play(g,'h42.indirect',g.state.players[2].board[0]);self.assertFalse(self.cards(g,2))
        self.assertFalse(any(e.card_id==WOLF for e in self.cards(g)))

    def test_spark_samples_one_current_friendly_minion_and_no_manual_choice(self):
        g=self.game((SPARK,),board=('h42.four','h42.four','h42.sleep'),enemy=('h42.small',))
        self.play(g,SPARK,g.state.players[2].board[0]);s=g.state
        self.assertIsNone(s.pending_choice);self.assertEqual(sorted(e.attack for e in self.cards(g)),[1,4,7])
        self.assertEqual(sum(e.max_health==11 for e in self.cards(g)),1)
        for p in(1,2):
            visible=json.dumps(g.player_events(p))
            self.assertNotIn('zone_epoch',visible);self.assertNotIn('entered_order',visible)

    def test_spark_nonlethal_and_empty_friendly_do_not_invent_beneficiary(self):
        g=self.game((SPARK,),board=('h42.four',),enemy=('h42.huge',));self.play(g,SPARK,g.state.players[2].board[0])
        self.assertEqual(self.cards(g)[0].attack,4)
        g=self.game((SPARK,),enemy=('h42.small',));self.play(g,SPARK,g.state.players[2].board[0])
        self.assertFalse(self.cards(g));self.assertIsNone(g.state.pending_choice)

    def test_spark_only_enemy_and_rod_only_friendly_targets(self):
        for cid,wrong in((SPARK,1),(ROD,2)):
            g=self.game((cid,),board=('h42.huge',),enemy=('h42.huge',));s=g.state;before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid,s.players[wrong].board[0])
            self.assertEqual(g.snapshot(),before)

    def test_rod_first_death_then_random_damage_and_current_spell_bonus(self):
        g=self.game((ROD,),board=('h42.bonus',),enemy=('h42.huge',));target=g.state.players[1].board[0]
        self.play(g,ROD,target);rows=self.rows(g,ROD)
        self.assertEqual([r.damage_dealt for r in rows],[3,4]);self.assertEqual([r.spell_bonus for r in rows],[1,0])
        self.assertFalse(self.cards(g))

    def test_rod_shield_still_runs_tail_and_empty_enemy_no_rng(self):
        g=self.game((ROD,),board=('h42.shield',),enemy=('h42.huge',));self.play(g,ROD,g.state.players[1].board[0])
        self.assertEqual([r.damage_dealt for r in self.rows(g,ROD)],[0,4])
        g=self.game((ROD,),board=('h42.huge',),enemy=('h42.sleep',));before=g._rng.getstate()
        self.play(g,ROD,g.state.players[1].board[0]);self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(len(self.rows(g,ROD)),1)

    def test_rod_wait_tail_requeries_new_enemy_restore_rollback_and_replay(self):
        g=self.game((ROD,),board=('h42.small','h42.wait'));self.play(g,ROD,g.state.players[1].board[0])
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.cards(g,2)[0].health,36)

    def test_swarm_actual_damage_and_overkill_not_remaining_health(self):
        for target,count in(('h42.small',3),('h42.shield',0)):
            g=self.game((SWARM,),enemy=(target,));self.play(g,SWARM,g.state.players[2].board[0])
            self.assertEqual(sum(e.card_id==EMBER for e in self.cards(g)),count)
        g=self.game((SWARM,),board=('h42.bonus',));s=g.state;self.play(g,SWARM,s.players[2].hero_id)
        self.assertEqual(sum(e.card_id==EMBER for e in self.cards(g)),4)

    def test_swarm_shared_quantity_source_and_existing_cinder_deathrattle(self):
        g=self.game((SWARM,),board=('h42.double',));s=g.state;self.play(g,SWARM,s.players[2].hero_id)
        self.assertEqual(sum(e.card_id==EMBER for e in self.cards(g)),6)
        g=self.game((SWARM,'h42.kill'));s=g.state;self.play(g,SWARM,s.players[2].hero_id)
        ember=next(e.id for e in self.cards(g)if e.card_id==EMBER);self.play(g,'h42.kill',ember)
        self.assertEqual(g.state.entities[s.players[2].hero_id].health,25)

    def test_swarm_wait_keeps_original_damage_and_full_recovery(self):
        g=self.game((SWARM,),board=('h42.wait',));s=g.state;self.play(g,SWARM,s.players[2].hero_id)
        self.assertEqual(len(self.cards(g)),1);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(sum(e.card_id==EMBER for e in self.cards(g)),3)

    def test_story_current_attack_five_or_four_and_physical_minion_selection(self):
        for cid,health,armor in(('h42.five',12,5),('h42.four',8,0)):
            g=self.game((STORY,),deck=('h42.noop',cid));original=g.state.players[1].deck[1];self.play(g,STORY);s=g.state
            self.assertEqual(s.players[1].hand,[original]);self.assertEqual(s.entities[original].max_health,health)
            self.assertEqual(s.entities[s.players[1].hero_id].armor,armor)

    def test_story_draw_reaction_current_attack_buff_qualifies(self):
        g=self.game((STORY,),board=('h42.draw_wait',),deck=('h42.four',));self.play(g,STORY);self.choose(g,'buff')
        e=self.cards(g,zone='hand')[0];self.assertEqual((e.attack,e.health),(5,13))

    def test_story_extra_unrelated_draw_never_receives_original_reward(self):
        g=self.game((STORY,),board=('h42.draw_wait',),deck=('h42.five','h42.five'));self.play(g,STORY)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in(g,other):self.choose(current,'extra')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(sorted(e.health for e in self.cards(g,zone='hand')),[7,12])

    def test_story_leave_and_redraw_same_entity_invalidates_old_hand_reference(self):
        g=self.game((STORY,),board=('h42.draw_wait',),deck=('h42.five',));self.play(g,STORY);self.choose(g,'cycle')
        s=g.state;self.assertEqual(len(s.draw_history),2);self.assertEqual(s.draw_history[0].entity_id,s.draw_history[1].entity_id)
        self.assertEqual(self.cards(g,zone='hand')[0].health,7);self.assertEqual(s.entities[s.players[1].hero_id].armor,0)

    def test_story_and_recipe_empty_matching_pool_no_draw_or_fatigue(self):
        for cid in(STORY,RECIPE):
            g=self.game((cid,),deck=('h42.noop',));before=g._rng.getstate();self.play(g,cid)
            self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),before)

    def test_story_and_recipe_burns_do_not_buff_another_card(self):
        for cid in(STORY,RECIPE):
            g=self.game(('h42.cap',cid,'h42.noop'),deck=('h42.five','h42.five'))
            self.play(g,'h42.cap');self.play(g,cid);s=g.state
            self.assertTrue(all(d.outcome=='burned'for d in s.draw_history))
            self.assertEqual([e.card_id for e in self.cards(g,zone='hand')],['h42.noop'])
            self.assertEqual(s.entities[s.players[1].hero_id].armor,0)

    def test_recipe_uses_total_capacity_not_unspent_or_temporary_mana(self):
        for maximum,temporary,mana,buff in((9,0,9,0),(10,0,10,3),(9,2,11,0)):
            g=self.game((RECIPE,),deck=('h42.five','h42.four'),max_mana=maximum,temporary=temporary,mana=mana)
            self.play(g,RECIPE);self.assertEqual(sorted(e.attack for e in self.cards(g,zone='hand')),[4+buff,5+buff])

    def test_recipe_draws_all_before_rewards_and_restores_each_wait(self):
        g=self.game((RECIPE,),board=('h42.draw_wait',),deck=('h42.five','h42.four'),max_mana=10)
        self.play(g,RECIPE);self.assertEqual(len(g.state.draw_history),1);self.assertTrue(all(e.attack in(4,5)for e in self.cards(g,zone='hand')))
        other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual(sorted(e.attack for e in self.cards(g,zone='hand')),[4,5]);self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(sorted(e.attack for e in self.cards(g,zone='hand')),[7,8])

    def test_recipe_two_attempts_same_entity_only_current_residency_buffed_once(self):
        g=self.game((RECIPE,),board=('h42.draw_wait',),deck=('h42.five',),max_mana=10)
        self.play(g,RECIPE);self.choose(g,'cycle_only');self.assertIsNotNone(g.state.pending_choice);self.choose(g)
        s=g.state;self.assertEqual(len(s.draw_history),2);self.assertEqual(s.draw_history[0].entity_id,s.draw_history[1].entity_id)
        self.assertEqual(self.cards(g,zone='hand')[0].attack,8)

    def test_recipe_callbacks_share_post_group_qualification_before_first_buff_reactions(self):
        g=self.game((RECIPE,),board=('h42.mana_watch',),deck=('h42.five','h42.four'),max_mana=10);self.play(g,RECIPE)
        self.assertEqual(g.state.players[1].max_mana,8)
        self.assertEqual(sorted(e.attack for e in self.cards(g,zone='hand')),[7,8])

    def test_draw_followup_wrong_original_source_and_future_residency_rollback(self):
        for cid in('h42.wrong_draw','h42.future_draw'):
            g=self.game((cid,),deck=('h42.five',));before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,cid)
            self.assertEqual(g.snapshot(),before)

    def test_draw_request_strict_count_owner_and_ordered_link_shapes(self):
        query=PoolQuery(kinds=(CardType.MINION,))
        for n in(True,0,-1):
            with self.assertRaises(ValueError):DrawMatchingWithFollowup(1,query,1,'known',n)
        ref=CardReference(2,1,Zone.HAND,'h42.five',1)
        with self.assertRaises(ValueError):ContinueMatchingDraws(1,query,1,'known',0,((2,ref),(1,ref)))
        with self.assertRaises(ValueError):FinishMatchingDraws(2,query,1,'known',((1,ref),))

    def test_waiting_players_cannot_see_draw_group_proofs_or_private_deck(self):
        g=self.game((RECIPE,),board=('h42.draw_wait',),deck=('h42.five','h42.four'),max_mana=10);self.play(g,RECIPE)
        for p in(1,2):
            visible=json.dumps(g.observe(p))+json.dumps(g.player_events(p))
            for token in('ContinueMatchingDraws','FinishMatchingDraws','draw_history','rng_state','candidates'):self.assertNotIn(token,visible)
        self.assertNotIn('h42.five',json.dumps(g.observe(2)))


if __name__=='__main__':unittest.main()
