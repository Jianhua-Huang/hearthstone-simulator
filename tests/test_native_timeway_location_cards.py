"""Actual Conflux uses native offers, original selection copies and locations."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_timeway_location_cards import (
    DISCOVER_QUERY, FACES, load_batch, register_native_timeway_location_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, RewindSpec, Scenario,
    SelectChoice, SummonQuantitySpec, UseLocation, Zone)
from hs_sim.engine.discovery_summons import CopyDiscoveredCardToHand
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage, Destroy,
    InvokeBehavior, RequestChoice, Transform)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.locations import DestroyLocation, ModifyLocation
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import DiscoverFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause

P = 'k156.'
HERO, PLAIN, A, B, OWN, OTHER, SMALL, ALL, UNKNOWN = (
    P + n for n in ('hero', 'plain', 'dragon_a', 'dragon_b', 'priest', 'warrior', 'small', 'all', 'unknown'))
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.NONE, tribes=())
CTX = GenerationContext('k156', 'experimental')


@lru_cache(maxsize=8)
def registry(role, mode='normal'):
    assert role in ('writer', 'reader') and mode in ('normal', 'empty', 'unknown', 'other')
    r = Registry('k156-native-conflux-' + mode + '-v1')
    register_native_timeway_location_cards(r)
    r.register_card(CardDefinition(HERO, 'Priest fixture', CardType.HERO, health=30,
        metadata=CardMetadata(False, (CardClass.PRIEST,), Rarity.NONE, tribes=())))
    r.register_card(CardDefinition(PLAIN, 'Plain fixture', CardType.MINION, attack=1, health=3, metadata=META))
    for cid, cls, cost, tribes in ((A, CardClass.NEUTRAL, 5, ('dragon',)),
            (B, CardClass.NEUTRAL, 8, ('dragon',)), (OWN, CardClass.PRIEST, 6, ('dragon',)),
            (OTHER, CardClass.WARRIOR, 7, ('dragon',)), (SMALL, CardClass.NEUTRAL, 4, ('dragon',)),
            (ALL, CardClass.NEUTRAL, 5, ('all',)), (UNKNOWN, CardClass.NEUTRAL, 5, ('dragon',))):
        d = CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=2, health=4,
            metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=tribes))
        if cid != UNKNOWN: r.register_card(d)
        r.register_pool_card(PoolCard.from_definition(d))
    members = (SMALL,) if mode == 'empty' else (OTHER,) if mode == 'other' else (A, OWN, OTHER, SMALL, ALL)
    if mode == 'unknown': members = (*members, UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards', 'k156-v1', 'k156', 'experimental',
        tuple(PoolMember(cid) for cid in members), complete=True))
    r.register_card(CardDefinition(P + 'quantity', 'Quantity fixture', CardType.MINION, health=8,
        summon_quantities=(SummonQuantitySpec(),), metadata=META))
    r.register_behavior(P + 'lower', lambda c: (ModifyLocation(next(i for i in c.state.players[1].board
        if c.state.entities[i].card_id in FACES), durability=-2, source_id=c.source_id),))
    r.register_card(CardDefinition(P + 'lower', 'Durability fixture', CardType.SPELL, on_play=P + 'lower', metadata=META))
    def fail(c): raise ResolutionError('deliberate K156 rollback')
    r.register_behavior(P + 'raise_failure', fail)
    r.register_trigger_condition(P + 'chosen_a', lambda c: c.event.target_id is not None and
        c.state.entities[c.event.target_id].card_id == A)
    for action in ('wait', 'kill', 'transform', 'control', 'buff', 'terminal', 'destroy_source', 'copy_wait', 'copy_fail'):
        key = P + action
        def watch(c, action=action):
            target = c.event.target_id
            if action in ('wait', 'copy_wait'):
                return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id),)
            if action == 'kill': return (Destroy(target),)
            if action == 'transform': return (Transform(target, PLAIN),)
            if action == 'control': return (ChangeControl(target, 2),)
            if action == 'buff': return (Buff(target, 9, 9, c.source_id),)
            if action == 'terminal': return (Damage(c.state.players[2].hero_id, 100, c.source_id),)
            if action == 'destroy_source':
                return (DestroyLocation(c.state.discovery_summon_history[-1].spec.cause.source.entity_id, c.source_id),)
            return (InvokeBehavior(P + 'raise_failure', c.source_id, c.player_id),)
        r.register_behavior(key, watch)
        event = 'card_added_to_hand' if action.startswith('copy_') else 'minion_summoned'
        r.register_card(CardDefinition(key, key, CardType.MINION, health=8, metadata=META,
            limited_triggers=(LimitedTriggerSpec(event, key, condition_id=P + 'chosen_a'),)))
    r.register_behavior(P + 'rewind_body', lambda c: (DiscoverFromPool(c.player_id, 'constructed.cards',
        DISCOVER_QUERY, source_id=c.source_id, destination='board', cause=SummonCause.capture(c),
        copy_selected_to_hand=True),))
    r.register_card(CardDefinition(P + 'rewind', 'Public discovery rewind fixture', CardType.SPELL,
        cost=1, keywords=(Keyword.REWIND,), rewind=RewindSpec(), on_play=P + 'rewind_body', metadata=META))
    r.validate(); r.freeze()
    return r


class NativeTimewayLocationTests(unittest.TestCase):
    def game(self, face=FACES[2], board=(), hand=(), mode='normal', context=CTX, seed=112):
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, board=(() if face is None else (face,)) + board, hand=hand,
                deck=(PLAIN,) * 24, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup(HERO, deck=(PLAIN,) * 24)), seed=seed, generation_context=context), registry('writer', mode))

    def loc(self, g): return next(i for i in g.state.players[1].board if g.state.entities[i].card_id in FACES)
    def use(self, g):
        eid = self.loc(g); g.apply(UseLocation(1, eid)); return eid
    def play(self, g, cid):
        state = g.state; eid = next(i for i in state.players[1].hand if state.entities[i].card_id == cid)
        position = len(state.players[1].board) if state.entities[eid].kind == CardType.LOCATION else None
        g.apply(PlayCard(1, eid, position=position)); return eid
    def choose(self, g, option='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))
    def pick(self, g, cid=A):
        self.choose(g, next(o.id for o in g.state.pending_choice.options if o.card_id == cid))
    def hand(self, g, cid=A): return [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == cid]
    def ready(self, g, eid):
        for _ in range(8):
            if g.state.active_player == 1 and g.state.entities[eid].location_cooldown == 0: return
            g.apply(EndTurn(g.state.active_player))
        self.fail('Original location did not reopen')
    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); a, b = registry('writer', mode), registry('reader', mode)
        self.assertIsNot(a, b); self.assertEqual(a.fingerprint(), b.fingerprint())
        other = Game.from_snapshot(saved, b)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), b).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            for field in ('copy_acceptances', 'copy_selected_to_hand', 'discovery_summon_copy_started',
                          'discovery_summon_history', 'resolution_frame'):
                self.assertNotIn('"' + field + '"', public)
        return other
    def rehash(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return saved

    def test_01_original_offer_copy_and_location_cause_restore_without_cast_or_resampling(self):
        g = self.game(); source = self.use(g); root, = g.state.discovery_summon_history
        self.assertTrue({o.card_id for o in g.state.pending_choice.options} <= {A, B, OWN, ALL})
        self.assertEqual((root.spec.cause.origin, root.spec.cause.cast_id), ('card_effect', None))
        self.assertEqual(root.spec.cause.source.entity_id, source)
        other = self.portable(g); rng = g.snapshot()['rng_state']
        for game in (g, other): self.pick(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(len(self.hand(g)), 1); self.assertEqual(g.state.discovery_summon_history[0].copy_acceptances, (0,))
        self.assertFalse(g.state.cast_history); self.assertFalse(g.state.battlecry_history)
        self.assertEqual(g.state.entities[source].card_id, FACES[2]); self.portable(g)

    def test_02_waiting_entry_preserves_exact_owed_copy_and_rejects_crop_or_foreign_index(self):
        g = self.game(board=(P + 'wait',)); self.use(g); self.pick(g)
        self.assertFalse(self.hand(g)); self.assertEqual(g.state.discovery_summon_history[0].copy_acceptances, ())
        other = self.portable(g)
        for wrong in (False, True):
            bad = g.clone(); frame = bad._frame
            self.assertEqual(sum(type(w) is CopyDiscoveredCardToHand for w in (*frame.prefix, *frame.continuation)), 1)
            def change(work):
                return tuple(replace(w, index=1) if type(w) is CopyDiscoveredCardToHand and wrong else w
                    for w in work if wrong or type(w) is not CopyDiscoveredCardToHand)
            bad._frame = replace(frame, prefix=change(frame.prefix), continuation=change(frame.continuation))
            with self.assertRaises((ValueError, SnapshotError)):
                Game.from_snapshot(bad.snapshot(), registry('reader'))
        for game in (g, other): self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(self.hand(g)), 1); self.portable(g)

    def test_03_entry_changes_cannot_rebind_original_selected_base_recipe(self):
        for action in ('kill', 'transform', 'control', 'buff'):
            with self.subTest(action=action):
                g = self.game(board=(P + action,)); self.use(g); self.pick(g)
                card, = self.hand(g); self.assertEqual((card.base_attack, card.base_health, card.damage), (2, 4, 0))
                self.assertFalse(card.enchantments); self.portable(g)

    def test_04_full_board_still_copies_selected_card_once(self):
        g = self.game(board=(PLAIN,) * 6); self.use(g); self.pick(g)
        self.assertEqual(len(g.state.players[1].board), 7); self.assertEqual(len(self.hand(g)), 1)
        child = g.state.card_summon_history[-1]; self.assertTrue(all(d.entity is None for d in child.deliveries))
        self.portable(g)

    def test_05_full_hand_uses_ordinary_creation_overflow(self):
        g = self.game(hand=(PLAIN,) * 10); source = self.use(g); self.pick(g)
        self.assertEqual(len(g.state.players[1].hand), 10); self.assertFalse(self.hand(g))
        created = [e for e in g.events if e.kind == 'card_created' and e.source_id == source]
        self.assertEqual(len(created), 1); self.assertEqual(g.state.entities[created[0].target_id].zone, Zone.GRAVEYARD)
        self.portable(g)

    def test_06_copy_acquisition_wait_keeps_one_acceptance_and_private_hand(self):
        g = self.game(board=(P + 'copy_wait',)); self.use(g); self.pick(g)
        self.assertEqual(len(self.hand(g)), 1); self.assertEqual(g.state.discovery_summon_history[0].copy_acceptances, (0,))
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        other = self.portable(g)
        for game in (g, other): self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(self.hand(g)), 1); self.portable(g)

    def test_07_copy_acquisition_failure_rolls_back_original_choice_delivery_and_rng(self):
        g = self.game(board=(P + 'copy_fail',)); self.use(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g)
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_08_entry_terminal_does_not_run_unreached_copy(self):
        g = self.game(board=(P + 'terminal',)); self.use(g); self.pick(g)
        self.assertNotEqual(g.state.status, 'playing'); self.assertFalse(self.hand(g))
        self.assertEqual((g.state.discovery_summon_history[0].status, g.state.discovery_summon_history[0].copy_acceptances), ('interrupted', ()))
        self.portable(g)

    def test_09_past_any_class_and_present_current_class_are_distinct_original_queries(self):
        g = self.game(face=FACES[0], mode='other'); source = self.use(g)
        self.assertTrue(any(g.state.entities[i].card_id == OTHER for i in g.state.players[1].board))
        self.assertEqual(g.state.entities[source].card_id, FACES[1]); self.portable(g, 'other')
        g = self.game(face=FACES[1], mode='other'); rng = g.snapshot()['rng_state']; source = self.use(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(g.state.entities[source].card_id, FACES[2]); self.portable(g, 'other')

    def test_10_paid_three_uses_keep_identity_cooldown_and_last_use_body(self):
        g = self.game(face=None, hand=(FACES[0],)); source = self.play(g, FACES[0])
        self.assertEqual(g.state.players[1].mana, 23)
        for index in range(3):
            self.ready(g, source); self.use(g)
            if g.state.pending_choice: self.pick(g, g.state.pending_choice.options[0].card_id)
            e = g.state.entities[source]
            self.assertEqual(e.durability, 2-index)
            if index < 2: self.assertEqual((e.card_id, e.location_cooldown), (FACES[index+1], 2))
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.discovery_summon_history), 2)
        self.assertEqual(sum(g.state.entities[i].card_id != PLAIN for i in g.state.players[1].hand), 1)
        self.assertFalse(g.state.cast_history); self.portable(g)

    def test_11_complete_empty_pools_advance_without_choice_copy_or_rng(self):
        for index, face in enumerate(FACES):
            g = self.game(face=face, mode='empty'); rng = g.snapshot()['rng_state']; source = self.use(g)
            self.assertIsNone(g.state.pending_choice); self.assertEqual(g.snapshot()['rng_state'], rng)
            self.assertEqual(g.state.entities[source].card_id, FACES[min(index+1, 2)])
            self.assertFalse(g.state.players[1].hand); self.portable(g, 'empty')

    def test_12_unknown_eligible_and_missing_context_restore_spent_location(self):
        for mode, context in (('unknown', CTX), ('normal', None)):
            for face in (FACES[0], FACES[2]):
                g = self.game(face=face, mode=mode, context=context); before = g.snapshot()
                with self.assertRaises((ValueError, ResolutionError)): self.use(g)
                self.assertEqual(g.snapshot(), before)

    def test_13_last_use_death_keeps_accepted_copy_and_original_cause(self):
        g = self.game(hand=(P + 'lower',)); source = self.loc(g); self.play(g, P + 'lower'); self.use(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD); self.portable(g); self.pick(g)
        self.assertEqual(len(self.hand(g)), 1); self.assertEqual(g.state.discovery_summon_history[0].spec.cause.source.entity_id, source)
        self.portable(g)

    def test_14_rehashed_missing_acceptance_receipt_and_old_schema_reject(self):
        g = self.game(); self.use(g); self.pick(g)
        for events in (False, True):
            saved = g.snapshot()
            if events: saved['events'] = [e for e in saved['events'] if e['kind'] != 'discovery_summon_copy_started']
            else: saved['state']['discovery_summon_history'][0]['copy_acceptances'] = []
            with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(saved), registry('reader'))
        saved = g.snapshot(); saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry('reader'))

    def test_15_finite_copy_declaration_preserves_ordinary_default(self):
        g = self.game(); self.use(g); spec = g.state.discovery_summon_history[0].spec
        for change in (dict(destination='hand'), dict(cause=None), dict(source_id=None), dict(discoveries=2),
                dict(copy_selected_to_hand=1), dict(freeze_summoned=True), dict(delivery='after_all'),
                dict(query=replace(spec.query, collectible=False))):
            with self.subTest(change=change):
                with self.assertRaises(ValueError): replace(spec, **change)
        self.assertIs(DiscoverFromPool(1, 'constructed.cards').copy_selected_to_hand, False)

    def test_16_quantity_extras_do_not_multiply_original_selected_hand_copy(self):
        g = self.game(board=(P + 'quantity',)); self.use(g); self.pick(g)
        self.assertEqual(sum(g.state.entities[i].card_id == A for i in g.state.players[1].board), 2)
        self.assertEqual(len(self.hand(g)), 1); self.portable(g)

    def test_17_present_destroyed_during_entry_does_not_advance_replacement_or_cancel_body(self):
        g = self.game(face=FACES[1], board=(P + 'destroy_source',)); source = self.use(g); self.pick(g)
        self.assertEqual((g.state.entities[source].zone, g.state.entities[source].card_id), (Zone.GRAVEYARD, FACES[1]))
        self.assertFalse(self.hand(g)); self.portable(g)

    def test_18_public_discovery_rewind_retires_copy_and_repeats_original_offer(self):
        g = self.game(face=None, hand=(P + 'rewind',)); self.play(g, P + 'rewind'); self.pick(g)
        self.assertEqual(len(self.hand(g)), 1); self.portable(g); self.choose(g, 'retry')
        self.assertFalse(self.hand(g)); self.portable(g); self.pick(g)
        self.assertEqual(len(self.hand(g)), 1); self.assertEqual(g.state.players[1].mana, 29); self.portable(g)

    def test_19_full_raw_primary_faces_and_central_definitions_match(self):
        data = load_batch(); self.assertEqual((len(data['cards']), len(data['official_observations'])), (3, 6))
        from hs_sim.cards.constructed import build_registry
        r = build_registry(); r.freeze()
        for cid in FACES:
            self.assertEqual(asdict(r.card(cid)), asdict(registry('writer').card(cid)))
            self.assertEqual((r.card(cid).cost, r.card(cid).durability), (7, 3))


if __name__ == '__main__': unittest.main()
