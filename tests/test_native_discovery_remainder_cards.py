"""Original Vendor offers survive acquisition and shuffle as one actual batch."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_discovery_remainder_cards import CARD, BODY, QUERY, load_batch, register_native_discovery_remainder_cards
from hs_sim.engine import (BattlecryRepeatSpec, CardClass, CardDefinition, CardMetadata, CardType,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, RewindSpec, Scenario, SelectChoice, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.discovery_remainders import ACCEPTED, FINISHED, ShuffleDiscoveryRemainder
from hs_sim.engine.effects import AddToHand, ChoiceOption, Damage, Destroy, Draw, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import DiscoverFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, MoveCard

P = 'k158.'
HERO, PLAIN, A, B, OWN, OTHER, COMMON, UNKNOWN = (
    P + n for n in ('hero', 'plain', 'legend_a', 'legend_b', 'shaman', 'warrior', 'common', 'unknown'))
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.NONE, tribes=())
CTX = GenerationContext('k158', 'experimental')


@lru_cache(maxsize=10)
def registry(role, mode='normal'):
    assert role in ('writer', 'reader') and mode in ('normal', 'empty', 'one', 'two', 'unknown')
    r = Registry('k158-native-vendor-' + mode + '-v1')
    register_native_discovery_remainder_cards(r)
    r.register_card(CardDefinition(HERO, 'Shaman fixture', CardType.HERO, health=30,
        metadata=CardMetadata(False, (CardClass.SHAMAN,), Rarity.NONE, tribes=())))
    r.register_card(CardDefinition(PLAIN, 'Plain fixture', CardType.MINION, cost=1, attack=1, health=5, metadata=META))
    for cid, cls, rarity in ((A, CardClass.NEUTRAL, Rarity.LEGENDARY), (B, CardClass.NEUTRAL, Rarity.LEGENDARY),
            (OWN, CardClass.SHAMAN, Rarity.LEGENDARY), (OTHER, CardClass.WARRIOR, Rarity.LEGENDARY),
            (COMMON, CardClass.NEUTRAL, Rarity.COMMON), (UNKNOWN, CardClass.NEUTRAL, Rarity.LEGENDARY)):
        d = CardDefinition(cid, cid, CardType.MINION, cost=5, attack=2, health=4,
            metadata=CardMetadata(True, (cls,), rarity, tribes=()))
        if cid != UNKNOWN: r.register_card(d)
        r.register_pool_card(PoolCard.from_definition(d))
    members = (OTHER, COMMON) if mode == 'empty' else (A,) if mode == 'one' else (A, B) if mode == 'two' else (A, B, OWN, OTHER, COMMON)
    if mode == 'unknown': members = (*members, UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards', 'k158-v1', 'k158', 'experimental',
        tuple(PoolMember(cid) for cid in members), complete=True))
    r.register_card(CardDefinition(P + 'repeat', 'Battlecry repetition fixture', CardType.MINION,
        health=5, battlecry_repeats=(BattlecryRepeatSpec(),), metadata=META))
    r.register_card(CardDefinition(P + 'rewind', 'Public ordinary discovery Retry fixture', CardType.SPELL,
        cost=1, keywords=(Keyword.REWIND,), rewind=RewindSpec(), on_play=BODY, metadata=META))
    r.register_behavior(P + 'summon', lambda c: (SummonByCard(c.player_id,
        (SummonEntryMaterial(CARD),), SummonCause.capture(c)),))
    r.register_card(CardDefinition(P + 'summon', 'Natural summon fixture', CardType.SPELL, on_play=P + 'summon', metadata=META))
    def fail(c): raise ResolutionError('deliberate K158 rollback')
    r.register_behavior(P + 'raise_failure', fail)
    r.register_trigger_condition(P + 'is_a', lambda c: c.event.target_id is not None and c.state.entities[c.event.target_id].card_id == A)
    r.register_trigger_condition(P + 'vendor_choice', lambda c: c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == CARD)
    for action in ('wait', 'cycle', 'source_death', 'fill', 'deck_wait', 'deck_fail', 'terminal', 'nested'):
        key = P + action
        def watch(c, action=action):
            if action in ('wait', 'deck_wait'):
                return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id),)
            if action == 'cycle':
                return (MoveCard(CardReference.capture(c.state.entities[c.event.target_id]), c.player_id,
                    Zone.DECK, position='top', source_id=c.source_id), Draw(c.player_id, 1, c.source_id))
            if action == 'source_death': return (Destroy(c.event.source_id),)
            if action == 'nested': return (InvokeBehavior(BODY, c.source_id, c.player_id),)
            if action == 'fill': return (AddToHand(c.player_id, PLAIN, c.source_id),)
            if action == 'terminal': return (Damage(c.state.players[2].hero_id, 100, c.source_id),)
            return (InvokeBehavior(P + 'raise_failure', c.source_id, c.player_id),)
        r.register_behavior(key, watch)
        event = 'choice_selected' if action == 'fill' else 'card_added_to_deck' if action.startswith('deck_') else 'card_added_to_hand'
        condition = P + 'vendor_choice' if action == 'fill' else 'always' if action.startswith('deck_') else P + 'is_a'
        r.register_card(CardDefinition(key, key, CardType.MINION, health=5, metadata=META,
            limited_triggers=(LimitedTriggerSpec(event, key, condition_id=condition),)))
    r.validate(); r.freeze()
    return r


class NativeDiscoveryRemainderTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(), mode='normal', context=CTX):
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=(PLAIN,) * 4, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup(HERO, deck=(PLAIN,) * 4)), seed=81, generation_context=context), registry('writer', mode))
    def play(self, g, cid=CARD):
        state = g.state; eid = next(i for i in state.players[1].hand if state.entities[i].card_id == cid)
        position = len(state.players[1].board) if state.entities[eid].kind == CardType.MINION else None
        g.apply(PlayCard(1, eid, position=position)); return eid
    def choose(self, g, option='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))
    def pick(self, g, cid=A): self.choose(g, next(o.id for o in g.state.pending_choice.options if o.card_id == cid))
    def works(self, g, kind=ACCEPTED):
        return [FrameCodec(g.mechanics, g.registry).decode(json.loads(dict(e.data)['receipt'])) for e in g.events if e.kind == kind]
    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); a, b = registry('writer', mode), registry('reader', mode)
        self.assertIsNot(a, b); self.assertEqual(a.fingerprint(), b.fingerprint())
        other = Game.from_snapshot(saved, b)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), b).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            for field in ('receipt', ACCEPTED, FINISHED, 'offered_card_ids', 'ShuffleDiscoveryRemainder'):
                self.assertNotIn('"' + field + '"', public)
        return other
    def rehash(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return saved

    def test_01_native_actual_offer_creates_selected_and_one_original_remainder_shuffle(self):
        g = self.game(hand=(CARD, A)); old = g.state.players[1].hand[1]; source = self.play(g)
        offered = tuple(o.card_id for o in g.state.pending_choice.options); self.assertEqual(set(offered), {A, B, OWN})
        self.assertEqual(g.state.players[1].mana, 29); other = self.portable(g)
        for game in (g, other): self.pick(game)
        self.assertEqual(g.snapshot(), other.snapshot()); work, = self.works(g)
        self.assertEqual(work.discovery.offered_card_ids, offered); self.assertNotEqual(work.created.entity_id, old)
        self.assertEqual(g.state.entities[work.created.entity_id].card_id, A)
        row, = g.state.deck_shuffle_history; self.assertEqual((row.actor_id, row.player_id, row.declared_count), (1, 1, 2))
        inserted = [e for e in g.events if e.kind == 'card_added_to_deck' and e.source_id == source]
        self.assertEqual(tuple(g.state.entities[e.target_id].card_id for e in inserted), tuple(c for c in offered if c != A))
        self.assertEqual(len(self.works(g, FINISHED)), 1); self.portable(g)
        enemy = json.dumps(g.observe(2)) + json.dumps(g.player_events(2))
        for cid in (A, B, OWN): self.assertNotIn(cid, enemy)

    def test_02_acquisition_wait_restores_original_offer_before_shuffle(self):
        g = self.game(board=(P + 'wait',)); self.play(g); self.pick(g)
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(g.state.deck_shuffle_history)
        self.assertEqual(len(self.works(g)), 1); other = self.portable(g)
        for game in (g, other): self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(g.state.deck_shuffle_history), 1); self.portable(g)

    def test_03_cropped_or_reordered_original_remainder_cannot_restore(self):
        g = self.game(board=(P + 'wait',)); self.play(g); self.pick(g)
        for wrong in (False, True):
            bad = g.clone(); frame = bad._frame
            self.assertEqual(sum(type(w) is ShuffleDiscoveryRemainder for w in (*frame.prefix, *frame.continuation)), 1)
            def change(work):
                return tuple(replace(w, discovery=replace(w.discovery, offered_card_ids=tuple(reversed(w.discovery.offered_card_ids))))
                    if type(w) is ShuffleDiscoveryRemainder and wrong else w for w in work
                    if wrong or type(w) is not ShuffleDiscoveryRemainder)
            bad._frame = replace(frame, prefix=change(frame.prefix), continuation=change(frame.continuation))
            with self.assertRaises((ValueError, SnapshotError)): Game.from_snapshot(bad.snapshot(), registry('reader'))

    def test_04_selected_reentry_and_source_death_do_not_change_unselected_recipes(self):
        for action in ('cycle', 'source_death'):
            g = self.game(board=(P + action,)); source = self.play(g); offered = tuple(o.card_id for o in g.state.pending_choice.options)
            self.pick(g)
            work, = self.works(g); self.assertEqual(work.discovery.offered_card_ids, offered)
            self.assertEqual(g.state.deck_shuffle_history[-1].declared_count, 2)
            if action == 'source_death': self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
            self.portable(g)

    def test_05_full_hand_burns_selected_but_keeps_two_unselected_cards(self):
        g = self.game(hand=(CARD,) + (PLAIN,) * 9, board=(P + 'fill',)); self.play(g); self.pick(g)
        work, = self.works(g); self.assertEqual(work.created.zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[work.created.entity_id].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand), 10); self.assertEqual(g.state.deck_shuffle_history[-1].declared_count, 2)
        self.portable(g)

    def test_06_semantic_shuffle_is_complete_before_its_first_insertion_reaction_wait(self):
        g = self.game(board=(P + 'deck_wait',)); source = self.play(g); self.pick(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len([e for e in g.events if e.kind == 'card_added_to_deck' and e.source_id == source]), 2)
        self.assertEqual(len(self.works(g, FINISHED)), 1); other = self.portable(g)
        for game in (g, other): self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_07_insertion_reaction_failure_restores_original_choice_creation_shuffle_and_rng(self):
        g = self.game(board=(P + 'deck_fail',)); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g)
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_08_acquisition_terminal_does_not_execute_unreached_shuffle(self):
        g = self.game(board=(P + 'terminal',)); self.play(g); self.pick(g)
        self.assertNotEqual(g.state.status, 'playing'); self.assertEqual(len(self.works(g)), 1)
        self.assertFalse(g.state.deck_shuffle_history); self.assertFalse(self.works(g, FINISHED)); self.portable(g)

    def test_09_actual_retry_retires_first_outcome_and_keeps_final_original_remainder(self):
        g = self.game(hand=(P + 'rewind',)); self.play(g, P + 'rewind'); self.pick(g); self.portable(g)
        self.choose(g, 'retry'); self.assertFalse(g.state.deck_shuffle_history); self.portable(g); self.pick(g)
        self.assertEqual(len(g.state.deck_shuffle_history), 1); self.assertEqual(g.state.players[1].mana, 29); self.portable(g)

    def test_10_repeat_battlecries_have_independent_real_choices_and_one_payment(self):
        g = self.game(board=(P + 'repeat',)); self.play(g); self.pick(g); self.portable(g); self.pick(g, B)
        self.assertEqual(len(g.state.deck_shuffle_history), 2)
        self.assertEqual([r.declared_count for r in g.state.deck_shuffle_history], [2, 2])
        self.assertEqual(g.state.players[1].mana, 29); self.assertEqual(len({w.discovery.choice_result.choice.id for w in self.works(g)}), 2)
        self.portable(g)

    def test_11_empty_and_short_complete_pools_preserve_actual_offer_size(self):
        g = self.game(mode='empty'); rng = g.snapshot()['rng_state']; self.play(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.snapshot()['rng_state'], rng); self.portable(g, 'empty')
        for mode, count in (('one', 0), ('two', 1)):
            g = self.game(mode=mode); self.play(g); rng = g.snapshot()['rng_state']; self.pick(g)
            if count: self.assertEqual(g.state.deck_shuffle_history[0].declared_count, count)
            else: self.assertFalse(g.state.deck_shuffle_history); self.assertEqual(g.snapshot()['rng_state'], rng)
            self.portable(g, mode)

    def test_12_unknown_eligible_or_missing_context_rolls_back_native_payment(self):
        for mode, context in (('unknown', CTX), ('normal', None)):
            g = self.game(mode=mode, context=context); before = g.snapshot()
            with self.assertRaises((ValueError, ResolutionError)): self.play(g)
            self.assertEqual(g.snapshot(), before)

    def test_13_rehashed_missing_receipts_or_wrong_shuffle_identity_reject(self):
        g = self.game(); self.play(g); self.pick(g)
        for kind in (ACCEPTED, FINISHED):
            saved = g.snapshot(); saved['events'] = [e for e in saved['events'] if e['kind'] != kind]
            with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(saved), registry('reader'))
        saved = g.snapshot(); event = next(e for e in saved['events'] if e['kind'] == FINISHED)
        event['data']['shuffle_id'] += 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(saved), registry('reader'))
        saved = g.snapshot(); saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry('reader'))

    def test_14_finite_declaration_preserves_plain_default_and_rejects_losing_wrapper(self):
        spec = DiscoverFromPool(1, 'constructed.cards', QUERY, source_id=1, shuffle_unselected_into_deck=True)
        for change in (dict(destination='board'), dict(source_id=None), dict(discoveries=2), dict(delivery='after_all'),
                dict(shuffle_unselected_into_deck=1), dict(query=replace(QUERY, rarities=())), dict(copy_selected_to_hand=True)):
            with self.subTest(change=change):
                with self.assertRaises(ValueError): replace(spec, **change)
        from hs_sim.engine.hand_choice_followups import validate_request
        with self.assertRaises(ValueError): validate_request(spec)
        self.assertIs(DiscoverFromPool(1, 'constructed.cards').shuffle_unselected_into_deck, False)

    def test_15_natural_summon_has_no_battlecry_or_pool_requirement(self):
        g = self.game(hand=(P + 'summon',), context=None); self.play(g, P + 'summon')
        self.assertIsNone(g.state.pending_choice); self.assertFalse(self.works(g)); self.assertFalse(g.state.deck_shuffle_history)
        self.assertEqual(sum(g.state.entities[i].card_id == CARD for i in g.state.players[1].board), 1); self.portable(g)

    def test_16_complete_raw_primary_faces_and_central_definition_are_exact(self):
        data = load_batch(); self.assertEqual((len(data['cards']), len(data['official_observations'])), (1, 2))
        from hs_sim.cards.constructed import build_registry
        r = build_registry(); r.freeze()
        self.assertEqual(asdict(r.card(CARD)), asdict(registry('writer').card(CARD)))
        self.assertEqual((r.card(CARD).cost, r.card(CARD).attack, r.card(CARD).health), (1, 1, 2))

    def test_17_nested_discovery_keeps_independent_owed_remainders_in_execution_order(self):
        g = self.game(board=(P + 'nested',)); source = self.play(g); self.pick(g)
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(g.state.deck_shuffle_history)
        other = self.portable(g)
        for game in (g, other): self.pick(game, B)
        self.assertEqual(g.snapshot(), other.snapshot())
        accepted = [w.discovery.choice_result.choice.id for w in self.works(g)]
        finished = [w.discovery.choice_result.choice.id for w in self.works(g, FINISHED)]
        self.assertEqual(finished, list(reversed(accepted)))
        self.assertEqual(g.state.deck_shuffle_history[-1].source.entity_id, source); self.portable(g)


if __name__ == '__main__': unittest.main()
