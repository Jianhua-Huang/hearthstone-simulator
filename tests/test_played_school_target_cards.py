"""Actual Fire-conditional targeting, private school input and accepted proofs."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.played_school_target_cards import BLAZER, FIELD, load_batch
from hs_sim.engine import (CardDefinition, CardType, CastSpell, EndTurn, Game, IllegalAction, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.effects import (AddToHand, ChoiceOption, InvokeBehavior,
    RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.play_history import played_cards, spell_schools_from_plays
from hs_sim.engine.player_target_inputs import canonical, capture, decode, validate_full_state
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

FIRE='CS2_029';YETI='CORE_CS2_182';PREFIX='k97.'


def registry():
    r=build_registry()
    r.register_behavior(PREFIX+'noop',lambda c:())
    for school in (*SpellSchool,None):
        name=PREFIX+('none'if school is None else school.value)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=PREFIX+'noop',spell_school=school))
    for school in (SpellSchool.FIRE,SpellSchool.FROST):
        name=PREFIX+'secret_'+school.value
        r.register_card(replace(r.card('EX1_287'),id=name,name=name,spell_school=school))
    r.register_behavior(PREFIX+'auto',lambda c:(CastSpell(c.player_id,FIRE,c.source_id,
        target_id=c.state.players[2].hero_id,targeting='explicit'),))
    r.register_behavior(PREFIX+'summon',lambda c:(Summon(c.player_id,BLAZER),))
    def trigger(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==BLAZER)
        return (TriggerBattlecry(MinionReference.capture(e),c.source_id,e.id,targeting='explicit'),)
    r.register_behavior(PREFIX+'trigger',trigger)
    r.register_behavior(PREFIX+'fail',lambda c:(AddToHand(c.player_id,'unknown.k97'),))
    def wait(c):
        source=c.state.entities[c.event.source_id]
        if source.card_id!=BLAZER:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('bad','Fail',(InvokeBehavior(PREFIX+'fail',c.source_id,c.player_id),)),
        ),source_id=c.source_id),)
    def death_fail(c):
        source=c.state.entities[c.event.source_id]
        return (AddToHand(c.player_id,'unknown.k97'),)if source.card_id==YETI else ()
    for name,event,body in (('watch','battlecry_started',wait),('death_fail','minion_died',death_fail)):
        r.register_behavior(PREFIX+name,body)
        r.register_card(CardDefinition(PREFIX+name,name,CardType.MINION,health=8,
            triggers=(TriggerSpec(event,PREFIX+name),)))
    for name in ('auto','summon','trigger'):
        r.register_card(CardDefinition(PREFIX+name,name,CardType.SPELL,on_play=PREFIX+name))
    return r


class PlayedSchoolTargetCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(BLAZER,),board=(),enemy=(YETI,),enemy_hand=(),active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        ),active_player=active,seed=97),self.r)
    def play(self,g,cid=BLAZER,target=None):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,i,target,position=len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return i
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def schools(self,g,p=1):return g.observe(p)['players'][p-1][FIELD]
    def actions(self,g):
        p=g.state.active_player;result=g.for_player(p).legal_actions();self.assertIsNone(result['error'])
        own=result['observation']['players'][p-1]
        source=next(e['ref']for e in own['hand']if e['card_id']==BLAZER)
        return result,[a for a in result['actions']if a.get('type')=='play_card'and a.get('card')==source]
    def public_play(self,g,target=None):
        result,actions=self.actions(g);p=g.state.active_player
        ref=None if target is None else next(e['ref']for row in result['observation']['players']for e in row['board']if
            e['card_id']==g.state.entities[target].card_id and e['controller']==g.state.entities[target].controller)
        action=next(a for a in actions if a.get('target')==ref)
        response=g.for_player(p).submit({'revision':result['revision'],'action':action})
        self.assertTrue(response['accepted'],response.get('error'))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in (1,2):
            view=g.observe(p);self.assertNotIn(FIELD,view['players'][2-p])
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for private in ('played_face','rng_state','observation_json','resolution_frame','zone_epoch'):
                self.assertNotIn(private,public)
        return other

    def test_full_raw_face_metadata_and_real_conditional_target(self):
        data=load_batch();raw=data['cards'][0]['record'];card=self.r.card(BLAZER)
        self.assertEqual(canonical_digest(raw),data['cards'][0]['record_sha256'])
        self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=BLAZER))
        self.assertEqual((card.cost,card.attack,card.health),(3,4,3))
        self.assertFalse(card.targeting.exclude_source);self.assertEqual(len(data['official_observations']),2)
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_no_fire_allows_targetless_public_play_and_rejects_invented_target(self):
        g=self.game();result,actions=self.actions(g);self.assertTrue(actions)
        self.assertTrue(all(a.get('target')is None for a in actions));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,target=g.state.players[2].board[0])
        self.assertEqual(g.snapshot(),before);self.public_play(g)
        self.assertEqual(len(g.state.players[2].board),1);self.assertEqual(g.state.players[1].mana,37)

    def test_actual_fire_requires_minion_public_target_pays_once_and_destroys(self):
        g=self.game((FIRE,BLAZER));self.play(g,FIRE,g.state.players[2].hero_id)
        result,actions=self.actions(g);self.assertTrue(all(a.get('target')is not None for a in actions))
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before);target=g.state.players[2].board[0];self.public_play(g,target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].mana,33)
        self.assertEqual(len(g.state.play_history),2);self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_fire_can_destroy_friendly_minion_and_empty_board_keeps_targetless_play(self):
        g=self.game((FIRE,BLAZER),board=(YETI,),enemy=());self.play(g,FIRE,g.state.players[2].hero_id)
        target=g.state.players[1].board[0];self.public_play(g,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        g=self.game((FIRE,BLAZER),enemy=());self.play(g,FIRE,g.state.players[2].hero_id);self.public_play(g)
        self.assertEqual(len(g.state.death_history),0)

    def test_nonfire_and_no_school_plays_do_not_enable_target(self):
        g=self.game((PREFIX+'frost',PREFIX+'none',BLAZER));self.play(g,PREFIX+'frost');self.play(g,PREFIX+'none')
        self.assertEqual(self.schools(g),['frost']);self.public_play(g);self.assertEqual(len(g.state.death_history),0)

    def test_effect_cast_fire_does_not_become_committed_hand_fire(self):
        g=self.game((PREFIX+'auto',BLAZER));self.play(g,PREFIX+'auto')
        self.assertEqual(self.schools(g),[]);self.assertTrue(any(c.card_id==FIRE for c in g.state.cast_history))
        self.public_play(g);self.assertEqual(len(g.state.death_history),0)

    def test_opponent_and_previous_global_turn_fire_do_not_enable(self):
        g=self.game(enemy_hand=(FIRE,),active=2);self.play(g,FIRE,g.state.players[1].hero_id);self.end(g)
        self.assertEqual(self.schools(g),[]);self.public_play(g);self.assertEqual(len(g.state.death_history),0)
        g=self.game((FIRE,BLAZER));self.play(g,FIRE,g.state.players[2].hero_id);self.end(g);self.end(g)
        self.assertEqual(self.schools(g),[]);self.public_play(g);self.assertEqual(len(g.state.death_history),0)

    def test_countered_committed_fire_still_enables(self):
        g=self.game((FIRE,BLAZER),enemy_hand=('EX1_287',),active=2);self.play(g,'EX1_287');self.end(g)
        self.play(g,FIRE,g.state.players[2].hero_id);self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(self.schools(g),['fire']);self.public_play(g,g.state.players[2].board[0])
        self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_school_aggregate_is_sorted_unique_and_preserves_no_school_play_count(self):
        hand=tuple(PREFIX+s.value for s in reversed(tuple(SpellSchool)))+(PREFIX+'fire',PREFIX+'none',BLAZER)
        g=self.game(hand)
        for name in hand[:-1]:self.play(g,name)
        self.assertEqual(self.schools(g),sorted(s.value for s in SpellSchool))
        self.assertEqual(g.observe(1)['players'][0]['cards_played_this_turn'],9)

    def test_school_projection_reads_frozen_play_faces_after_source_is_gone(self):
        g=self.game((FIRE,));source=self.play(g,FIRE,g.state.players[2].hero_id)
        state=g.state;state.entities[source].card_id=PREFIX+'frost'
        self.assertEqual(spell_schools_from_plays(played_cards(state,1,turn=state.turn)),(SpellSchool.FIRE,))
        self.assertEqual(g.state.entities[source].card_id,FIRE)

    def test_opposing_hidden_secret_school_does_not_enter_view_or_events(self):
        a=self.game(enemy_hand=(PREFIX+'secret_fire',),active=2);b=self.game(enemy_hand=(PREFIX+'secret_frost',),active=2)
        self.play(a,PREFIX+'secret_fire');self.play(b,PREFIX+'secret_frost')
        self.assertEqual(a.observe(1),b.observe(1));self.assertEqual(a.player_events(1),b.player_events(1))
        self.assertEqual(self.schools(a,2),['fire']);self.assertEqual(self.schools(b,2),['frost'])

    def test_plain_summon_is_not_battlecry_and_explicit_trigger_can_target_itself(self):
        g=self.game((PREFIX+'summon',FIRE,PREFIX+'trigger'));self.play(g,PREFIX+'summon')
        self.assertEqual(len(g.state.battlecry_history),0);source=g.state.players[1].board[0]
        self.play(g,FIRE,g.state.players[2].hero_id);self.play(g,PREFIX+'trigger')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_waiting_restore_clone_replay_bad_choice_rollback_and_same_completion(self):
        g=self.game((FIRE,BLAZER),board=(PREFIX+'watch',));self.play(g,FIRE,g.state.players[2].hero_id)
        target=g.state.players[2].board[0];self.play(g,target=target);self.assertIsNotNone(g.state.pending_choice)
        saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)

    def test_late_death_failure_rolls_back_payment_history_target_and_information(self):
        g=self.game((FIRE,BLAZER),board=(PREFIX+'death_fail',));self.play(g,FIRE,g.state.players[2].hero_id);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,target=g.state.players[2].board[0])
        self.assertEqual(g.snapshot(),before)

    def test_hero_target_is_not_accepted_even_after_fire(self):
        g=self.game((FIRE,BLAZER));self.play(g,FIRE,g.state.players[2].hero_id);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,target=g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),before)

    def test_original_input_requires_own_sorted_known_distinct_schools_only(self):
        g=self.game();source=g._state.entities[g._state.players[1].hand[0]];proof=capture(g,g._state,source)
        mutations=(lambda v:v['players'][0].pop(FIELD),lambda v:v['players'][1].update({FIELD:[]}),
            *(lambda v,x=x:v['players'][0].update({FIELD:x})for x in (None,True,['unknown'],['fire','fire'],['frost','fire'],[True])))
        for mutate in mutations:
            value=json.loads(proof.observation_json);mutate(value)
            with self.assertRaises(ValueError):decode(replace(proof,observation_json=canonical(value)))

    def test_original_full_state_projection_rejects_valid_but_forged_schools(self):
        g=self.game((FIRE,BLAZER));self.play(g,FIRE,g.state.players[2].hero_id)
        source=g._state.entities[g._state.players[1].hand[0]];proof=capture(g,g._state,source)
        for schools in ([],['arcane'],['fire','frost']):
            value=json.loads(proof.observation_json);value['players'][0][FIELD]=schools
            with self.assertRaisesRegex(ValueError,'complete payment state projection'):
                validate_full_state(g._state,g.registry,source,replace(proof,observation_json=canonical(value)))

    def test_rehashed_closed_paid_receipt_rejects_forged_preceding_schools(self):
        from test_player_target_inputs import registry as paid_registry,command
        r=paid_registry();r.register_card(CardDefinition(PREFIX+'fire',PREFIX+'fire',CardType.SPELL,spell_school=SpellSchool.FIRE))
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=(PREFIX+'fire','unit'),board=('tiny','big'),mana=6,max_mana=6),
            PlayerSetup('hero',board=('tiny','big'))),seed=97),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));result=g.for_player(1).submit(command(g));self.assertTrue(result['accepted'])
        self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot())
        for schools in ([],['arcane'],['fire','frost']):
            saved=deepcopy(g.snapshot());receipt=saved['state']['play_history'][-1]['body_targets'];proof=receipt['origin']['observation']
            value=json.loads(proof['observation_json']);value['players'][0][FIELD]=schools;proof['observation_json']=canonical(value)
            receipt['origin_hash']=canonical_hash(receipt['origin'])
            saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(saved,r)
            self.assertNotIn('digest mismatch',str(caught.exception))

    def test_player_queries_are_repeatable_and_do_not_mutate_state(self):
        g=self.game((FIRE,BLAZER));self.play(g,FIRE,g.state.players[2].hero_id)
        self.actions(g);before=g.snapshot();a=g.for_player(1).legal_actions();b=g.for_player(1).legal_actions()
        self.assertEqual(a,b);self.assertEqual(g.snapshot(),before)

    def test_turn_transition_clears_projection_but_keeps_original_school_fact(self):
        g=self.game((FIRE,));self.play(g,FIRE,g.state.players[2].hero_id);self.assertEqual(self.schools(g),['fire'])
        self.end(g);self.assertEqual(self.schools(g),[])
        self.assertEqual(g.state.play_history[0].played_face.spell_school,SpellSchool.FIRE);self.portable(g)
