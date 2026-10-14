"""Hero ordinary listeners across actual installation, replacement and waiting."""
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, EndTurnSpec, Game, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, Effect, GainArmor, GrantTrigger,
    ReplaceHero, RequestChoice)
from hs_sim.engine.end_turns import TriggerEndTurnEffects
from hs_sim.engine.generated_heroes import InstallGeneratedHeroCard
from hs_sim.engine.model import EndTurnRequest, EndTurnSelector
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards


@dataclass(frozen=True)
class HeroTriggerDeliberateFailure(Effect):
    pass


def mechanics():
    m = default_mechanics('hero-ordinary-tests-v1')
    def fail(r, e): raise ResolutionError('deliberate ordinary hero failure')
    m.register(HeroTriggerDeliberateFailure, fail)
    return m


def registry():
    r = Registry('hero-ordinary-tests-v1')
    r.register_behavior('tick', lambda c: (GainArmor(c.player_id, 1),) if c.event.player_id == c.player_id else ())
    def wait(c):
        if c.event.player_id != c.player_id: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('a', 'Continue', (GainArmor(c.player_id, 3),)),), source_id=c.source_id),)
    r.register_behavior('wait', wait)
    r.register_behavior('fail', lambda c: (GainArmor(c.player_id, 1), HeroTriggerDeliberateFailure()))
    r.register_behavior('owner_end', lambda c: (GainArmor(c.player_id, 4),) if c.event.player_id == c.player_id else ())
    r.register_card(CardDefinition('plain_hero', 'Plain hero', CardType.HERO, health=30))
    for name, behavior in (('printed', 'tick'), ('waiting', 'wait'), ('failing', 'fail')):
        r.register_card(CardDefinition(name, name, CardType.HERO, health=30,
            triggers=(TriggerSpec('card_played', behavior),)))
    r.register_card(CardDefinition('end_hero', 'End hero', CardType.HERO, health=30,
        triggers=(TriggerSpec('turn_ended', 'owner_end'),)))
    r.register_behavior('noop', lambda c: ())
    r.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, on_use='noop'))
    r.register_card(CardDefinition('hero_card', 'Hero card', CardType.HERO, health=30,
        hero_card=True, initial_hero_power='power', triggers=(TriggerSpec('card_played', 'tick'),)))
    r.register_card(CardDefinition('waiting_card', 'Waiting card', CardType.HERO, health=30,
        hero_card=True, initial_hero_power='power', triggers=(TriggerSpec('card_played', 'wait'),)))
    r.register_card(CardDefinition('ordinary', 'Ordinary', CardType.MINION, health=4))
    def swap(c):
        if c.event.player_id == c.player_id and c.state.entities[c.event.source_id].card_id == 'pulse':
            return (ReplaceHero(c.player_id, 'plain_hero'),)
        return ()
    r.register_behavior('swap', swap)
    r.register_card(CardDefinition('switcher', 'Switcher', CardType.MINION, health=4,
        triggers=(TriggerSpec('card_played', 'swap'),)))
    def grant(c, expiry=False, twice=False, classified=False):
        effect = GrantTrigger(c.state.players[c.player_id].hero_id, 'turn_ended' if classified else 'card_played',
            'tick', c.source_id, c.state.turn if expiry else None, EndTurnSpec() if classified else None)
        return (effect, effect) if twice else (effect,)
    r.register_behavior('grant', grant)
    r.register_behavior('grant_twice', lambda c: grant(c, twice=True))
    r.register_behavior('grant_expiring', lambda c: grant(c, expiry=True))
    r.register_behavior('grant_classified', lambda c: grant(c, classified=True))
    r.register_behavior('grant_unknown', lambda c: (GrantTrigger(c.state.players[c.player_id].hero_id,
        'card_played', 'unknown', c.source_id),))
    r.register_behavior('grant_old', lambda c: (GrantTrigger(next(i for i in c.state.players[c.player_id].graveyard
        if c.state.entities[i].kind == CardType.HERO), 'card_played', 'tick', c.source_id),))
    r.register_behavior('replace', lambda c: (ReplaceHero(c.player_id, 'plain_hero'),))
    r.register_behavior('install', lambda c: (InstallGeneratedHeroCard(c.player_id, 'hero_card', c.source_id),))
    r.register_behavior('lethal', lambda c: (Damage(c.state.players[2].hero_id, 100, c.source_id),))
    r.register_behavior('rerun', lambda c: (ReplayWholeCards(c.player_id, c.source_id,
        WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1, kinds=(CardType.HERO,)),
        physical_profile=PROFILE, choices='player'),))
    r.register_behavior('active_end', lambda c: (TriggerEndTurnEffects(c.player_id,
        EndTurnRequest(EndTurnSelector('owner', (c.player_id,), ('minion', 'weapon', 'location', 'hero_power', 'player_effect'))), c.source_id),))
    for name in ('pulse', 'grant', 'grant_twice', 'grant_expiring', 'grant_classified', 'grant_unknown',
            'grant_old', 'replace', 'install', 'lethal', 'rerun', 'active_end'):
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play='noop' if name == 'pulse' else name))
    return r


class HeroOrdinaryTriggerTests(unittest.TestCase):
    def game(self, hero='plain_hero', hand=('pulse',), board=(), enemy='plain_hero'):
        return Game.from_scenario(Scenario((PlayerSetup(hero, hand=hand, board=board, deck=('ordinary',) * 5,
            mana=10, max_mana=10), PlayerSetup(enemy, deck=('ordinary',) * 5, mana=10, max_mana=10)), seed=234),
            registry(), mechanics=mechanics())

    def play(self, g, name):
        entity = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, entity))

    def armor(self, g, seat=1): return g.state.entities[g.state.players[seat].hero_id].armor

    def portable(self, g, label='stable'):
        snap = json.loads(json.dumps(g.snapshot())); payload = build_replay(g)
        branches = (Game.from_snapshot(snap, registry(), mechanics()), g.clone(), replay(payload, registry(), mechanics()))
        for branch in branches:
            self.assertEqual(branch.snapshot(), snap)
            for seat in (1, 2):
                self.assertEqual(branch.observe(seat), g.observe(seat))
                self.assertEqual(branch.player_events(seat), g.player_events(seat))
                self.assertEqual(branch.for_player(seat).legal_actions(), g.for_player(seat).legal_actions())
        directory = os.environ.get('HERO_ORDINARY_INPUT_DIR')
        if directory:
            self.serial = getattr(self, 'serial', 0) + 1
            p = Path(directory) / self.id() / f'{self.serial:03d}-{label}.json'; p.parent.mkdir(parents=True, exist_ok=True)
            with p.open('x', encoding='utf-8') as f: json.dump({'host_privileged_input': True, 'method_id': self.id(),
                'snapshot': snap, 'replay': payload, 'actual_hero_ordinary_runtime': True}, f, ensure_ascii=False)
        return branches

    def test_static_hero_listener_uses_current_player(self):
        g = self.game('printed'); self.play(g, 'pulse'); self.assertEqual(self.armor(g), 1); self.portable(g)

    def test_enemy_hero_has_its_own_callback_player(self):
        g = self.game(enemy='printed'); self.play(g, 'pulse'); self.assertEqual(self.armor(g, 2), 0); self.portable(g)

    def test_dynamic_grant_enters_real_hero_subscription(self):
        g = self.game(hand=('grant', 'pulse')); self.play(g, 'grant'); self.play(g, 'pulse')
        self.assertEqual(self.armor(g), 2); self.portable(g)

    def test_duplicate_dynamic_abilities_have_independent_callbacks(self):
        g = self.game(hand=('grant_twice', 'pulse')); self.play(g, 'grant_twice'); self.play(g, 'pulse')
        self.assertEqual(self.armor(g), 4); self.portable(g)

    def test_incoming_hero_printed_listener_is_active_on_its_played_event(self):
        g = self.game(hand=('hero_card',)); old = g.state.players[1].hero_id; self.play(g, 'hero_card')
        self.assertEqual(self.armor(g), 1); self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD); self.portable(g)

    def test_replacement_retires_old_printed_subscription(self):
        g = self.game('printed', hand=('replace', 'pulse')); self.play(g, 'replace'); self.play(g, 'pulse')
        self.assertEqual(self.armor(g), 0); self.portable(g)

    def test_ordinary_replacement_preserves_dynamic_hero_trigger(self):
        g = self.game(hand=('grant', 'replace', 'pulse')); self.play(g, 'grant'); self.play(g, 'replace'); self.play(g, 'pulse')
        self.assertEqual(self.armor(g), 3); self.portable(g)

    def test_manual_hero_combines_incoming_printed_and_inherited_dynamic(self):
        g = self.game(hand=('grant', 'hero_card', 'pulse')); self.play(g, 'grant'); self.play(g, 'hero_card'); self.play(g, 'pulse')
        self.assertEqual(self.armor(g), 5); self.portable(g)

    def test_generated_hero_combines_incoming_and_inherited_triggers(self):
        g = self.game(hand=('grant', 'install', 'pulse')); self.play(g, 'grant'); self.play(g, 'install'); self.play(g, 'pulse')
        self.assertEqual(self.armor(g), 5); self.portable(g)

    def test_expiring_hero_trigger_uses_one_actual_natural_clock(self):
        g = self.game(hand=('grant_expiring', 'pulse')); self.play(g, 'grant_expiring'); g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, 'pulse')
        self.assertEqual(self.armor(g), 1); self.portable(g)

    def test_plain_turn_ended_hero_callback_is_ordinary_not_repeatable_subject(self):
        g = self.game('end_hero'); g.apply(EndTurn(1)); self.assertEqual(self.armor(g), 4)
        self.assertTrue(all(not batch.subjects for batch in g.state.end_turn_batches)); self.portable(g)

    def test_active_end_effect_does_not_call_ordinary_hero_turn_listener(self):
        g = self.game('end_hero', hand=('active_end',)); self.play(g, 'active_end'); self.assertEqual(self.armor(g), 0); self.portable(g)

    def test_actual_hero_installation_order_advances_on_replacement(self):
        g = self.game(hand=('hero_card',), board=('ordinary',)); before = g.state
        hero = before.entities[before.players[1].hero_id]; minion = before.entities[before.players[1].board[0]]
        self.assertLess(hero.entered_order, minion.entered_order); self.play(g, 'hero_card')
        self.assertGreater(g.state.entities[g.state.players[1].hero_id].entered_order, minion.entered_order); self.portable(g)

    def test_already_captured_callback_survives_replacement_before_execution(self):
        g = self.game(hand=('hero_card', 'pulse'), board=('switcher',)); self.play(g, 'hero_card'); self.play(g, 'pulse')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].card_id, 'plain_hero')
        self.assertEqual(self.armor(g), 2); self.portable(g)

    def test_waiting_hero_callback_restores_clones_and_replays(self):
        g = self.game('waiting'); self.play(g, 'pulse'); self.assertIsNotNone(g.state.pending_choice)
        branches = self.portable(g, 'waiting')
        for branch in (g, *branches):
            c = branch.state.pending_choice; branch.apply(SelectChoice(c.player_id, c.id, ('a',)))
        for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertEqual(self.armor(g), 3); self.portable(g, 'resumed')

    def test_waiting_retired_hero_callback_retains_accepted_original_source(self):
        g = self.game(hand=('waiting_card', 'pulse'), board=('switcher',)); self.play(g, 'waiting_card')
        c = g.state.pending_choice; g.apply(SelectChoice(c.player_id, c.id, ('a',))); self.play(g, 'pulse')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].card_id, 'plain_hero')
        branches = self.portable(g, 'retired-source-wait')
        for branch in (g, *branches):
            c = branch.state.pending_choice; branch.apply(SelectChoice(c.player_id, c.id, ('a',)))
        for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertEqual(self.armor(g), 6); self.portable(g, 'retired-source-resumed')

    def test_actual_whole_hero_replay_has_ordinary_subscription(self):
        g = self.game(hand=('hero_card', 'rerun', 'pulse')); self.play(g, 'hero_card'); self.play(g, 'rerun'); self.play(g, 'pulse')
        self.assertEqual(self.armor(g), 3); self.assertEqual(len(g.state.whole_card_replay_ledger.children), 1); self.portable(g)

    def test_hero_body_failure_rolls_back_real_spell_payment_and_events(self):
        g = self.game('failing'); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate ordinary hero failure'): self.play(g, 'pulse')
        self.assertEqual(g.snapshot(), before); self.portable(g, 'rollback')

    def test_unknown_dynamic_behavior_rejects_and_rolls_back(self):
        g = self.game(hand=('grant_unknown',)); before = g.snapshot()
        with self.assertRaises((ResolutionError, ValueError)): self.play(g, 'grant_unknown')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_dynamic_classified_hero_end_turn_is_accepted_by_own_pipeline(self):
        g = self.game(hand=('grant_classified',)); self.play(g, 'grant_classified')
        g.apply(EndTurn(1)); self.assertEqual(self.armor(g), 1)
        self.assertEqual(len(g.state.end_turn_history), 1); self.portable(g)

    def test_static_classified_hero_end_turn_registers_and_executes(self):
        r = registry()
        r.register_card(CardDefinition('classified', 'Classified', CardType.HERO, health=30,
            triggers=(TriggerSpec('turn_ended', 'tick', EndTurnSpec()),)))
        g = Game.from_scenario(Scenario((PlayerSetup('classified'), PlayerSetup('plain_hero'))), r, mechanics=mechanics())
        g.apply(EndTurn(1)); self.assertEqual(self.armor(g), 1)
        self.assertEqual(len(g.state.end_turn_history), 1)

    def test_graveyard_hero_grant_is_stale_and_does_not_resubscribe(self):
        g = self.game('printed', hand=('replace', 'grant_old', 'pulse')); self.play(g, 'replace'); self.play(g, 'grant_old'); self.play(g, 'pulse')
        self.assertEqual(self.armor(g), 0); self.assertTrue(any(e.kind == 'effect_skipped' for e in g.events)); self.portable(g)

    def test_lethal_body_never_fabricates_later_hero_played_callback(self):
        g = self.game('printed', hand=('lethal',)); self.play(g, 'lethal')
        self.assertEqual(g.state.status, 'finished'); self.assertEqual(self.armor(g), 0); self.portable(g)

    def test_rehashed_hero_trigger_order_zero_is_rejected(self):
        g = self.game('printed'); bad = g.snapshot(); hero_id = g.state.players[1].hero_id
        bad['state']['entities'][str(hero_id)]['entered_order'] = 0
        payload = {k: v for k, v in bad.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')}
        bad['state_hash'] = canonical_hash(payload)
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry(), mechanics())
        self.portable(g)

    def test_previous_schema114_does_not_infer_new_hero_order(self):
        g = self.game('printed'); bad = g.snapshot(); bad['schema_version'] = 114
        with self.assertRaisesRegex(SnapshotError, 'Unsupported snapshot schema version'): Game.from_snapshot(bad, registry(), mechanics())
        self.portable(g)

    def test_both_player_interfaces_do_not_expose_private_hero_behavior_names(self):
        g = self.game('waiting'); self.play(g, 'pulse')
        for seat in (1, 2):
            text = json.dumps({'observation': g.observe(seat), 'events': g.player_events(seat)}, ensure_ascii=False)
            self.assertNotIn('behavior_id', text); self.assertNotIn('hero-ordinary-tests-v1', text)
        self.portable(g)
