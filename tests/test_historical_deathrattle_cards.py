"""Historical consumers use base private sources and the ordinary DR pipeline."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.historical_deathrattle_cards import SENTENCE, UMBRA, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.deathrattles import activated_deathrattles
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, Damage,
    Destroy, GainArmor, GrantDeathrattle, InvokeBehavior, RequestChoice, ReturnToHand,
    Silence, Transform)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.historical_deathrattles import ROOT, CLOSED, eligible_deaths
from hs_sim.engine.model import DeathrattleRepeatSpec, Resource
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest

P = 'k199.'
RATTLE, WAIT, PLAIN, REPEATER, BLOCKER = (P + s for s in ('rattle', 'wait', 'plain', 'repeat', 'block'))
KILLER = P + 'killer'
YETI = 'CORE_CS2_182'


def registry():
    r = build_registry()
    r.register_behavior(P + 'armor', lambda c: (GainArmor(c.player_id, c.source.attack),))
    r.register_behavior(P + 'granted', lambda c: (GainArmor(c.player_id, 11),))
    def destroy_next(c):
        targets = [i for i in c.state.players[c.player_id].board if i != c.source_id]
        return (Destroy(targets[0], c.source_id),) if targets else ()
    r.register_behavior(P + 'destroy_next', destroy_next)
    r.register_behavior(P + 'fail', lambda c: (AddToHand(c.player_id, P + 'unknown', c.source_id),))
    r.register_behavior(P + 'wait', lambda c: (RequestChoice(c.player_id, (
        ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 3),)),
        ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),))),
        source_id=c.source_id),))
    r.register_card(CardDefinition(RATTLE, 'Base Attack Deathrattle', CardType.MINION,
        attack=2, health=2, deathrattle=P + 'armor'))
    r.register_card(CardDefinition(WAIT, 'Choice Deathrattle', CardType.MINION,
        attack=1, health=2, deathrattle=P + 'wait'))
    r.register_card(CardDefinition(PLAIN, 'No printed Deathrattle', CardType.MINION, attack=1, health=2))
    r.register_card(CardDefinition(KILLER, 'Destroy another friendly minion', CardType.MINION,
        attack=1, health=2, deathrattle=P + 'destroy_next'))
    r.register_card(CardDefinition(REPEATER, 'Repeat source', CardType.MINION,
        attack=1, health=5, deathrattle_repeats=(DeathrattleRepeatSpec(2),)))
    r.register_card(CardDefinition(BLOCKER, 'Deathrattle prohibition', CardType.MINION,
        attack=1, health=5, keywords=(Keyword.DEATHRATTLE_SUPPRESSOR,)))
    scripts = dict(kill=lambda c: (Destroy(c.target_id, c.source_id),),
        grant=lambda c: (GrantDeathrattle(c.target_id, P + 'granted', c.source_id),),
        buff=lambda c: (Buff(c.target_id, attack=5, source_id=c.source_id),),
        silence=lambda c: (Silence(c.target_id),),
        transform=lambda c: (Transform(c.target_id, PLAIN),),
        take=lambda c: (ChangeControl(c.target_id, c.player_id),),
        bounce=lambda c: (ReturnToHand(c.target_id),))
    for name, body in scripts.items():
        r.register_behavior(P + name, body)
        r.register_card(CardDefinition(P + name, name, CardType.SPELL, on_play=P + name, requires_target=True))
    r.validate()
    return r


class HistoricalDeathrattleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(), board=(RATTLE,), enemy=(), actor=1, seed=199):
        own = PlayerSetup('HERO_08', hand=hand, board=board, deck=(YETI,) * 10,
                          mana=50, max_mana=50, mana_cap=50)
        other = PlayerSetup('HERO_08', board=enemy, deck=(YETI,) * 10,
                            mana=50, max_mana=50, mana_cap=50)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
                                          active_player=actor, seed=seed), self.r)

    def entity(self, g, cid, *, zone='board', player=None):
        p = g.state.active_player if player is None else player
        return next(i for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        eid = self.entity(g, cid, zone='hand')
        g.apply(PlayCard(g.state.active_player, eid, target))
        return eid

    def kill(self, g, cid=RATTLE):
        self.play(g, P + 'kill', self.entity(g, cid))

    def armor(self, g, player=None):
        p = g.state.active_player if player is None else player
        return g.state.entities[g.state.players[p].hero_id].armor

    def roots(self, g):
        return [e for e in g.events if e.kind == ROOT]

    def rows(self, g):
        return activated_deathrattles(g.state, g.state.active_player, origin='history')

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(deepcopy(snapshot), registry()).snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snapshot)

    def test_original_source_rows_and_faces(self):
        d = load_batch()
        self.assertEqual([x['record']['id'] for x in d['cards']], [SENTENCE, UMBRA])
        self.assertEqual(len(d['official_observations']), 4)
        for row in d['cards']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        self.assertEqual((self.r.card(UMBRA).cost, self.r.card(UMBRA).attack, self.r.card(UMBRA).health), (7, 6, 6))
        self.assertFalse(d['cn_calibrated'])

    def test_empty_history_spell_is_illegal_and_rolls_back(self):
        g = self.game((SENTENCE,))
        action = PlayCard(1, self.entity(g, SENTENCE, zone='hand'))
        before = g.snapshot()
        self.assertNotIn(action, g.legal_actions())
        with self.assertRaises(IllegalAction):
            g.apply(action)
        self.assertEqual(g.snapshot(), before)

    def test_umbra_can_play_with_no_eligible_deaths_and_no_rng_draw(self):
        g = self.game((UMBRA,), board=())
        before = g.snapshot()['rng_state']
        self.play(g, UMBRA)
        root = self.roots(g)[0]
        self.assertEqual(dict(root.data)['selected'], ())
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(len(g.state.players[1].board), 1)

    def test_real_spell_triggers_once_and_pays_once(self):
        g = self.game((P + 'kill', SENTENCE))
        self.kill(g)
        mana = g.state.players[1].mana
        self.play(g, SENTENCE)
        self.assertEqual(self.armor(g), 4)
        self.assertEqual(g.state.players[1].mana, mana - 1)
        self.assertEqual(len(self.rows(g)), 1)
        self.assertTrue(self.rows(g)[0].completed)

    def test_full_board_spell_does_not_require_or_consume_a_slot(self):
        g = self.game((P + 'kill', YETI, SENTENCE), (RATTLE,) + (YETI,) * 6)
        self.kill(g)
        self.play(g, YETI)
        board = tuple(g.state.players[1].board)
        deaths = tuple(g.state.death_history)
        summons = tuple(g.state.successful_summon_history)
        corpses = g.state.players[1].resources[Resource.CORPSES]
        self.play(g, SENTENCE)
        self.assertEqual(tuple(g.state.players[1].board), board)
        self.assertEqual(tuple(g.state.death_history), deaths)
        self.assertEqual(tuple(g.state.successful_summon_history), summons)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], corpses)
        self.assertEqual(self.armor(g), 4)

    def test_private_carrier_keeps_original_dead_entity_untouched(self):
        g = self.game((P + 'kill', SENTENCE))
        old = self.entity(g, RATTLE)
        self.kill(g)
        original = deepcopy(g.state.entities[old])
        self.play(g, SENTENCE)
        carrier = self.rows(g)[0].capture.carrier_id
        self.assertNotEqual(carrier, old)
        self.assertEqual(g.state.entities[old], original)
        self.assertEqual(g.state.entities[carrier].zone, Zone.SETASIDE)

    def test_base_attack_does_not_replay_old_buffs(self):
        g = self.game((P + 'buff', P + 'kill', SENTENCE))
        self.play(g, P + 'buff', self.entity(g, RATTLE))
        self.kill(g)
        self.assertEqual(self.armor(g), 7)
        self.play(g, SENTENCE)
        self.assertEqual(self.armor(g), 9)
        self.assertEqual(self.rows(g)[0].source_attack, 2)

    def test_granted_rattle_is_excluded_from_historical_payload(self):
        g = self.game((P + 'grant', P + 'kill', SENTENCE))
        self.play(g, P + 'grant', self.entity(g, RATTLE))
        self.kill(g)
        self.assertEqual(self.armor(g), 13)
        self.play(g, SENTENCE)
        self.assertEqual(self.armor(g), 15)
        self.assertEqual(len(self.rows(g)), 1)
        self.assertEqual(self.rows(g)[0].capture.ability.origin, 'printed')

    def test_granted_only_minion_is_not_a_historical_candidate(self):
        g = self.game((P + 'grant', P + 'kill', SENTENCE), (PLAIN,))
        self.play(g, P + 'grant', self.entity(g, PLAIN))
        self.kill(g, PLAIN)
        self.assertEqual(eligible_deaths(g.state, g.registry, 1), ())
        self.assertNotIn(PlayCard(1, self.entity(g, SENTENCE, zone='hand')), g.legal_actions())

    def test_silence_is_not_copied_to_the_fresh_printed_body(self):
        g = self.game((P + 'silence', P + 'kill', SENTENCE))
        self.play(g, P + 'silence', self.entity(g, RATTLE))
        self.kill(g)
        self.assertEqual(self.armor(g), 0)
        self.play(g, SENTENCE)
        self.assertEqual(self.armor(g), 2)

    def test_capture_retains_its_original_death_face(self):
        g = self.game((P + 'kill', SENTENCE))
        self.kill(g)
        # Source selection reads immutable DeathRecords; no present graveyard lookup.
        death = g.state.death_history[0]
        self.assertEqual(death.card_id, RATTLE)
        self.play(g, SENTENCE)
        self.assertEqual(self.rows(g)[0].capture.card_id, death.card_id)

    def test_opponent_death_is_not_eligible(self):
        g = self.game((P + 'kill', SENTENCE), board=(), enemy=(RATTLE,))
        self.play(g, P + 'kill', self.entity(g, RATTLE, player=2))
        self.assertEqual(eligible_deaths(g.state, g.registry, 1), ())
        self.assertEqual(self.armor(g, 2), 2)

    def test_controller_at_death_is_the_friendly_owner(self):
        g = self.game((P + 'take', P + 'kill', SENTENCE), board=(), enemy=(RATTLE,))
        enemy = self.entity(g, RATTLE, player=2)
        self.play(g, P + 'take', enemy)
        self.kill(g)
        self.play(g, SENTENCE)
        self.assertEqual(self.armor(g), 4)
        self.assertEqual(self.armor(g, 2), 0)

    def test_second_seat_uses_its_own_history_and_hero(self):
        g = self.game((P + 'kill', SENTENCE), actor=2)
        self.kill(g)
        self.play(g, SENTENCE)
        self.assertEqual(self.armor(g, 2), 4)
        self.assertEqual(self.armor(g, 1), 0)

    def test_umbra_selects_up_to_five_death_occurrences_not_card_names(self):
        g = self.game((P + 'kill',) * 6 + (UMBRA,), (RATTLE,) * 6)
        for _ in range(6):
            self.kill(g)
        self.play(g, UMBRA)
        data = dict(self.roots(g)[0].data)
        self.assertEqual(data['candidates'], (1, 2, 3, 4, 5, 6))
        self.assertEqual(len(data['selected']), 5)
        self.assertEqual(len(set(data['selected'])), 5)
        self.assertEqual(len(self.rows(g)), 5)
        self.assertEqual(self.armor(g), 22)

    def test_umbra_uses_all_available_deaths_when_fewer_than_five(self):
        g = self.game((P + 'kill', P + 'kill', UMBRA), (RATTLE, RATTLE))
        self.kill(g)
        self.kill(g)
        self.play(g, UMBRA)
        self.assertEqual(len(self.rows(g)), 2)
        self.assertEqual(self.armor(g), 8)

    def test_deaths_during_selected_payload_do_not_join_original_inventory(self):
        g = self.game((P + 'kill', RATTLE, UMBRA), (KILLER,))
        self.kill(g, KILLER)
        self.play(g, RATTLE)
        self.play(g, UMBRA)
        data = dict(self.roots(g)[0].data)
        self.assertEqual(data['candidates'], (1,))
        self.assertEqual(data['selected'], (1,))
        self.assertEqual(len(g.state.death_history), 2)
        self.assertEqual(len(self.rows(g)), 1)
        self.assertEqual(self.armor(g), 2)

    def test_current_repeat_source_applies_to_historical_printed_body(self):
        g = self.game((P + 'kill', SENTENCE), (RATTLE, REPEATER))
        self.kill(g)
        self.assertEqual(self.armor(g), 4)
        self.play(g, SENTENCE)
        self.assertEqual(self.armor(g), 8)
        self.assertEqual([d.capture.repeat_index for d in self.rows(g)], [1, 2])

    def test_current_global_prohibition_blocks_historical_execution(self):
        g = self.game((P + 'kill', SENTENCE), (RATTLE, BLOCKER))
        self.kill(g)
        self.play(g, SENTENCE)
        self.assertEqual(self.armor(g), 0)
        self.assertEqual(len(self.rows(g)), 0)
        self.assertEqual(len([e for e in g.events if e.kind == CLOSED]), 1)

    def test_printed_native_memory_starts_at_base_not_dead_growth(self):
        egg = 'CATA_210'
        g = self.game((P + 'kill', SENTENCE), (egg,))
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.kill(g, egg)
        self.play(g, SENTENCE)
        whelps = [g.state.entities[i] for i in g.state.players[1].board
                  if g.state.entities[i].card_id == 'CATA_210t']
        self.assertEqual(sorted((e.attack, e.health) for e in whelps), [(2, 1), (3, 2)])

    def waiting(self, *, umbra=False):
        g = self.game((P + 'kill', UMBRA if umbra else SENTENCE), (WAIT,))
        self.kill(g, WAIT)
        self.choose(g)
        self.play(g, UMBRA if umbra else SENTENCE)
        self.assertIsNotNone(g.state.pending_choice)
        return g

    def test_historical_choice_waiting_restores_clone_and_replays(self):
        g = self.waiting()
        self.portable(g)
        self.choose(g)
        self.assertEqual(self.armor(g), 6)
        self.portable(g)

    def test_umbra_choice_uses_ordinary_battlecry_and_deathrattle_frames(self):
        g = self.waiting(umbra=True)
        self.portable(g)
        self.choose(g)
        self.assertEqual(len(g.state.players[1].board), 1)
        self.assertEqual(self.armor(g), 6)

    def test_failed_choice_restores_waiting_boundary(self):
        g = self.waiting()
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertEqual(self.armor(g), 6)

    def test_finished_state_and_random_history_are_portable(self):
        g = self.game((P + 'kill', P + 'kill', SENTENCE), (RATTLE, WAIT))
        self.kill(g)
        self.kill(g, WAIT)
        self.choose(g)
        self.play(g, SENTENCE)
        if g.state.pending_choice:
            self.choose(g)
        self.portable(g)

    def test_selection_rng_and_candidates_are_bound_in_snapshot(self):
        g = self.waiting()
        s = g.snapshot()
        bad = deepcopy(s)
        root = next(e for e in bad['events'] if e['kind'] == ROOT)
        root['data']['selected'] = []
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(bad, registry())

    def drop_work(self, value, suffix):
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, list):
                    value[key] = [v for v in child if not (isinstance(v, dict)
                        and str(v.get('type', '')).endswith(suffix))]
                self.drop_work(value[key], suffix)
        elif isinstance(value, list):
            for child in value:
                self.drop_work(child, suffix)

    def test_waiting_cannot_drop_historical_root_completion(self):
        g = self.waiting()
        bad = deepcopy(g.snapshot())
        self.drop_work(bad['resolution_frame'], '.FinishHistoricalDeathrattles')
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(bad, registry())

    def test_waiting_cannot_drop_selected_minion_completion(self):
        g = self.waiting()
        bad = deepcopy(g.snapshot())
        self.drop_work(bad['resolution_frame'], '.FinishHistoricalDeathrattle')
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(bad, registry())

    def test_history_can_be_triggered_again_with_independent_private_sources(self):
        g = self.game((P + 'kill', SENTENCE, SENTENCE))
        self.kill(g)
        self.play(g, SENTENCE)
        self.play(g, SENTENCE)
        self.assertEqual(self.armor(g), 6)
        rows = self.rows(g)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].capture.carrier_id, rows[1].capture.carrier_id)
        self.assertEqual(len(g.state.death_history), 1)

    def test_player_views_do_not_expose_private_carriers_or_selection_receipts(self):
        g = self.game((P + 'kill', SENTENCE))
        self.kill(g)
        self.play(g, SENTENCE)
        for p in (1, 2):
            view = g.for_player(p).observe()
            text = json.dumps(view, ensure_ascii=False)
            for private in ('rng_before', 'rng_after', 'historical_root', 'historical_deathrattles_selected'):
                self.assertNotIn(private, text)
            g.for_player(p).legal_actions()


if __name__ == '__main__':
    unittest.main()
