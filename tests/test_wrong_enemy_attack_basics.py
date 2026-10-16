"""A real wrong-enemy source uses existing sampled offers and attack replacement."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, TriggerSpec)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    InvokeBehavior, ReplaceHero, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.interrupts import RedirectAttack, attack_live, find_window
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

OGRE='GVG_065'
PATH=Path(__file__).resolve().parents[1]/'data/support/wrong-enemy-attack-basics.json'
PIN='ad8cbaac35fea05ea152f39e6a7855a036f0bd6cadcf3cc329e5c9b8f3194470'


def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Ogre evidence changed')
    row=support['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw card evidence changed')
    return row['data']


def alternate_ids(state,window):
    if not attack_live(state,window):return ()
    actor=state.entities[window.source_id];enemy=state.players[3-actor.controller]
    return tuple(sorted(i for i in (enemy.hero_id,*enemy.board) if i!=window.target_id and
        (e:=state.entities[i]).active and e.is_character and e.health>0 and not e.doomed))


def registry():
    r=Registry('isolated-wrong-enemy-attack-basics-v1');raw=evidence()
    for cid in ('hero','replacement-hero'):
        r.register_card(CardDefinition(cid,cid,CardType.HERO,health=80,metadata=metadata()))
    for cid,attack,fields in (('plain',2,{}),('taunt',0,{'keywords':(Keyword.TAUNT,)}),
            ('stealth',0,{'keywords':(Keyword.STEALTH,)}),('sleeping',0,{'dormant_turns':2})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=12,
            metadata=metadata(),**fields))
    def sampled(c):
        result=c.choice
        if (result is None or result.selected_ids or len(result.choice.options)!=1 or
                (result.choice.min_count,result.choice.max_count)!=(0,0)):
            raise ValueError('Expected one automatically sampled offer')
        item=result.choice.options[0];wid,stage=item.id.split('.')
        return int(wid),stage,item
    def start(c):
        if c.event.source_id!=c.source_id:return ()
        wid=dict(c.event.data)['window_id']
        # Refresh through the original zero-selection callback before using RNG.
        return (RequestChoice(c.player_id,(ChoiceOption(f'{wid}.start','Start'),),
            c.source_id,min_count=0,max_count=0,on_select='ogre.begin'),)
    def begin(c):
        wid,stage,_=sampled(c);assert stage=='start'
        w=find_window(c.state,wid);actor=c.state.entities[c.source_id]
        if (w is None or w.source_id!=actor.id or actor.card_id!=OGRE or actor.silenced or
                not alternate_ids(c.state,w)):return ()
        return (RequestChoice(actor.controller,(ChoiceOption(f'{wid}.keep','Keep'),
            ChoiceOption(f'{wid}.redirect','Redirect')),c.source_id,min_count=0,max_count=0,
            sample_size=1,on_select='ogre.coin'),)
    def coin(c):
        wid,stage,_=sampled(c)
        if stage=='keep':return ()
        assert stage=='redirect'
        w=find_window(c.state,wid);ids=alternate_ids(c.state,w)
        if not ids:return ()
        return (RequestChoice(c.state.entities[w.source_id].controller,
            tuple(ChoiceOption(f'{wid}.target{i}',str(i),entity_id=i) for i in ids),
            c.source_id,min_count=0,max_count=0,sample_size=1,on_select='ogre.target'),)
    def target(c):
        wid,stage,item=sampled(c)
        if stage!=f'target{item.entity_id}':raise ValueError('Wrong target offer identity')
        return (RedirectAttack(wid,item.entity_id),)
    for name,fn in (('ogre.attack',start),('ogre.begin',begin),('ogre.coin',coin),('ogre.target',target)):
        r.register_behavior(name,fn)
    r.register_card(CardDefinition(OGRE,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],triggers=(TriggerSpec('attack_declared','ogre.attack'),),
        metadata=metadata()))
    def actor(c):return next(i for i in c.state.players[1].board if c.state.entities[i].card_id==OGRE)
    def fault(c):raise ValueError('Fixture late failure')
    r.register_behavior('late-fault',fault)
    def pause(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id!=OGRE:return ()
        return (RequestChoice(1,(
            ChoiceOption('resolve','Resolve',()),
            ChoiceOption('destroy','Remove attacker',(Destroy(c.event.source_id),)),
            ChoiceOption('replace','Replace hero',(ReplaceHero(2,'replacement-hero'),)),
            ChoiceOption('fault','Replace and fail',(ReplaceHero(2,'replacement-hero'),
                InvokeBehavior('late-fault',source_id=c.source_id,player_id=1))),
        ),c.source_id),)
    for cid,event in (('watch-before','attack_declared'),('watch-after','attack_redirected')):
        r.register_behavior(cid,pause)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=12,
            triggers=(TriggerSpec(event,cid),),metadata=metadata()))
    r.register_card(CardDefinition('fault-after','Fail after combat',CardType.MINION,health=12,
        triggers=(TriggerSpec('attack_finished','late-fault'),),metadata=metadata()))
    for cid,fn in (
        ('silence',lambda c:(Silence(c.target_id),)),
        ('transform',lambda c:(Transform(c.target_id,'plain'),)),
        ('bounce',lambda c:(ReturnToHand(c.target_id),)),
        ('copy',lambda c:(CopyMinion(c.target_id,1),)),
        ('base-copy',lambda c:(CopyMinion(c.target_id,1,mode='base'),)),
        ('transfer',lambda c:(ChangeControl(c.target_id,2),)),
        ('sleep',lambda c:(MakeDormant(c.target_id,None),)),
        ('wake',lambda c:(AwakenMinion(actor(c)),)),
    ):
        r.register_behavior(cid,fn)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=cid!='wake',metadata=metadata()))
    return r


def seed_for(outcome):
    return next(seed for seed in range(256) if random.Random(seed).sample(('keep','redirect'),1)[0]==outcome)


class WrongEnemyAttackBasicsTests(unittest.TestCase):
    def game(self,enemy=('plain',),board=(OGRE,),hand=(),outcome='redirect'):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*4,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy,deck=('plain',)*4,mana=10,max_mana=10),
        ),seed=seed_for(outcome)),registry())
    def actor(self,g,p=1):return next(i for i in g.state.players[p].board if g.state.entities[i].card_id==OGRE)
    def hero(self,g,p=2):return g.state.players[p].hero_id
    def attack(self,g,target=None,source=None):
        return g.apply(Attack(1,self.actor(g) if source is None else source,
            self.hero(g) if target is None else target))
    def play(self,g,cid,target):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(1,eid,target if g.registry.card(cid).requires_target else None))
    def choose(self,g,key='resolve'):
        c=g.state.pending_choice;return g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,registry()).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
    def probe(self,g,target):
        probe=random.Random();probe.setstate(g._rng.getstate())
        choice=probe.sample(('keep','redirect'),1)[0]
        actor=g.state.entities[self.actor(g)];enemy=g.state.players[3-actor.controller]
        ids=tuple(sorted(i for i in (enemy.hero_id,*enemy.board) if i!=target and
            g.state.entities[i].active and g.state.entities[i].health>0 and not g.state.entities[i].doomed))
        return choice,(probe.sample(ids,1)[0] if choice=='redirect' else target),probe.getstate()
    def redirected(self,g):return [e for e in g.events if e.kind=='attack_redirected']

    def test_full_raw_pin_real_source_and_presence_tag(self):
        raw=evidence();self.assertEqual((raw['id'],raw['dbf_id'],raw['cost'],raw['attack'],raw['health']),
            (OGRE,2033,3,4,4))
        self.assertEqual(raw['text_en'],'50% chance to attack the wrong enemy.')
        self.assertEqual(raw['tags']['FORGETFUL'],1)
        card=registry().card(OGRE)
        self.assertEqual(card.triggers,(TriggerSpec('attack_declared','ogre.attack'),))

    def test_coin_keep_has_one_sample_and_original_ordinary_attack(self):
        g=self.game(outcome='keep');a=self.actor(g);d=self.hero(g)
        coin,selected,after=self.probe(g,d);self.assertEqual((coin,selected),('keep',d))
        result=self.attack(g)
        self.assertEqual(g._rng.getstate(),after);self.assertFalse(self.redirected(g))
        self.assertEqual(g.state.entities[d].damage,4)
        self.assertEqual(g.state.entities[a].attacks_this_turn,1)
        self.assertFalse(g.state.pending_choice)
        self.assertEqual(sum(e.kind=='attack_declared' for e in result.events),1)
        self.assertEqual(sum(e.kind=='attack_finished' for e in result.events),1);self.check(g)

    def test_coin_redirect_samples_other_enemy_and_uses_same_window(self):
        g=self.game();a=self.actor(g);d=self.hero(g);coin,selected,after=self.probe(g,d)
        self.assertEqual(coin,'redirect');result=self.attack(g)
        self.assertEqual(g._rng.getstate(),after)
        changed=self.redirected(g);self.assertEqual(len(changed),1)
        self.assertEqual(changed[0].target_id,selected)
        self.assertNotEqual(selected,d)
        self.assertEqual(g.state.entities[d].damage,0)
        self.assertEqual(g.state.entities[selected].damage,4)
        self.assertEqual(g.state.entities[a].damage,2)
        self.assertEqual(g.state.entities[a].attacks_this_turn,1)
        self.assertEqual(sum(e.kind=='attack_declared' for e in result.events),1)
        declared=next(e for e in result.events if e.kind=='attack_declared')
        self.assertFalse(dict(declared.data).get('forced',False))
        self.assertFalse(g.state.pending_choice);self.check(g)

    def test_minion_declared_target_can_redirect_to_enemy_hero(self):
        g=self.game();d=g.state.players[2].board[0]
        coin,selected,after=self.probe(g,d);self.assertEqual((coin,selected),('redirect',self.hero(g)))
        self.attack(g,d);self.assertEqual(g._rng.getstate(),after)
        self.assertEqual(g.state.entities[self.hero(g)].damage,4)
        self.assertEqual(g.state.entities[d].damage,0);self.check(g)

    def test_multiple_physical_alternates_each_have_one_weight_in_ordered_sample(self):
        g=self.game(enemy=('plain','plain','plain'));d=g.state.players[2].board[1]
        coin,selected,after=self.probe(g,d);self.assertEqual(coin,'redirect')
        self.attack(g,d)
        self.assertEqual(self.redirected(g)[0].target_id,selected)
        self.assertNotEqual(selected,d);self.assertEqual(g._rng.getstate(),after);self.check(g)

    def test_single_enemy_has_no_wrong_target_and_no_rng_sample(self):
        g=self.game(enemy=());before=g._rng.getstate();result=self.attack(g)
        self.assertEqual(g._rng.getstate(),before);self.assertFalse(self.redirected(g))
        self.assertFalse(g.state.pending_choice)
        self.assertFalse(any(e.kind=='choice_requested' for e in result.events))
        self.assertEqual(g.state.entities[self.hero(g)].damage,4);self.check(g)

    def test_wrong_target_can_bypass_taunt_and_reach_stealth(self):
        g=self.game(enemy=('taunt','stealth'));d=g.state.players[2].board[0]
        # Choose a seed whose second sample reaches the stealth minion.
        for seed in range(100):
            p=random.Random(seed)
            if p.sample(('keep','redirect'),1)[0]=='redirect' and p.sample((0,1),1)[0]==1:
                break
        g=Game.from_scenario(Scenario((
            PlayerSetup('hero',board=(OGRE,),deck=('plain',)*4),
            PlayerSetup('hero',board=('taunt','stealth'),deck=('plain',)*4)),seed=seed),registry())
        d,s=g.state.players[2].board;before=g.snapshot()
        with self.assertRaises(IllegalAction):self.attack(g,s)
        self.assertEqual(g.snapshot(),before)
        self.attack(g,d)
        self.assertEqual(self.redirected(g)[0].target_id,s)
        self.assertEqual(g.state.entities[s].damage,4)
        self.assertEqual(g.state.entities[d].damage,0);self.check(g)

    def test_dormant_enemy_never_enters_wrong_target_pool(self):
        g=self.game(enemy=('sleeping',));rng=g._rng.getstate();self.attack(g)
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.redirected(g))
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].damage,0);self.check(g)

    def test_another_minions_attack_does_not_roll_ogre_chance(self):
        g=self.game(board=(OGRE,'plain'));rng=g._rng.getstate()
        self.attack(g,source=g.state.players[1].board[1])
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.redirected(g));self.check(g)

    def test_enemy_ogre_does_not_roll_when_its_opponent_attacks(self):
        g=self.game(board=('plain',),enemy=(OGRE,'plain'));rng=g._rng.getstate()
        self.attack(g,source=g.state.players[1].board[0])
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.redirected(g));self.check(g)

    def test_silence_removes_original_listener_and_no_chance_is_sampled(self):
        g=self.game(hand=('silence',));a=self.actor(g);self.play(g,'silence',a)
        rng=g._rng.getstate();self.attack(g)
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.redirected(g));self.check(g)

    def test_transform_removes_listener_from_same_physical_entity(self):
        g=self.game(hand=('transform',));a=self.actor(g);self.play(g,'transform',a)
        rng=g._rng.getstate();self.attack(g,source=a)
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.redirected(g));self.check(g)

    def test_return_and_replay_reinstalls_native_source_without_rng_on_bounce(self):
        g=self.game(hand=('bounce',));a=self.actor(g);rng=g._rng.getstate()
        self.play(g,'bounce',a);self.assertEqual(g._rng.getstate(),rng)
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==OGRE)
        g.apply(PlayCard(1,eid));self.assertEqual(g.state.players[1].mana,7)
        self.assertTrue(any(b.behavior_id=='ogre.attack' for b in g.state.entities[eid].abilities))
        self.check(g)

    def test_current_and_base_copy_each_use_existing_native_listener_identity(self):
        for cid in ('copy','base-copy'):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,));a=self.actor(g);self.play(g,cid,a)
                copied=g.state.players[1].board[-1]
                left=next(b for b in g.state.entities[a].abilities if b.behavior_id=='ogre.attack')
                right=next(b for b in g.state.entities[copied].abilities if b.behavior_id=='ogre.attack')
                self.assertNotEqual(left.id,right.id)
                g.apply(EndTurn(1));g.apply(EndTurn(2));self.attack(g,source=copied)
                self.assertEqual(self.redirected(g)[0].source_id,copied)
                self.assertEqual(g.state.entities[a].attacks_this_turn,0)
                self.assertEqual(g.state.entities[copied].attacks_this_turn,1);self.check(g)

    def test_control_transfer_retains_native_listener_and_new_controller(self):
        g=self.game(hand=('transfer',),board=(OGRE,'plain'));a=self.actor(g);self.play(g,'transfer',a)
        self.assertEqual(g.state.entities[a].controller,2)
        self.assertTrue(any(b.behavior_id=='ogre.attack' for b in g.state.entities[a].abilities))
        g.apply(EndTurn(1));g.apply(Attack(2,a,self.hero(g,1)))
        changed=self.redirected(g)[0]
        self.assertEqual(g.state.entities[changed.target_id].controller,1)
        self.assertEqual(g.state.entities[self.hero(g,1)].damage,0)
        self.assertEqual(g.state.entities[a].attacks_this_turn,1);self.check(g)

    def test_dormancy_blocks_normal_attack_without_sampling_and_wake_preserves_listener(self):
        g=self.game(hand=('sleep','wake'));a=self.actor(g);self.play(g,'sleep',a)
        before=g.snapshot();rng=g._rng.getstate()
        with self.assertRaises(IllegalAction):self.attack(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g._rng.getstate(),rng)
        self.play(g,'wake',a)
        self.assertTrue(any(b.behavior_id=='ogre.attack' for b in g.state.entities[a].abilities));self.check(g)

    def test_second_normal_attack_is_rejected_without_another_chance(self):
        g=self.game();self.attack(g);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.attack(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_wait_before_coin_preserves_unsampled_root_and_recovers_independent_registry(self):
        g=self.game(board=('watch-before',OGRE));rng=g._rng.getstate();self.attack(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng)
        self.check(g)
        others=(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),registry()),
            g.clone(),replay(build_replay(g),registry()))
        self.choose(g)
        for other in others:
            self.choose(other);self.assertEqual(other.snapshot(),g.snapshot())
        self.assertEqual(len(self.redirected(g)),1);self.check(g)

    def test_attacker_removed_before_coin_causes_no_random_sampling(self):
        g=self.game(board=('watch-before',OGRE));rng=g._rng.getstate();self.attack(g)
        self.choose(g,'destroy')
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.redirected(g))
        self.assertFalse(any(g.state.entities[i].card_id==OGRE for i in g.state.players[1].board))
        self.check(g)

    def test_wait_after_redirect_saves_original_window_selected_target_and_rng(self):
        g=self.game(board=(OGRE,'watch-after'));d=self.hero(g)
        _,selected,after=self.probe(g,d);self.attack(g)
        self.assertIsNotNone(g.state.pending_choice)
        w=g.state.action_windows[0]
        self.assertEqual((w.target_id,w.forced),(selected,False))
        self.assertEqual(g._rng.getstate(),after);self.assertEqual(g.state.entities[selected].damage,0)
        self.check(g)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),registry())
        self.choose(g);self.choose(restored)
        self.assertEqual(restored.snapshot(),g.snapshot());self.assertEqual(g._rng.getstate(),after)
        self.assertEqual(g.state.entities[selected].damage,4);self.check(g)

    def test_selected_hero_replaced_during_wait_cancels_delivery_without_new_sample(self):
        g=self.game(board=(OGRE,'watch-after'));d=g.state.players[2].board[0]
        self.attack(g,d);old=self.hero(g);rng=g._rng.getstate()
        self.assertEqual(g.state.action_windows[0].target_id,old)
        self.choose(g,'replace')
        self.assertNotEqual(self.hero(g),old);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.entities[self.hero(g)].damage,0)
        self.assertEqual(len(self.redirected(g)),1);self.check(g)

    def test_failed_selection_rolls_back_original_waiting_window_and_rng(self):
        g=self.game(board=(OGRE,'watch-after'));self.attack(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.check(g)
        self.choose(g);self.assertEqual(len(self.redirected(g)),1)

    def test_failure_after_combat_rolls_back_attack_counter_damage_rng_and_events(self):
        g=self.game(board=(OGRE,'fault-after'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.attack(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_auto_offers_do_not_request_player_actions_or_publish_internal_options(self):
        g=self.game();result=self.attack(g)
        self.assertFalse(g.state.pending_choice)
        self.assertFalse(any(e.kind in ('choice_requested','choice_selected') for e in result.events))
        for p in (1,2):
            events=g.player_events(p);text=json.dumps(events).lower()
            self.assertNotIn('choice_skipped',text)
            self.assertNotIn('redirect"',text);self.assertNotIn('ogre.coin',text)
        self.check(g)

    def test_player_queries_are_pure_during_actual_redirect_wait(self):
        g=self.game(board=(OGRE,'watch-after'));self.attack(g);before=g.snapshot()
        for p in (1,2):
            v=g.for_player(p);v.observe();v.events();v.legal_actions()
            text=json.dumps(v.observe()).lower()
            for hidden in ('rng_state','action_windows','ogre.coin','resolution_frame','enchantments'):
                self.assertNotIn(hidden,text)
        self.assertEqual(g.snapshot(),before)

    def test_existing_core_and_wire_versions_remain_and_recipe_is_replayable(self):
        g=self.game();self.attack(g);snap=g.snapshot()
        self.assertEqual((snap['ruleset']['id'],snap['mechanics_version']['version'],snap['schema_version']),
            ('prototype-v302',CORE_EFFECTS_VERSION,SNAPSHOT_SCHEMA_VERSION));self.check(g)


if __name__=='__main__':unittest.main()
