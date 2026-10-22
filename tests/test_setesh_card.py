"""Actual Setesh Battlecry, owner intervals and original armor-to-Golem results."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.setesh_card import (CARD,GOLEM,PROGRAM,TURNS,load_batch,register_setesh_card)
from hs_sim.cards.armor_summon_reward_card import register_armor_summon_reward_card
from hs_sim.engine import (BattlecryRepeatSpec,CardDefinition,CardType,EndTurn,Game,PlayCard,
    PlayerSetup,Registry,Scenario,SelectChoice,SnapshotError,TriggerSpec)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,Destroy,GainArmor,
    InvokeBehavior,LoseArmor,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,Keyword,PlayerEffectSpec,Rarity,TargetSpec,Zone
from hs_sim.engine.player_effects import AddPlayerEffect,RemovePlayerEffect
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from tools.card_batch import canonical,check_face

P='fixture.setesh.'
HERO,UNIT,MORE,HIT,CLEAR,KILL,MUTE,ALTER,GIVE,BOUNCE,NATURAL,EXTRA,SKIP,FILL_AREA,FILL_BOARD,REMOVE,REPEAT,WATCH=(
    P+n for n in ('hero','unit','more','hit','clear','kill','mute','alter','give','bounce','natural',
        'extra','skip','fill-area','fill-board','remove','repeat','watch'))
META=CardMetadata(True,(CardClass.WARRIOR,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    assert role in ('writer','reader')
    r=Registry('setesh-'+mode);register_armor_summon_reward_card(r);register_setesh_card(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,metadata=CardMetadata(False,(CardClass.WARRIOR,),Rarity.NONE,tribes=())))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=3,metadata=META))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=4,metadata=META,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    def remove(c):
        instance=next(x for x in c.state.players[c.player_id].player_effects if x.spec_id==PROGRAM)
        return (RemovePlayerEffect(c.player_id,instance.id),)
    bodies={MORE:lambda c:(GainArmor(c.player_id,5),),HIT:lambda c:(Damage(c.state.players[c.player_id].hero_id,7,c.source_id),),
        CLEAR:lambda c:(LoseArmor(c.player_id,source_id=c.source_id),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        MUTE:lambda c:(Silence(c.target_id),),ALTER:lambda c:(Transform(c.target_id,UNIT),),
        GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        NATURAL:lambda c:(Summon(c.player_id,CARD),),EXTRA:lambda c:(QueueTurns((c.player_id,c.player_id),c.source_id),),
        SKIP:lambda c:(SkipTurns(c.player_id,1,c.source_id),),
        FILL_AREA:lambda c:tuple(AddPlayerEffect(c.player_id,P+'area.'+str(i),c.source_id)for i in range(5)),
        FILL_BOARD:lambda c:tuple(Summon(c.player_id,UNIT)for _ in range(7)),REMOVE:remove}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')
                if cid in (KILL,MUTE,ALTER,GIVE,BOUNCE)else None))
    for i in range(5):r.register_player_effect(PlayerEffectSpec(P+'area.'+str(i),FILL_AREA,
        kind='objective',duration=99,tick_event='turn_started'))
    def fail(c):raise ResolutionError('Deliberate Setesh reaction failure')
    r.register_behavior(P+'fail',fail)
    if mode!='normal':
        event='minion_summoned'if mode=='summon_wait'else 'player_effect_removed'if mode in ('remove_wait','gain_before')else 'armor_lost'if mode=='gain_after'else 'armor_loss_resolved'
        def watch(c):
            if c.event.player_id!=c.player_id:return ()
            if mode=='summon_wait':
                if c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=GOLEM:return ()
            elif c.event.source_id is None or c.state.entities[c.event.source_id].card_id!=CARD:return ()
            if mode=='gain_before':return (GainArmor(c.player_id,7),)
            if mode=='gain_after':return (GainArmor(c.player_id,5),)
            if mode=='fail_loss':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('gain','Gain Armor',(GainArmor(c.player_id,7),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,
            health=4,metadata=META,triggers=(TriggerSpec(event,WATCH),)))
    r.validate();r.freeze();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
    return s


class SeteshTests(unittest.TestCase):
    def game(self,hand=None,board=(),mode='normal',pid=1):
        self.mode,self.pid=mode,pid
        if mode!='normal':board=(*board,WATCH)
        players=tuple(PlayerSetup(HERO,hand=((CARD,)if hand is None else hand)if p==pid else (),
            board=board if p==pid else (),deck=(UNIT,)*16,mana=50,max_mana=50,mana_cap=50)for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=pid,seed=385),registry(mode))
    def play(self,g,cid=CARD,target=None):
        e=next(g.state.entities[i]for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.pid,e.id,target_id=target,position=len(g.state.players[self.pid].board)if e.kind==CardType.MINION else None));return e.id
    def next_owner(self,g):g.apply(EndTurn(self.pid));g.apply(EndTurn(3-self.pid))
    def mature(self,g):self.next_owner(g);self.next_owner(g)
    def select(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def hero(self,g):return g.state.entities[g.state.players[self.pid].hero_id]
    def markers(self,g):return [x for x in g.state.players[self.pid].player_effects if x.spec_id==PROGRAM]
    def golems(self,g):return [g.state.entities[i]for i in g.state.players[self.pid].board if g.state.entities[i].card_id==GOLEM]
    def portable(self,g):
        reader=registry(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return other

    def test_complete_root_existing_golem_and_delayed_marker_sources(self):
        data=load_batch();rows={x['record']['id']:x['record']for key in ('cards','existing_dependencies','evidence_only')for x in data[key]}
        self.assertEqual(set(rows),{CARD,GOLEM,'BE_557e2'})
        card=registry().card(CARD);self.assertEqual((card.cost,card.attack,card.health,TURNS),(7,7,7,2))
        self.assertEqual(rows[GOLEM]['cost'],3);self.assertEqual(rows['BE_557e2']['type'],'ENCHANTMENT')
        for face in data['official_observations']:check_face(rows[face['card_id']],face['face'],face['locale'])
        from dataclasses import asdict
        self.assertEqual(canonical(asdict(registry().card(GOLEM))),data['existing_definition_sha256'][GOLEM])

    def test_real_seven_mana_battlecry_gains_twenty_and_installs_one_permanent_marker(self):
        g=self.game();eid=self.play(g)
        self.assertEqual((self.hero(g).armor,g.state.players[1].mana),(20,43));marker,=self.markers(g)
        self.assertEqual(marker.source_id,eid);self.assertIsNone(marker.remaining_turns)
        self.assertFalse(self.golems(g));self.assertIsNone(g.state.pending_choice)

    def test_only_second_future_owner_start_converts_current_armor(self):
        g=self.game();self.play(g);g.apply(EndTurn(1))
        self.assertEqual(self.hero(g).armor,20);self.assertFalse(self.golems(g));g.apply(EndTurn(2))
        self.assertEqual(self.hero(g).armor,20);self.assertFalse(self.golems(g));self.next_owner(g)
        golem,=self.golems(g);self.assertEqual((golem.attack,golem.health),(20,20))
        self.assertIn(Keyword.TAUNT,golem.keywords);self.assertEqual(self.hero(g).armor,0);self.assertFalse(self.markers(g))

    def test_current_armor_after_gain_and_absorbed_damage_sets_actual_stats(self):
        g=self.game(hand=(CARD,MORE,HIT));self.play(g);self.play(g,MORE);self.play(g,HIT)
        self.assertEqual(self.hero(g).armor,18);self.assertEqual(self.hero(g).health,30);self.mature(g)
        golem,=self.golems(g);self.assertEqual((golem.attack,golem.health),(18,18));self.assertEqual(self.hero(g).armor,0)

    def test_zero_armor_uses_zero_stats_and_ordinary_death(self):
        g=self.game(hand=(CARD,CLEAR));self.play(g);self.play(g,CLEAR);self.mature(g)
        self.assertFalse(self.golems(g));self.assertFalse(self.markers(g))
        corpses=[e for e in g.state.entities.values()if e.card_id==GOLEM and e.zone==Zone.GRAVEYARD]
        self.assertEqual(len(corpses),1);self.assertEqual(corpses[0].attack,0)

    def test_full_board_still_loses_all_armor_and_normal_summon_fails(self):
        g=self.game(hand=(CARD,FILL_BOARD));self.play(g);self.play(g,FILL_BOARD)
        self.assertEqual(len(g.state.players[1].board),7);self.mature(g)
        self.assertEqual(self.hero(g).armor,0);self.assertFalse(self.golems(g));self.assertFalse(self.markers(g))

    def test_repeated_battlecry_has_independent_markers_and_never_double_uses_the_armor(self):
        g=self.game(board=(REPEAT,));self.play(g)
        self.assertEqual(self.hero(g).armor,40);self.assertEqual(len(self.markers(g)),2);self.mature(g)
        golem,=self.golems(g);self.assertEqual((golem.attack,golem.health),(40,40));self.assertFalse(self.markers(g))
        self.assertEqual(len([e for e in g.state.entities.values()if e.card_id==GOLEM]),2)

    def test_staggered_instances_keep_their_own_future_owner_deadlines(self):
        g=self.game(hand=(CARD,CARD));self.play(g);self.next_owner(g);self.play(g)
        self.next_owner(g);self.assertEqual(len(self.markers(g)),1);self.assertEqual(self.golems(g)[0].health,40)
        self.next_owner(g);self.assertFalse(self.markers(g));self.assertEqual(len(self.golems(g)),1)

    def test_source_death_silence_transform_control_and_return_do_not_move_the_player_program(self):
        for effect in (KILL,MUTE,ALTER,GIVE,BOUNCE):
            with self.subTest(effect=effect):
                g=self.game(hand=(CARD,effect));eid=self.play(g);self.play(g,effect,eid);self.mature(g)
                self.assertEqual(self.hero(g).armor,0);self.assertEqual(self.golems(g)[0].health,20)
                self.assertFalse(g.state.players[2].player_effects)

    def test_natural_summon_does_not_gain_armor_or_install_a_battlecry_marker(self):
        g=self.game(hand=(NATURAL,));self.play(g,NATURAL);self.mature(g)
        self.assertEqual(self.hero(g).armor,0);self.assertFalse(self.markers(g));self.assertFalse(self.golems(g))

    def test_two_queued_owner_turns_count_as_two_real_starts(self):
        g=self.game(hand=(CARD,EXTRA));self.play(g);self.play(g,EXTRA)
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1);self.assertEqual(self.hero(g).armor,20)
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1);self.assertEqual(self.hero(g).armor,0)
        self.assertEqual(self.golems(g)[0].health,20)

    def test_skipped_owner_opportunity_does_not_advance_the_deadline(self):
        g=self.game(hand=(CARD,SKIP));self.play(g);self.play(g,SKIP)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.state.active_player,2)
        self.assertEqual(self.hero(g).armor,20);g.apply(EndTurn(2));self.assertEqual(g.state.active_player,1)
        self.assertEqual(self.hero(g).armor,20);self.next_owner(g);self.assertEqual(self.golems(g)[0].health,20)

    def test_delayed_battlecry_program_does_not_use_the_timed_secret_area(self):
        g=self.game(hand=(FILL_AREA,CARD));self.play(g,FILL_AREA);self.play(g)
        self.assertEqual(len(g.state.players[1].player_effects),6);self.mature(g)
        self.assertEqual(self.golems(g)[0].health,20);self.assertEqual(len(g.state.players[1].player_effects),5)

    def test_removed_original_program_has_no_later_conversion(self):
        g=self.game(hand=(CARD,REMOVE));self.play(g);self.play(g,REMOVE);self.mature(g)
        self.assertFalse(self.golems(g));self.assertEqual(self.hero(g).armor,20)

    def test_armor_added_by_removal_reaction_is_included_at_actual_loss_execution(self):
        g=self.game(mode='gain_before');self.play(g);self.mature(g)
        self.assertEqual(self.golems(g)[0].health,27);self.assertEqual(self.hero(g).armor,0)

    def test_armor_added_after_loss_remains_armor_and_does_not_inflate_the_original_golem(self):
        g=self.game(mode='gain_after');self.play(g);self.mature(g)
        self.assertEqual(self.golems(g)[0].health,20);self.assertEqual(self.hero(g).armor,5)

    def test_shared_golem_definition_keeps_its_original_three_three_printed_face(self):
        g=self.game();self.play(g);self.mature(g);base=g.registry.card(GOLEM)
        self.assertEqual((base.cost,base.attack,base.health),(3,3,3));self.assertEqual(self.golems(g)[0].health,20)

    def test_consumption_wait_before_loss_restores_clone_and_replay(self):
        g=self.game(mode='remove_wait');self.play(g);self.mature(g)
        self.assertEqual(self.hero(g).armor,20);self.assertFalse(self.markers(g));self.assertFalse(self.golems(g))
        restored=self.portable(g)
        for match in (g,restored):self.select(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.golems(g)[0].health,20)

    def test_original_loss_result_survives_wait_and_new_armor_before_summon(self):
        g=self.game(mode='armor_wait');self.play(g);self.mature(g)
        self.assertEqual(self.hero(g).armor,0);self.assertFalse(self.golems(g));restored=self.portable(g)
        for match in (g,restored):self.select(match,'gain')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g).armor,7)
        self.assertEqual(self.golems(g)[0].health,20);self.portable(g)

    def test_actual_golem_entry_wait_restores_without_spending_or_summoning_twice(self):
        g=self.game(mode='summon_wait');self.play(g);self.mature(g)
        self.assertEqual(self.hero(g).armor,0);self.assertEqual(len(self.golems(g)),1);restored=self.portable(g)
        for match in (g,restored):self.select(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(len(self.golems(g)),1)

    def test_conversion_failure_rolls_back_complete_original_turn_handoff(self):
        g=self.game(mode='fail_loss');self.play(g);self.next_owner(g);g.apply(EndTurn(1));before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.hero(g).armor,20)

    def test_failure_in_later_choice_keeps_accepted_zero_armor_and_original_loss_result(self):
        g=self.game(mode='armor_wait');self.play(g);self.mature(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'fail')
        self.assertEqual(g.snapshot(),before);self.select(g);self.assertEqual(self.golems(g)[0].health,20)

    def test_other_player_keeps_own_deadline_account_and_golem(self):
        g=self.game(pid=2);self.play(g);self.mature(g)
        self.assertEqual(self.golems(g)[0].controller,2);self.assertEqual(self.hero(g).armor,0)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_player_command_for_reaction_hides_internal_armor_results_and_continuation(self):
        g=self.game(mode='armor_wait');self.play(g);self.mature(g)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('armor_loss_resolved','result','resolution_frame','owner_turn_history','rng_state'):
                self.assertNotIn('"'+key+'"',visible)
        port=g.for_player(2);commands=port.legal_actions()
        command=next(x for x in commands['actions']if x['type']=='select_choice')
        port.submit({'revision':commands['revision'],'action':command});self.assertEqual(self.golems(g)[0].health,20)


if __name__=='__main__':unittest.main()
