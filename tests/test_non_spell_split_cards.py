"""Actual non-spell split consumers retain original unit and death identities."""
from copy import deepcopy
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.non_spell_split_cards import ELEPHANT, VOLCANO, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseLocation, Zone)
from hs_sim.engine.effects import AddToHand, ChangeControl, ChoiceOption, Damage, Destroy, GrantKeyword, InvokeBehavior, RequestChoice, Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE, RandomSplitDamage, SplitDamageScope, killed_minions
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell

PREFIX = 'k95.'
YETI = 'CORE_CS2_182'
FIRE = 'CORE_CS2_029'


def registry():
    r = build_registry()
    r.register_card(CardDefinition(PREFIX+'fragile', 'Fragile target', CardType.MINION, health=1))
    r.register_card(CardDefinition(PREFIX+'tank', 'Healthy target', CardType.MINION, health=20))
    r.register_card(CardDefinition(PREFIX+'provider', 'Ordinary spell bonus', CardType.MINION, health=8, spell_damage=3))
    r.register_behavior(PREFIX+'fail', lambda c: (AddToHand(c.player_id, 'unknown.k95'),))
    def wait(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or source.card_id != ELEPHANT:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(PREFIX+'fail', c.source_id, c.player_id),)),
            ChoiceOption('take', 'Transfer original source', (ChangeControl(source.id, 2),)),
            ChoiceOption('kill', 'Remove original source', (Destroy(source.id, c.source_id),)),
            ChoiceOption('lifesteal', 'Grant to original source', (GrantKeyword(source.id, Keyword.LIFESTEAL, c.source_id),)),
        ), source_id=c.source_id),)
    def unrelated(c):
        source = c.state.entities.get(c.event.source_id)
        targets = [i for i in c.state.players[2].board if c.state.entities[i].card_id == PREFIX+'tank']
        return (Destroy(targets[0], c.source_id),) if source is not None and source.card_id == ELEPHANT and targets else ()
    for name, body in (('wait', wait), ('unrelated', unrelated)):
        r.register_behavior(PREFIX+name, body)
        r.register_card(CardDefinition(PREFIX+name, name, CardType.MINION, health=8,
                                       triggers=(TriggerSpec('damage_dealt', PREFIX+name),)))
    scripts = {
        'summon': lambda c: (Summon(c.player_id, ELEPHANT),),
        'hurt': lambda c: (Damage(c.state.players[c.player_id].hero_id, 5, c.source_id),),
        'auto_fire': lambda c: (CastSpell(c.player_id, FIRE, c.source_id, target_id=c.state.players[2].hero_id, targeting='explicit'),),
        'bad_source': lambda c: (RandomSplitDamage(c.player_id, None, c.source_id, 2,
            profile=NON_SPELL_PROFILE, kind=DamageKind.MINION_ABILITY),),
    }
    for name, body in scripts.items():
        r.register_behavior(PREFIX+name, body)
        r.register_card(CardDefinition(PREFIX+name, name, CardType.SPELL, on_play=PREFIX+name))
    for name, amount in (('zero', 0), ('empty', 2)):
        r.register_behavior(PREFIX+name, lambda c, n=amount: (RandomSplitDamage(c.player_id, None, c.source_id, n,
            scope=SplitDamageScope(kinds=(CardType.MINION,)), profile=NON_SPELL_PROFILE, kind=DamageKind.MINION_ABILITY),))
        r.register_card(CardDefinition(PREFIX+name, name, CardType.MINION, health=2, battlecry=PREFIX+name))
    return r


class NonSpellSplitCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(ELEPHANT,), board=(), enemy=(), enemy_hand=(), active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(YETI,)*12, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*12, mana=40, max_mana=40, mana_cap=40),
        ), active_player=active, seed=95), self.r)

    def play(self, g, cid=ELEPHANT, target=None):
        p = g.state.active_player
        i = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        kind = self.r.card(cid).kind
        g.apply(PlayCard(p, i, target, position=len(g.state.players[p].board) if kind in (CardType.MINION, CardType.LOCATION) else None))
        return i

    def turn(self, g):
        g.apply(EndTurn(g.state.active_player))

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def finish(self, g):
        while g.state.pending_choice is not None:
            self.choose(g)

    def values(self, g):
        return [v for e in g.events if (v := health_result(e)) is not None and v.split_packet is not None]

    def closed(self, g, index=0):
        return [e for e in g.events if e.kind == 'split_damage_closed'][index]

    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(s, registry())
        self.assertEqual(other.snapshot(), s); self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), s)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for hidden in ('split_damage_history', 'split_packet', 'rng_before', 'source_allocation', 'resolution_frame', 'contributions'):
                self.assertNotIn('"'+hidden+'"', public)
        return other

    def reject(self, s):
        s['state_hash'] = canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(s, self.r)
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_complete_actual_minion_and_location_faces(self):
        data = load_batch(); self.assertEqual(len(data['official_observations']), 4)
        self.assertFalse(data['dependencies'])
        a, b = self.r.card(ELEPHANT), self.r.card(VOLCANO)
        self.assertEqual((a.kind,a.cost,a.attack,a.health),(CardType.MINION,4,3,3))
        self.assertEqual((b.kind,b.cost,b.health,b.durability),(CardType.LOCATION,3,0,3))
        self.assertIsNone(b.on_play); self.assertIsNotNone(b.on_use)

    def test_elephant_three_original_nonspell_units_one_payment_no_cast(self):
        g = self.game(); self.play(g); root, = g.state.split_damage_history
        self.assertEqual(g.state.players[1].mana, 36)
        self.assertFalse(g.state.cast_history)
        self.assertIsNone(root.quote.cast); self.assertEqual((root.quote.spell_bonus,root.quote.budget),(0,3))
        self.assertEqual([(v.damage_kind,v.base_amount,v.spell_bonus) for v in self.values(g)], [('minion_ability',1,0)]*3)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27); self.portable(g)

    def test_actual_first_group_death_accepts_exactly_one_additional_three(self):
        g = self.game(enemy=(PREFIX+'fragile',)); self.play(g)
        self.assertEqual(len(g.state.split_damage_history), 2)
        self.assertEqual(len(self.values(g)), 6)
        deaths = killed_minions(g.state, self.closed(g)); self.assertEqual(len(deaths), 1)
        self.assertEqual(deaths[0].cause.health_result.split_packet.root_id, 1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 25); self.portable(g)

    def test_deaths_in_extra_group_do_not_start_an_unprinted_third_group(self):
        g = self.game(enemy=(PREFIX+'fragile',)*5); self.play(g)
        self.assertEqual(len(g.state.split_damage_history), 2)
        self.assertEqual(len(self.values(g)), 6)
        self.assertTrue(killed_minions(g.state, self.closed(g)))
        self.assertTrue(killed_minions(g.state, self.closed(g, 1)))

    def test_unrelated_destroy_during_first_group_does_not_earn_death_credit(self):
        g = self.game(board=(PREFIX+'unrelated',), enemy=(PREFIX+'tank',)); self.play(g)
        self.assertEqual(len(g.state.death_history), 1)
        self.assertFalse(killed_minions(g.state, self.closed(g)))
        self.assertEqual(len(g.state.split_damage_history), 1); self.portable(g)

    def test_ordinary_spell_bonus_does_not_expand_minion_budget(self):
        g = self.game(board=(PREFIX+'provider',)); self.play(g)
        self.assertEqual(len(self.values(g)), 3)
        self.assertEqual(g.state.split_damage_history[0].quote.spell_bonus, 0)

    def test_plain_summon_does_not_execute_battlecry(self):
        g = self.game((PREFIX+'summon',)); self.play(g, PREFIX+'summon')
        self.assertFalse(g.state.split_damage_history)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id, ELEPHANT)

    def test_location_installation_is_not_a_spell_or_damage_body(self):
        g = self.game((VOLCANO,)); source = self.play(g, VOLCANO)
        self.assertEqual((g.state.players[1].mana,g.state.entities[source].durability),(37,3))
        self.assertFalse(g.state.cast_history); self.assertFalse(g.state.split_damage_history)
        g.apply(UseLocation(1, source))
        self.assertEqual(g.state.entities[source].durability, 2)
        self.assertEqual([v.damage_kind for v in self.values(g)], ['effect']*3)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(UseLocation(1, source))
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_location_prior_actual_fire_play_doubles_three_point_groups(self):
        g = self.game((VOLCANO,FIRE)); source = self.play(g,VOLCANO)
        self.play(g,FIRE,g.state.players[2].hero_id); g.apply(UseLocation(1,source))
        self.assertEqual(len(g.state.split_damage_history),2); self.assertEqual(len(self.values(g)),6)
        self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,18); self.portable(g)

    def test_previous_turn_fire_is_not_current_turn_play_history(self):
        g = self.game((VOLCANO,FIRE)); source = self.play(g,VOLCANO)
        self.play(g,FIRE,g.state.players[2].hero_id); self.turn(g); self.turn(g); g.apply(UseLocation(1,source))
        self.assertEqual(len(self.values(g)),3)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,21)

    def test_automatic_fire_cast_does_not_invent_a_paid_fire_play(self):
        g = self.game((VOLCANO,PREFIX+'auto_fire')); source = self.play(g,VOLCANO)
        self.play(g,PREFIX+'auto_fire'); g.apply(UseLocation(1,source))
        self.assertEqual(len(self.values(g)),3); self.assertEqual(len(g.state.cast_history),2)

    def test_countered_committed_fire_counts_under_existing_play_policy(self):
        g = self.game((VOLCANO,FIRE),enemy_hand=('EX1_287',),active=2)
        self.play(g,'EX1_287'); self.turn(g); source = self.play(g,VOLCANO)
        self.play(g,FIRE,g.state.players[2].hero_id); self.assertTrue(g.state.play_history[-1].countered)
        g.apply(UseLocation(1,source)); self.assertEqual(len(self.values(g)),6)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24)

    def test_location_three_uses_retire_original_without_suppressing_last_damage(self):
        g = self.game((VOLCANO,)); source = self.play(g,VOLCANO)
        for n in range(3):
            if n:
                for _ in range(4): self.turn(g)
            g.apply(UseLocation(1,source))
        self.assertEqual(len(self.values(g)),9)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,21); self.portable(g)

    def test_original_unit_waiting_failure_restores_rng_packet_and_payment(self):
        g = self.game(board=(PREFIX+'wait',)); self.play(g); before = g.snapshot(); other = self.portable(g)
        self.assertEqual(len(self.values(g)),1)
        with self.assertRaises(ResolutionError): self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for current in (g,other): self.finish(current)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.players[1].mana,36); self.assertEqual(len(self.values(g)),3); self.portable(g)

    def test_next_unit_requotes_actual_source_controller_without_changing_actor_pool(self):
        g = self.game(board=(PREFIX+'wait',)); source = self.play(g)
        self.choose(g,'take'); self.finish(g); root, = g.state.split_damage_history
        self.assertEqual([p.source.controller for p in root.packets],[1,2,2])
        self.assertEqual(root.request.player_id,1); self.assertEqual(g.state.entities[source].controller,2)
        self.assertEqual([v.source_controller for v in self.values(g)],[1,2,2]); self.portable(g)

    def test_source_death_preserves_remaining_group_with_live_delivery_facts(self):
        g = self.game(board=(PREFIX+'wait',)); source = self.play(g)
        self.choose(g,'kill'); self.finish(g); root, = g.state.split_damage_history
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual([p.source.zone for p in root.packets],[Zone.BOARD,Zone.GRAVEYARD,Zone.GRAVEYARD])
        self.assertEqual(len(self.values(g)),3); self.assertEqual(len(g.state.split_damage_history),1); self.portable(g)

    def test_later_granted_lifesteal_uses_next_unit_not_frozen_root_keywords(self):
        g = self.game((PREFIX+'hurt',ELEPHANT),board=(PREFIX+'wait',)); self.play(g,PREFIX+'hurt'); self.play(g)
        self.choose(g,'lifesteal'); self.finish(g); root, = g.state.split_damage_history
        self.assertNotIn(Keyword.LIFESTEAL,root.packets[0].source_keywords)
        self.assertTrue(all(Keyword.LIFESTEAL in p.source_keywords for p in root.packets[1:]))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27); self.portable(g)

    def test_rehashed_waiting_unit_cannot_borrow_source_controller_or_keywords(self):
        g = self.game(board=(PREFIX+'wait',)); self.play(g)
        for field,value in (('controller',2),('keywords',['lifesteal'])):
            s = deepcopy(g.snapshot()); packet = s['state']['split_damage_history'][0]['packets'][0]
            if field=='keywords': packet['source_keywords']=value
            else: packet['source'][field]=value
            with self.subTest(field=field): self.reject(s)

    def test_invalid_profiles_fake_cast_and_wrong_source_kind_reject(self):
        for kwargs in (dict(profile=NON_SPELL_PROFILE,kind=DamageKind.MINION_ABILITY,cast_id=1),
                       dict(kind=DamageKind.MINION_ABILITY,cast_id=None),
                       dict(profile=NON_SPELL_PROFILE,kind='effect',cast_id=None)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RandomSplitDamage(1,source_id=1,amount=3,**kwargs)
        g = self.game((PREFIX+'bad_source',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,PREFIX+'bad_source')
        self.assertEqual(g.snapshot(),before)

    def test_zero_and_empty_nonspell_roots_keep_rng_and_close_actual_obligations(self):
        for name,reason in (('zero','exhausted'),('empty','empty_pool')):
            with self.subTest(name=name):
                g = self.game((PREFIX+name,)); rng = g._rng.getstate(); self.play(g,PREFIX+name)
                root, = g.state.split_damage_history
                self.assertEqual(g._rng.getstate(),rng); self.assertEqual(root.reason,reason)
                self.assertFalse(root.packets); self.assertTrue(root.completed); self.portable(g)


if __name__ == '__main__': unittest.main()
