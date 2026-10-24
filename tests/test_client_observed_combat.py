"""Bounded legacy-client combat observations against real current adapters.

These are projected situations from build 254477, not complete game replays or
acceptance of the fixed CN 37.0 target. The packet records every projection
assumption and the complete anonymous windows from the pinned observation.
"""
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.engine import (Attack, CardDefinition, CardType, Game, Keyword,
                          PlayCard, PlayerSetup, Scenario, Zone)
from hs_sim.engine.effects import Damage, GrantKeyword, SetStats
from hs_sim.targets import canonical_digest
from card_batch_testkit import CardBatchTestMixin

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/support/legacy-client-combat-observations-v1.json'
PIN = 'da2b44ec79a3c03260fe5c94e0c0701337b8c27e9ae88e629b6079bcd4b2a1b4'
PREFIX = 'fixture.client_combat.'


@lru_cache(maxsize=1)
def packet():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Legacy observation packet lost its complete source binding')
    for row in data['source_records']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise ValueError('Legacy comparison lost its complete current raw record')
    if (data['boundary']['current_target_behavior_certified'] or
            data['boundary']['official_calibration_cases_added'] != 0 or
            data['boundary']['complete_game_reconstruction']):
        raise ValueError('Legacy projected observations cannot certify CN 37.0')
    return data


def bindings(game, case):
    return {actor['role']: next(eid for eid in game.state.players[actor['owner']].board
            if game.state.entities[eid].card_id == actor['card_id'])
            for actor in case['actors']}


@lru_cache(maxsize=None)
def fixture(mode='projection', role='writer'):
    if mode != 'projection':
        raise ValueError('Only the explicit projected combat fixture is available')
    registry = build_registry()
    # Preserve the Priest's native class; the portrait and observed 40 maximum
    # health are fixture material, not a newly supported cosmetic hero.
    priest = registry.card('HERO_09')
    registry.register_card(replace(priest, id=PREFIX + 'priest40',
                                   name='Observed Priest at 40 maximum health', health=40))
    for case in packet()['cases']:
        def setup(context, case=case):
            result = []
            actors = bindings_from_state(context.state, case)
            for row in case['actors']:
                target = actors[row['role']]
                result.append(SetStats(target, row['attack'], row['max_health'], context.source_id))
                if row['damage']:
                    result.append(Damage(target, row['damage'], context.source_id))
                result.extend(GrantKeyword(target, Keyword(k), context.source_id)
                              for k in row['fixture_extra_keywords'])
            for hero in case['heroes']:
                if hero['damage']:
                    result.append(Damage(context.state.players[hero['owner']].hero_id,
                                         hero['damage'], context.source_id))
            return tuple(result)
        name = PREFIX + case['id']
        registry.register_behavior(name, setup)
        registry.register_card(CardDefinition(name, 'Observed initial combat material',
                                              CardType.SPELL, on_play=name))
    registry._version = 'legacy-client-combat-projection-v1'
    registry.validate()
    registry.freeze()
    return registry


def bindings_from_state(state, case):
    return {actor['role']: next(eid for eid in state.players[actor['owner']].board
            if state.entities[eid].card_id == actor['card_id'])
            for actor in case['actors']}


def client_labels(case):
    return {**{a['client_entity_id']: a['role'] for a in case['actors']},
            **{h['client_entity_id']: 'hero' + str(h['owner']) for h in case['heroes']}}


def client_projection(case):
    """Compare semantic deliveries, not transient internal tag-write order."""
    labels = client_labels(case)
    events = case['events']
    result = []
    for event in events:
        if event['kind'] == 'metadata' and event['meta'] == 'DAMAGE' and event['data'] > 0:
            info = [e for e in events if e['kind'] == 'metadata_info'
                    and e['packet_line'] == event['line']]
            if len(info) != 1:
                raise ValueError('Compared damage must name its one actually observed recipient')
            target = info[0]['entity'].get('entity_id')
            if target in labels:
                result.append((event['line'], 'damage', labels[target], event['data']))
        elif event['kind'] == 'tag_change' and event['tag'] == 'ZONE' and event['value'] == 'GRAVEYARD':
            target = event['entity'].get('entity_id')
            if target in labels:
                result.append((event['line'], 'death', labels[target], None))
        elif event['kind'] == 'tag_change' and event['tag'] == 'DIVINE_SHIELD' and event['value'] == 0:
            target = event['entity'].get('entity_id')
            if target in labels:
                result.append((event['line'], 'shield', labels[target], None))
    return result


class ClientObservedCombatTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, case_id):
        self.mode = 'projection'
        case = next(c for c in packet()['cases'] if c['id'] == case_id)
        players = []
        for pid in (1, 2):
            hero = next(h for h in case['heroes'] if h['owner'] == pid)
            players.append(PlayerSetup(hero['fixture_card_id'],
                board=tuple(a['card_id'] for a in case['actors'] if a['owner'] == pid),
                hand=(PREFIX + case_id,) if case['active_player'] == pid else (),
                mana=10, max_mana=10, armor=hero['armor']))
        game = Game.from_scenario(Scenario(tuple(players), active_player=case['active_player'],
                                         seed=case['seed'], name=case_id), fixture('projection', 'writer'))
        self.play(game, PREFIX + case_id, player=case['active_player'])
        actor_ids = bindings(game, case)
        for row in case['actors']:
            actor = game.state.entities[actor_ids[row['role']]]
            self.assertEqual((actor.attack, actor.max_health, actor.damage),
                             (row['attack'], row['max_health'], row['damage']))
        for row in case['heroes']:
            hero = game.state.entities[game.state.players[row['owner']].hero_id]
            self.assertEqual((hero.max_health, hero.damage, hero.armor),
                             (row['max_health'], row['damage'], row['armor']))
        return case, game

    def run_attacks(self, case, game):
        actor_ids = bindings(game, case)
        labels = {**{eid: name for name, eid in actor_ids.items()},
                  **{p.hero_id: 'hero' + str(pid) for pid, p in game.state.players.items()}}
        observed = []
        raw_events = []
        for action in case['actions']:
            result = game.apply(Attack(case['active_player'], actor_ids[action['attacker']],
                                       actor_ids[action['target']]))
            raw_events.extend(result.events)
        for event in raw_events:
            if event.kind == 'damage_dealt' and event.amount > 0 and event.target_id in labels:
                observed.append((event.sequence, 'damage', labels[event.target_id], event.amount))
            elif event.kind == 'minion_died' and event.target_id in labels:
                observed.append((event.sequence, 'death', labels[event.target_id], None))
            elif event.kind == 'shield_lost' and event.target_id in labels:
                observed.append((event.sequence, 'shield', labels[event.target_id], None))
        return actor_ids, observed, raw_events

    def replay_pair(self, case, game):
        # Continue the restored game through the actual attacks, not just load
        # and discard it. Source fixtures do not need artificial choices.
        restored = self.portable(game)
        first = self.run_attacks(case, game)
        second = self.run_attacks(case, restored)
        self.assertEqual(first[1], second[1])
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.portable(game)
        return first

    def test_actual_pair_commits_both_combat_damage_deliveries_before_mutual_deaths(self):
        case, game = self.game('mutual_damage_before_deaths')
        actors, actual, _ = self.replay_pair(case, game)
        expected = client_projection(case)
        self.assertEqual([row[1:] for row in actual], [row[1:] for row in expected])
        self.assertEqual([r[1:] for r in expected], [('damage', 'defender', 2),
                         ('damage', 'attacker', 1), ('death', 'attacker', None), ('death', 'defender', None)])
        self.assertTrue(all(game.state.entities[eid].zone == Zone.GRAVEYARD for eid in actors.values()))

    def test_actual_shielded_spirit_blocks_retaliation_before_xavius_dies(self):
        case, game = self.game('shield_blocks_retaliation')
        actors, actual, events = self.replay_pair(case, game)
        expected = client_projection(case)
        # Tag writes and semantic health-event publication have different
        # granularity. Compare the deliveries and their common death barrier.
        self.assertCountEqual([r[1:] for r in actual], [r[1:] for r in expected])
        for rows in (expected, actual):
            death = next(r[0] for r in rows if r[1] == 'death')
            self.assertTrue(all(r[0] < death for r in rows if r[1] in ('damage', 'shield')))
        attacker = game.state.entities[actors['attacker']]
        self.assertEqual((attacker.zone, attacker.health), (Zone.BOARD, 3))
        self.assertNotIn(Keyword.DIVINE_SHIELD, attacker.keywords)
        self.assertIn(Keyword.REBORN, attacker.keywords)
        self.assertEqual(game.state.entities[actors['defender']].zone, Zone.GRAVEYARD)
        self.assertFalse(any(e.kind == 'minion_reborn' for e in events))

    def test_two_real_windfury_attacks_resolve_overheal_deathrattle_before_native_reborn(self):
        case, game = self.game('overheal_deathrattle_before_reborn')
        actors, actual, events = self.replay_pair(case, game)
        expected = client_projection(case)
        self.assertEqual([r[1:] for r in actual], [r[1:] for r in expected])
        death = next(e for e in events if e.kind == 'minion_died' and e.target_id == actors['defender'])
        extra = next(e for e in events if e.kind == 'damage_dealt' and
                     e.target_id == game.state.players[2].hero_id and e.amount == 3)
        reborn = next(e for e in events if e.kind == 'minion_reborn')
        self.assertLess(death.sequence, extra.sequence)
        self.assertLess(extra.sequence, reborn.sequence)
        newborn = game.state.entities[reborn.target_id]
        client_new = next(e for e in case['events'] if e['kind'] == 'full_entity'
                          and e.get('card_id') == 'CAP_803')
        cid = client_new['entity']['entity_id']
        tags = {e['tag']: e['value'] for e in case['events']
                if e['kind'] in ('initial_tag', 'tag_change') and e['entity'].get('entity_id') == cid}
        self.assertLess(next(r[0] for r in expected if r[1:3] == ('damage', 'hero2')), client_new['line'])
        self.assertEqual((newborn.card_id, newborn.attack, newborn.max_health, newborn.damage),
                         ('CAP_803', tags['ATK'], tags['HEALTH'], tags['DAMAGE']))
        self.assertEqual(newborn.health, 1)
        self.assertEqual(tags['REBORN'], 0)
        self.assertNotIn(Keyword.REBORN, newborn.keywords)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 24)
        self.assertEqual(game.state.entities[actors['attacker']].attacks_this_turn, 2)


if __name__ == '__main__':
    unittest.main()
