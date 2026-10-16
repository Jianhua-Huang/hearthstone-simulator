"""Random forced combat retains its original pipeline and can select enemy heroes."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, Game, Keyword,
    LimitedTriggerSpec, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, Freeze,
    InvokeBehavior, RandomForceAttack, ReplaceHero, RequestChoice)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

RAIDER='BAR_020'
PATH=Path(__file__).resolve().parents[1]/'data/support/random-forced-hero-basics.json'
PIN='2f922f89b950b809b761970979767f719d664f8916e1e280ea51b6723ed2340e'


def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Raider evidence changed')
    row=support['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw card evidence changed')
    return row['data']


def registry():
    r=Registry('isolated-random-forced-hero-basics-v1');raw=evidence()
    for cid in ('hero-character','replacement-hero'):
        r.register_card(CardDefinition(cid,cid,CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition('immune-hero','Immune hero',CardType.HERO,health=80,
        keywords=(Keyword.IMMUNE,),metadata=metadata()))
    for cid,fields in (('plain',{}),('sleeping',{'dormant_turns':2})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=8,
            metadata=metadata(),**fields))
    r.register_card(CardDefinition('weapon','Weapon',CardType.WEAPON,attack=1,
        durability=2,metadata=metadata()))
    def enemies(c):
        p=c.state.players[3-c.player_id]
        return (p.hero_id,*p.board)
    def raider_body(c):return (RandomForceAttack((c.source_id,),enemies(c),c.source_id),)
    r.register_behavior('raider-body',raider_body)
    r.register_card(CardDefinition(RAIDER,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],keywords=(Keyword.FRENZY,),
        limited_triggers=(LimitedTriggerSpec.frenzy('raider-body'),),
        metadata=metadata(tribes=('quilboar',))))
    def actor(c):return c.state.players[c.player_id].board[0]
    def force(c,defenders=None,attackers=None,relation='opponent',source=None):
        return RandomForceAttack((actor(c),) if attackers is None else attackers,
            enemies(c) if defenders is None else defenders,
            c.source_id if source is None else source,relation)
    def fail(c):raise ValueError('Fixture late failure')
    r.register_behavior('late-fault',fail)
    def wait(c):
        if not dict(c.event.data).get('forced'):return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('resolve','Resolve',()),
            ChoiceOption('replace','Replace hero',(ReplaceHero(2,'replacement-hero'),)),
            ChoiceOption('fault','Replace and fail',(ReplaceHero(2,'replacement-hero'),
                InvokeBehavior('late-fault',source_id=c.source_id,player_id=c.player_id))),
        ),c.source_id),)
    r.register_behavior('wait-attack',wait)
    r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=8,
        triggers=(TriggerSpec('attack_declared','wait-attack'),),metadata=metadata()))
    scripts=(
        ('random',lambda c:(force(c),),False),
        ('hero',lambda c:(force(c,(c.state.players[3-c.player_id].hero_id,)),),False),
        ('minions',lambda c:(force(c,tuple(c.state.players[3-c.player_id].board)),),False),
        ('mixed',lambda c:(force(c,tuple(reversed(enemies(c))),
            (c.state.players[c.player_id].hero_id,*reversed(c.state.players[c.player_id].board))),),False),
        ('hero-attacker',lambda c:(force(c,attackers=(c.state.players[c.player_id].hero_id,)),),False),
        ('own-hero',lambda c:(force(c,(c.state.players[c.player_id].hero_id,)),),False),
        ('friendly-hero',lambda c:(force(c,(c.state.players[c.player_id].hero_id,),
            relation='friendly_minions'),),False),
        ('empty',lambda c:(force(c,()),),False),
        ('stale',lambda c:(force(c,(999999,)),),False),
        ('noncharacters',lambda c:(force(c,(c.source_id,c.state.players[2].weapon_id)),),False),
        ('bad-source',lambda c:(force(c,source=999999),),False),
        ('destroy-actor',lambda c:(Destroy(actor(c),c.source_id),force(c)),False),
        ('replace-first',lambda c:(ReplaceHero(2,'replacement-hero'),
            force(c,(c.state.players[2].hero_id,))),False),
        ('freeze-force',lambda c:(Freeze(actor(c)),force(c)),False),
        ('lethal',lambda c:(Damage(c.state.players[2].hero_id,79,c.source_id),force(c)),False),
        ('fault',lambda c:(force(c),InvokeBehavior('late-fault',source_id=c.source_id,
            player_id=c.player_id)),False),
        ('ping',lambda c:(Damage(c.target_id,1,c.source_id),),True),
        ('kill',lambda c:(Damage(c.target_id,6,c.source_id),),True),
    )
    for cid,body,targeted in scripts:
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            requires_target=targeted,metadata=metadata()))
    return r


class RandomForcedHeroBasicsTests(unittest.TestCase):
    def game(self,hand=('hero',),board=('plain',),enemy=(),seed=41,
            enemy_hero='hero-character',armor=0,enemy_weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero-character',hand=hand,board=board,deck=('plain',)*4,mana=10,max_mana=10),
            PlayerSetup(enemy_hero,board=enemy,deck=('plain',)*4,mana=10,max_mana=10,
                armor=armor,weapon_card_id=enemy_weapon),
        ),seed=seed),registry())
    def hero(self,g,p=2):return g.state.players[p].hero_id
    def play(self,g,cid='hero',target=None):
        p=g.state.active_player
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        result=g.apply(PlayCard(p,eid,target if g.registry.card(cid).requires_target else None))
        return result
    def choices(self,g):return [e for e in g.events if e.kind=='random_choice']
    def choose(self,g,key='resolve'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,registry()).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
    def no_random(self,g,cid):
        before=g._rng.getstate();result=self.play(g,cid)
        self.assertEqual(g._rng.getstate(),before)
        self.assertFalse(any(e.kind in ('random_choice','attack_declared') for e in result.events))
        self.check(g)
    def waiting(self):
        g=self.game(board=('plain','watcher'));self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        return g

    def test_raw_pin_is_current_local_five_six_not_historical_five_five(self):
        raw=evidence()
        self.assertEqual((raw['id'],raw['dbf_id'],raw['cost'],raw['attack'],raw['health']),
            (RAIDER,62701,5,5,6))
        self.assertEqual(raw['text_en'],'<b>Frenzy:</b> Attack a\nrandom enemy.')
        self.assertEqual([raw['tags'][k] for k in ('CLASS','RARITY','CARDRACE','FRENZY')],[12,1,43,1])
        card=registry().card(RAIDER)
        self.assertEqual((card.cost,card.attack,card.health,card.metadata.tribes),(5,5,6,('quilboar',)))
        self.assertEqual(card.limited_triggers,(LimitedTriggerSpec.frenzy('raider-body'),))

    def test_hero_only_pool_samples_once_and_delivers_original_combat(self):
        g=self.game();a=g.state.players[1].board[0];d=self.hero(g)
        probe=random.Random();probe.setstate(g._rng.getstate());self.assertEqual(probe.choice([(a,d)]),(a,d))
        result=self.play(g)
        self.assertEqual(g._rng.getstate(),probe.getstate())
        self.assertEqual(g.state.entities[d].damage,2)
        self.assertEqual(g.state.entities[a].damage,0)
        self.assertEqual(g.state.entities[a].attacks_this_turn,0)
        chosen=self.choices(g);self.assertEqual(len(chosen),1)
        self.assertEqual((chosen[0].target_id,dict(chosen[0].data)['defender_id']),(a,d))
        attack=next(e for e in result.events if e.kind=='attack_declared')
        self.assertEqual((attack.source_id,attack.target_id,dict(attack.data)['forced']),(a,d,True))
        self.assertEqual(sum(e.kind=='attack_finished' for e in result.events),1)
        self.check(g)

    def test_complete_mixed_pairs_are_sorted_once_and_match_rng_state(self):
        g=self.game(hand=('mixed',),board=('plain','plain'),enemy=('plain','plain'))
        pairs=sorted((a,d) for a in g.state.players[1].board
            for d in (self.hero(g),*g.state.players[2].board))
        self.assertEqual(len(pairs),6)
        probe=random.Random();probe.setstate(g._rng.getstate());expected=probe.choice(pairs)
        self.play(g,'mixed');chosen=self.choices(g)[0]
        self.assertEqual((chosen.target_id,dict(chosen.data)['defender_id']),expected)
        self.assertEqual(g._rng.getstate(),probe.getstate())
        self.assertEqual(g.state.entities[expected[1]].damage,2)
        self.assertEqual(len(self.choices(g)),1);self.check(g)

    def test_original_minion_only_request_keeps_its_pool_and_sampling(self):
        g=self.game(hand=('minions',),enemy=('plain','plain'))
        a=g.state.players[1].board[0];pairs=sorted((a,d) for d in g.state.players[2].board)
        probe=random.Random();probe.setstate(g._rng.getstate());expected=probe.choice(pairs)
        self.play(g,'minions');chosen=self.choices(g)[0]
        self.assertEqual((chosen.target_id,dict(chosen.data)['defender_id']),expected)
        self.assertEqual(g._rng.getstate(),probe.getstate())
        self.assertEqual(g.state.entities[self.hero(g)].damage,0);self.check(g)

    def test_hero_attackers_remain_excluded_without_rng_consumption(self):
        self.no_random(self.game(hand=('hero-attacker',)),'hero-attacker')

    def test_opponent_relation_excludes_own_hero_without_rng_consumption(self):
        self.no_random(self.game(hand=('own-hero',)),'own-hero')

    def test_friendly_minions_relation_still_excludes_hero(self):
        self.no_random(self.game(hand=('friendly-hero',)),'friendly-hero')

    def test_empty_pool_has_no_event_or_rng_consumption(self):
        self.no_random(self.game(hand=('empty',)),'empty')

    def test_unknown_defender_is_filtered_without_rng_consumption(self):
        self.no_random(self.game(hand=('stale',)),'stale')

    def test_spell_and_weapon_are_not_character_defenders(self):
        self.no_random(self.game(hand=('noncharacters',),enemy_weapon='weapon'),'noncharacters')

    def test_dormant_defender_keeps_original_empty_pool_policy(self):
        self.no_random(self.game(hand=('minions',),enemy=('sleeping',)),'minions')

    def test_dormant_attacker_keeps_original_empty_pool_policy(self):
        self.no_random(self.game(board=('sleeping',)),'hero')

    def test_unknown_source_rolls_back_without_consuming_rng_or_payment(self):
        g=self.game(hand=('bad-source',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad-source')
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_actor_removed_before_selection_is_not_resurrected_or_sampled(self):
        g=self.game(hand=('destroy-actor',));self.no_random(g,'destroy-actor')
        self.assertFalse(g.state.players[1].board)

    def test_old_hero_removed_before_selection_is_not_replaced_in_pool(self):
        g=self.game(hand=('replace-first',));old=self.hero(g)
        self.no_random(g,'replace-first')
        self.assertNotEqual(self.hero(g),old)
        self.assertEqual(g.state.entities[self.hero(g)].damage,0)

    def test_same_turn_played_raider_forces_attack_after_surviving_damage(self):
        g=self.game(hand=(RAIDER,'ping'),board=());self.play(g,RAIDER)
        a=g.state.players[1].board[0];self.assertEqual(g.state.players[1].mana,5)
        self.play(g,'ping',a)
        self.assertEqual(g.state.entities[a].damage,1)
        self.assertEqual(g.state.entities[self.hero(g)].damage,5)
        self.assertEqual(g.state.entities[a].attacks_this_turn,0)
        self.assertNotIn(Keyword.FRENZY,g.state.entities[a].keywords)
        self.assertEqual(len(self.choices(g)),1);self.check(g)

    def test_raider_frenzy_remains_once_per_original_lifecycle(self):
        g=self.game(hand=('ping','ping'),board=(RAIDER,));a=g.state.players[1].board[0]
        self.play(g,'ping',a);rng=g._rng.getstate();self.play(g,'ping',a)
        self.assertEqual(g.state.entities[a].damage,2)
        self.assertEqual(g.state.entities[self.hero(g)].damage,5)
        self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(len(self.choices(g)),1);self.check(g)

    def test_lethally_damaged_raider_does_not_attack(self):
        g=self.game(hand=('kill',),board=(RAIDER,));a=g.state.players[1].board[0]
        before=g._rng.getstate();self.play(g,'kill',a)
        self.assertFalse(g.state.players[1].board)
        self.assertFalse(self.choices(g));self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(g.state.entities[self.hero(g)].damage,0);self.check(g)

    def test_enemy_raider_uses_its_controller_and_attacks_on_opponent_turn(self):
        g=self.game(hand=('ping',),board=(),enemy=(RAIDER,))
        a=g.state.players[2].board[0];self.play(g,'ping',a)
        self.assertEqual(g.state.entities[self.hero(g,1)].damage,5)
        self.assertEqual(g.state.entities[self.hero(g,2)].damage,0)
        chosen=self.choices(g)[0];self.assertEqual(dict(chosen.data)['defender_id'],self.hero(g,1))
        attack=next(e for e in g.events if e.kind=='attack_declared')
        self.assertEqual(attack.player_id,2);self.check(g)

    def test_existing_forced_policy_ignores_freeze_and_preserves_counter(self):
        g=self.game(hand=('freeze-force',));a=g.state.players[1].board[0]
        self.play(g,'freeze-force')
        self.assertTrue(g.state.entities[a].frozen)
        self.assertEqual(g.state.entities[a].attacks_this_turn,0)
        self.assertEqual(g.state.entities[self.hero(g)].damage,2);self.check(g)

    def test_forced_hero_combat_does_not_spend_used_normal_attack(self):
        g=self.game();a=g.state.players[1].board[0];d=self.hero(g)
        g.apply(Attack(1,a,d));self.play(g)
        self.assertEqual(g.state.entities[a].attacks_this_turn,1)
        self.assertEqual(g.state.entities[d].damage,4);self.check(g)

    def test_hero_armor_uses_original_damage_layer(self):
        g=self.game(armor=1);self.play(g)
        self.assertEqual((g.state.entities[self.hero(g)].armor,g.state.entities[self.hero(g)].damage),(0,1))
        self.check(g)

    def test_hero_lethal_uses_original_game_termination(self):
        g=self.game(hand=('lethal',));self.play(g,'lethal')
        self.assertEqual((g.state.status,g.state.winner),('finished',1));self.check(g)

    def test_immune_character_keeps_original_forced_combat_prevention(self):
        g=self.game(enemy_hero='immune-hero');self.play(g)
        self.assertEqual(g.state.entities[self.hero(g)].damage,0)
        self.assertEqual(len(self.choices(g)),1);self.check(g)

    def test_hero_window_waits_restores_clones_and_replays_with_independent_registry(self):
        g=self.waiting();window=g.state.action_windows[0]
        self.assertEqual((window.kind,window.target_id,window.forced),('attack',self.hero(g),True))
        self.assertEqual(g.state.entities[self.hero(g)].damage,0)
        self.check(g)
        copies=(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),registry()),
            g.clone(),replay(build_replay(g),registry()))
        self.choose(g)
        for other in copies:
            self.choose(other);self.assertEqual(other.snapshot(),g.snapshot())
        self.assertEqual(g.state.entities[self.hero(g)].damage,2)
        self.assertEqual(len(self.choices(g)),1);self.assertFalse(g.state.action_windows);self.check(g)

    def test_hero_removed_during_wait_cancels_old_delivery_without_redrawing(self):
        g=self.waiting();old=self.hero(g);rng=g._rng.getstate();self.choose(g,'replace')
        self.assertNotEqual(self.hero(g),old)
        self.assertEqual(g.state.entities[self.hero(g)].damage,0)
        self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(len(self.choices(g)),1);self.assertFalse(g.state.action_windows);self.check(g)

    def test_failed_choice_rolls_back_to_original_hero_window_and_rng(self):
        g=self.waiting();before=g.snapshot();rng=g._rng.getstate()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g._rng.getstate(),rng)
        self.check(g);self.choose(g);self.assertEqual(g.state.entities[self.hero(g)].damage,2)

    def test_immediate_failure_rolls_back_random_combat_events_rng_and_payment(self):
        g=self.game(hand=('fault',));before=g.snapshot();rng=g._rng.getstate()
        with self.assertRaises(ResolutionError):self.play(g,'fault')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g._rng.getstate(),rng);self.check(g)

    def test_player_queries_remain_pure_and_show_hero_health_without_internal_state(self):
        g=self.waiting();before=g.snapshot()
        for p in (1,2):
            view=g.for_player(p)
            view.observe();view.legal_actions();view.events()
            text=json.dumps(view.observe()).lower()
            for hidden in ('rng_state','action_windows','randomforceattack','continuations','enchantments'):
                self.assertNotIn(hidden,text)
        self.assertEqual(g.snapshot(),before)
        self.choose(g);self.assertEqual(g.observe(1)['players'][1]['hero']['health'],78)

    def test_rule_and_mechanics_versions_change_without_wire_schema_change(self):
        g=self.game();snap=g.snapshot()
        self.assertEqual((snap['ruleset']['id'],snap['mechanics_version']['version'],
            snap['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,SNAPSHOT_SCHEMA_VERSION))
        for field,key,old in (('ruleset','id','prototype-v200'),
                ('mechanics_version','version','core-effects-v194')):
            bad=json.loads(json.dumps(snap));bad[field][key]=old
            with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())


if __name__=='__main__':unittest.main()
