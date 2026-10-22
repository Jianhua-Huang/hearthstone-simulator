"""Original in-play Rune gate, native location uses and complete pool summons."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.uldir_quarantine_card import CARD, load_batch, register_uldir_quarantine_card
from hs_sim.cards.remaining_mana_numbers_card import CARD as PICKLOCK, register_remaining_mana_numbers_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, UseLocation)
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice, Summon
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.location_rune_locks import BIRTH, PROGRESS, LocationRuneLock
from hs_sim.engine.lifecycle import reset_to_definition
from hs_sim.engine.locations import ModifyLocation, PlaceLocation, RefreshLocation
from hs_sim.engine.model import CardClass, CardMetadata, Rarity, Runes, TargetSpec, Zone
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from tools.card_batch import canonical, check_face

P = 'fixture.uldir.'
BLOOD, FROST, UNHOLY, MIXED, TRIPLE, THREE_BLOOD, ZERO, A, B, CHEAP, POOLSPELL, WATCH, UNKNOWN, RUNE_MINION = (
    P+x for x in ('blood', 'frost', 'unholy', 'mixed', 'triple', 'three_blood', 'zero',
        'five', 'foreign_five', 'four', 'poolspell', 'watch', 'unknown', 'rune_minion'))
REFRESH, LAST, COPY, NATURAL, PLACE = (P+x for x in ('refresh', 'last', 'copy', 'natural', 'place'))
CTX = GenerationContext('fixture.uldir', 'experimental')
META = CardMetadata(True, (CardClass.DEATH_KNIGHT,), Rarity.COMMON)


@lru_cache(maxsize=None)
def fixture(mode=None, pool='normal', role='writer'):
    assert role in ('writer', 'reader')
    r = build_registry(); register_uldir_quarantine_card(r)
    if PICKLOCK not in r.cards: register_remaining_mana_numbers_card(r)
    r.register_behavior(P+'noop', lambda c: ())
    for cid, runes in ((BLOOD, Runes(1, 0, 0)), (FROST, Runes(0, 1, 0)), (UNHOLY, Runes(0, 0, 1)),
            (MIXED, Runes(1, 0, 1)), (TRIPLE, Runes(1, 1, 1)), (THREE_BLOOD, Runes(3, 0, 0)), (ZERO, None)):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=P+'noop',
            metadata=CardMetadata(True, (CardClass.DEATH_KNIGHT,), Rarity.COMMON, runes=runes)))
    r.register_card(CardDefinition(RUNE_MINION, RUNE_MINION, CardType.MINION, attack=1, health=40,
        metadata=CardMetadata(True, (CardClass.DEATH_KNIGHT,), Rarity.COMMON, runes=Runes(1, 1, 1))))
    for cid, cost, cls in ((A, 5, CardClass.NEUTRAL), (B, 5, CardClass.PRIEST), (CHEAP, 4, CardClass.NEUTRAL)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=2, health=7,
            metadata=CardMetadata(True, (cls,), Rarity.COMMON)))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(POOLSPELL, POOLSPELL, CardType.SPELL, cost=5, on_play=P+'noop', metadata=META))
    r.register_pool_card(PoolCard.from_definition(r.card(POOLSPELL)))
    bodies = {REFRESH: lambda c: (RefreshLocation(c.target_id, c.source_id),),
        LAST: lambda c: (ModifyLocation(c.target_id, -2, c.source_id),),
        COPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id,
            mode='current', source_id=c.source_id),),
        NATURAL: lambda c: (Summon(c.player_id, RUNE_MINION),), PLACE: lambda c: (PlaceLocation(c.player_id, CARD),)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.HAND if cid == COPY else Zone.BOARD,), kinds=(CardType.LOCATION,), relation='friendly')
                if cid in (REFRESH, LAST, COPY) else None))
    def fail(c): raise ResolutionError('Deliberate Uldir reaction failure')
    r.register_behavior(P+'fail', fail)
    if mode:
        def watch(c):
            target = c.state.entities.get(c.event.target_id)
            if target is None or target.card_id not in ((CARD,) if mode == 'wait_open' else (A, B)): return ()
            if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            return (RequestChoice(3-c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        r.register_behavior(WATCH, watch)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40, metadata=META,
            triggers=(TriggerSpec('location_opened' if mode == 'wait_open' else 'minion_summoned', WATCH),)))
    members = () if pool == 'empty' else (A, B, CHEAP, POOLSPELL)
    if pool == 'foreign': members = (B, CHEAP, POOLSPELL)
    if pool == 'unknown':
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 5, META, attack=2)); members = (*members, UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards', 'v1', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    return r


class UldirTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy_hand=(), mode=None, pool='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(A,)*15, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_01', hand=enemy_hand, deck=(A,)*15, mana=30, max_mana=30, mana_cap=30)),
            seed=380, generation_context=CTX), fixture(mode, pool))

    def source(self, g): return next(g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == CARD)
    def play(self, g, cid, target=None, pid=1):
        source = next(g.state.entities[i] for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, source.id, target)); return source.id
    def use(self, g, source=None): return g.apply(UseLocation(1, self.source(g).id if source is None else source))
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; return g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def open(self, g, eid=None):
        eid = self.source(g).id if eid is None else eid
        index = g.state.players[1].board.index(eid)
        return g.observe(1)['players'][0]['board'][index]['location']['open']
    def portable(self, g, mode=None, pool='normal'):
        other = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), fixture(mode, pool, 'reader'))
        self.assertEqual(other.state_hash(), g.state_hash()); self.assertEqual(g.clone().state_hash(), g.state_hash())
        self.assertEqual(replay(build_replay(g), fixture(mode, pool, 'reader')).state_hash(), g.state_hash())
        return other
    def rehash(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def test_complete_raw_two_primary_faces_and_actual_three_rune_three_durability(self):
        data = load_batch(); entry, = data['cards']; raw = entry['record']
        self.assertEqual(canonical(raw), entry['record_sha256']); self.assertEqual(len(data['official_observations']), 2)
        for o in data['official_observations']: check_face(raw, o['face'], o['locale'])
        c = fixture().card(CARD); self.assertEqual((c.cost, c.durability, c.metadata.runes), (3, 3, Runes(1,1,1)))

    def test_real_placement_pays_three_but_never_counts_its_own_three_runes(self):
        g = self.game(hand=(CARD,)); source = self.play(g, CARD)
        self.assertEqual(g.state.players[1].mana, 27); self.assertFalse(self.open(g))
        self.assertEqual(g.state.entities[source].location_lock.start_play_id, 2)
        self.assertFalse(g.state.entities[source].location_lock.steps)
        before = g.state_hash()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.state_hash(), before); self.portable(g)

    def test_past_game_runes_do_not_unlock_a_new_location(self):
        g = self.game(hand=(BLOOD, FROST, UNHOLY, CARD));
        for cid in (BLOOD, FROST, UNHOLY, CARD): self.play(g, cid)
        self.assertFalse(self.open(g)); self.assertEqual(self.source(g).location_lock.start_play_id, 5)

    def test_three_actual_rune_plays_unlock_once_and_native_use_summons_without_mana(self):
        g = self.game(board=(CARD,), hand=(BLOOD, FROST, UNHOLY))
        for cid in (BLOOD, FROST): self.play(g, cid); self.assertFalse(self.open(g))
        self.play(g, UNHOLY); self.assertTrue(self.open(g)); before = g.state.players[1].mana; self.use(g)
        self.assertEqual((self.source(g).durability, self.source(g).location_cooldown), (2, 2))
        self.assertEqual(g.state.players[1].mana, before); self.assertEqual(len(g.state.successful_summon_history), 1)
        self.assertEqual(len([e for e in g.events if e.kind == 'location_opened' and dict(e.data).get('reason') == 'runes_completed']), 1)
        self.portable(g)

    def test_one_mixed_card_can_cover_two_runes_and_three_blood_is_only_one_kind(self):
        g = self.game(board=(CARD,), hand=(THREE_BLOOD, MIXED, FROST))
        self.play(g, THREE_BLOOD); self.assertFalse(self.open(g)); self.play(g, MIXED); self.assertFalse(self.open(g))
        self.play(g, FROST); self.assertTrue(self.open(g))

    def test_second_uldir_unlocks_first_but_starts_its_own_fresh_lock(self):
        g = self.game(hand=(CARD, CARD)); first = self.play(g, CARD); second = self.play(g, CARD)
        self.assertTrue(self.open(g, first)); self.assertFalse(self.open(g, second))
        self.assertEqual(g.state.entities[first].location_lock.steps[0].runes, (1,1,1))
        self.assertEqual(g.state.entities[second].location_lock.start_play_id, 3); self.portable(g)

    def test_opponent_roots_and_rune_less_plays_do_not_satisfy_own_lock(self):
        g = self.game(board=(CARD,), hand=(ZERO,), enemy_hand=(TRIPLE,)); self.play(g, ZERO)
        g.apply(EndTurn(1)); self.play(g, TRIPLE, pid=2); self.assertFalse(self.open(g))
        self.assertEqual(len(self.source(g).location_lock.steps), 2); self.portable(g)

    def test_rune_minion_summon_is_not_a_rune_play_but_real_minion_play_is(self):
        g = self.game(board=(CARD,), hand=(NATURAL, RUNE_MINION)); self.play(g, NATURAL); self.assertFalse(self.open(g))
        self.play(g, RUNE_MINION); self.assertTrue(self.open(g)); self.portable(g)

    def test_countered_rune_spell_still_counts_its_actual_admitted_hand_face(self):
        g = self.game(board=(CARD,), hand=(TRIPLE,), enemy_hand=('EX1_287',))
        g.apply(EndTurn(1)); self.play(g, 'EX1_287', pid=2); g.apply(EndTurn(2)); self.play(g, TRIPLE)
        self.assertTrue(g.state.play_history[-1].countered); self.assertTrue(self.open(g)); self.portable(g)

    def test_lock_progress_notifications_preserve_the_accepted_picklock_body_numbers(self):
        g = self.game(board=(CARD,), hand=(PICKLOCK,)); source = self.play(g, PICKLOCK)
        self.assertEqual(g.state.play_history[-1].cost, 30)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (30,30))
        self.assertEqual(g.state.players[1].mana, 0); self.assertFalse(self.open(g)); self.portable(g)

    def test_lock_progress_notifications_preserve_real_remaining_mana_spell_quote(self):
        from hs_sim.cards import build_registry as constructed_registry
        from hs_sim.cards.holy_soldier_cards import MARCH, TOKEN
        r = constructed_registry()
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_08', board=(CARD,), hand=(MARCH,),
            mana=4, max_mana=4), PlayerSetup('HERO_01'))), r)
        self.play(g, MARCH)
        self.assertEqual(g.state.play_history[-1].cost, 4); self.assertEqual(g.state.players[1].mana, 0)
        soldiers = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == TOKEN]
        self.assertEqual([(e.attack, e.health) for e in soldiers], [(4,4)])
        self.assertFalse(self.open(g))
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())), constructed_registry()).state_hash(), g.state_hash())
        self.assertEqual(replay(build_replay(g), constructed_registry()).state_hash(), g.state_hash())

    def test_remaining_uses_need_only_ordinary_two_own_turn_cooldown(self):
        g = self.game(board=(CARD,), hand=(TRIPLE,)); self.play(g, TRIPLE); self.use(g)
        for _ in range(2): g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertTrue(self.open(g)); self.use(g)
        self.assertEqual(self.source(g).durability, 1); self.assertEqual(len(self.source(g).location_lock.steps), 1)

    def test_refresh_cannot_bypass_rune_lock_but_reopens_unlocked_cooldown(self):
        g = self.game(board=(CARD,), hand=(REFRESH, TRIPLE, REFRESH)); source = self.source(g).id
        self.play(g, REFRESH, source); self.assertFalse(self.open(g))
        self.assertFalse(any(e.kind == 'location_opened' for e in g.events))
        self.play(g, TRIPLE); self.use(g); self.play(g, REFRESH, source); self.assertTrue(self.open(g))

    def test_hand_copy_starts_an_independent_lock_and_original_reset_clears_old_progress(self):
        g = self.game(hand=(CARD, TRIPLE, COPY))
        held = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == CARD)
        self.play(g, COPY, held); source = self.play(g, CARD); self.play(g, TRIPLE); copy = self.play(g, CARD)
        self.assertTrue(g.state.entities[source].location_lock.open); self.assertFalse(g.state.entities[copy].location_lock.open)
        self.portable(g)
        state = g.state; entity = state.entities[source]
        reset_to_definition(state, entity, g.registry.card(CARD), g.registry)
        self.assertIsNone(entity.location_lock)

    def test_effect_placement_starts_tracking_from_its_actual_entry(self):
        g = self.game(hand=(TRIPLE, PLACE)); self.play(g, TRIPLE); self.play(g, PLACE)
        self.assertFalse(self.open(g)); self.assertEqual(self.source(g).location_lock.start_play_id, 3)
        self.portable(g)

    def test_exact_five_cost_all_class_pool_and_one_actual_delivery(self):
        g = self.game(board=(CARD,), hand=(TRIPLE,), pool='foreign'); self.play(g, TRIPLE); self.use(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [CARD, B])
        self.assertEqual(len(g.state.successful_summon_history), 1); self.portable(g, pool='foreign')

    def test_full_board_blocks_nonfinal_activation_but_last_durability_frees_one_slot(self):
        g = self.game(board=(CARD,)+(A,)*6, hand=(TRIPLE, LAST), pool='foreign'); self.play(g, TRIPLE)
        source = self.source(g).id; before = g.state_hash()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.state_hash(), before); self.play(g, LAST, source); self.use(g, source)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD); self.assertIsNone(g.state.entities[source].location_lock)
        self.assertEqual(len(g.state.players[1].board), 7); self.assertEqual(g.state.successful_summon_history[-1].card_id, B)
        self.portable(g, pool='foreign')

    def test_empty_pool_consumes_native_use_without_sampling(self):
        g = self.game(board=(CARD,), hand=(TRIPLE,), pool='empty'); self.play(g, TRIPLE); before = g.snapshot()['rng_state']
        self.use(g); self.assertEqual(g.snapshot()['rng_state'], before); self.assertEqual(self.source(g).durability, 2)

    def test_unknown_eligible_candidate_rolls_back_durability_rng_and_events(self):
        g = self.game(board=(CARD,), hand=(TRIPLE,), pool='unknown'); self.play(g, TRIPLE); before = g.state_hash()
        with self.assertRaises(ResolutionError): self.use(g)
        self.assertEqual(g.state_hash(), before)

    def test_public_commands_and_direct_legality_share_closed_and_open_state(self):
        g = self.game(board=(CARD,), hand=(TRIPLE,)); port = g.for_player(1)
        self.assertFalse(any(a['type'] == 'use_location' for a in port.legal_actions()['actions']))
        self.assertFalse(any(isinstance(a, UseLocation) for a in g.legal_actions()))
        self.play(g, TRIPLE); commands = port.legal_actions()
        command = next(a for a in commands['actions'] if a['type'] == 'use_location')
        result = port.submit({'revision':commands['revision'], 'action':command})
        self.assertTrue(result['accepted']); self.assertFalse(self.open(g)); self.portable(g)

    def test_pending_open_reaction_restores_original_admitted_rune_play(self):
        g = self.game(board=(CARD, WATCH), hand=(TRIPLE,), mode='wait_open'); self.play(g, TRIPLE)
        self.assertIsNotNone(g.state.pending_choice); other = self.portable(g, 'wait_open')
        for branch in (g, other): self.choose(branch)
        self.assertEqual(g.state_hash(), other.state_hash()); self.assertTrue(self.open(g))
        self.assertEqual(len(self.source(g).location_lock.steps), 1)

    def test_pending_summon_reaction_restores_original_use_and_single_delivery(self):
        g = self.game(board=(CARD, WATCH), hand=(TRIPLE,), mode='wait_summon'); self.play(g, TRIPLE); self.use(g)
        self.assertIsNotNone(g.state.pending_choice); other = self.portable(g, 'wait_summon')
        for branch in (g, other): self.choose(branch)
        self.assertEqual(g.state_hash(), other.state_hash()); self.assertEqual(self.source(g).durability, 2)
        self.assertEqual(len(g.state.successful_summon_history), 1); self.portable(g, 'wait_summon')

    def test_failed_summon_or_failed_wait_branch_restores_the_whole_original_use(self):
        g = self.game(board=(CARD, WATCH), hand=(TRIPLE,), mode='fail'); self.play(g, TRIPLE); before = g.state_hash()
        with self.assertRaises(ResolutionError): self.use(g)
        self.assertEqual(g.state_hash(), before)
        g = self.game(board=(CARD, WATCH), hand=(TRIPLE,), mode='wait_summon'); self.play(g, TRIPLE); self.use(g); before = g.state_hash()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.state_hash(), before)

    def test_rehashed_origin_progress_runes_and_missing_all_receipts_are_rejected(self):
        g = self.game(board=(CARD,), hand=(BLOOD,)); self.play(g, BLOOD); source = self.source(g).id
        def lock(saved): return saved['state']['entities'][str(source)]['location_lock']
        def reject(edit):
            saved = deepcopy(g.snapshot()); edit(saved); self.rehash(saved)
            with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture(role='reader'))
        reject(lambda s: lock(s)['steps'][0].update(runes=[1,1,1]))
        reject(lambda s: lock(s).update(steps=[]))
        reject(lambda s: lock(s).update(start_play_id=True))
        reject(lambda s: lock(s).update(start_play_id=2, steps=[]))
        reject(lambda s: s['state']['entities'][str(source)].update(location_lock=None))
        reject(lambda s: s.update(events=[e for e in s['events'] if e['kind'] != PROGRESS]))
        reject(lambda s: s.update(events=[e for e in s['events'] if e['kind'] not in (BIRTH, PROGRESS)]))

    def test_lock_receipts_and_raw_play_histories_are_not_player_information(self):
        g = self.game(board=(CARD,), hand=(BLOOD,)); self.play(g, BLOOD)
        for pid in (1,2):
            public = json.dumps(g.observe(pid))+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('location_lock', 'start_play_id', 'controller_at_entry', BIRTH, PROGRESS, 'play_history'):
                self.assertNotIn('"'+key+'"', public)
        self.portable(g)
