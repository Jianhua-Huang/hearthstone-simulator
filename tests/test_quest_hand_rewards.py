"""Real Underfel completion, full-hand preservation and quest/Godfrey priority."""
from functools import lru_cache
from dataclasses import replace
import json,unittest

from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.actions import Concede
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Draw,GainArmor,InvokeBehavior,RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import QuestSpec,QuestStageSpec,CostSpec,Keyword
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.engine.quest_hand_rewards import ACCEPTED,DELIVERED
from hs_sim.engine.overdraw_returns import SOURCE as GODFREY,PROGRAM
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.temporary_cards import CreateTemporaryCard
from hs_sim.cards.underfel_rift_cards import ROOT,REWARD
from hs_sim.cards.overdraw_return_card import register_overdraw_return_card
from test_underfel_rift_cards import registry as underfel_registry,P as OLD

P='questhand.test.'
PLAIN=P+'plain'
PROBE=P+'quest'
AWARD=P+'award'


@lru_cache(None)
def registry(role='writer',mode='plain'):
    r=underfel_registry();register_overdraw_return_card(r)
    def fail(c):raise ResolutionError('deliberate quest delivery rollback')
    r.register_behavior(P+'fail',fail)
    def fill(c):
        work=tuple(AddToHand(c.player_id,PLAIN,c.source_id)for _ in range(10-len(c.state.players[c.player_id].hand)))
        return(*work,Draw(c.player_id,3,c.source_id))if mode=='godfrey'else work
    def enable(c):
        source=next(i for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==GODFREY)
        return(AddPlayerEffect(c.player_id,PROGRAM,source),)
    def progress(c):
        if c.event.player_id!=c.player_id or c.event.source_id==c.source_id:return ()
        q=c.source.quest_progress;return(AdvanceQuest(c.source_id,q.id,q.stage),)
    def reward(c):
        material=AddToHand(c.player_id,'unknown.quest.reward'if mode=='unknown'else AWARD,c.source_id,
            cost=CostSpec(delta=-3)if mode=='cost'else None)
        if mode=='choice':return(RequestChoice(c.player_id,(ChoiceOption('yes','Reward',(material,)),ChoiceOption('no','Nothing')),c.source_id),)
        return(material,material)if mode=='multi'else(material,)
    bodies={
        'fill':fill,
        'maker':lambda c:tuple(CreateTemporaryCard(c.player_id,P+'fill'if mode!='room'else OLD+'noop',c.state.turn,source_id=c.source_id)for _ in range(6)),
        'free':lambda c:(GainArmor(c.player_id,1),),
        'enable':enable,
        'plain-generate':lambda c:(AddToHand(c.player_id,AWARD,c.source_id),AddToHand(c.player_id,AWARD,c.source_id)),
        'fail-generate':lambda c:(AddToHand(c.player_id,'unknown.quest.reward',c.source_id),),
        'progress':progress,'reward':reward,
    }
    for key,body in bodies.items():
        r.register_behavior(P+key,body)
        if key not in ('progress','reward'):r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key))
    r.register_card(CardDefinition(PLAIN,'Filler',CardType.MINION,cost=1,attack=1,health=2))
    r.register_card(CardDefinition(AWARD,'Fixed hand reward',CardType.MINION,cost=5,attack=4,health=5))
    r.register_card(CardDefinition(PROBE,'Quest probe',CardType.SPELL,cost=0,keywords=(Keyword.QUEST,),
        quest=QuestSpec('quest',(QuestStageSpec(PROBE,1,('card_played',),P+'progress',P+'reward'),))))
    if mode in ('wait','fail'):
        def watch(c):
            if c.state.entities[c.event.target_id].card_id not in(REWARD,AWARD):return ()
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
                (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Reward observer',CardType.MINION,health=20,
            triggers=(TriggerSpec('card_added_to_hand',P+'watch'),)))
    r.validate();r.freeze();return r


class QuestHandRewardTests(unittest.TestCase):
    def game(self,mode='plain',*,probe=False,seat=1):
        hand=(PROBE,P+'free',P+'fill',P+'free',P+'plain-generate')if probe else(ROOT,P+'maker',P+'free',P+'free')
        if mode=='godfrey':hand=(P+'enable',*hand)
        own=PlayerSetup(OLD+'hero',hand=hand,board=(P+'watch',)if mode in('wait','fail')else(),
            deck=(GODFREY,)+(PLAIN,)*24,mana=30,max_mana=30,mana_cap=30)
        other=PlayerSetup(OLD+'hero',deck=(PLAIN,)*4,mana=30,max_mana=30,mana_cap=30)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=2901),registry('writer',mode))
    def play(self,g,cid):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        d=g.registry.card(cid)
        g.apply(PlayCard(pid,eid,position=len(g.state.players[pid].board)if d.kind==CardType.MINION else None));return eid
    def complete(self,g,mode='plain'):
        if mode=='godfrey':self.play(g,P+'enable')
        source=self.play(g,ROOT);self.play(g,P+'maker')
        for _ in range(6):self.play(g,OLD+'noop'if mode=='room'else P+'fill')
        return source
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode='plain'):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry('reader',mode))
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),s);return other
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        return s

    def test_a01_real_underfel_full_completion_retires_quest_without_burning_reward(self):
        g=self.game();source=self.complete(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(g.state.players[1].quests)
        row,=g.state.quest_hand_rewards;self.assertEqual((row.phase,row.request.instruction.card_id),('pending',REWARD))
        self.assertFalse(any(e.kind=='card_burned'and g.state.entities[e.target_id].card_id==REWARD for e in g.events))
        self.assertFalse(any(e.card_id==REWARD for e in g.state.entities.values()));self.portable(g)

    def test_a02_next_real_slot_delivers_same_accepted_recipe_once_without_draw_or_rng(self):
        g=self.game();self.complete(g);before=g.snapshot()['rng_state'];self.play(g,P+'free')
        row,=g.state.quest_hand_rewards;self.assertEqual(row.phase,'delivered')
        self.assertEqual(g.state.entities[row.delivery.entity_id].card_id,REWARD)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(g.state.draw_history,[])
        self.play(g,P+'free');self.assertEqual(len([e for e in g.state.entities.values()if e.card_id==REWARD]),1)

    def test_a03_room_at_completion_uses_normal_shared_creator_immediately(self):
        g=self.game('room');self.complete(g,'room')
        row,=g.state.quest_hand_rewards;self.assertEqual(row.phase,'delivered')
        self.assertEqual(row.delivery.entity_id,g.state.players[1].hand[-1]);self.portable(g,'room')

    def test_a04_real_waiting_quest_reward_has_priority_over_godfrey_without_rng(self):
        g=self.game('godfrey');self.complete(g,'godfrey')
        self.assertEqual(g.state.quest_hand_rewards[0].phase,'pending')
        self.assertTrue(any(r.phase=='stored'for r in g.state.overdraw_returns))
        old=sum(r.phase=='returned'for r in g.state.overdraw_returns);before=g.snapshot()['rng_state']
        self.play(g,P+'free')
        self.assertEqual(g.state.quest_hand_rewards[0].phase,'delivered')
        self.assertEqual(sum(r.phase=='returned'for r in g.state.overdraw_returns),old)
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g,'godfrey')

    def test_a05_ordinary_generation_still_burns_and_is_not_a_quest_reward(self):
        g=self.game(probe=True);self.play(g,P+'fill');self.play(g,P+'plain-generate')
        self.assertEqual(g.state.quest_hand_rewards,[])
        self.assertEqual(sum(e.kind=='card_added_to_hand'for e in g.events if e.target_id and g.state.entities[e.target_id].card_id==AWARD),1)
        self.assertEqual(sum(e.kind=='card_burned'for e in g.events if e.target_id and g.state.entities[e.target_id].card_id==AWARD),1)

    def test_a06_missing_hand_material_is_rejected_before_deferral_and_action_rolls_back(self):
        g=self.game('unknown',probe=True);self.play(g,PROBE);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'fill')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.quest_hand_rewards,[])

    def test_a07_recipe_cost_is_frozen_and_roundtrips_while_pending(self):
        g=self.game('cost',probe=True);self.play(g,PROBE);self.play(g,P+'fill')
        self.assertEqual(g.state.quest_hand_rewards[0].phase,'pending');self.portable(g,'cost')
        self.play(g,P+'free');row=g.state.quest_hand_rewards[0]
        self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[row.delivery.entity_id]).amount,2)

    def test_a08_reward_choice_uses_original_cause_and_defers_only_selected_material(self):
        g=self.game('choice',probe=True);self.play(g,PROBE);self.play(g,P+'fill')
        self.assertIsNotNone(g.state.pending_choice);self.portable(g,'choice');self.choose(g,'yes')
        self.assertEqual(len(g.state.quest_hand_rewards),1);self.assertEqual(g.state.quest_hand_rewards[0].phase,'pending')
        self.play(g,P+'free');self.assertEqual(g.state.quest_hand_rewards[0].phase,'delivered')

    def test_b01_pending_survives_turn_change_and_returns_to_original_owner(self):
        g=self.game();self.complete(g);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(g.state.quest_hand_rewards[0].phase,'pending');self.play(g,P+'free')
        self.assertEqual(g.state.quest_hand_rewards[0].delivery.controller,1)

    def test_b02_second_seat_and_two_waiting_rewards_use_complete_fifo(self):
        g=self.game('multi',probe=True,seat=2);self.play(g,PROBE);self.play(g,P+'fill')
        self.assertEqual([r.phase for r in g.state.quest_hand_rewards],['pending','pending'])
        self.play(g,P+'free');self.assertEqual([r.phase for r in g.state.quest_hand_rewards],['delivered','pending'])
        self.play(g,P+'free');self.assertTrue(all(r.phase=='delivered'and r.delivery.controller==2 for r in g.state.quest_hand_rewards))

    def test_b03_delivery_observer_sees_committed_receipt_waits_and_bad_choice_rolls_back(self):
        g=self.game('wait');self.complete(g,'wait');self.play(g,P+'free')
        self.assertEqual(g.state.quest_hand_rewards[0].phase,'delivered');other=self.portable(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_b04_direct_delivery_error_rolls_back_slot_creation_recipe_and_events(self):
        g=self.game('fail');self.complete(g,'fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'free')
        self.assertEqual(g.snapshot(),before)

    def test_b05_pending_rewards_are_private_and_terminal_keeps_actual_prefix(self):
        g=self.game();self.complete(g)
        for pid in(1,2):
            view=json.dumps(g.observe(pid),sort_keys=True)
            for key in('quest_hand_rewards',ACCEPTED,DELIVERED,'instruction','completion'):self.assertNotIn(key,view)
        g.apply(Concede(1));self.assertEqual(g.state.quest_hand_rewards[0].phase,'pending');self.portable(g)

    def test_b06_fully_rehashed_cropped_or_changed_reward_obligation_is_rejected(self):
        g=self.game();self.complete(g)
        s=json.loads(json.dumps(g.snapshot()));s['state']['quest_hand_rewards']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry('reader'))
        s=json.loads(json.dumps(g.snapshot()));s['state']['quest_hand_rewards'][0]['request']['instruction']['card_id']=PLAIN
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry('reader'))
