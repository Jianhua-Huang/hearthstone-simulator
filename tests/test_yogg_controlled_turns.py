"""Real Yogg input, controlled lifecycle, native choices and transaction boundaries."""
import json
import random
import unittest
from dataclasses import replace
from functools import lru_cache

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.yogg_skills import ROOT,SKILLS,ASCENT,DOMAIN,register_yogg_skills
from hs_sim.cards.yogg_root_card import register_yogg_root_card
from hs_sim.engine import (Game,Registry,CardDefinition,CardMetadata,CardClass,Rarity,CardType,
    PlayerSetup,Scenario,TriggerSpec,PlayCard,EndTurn,SelectChoice,Concede,Ruleset,
    BattlecryRepeatSpec,ResolutionError,ResolutionLimitExceeded,SnapshotError,UseHeroPower)
from hs_sim.engine.effects import ChoiceOption,RequestChoice,Damage,Destroy
from hs_sim.engine.model import DamageKind,TargetSpec,TargetMode,TurnSchedule
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember,PoolCard
from hs_sim.engine.controlled_turns import RequestControlledTurn,NativeTurnInput,ControlledTurnRequest
from hs_sim.engine.native_turn_policy import choose
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.sacrifice import MinionReference

P='k502.'
HERO,POWER,UNIT,SPELL,FIVE,WATCH,REPEATER,BAD=(P+x for x in ('hero','power','unit','spell','five','watch','repeater','bad'))
META=CardMetadata(False,(CardClass.MAGE,),Rarity.NONE,tribes=(),factions=(),subtypes=())
COLLECTIBLE=replace(META,collectible=True,rarity=Rarity.COMMON)
CTX=GenerationContext('complete-k502-experimental-domain','experimental')
TARGET=TargetSpec(TargetMode.REQUIRED,kinds=(CardType.HERO,CardType.MINION),relation='any')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_yogg_skills(r);register_yogg_root_card(r)
    r.register_behavior(P+'noop',lambda c:())
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=10 if mode=='lethal' else 1000,metadata=META))
    def power(c):
        if mode=='indirect':
            entity=next(c.state.entities[i] for i in c.state.players[2].board if c.state.entities[i].card_id==ROOT)
            return (TriggerBattlecry(MinionReference.capture(entity),c.source_id),)
        if mode=='invalid_source':return (RequestControlledTurn(1),)
        return ()
    r.register_behavior(P+'power',power)
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,cost=0,on_use=P+'power',metadata=META))
    def unit(c):
        if mode in ('own_choice','opponent_choice'):
            return (RequestChoice(c.player_id if mode=='own_choice' else 3-c.player_id,
                (ChoiceOption('a','A'),ChoiceOption('b','B')),source_id=c.source_id),)
        return ()
    r.register_behavior(P+'unit',unit)
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=1,attack=1,health=3,
        battlecry=P+'unit',metadata=META))
    def hit(c):return (Damage(c.target_id,2,c.source_id,DamageKind.SPELL),)
    r.register_behavior(P+'hit',hit)
    for cid,cost in ((SPELL,2),(FIVE,5)):
        card=CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=P+'hit',targeting=TARGET,metadata=COLLECTIBLE)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_pool(PoolDefinition('constructed.cards','k502-original-exact-tier',CTX.target_id,CTX.mode,
        (PoolMember(FIVE),),complete=True))
    def bad(c):raise RuntimeError('k502-native-late-failure')
    r.register_behavior(P+'bad',bad)
    r.register_target_rule(P+'trusted_only',lambda c:True)
    r.register_card(CardDefinition(BAD,BAD,CardType.MINION,cost=1,attack=1,health=1,on_play=P+'bad',metadata=META))
    if mode=='unsupported':r._cards[BAD]=replace(r.card(BAD),target_rule=P+'trusted_only',targeting=TARGET)
    r.register_card(CardDefinition(REPEATER,REPEATER,CardType.MINION,health=5,
        battlecry_repeats=(BattlecryRepeatSpec(2),),metadata=META))
    def watch(c):
        if c.event.kind=='card_played' and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==ROOT:
            if mode=='before_tail':return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),source_id=c.source_id),)
            if mode=='source_dead':return (Destroy(c.event.source_id,c.source_id),)
            if mode=='pre_queue':return (QueueTurns((3-c.player_id,),c.source_id),)
            if mode=='skip':return (SkipTurns(c.player_id,source_id=c.source_id),)
            if mode=='terminal':return (Damage(c.state.players[c.player_id].hero_id,2000,c.source_id),)
        if c.event.kind in ('turn_started','turn_ended') and c.event.player_id==c.player_id and c.state.turn==2:
            match=(mode=='start_choice' and c.event.kind=='turn_started') or (
                mode in ('end_choice','end_opponent_choice') and c.event.kind=='turn_ended')
            if match:return (RequestChoice(3-c.player_id if mode=='end_opponent_choice' else c.player_id,
                (ChoiceOption('continue','Continue'),),source_id=c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=8,metadata=META,
        triggers=tuple(TriggerSpec(event,P+'watch') for event in ('card_played','turn_started','turn_ended'))))
    return r


class YoggControlledTurnTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)
    mode='normal'

    def game(self,mode='normal',player=1,hand=(ROOT,),deck=(UNIT,)*8,seed=502,rules=None):
        self.mode=mode
        board=(WATCH,) if mode in ('before_tail','source_dead','pre_queue','skip','terminal','start_choice','end_choice','end_opponent_choice') else (REPEATER,) if mode=='repeat' else ()
        players=tuple(PlayerSetup(HERO,hero_power_card_id=POWER,hand=hand if p==player else (),
            deck=deck if p==player else (UNIT,)*8,board=board if p==player else (),mana=10,max_mana=10) for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=seed,generation_context=CTX),fixture(mode),ruleset=rules)

    def requests(self,g):return g.state.controlled_turn_requests
    def commands(self,row):return [json.loads(v.command) for v in row.inputs]
    def seed(self,skills):
        return next(i for i in range(100) if set(random.Random(i).sample(SKILLS,2))==set(skills))

    def test_real_paid_battlecry_runs_one_native_turn_and_preserves_external_history(self):
        g=self.game();self.play(g,ROOT)
        row=self.requests(g)[0]
        self.assertEqual((row.status,row.player_id,g.state.turn,g.state.active_player),('completed',1,3,2))
        self.assertEqual([v.player_id for v in g.state.owner_turn_history],[1,1,2])
        self.assertEqual(len(g._history),1)
        self.assertGreater(len(row.inputs),2)
        self.assertGreater(g.state.action_number,len(g._history))
        commands=self.commands(row)
        self.assertEqual(commands[0]['type'],'use_minion_ability')
        self.assertEqual(commands[-1]['type'],'end_turn')
        self.assertEqual(sum(e.kind=='mana_spent' and e.amount==9 for e in g.events),1)
        self.portable(g)

    def test_second_player_uses_same_native_pipeline_and_correct_natural_successor(self):
        g=self.game(player=2);self.play(g,ROOT,player=2)
        self.assertEqual([v.player_id for v in g.state.owner_turn_history],[2,2,1])
        self.assertEqual((self.requests(g)[0].status,g.state.active_player),('completed',1))

    def test_equal_ability_sample_and_domain_before_ascent_then_new_spells_transform(self):
        g=self.game(deck=(SPELL,)*9,seed=self.seed((ASCENT,DOMAIN)));self.play(g,ROOT)
        row=self.requests(g)[0]
        self.assertEqual(row.opening_plan,(DOMAIN,ASCENT))
        commands=self.commands(row)
        self.assertEqual([a['ability_id'] for a in commands[:2]],[DOMAIN,ASCENT])
        self.assertTrue(any(e.kind=='stored_card_transformed' for e in g.events))
        self.assertTrue(any(c.card_id==FIVE for c in g.state.cast_history))

    def test_native_owned_choice_uses_ordinary_selection_without_external_history(self):
        g=self.game('own_choice');self.play(g,ROOT)
        self.assertEqual(self.requests(g)[0].status,'completed')
        self.assertIn('select_choice',[a['type'] for a in self.commands(self.requests(g)[0])])
        self.assertEqual(len(g._history),1)

    def test_opponent_choice_pauses_native_actor_and_restores_then_continues(self):
        g=self.game('opponent_choice',deck=(UNIT,));self.play(g,ROOT)
        self.assertEqual((g.state.pending_choice.player_id,self.requests(g)[0].status),(2,'active'))
        restored=self.portable(g)
        self.choose(g,'a');self.choose(restored,'a')
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual((self.requests(g)[0].status,len(g._history)),('completed',2))

    def test_original_play_choice_keeps_request_tail_until_real_completion(self):
        g=self.game('before_tail');self.play(g,ROOT)
        self.assertEqual((g.state.turn,self.requests(g)[0].status),(1,'requested'))
        self.assertEqual(g.state.turn_schedule.pending,())
        self.portable(g);self.choose(g)
        self.assertEqual((g.state.turn,self.requests(g)[0].status),(3,'completed'))

    def test_controlled_start_choice_is_resolved_before_first_ordinary_ability(self):
        g=self.game('start_choice');self.play(g,ROOT)
        commands=self.commands(self.requests(g)[0])
        self.assertEqual([a['type'] for a in commands[:2]],['select_choice','use_minion_ability'])

    def test_controlled_end_choice_stays_native_until_actual_handoff(self):
        g=self.game('end_choice');self.play(g,ROOT)
        commands=self.commands(self.requests(g)[0])
        self.assertEqual([a['type'] for a in commands[-2:]],['end_turn','select_choice'])
        self.assertEqual(self.requests(g)[0].status,'completed')

    def test_opponent_end_choice_preserves_ending_lease_and_rejects_manual_owner_input(self):
        g=self.game('end_opponent_choice');self.play(g,ROOT)
        self.assertEqual(self.requests(g)[0].status,'ending')
        self.portable(g)
        with self.assertRaises(Exception):g.apply(EndTurn(1))
        self.choose(g)
        self.assertEqual((self.requests(g)[0].status,g.state.active_player),('completed',2))

    def test_once_per_game_survives_repeated_battlecry_and_another_physical_yogg(self):
        g=self.game('repeat',hand=(ROOT,ROOT));self.play(g,ROOT)
        self.assertEqual(len(self.requests(g)),1)
        self.assertEqual(len([v for v in g.state.play_history if v.card_id==ROOT]),2)
        self.assertEqual(len([v for v in g.state.battlecry_history if v.payload.card_id==ROOT]),4)
        self.assertEqual([v.player_id for v in g.state.owner_turn_history],[1,1,2])

    def test_once_per_game_is_independent_for_each_player(self):
        other=Game.from_scenario(Scenario((
            PlayerSetup(HERO,hero_power_card_id=POWER,hand=(ROOT,),deck=(UNIT,)*8,mana=10,max_mana=10),
            PlayerSetup(HERO,hero_power_card_id=POWER,hand=(ROOT,),deck=(UNIT,)*8,mana=10,max_mana=10)),seed=502,generation_context=CTX),fixture())
        self.play(other,ROOT);self.play(other,ROOT,player=2)
        self.assertEqual([(r.player_id,r.status) for r in self.requests(other)],[(1,'completed'),(2,'completed')])

    def test_source_death_does_not_cancel_already_accepted_native_turn(self):
        g=self.game('source_dead');source=self.play(g,ROOT)
        self.assertNotIn(source,g.state.players[1].board)
        self.assertEqual((self.requests(g)[0].opening_plan,self.requests(g)[0].status),((),'completed'))

    def test_existing_queued_turn_keeps_fifo_and_controlled_identity(self):
        g=self.game('pre_queue');self.play(g,ROOT)
        self.assertEqual((g.state.active_player,self.requests(g)[0].status),(2,'queued'))
        self.assertEqual(g.state.turn_schedule.controlled_slots,((0,1),))
        self.portable(g);g.apply(EndTurn(2))
        self.assertEqual([v.player_id for v in g.state.owner_turn_history],[1,2,1,2])
        self.assertEqual(self.requests(g)[0].status,'completed')

    def test_skipped_controlled_slot_has_no_interval_inputs_or_ability_rng(self):
        g=self.game('skip');before=g.snapshot()['rng_state'];self.play(g,ROOT)
        row=self.requests(g)[0]
        self.assertEqual((row.status,row.started_owner_turn_id,row.inputs),('skipped',None,()))
        self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertEqual([v.player_id for v in g.state.owner_turn_history],[1,2])

    def test_terminal_original_play_interrupts_request_without_creating_extra_turn(self):
        g=self.game('terminal');self.play(g,ROOT)
        row=self.requests(g)[0]
        self.assertEqual((row.status,row.scheduled_event,row.inputs),('interrupted',None,()))
        self.assertNotEqual(g.state.status,'playing');self.portable(g)

    def test_concede_during_opponent_choice_interrupts_real_controlled_interval(self):
        g=self.game('opponent_choice',deck=(UNIT,));self.play(g,ROOT);g.apply(Concede(2))
        self.assertEqual(self.requests(g)[0].status,'interrupted');self.portable(g)

    def test_late_native_failure_rolls_back_paid_root_turns_rng_and_history(self):
        g=self.game(deck=(BAD,));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'k502-native-late-failure'):self.play(g,ROOT)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g._history,[])

    def test_engineering_turn_limit_rolls_back_entire_originating_play(self):
        g=self.game(rules=Ruleset(max_turns=2));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,ROOT)
        self.assertEqual(g.snapshot(),before)

    def test_missing_or_inactive_battlecry_cannot_create_a_controlled_turn(self):
        g=self.game('invalid_source');before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(g.snapshot(),before)
        for value in (0,True,-1):
            with self.assertRaises(ValueError):RequestControlledTurn(value)

    def test_indirect_off_turn_battlecry_queues_its_owner_without_ending_other_player(self):
        self.mode='indirect'
        g=Game.from_scenario(Scenario((
            PlayerSetup(HERO,hero_power_card_id=POWER,deck=(UNIT,)*8,mana=10,max_mana=10),
            PlayerSetup(HERO,hero_power_card_id=POWER,board=(ROOT,),deck=(UNIT,)*8,mana=10,max_mana=10)),
            seed=502,generation_context=CTX),fixture('indirect'))
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual((g.state.active_player,g.state.turn,self.requests(g)[0].status),(1,1,'queued'))
        self.assertEqual(g.state.battlecry_history[0].origin,'effect')
        g.apply(EndTurn(1))
        self.assertEqual([v.player_id for v in g.state.owner_turn_history],[1,2,2])
        self.assertEqual(self.requests(g)[0].status,'completed')

    def test_native_lethal_interrupts_actual_extra_interval_without_fictitious_end(self):
        g=self.game('lethal',seed=self.seed((SKILLS[0],SKILLS[1])));self.play(g,ROOT)
        self.assertEqual((g.state.status,g.state.winner,len(g.state.owner_turn_history)),('finished',1,2))
        self.assertEqual((self.requests(g)[0].status,self.requests(g)[0].ended_event),('interrupted',None))
        self.portable(g)

    def test_unsupported_player_rule_is_explicit_and_rolls_back_instead_of_skipping_card(self):
        g=self.game('unsupported',hand=(ROOT,BAD));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported'):self.play(g,ROOT)
        self.assertEqual(g.snapshot(),before)

    def test_snapshot_rejects_changed_plan_input_owner_once_and_queue_identity(self):
        g=self.game();self.play(g,ROOT);saved=g.snapshot()
        for field,value in (('player_id',2),('opening_plan',['BE_009t3']),('ended_event',1),('policy','invented')):
            broken=json.loads(json.dumps(saved));broken['state']['controlled_turn_requests'][0][field]=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(broken,fixture())
        broken=json.loads(json.dumps(saved));broken['state']['controlled_turn_requests'][0]['inputs'][0]['command']='{}'
        with self.assertRaises(SnapshotError):Game.from_snapshot(broken,fixture())
        for slots in (((0,True),),((1,1),),((0,1),(0,2))):
            with self.assertRaises(ValueError):TurnSchedule((1,),2,controlled_slots=slots)

    def test_player_dtos_and_events_exclude_control_proofs_and_hidden_opponent_hands(self):
        g=self.game();self.play(g,ROOT)
        for player in (1,2):
            data=json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).events())
            for key in ('controlled_input','controlled_ability_plan','controlled_turn_requests','rng_before','observation_hash','menu_hash'):
                self.assertNotIn('"'+key+'"',data)

    def test_real_root_source_and_standard_assembly_have_one_remaining_candidate(self):
        r=build_registry();root=r.card(ROOT)
        self.assertEqual((root.cost,root.attack,root.health,len(root.activated_abilities)),(9,7,5,4))
        self.assertEqual(tuple(a.card_id for a in root.activated_abilities),SKILLS)
        self.assertIn(ROOT,r.pool_cards)


class NativeTurnPolicyTests(unittest.TestCase):
    def message(self,actions):
        player=lambda pid:dict(id=pid,hero=dict(ref='hero'+str(pid),controller=pid,kind=CardType.HERO.value,attack=3,health=2,armor=0),hero_power=None,additional_hero_powers=[],weapon=None,board=[],hand=[],quests=[])
        return dict(error=None,actions=actions,observation=dict(viewer=1,players=[player(1),player(2)]))

    def test_confirmed_opening_ability_precedes_even_an_available_lethal_attack(self):
        ability=dict(type='use_minion_ability',minion='yogg',ability_id=DOMAIN,target=None)
        attack=dict(type='attack',attacker='hero1',defender='hero2')
        self.assertEqual(choose(self.message([attack,ability]),'yogg',(DOMAIN,)),ability)

    def test_ordinary_ranking_prefers_lethal_to_end_and_never_concedes(self):
        attack=dict(type='attack',attacker='hero1',defender='hero2')
        message=self.message([dict(type='end_turn'),dict(type='concede'),attack])
        message['observation']['players'][0]['hand']=[dict(ref='card',cost=dict(amount=9))]
        message['actions'].insert(0,dict(type='play_card',card='card',target=None))
        self.assertEqual(choose(message),attack)

    def test_unavailable_planned_ability_does_not_invent_a_command(self):
        action=dict(type='end_turn')
        self.assertEqual(choose(self.message([action]),'gone',(DOMAIN,)),action)

    def test_unknown_or_unsupported_player_rules_fail_instead_of_ending(self):
        message=self.message([dict(type='end_turn')]);message['error']='unsupported_rule'
        with self.assertRaises(ResolutionError):choose(message)
        with self.assertRaises(ResolutionError):choose(self.message([dict(type='invented')]))
