"""Actual generated weapon, separate Battlecry/Combo, and physical provenance."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_generated_weapon_combo_cards import (
    CARD, PREFIX, load_batch, register_native_generated_weapon_combo_cards)
from hs_sim.engine import (BattlecryRepeatSpec, CardClass, CardDefinition, CardMetadata,
    CardType, ComboRepeatSpec, Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry,
    RewindSpec, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, InvokeBehavior,
    RequestChoice)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.generated_combo_repeats import PROFILE
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference, MoveCard

P = 'k152.'
HERO, PLAIN, NOP, FOREIGN, OWN, NEUTRAL, UNKNOWN = (
    P + n for n in ('hero', 'plain', 'nop', 'foreign', 'own', 'neutral', 'unknown'))
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.NONE, tribes=())


@lru_cache(maxsize=6)
def registry(role, mode='normal'):
    assert role in ('writer', 'reader') and mode in ('normal', 'empty', 'unknown')
    r = Registry('k152-actual-weapon-' + mode + '-v1')
    register_native_generated_weapon_combo_cards(r)
    r.register_card(CardDefinition(HERO, 'Mage fixture', CardType.HERO, health=30,
        metadata=CardMetadata(False, (CardClass.MAGE,), Rarity.NONE, tribes=())))
    r.register_card(CardDefinition(PLAIN, 'Plain fixture', CardType.MINION,
        attack=1, health=3, metadata=META))
    r.register_behavior(NOP, lambda c: ())
    r.register_card(CardDefinition(NOP, 'No-op fixture', CardType.SPELL, on_play=NOP, metadata=META))
    weapons = []
    for cid, cls in ((FOREIGN, CardClass.WARRIOR), (OWN, CardClass.MAGE),
                     (NEUTRAL, CardClass.NEUTRAL), (UNKNOWN, CardClass.DRUID)):
        definition = CardDefinition(cid, cid, CardType.WEAPON, cost=2, attack=3, durability=2,
            metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=()))
        if cid != UNKNOWN:
            r.register_card(definition)
        r.register_pool_card(PoolCard.from_definition(definition))
        if cid in (OWN, NEUTRAL) or (mode == 'normal' and cid == FOREIGN) or (mode == 'unknown' and cid == UNKNOWN):
            weapons.append(PoolMember(cid))
    r.register_pool(PoolDefinition('constructed.cards', 'k152-v1', 'k152', 'experimental',
                                   tuple(weapons), complete=True))
    r.register_card(CardDefinition(P + 'repeat', 'Repeat fixture', CardType.MINION, health=8,
        battlecry_repeats=(BattlecryRepeatSpec(),), combo_repeats=(ComboRepeatSpec(),), metadata=META))
    r.register_card(CardDefinition(P + 'rewind', 'Rewind alias fixture', CardType.MINION,
        cost=4, attack=5, health=4, keywords=(Keyword.COMBO, Keyword.REWIND), rewind=RewindSpec(),
        battlecry=PREFIX + 'battlecry', combo=PREFIX + 'combo', metadata=META))
    r.register_behavior(P + 'replay', lambda c: (ReplayWholeCards(c.player_id, c.source_id,
        WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1,
                             kinds=(CardType.MINION,)), choices='player', physical_profile=PROFILE),))
    r.register_card(CardDefinition(P + 'replay', 'Replay fixture', CardType.SPELL,
        on_play=P + 'replay', metadata=META))
    r.register_behavior(P + 'trigger', lambda c: (TriggerBattlecry(
        MinionReference.capture(c.state.entities[c.target_id]), c.source_id, choices='player'),))
    from hs_sim.engine import TargetSpec
    r.register_card(CardDefinition(P + 'trigger', 'Trigger fixture', CardType.SPELL,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='friendly'),
        on_play=P + 'trigger', metadata=META))
    def fail(c):
        raise ResolutionError('deliberate K152 rollback')
    r.register_behavior(P + 'fail', fail)
    def wait(c, failure=False):
        effects = (InvokeBehavior(P + 'fail', c.source_id, c.player_id),) if failure else ()
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', effects),), c.source_id),)
    def created(c, action):
        if c.event.target_id is None or c.state.entities[c.event.target_id].kind != CardType.WEAPON:
            return ()
        if action == 'kill':
            return (Destroy(c.event.source_id),)
        return wait(c, failure=action == 'fail_wait')
    def back(c):
        return (MoveCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id,
                         Zone.HAND, source_id=c.source_id),)
    r.register_behavior(P + 'back', back)
    def move(c, reenter):
        if c.event.target_id is None or c.state.entities[c.event.target_id].kind != CardType.WEAPON:
            return ()
        original = CardReference.capture(c.state.entities[c.event.target_id])
        work = [MoveCard(original, c.player_id, Zone.DECK, position='top', source_id=c.source_id)]
        if reenter:
            work.append(InvokeBehavior(P + 'back', c.source_id, c.player_id, original.entity_id))
        work.append(AddToHand(c.player_id, OWN, source_id=c.source_id))
        return tuple(work)
    for action in ('kill', 'wait', 'fail_wait', 'move', 'reenter'):
        key = P + action
        def watcher(c, action=action):
            # The decoy must not recursively trigger this source fixture.
            if c.event.source_id == c.source_id:
                return ()
            return move(c, action == 'reenter') if action in ('move', 'reenter') else created(c, action)
        r.register_behavior(key, watcher)
        r.register_card(CardDefinition(key, key, CardType.MINION, health=8,
            triggers=(TriggerSpec('card_added_to_hand', key),), metadata=META))
    r.register_behavior(P + 'combo_wait', wait)
    r.register_card(CardDefinition(P + 'combo_wait', 'Combo start wait', CardType.MINION, health=8,
        triggers=(TriggerSpec('combo_started', P + 'combo_wait'),), metadata=META))
    def fill(c):
        if dict(c.event.data).get('battlecry_id') is None:
            return ()
        return tuple(AddToHand(c.player_id, PLAIN, source_id=c.source_id) for _ in range(10))
    r.register_behavior(P + 'fill', fill)
    r.register_card(CardDefinition(P + 'fill', 'Fill fixture', CardType.MINION, health=8,
        triggers=(TriggerSpec('battlecry_started', P + 'fill'),), metadata=META))
    r.validate(); r.freeze()
    return r


class NativeGeneratedWeaponComboTests(unittest.TestCase):
    def game(self, hand=(NOP, CARD), board=(), mode='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=(PLAIN,) * 6,
                        max_mana=30, mana=30, mana_cap=30),
            PlayerSetup(HERO, deck=(PLAIN,) * 6)), seed=193,
            generation_context=GenerationContext('k152', 'experimental')), registry('writer', mode))

    def play(self, g, cid, target=None):
        state = g.state
        eid = next(i for i in state.players[1].hand if state.entities[i].card_id == cid)
        position = len(state.players[1].board) if state.entities[eid].kind == CardType.MINION else None
        g.apply(PlayCard(1, eid, target_id=target, position=position))
        return eid

    def combo(self, g):
        self.play(g, NOP)
        return self.play(g, CARD)

    def choose(self, g, option='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def weapons(self, g, zone='hand'):
        state = g.state
        return [state.entities[i] for i in getattr(state.players[1], zone)
                if state.entities[i].kind == CardType.WEAPON]

    def check(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot()))
        writer, reader = registry('writer', mode), registry('reader', mode)
        self.assertIsNot(writer, reader)
        self.assertEqual(writer.fingerprint(), reader.fingerprint())
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)

    def rehash(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return saved

    def test_native_weapon_not_own_class_or_neutral_and_one_payment(self):
        g = self.game(); source = self.combo(g)
        weapons = self.weapons(g)
        self.assertEqual([(w.card_id, w.attack) for w in weapons], [(FOREIGN, 5)])
        self.assertEqual(g.state.players[1].mana, 26)
        self.assertEqual((len(g.state.battlecry_history), len(g.state.combo_history)), (1, 1))
        output = g.state.battlecry_weapon_outputs[0]
        self.assertEqual(output.created.entity_id, weapons[0].id)
        self.assertEqual(g.state.battlecry_history[output.battlecry_id - 1].source_id, source)
        self.check(g)

    def test_first_card_battlecry_does_not_invent_combo(self):
        g = self.game(hand=(CARD,)); self.play(g, CARD)
        self.assertEqual([w.attack for w in self.weapons(g)], [3])
        self.assertEqual(g.state.combo_history, [])
        self.check(g)

    def test_repeated_families_target_last_actual_weapon_only(self):
        g = self.game(board=(P + 'repeat',)); self.combo(g)
        self.assertEqual([w.attack for w in self.weapons(g)], [3, 7])
        self.assertEqual((len(g.state.battlecry_history), len(g.state.combo_history),
                          len(g.state.battlecry_weapon_outputs)), (2, 2, 2))
        self.assertEqual(g.state.players[1].mana, 26)
        self.check(g)

    def test_generated_physical_body_joins_its_own_battlecry_and_combo(self):
        g = self.game(hand=(NOP, CARD, P + 'replay'), board=(P + 'repeat',)); self.combo(g)
        self.play(g, P + 'replay')
        self.assertEqual([w.attack for w in self.weapons(g)], [3, 7, 3, 7])
        generated = [b for b in g.state.battlecry_history if b.physical_child_id is not None]
        combos = [c for c in g.state.combo_history if c.physical_child_id is not None]
        self.assertEqual((len(generated), len(combos), len(g.state.play_history)), (2, 2, 3))
        self.assertTrue(all(b.play_id is None for b in generated))
        self.assertEqual({b.physical_child_id for b in generated}, {c.physical_child_id for c in combos})
        self.check(g)

    def test_rewind_retires_old_binding_and_restores_one_current_output(self):
        g = self.game(hand=(NOP, P + 'rewind'))
        self.play(g, NOP); self.play(g, P + 'rewind')
        self.assertEqual([w.attack for w in self.weapons(g)], [5]); self.check(g)
        self.choose(g, 'retry')
        self.assertEqual([w.attack for w in self.weapons(g)], [5])
        self.assertEqual((len(g.state.play_history), len(g.state.battlecry_weapon_outputs)), (2, 1))
        self.assertEqual(g.state.players[1].mana, 26)
        self.check(g)

    def test_created_waiting_independent_restore_clone_and_replay(self):
        g = self.game(board=(P + 'wait',)); self.combo(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual([w.attack for w in self.weapons(g)], [3]); self.check(g)
        saved = g.snapshot(); other = Game.from_snapshot(saved, registry('reader'))
        self.choose(g); self.choose(other)
        self.assertEqual([w.attack for w in self.weapons(g)], [5])
        self.assertEqual(g.snapshot(), other.snapshot()); self.check(g)

    def test_combo_start_waiting_validates_captured_complete_prefix(self):
        g = self.game(board=(P + 'combo_wait',)); self.combo(g)
        self.check(g)
        saved = deepcopy(g.snapshot())
        def truncate(value):
            changed = 0
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'battlecry_weapon_outputs' and isinstance(item, list) and item:
                        value[key] = []; changed += 1
                    else:
                        changed += truncate(item)
            elif isinstance(value, list):
                changed += sum(truncate(item) for item in value)
            return changed
        self.assertGreater(truncate(saved['resolution_frame']), 0)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(self.rehash(saved), registry('reader'))
        self.choose(g); self.assertEqual([w.attack for w in self.weapons(g)], [5]); self.check(g)

    def test_original_source_death_does_not_cancel_accepted_combo(self):
        g = self.game(board=(P + 'kill',)); source = self.combo(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual([w.attack for w in self.weapons(g)], [5]); self.check(g)

    def test_moved_original_skips_without_buffing_decoy(self):
        g = self.game(board=(P + 'move',)); self.combo(g)
        self.assertEqual([(w.card_id, w.attack) for w in self.weapons(g)], [(OWN, 3)])
        self.assertEqual([(w.card_id, w.attack) for w in self.weapons(g, 'deck')], [(FOREIGN, 3)])
        self.check(g)

    def test_reentered_original_does_not_regain_original_residency(self):
        g = self.game(board=(P + 'reenter',)); self.combo(g)
        self.assertEqual([w.attack for w in self.weapons(g)], [3, 3]); self.check(g)

    def test_empty_complete_pool_is_rng_neutral_and_records_empty_output(self):
        g = self.game(mode='empty'); self.play(g, NOP)
        before = g.snapshot()['rng_state']; self.play(g, CARD)
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(self.weapons(g), [])
        self.assertIsNone(g.state.battlecry_weapon_outputs[0].created); self.check(g, 'empty')

    def test_full_hand_records_actual_burn_and_combo_does_not_rebind(self):
        g = self.game(board=(P + 'fill',)); self.combo(g)
        self.assertEqual(self.weapons(g), [])
        output = g.state.battlecry_weapon_outputs[0]
        self.assertEqual(output.created.zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[output.created.entity_id].attack, 3); self.check(g)

    def test_unknown_eligible_weapon_fails_atomically(self):
        g = self.game(mode='unknown'); self.play(g, NOP); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, CARD)
        self.assertEqual(g.snapshot(), before); self.check(g, 'unknown')

    def test_failed_choice_after_creation_rolls_back_to_exact_waiting(self):
        g = self.game(board=(P + 'fail_wait',)); self.combo(g)
        before = g.snapshot(); self.check(g)
        with self.assertRaises(ResolutionError): self.choose(g)
        self.assertEqual(g.snapshot(), before)

    def test_private_binding_and_rehashed_truncated_history_are_rejected(self):
        g = self.game(); self.combo(g)
        for player in (1, 2):
            dto = json.dumps(g.observe(player))
            self.assertNotIn('battlecry_weapon_outputs', dto)
            self.assertNotIn('battlecry_weapon_bound', dto)
        saved = g.snapshot(); saved['state']['battlecry_weapon_outputs'] = []
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(self.rehash(saved), registry('reader'))
        saved = g.snapshot(); saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry('reader'))

    def test_indirect_battlecry_creates_new_weapon_without_new_combo(self):
        g = self.game(hand=(NOP, CARD, P + 'trigger')); source = self.combo(g)
        self.play(g, P + 'trigger', target=source)
        self.assertEqual([w.attack for w in self.weapons(g)], [5, 3])
        self.assertEqual((len(g.state.battlecry_history), len(g.state.combo_history)), (2, 1))
        self.check(g)

    def test_complete_real_source_and_main_assembly(self):
        data = load_batch()
        self.assertEqual((len(data['cards']), len(data['official_observations'])), (1, 2))
        from hs_sim.cards.constructed import build_registry
        actual = build_registry(); actual.freeze()
        self.assertIn(CARD, actual.cards)
        self.assertEqual(asdict(actual.card(CARD)), asdict(registry('writer').card(CARD)))
        self.assertEqual((actual.card(CARD).cost, actual.card(CARD).attack, actual.card(CARD).health), (4, 5, 4))


if __name__ == '__main__':
    unittest.main()
