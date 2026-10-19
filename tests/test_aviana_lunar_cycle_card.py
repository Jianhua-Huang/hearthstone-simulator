"""Aviana's real owner-clock program and ordinary permanent card prices."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards.aviana_lunar_cycle_card import CARD,PROGRAM,load_batch,register_aviana_lunar_cycle_card
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerEffectSpec,
    PlayerSetup,Scenario,SelectChoice,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Destroy,InvokeBehavior,
    RandomDamage,RequestChoice,Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.turn_scheduling import QueueTurns

P='aviana.test.'
FILL='CS2_182'
CASES=('CS2_182','CS2_028','CATA_472','SC_400','SC_403')
ZERO,KILL,SILENCE,CHANGE,GIVE,MAKE,SUMMON,EXTRA,FILL_AREA,WATCH=(
    P+x for x in ('zero','kill','silence','change','give','make','summon','extra','fill_area','watch'))


@lru_cache(maxsize=None)
def registry(role,mode='normal'):
    assert role in ('writer','reader')
    r=build_registry();register_aviana_lunar_cycle_card(r)
    bodies={ZERO:lambda c:(),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        SILENCE:lambda c:(Silence(c.target_id),),CHANGE:lambda c:(Transform(c.target_id,FILL),),
        GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        MAKE:lambda c:(AddToHand(c.player_id,FILL,c.source_id),),
        SUMMON:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(CARD),),SummonCause.capture(c)),),
        EXTRA:lambda c:(QueueTurns((c.player_id,)*3,c.source_id),),
        FILL_AREA:lambda c:tuple(AddPlayerEffect(c.player_id,P+'objective.'+str(i),c.source_id)for i in range(5))}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        extra={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}if cid in (KILL,SILENCE,CHANGE,GIVE)else {}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,**extra))
    for i in range(5):r.register_player_effect(PlayerEffectSpec(P+'objective.'+str(i),FILL_AREA,
        kind='objective',duration=99,tick_event='turn_started'))
    def fail(c):raise ResolutionError('Aviana deliberate rollback')
    r.register_behavior(P+'fail',fail)
    if mode in ('removed','cost','fail'):
        def watch(c):
            if c.event.player_id!=c.player_id:return ()
            if mode=='removed':
                if dict(c.event.data).get('effect_key')!=PROGRAM:return ()
            elif c.event.source_id is None or c.state.entities[c.event.source_id].card_id!=CARD:return ()
            bad=(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))
            if mode=='fail':return bad
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),ChoiceOption('fail','Fail',bad)),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,
            triggers=(TriggerSpec('player_effect_removed'if mode=='removed'else 'cost_modifier_added',WATCH),)))
    r.validate();r.freeze();return r


class AvianaCycleTests(unittest.TestCase):
    def game(self,hand=(CARD,FILL),*,mode='normal',board=(),enemy_hand=(FILL,)):
        if mode in ('removed','cost','fail'):board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(FILL,)*40,
            hero_power_card_id='HERO_08bp',mana=10,max_mana=10),PlayerSetup('HERO_08',hand=enemy_hand,
            deck=(FILL,)*40,hero_power_card_id='HERO_08bp',mana=10,max_mana=10)),seed=251895),registry('writer',mode))
    def play(self,g,cid=CARD,target=None):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target));return eid
    def next_owner(self,g,pid=1):
        while True:
            g.apply(EndTurn(g.state.active_player))
            if g.state.active_player==pid:return
    def advance(self,g,n=3,pid=1):
        for _ in range(n):self.next_owner(g,pid)
    def cost(self,g,cid=FILL,pid=1):
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        return quote_cost(g.state,g.registry,g.state.entities[eid]).amount
    def programs(self,g,pid=1):return [x for x in g.state.players[pid].player_effects if x.spec_id==PROGRAM]
    def modifiers(self,g,pid=1):return [x for x in g.state.players[pid].cost_modifiers if x.spec.set_to==1]
    def pick(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode='normal'):
        r=registry('reader'if g.registry is registry('writer',mode)else 'writer',mode)
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,r)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved);return other

    def test_a00_complete_sources_and_full_assembly_match_original_adapter(self):
        from hs_sim.cards import build_registry as assembled
        from tools.card_batch import check_face
        data=load_batch();raw=data['cards'][0]['record']
        for x in data['official_observations']:check_face(raw,x['face'],x['locale'])
        self.assertEqual(len(data['evidence_only']),2)
        full=assembled();minimal=registry('writer')
        self.assertEqual(asdict(full.card(CARD)),asdict(minimal.card(CARD)))
        self.assertEqual(asdict(full.player_effect(PROGRAM)),asdict(minimal.player_effect(PROGRAM)))

    def test_b00_third_future_owner_start_sets_all_five_kinds_and_zero_to_one_but_not_powers(self):
        g=self.game((CARD,*CASES,ZERO));self.play(g)
        self.assertEqual({g.registry.card(cid).kind for cid in CASES},{CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.HERO,CardType.LOCATION})
        for _ in range(2):
            self.next_owner(g);self.assertEqual(self.cost(g),4);self.assertEqual(len(self.programs(g)),1)
        self.next_owner(g)
        for cid in (*CASES,ZERO):self.assertEqual(self.cost(g,cid),1)
        power=g.state.entities[g.state.players[1].hero_power_id]
        self.assertEqual(quote_cost(g.state,g.registry,power).amount,2)
        self.assertEqual(self.cost(g,FILL,2),4);self.assertFalse(self.programs(g))

    def test_b01_source_death_silence_and_transform_do_not_cancel_the_owner_program(self):
        for action in (KILL,SILENCE,CHANGE):
            with self.subTest(action=action):
                g=self.game((CARD,FILL,action));source=self.play(g);self.play(g,action,source)
                self.advance(g);self.assertEqual(self.cost(g),1)

    def test_b02_source_control_change_does_not_transfer_cycle_or_permanent_prices(self):
        g=self.game((CARD,FILL,GIVE));source=self.play(g);self.play(g,GIVE,source)
        self.advance(g);self.assertEqual(self.cost(g),1);self.assertEqual(self.cost(g,FILL,2),4)

    def test_b03_later_draws_created_cards_and_later_turns_keep_the_permanent_price(self):
        g=self.game((CARD,FILL,MAKE));self.play(g);self.advance(g);self.play(g,MAKE)
        self.advance(g,2);self.assertEqual(self.cost(g),1);self.assertEqual(len(self.modifiers(g)),1)
        for eid in g.state.players[1].hand:
            if g.state.entities[eid].card_id==FILL:self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,1)

    def test_c00_real_repeated_battlecry_installs_and_consumes_distinct_original_cycles_once(self):
        g=self.game(board=('TIME_064',));self.play(g)
        self.assertEqual(len(self.programs(g)),2);self.assertEqual(g.state.players[1].mana,1)
        self.advance(g);self.assertFalse(self.programs(g));self.assertEqual(len(self.modifiers(g)),2)
        self.advance(g,1);self.assertEqual(len(self.modifiers(g)),2)

    def test_c01_staggered_physical_sources_have_independent_deadlines(self):
        g=self.game((CARD,CARD,FILL));self.play(g);self.next_owner(g);self.play(g)
        self.advance(g,2);self.assertEqual(len(self.modifiers(g)),1);self.assertEqual(len(self.programs(g)),1)
        self.next_owner(g);self.assertEqual(len(self.modifiers(g)),2);self.assertFalse(self.programs(g))

    def test_c02_plain_summon_does_not_start_a_lunar_cycle(self):
        g=self.game((SUMMON,FILL));self.play(g,SUMMON);self.advance(g)
        self.assertFalse(self.programs(g));self.assertFalse(self.modifiers(g));self.assertEqual(self.cost(g),4)

    def test_d00_full_timed_effect_area_does_not_block_the_persistent_cycle(self):
        g=self.game((FILL_AREA,CARD,FILL));self.play(g,FILL_AREA);self.play(g)
        self.assertEqual(len(g.state.players[1].player_effects),6)
        self.advance(g);self.assertEqual(len(g.state.players[1].player_effects),5);self.assertEqual(self.cost(g),1)

    def test_d01_extra_owner_turns_advance_the_real_clock_without_opponent_parity(self):
        g=self.game((CARD,EXTRA,FILL));self.play(g);self.play(g,EXTRA)
        self.advance(g);self.assertEqual(g.state.turn,4);self.assertEqual(self.cost(g),1)

    def test_e00_consumed_program_wait_restores_the_original_pending_cost_installation(self):
        g=self.game(mode='removed');self.play(g);self.advance(g)
        self.assertFalse(self.programs(g));self.assertFalse(self.modifiers(g));self.assertEqual(self.cost(g),4)
        g=self.portable(g,'removed');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g,'fail')
        self.assertEqual(g.snapshot(),before);self.pick(g);self.assertEqual(self.cost(g),1);self.assertEqual(len(self.modifiers(g)),1)

    def test_e01_installed_cost_wait_preserves_one_modifier_across_restore_and_resume(self):
        g=self.game(mode='cost');self.play(g);self.advance(g)
        self.assertEqual(self.cost(g),1);self.assertEqual(len(self.modifiers(g)),1)
        g=self.portable(g,'cost');self.pick(g);self.assertEqual(len(self.modifiers(g)),1)

    def test_e02_late_failure_rolls_back_the_actual_handoff_and_original_owner_interval(self):
        g=self.game(mode='fail',enemy_hand=(KILL,FILL));self.play(g);self.advance(g,2)
        g.apply(EndTurn(1));before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(),before);self.assertEqual(len(self.programs(g)),1)
        watch=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==WATCH)
        self.play(g,KILL,watch);g.apply(EndTurn(2));self.assertEqual(self.cost(g),1)

    def test_f00_live_cycle_restore_keeps_the_original_birth_interval(self):
        g=self.game();self.play(g);g=self.portable(g);self.advance(g,2);g=self.portable(g)
        self.next_owner(g);self.assertEqual(self.cost(g),1)

    def test_f01_private_clock_and_source_allocations_do_not_enter_player_views(self):
        g=self.game();self.play(g);self.next_owner(g)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('"owner_turn_history"','"entered_order"','"source_allocation"','"resolution_frame"','"rng_state"'):self.assertNotIn(key,wire)

    def test_g00_second_player_counts_only_its_future_owner_starts(self):
        g=self.game(hand=(FILL,),enemy_hand=(CARD,FILL));g.apply(EndTurn(1));self.play(g)
        self.advance(g,2,2);self.assertEqual(self.cost(g,FILL,2),4)
        self.next_owner(g,2);self.assertEqual(self.cost(g,FILL,2),1);self.assertEqual(self.cost(g),4)


if __name__=='__main__':unittest.main()
