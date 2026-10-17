"""Native Quest-play history, actual conditional targeting and accepted inputs."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.played_quest_target_cards import ASSISTANT, FIELD, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, QuestSpec, QuestStageSpec, Rarity,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.effects import (AddToHand, ChoiceOption, InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.play_history import played_cards, quests_from_plays
from hs_sim.engine.player_target_inputs import canonical, capture, decode, validate_full_state
from hs_sim.engine.quests import AdvanceQuest, RemoveQuest
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, DiscardCard
from hs_sim.targets import canonical_digest

P = 'k133.'; Q = P+'quest'; YETI = 'CORE_CS2_182'; SHIELD = 'CORE_GVG_085'
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.LEGENDARY)


def add_quests(r):
    r.register_behavior(P+'noop', lambda c: ())
    def progress(c):
        return (AdvanceQuest(c.source_id, c.source.quest_progress.id, c.source.quest_progress.stage),)
    r.register_behavior(P+'progress', progress)
    for name, kind, goal in (('quest','quest',99), ('complete','quest',1),
            ('sidequest','sidequest',1), ('questline','questline',1), ('repeat','repeatable_quest',1)):
        cid = P+name; stages = (cid,) if kind != 'questline' else (cid,cid+'.2',cid+'.3')
        for stage in stages[1:]:
            r.register_card(CardDefinition(stage, stage, CardType.SPELL, choice_only=True))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL,
            keywords=(Keyword.QUEST if kind == 'repeatable_quest' else Keyword(kind),),
            quest=QuestSpec(kind, tuple(QuestStageSpec(s,goal,('minion_summoned',),P+'progress',P+'noop') for s in stages)),
            metadata=replace(META,rarity=Rarity.COMMON) if kind == 'sidequest' else META))


def registry(mode=None):
    r = build_registry(); add_quests(r)
    r.register_card(CardDefinition(P+'small','Small ordinary victim',CardType.MINION,attack=1,health=1))
    def remove(c):
        return tuple(RemoveQuest(i) for i in c.state.players[c.player_id].quests)
    def discard(c):
        e = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == Q)
        return (DiscardCard(CardReference.capture(e), c.source_id),)
    def trigger(c, player):
        e = next(c.state.entities[i] for i in c.state.players[player].board if c.state.entities[i].card_id == ASSISTANT)
        return (TriggerBattlecry(MinionReference.capture(e), c.source_id),)
    bodies = {'remove':remove, 'discard':discard,
        'summon':lambda c:(Summon(c.player_id,ASSISTANT),),
        'trigger':lambda c:trigger(c,c.player_id), 'trigger_enemy':lambda c:trigger(c,3-c.player_id),
        'auto':lambda c:(CastSpell(c.player_id,Q,c.source_id),),
        'add':lambda c:(AddToHand(c.player_id,Q,c.source_id),),
        'fail':lambda c:(AddToHand(c.player_id,'unknown.k133'),)}
    for name, body in bodies.items():
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name))
    if mode:
        def watch(c):
            source = c.state.entities[c.event.source_id]
            expected = Q if mode == 'commit' else ASSISTANT
            if source.card_id != expected:return ()
            if mode == 'death':return bodies['fail'](c)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        event = {'commit':'card_played','death':'minion_died'}.get(mode,'battlecry_started')
        # Death reactions inspect the actual damaged victim rather than its source.
        if mode == 'death':
            def watch(c):return bodies['fail'](c) if c.event.source_id is not None else ()
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Ordinary boundary witness',CardType.MINION,health=8,
            triggers=(TriggerSpec(event,P+'watch'),)))
    r.validate();return r


@lru_cache(maxsize=None)
def shared_registry(mode):return registry(mode)


class PlayedQuestTargetCardTests(unittest.TestCase):
    def game(self,hand=(ASSISTANT,),board=(),enemy=(YETI,),enemy_hand=(),active=1,mode=None):
        self.mode=mode
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
            mana=40,max_mana=40,mana_cap=40),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,
            deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),active_player=active,seed=133),shared_registry(mode))
    def play(self,g,cid=ASSISTANT,target=None):
        p=g.state.active_player;e=next(g.state.entities[i] for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,e.id,target,position=len(g.state.players[p].board) if e.kind==CardType.MINION else None));return e.id
    def count(self,g,p=1):return g.observe(p)['players'][p-1][FIELD]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def actions(self,g):
        result=g.for_player(g.state.active_player).legal_actions();self.assertIsNone(result['error'])
        own=result['observation']['players'][g.state.active_player-1]
        ref=next(e['ref'] for e in own['hand'] if e['card_id']==ASSISTANT)
        return result,[a for a in result['actions'] if a.get('type')=='play_card' and a.get('card')==ref]
    def public_play(self,g,targeted):
        result,actions=self.actions(g);action=next(a for a in actions if (a.get('target') is not None)==targeted)
        response=g.for_player(g.state.active_player).submit({'revision':result['revision'],'action':action})
        self.assertTrue(response['accepted'],response.get('error'))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(self.mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),saved)
        for p in (1,2):
            self.assertNotIn(FIELD,g.observe(p)['players'][2-p])
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for key in ('played_face','play_history','rng_state','observation_json','resolution_frame','source_json'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_full_raw_two_primary_faces_and_native_neutral_metadata(self):
        d=load_batch();row=d['cards'][0];raw=row['record'];card=build_registry().card(ASSISTANT)
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertEqual((card.cost,card.attack,card.health,card.metadata.classes),(2,3,2,(CardClass.NEUTRAL,)))
        self.assertEqual(len(d['official_observations']),2);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        for o in d['official_observations']:
            self.assertEqual((o['face']['id'],o['face']['manaCost'],o['face']['attack'],o['face']['health']),
                (raw['dbf_id'],2,3,2))
            self.assertFalse(Path(o['response_file']).is_absolute())
            self.assertRegex(o['response_sha256'],r'^[0-9a-f]{64}$')

    def test_no_quest_or_merely_held_quest_allows_targetless_play_and_rejects_invented_target(self):
        for hand in ((ASSISTANT,),(Q,ASSISTANT)):
            g=self.game(hand);self.assertEqual(self.count(g),0);_,actions=self.actions(g)
            self.assertTrue(actions);self.assertTrue(all(a.get('target') is None for a in actions));saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,target=g.state.players[2].board[0])
            self.assertEqual(g.snapshot(),saved);self.public_play(g,False)
            self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,5)

    def test_removed_quest_still_requires_enemy_minion_target_and_pays_once(self):
        g=self.game((Q,P+'remove',ASSISTANT),board=(YETI,));self.play(g,Q);self.play(g,P+'remove')
        self.assertEqual(g.state.players[1].quests,[]);self.assertEqual(self.count(g),1);_,actions=self.actions(g)
        self.assertTrue(all(a.get('target') is not None for a in actions));saved=g.snapshot()
        for target in (None,g.state.players[1].board[0],g.state.players[2].hero_id):
            with self.assertRaises(IllegalAction):self.play(g,target=target)
            self.assertEqual(g.snapshot(),saved)
        self.public_play(g,True);self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,2)
        self.assertEqual(g.state.players[1].mana,38);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_completed_quest_and_all_typed_native_kinds_count_once_without_stage_or_cycle_inflation(self):
        for cid in (P+'complete',P+'sidequest',P+'questline',P+'repeat'):
            with self.subTest(cid=cid):
                g=self.game((cid,YETI,YETI,YETI));self.play(g,cid)
                for _ in range(3):self.play(g,YETI);self.assertEqual(self.count(g),1)
                self.assertEqual(len(quests_from_plays(played_cards(g.state,1),g.registry)),1)
                if cid==P+'repeat':self.assertTrue(g.state.players[1].quests)
                else:self.assertFalse(g.state.players[1].quests)

    def test_countered_committed_quest_still_counts_without_an_active_slot(self):
        g=self.game((Q,ASSISTANT),enemy_hand=('EX1_287',),active=2);self.play(g,'EX1_287');g.apply(EndTurn(2))
        self.play(g,Q);self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(g.state.players[1].quests,[])
        self.assertEqual(self.count(g),1);self.public_play(g,True);self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,2)

    def test_discarded_or_generated_unplayed_quest_does_not_become_play_history(self):
        g=self.game((Q,P+'discard',ASSISTANT));self.play(g,P+'discard');self.assertEqual(self.count(g),0)
        self.assertTrue(any(g.state.entities[i].card_id==Q for i in g.state.players[1].graveyard));self.public_play(g,False)
        g=self.game((P+'add',ASSISTANT));self.play(g,P+'add');self.assertEqual(self.count(g),0);self.public_play(g,False)

    def test_effect_cast_quest_installs_a_real_slot_without_inventing_a_hand_play(self):
        g=self.game((P+'auto',ASSISTANT));self.play(g,P+'auto');self.assertTrue(g.state.players[1].quests)
        self.assertEqual(self.count(g),0);self.assertTrue(any(c.card_id==Q for c in g.state.cast_history));self.public_play(g,False)

    def test_only_original_player_counts_and_own_game_history_survives_turns(self):
        g=self.game((ASSISTANT,),enemy_hand=(Q,),active=2);self.play(g,Q);g.apply(EndTurn(2))
        self.assertEqual((self.count(g),self.count(g,2)),(0,1));self.public_play(g,False)
        g=self.game((Q,ASSISTANT));self.play(g,Q);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(self.count(g),1);self.public_play(g,True)

    def test_projection_uses_original_submitted_face_and_not_later_physical_card_or_zone(self):
        g=self.game((Q,P+'remove'));source=self.play(g,Q);self.play(g,P+'remove')
        state=g.state;state.entities[source].card_id=P+'remove'
        self.assertEqual(len(quests_from_plays(played_cards(state,1),g.registry)),1)
        state=g.state;ordinary=next(p.source_id for p in state.play_history if p.card_id==P+'remove');state.entities[ordinary].card_id=Q
        self.assertEqual(len(quests_from_plays(played_cards(state,1),g.registry)),1)
        self.assertEqual(g.state.entities[source].card_id,Q)

    def test_multiple_actual_quest_hand_plays_count_even_after_removal(self):
        g=self.game((Q,P+'remove',Q,P+'remove'));self.play(g,Q);self.play(g,P+'remove');self.play(g,Q);self.play(g,P+'remove')
        self.assertEqual(self.count(g),2);self.assertFalse(g.state.players[1].quests);self.portable(g)

    def test_conditional_damage_is_minion_ability_without_spell_power_and_shield_is_ordinary(self):
        g=self.game((Q,ASSISTANT),board=('CORE_EX1_012',));self.play(g,Q);self.public_play(g,True)
        result=next(x.health_result for x in g.state.damage_history if x.health_result.source_card_id==ASSISTANT)
        self.assertEqual((result.base_amount,result.spell_bonus,result.damage_dealt),(3,0,3))
        g=self.game((Q,ASSISTANT),enemy=(SHIELD,));self.play(g,Q);target=g.state.players[2].board[0];self.public_play(g,True)
        self.assertEqual(g.state.entities[target].health,2);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords)

    def test_positive_history_with_no_enemy_minions_can_be_played_without_target(self):
        g=self.game((Q,ASSISTANT),enemy=());self.play(g,Q);self.public_play(g,False);self.assertFalse(g.state.damage_history)

    def test_ordinary_summon_has_no_battlecry_then_indirect_activation_uses_same_complete_condition(self):
        for positive in (False,True):
            g=self.game(((Q,) if positive else ())+(P+'summon',P+'trigger'))
            if positive:self.play(g,Q)
            self.play(g,P+'summon');self.assertFalse(g.state.battlecry_history);self.play(g,P+'trigger')
            self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,2 if positive else 5)
            self.assertEqual(len(g.state.battlecry_history),1)

    def test_indirect_activation_outside_its_owner_turn_uses_actual_subject_controller(self):
        g=self.game((P+'trigger_enemy',),board=(YETI,),enemy=(ASSISTANT,),enemy_hand=(Q,),active=2)
        self.play(g,Q);g.apply(EndTurn(2));target=g.state.players[1].board[0];self.play(g,P+'trigger_enemy')
        self.assertEqual(g.state.entities[target].health,2);self.assertEqual(g.state.battlecry_history[-1].player_id,2);self.portable(g)

    def test_committed_quest_notice_wait_keeps_one_play_and_the_actual_installed_slot(self):
        g=self.game((Q,),mode='commit');self.play(g,Q);self.assertIsNotNone(g.state.pending_choice)
        self.assertTrue(g.state.players[1].quests);self.assertEqual(self.count(g),1);other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.count(g),1);self.assertTrue(g.state.players[1].quests)

    def test_waiting_damage_restore_replay_and_failed_resume_preserves_original_boundary(self):
        g=self.game((Q,P+'remove',ASSISTANT),mode='wait');self.play(g,Q);self.play(g,P+'remove')
        self.play(g,target=g.state.players[2].board[0]);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,2)

    def test_late_death_failure_rolls_back_assistant_payment_history_and_information(self):
        g=self.game((Q,ASSISTANT),enemy=(P+'small',),mode='death');self.play(g,Q);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,target=g.state.players[2].board[0])
        self.assertEqual(g.snapshot(),saved);self.assertEqual(self.count(g),1)

    def test_original_dto_requires_own_exact_bounded_count_and_forbids_opponent_field(self):
        g=self.game();source=g._state.entities[g._state.players[1].hand[0]];proof=capture(g,g._state,source)
        mutations=(lambda v:v['players'][0].pop(FIELD),lambda v:v['players'][1].update({FIELD:0}),
            *(lambda v,x=x:v['players'][0].update({FIELD:x}) for x in (None,True,-1,1,'0',0.0)))
        for change in mutations:
            value=json.loads(proof.observation_json);change(value)
            with self.assertRaises(ValueError):decode(replace(proof,observation_json=canonical(value)))

    def test_live_projection_rejects_well_typed_forged_quest_count(self):
        g=self.game((Q,P+'remove',ASSISTANT));self.play(g,Q);self.play(g,P+'remove')
        source=g._state.entities[g._state.players[1].hand[0]];proof=capture(g,g._state,source)
        for count in (0,2):
            value=json.loads(proof.observation_json);value['players'][0][FIELD]=count
            with self.assertRaisesRegex(ValueError,'complete payment state projection'):
                validate_full_state(g._state,g.registry,source,replace(proof,observation_json=canonical(value)))

    def test_rehashed_closed_paid_receipt_rejects_forged_preceding_quest_count(self):
        from test_player_target_inputs import registry as paid_registry,command
        r=paid_registry();add_quests(r);r.register_card(CardDefinition(P+'ordinary','Ordinary',CardType.SPELL))
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=(Q,P+'ordinary','unit'),board=('tiny','big'),mana=6,max_mana=6),
            PlayerSetup('hero',board=('tiny','big'))),seed=133),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));g.apply(PlayCard(1,g.state.players[1].hand[0]))
        self.assertTrue(g.for_player(1).submit(command(g))['accepted']);self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot())
        for count in (0,2):
            saved=deepcopy(g.snapshot());receipt=saved['state']['play_history'][-1]['body_targets'];proof=receipt['origin']['observation']
            value=json.loads(proof['observation_json']);value['players'][0][FIELD]=count;proof['observation_json']=canonical(value)
            receipt['origin_hash']=canonical_hash(receipt['origin'])
            saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError) as caught:Game.from_snapshot(saved,r)
            self.assertIn('preceding Quest plays',str(caught.exception))

    def test_player_queries_are_repeatable_and_leave_history_and_information_unchanged(self):
        g=self.game((Q,ASSISTANT));self.play(g,Q);self.actions(g);saved=g.snapshot()
        self.assertEqual(g.for_player(1).legal_actions(),g.for_player(1).legal_actions());self.assertEqual(g.snapshot(),saved)

    def test_old_schema_rejected_and_all_previous_complete_cards_and_pools_preserved(self):
        with patch('hs_sim.cards.played_quest_target_cards.register_played_quest_target_cards',lambda r:None):before=build_registry()
        r=build_registry();self.assertEqual(set(r.cards)-set(before.cards),{ASSISTANT})
        for cid,value in before.cards.items():self.assertEqual(asdict(r.card(cid)),asdict(value))
        self.assertEqual(dict(r.pool_cards),dict(before.pool_cards))
        g=self.game();saved=g.snapshot();saved['schema_version']-=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())


if __name__=='__main__':unittest.main()
