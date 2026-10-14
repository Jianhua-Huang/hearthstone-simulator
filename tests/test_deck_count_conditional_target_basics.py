"""Real conditional ordinary Battlecry using the existing target and player APIs."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, PlayerTargetRuleSpec, Rarity, Registry, ResolutionError,
    Scenario, SelectChoice, SnapshotError, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.deck_conditions import CheckDeckCondition, DeckCountCondition
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Damage, Destroy, Draw,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE='BAR_916'
PATH=Path(__file__).resolve().parents[1]/'data/support/deck-count-conditional-target-basics.json'
PIN='a3ff6a02d82b2b8a9240adb2454c31d9bb369d12f61f19cb2be5bb329f9a0807'
LOW=DeckCountCondition(10,'at_most')
DOMAIN=TargetSpec(TargetMode.IF_AVAILABLE,(Zone.BOARD,),(CardType.MINION,))


def evidence():
    support=json.loads(PATH.read_bytes())
    if canonical_digest(support)!=PIN:raise ValueError('Complete conditional target raw evidence changed')
    row=support['records'][0]
    if row['id']!=NATIVE or canonical_digest(row['data'])!=row['data_sha256']:
        raise ValueError('Complete native card raw changed')
    return row['data']


def registry():
    r=Registry('isolated-deck-count-conditional-target-v1');raw=evidence()
    def visible_low(c):
        assert not hasattr(c,'state')and not hasattr(c,'target_id')
        return c.observation['players'][c.player_id-1]['deck_count']<=LOW.card_count
    r.register_player_target_rule(PlayerTargetRuleSpec('deck-low-minion-v1','v1'),visible_low)
    r.register_behavior('native',lambda c:()if c.target_id is None else(
        CheckDeckCondition(c.player_id,LOW,(Damage(c.target_id,6,c.source_id),)),))
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=3,attack=3,health=3,
        keywords=(Keyword.LIFESTEAL,),battlecry='native',targeting=DOMAIN,target_rule='deck-low-minion-v1',
        metadata=metadata(CardClass.WARLOCK,rarity=Rarity.RARE,tribes=('quilboar',))))
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,cost=1,attack=1,health=20,metadata=metadata()))
    r.register_card(CardDefinition('weak','Weak',CardType.MINION,attack=1,health=2,metadata=metadata()))
    r.register_card(CardDefinition('no_meta','Known without class metadata',CardType.MINION,health=1))
    for name,key in(('shield',Keyword.DIVINE_SHIELD),('immune',Keyword.IMMUNE),
                     ('stealth',Keyword.STEALTH),('elusive',Keyword.ELUSIVE)):
        r.register_card(CardDefinition(name,name,CardType.MINION,health=20,keywords=(key,),metadata=metadata()))
    r.register_card(CardDefinition('magic','Magic',CardType.MINION,health=20,spell_damage=3,metadata=metadata()))

    def fail(c):raise RuntimeError('deliberate late paid conditional target failure')
    r.register_behavior('late-fault',fail)

    def reaction(c,work):
        if c.event.player_id!=c.player_id:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('go','Continue',tuple(work(c))),
            ChoiceOption('fault','Fail after change',tuple(work(c))+(InvokeBehavior('late-fault',c.source_id,c.player_id),)),
        ),c.source_id),)
    bodies={
        'wait':lambda c:reaction(c,lambda c:()),
        'wait.add':lambda c:reaction(c,lambda c:(AddToDeck(c.player_id,'plain','random',c.source_id),)),
        'wait.draw':lambda c:reaction(c,lambda c:(Draw(c.player_id,source_id=c.source_id),)),
        'wait.kill':lambda c:reaction(c,lambda c:(Destroy(c.state.players[2].board[0],c.source_id),)),
    }
    for name,body in bodies.items():
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.MINION,health=20,
            triggers=(TriggerSpec('mana_spent',name),),metadata=metadata()))
    scripts={
        'hurt':lambda c:(Damage(c.state.players[c.player_id].hero_id,12,c.source_id),),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
        'add':lambda c:(AddToDeck(c.player_id,'plain','random',c.source_id),),
        'enemy.draw':lambda c:(Draw(3-c.player_id,source_id=c.source_id),),
    }
    targeted={
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'copy':lambda c:(CopyMinion(c.target_id,2),),
    }
    for name,body in{**scripts,**targeted}.items():
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,
            requires_target=name in targeted,metadata=metadata()))
    return r


class DeckCountConditionalTargetTests(unittest.TestCase):
    def game(self,hand=(NATIVE,),count=10,enemy_count=20,board=(),enemy_board=('plain',),deck=None,enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*count if deck is None else deck,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy_board,deck=('plain',)*enemy_count,mana=10,max_mana=10),
        ),seed=85),registry())
    def source(self,g,player=1):
        return next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==NATIVE)
    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def play(self,g,target=None,player=1):return g.apply(PlayCard(player,self.source(g,player),target))
    def cast(self,g,name,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,eid,target))
    def actions(self,g):
        return tuple(a for a in g.legal_actions()if isinstance(a,PlayCard)and a.entity_id==self.source(g))
    def choices(self,g):return{a.target_id for a in self.actions(g)}
    def choose(self,g,name):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(s,registry())
        self.assertEqual(h.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return h
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_complete_raw_native_and_existing_declarations(self):
        raw=evidence();r=registry();card=r.card(NATIVE)
        original=next(x for x in json.loads((PATH.parents[1]/'extracted/cards.json').read_bytes())if x['id']==NATIVE)
        self.assertEqual(raw,original)
        self.assertEqual((card.cost,card.attack,card.health,card.keywords),(3,3,3,(Keyword.LIFESTEAL,)))
        self.assertEqual((card.metadata.classes,card.metadata.tribes,card.metadata.rarity),
                         ((CardClass.WARLOCK,),('quilboar',),Rarity.RARE))
        self.assertEqual(card.targeting,DOMAIN);self.assertIsNone(card.target_condition)
        self.assertEqual(r.target_visibility(card.target_rule),'player')
        self.assertEqual(r.player_target_rule(card.target_rule),PlayerTargetRuleSpec('deck-low-minion-v1','v1'))

    def test_false_condition_has_only_none_and_commits_without_damage(self):
        g=self.game(count=11);before=g.state.entities[g.state.players[2].board[0]].damage
        self.assertEqual(self.choices(g),{None});self.assertEqual(g.legal_targets(self.source(g)),())
        source=self.source(g);self.play(g)
        self.assertEqual((g.state.players[1].mana,g.state.entities[source].zone),(7,Zone.BOARD))
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].damage,before)
        self.assertEqual(g.state.play_history[-1].target_id,None);self.portable(g)

    def test_false_condition_cannot_force_an_otherwise_eligible_target(self):
        g=self.game(count=11);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,g.state.players[2].board[0])
        self.assertEqual(g.snapshot(),before)

    def test_inclusive_9_10_require_target_and_11_does_not(self):
        for count in(9,10,11):
            with self.subTest(count=count):
                g=self.game(count=count);target=g.state.players[2].board[0]
                self.assertEqual(self.choices(g),{None}if count==11 else{target})
                self.play(g,None if count==11 else target)
                self.assertEqual(g.state.entities[target].damage,0 if count==11 else 6);self.portable(g)

    def test_true_nonempty_cannot_skip_or_target_a_hero(self):
        g=self.game();before=g.snapshot()
        for target in(None,self.hero(g).id,self.hero(g,2).id,999999):
            with self.subTest(target=target),self.assertRaises(IllegalAction):self.play(g,target)
            self.assertEqual(g.snapshot(),before)

    def test_true_empty_pool_still_commits_targetless_without_self_target(self):
        g=self.game(enemy_board=());self.assertEqual(self.choices(g),{None})
        source=self.source(g);self.play(g)
        self.assertEqual(g.state.players[1].board,[source]);self.assertEqual(g.state.entities[source].damage,0)
        self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_filtered_enemy_immune_stealth_pool_is_empty_but_friendly_immune_is_eligible(self):
        for card in('immune','stealth'):
            with self.subTest(card=card):
                g=self.game(enemy_board=(card,));self.assertEqual(self.choices(g),{None});self.play(g);self.portable(g)
        g=self.game(board=('immune',),enemy_board=('stealth',))
        target=g.state.players[1].board[0];self.assertEqual(self.choices(g),{target});self.play(g,target)
        self.assertEqual(g.state.entities[target].damage,0);self.portable(g)

    def test_minion_battlecry_can_select_elusive_and_friendly_minions(self):
        g=self.game(board=('plain',),enemy_board=('elusive',))
        own=g.state.players[1].board[0];enemy=g.state.players[2].board[0]
        self.assertEqual(self.choices(g),{own,enemy});self.play(g,own)
        self.assertEqual(g.state.entities[own].damage,6);self.portable(g)

    def test_every_physical_slot_counts_without_unrelated_metadata(self):
        g=self.game(deck=('no_meta',)+('plain',)*9);self.assertEqual(self.choices(g),set(g.state.players[2].board))
        self.play(g,g.state.players[2].board[0]);self.portable(g)

    def test_draw_and_shuffle_update_new_target_requirement(self):
        g=self.game((NATIVE,'draw','add'),count=11);target=g.state.players[2].board[0]
        self.assertEqual(self.choices(g),{None});self.cast(g,'draw');self.assertEqual(self.choices(g),{target})
        self.cast(g,'add');self.assertEqual(self.choices(g),{None});self.play(g);self.portable(g)

    def test_enemy_deck_count_does_not_activate_own_target_requirement(self):
        g=self.game((NATIVE,'enemy.draw'),count=11,enemy_count=1)
        self.cast(g,'enemy.draw');self.assertEqual(self.choices(g),{None});self.play(g);self.portable(g)

    def test_original_source_lifesteal_uses_battlecry_effect_damage(self):
        g=self.game(('hurt',NATIVE),board=('magic',));self.cast(g,'hurt');target=g.state.players[2].board[0]
        self.play(g,target);self.assertEqual((g.state.entities[target].damage,self.hero(g).damage),(6,6))
        self.assertEqual(sum(e.kind=='battlecry_started'for e in g.events),1);self.portable(g)

    def test_divine_shield_prevention_does_not_heal_and_overkill_uses_original_damage_policy(self):
        g=self.game(('hurt',NATIVE),enemy_board=('shield',));self.cast(g,'hurt');target=g.state.players[2].board[0]
        self.play(g,target);self.assertEqual((g.state.entities[target].damage,self.hero(g).damage),(0,12));self.portable(g)
        g=self.game(('hurt',NATIVE),enemy_board=('weak',));self.cast(g,'hurt');target=g.state.players[2].board[0]
        self.play(g,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(self.hero(g).damage,6);self.portable(g)

    def test_player_command_matches_host_targets_and_submits_once(self):
        g=self.game();source=self.source(g);target=g.state.players[2].board[0]
        api=g.for_player(1);actions=api.legal_actions()
        view=actions['observation']
        source_ref=next(c['ref']for c in view['players'][0]['hand']if c['card_id']==NATIVE)
        target_ref=view['players'][1]['board'][0]['ref']
        commands=[a for a in actions['actions'] if a['type']=='play_card'and a['card']==source_ref]
        self.assertTrue(commands)
        command=next(a for a in commands if a.get('target')==target_ref)
        result=api.submit({'revision':actions['revision'],'action':command})
        self.assertTrue(result['accepted']);self.assertIsNone(result['error'])
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(g.state.entities[target].damage,6);self.portable(g)

    def test_public_rules_are_pure_and_do_not_leak_hidden_deck_or_hand(self):
        g=self.game(enemy_hand=('plain',))
        before=g.snapshot()
        for _ in range(3):
            self.actions(g);public=json.dumps(g.observe(1))+json.dumps(g.for_player(1).legal_actions())
            for key in('state','entities','rng_state','resolution_frame','abilities','body_target_profile_id'):
                self.assertNotIn('"'+key+'"',public)
            self.assertNotIn('"deck":',public)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_same_visible_count_different_hidden_inventory_does_not_change_actions(self):
        first=self.game(deck=('plain',)*10,enemy_hand=('plain',))
        other=self.game(deck=('no_meta',)*10,enemy_hand=('weak',))
        self.assertEqual(self.choices(first),self.choices(other))
        self.assertEqual(first.for_player(1).legal_actions(),other.for_player(1).legal_actions())

    def test_paid_waiting_original_target_restores_clone_replay_and_finishes_once(self):
        g=self.game(board=('wait',));source=self.source(g);target=g.state.players[2].board[0]
        self.play(g,target);self.assertIsNotNone(g.state.pending_choice)
        h=self.portable(g);clone=g.clone()
        for branch in(g,h,clone):
            self.choose(branch,'go');self.assertIsNone(branch.state.pending_choice)
            self.assertEqual(branch.state.entities[target].damage,6);self.assertEqual(branch.state.players[1].mana,7)
            self.assertEqual(sum(r.source_id==source for r in branch.state.play_history),1)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(g.snapshot(),clone.snapshot());self.portable(g)

    def test_true_submitted_target_and_later_false_dispatch_are_distinct(self):
        g=self.game(board=('wait.add',));target=g.state.players[2].board[0];source=self.source(g)
        self.play(g,target);h=self.portable(g)
        for branch in(g,h):
            self.choose(branch,'go');self.assertEqual(len(branch.state.players[1].deck),11)
            self.assertEqual(branch.state.entities[target].damage,0);self.assertEqual(branch.state.players[1].mana,7)
            row=next(r for r in branch.state.play_history if r.source_id==source);self.assertEqual(row.target_id,target)
        self.assertEqual(g.snapshot(),h.snapshot());self.portable(g)

    def test_false_submitted_targetless_does_not_invent_target_after_later_draw(self):
        g=self.game(board=('wait.draw',),count=11);target=g.state.players[2].board[0];self.play(g)
        h=self.portable(g)
        for branch in(g,h):
            self.choose(branch,'go');self.assertEqual(len(branch.state.players[1].deck),10)
            self.assertEqual(branch.state.entities[target].damage,0)
            self.assertIsNone(branch.state.play_history[-1].target_id)
        self.assertEqual(g.snapshot(),h.snapshot());self.portable(g)

    def test_selected_target_leaving_during_paid_wait_does_not_retarget(self):
        g=self.game(board=('wait.kill',));target=g.state.players[2].board[0];source=self.source(g)
        self.play(g,target);h=self.portable(g)
        for branch in(g,h):
            self.choose(branch,'go');self.assertEqual(branch.state.entities[target].zone,Zone.GRAVEYARD)
            self.assertEqual(branch.state.entities[source].damage,0);self.assertEqual(branch.state.players[1].mana,7)
        self.assertEqual(g.snapshot(),h.snapshot());self.portable(g)

    def test_waiting_choice_failure_rolls_back_to_the_paid_boundary(self):
        g=self.game(board=('wait.add',));self.play(g,g.state.players[2].board[0]);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_silence_bounce_and_manual_replay_install_original_native_declaration(self):
        g=self.game((NATIVE,'silence','bounce'),count=11);self.play(g);source=g.state.players[1].board[-1]
        self.cast(g,'silence',source);self.assertNotIn(Keyword.LIFESTEAL,g.state.entities[source].keywords)
        self.cast(g,'bounce',source);self.assertIn(Keyword.LIFESTEAL,g.state.entities[source].keywords)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.play(g)
        self.assertEqual(len([a for a in g.state.entities[source].abilities if a.kind=='battlecry']),1);self.portable(g)

    def test_current_copy_to_other_controller_and_later_play_use_its_deck(self):
        g=self.game((NATIVE,'copy','bounce'),count=11,enemy_count=0)
        self.play(g);source=g.state.players[1].board[-1];self.cast(g,'copy',source)
        copy=g.state.players[2].board[-1]
        self.assertEqual(g.state.entities[copy].controller,2)
        self.assertIn(Keyword.LIFESTEAL,g.state.entities[copy].keywords)
        self.assertEqual(sum(e.kind=='battlecry_started'for e in g.events),1)
        self.cast(g,'bounce',copy);g.apply(EndTurn(1))
        self.assertEqual(len(g.state.players[2].deck),0)
        target=g.state.players[2].board[0]
        self.assertIn(target,{a.target_id for a in g.legal_actions()if isinstance(a,PlayCard)and a.entity_id==copy})
        self.play(g,target,player=2)
        self.assertEqual((g.state.entities[target].damage,self.hero(g,2).damage),(6,0))
        self.assertEqual(g.state.play_history[-1].player_id,2);self.portable(g)

    def test_rehashed_paid_wait_cannot_change_original_target_identity(self):
        g=self.game(board=('wait',));self.play(g,g.state.players[2].board[0]);snap=g.snapshot()
        bad=deepcopy(snap);bad['state']['play_history'][-1]['target_id']=self.hero(g,2).id
        self.reject(bad)
        self.portable(g)

    def test_existing_protocol_remains_and_old_schema_rejected(self):
        g=self.game();snap=g.snapshot()
        self.assertEqual((snap['schema_version'],snap['ruleset']['id'],snap['mechanics_version']['version']),
                         (266,'prototype-v302',CORE_EFFECTS_VERSION))
        for value in(1,217,True,218.0,'218'):
            bad=deepcopy(snap);bad['schema_version']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        self.portable(g)


if __name__=='__main__':unittest.main()

