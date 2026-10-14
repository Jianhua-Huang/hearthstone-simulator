"""A whole-game player marker reuses persistent effects and committed play history."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,PlayCard,PlayerEffectSpec,
    PlayerSetup,QueueTurns,Rarity,ResolutionError,Scenario,SelectChoice,SnapshotError)
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,ReplaceHero
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.representative import build_registry,metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='1da12b9e6a3b3d9c0146b1fd94da091c922dac4ac673990cb3c5c1f1fe952e0c'
MARKER='game.used.zarimi'

def evidence():
    p=json.loads((ROOT/'data/support/player-once-per-game-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Player whole-game evidence changed')
    return p

def registry(mode='direct'):
    r=build_registry();x=next(x for x in evidence()['records'] if x['id']=='TOY_385')
    def fail(c):raise ResolutionError('Diagnostic once-game body failure')
    r.register_behavior('og.fail',fail)
    def body(c):
        if any(e.spec_id==MARKER for e in c.state.players[c.player_id].player_effects):return ()
        if c.play is None:raise ResolutionError('Experimental Zarimi needs its actual paid play')
        dragons=played_cards(c.state,c.player_id,before_id=c.play.id,registry=r,tribes_any=('dragon',))
        if len(dragons)<8:return ()
        marker=AddPlayerEffect(c.player_id,MARKER,c.source_id);turn=QueueTurns((c.player_id,),c.source_id)
        if mode=='wait':return (marker,RequestChoice(c.player_id,(
            ChoiceOption('turn','Turn',(turn,)),ChoiceOption('fail','Fail',(turn,InvokeBehavior('og.fail',c.source_id,c.player_id)))),c.source_id))
        if mode=='fail':return (marker,turn,InvokeBehavior('og.fail',c.source_id,c.player_id))
        return (marker,turn)
    r.register_behavior('og.zarimi.'+mode,body)
    r.register_card(CardDefinition('TOY_385',x['name'],CardType.MINION,cost=x['cost'],attack=x['attack'],health=x['health'],
        metadata=metadata_from_record(x),battlecry='og.zarimi.'+mode))
    r.register_player_effect(PlayerEffectSpec(MARKER,'TOY_385'))
    for name,fn in (
        ('clear',lambda c:tuple(Destroy(i) for i in c.state.players[c.player_id].board)),
        ('bounce',lambda c:(ReturnToHand(c.target_id),)),
        ('hero',lambda c:(ReplaceHero(c.player_id,'HERO_01'),))):
        r.register_behavior('og.'+name,fn)
        r.register_card(CardDefinition('og.'+name,'Diagnostic '+name,CardType.SPELL,on_play='og.'+name,requires_target=name=='bounce',
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())))
    return r

class PlayerOnceGameTests(unittest.TestCase):
    def game(self,ready=True,mode='direct'):
        self.mode=mode
        hand=('NEW1_023',)*8+('og.clear','TOY_385') if ready else ('TOY_385','og.bounce','og.hero')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=('TOY_385','og.clear')+('CS2_182',)*12,
            max_mana=10,mana=10),PlayerSetup('HERO_08',deck=('CS2_182',)*12,max_mana=10,mana=10)),seed=128),registry(mode))
    def card(self,g,name):return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,target=None):return g.apply(PlayCard(g.state.active_player,self.card(g,name),target))
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def prepare(self,g):
        for _ in range(4):self.play(g,'NEW1_023')
        self.play(g,'og.clear');self.cycle(g)
        for _ in range(4):self.play(g,'NEW1_023')
        self.cycle(g)
    def used(self,g):return [e for e in g.state.players[1].player_effects if e.spec_id==MARKER]
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry(self.mode)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s);return s

    def test_five_complete_sources_are_pinned_and_other_bodies_not_claimed(self):
        p=evidence();self.assertEqual(len(p['records']),5);self.assertFalse(p['full_card_adaptation'])
        self.assertEqual(p['new_runtime_modules'],0);self.assertEqual(p['new_state_fields'],0)

    def test_unmet_condition_does_not_spend_once_game_marker(self):
        g=self.game(ready=False);self.play(g,'TOY_385')
        self.assertEqual(self.used(g),[]);self.assertFalse(any(e.kind=='turns_scheduled' for e in g.events));self.portable(g)

    def test_prior_dragon_history_commits_marker_then_one_extra_turn(self):
        g=self.game();self.prepare(g)
        self.assertEqual(len(played_cards(g.state,1,registry=g.registry,tribes_any=('dragon',))),8)
        self.play(g,'TOY_385');self.assertEqual(len(self.used(g)),1)
        kinds=[e.kind for e in g.events];self.assertLess(kinds.index('player_effect_added'),kinds.index('turns_scheduled'))
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1);self.portable(g)

    def test_second_physical_copy_uses_same_player_limit(self):
        g=self.game();self.prepare(g);first=self.card(g,'TOY_385');self.play(g,'TOY_385')
        second=self.card(g,'TOY_385');self.assertNotEqual(first,second);self.play(g,'TOY_385')
        self.assertEqual(len(self.used(g)),1);self.assertEqual(sum(e.kind=='turns_scheduled' for e in g.events),1);self.portable(g)

    def test_persistent_marker_survives_source_death_and_new_actual_turn(self):
        g=self.game();self.prepare(g);self.play(g,'TOY_385');source=self.used(g)[0].source_id
        self.play(g,'og.clear');self.assertEqual(len(self.used(g)),1)
        self.assertEqual(g.state.entities[source].zone.value,'graveyard')
        g.apply(EndTurn(1));self.assertEqual(len(self.used(g)),1);self.portable(g)

    def test_marker_commits_before_waiting_and_restore_resume_keeps_one_use(self):
        g=self.game(mode='wait');self.prepare(g);self.play(g,'TOY_385');self.assertEqual(len(self.used(g)),1)
        s=self.portable(g);choice=g.state.pending_choice;restored=Game.from_snapshot(s,registry(self.mode))
        g.apply(SelectChoice(1,choice.id,('turn',)));restored.apply(SelectChoice(1,choice.id,('turn',)))
        self.assertEqual(restored.snapshot(),g.snapshot());self.assertEqual(len(self.used(g)),1);self.portable(g)

    def test_failed_direct_body_rolls_back_marker_turn_queue_and_payment(self):
        g=self.game(mode='fail');self.prepare(g);s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic once-game body failure'):self.play(g,'TOY_385')
        self.assertEqual(g.snapshot(),s)

    def test_failed_choice_preserves_already_committed_marker_and_pending_state(self):
        g=self.game(mode='wait');self.prepare(g);self.play(g,'TOY_385');s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic once-game body failure'):
            g.apply(SelectChoice(1,g.state.pending_choice.id,('fail',)))
        self.assertEqual(g.snapshot(),s);self.assertEqual(len(self.used(g)),1)

    def test_marker_is_player_owned_and_exposes_no_global_attachment_ids(self):
        g=self.game();self.prepare(g);self.play(g,'TOY_385')
        self.assertFalse(any(e.spec_id==MARKER for e in g.state.players[2].player_effects))
        for p in (1,2):
            text=json.dumps([g.for_player(p).observe(),g.for_player(p).events()])
            self.assertNotIn('entered_order',text);self.assertNotIn('source_card_id',text);self.assertNotIn('created_turn',text)

if __name__=='__main__':unittest.main()
