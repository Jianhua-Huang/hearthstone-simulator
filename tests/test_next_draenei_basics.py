"""Independent next-play matching and finite phases reuse public player effects."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (AddPlayerEffect, CardClass, CardDefinition, CardType, CounterMinion,
    EndTurn, Game, IllegalAction, Keyword, PlayerEffectSpec, PlayCard, PlayerSetup, Rarity,
    RemovePlayerEffect, ResolutionError, Scenario, SecretSpec, SelectChoice,
    TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion, Destroy,
    RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.pools import PoolQuery, matches_metadata
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry

STAR, ASKARA, OTHER = 'GDB_720', 'GDB_455', 'CS2_168'
STATS, TWO, ONE = 'next.draenei.stats', 'next.draenei.copy.two', 'next.draenei.copy.one'
FIXTURE = Path(__file__).resolve().parents[1]/'data/support/next-draenei-basics.json'
PIN = '5c50466b83c99a1c4f17f56696a2654c91698fe393dbde528453997f05c2b51f'


def evidence():
    raw=json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw)!=PIN:raise ValueError('Next-Draenei full raw changed')
    for r in raw['records']:
        if r['id']!=r['data']['id'] or canonical_digest(r['data'])!=r['data_sha256']:
            raise ValueError('Next-Draenei complete original row changed')
    return {r['id']:r['data']for r in raw['records']}


def qualifies(c):
    """Pure accepted physical-hand profile; no current-state or card-name guess."""
    if c.event is None or c.event.kind!='minion_play_accepted' or c.player_effect is None:
        raise ResolutionError('Next-Draenei expression requires its original player-effect acceptance')
    if c.event.player_id!=c.player_id:return False
    if c.play is None:
        raise ResolutionError('Next-Draenei experimental expression needs an actual paid hand play')
    play=c.play;face=play.played_face
    if (play.source_id,play.player_id)!=(c.event.source_id,c.player_id):
        raise ResolutionError('Next-Draenei play differs from its original acceptance')
    if play.minion_result!='summoned':
        raise ResolutionError('Next-Draenei expression requires an accepted physical board minion')
    # Installation is later than the creator's own accepted-entry fact. A new
    # hand play of that same physical source is allowed to use the older gift.
    return matches_metadata(PoolQuery(kinds=(CardType.MINION,),tribes_any=('draenei',)),
        card_id=face.card_id,kind=face.kind,cost=0,meta=face.metadata,
        spell_school=face.spell_school,keywords=())


def registry(scripts=(), *, observers=(), counter=False, fault=None):
    r=opening_registry();rows=evidence()
    r.register_behavior('star.install',lambda c:(AddPlayerEffect(c.player_id,STATS,c.source_id),))
    def stats(c):
        if not qualifies(c):return ()
        work=(RemovePlayerEffect(c.player_id,c.player_effect.id),Buff(c.play.source_id,2,1,c.source_id))
        if fault=='missing':work+=(AddToHand(c.player_id,'missing.reward'),)
        if fault=='late':work+=(AddToDeck(c.player_id,OTHER),AddToHand(c.player_id,'missing.reward'))
        return work
    r.register_behavior('star.reward',stats)
    r.register_player_effect(PlayerEffectSpec(STATS,STAR,triggers=(TriggerSpec('minion_play_accepted','star.reward'),)))
    r.register_behavior('askara.install',lambda c:(AddPlayerEffect(c.player_id,TWO,c.source_id),))
    for phase,next_phase in ((TWO,ONE),(ONE,None)):
        def copy(c,next_phase=next_phase):
            if not qualifies(c):return ()
            work=(RemovePlayerEffect(c.player_id,c.player_effect.id),)
            if next_phase is not None:work+=(AddPlayerEffect(c.player_id,next_phase,c.source_id),)
            return (*work,CopyMinion(c.play.source_id,c.player_id))
        r.register_behavior(phase,copy)
        r.register_player_effect(PlayerEffectSpec(phase,ASKARA,triggers=(TriggerSpec('minion_play_accepted',phase),)))
    for cid,body,cls,rarity in ((STAR,'star.install',CardClass.NEUTRAL,Rarity.COMMON),
            (ASKARA,'askara.install',CardClass.PRIEST,Rarity.LEGENDARY)):
        row=rows[cid]
        r.register_card(CardDefinition(cid,row['name'],CardType.MINION,cost=row['cost'],
            attack=row['attack'],health=row['health'],battlecry=body,
            metadata=metadata(cls,rarity=rarity,tribes=('draenei',))))
    row=rows[OTHER]
    r.register_card(CardDefinition(OTHER,row['name'],CardType.MINION,cost=row['cost'],
        attack=row['attack'],health=row['health'],metadata=metadata(tribes=('murloc',),rarity=Rarity.FREE)))
    r.register_card(CardDefinition('probe.draenei','Synthetic plain Draenei',CardType.MINION,
        cost=2,attack=2,health=3,metadata=metadata(tribes=('draenei',))))
    r.register_card(CardDefinition('probe.all','Synthetic all-tribe minion',CardType.MINION,
        cost=1,attack=1,health=1,metadata=metadata(tribes=('all',))))
    r.register_card(CardDefinition('probe.unknown','Synthetic unknown metadata',CardType.MINION,
        cost=1,attack=1,health=1))
    # A simple Battlecry observation tests the reward's declared entry window.
    def body(c):
        target=c.state.entities[c.source_id]
        return (Buff(c.state.players[c.player_id].hero_id,target.attack,0),)
    r.register_behavior('probe.body',body)
    r.register_card(CardDefinition('probe.body','Synthetic body-window probe',CardType.MINION,
        cost=1,attack=1,health=2,battlecry='probe.body',metadata=metadata(tribes=('draenei',))))
    if counter:
        r.register_secret_condition('probe.counter',lambda c:c.window is not None and
            c.window.kind=='minion' and not c.window.countered and c.window.player_id!=c.player_id)
        r.register_behavior('probe.counter',lambda c:(CounterMinion(c.window.id),))
        r.register_card(CardDefinition('probe.counter','Synthetic minion counter',CardType.SPELL,
            keywords=(Keyword.SECRET,),secret=SecretSpec('probe.counter',('minion_counter_check',),'probe.counter','probe.counter'),
            metadata=metadata(collectible=False)))
    for name,event,callback in observers:
        r.register_behavior(name,callback)
        r.register_card(CardDefinition(name,name,CardType.MINION,health=4,
            triggers=(TriggerSpec(event,name),),metadata=metadata()))
    for name,callback in scripts:
        r.register_behavior(name,callback)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,metadata=metadata()))
    return r


class NextDraeneiTests(unittest.TestCase):
    def setUp(self):self.scripts=[];self.options={}
    def script(self,name,callback):self.scripts.append((name,callback))
    def watch(self,name,event,callback):self.options.setdefault('observers',[]).append((name,event,callback))
    def game(self,hand=(STAR,'probe.draenei'), *,board=(),enemy_hand=(),enemy_board=(),mana=10,deck=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=hand,board=board,mana=mana,max_mana=10,deck=deck or ('card.1',)*4),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy_board,mana=10,max_mana=10,deck=('card.1',)*4)),seed=89),
            registry(self.scripts,**self.options))
    def entity(self,g,cid,*,player=1,zone=Zone.HAND):
        return next(g.state.entities[i]for i in getattr(g.state.players[player],zone.value)if g.state.entities[i].card_id==cid)
    def captured_entity(self,c,cid,*,zone=Zone.BOARD,player=1):
        return next(c.state.entities[i]for i in getattr(c.state.players[player],zone.value)
            if c.state.entities[i].card_id==cid)
    def play(self,g,cid,player=None):
        player=player or g.state.active_player;eid=self.entity(g,cid,player=player).id
        g.apply(PlayCard(player,eid));return eid
    def effects(self,g,player=1):return [e.spec_id for e in g.state.players[player].player_effects]
    def choose(self,g):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
    def round(self,g):
        g.apply(EndTurn(1));g.apply(EndTurn(2))
    def wait(self,c):return (RequestChoice(1,(ChoiceOption('ok','Continue'),),c.source_id),)
    def copies(self,g,source):return [e for e in g.state.entities.values()if e.origin_entity_id==source]
    def portable(self,g):
        snap=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snap,registry(self.scripts,**self.options))
        self.assertEqual(other.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry(self.scripts,**self.options)).snapshot(),snap);return other

    def test_once_buff_installs_after_creator_and_consumes_only_next_matching_play(self):
        g=self.game((STAR,OTHER,'probe.draenei','probe.draenei'));source=self.play(g,STAR)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,1))
        self.assertEqual(self.effects(g),[STATS]);self.play(g,OTHER);self.assertEqual(self.effects(g),[STATS])
        first=self.play(g,'probe.draenei');self.assertEqual((g.state.entities[first].attack,g.state.entities[first].health),(4,4))
        self.assertEqual(self.effects(g),[])
        second=self.play(g,'probe.draenei');self.assertEqual((g.state.entities[second].attack,g.state.entities[second].health),(2,3))

    def test_next_two_copies_are_finite_named_phases(self):
        g=self.game((ASKARA,'probe.draenei','probe.draenei','probe.draenei'));self.play(g,ASKARA)
        self.assertEqual(self.effects(g),[TWO]);first=self.play(g,'probe.draenei')
        self.assertEqual(self.effects(g),[ONE]);second=self.play(g,'probe.draenei')
        self.assertEqual(self.effects(g),[]);self.play(g,'probe.draenei')
        copies=[e for e in g.state.entities.values()if e.origin_entity_id in (first,second)]
        self.assertEqual([e.origin_entity_id for e in copies],[first,second]);self.portable(g)

    def test_complete_rows_and_current_two_use_source_are_pinned(self):
        rows=evidence();local=json.loads((FIXTURE.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))
        # The raw extraction is a list, not a selected or reconstructed card face.
        self.assertIsInstance(local,list)
        original={row['id']:row for row in local}
        self.assertEqual(set(rows),{STAR,STAR+'e',ASKARA,ASKARA+'e',OTHER})
        for cid,row in rows.items():self.assertEqual(row,original[cid])
        self.assertIn('next two Draenei',rows[ASKARA]['text_en'])
        self.assertEqual((rows[ASKARA]['cost'],rows[ASKARA]['attack'],rows[ASKARA]['health']),(4,4,4))
        self.assertIn('next Draenei',rows[STAR]['text_en'])

    def test_same_physical_creator_can_receive_its_earlier_gift_on_replay(self):
        self.script('bounce',lambda c:(ReturnToHand(self.captured_entity(c,STAR).id),))
        g=self.game((STAR,'bounce','probe.draenei'));source=self.play(g,STAR)
        old=g.state.players[1].player_effects[0].id;self.play(g,'bounce');again=self.play(g,STAR)
        self.assertEqual(again,source)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(4,2))
        self.assertEqual(self.effects(g),[STATS]);self.assertNotEqual(g.state.players[1].player_effects[0].id,old)
        recipient=self.play(g,'probe.draenei');self.assertEqual(g.state.entities[recipient].attack,4)
        self.assertEqual(self.effects(g),[]);self.portable(g)

    def test_next_real_creator_receives_old_gift_then_installs_new_one(self):
        g=self.game((STAR,STAR,'probe.draenei'));self.play(g,STAR);second=self.play(g,STAR)
        self.assertEqual((g.state.entities[second].attack,g.state.entities[second].health),(4,2))
        self.assertEqual(self.effects(g),[STATS]);last=self.play(g,'probe.draenei')
        self.assertEqual(g.state.entities[last].attack,4);self.assertEqual(self.effects(g),[])

    def test_stat_reward_precedes_recipient_battlecry_in_declared_profile(self):
        g=self.game((STAR,'probe.body'));self.play(g,STAR);recipient=self.play(g,'probe.body')
        self.assertEqual((g.state.entities[recipient].attack,g.state.entities[recipient].health),(3,3))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,3)
        self.portable(g)

    def test_summoned_copy_does_not_run_battlecry_or_consume_next_phase(self):
        g=self.game((ASKARA,'probe.body'));self.play(g,ASKARA);recipient=self.play(g,'probe.body')
        self.assertEqual(self.effects(g),[ONE]);self.assertEqual(len(self.copies(g,recipient)),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,1)
        self.assertEqual([e.kind for e in g.events].count('minion_play_accepted'),2)

    def test_gift_persists_through_natural_rounds_until_match(self):
        g=self.game();self.play(g,STAR);self.round(g);self.round(g)
        self.assertEqual(self.effects(g),[STATS]);restored=self.portable(g)
        self.play(g,'probe.draenei');self.play(restored,'probe.draenei')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.effects(g),[])

    def test_source_silence_does_not_remove_player_gift(self):
        self.script('silence',lambda c:(Silence(self.captured_entity(c,STAR).id),))
        g=self.game((STAR,'silence','probe.draenei'));self.play(g,STAR);self.play(g,'silence')
        self.assertEqual(self.effects(g),[STATS]);target=self.play(g,'probe.draenei')
        self.assertEqual(g.state.entities[target].attack,4)

    def test_source_death_does_not_remove_player_gift(self):
        self.script('kill',lambda c:(Destroy(self.captured_entity(c,STAR).id,c.source_id),))
        g=self.game((STAR,'kill','probe.draenei'));source=self.play(g,STAR);self.play(g,'kill')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(self.effects(g),[STATS]);target=self.play(g,'probe.draenei')
        self.assertEqual(g.state.entities[target].attack,4);self.portable(g)

    def test_source_control_change_does_not_transfer_player_gift(self):
        self.script('give',lambda c:(ChangeControl(self.captured_entity(c,STAR).id,2),))
        g=self.game((STAR,'give','probe.draenei'));source=self.play(g,STAR);self.play(g,'give')
        self.assertEqual(g.state.entities[source].controller,2)
        self.assertEqual(self.effects(g),[STATS]);self.assertEqual(self.effects(g,2),[])
        target=self.play(g,'probe.draenei');self.assertEqual(g.state.entities[target].attack,4)

    def test_creation_summon_copy_and_draw_do_not_consume_a_play_gift(self):
        def generate(c):
            return (Summon(1,'probe.draenei'),CopyMinion(self.captured_entity(c,STAR).id,1),
                AddToHand(1,'probe.draenei'),MoveCard(CardReference.capture(self.captured_entity(c,'probe.draenei',zone=Zone.DECK)),1,Zone.HAND,draw=True))
        self.script('generate',generate)
        g=self.game((STAR,'generate'),deck=('probe.draenei','card.1'));self.play(g,STAR);self.play(g,'generate')
        self.assertEqual(self.effects(g),[STATS])
        copies=[e for e in g.state.entities.values()if e.card_id==STAR and e.origin_entity_id is not None]
        self.assertEqual(len(copies),1);self.assertEqual(copies[0].attack,2)
        self.assertEqual([e.kind for e in g.events].count('minion_play_accepted'),1)
        target=self.play(g,'probe.draenei');self.assertEqual(g.state.entities[target].attack,4)

    def test_other_player_matching_play_does_not_consume_owner_gift(self):
        g=self.game(enemy_hand=('probe.draenei',));self.play(g,STAR);g.apply(EndTurn(1))
        enemy=self.play(g,'probe.draenei');self.assertEqual(g.state.entities[enemy].attack,2)
        self.assertEqual(self.effects(g),[STATS]);g.apply(EndTurn(2))
        target=self.play(g,'probe.draenei');self.assertEqual(g.state.entities[target].attack,4)

    def test_all_tribe_uses_existing_metadata_matching(self):
        g=self.game((STAR,'probe.all'));self.play(g,STAR);target=self.play(g,'probe.all')
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(3,2))
        self.assertEqual(self.effects(g),[])

    def test_unknown_required_tribe_metadata_is_explicit_and_rolls_back(self):
        g=self.game((STAR,'probe.unknown'));self.play(g,STAR);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'metadata|Metadata'):self.play(g,'probe.unknown')
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.effects(g),[STATS])

    def test_countered_recipient_retains_gift_under_accepted_entry_policy(self):
        self.options['counter']=True
        g=self.game(enemy_hand=('probe.counter',));self.play(g,STAR);g.apply(EndTurn(1));self.play(g,'probe.counter')
        g.apply(EndTurn(2));target=self.play(g,'probe.draenei')
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(self.effects(g),[STATS]);self.portable(g)

    def test_illegal_full_board_play_preserves_gift_and_transaction(self):
        g=self.game(board=(OTHER,)*6);self.play(g,STAR);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'probe.draenei')
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.effects(g),[STATS])

    def test_board_filled_after_payment_retains_gift_when_recipient_cannot_enter(self):
        self.watch('fill','minion_counter_check',lambda c:(Summon(1,OTHER),)
            if c.state.entities[c.event.source_id].card_id=='probe.draenei' else ())
        g=self.game(board=(OTHER,)*4+('fill',));self.play(g,STAR);before_mana=g.state.players[1].mana
        target=self.play(g,'probe.draenei')
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].mana,before_mana-2)
        self.assertEqual(self.effects(g),[STATS]);self.assertEqual(len(g.state.players[1].board),7)
        failures=[e for e in g.events if e.kind=='minion_entry_failed']
        self.assertEqual([e.source_id for e in failures],[target]);self.portable(g)

    def test_second_copy_on_full_board_consumes_last_phase_without_extra_minion(self):
        g=self.game((ASKARA,'probe.draenei','probe.draenei'),board=(OTHER,)*3);self.play(g,ASKARA)
        first=self.play(g,'probe.draenei');self.assertEqual(len(self.copies(g,first)),1)
        self.assertEqual(len(g.state.players[1].board),6);self.assertEqual(self.effects(g),[ONE])
        second=self.play(g,'probe.draenei');self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(self.copies(g,second),[]);self.assertEqual(self.effects(g),[]);self.portable(g)

    def test_next_two_midpoint_restores_and_replays_remaining_phase(self):
        g=self.game((ASKARA,'probe.draenei','probe.draenei'));self.play(g,ASKARA);self.play(g,'probe.draenei')
        self.assertEqual(self.effects(g),[ONE]);restored=self.portable(g)
        target=self.play(g,'probe.draenei');self.play(restored,'probe.draenei')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(len(self.copies(g,target)),1)
        self.assertEqual(self.effects(g),[])

    def test_removed_instance_wait_restores_pending_stat_reward_once(self):
        self.watch('wait','player_effect_removed',self.wait)
        g=self.game(board=('wait',));self.play(g,STAR);target=self.play(g,'probe.draenei')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.effects(g),[])
        self.assertEqual(g.state.entities[target].attack,2);restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(g.state.entities[target].attack,4)
        self.assertEqual([e.kind for e in g.events].count('player_effect_removed'),1)

    def test_replacement_phase_wait_restores_original_copy_without_consuming_again(self):
        self.watch('wait','player_effect_added',lambda c:self.wait(c)if dict(c.event.data)['effect_key']==ONE else ())
        g=self.game((ASKARA,'probe.draenei'),board=('wait',));self.play(g,ASKARA);target=self.play(g,'probe.draenei')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.effects(g),[ONE])
        self.assertEqual(self.copies(g,target),[]);restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(len(self.copies(g,target)),1);self.assertEqual(self.effects(g),[ONE])

    def test_post_reward_wait_does_not_repeat_stats_or_reinstall_effect(self):
        self.watch('wait','stats_changed',lambda c:self.wait(c)if c.event.target_id is not None and
            c.state.entities[c.event.target_id].card_id=='probe.draenei' else ())
        g=self.game(board=('wait',));self.play(g,STAR);target=self.play(g,'probe.draenei')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.effects(g),[])
        self.assertEqual(g.state.entities[target].attack,4);restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(g.state.entities[target].attack,4)

    def test_late_reward_failure_restores_stats_instances_rng_and_all_history(self):
        self.options['fault']='late';g=self.game();self.play(g,STAR);before=g.snapshot();rng=g._rng.getstate()
        with self.assertRaisesRegex(ResolutionError,'missing.reward'):self.play(g,'probe.draenei')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(self.effects(g),[STATS]);self.portable(g)

    def test_public_player_effect_dto_does_not_leak_engine_identities(self):
        g=self.game();self.play(g,STAR);before=g.snapshot();rng=g._rng.getstate()
        expected={'effect_key':STATS,'card_id':STAR,'effect_kind':'persistent','remaining_turns':None}
        for viewer in (1,2):
            self.assertEqual(g.observe(viewer)['players'][0]['player_effects'],[expected])
            public=json.dumps(g.observe(viewer))
            for private in ('instance_id','source_id','zone_epoch','played_face','random_state'):
                self.assertNotIn('"'+private+'"',public)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g._rng.getstate(),rng)
