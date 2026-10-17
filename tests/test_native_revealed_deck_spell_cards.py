"""Actual single-deck revelation, original cost, native non-spell split damage."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import unittest

from hs_sim.cards.native_revealed_deck_spell_cards import CARD, BODY, load_batch, register_native_revealed_deck_spell_cards
from hs_sim.engine import (BattlecryRepeatSpec, CardClass, CardDefinition, CardMetadata,
    CardType, Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, RewindSpec, Scenario,
    SelectChoice, Zone)
from hs_sim.engine.deck_reveals import EVENT, RevealRandomDeckCard, deck_reveal_result
from hs_sim.engine.effects import ChoiceOption, Draw, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.generated_combo_repeats import PROFILE
from hs_sim.engine.model import CostSpec, LimitedTriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import BehaviorCall
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import ModifyStoredCost

P = 'k154.'
HERO, HIGH, LOW, PLAIN, ENEMY = (P + s for s in ('hero', 'high', 'low', 'plain', 'enemy'))
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.NONE, tribes=())


@lru_cache(maxsize=2)
def registry(role):
    assert role in ('writer', 'reader')
    r = Registry('k154-native-deck-reveal-v1')
    register_native_revealed_deck_spell_cards(r)
    r.register_card(CardDefinition(HERO, 'Mage fixture', CardType.HERO, health=30,
        metadata=CardMetadata(False, (CardClass.MAGE,), Rarity.NONE, tribes=())))
    r.register_card(CardDefinition(PLAIN, 'Plain fixture', CardType.MINION, cost=1, attack=1, health=3, metadata=META))
    r.register_behavior(P + 'noop', lambda c: ())
    for cid, cost in ((HIGH, 5), (LOW, 4)):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=P + 'noop', metadata=META))
    r.register_card(CardDefinition(ENEMY, 'Enemy fixture', CardType.MINION, attack=0, health=20, metadata=META))
    r.register_card(CardDefinition(P + 'stealth', 'Stealth fixture', CardType.MINION, health=20,
        keywords=(Keyword.STEALTH,), metadata=META))
    r.register_card(CardDefinition(P + 'spell_power', 'Spell Damage fixture', CardType.MINION,
        health=8, spell_damage=100, metadata=META))
    r.register_card(CardDefinition(P + 'repeat', 'Battlecry repeat fixture', CardType.MINION,
        health=8, battlecry_repeats=(BattlecryRepeatSpec(),), metadata=META))
    r.register_card(CardDefinition(P + 'rewind', 'Rewind alias fixture', CardType.MINION,
        cost=3, attack=3, health=4, keywords=(Keyword.REWIND,), rewind=RewindSpec(), battlecry=BODY, metadata=META))
    r.register_behavior(P + 'replay', lambda c: (ReplayWholeCards(c.player_id, c.source_id,
        WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1, kinds=(CardType.MINION,)),
        physical_profile=PROFILE, choices='player'),))
    r.register_card(CardDefinition(P + 'replay', 'Replay fixture', CardType.SPELL, on_play=P + 'replay', metadata=META))
    def fail(c): raise ResolutionError('deliberate K154 rollback')
    r.register_behavior(P + 'raise_failure', fail)
    r.register_trigger_condition(P + 'revealed', lambda c: deck_reveal_result(c.event) is not None)
    for action in ('wait', 'cost', 'draw', 'fail_wait', 'fail'):
        key = P + action
        def watch(c, action=action):
            result = deck_reveal_result(c.event)
            if action == 'cost':
                return () if result.card is None else (ModifyStoredCost(result.card.card, CostSpec(set_to=0), c.source_id),)
            if action == 'draw': return (Draw(c.player_id, 1, c.source_id),)
            if action == 'fail': return (InvokeBehavior(P + 'raise_failure', c.source_id, c.player_id),)
            effects = (InvokeBehavior(P + 'raise_failure', c.source_id, c.player_id),) if action == 'fail_wait' else ()
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', effects),), c.source_id),)
        r.register_behavior(key, watch)
        r.register_card(CardDefinition(key, key, CardType.MINION, health=8, metadata=META,
            limited_triggers=(LimitedTriggerSpec(EVENT, key, condition_id=P + 'revealed'),)))
    r.validate(); r.freeze()
    return r


class NativeRevealedDeckSpellTests(unittest.TestCase):
    def game(self, deck=(HIGH, PLAIN, LOW), enemy=(ENEMY,), board=(), hand=(CARD,), seed=3, enemy_deck=(LOW,) * 6):
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, deck=deck, board=board, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup(HERO, deck=enemy_deck, board=enemy)), seed=seed), registry('writer'))

    def play(self, g, cid=CARD):
        state = g.state
        eid = next(i for i in state.players[1].hand if state.entities[i].card_id == cid)
        position = len(state.players[1].board) if state.entities[eid].kind == CardType.MINION else None
        g.apply(PlayCard(1, eid, position=position))
        return eid

    def choose(self, g, option='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def reveals(self, g):
        return [deck_reveal_result(e) for e in g.events if e.kind == EVENT]

    def damage(self, g, player=2):
        return sum(g.state.entities[i].damage for i in g.state.players[player].board)

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        writer, reader = registry('writer'), registry('reader')
        self.assertIsNot(writer, reader); self.assertEqual(writer.fingerprint(), reader.fingerprint())
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        return other

    def rehash(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return saved

    def test_native_high_cost_one_payment_deck_order_and_nonspell_split(self):
        g = self.game(deck=(HIGH, PLAIN), board=(P + 'spell_power',))
        before = tuple(g.state.players[1].deck); source = self.play(g)
        result, = self.reveals(g)
        self.assertEqual((result.kind, result.card.cost, result.card.card.card_id), (CardType.SPELL, 5, HIGH))
        self.assertEqual(tuple(g.state.players[1].deck), before)
        self.assertEqual(self.damage(g), 5); self.assertEqual(self.damage(g, 1), 0)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 0)
        self.assertEqual(g.state.players[1].mana, 27)
        self.assertEqual((len(g.state.play_history), len(g.state.battlecry_history), len(g.state.cast_history)), (1, 1, 0))
        self.assertEqual(g.state.entities[source].card_id, CARD); self.portable(g)

    def test_low_cost_skips_reward_and_rng_only_samples_own_pool(self):
        g = self.game(deck=(LOW, PLAIN), enemy_deck=(HIGH,) * 20)
        expected = random.Random(3); expected.randrange(1)
        self.play(g)
        self.assertEqual(self.reveals(g)[0].card.cost, 4)
        self.assertEqual(self.damage(g), 0); self.assertEqual(g._rng.getstate(), expected.getstate())
        self.portable(g)

    def test_physical_duplicates_have_independent_weight_without_face_dedup(self):
        for seed in (0, 1, 5, 9):
            with self.subTest(seed=seed):
                g = self.game(deck=(HIGH, HIGH, PLAIN, LOW), enemy=(), seed=seed)
                ids = [i for i in g.state.players[1].deck if g.state.entities[i].kind == CardType.SPELL]
                rng = random.Random(seed); chosen = ids[rng.randrange(3)]
                self.play(g)
                self.assertEqual(self.reveals(g)[0].card.card.entity_id, chosen)
                self.assertEqual(g._rng.getstate(), rng.getstate())
        self.portable(g)

    def test_empty_spell_pool_no_reveal_randomness_damage_movement_or_fatigue(self):
        g = self.game(deck=(PLAIN,)); before = g.snapshot()['rng_state']; deck = tuple(g.state.players[1].deck)
        self.play(g)
        self.assertIsNone(self.reveals(g)[0].card); self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(tuple(g.state.players[1].deck), deck)
        self.assertEqual(g.state.players[1].fatigue, 0); self.assertEqual(self.damage(g), 0); self.portable(g)

    def test_accepted_original_cost_survives_later_local_cost_change(self):
        g = self.game(deck=(HIGH,), board=(P + 'cost',)); self.play(g)
        self.assertEqual(self.reveals(g)[0].card.cost, 5)
        from hs_sim.engine.costs import local_cost
        self.assertEqual(local_cost(g.state.entities[g.state.players[1].deck[0]])[0], 0)
        self.assertEqual(self.damage(g), 5); self.portable(g)

    def test_reveal_wait_restores_original_callback_without_resampling(self):
        g = self.game(deck=(HIGH,), board=(P + 'wait',)); self.play(g)
        self.assertEqual(self.damage(g), 0); other = self.portable(g)
        for game in (g, other): self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(self.damage(g), 5)
        self.assertEqual(len(self.reveals(g)), 1); self.portable(g)

    def test_both_players_see_face_and_cost_without_physical_handle_or_deck_position(self):
        g = self.game(deck=(HIGH,)); self.play(g)
        for player in (1, 2):
            row, = [e for e in g.player_events(player) if e['kind'] == EVENT]
            self.assertEqual(row['deck_reveal'], dict(kind='spell', card=dict(player_id=1, card_id=HIGH, cost=5)))
            self.assertIsNone(row['target'])
            self.assertEqual(set(row['deck_reveal']['card']), {'player_id', 'card_id', 'cost'})
            dto = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            for key in ('zone_epoch', 'entity_id', 'rng_state', 'resolution_frame'):
                self.assertNotIn('"' + key + '"', dto)
        self.portable(g)

    def test_revealed_deck_card_is_not_tracked_when_later_drawn(self):
        g = self.game(deck=(HIGH, PLAIN), board=(P + 'draw',)); self.play(g)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, HIGH)
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        self.assertEqual(self.damage(g), 5); self.portable(g)

    def test_repeated_battlecry_has_two_independent_reveals_and_one_payment(self):
        g = self.game(deck=(HIGH,), board=(P + 'repeat',)); self.play(g)
        self.assertEqual(len(self.reveals(g)), 2); self.assertEqual(self.damage(g), 10)
        self.assertEqual((len(g.state.play_history), len(g.state.battlecry_history), g.state.players[1].mana), (1, 2, 27))
        self.portable(g)

    def test_real_generated_body_reveals_without_fake_paid_play(self):
        g = self.game(deck=(HIGH,), hand=(CARD, P + 'replay')); self.play(g); self.play(g, P + 'replay')
        self.assertEqual(self.damage(g), 10); self.assertEqual(len(self.reveals(g)), 2)
        generated = [b for b in g.state.battlecry_history if b.physical_child_id is not None]
        self.assertEqual(len(generated), 1); self.assertIsNone(generated[0].play_id)
        self.assertEqual(len(g.state.play_history), 2); self.portable(g)

    def test_actual_rewind_restores_deck_reveal_reward_and_single_payment(self):
        g = self.game(deck=(HIGH,), hand=(P + 'rewind',)); self.play(g, P + 'rewind')
        self.assertEqual(self.damage(g), 5); self.portable(g); self.choose(g, 'retry')
        self.assertEqual(self.damage(g), 5); self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(g.state.players[1].mana, 27); self.portable(g)

    def test_random_damage_hits_stealth_minion_and_never_enemy_hero(self):
        g = self.game(deck=(HIGH,), enemy=(P + 'stealth',)); self.play(g)
        self.assertEqual(self.damage(g), 5)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 0); self.portable(g)

    def test_failed_reveal_listener_rolls_back_payment_rng_event_and_reward(self):
        g = self.game(deck=(HIGH,), board=(P + 'fail',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g)
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_failed_wait_choice_restores_exact_accepted_reveal(self):
        g = self.game(deck=(HIGH,), board=(P + 'fail_wait',)); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g)
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_forged_original_callback_cost_or_event_cannot_restore(self):
        g = self.game(deck=(HIGH,), board=(P + 'wait',)); self.play(g)
        bad = g.clone(); calls = [w for w in (*bad._frame.prefix, *bad._frame.continuation)
            if type(w) is BehaviorCall and w.context.event is not None and w.context.event.kind == EVENT
            and w.context.source_id == w.context.event.source_id]
        self.assertEqual(len(calls), 1)
        result = deck_reveal_result(calls[0].context.event)
        calls[0].context.state.entities[result.card.card.entity_id].base_cost = 1
        with self.assertRaises((ValueError, SnapshotError)):
            Game.from_snapshot(bad.snapshot(), registry('reader'))
        saved = g.snapshot(); saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry('reader'))

    def test_request_rejects_fake_kind_missing_callback_source_and_extra_targets(self):
        for kwargs in (dict(kind=CardType.WEAPON), dict(kind='spell'), dict(on_result='reward'), dict(target_id=1)):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError): RevealRandomDeckCard(1, **kwargs)

    def test_complete_real_source_main_assembly_and_full_printed_card(self):
        data = load_batch(); self.assertEqual((len(data['cards']), len(data['official_observations'])), (1, 2))
        from hs_sim.cards.constructed import build_registry
        actual = build_registry(); actual.freeze()
        self.assertEqual(asdict(actual.card(CARD)), asdict(registry('writer').card(CARD)))
        self.assertEqual((actual.card(CARD).cost, actual.card(CARD).attack, actual.card(CARD).health), (3, 3, 4))


if __name__ == '__main__': unittest.main()
