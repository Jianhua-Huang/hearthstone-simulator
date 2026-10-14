"""Same-turn physical-card followups retain the original private discovery offer."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, CounterMinion, CounterSpell, DiscoverFromPool, DiscoverForPlayFollowup, EndTurn, Game, IllegalAction,
    GenerationContext, Keyword, PlayCard, PlayerSetup, PoolCard, PoolDefinition,
    PoolMember, PoolQuery, Rarity, ResolutionError, Scenario, SecretSpec, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import AddToHand, ChoiceOption, Damage, Draw, ModifyCost, RequestChoice, RevealHandCard, Summon
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, ChooseFromZone, CopyCard, DestroyDeckCard, MoveCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

MAP = 'TLC_442'
MINIONS = ('CORE_LOEA10_3', 'CS2_168', 'CS2_173')
CONTEXT = GenerationContext('hand-followup-test', 'experimental')
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/hand-choice-followups.json'
PIN = '3bc54efa2a24f5bee2dbe8d037ea50c69267560c02cbc1f34fb438aa49a0fabc'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN: raise ValueError('Complete Map evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original Map record changed')
    return {row['id']: row['data'] for row in raw['records']}


def registry(scripts=(), *, members=MINIONS, observers=(), counter=None, unadapted=False):
    r = opening_registry(); rows = evidence()
    for cid in MINIONS:
        row = rows[cid]
        definition = CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'],
            keywords=(Keyword.CHARGE,) if cid == 'CS2_173' else (),
            metadata=metadata(tribes=('murloc',), rarity=Rarity.COMMON if cid == MINIONS[0] else Rarity.FREE))
        r.register_card(definition); r.register_pool_card(PoolCard.from_definition(definition))
    if unadapted:
        r.register_pool_card(PoolCard.from_definition(CardDefinition('probe.missing', 'Unadapted candidate',
            CardType.MINION, health=1, metadata=metadata(tribes=('murloc',)))))
    r.register_pool(PoolDefinition('murlocs', 'v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid) for cid in members)))
    r.register_behavior('map', lambda c: (DiscoverForPlayFollowup(DiscoverFromPool(c.player_id, 'murlocs',
        PoolQuery(tribes_any=('murloc',), class_mode='current'), source_id=c.source_id)),))
    r.register_card(CardDefinition(MAP, rows[MAP]['name'], CardType.SPELL, cost=rows[MAP]['cost'],
        on_play='map', metadata=metadata(CardClass.PALADIN)))
    # Explicit synthetic Paladin scenario substrate, not the real class power.
    r.register_card(CardDefinition('probe.paladin.power', 'Synthetic Paladin power', CardType.HERO_POWER,
        cost=2, on_use='power', metadata=metadata(CardClass.PALADIN, collectible=False)))
    r.register_card(CardDefinition('probe.paladin.hero', 'Synthetic Paladin hero', CardType.HERO, health=30,
        initial_hero_power='probe.paladin.power', metadata=metadata(CardClass.PALADIN, collectible=False)))
    for name, event, callback in observers:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.MINION, health=4,
            triggers=(TriggerSpec(event, name),), metadata=metadata()))
    if counter:
        r.register_secret_condition('probe.counter', lambda c: c.window is not None and
            c.window.kind == counter and not c.window.countered and c.window.player_id != c.player_id)
        effect = CounterMinion if counter == 'minion' else CounterSpell
        r.register_behavior('probe.counter', lambda c: (effect(c.window.id),))
        r.register_card(CardDefinition('probe.counter', 'Synthetic counter probe', CardType.SPELL,
            keywords=(Keyword.SECRET,), secret=SecretSpec('probe.counter',
                ('minion_counter_check' if counter == 'minion' else 'card_committed',),
                'probe.counter', 'probe.counter'), metadata=metadata(collectible=False)))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    return r


class HandChoiceFollowupTests(unittest.TestCase):
    def setUp(self): self.scripts = []; self.options = {}
    def script(self, name, callback): self.scripts.append((name, callback))
    def watch(self, name, event, callback):
        self.options.setdefault('observers', []).append((name, event, callback))
    def game(self, hand=(MAP,), *, deck=(), enemy_hand=(), board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('probe.paladin.hero', hand=hand, deck=deck, board=board, mana=10, max_mana=10),
            PlayerSetup('mage.hero', hand=enemy_hand, mana=10, max_mana=10)), seed=86,
            generation_context=CONTEXT), registry(self.scripts, **self.options))
    def entity(self, g, cid):
        return next(g.state.entities[i] for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id == cid)
    def play(self, g, cid):
        source = self.entity(g, cid).id; g.apply(PlayCard(g.state.active_player, source)); return source
    def select(self, g, card=None):
        choice = g.state.pending_choice
        option = next(o for o in choice.options if card is None or o.card_id == card)
        g.apply(SelectChoice(choice.player_id, choice.id, (option.id,))); return option.card_id
    def ref(self, c, cid, *, zone=Zone.HAND, player=1):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[player], zone.value)
            if c.state.entities[i].card_id == cid))
    def arm(self, g, card=MINIONS[0]):
        self.play(g, MAP); self.select(g, card); return g.state.hand_choice_followups[-1].initial_entity_id
    def continue_probe(self, g):
        choice = g.state.pending_choice; self.assertEqual([o.id for o in choice.options], ['ok'])
        g.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))
    def reject(self, snapshot):
        snapshot['state_hash'] = canonical_hash({k:v for k,v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot, registry(self.scripts, **self.options))
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored

    def test_play_selected_card_offers_only_original_unselected_cards(self):
        g = self.game(); self.play(g, MAP)
        offered = [o.card_id for o in g.state.pending_choice.options]
        selected = self.select(g); self.play(g, selected)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options], [c for c in offered if c != selected])
        self.select(g); self.assertEqual(g.state.players[1].mana, 9-evidence()[selected]['cost']); self.portable(g)

    def test_complete_map_and_three_necessary_murloc_records(self):
        rows = evidence(); self.assertEqual(set(rows), {MAP, *MINIONS})
        self.assertEqual((rows[MAP]['cost'], rows[MAP]['tags']['CLASS']), (1, 5))
        self.assertIn('If you play it this turn', rows[MAP]['text_en'])
        self.assertIn('pick one of the others', rows[MAP]['text_en'])
        self.assertEqual([(rows[c]['cost'], rows[c]['attack'], rows[c]['health']) for c in MINIONS],
            [(0, 1, 1), (1, 2, 1), (2, 2, 1)])
        self.assertEqual([rows[c]['tags']['CARDRACE'] for c in MINIONS], [14]*3)
        self.assertEqual(rows[MINIONS[2]]['tags']['CHARGE'], 1)

    def test_initial_choice_restores_with_independent_registry(self):
        g = self.game(); self.play(g, MAP); other = self.portable(g)
        for match in (g, other): self.select(match, MINIONS[0])
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.hand_choice_followups[0].status, 'armed')

    def test_armed_record_and_reward_choice_restore_without_resampling(self):
        g = self.game(); eid = self.arm(g); other = self.portable(g)
        for match in (g, other): match.apply(PlayCard(1, eid))
        self.assertEqual(g.snapshot(), other.snapshot()); waiting = self.portable(g)
        for match in (g, waiting): self.select(match, MINIONS[1])
        self.assertEqual(g.snapshot(), waiting.snapshot())
        self.assertEqual(g.state.hand_choice_followups[0].status, 'completed')

    def test_second_selection_does_not_touch_rng_and_pays_only_for_plays(self):
        g = self.game(); self.arm(g, MINIONS[2]); rng = g.snapshot()['rng_state']
        self.play(g, MINIONS[2]); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.select(g, MINIONS[0]); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(g.state.players[1].mana, 7)
        self.assertEqual([p.card_id for p in g.state.play_history], [MAP, MINIONS[2]])

    def test_same_printed_card_already_in_hand_cannot_consume_followup(self):
        g = self.game((MAP, MINIONS[0])); old = self.entity(g, MINIONS[0]).id
        selected = self.arm(g); self.assertNotEqual(selected, old)
        g.apply(PlayCard(1, old)); self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.hand_choice_followups[0].status, 'armed')
        g.apply(PlayCard(1, selected)); self.assertIsNotNone(g.state.pending_choice)

    def test_current_and_base_hand_copies_do_not_acquire_original_followup(self):
        for mode in ('current', 'base'):
            with self.subTest(mode=mode):
                self.scripts = []
                self.script('copy', lambda c, mode=mode: (CopyCard(self.ref(c, MINIONS[0]), 1, mode=mode),))
                g = self.game((MAP, 'copy')); original = self.arm(g); self.play(g, 'copy')
                copy = next(i for i in g.state.players[1].hand if i != original)
                g.apply(PlayCard(1, copy)); self.assertIsNone(g.state.pending_choice)
                self.assertEqual(g.state.hand_choice_followups[0].status, 'armed')
                g.apply(PlayCard(1, original)); self.assertIsNotNone(g.state.pending_choice)

    def test_leaving_and_returning_to_hand_loses_original_residence(self):
        self.script('away', lambda c: (MoveCard(self.ref(c, MINIONS[0]), 1, Zone.DECK, 'top'), Draw(1)))
        g = self.game((MAP, 'away')); eid = self.arm(g); entry = g.state.entities[eid].hand_entry_id
        self.play(g, 'away'); self.assertNotEqual(g.state.entities[eid].hand_entry_id, entry)
        self.assertEqual(g.state.hand_choice_followups[0].status, 'lost')
        g.apply(PlayCard(1, eid)); self.assertIsNone(g.state.pending_choice); self.portable(g)

    def test_hand_transfer_cannot_move_private_followup_to_other_player(self):
        self.script('transfer', lambda c: (MoveCard(self.ref(c, MINIONS[0]), 2, Zone.HAND),))
        g = self.game((MAP, 'transfer')); eid = self.arm(g); self.play(g, 'transfer')
        self.assertEqual(g.state.hand_choice_followups[0].status, 'lost')
        self.assertNotIn('play_followups', json.dumps(g.observe(2)))
        g.apply(EndTurn(1)); g.apply(PlayCard(2, eid)); self.assertIsNone(g.state.pending_choice)

    def test_followup_expires_at_end_of_original_global_turn(self):
        g = self.game(); eid = self.arm(g); g.apply(EndTurn(1))
        self.assertEqual(g.state.hand_choice_followups[0].status, 'expired')
        self.assertNotIn('play_followups', json.dumps(g.observe(1)))
        g.apply(EndTurn(2)); g.apply(PlayCard(1, eid)); self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_countered_map_has_no_offer_or_followup(self):
        self.options['counter'] = 'spell'
        self.script('arm-counter', lambda c: (SetSecret(2, 'probe.counter'),))
        g = self.game(('arm-counter', MAP)); self.play(g, 'arm-counter'); self.play(g, MAP)
        self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(g.state.hand_choice_followups, []); self.assertIsNone(g.state.pending_choice)

    def test_countered_selected_minion_still_completed_one_paid_play(self):
        self.options['counter'] = 'minion'
        self.script('arm-counter', lambda c: (SetSecret(2, 'probe.counter'),))
        g = self.game(('arm-counter', MAP)); self.play(g, 'arm-counter'); eid = self.arm(g)
        g.apply(PlayCard(1, eid)); self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.hand_choice_followups[0].trigger_play_id, g.state.play_history[-1].id)
        self.select(g); self.portable(g)

    def test_illegal_full_board_play_rolls_back_without_consuming_followup(self):
        g = self.game(board=('card.1',)*7); eid = self.arm(g); saved = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(PlayCard(1, eid))
        self.assertEqual(g.snapshot(), saved); self.assertEqual(g.state.hand_choice_followups[0].status, 'armed')

    def test_first_delivery_burn_has_no_armed_recipient(self):
        self.watch('fill', 'choice_selected', lambda c: tuple(AddToHand(1, 'card.1') for _ in range(10))
            if c.state.hand_choice_followups[0].initial_result is None else ())
        g = self.game(board=('fill',)); self.play(g, MAP); self.select(g, MINIONS[0])
        root = g.state.hand_choice_followups[0]
        self.assertEqual(root.status, 'not_hand'); self.assertIsNone(root.hand_entry_id)
        self.assertEqual(g.state.entities[root.initial_entity_id].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand), 10); self.portable(g)

    def test_reward_delivery_burn_consumes_once_without_reroll(self):
        self.watch('fill', 'card_played', lambda c: tuple(AddToHand(1, 'card.1') for _ in range(10))
            if c.state.hand_choice_followups and c.event.source_id == c.state.hand_choice_followups[0].initial_entity_id else ())
        g = self.game(board=('fill',)); eid = self.arm(g); g.apply(PlayCard(1, eid))
        rng = g.snapshot()['rng_state']; self.select(g, MINIONS[1]); root = g.state.hand_choice_followups[0]
        self.assertEqual(root.status, 'completed'); self.assertEqual(g.state.entities[root.reward_entity_id].zone, Zone.GRAVEYARD)
        self.assertEqual(g.snapshot()['rng_state'], rng); self.assertEqual(len(g.state.players[1].hand), 10)

    def test_delivery_reaction_wait_keeps_unique_finish_and_armed_identity(self):
        self.watch('wait', 'card_added_to_hand', lambda c: (RequestChoice(1, (ChoiceOption('ok', 'Continue'),), c.source_id),))
        g = self.game(board=('wait',)); self.play(g, MAP); self.select(g, MINIONS[0])
        root = g.state.hand_choice_followups[0]
        self.assertEqual((root.status, root.initial_delivery_pending), ('armed', True))
        other = self.portable(g)
        for match in (g, other): self.continue_probe(match)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertFalse(g.state.hand_choice_followups[0].initial_delivery_pending)
        self.play(g, MINIONS[0]); self.select(g, MINIONS[1])
        self.assertTrue(g.state.hand_choice_followups[0].reward_delivery_pending)
        other = self.portable(g)
        for match in (g, other): self.continue_probe(match)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.state.hand_choice_followups[0].status, 'completed')

    def test_card_played_reaction_wait_keeps_consumed_reward_in_continuation(self):
        self.watch('wait', 'card_played', lambda c: (RequestChoice(1, (ChoiceOption('ok', 'Continue'),), c.source_id),)
            if c.state.hand_choice_followups and c.event.source_id == c.state.hand_choice_followups[0].initial_entity_id else ())
        g = self.game(board=('wait',)); eid = self.arm(g); g.apply(PlayCard(1, eid))
        self.assertEqual(g.state.hand_choice_followups[0].status, 'reward_queued'); other = self.portable(g)
        for match in (g, other): self.continue_probe(match)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(g.state.pending_choice.options), 2)

    def test_empty_and_single_candidate_pools_have_no_second_choice(self):
        for members in ((), MINIONS[:1]):
            with self.subTest(members=members):
                self.options['members'] = members; g = self.game(); before = g.snapshot()['rng_state']; self.play(g, MAP)
                if not members:
                    self.assertEqual(g.snapshot()['rng_state'], before)
                    self.assertEqual(g.state.hand_choice_followups[0].status, 'empty')
                else:
                    self.select(g); self.play(g, MINIONS[0])
                    self.assertEqual(g.state.hand_choice_followups[0].status, 'exhausted')
                self.assertIsNone(g.state.pending_choice); self.portable(g)

    def test_unknown_matching_candidate_fails_instead_of_silent_pool_exclusion(self):
        self.options.update(members=(*MINIONS, 'probe.missing'), unadapted=True)
        g = self.game(); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, MAP)
        self.assertEqual(g.snapshot(), saved)

    def test_each_map_has_its_own_recipient_and_original_offer(self):
        g = self.game((MAP, MAP)); first = self.arm(g, MINIONS[0]); second = self.arm(g, MINIONS[1])
        self.assertNotEqual(first, second); g.apply(PlayCard(1, second)); self.select(g, MINIONS[2])
        self.assertEqual([r.status for r in g.state.hand_choice_followups], ['armed', 'completed'])
        g.apply(PlayCard(1, first)); self.assertEqual(len(g.state.pending_choice.options), 2)
        self.select(g, MINIONS[1]); self.assertEqual([r.status for r in g.state.hand_choice_followups], ['completed']*2)

    def test_followup_is_private_even_when_received_card_identity_is_revealed(self):
        self.script('reveal', lambda c: (RevealHandCard(self.ref(c, MINIONS[0]).entity_id),))
        g = self.game((MAP, 'reveal')); self.arm(g); self.play(g, 'reveal')
        owner = g.observe(1); opponent = g.observe(2)
        own = next(c for c in owner['players'][0]['hand'] if c['card_id'] == MINIONS[0])
        self.assertEqual([c['card_id'] for c in own['play_followups'][0]['remaining']], [o.card_id for o in g.state.hand_choice_followups[0].offers if o.card_id != MINIONS[0]])
        self.assertTrue(any(c['card_id'] == MINIONS[0] for c in opponent['players'][0]['hand']))
        for view in (owner, opponent):
            serialized = json.dumps(view)
            for private in ('hand_choice_followups', 'rng_before', 'available_pool', 'hand_entry_id'): self.assertNotIn(private, serialized)
        self.assertNotIn('play_followups', json.dumps(opponent))

    def test_other_players_offer_contents_do_not_change_opponent_projection(self):
        views = []; events = []
        for members in (MINIONS[:2], MINIONS[1:]):
            self.options['members'] = members; g = self.game(); self.play(g, MAP)
            views.append(g.observe(2)); events.append(g.player_events(2))
        self.assertEqual(views[0], views[1]); self.assertEqual(events[0], events[1])

    def test_deck_base_copy_current_copy_take_and_draw_reuse_physical_operations(self):
        for operation in ('copy_base', 'copy_current', 'take', 'draw'):
            with self.subTest(operation=operation):
                self.scripts = []
                self.script('deck-map', lambda c, operation=operation: (DiscoverForPlayFollowup(ChooseFromZone(
                    1, 1, Zone.DECK, operation=operation, distinct='card' if operation.startswith('copy') else 'entity',
                    source_id=c.source_id)),))
                g = self.game(('deck-map',), deck=MINIONS); originals = tuple(g.state.players[1].deck)
                self.play(g, 'deck-map'); self.portable(g); self.select(g, MINIONS[0])
                root = g.state.hand_choice_followups[0]; self.assertEqual(root.status, 'armed')
                self.assertEqual(root.initial_entity_id in originals, operation in ('take', 'draw'))
                self.play(g, MINIONS[0]); self.select(g, MINIONS[1]); root = g.state.hand_choice_followups[0]
                self.assertEqual(root.reward_entity_id in originals, operation in ('take', 'draw'))
                self.assertEqual(len(g.state.players[1].deck), 3 if operation.startswith('copy') else 1)
                self.assertEqual(len(g.state.draw_history), 2 if operation == 'draw' else 0); self.portable(g)

    def test_deck_current_copy_preserves_cost_base_copy_uses_printed_cost(self):
        for operation, expected in (('copy_current', 0), ('copy_base', 1)):
            with self.subTest(operation=operation):
                self.scripts = []
                self.script('deck-map', lambda c, operation=operation: (
                    ModifyCost(self.ref(c, MINIONS[1], zone=Zone.DECK).entity_id, CostSpec(set_to=0)),
                    DiscoverForPlayFollowup(ChooseFromZone(1, 1, Zone.DECK, operation=operation, source_id=c.source_id))))
                g = self.game(('deck-map',), deck=MINIONS); self.play(g, 'deck-map'); self.select(g, MINIONS[1])
                eid = g.state.hand_choice_followups[0].initial_entity_id
                self.assertEqual(g.state.entities[eid].cost, expected)
                g.apply(PlayCard(1, eid)); self.assertIsNotNone(g.state.pending_choice)

    def test_original_stale_deck_reward_is_explicitly_skipped_without_new_offer(self):
        self.script('deck-map', lambda c: (DiscoverForPlayFollowup(ChooseFromZone(
            1, 1, Zone.DECK, operation='take', distinct='entity', source_id=c.source_id)),))
        self.script('remove', lambda c: (DestroyDeckCard(self.ref(c, MINIONS[1], zone=Zone.DECK)),))
        g = self.game(('deck-map', 'remove'), deck=MINIONS); self.play(g, 'deck-map'); self.select(g, MINIONS[0])
        self.play(g, 'remove'); self.play(g, MINIONS[0]); rng = g.snapshot()['rng_state']
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, set(MINIONS[1:]))
        self.select(g, MINIONS[1]); self.assertEqual(g.state.hand_choice_followups[0].status, 'completed')
        self.assertIsNone(g.state.hand_choice_followups[0].reward_entity_id)
        self.assertEqual(sum(e.kind == 'zone_target_skipped' for e in g.events), 1)
        self.assertEqual(g.snapshot()['rng_state'], rng); self.portable(g)

    def test_duplicate_physical_deck_options_keep_unselected_copy_of_same_face(self):
        self.script('deck-map', lambda c: (DiscoverForPlayFollowup(ChooseFromZone(
            1, 1, Zone.DECK, operation='take', distinct='entity', source_id=c.source_id)),))
        g = self.game(('deck-map',), deck=(MINIONS[0], MINIONS[0], MINIONS[1]))
        self.play(g, 'deck-map'); self.select(g, MINIONS[0]); self.play(g, MINIONS[0])
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, set(MINIONS[:2]))
        self.select(g, MINIONS[0]); root = g.state.hand_choice_followups[0]
        self.assertNotEqual(root.initial_entity_id, root.reward_entity_id); self.portable(g)

    def test_late_delivery_failure_rolls_back_recipient_phase_rng_and_events(self):
        self.watch('fault', 'card_added_to_hand', lambda c: (AddToDeck(1, 'missing.card'),))
        g = self.game(board=('fault',)); self.play(g, MAP); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.select(g)
        self.assertEqual(g.snapshot(), saved); self.assertEqual(g.state.hand_choice_followups[0].status, 'offered')

    def test_terminal_delivery_cancels_pending_work_and_retains_ended_history(self):
        self.watch('kill', 'card_added_to_hand', lambda c: (Damage(c.state.players[2].hero_id, 40, c.source_id),))
        g = self.game(board=('kill',)); self.play(g, MAP); self.select(g, MINIONS[0])
        self.assertEqual(g.state.status, 'finished'); self.assertIsNone(g.state.pending_choice)
        root = g.state.hand_choice_followups[0]
        self.assertEqual(root.status, 'ended'); self.assertFalse(root.initial_delivery_pending); self.portable(g)

    def test_snapshot_rejects_changed_original_options_rng_or_recipient(self):
        g = self.game(); self.arm(g); snap = g.snapshot()
        for mutation in ('offers', 'rng', 'recipient', 'turn', 'phase'):
            with self.subTest(mutation=mutation):
                bad = deepcopy(snap); row = bad['state']['hand_choice_followups'][0]
                if mutation == 'offers': row['offers'].reverse()
                elif mutation == 'rng': row['rng_after'] = snap['rng_state']
                elif mutation == 'recipient': row['initial_entity_id'] = g.state.players[1].hero_id
                elif mutation == 'turn': row['turn'] = 2
                else: row['status'] = 'reward_offered'
                if mutation == 'rng': row['rng_after'][1][3] ^= 1
                self.reject(bad)

    def test_snapshot_rejects_removed_delivery_finish_or_owed_reward(self):
        self.watch('wait', 'card_added_to_hand', lambda c: (RequestChoice(1, (ChoiceOption('ok', 'Continue'),), c.source_id),))
        g = self.game(board=('wait',)); self.play(g, MAP); self.select(g, MINIONS[0]); bad = g.snapshot()
        queue = bad['resolution_frame']['fields']['continuation']['tuple']
        queue[:] = [v for v in queue if not v.get('type', '').endswith('FinishHandFollowupDelivery')]
        self.reject(bad)
        self.setUp()
        self.watch('wait', 'card_played', lambda c: (RequestChoice(1, (ChoiceOption('ok', 'Continue'),), c.source_id),)
            if c.state.hand_choice_followups and c.event.source_id == c.state.hand_choice_followups[0].initial_entity_id else ())
        g = self.game(board=('wait',)); self.arm(g); self.play(g, MINIONS[0]); bad = g.snapshot()
        queue = bad['resolution_frame']['fields']['continuation']['tuple']
        queue[:] = [v for v in queue if not v.get('type', '').endswith('RequestHandFollowupReward')]
        self.reject(bad)

    def test_original_source_departure_does_not_remove_armed_hand_followup(self):
        g = self.game(); source = self.play(g, MAP); self.select(g, MINIONS[0])
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.play(g, MINIONS[0]); self.assertIsNotNone(g.state.pending_choice)
        self.select(g, MINIONS[1]); self.assertEqual(g.state.hand_choice_followups[0].request.source_id, source)

    def test_first_delivery_reaction_departure_prevents_followup_from_arming_again(self):
        self.watch('depart', 'card_added_to_hand', lambda c: (MoveCard(
            CardReference.capture(c.state.entities[c.event.target_id]), 1, Zone.DECK, 'top'), Draw(1))
            if c.state.hand_choice_followups[0].status == 'armed' else ())
        g = self.game(board=('depart',)); self.play(g, MAP); self.select(g, MINIONS[0])
        root = g.state.hand_choice_followups[0]; self.assertEqual(root.status, 'lost')
        self.assertFalse(root.initial_delivery_pending)
        self.play(g, MINIONS[0]); self.assertIsNone(g.state.pending_choice); self.portable(g)

    def test_draw_delivery_reaction_wait_restores_original_draw_and_finish(self):
        self.script('deck-map', lambda c: (DiscoverForPlayFollowup(ChooseFromZone(
            1, 1, Zone.DECK, operation='draw', distinct='entity', source_id=c.source_id)),))
        self.watch('wait', 'card_drawn', lambda c: (RequestChoice(1, (ChoiceOption('ok', 'Continue'),), c.source_id),))
        g = self.game(('deck-map',), deck=MINIONS, board=('wait',)); self.play(g, 'deck-map'); self.select(g, MINIONS[0])
        self.assertEqual(g.state.hand_choice_followups[0].status, 'armed')
        self.assertEqual(len(g.state.draw_history), 1); other = self.portable(g)
        for match in (g, other): self.continue_probe(match)
        self.assertEqual(g.snapshot(), other.snapshot()); self.play(g, MINIONS[0]); self.select(g, MINIONS[1])
        self.portable(g); self.continue_probe(g); self.assertEqual(len(g.state.draw_history), 2)

    def test_followup_request_rejects_unrelated_destinations_grants_and_sources(self):
        for request in (DiscoverFromPool(1, 'murlocs'),
                DiscoverFromPool(1, 'murlocs', source_id=1, discoveries=2),
                DiscoverFromPool(1, 'murlocs', source_id=1, destination='board'),
                ChooseFromZone(1, 2, Zone.DECK, source_id=1),
                ChooseFromZone(1, 1, Zone.HAND, source_id=1)):
            with self.subTest(request=request):
                with self.assertRaises(ValueError): DiscoverForPlayFollowup(request)

    def test_new_schema_and_view_are_explicit_and_previous_schema_rejected(self):
        g = self.game(); snap = g.snapshot()
        self.assertEqual((snap['schema_version'], g.ruleset.id, g.mechanics.version), (266, 'prototype-v302', CORE_EFFECTS_VERSION))
        self.assertEqual(g.observe(1)['version'], 'player-view-v85')
        self.assertEqual(g.for_player(1).observe()['version'], 'player-actions-v12')
        self.assertEqual(build_replay(g)['schema_version'], 1)
        snap['schema_version'] = 162; self.reject(snap)
