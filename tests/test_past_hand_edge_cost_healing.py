"""Five paid native consumers, original budgets/history, and shared recovery."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_hand_edge_cost_healing as native
from hs_sim.engine import Attack,EndTurn,Game,PlayCard,PlayerSetup,ResolutionError,Scenario,UseHeroPower
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,Draw,ForceAttack,GainArmor,
    GrantKeyword,Heal,InvokeBehavior,RandomDamage,RequestChoice,Silence)
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format

HALVERIA,SCABBS,XYRELLA,NOZDORMU,ALTRUIS=native.ROOTS
P='k720.'
A,B,SMALL,RUSH,FRAIL,DORM=(P+x for x in('plain','big','small','rush','frail','dormant'))
FREE,SPELL,INJURE,HEAL3,HEAL10,KILL,HUSH,GRANT,FORCE,DRAW2,AUTO=(P+x for x in(
    'free','spell','injure','heal3','heal10','kill','hush','grant','force','draw2','auto'))
WAIT,FAIL=P+'wait',P+'fail'
CTX=GenerationContext(P+'explicit-consumer-fixture','experimental')


@lru_cache(None)
def fixture(role='writer',host=False):
    h=build_cn37_local_pool_format()if host else None;r=h.registry if h else defaults()
    if not host:native.register_past_hand_edge_cost_healing(r)
    meta=metadata(collectible=False,tribes=())
    for cid,cost,attack,health,kw in((A,3,2,6,()),(B,6,4,8,()),(SMALL,1,1,2,()),
            (RUSH,2,2,4,(Keyword.RUSH,)),(FRAIL,1,2,1,(Keyword.RUSH,)),(DORM,1,1,3,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,keywords=kw,
            metadata=meta,**({'dormant_turns':2}if cid==DORM else {})))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(FREE,lambda c:())
    for cid,cost in((FREE,0),(SPELL,3)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=FREE,metadata=meta))
    helpers={INJURE:lambda c:(Damage(c.target_id,5,c.source_id),),
        HEAL3:lambda c:(Heal(c.target_id,3,c.source_id),),HEAL10:lambda c:(Heal(c.target_id,10,c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        GRANT:lambda c:(GrantKeyword(c.target_id,Keyword.RUSH,c.source_id),),
        FORCE:lambda c:(ForceAttack(c.target_id,c.state.players[3-c.player_id].hero_id),),
        DRAW2:lambda c:(Draw(c.player_id,2,c.source_id),),AUTO:lambda c:(CastSpell(c.player_id,FREE,c.source_id),)}
    for cid,body in helpers.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta,
            **({'targeting':TargetSpec()}if cid in(INJURE,HEAL3,HEAL10,KILL,HUSH,GRANT,FORCE)else {})))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ValueError('K720 deliberate rollback')))
    def wait(c):
        event=c.event;source=c.state.entities.get(event.source_id)
        if event.kind=='mana_changed':
            qualifies=dict(event.data).get('operation')=='ChangeManaCrystals'
        else:qualifies=source is not None and source.card_id in(native.ROOTS)
        if not qualifies:return ()
        return(RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WAIT,wait)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,health=20,metadata=meta,triggers=tuple(
        TriggerSpec(event,WAIT)for event in('stats_changed','damage_dealt','cost_modifier_added','mana_changed'))))
    r.validate();return r,h.context if h else CTX


class PastHandEdgeCostHealingTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),host=False,mana=40,maximum=40,
            enemy_mana=40,enemy_maximum=40,cap=40):
        self.mode='host'if host else'small';r,context=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(A,)*16,
            mana=mana,max_mana=maximum,mana_cap=cap,armor=500,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*16,mana=enemy_mana,
                max_mana=enemy_maximum,mana_cap=cap,armor=500,hero_power_card_id='HERO_08bp')),seed=720,generation_context=context),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def armor(self,g,p=2):return g.state.entities[g.state.players[p].hero_id].armor
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:
            n+=1;self.assertLess(n,30);self.choose(g)
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
    def prime(self,g):self.play(g,FREE);return self.play(g,SCABBS)

    def test_complete_five_faces_twelve_primary_responses_and_full_past(self):
        d=native.load_batch();self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['official_observations']),12);self.assertFalse(d['complete_past_source_bound'])
        self.assertNotIn('MIS_701',fixture()[0].cards)
        for cid in native.ROOTS:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))

    def test_Halveria_paid_Rush_and_completed_self_attack_buff_entire_friendly_board(self):
        g=self.game((HALVERIA,RUSH),board=(A,),enemy=(A,));source=self.play(g,HALVERIA)
        g.apply(Attack(1,source,self.unit(g,A,2).id))
        self.assertEqual((g.state.entities[source].attack,self.unit(g,A).attack),(5,3))
        self.assertEqual(self.entity(g,RUSH).attack,2);self.assertEqual(self.unit(g,A,2).attack,2)
        self.assertEqual(g.state.players[1].mana,36)

    def test_Halveria_original_Rush_attacker_can_die_and_dead_body_is_not_buffed(self):
        g=self.game((FRAIL,),board=(HALVERIA,),enemy=(B,));attacker=self.play(g,FRAIL)
        g.apply(Attack(1,attacker,self.unit(g,B,2).id))
        self.assertEqual(g.state.entities[attacker].zone,Zone.GRAVEYARD)
        self.assertEqual(self.unit(g,HALVERIA).attack,5);self.assertEqual(g.state.entities[attacker].attack,2)

    def test_Halveria_current_granted_Rush_matches_and_non_Rush_does_not(self):
        for grant in(False,True):
            with self.subTest(grant=grant):
                g=self.game((GRANT,FORCE),board=(HALVERIA,A));attacker=self.unit(g,A).id
                if grant:self.play(g,GRANT,attacker)
                self.play(g,FORCE,attacker);self.assertEqual(self.unit(g,HALVERIA).attack,5 if grant else 4)

    def test_Halveria_silence_suppresses_and_real_buff_wait_restores_original_group(self):
        g=self.game((HUSH,RUSH),board=(HALVERIA,),enemy=(A,));self.play(g,HUSH,self.unit(g,HALVERIA).id)
        attacker=self.play(g,RUSH);g.apply(Attack(1,attacker,self.unit(g,A,2).id));self.assertEqual(self.unit(g,HALVERIA).attack,4)
        g=self.game((RUSH,),board=(HALVERIA,WAIT),enemy=(A,));attacker=self.play(g,RUSH)
        g.apply(Attack(1,attacker,self.unit(g,A,2).id));self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.unit(g,HALVERIA).attack,5)

    def test_Scabbs_actual_Combo_reduces_next_two_different_card_types_and_then_stops(self):
        g=self.game((FREE,SCABBS,A,SPELL,A));self.prime(g)
        self.play(g,A);self.play(g,SPELL);self.play(g,A)
        self.assertEqual([r.cost for r in g.state.play_history],[0,4,1,1,3]);self.assertEqual(g.state.players[1].mana,31)

    def test_Scabbs_no_Combo_has_no_budget_and_zero_cost_card_consumes_one_use(self):
        g=self.game((SCABBS,A));self.play(g,SCABBS);self.play(g,A);self.assertEqual(g.state.play_history[-1].cost,3)
        g=self.game((FREE,SCABBS,FREE,A,A));self.prime(g);self.play(g,FREE);self.play(g,A);self.play(g,A)
        self.assertEqual([r.cost for r in g.state.play_history][-3:],[0,1,3])

    def test_Scabbs_hero_power_does_not_consume_card_budget(self):
        g=self.game((FREE,SCABBS,A,A));self.prime(g)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,g.state.players[2].hero_id))
        self.play(g,A);self.play(g,A);self.assertEqual([r.cost for r in g.state.play_history][-2:],[1,1])

    def test_Scabbs_budget_survives_source_death_and_expires_at_real_turn_end(self):
        g=self.game((FREE,SCABBS,KILL,A,A));source=self.prime(g);self.play(g,KILL,source)
        self.play(g,A);self.play(g,A);self.assertEqual([r.cost for r in g.state.play_history][-3:],[0,1,3])
        g=self.game((FREE,SCABBS,A));self.prime(g);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,A)
        self.assertEqual(g.state.play_history[-1].cost,3)

    def test_Scabbs_installed_budget_wait_recovers_without_duplicate_uses(self):
        g=self.game((FREE,SCABBS,A,SPELL),board=(WAIT,));self.prime(g)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.finish(g)
        self.play(g,A);self.play(g,SPELL);self.assertEqual([r.cost for r in g.state.play_history][-2:],[1,1])

    def test_Xyrella_actual_this_turn_restoration_damages_enemy_minions_only(self):
        g=self.game((INJURE,HEAL3,XYRELLA),board=(A,),enemy=(B,DORM));target=self.unit(g,A).id
        self.play(g,INJURE,target);self.play(g,HEAL3,target);armor=self.armor(g);self.play(g,XYRELLA)
        self.assertEqual(self.unit(g,B,2).health,5);self.assertEqual(self.unit(g,DORM,2).health,3)
        self.assertEqual(self.unit(g,A).health,4);self.assertEqual(self.armor(g),armor)

    def test_Xyrella_uses_actual_healing_not_nominal_overheal_and_full_target_adds_zero(self):
        g=self.game((INJURE,HEAL10,XYRELLA),board=(A,),enemy=(B,));target=self.unit(g,A).id
        self.play(g,INJURE,target);self.play(g,HEAL10,target);self.play(g,XYRELLA)
        self.assertEqual(self.unit(g,B,2).health,3)
        g=self.game((HEAL10,XYRELLA),board=(A,),enemy=(B,));self.play(g,HEAL10,self.unit(g,A).id);self.play(g,XYRELLA)
        self.assertEqual(self.unit(g,B,2).health,8)

    def test_Xyrella_healing_enemy_counts_but_healing_from_previous_turn_does_not(self):
        g=self.game((INJURE,HEAL3,XYRELLA),enemy=(A,));target=self.unit(g,A,2).id
        self.play(g,INJURE,target);self.play(g,HEAL3,target);self.play(g,XYRELLA);self.assertEqual(g.state.entities[target].health,1)
        g=self.game((INJURE,HEAL3,XYRELLA),board=(A,),enemy=(B,));target=self.unit(g,A).id
        self.play(g,INJURE,target);self.play(g,HEAL3,target);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,XYRELLA)
        self.assertEqual(self.unit(g,B,2).health,8)

    def test_Xyrella_damage_batch_wait_restores_one_frozen_amount_and_failure_rng(self):
        g=self.game((INJURE,HEAL3,XYRELLA),board=(A,WAIT),enemy=(B,B));target=self.unit(g,A).id
        self.play(g,INJURE,target);self.play(g,HEAL3,target);self.play(g,XYRELLA)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[5,5])

    def test_Nozdormu_sets_both_to_ten_empty_crystals_without_refilling_available_mana(self):
        g=self.game((NOZDORMU,),mana=4,maximum=4,enemy_mana=3,enemy_maximum=3,cap=10);self.play(g,NOZDORMU)
        self.assertEqual([(g.state.players[p].max_mana,g.state.players[p].mana)for p in(1,2)],[(10,0),(10,3)])
        g.apply(EndTurn(1));self.assertEqual(g.state.players[2].mana,10)

    def test_Nozdormu_at_ten_does_not_refresh_and_above_ten_uses_shared_removal(self):
        g=self.game((NOZDORMU,),mana=10,maximum=10,enemy_mana=7,enemy_maximum=10,cap=10);self.play(g,NOZDORMU)
        self.assertEqual((g.state.players[1].mana,g.state.players[2].mana),(6,7))
        g=self.game((NOZDORMU,),mana=15,maximum=15,enemy_mana=2,enemy_maximum=12,cap=20);self.play(g,NOZDORMU)
        self.assertEqual([(g.state.players[p].max_mana,g.state.players[p].mana,g.state.players[p].mana_cap)for p in(1,2)],[(10,10,20),(10,2,20)])

    def test_Nozdormu_second_player_entry_uses_actual_actor_first_recipients(self):
        g=self.game(enemy_hand=(NOZDORMU,),mana=4,maximum=4,enemy_mana=4,enemy_maximum=4,cap=10)
        g.apply(EndTurn(1));self.play(g,NOZDORMU,player=2)
        self.assertEqual([g.state.players[p].max_mana for p in(1,2)],[10,10])
        events=[e.player_id for e in g._events if e.kind=='mana_changed'and dict(e.data).get('operation')=='ChangeManaCrystals']
        self.assertEqual(events,[2,1])

    def test_Nozdormu_wait_between_real_player_commits_restores_then_finishes_once(self):
        g=self.game((NOZDORMU,),board=(WAIT,),mana=4,maximum=4,enemy_mana=3,enemy_maximum=3,cap=10)
        self.play(g,NOZDORMU);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual([g.state.players[p].max_mana for p in(1,2)],[10,3])
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual([g.state.players[p].max_mana for p in(1,2)],[10,10])

    def test_Altruis_original_left_right_and_single_card_are_one_trigger_each(self):
        for hand,index in(((FREE,A,SPELL),0),((A,SPELL,FREE),2),((FREE,),0)):
            with self.subTest(hand=hand):
                g=self.game(hand,board=(ALTRUIS,),enemy=(B,));eid=g.state.players[1].hand[index]
                g.apply(PlayCard(1,eid));self.assertEqual(self.unit(g,B,2).health,7);self.assertEqual(self.armor(g),499)

    def test_Altruis_middle_enemy_and_its_own_new_hand_play_do_not_trigger(self):
        g=self.game((A,FREE,A),board=(ALTRUIS,),enemy=(B,),enemy_hand=(FREE,));self.play(g,FREE)
        self.assertEqual(self.unit(g,B,2).health,8);g.apply(EndTurn(1));self.play(g,FREE,player=2)
        self.assertEqual(self.unit(g,B,2).health,8)
        g=self.game((ALTRUIS,),enemy=(B,));self.play(g,ALTRUIS);self.assertEqual(self.unit(g,B,2).health,8)

    def test_Altruis_original_hand_edge_survives_body_draw_and_automatic_cast_is_not_extra_play(self):
        for cid in(DRAW2,AUTO):
            with self.subTest(card=cid):
                g=self.game((cid,A),board=(ALTRUIS,),enemy=(B,DORM));self.play(g,cid)
                self.assertEqual(self.unit(g,B,2).health,7);self.assertEqual(self.unit(g,DORM,2).health,3)
                self.assertEqual(self.armor(g),499)

    def test_Altruis_silence_suppresses_and_real_group_damage_wait_restores_once(self):
        g=self.game((HUSH,FREE),board=(ALTRUIS,),enemy=(B,));self.play(g,HUSH,self.unit(g,ALTRUIS).id);self.play(g,FREE)
        self.assertEqual(self.unit(g,B,2).health,8)
        g=self.game((FREE,),board=(ALTRUIS,WAIT),enemy=(B,));self.play(g,FREE)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.unit(g,B,2).health,7)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.unit(g,B,2).health,7)

    def test_all_five_actual_standard_host_entries_and_complete_native_bodies(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((FREE,cid,RUSH,INJURE,HEAL3),board=(A,),enemy=(B,),host=True);self.play(g,FREE)
                if cid==XYRELLA:
                    target=self.unit(g,A).id;self.play(g,INJURE,target);self.play(g,HEAL3,target)
                source=self.play(g,cid);self.assertEqual(g.state.play_history[-1].cost,4)
                if cid==HALVERIA:
                    attacker=self.play(g,RUSH);g.apply(Attack(1,attacker,self.unit(g,B,2).id));self.assertEqual(g.state.entities[source].attack,5)
                elif cid==SCABBS:self.play(g,RUSH);self.assertEqual(g.state.play_history[-1].cost,0)
                elif cid==XYRELLA:self.assertEqual(self.unit(g,B,2).health,5)
                elif cid==NOZDORMU:self.assertEqual([g.state.players[p].max_mana for p in(1,2)],[10,10])
                else:self.play(g,RUSH);self.assertEqual(self.unit(g,B,2).health,7)
