"""Native Maluk and Banana recipes; entity-return details remain local M6 policy."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.retained_banana_cards import BANANA, CARD, load_batch, register_retained_banana_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CastSpell, CastStoredSpell,
    Game, PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, SpellRepeatSpec, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, InvokeBehavior, ModifyCost,
    RequestChoice, Summon)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CostSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference

P = 'k215.'
HERO, BODY, FILL, WATCH, REPEAT = (P+x for x in ('hero', 'body', 'fill', 'watch', 'repeat'))
CMD = P+'cmd.'
META = CardMetadata(False, (CardClass.HUNTER,), None, tribes=())


@lru_cache(None)
def registry(mode=None):
    r = Registry(P+'host'); register_retained_banana_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=80, metadata=META))
    r.register_card(CardDefinition(BODY, BODY, CardType.MINION, attack=2, health=6, metadata=META))
    r.register_behavior(P+'empty', lambda c: ())
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate Banana rollback')))
    r.register_card(CardDefinition(FILL, FILL, CardType.SPELL, on_play=P+'empty', metadata=META))
    r.register_card(CardDefinition(REPEAT, REPEAT, CardType.MINION, health=10, metadata=META,
        spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
    def stored(c):
        original = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == BANANA)
        return (CastStoredSpell(CardReference.capture(original), c.player_id, c.source_id),)
    scripts = {
        'auto': lambda c: (CastSpell(c.player_id, BANANA, c.source_id),),
        'stored': stored,
        'discount': lambda c: tuple(ModifyCost(i, CostSpec(set_to=0), c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == BANANA),
        'summon': lambda c: (Summon(c.player_id, CARD),),
    }
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(CMD+name, name, CardType.SPELL, on_play=P+name, metadata=META))
    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in (CARD, BANANA): return ()
        if mode == 'discard_add' and c.event.kind == 'card_discarded':
            return (AddToHand(c.player_id, FILL, c.source_id),)
        if mode == 'counter' and source.card_id == BANANA and c.event.kind == 'card_committed':
            return (CounterSpell(dict(c.event.data)['window_id']),)
        if source.card_id == BANANA and c.event.kind == 'stats_changed':
            if mode == 'fill': return tuple(AddToHand(c.player_id, FILL, c.source_id) for _ in range(10))
            if mode == 'kill': return (Destroy(c.event.target_id, c.source_id),)
        if ((mode == 'wait_discard' and c.event.kind == 'card_discarded') or
                (mode == 'wait_buff' and c.event.kind == 'stats_changed')):
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        return ()
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=tuple(TriggerSpec(event, P+'watch') for event in ('card_discarded', 'card_committed', 'stats_changed'))))
    r.validate(); return r


class RetainedBananaTests(unittest.TestCase):
    def game(self, hand=(CARD, FILL, FILL), board=(BODY,), enemy=(), owner=1, mode=None):
        self.owner, self.mode = owner, mode
        own = PlayerSetup(HERO, hand=hand, board=board, deck=(FILL,)*4, mana=30, max_mana=30, mana_cap=30)
        other = PlayerSetup(HERO, board=enemy, deck=(FILL,)*4, mana=30, max_mana=30, mana_cap=30)
        return Game.from_scenario(Scenario((own, other) if owner == 1 else (other, own),
            active_player=owner, seed=215), registry(mode))
    def ids(self, g, cid, zone='hand', player=None):
        return tuple(i for i in getattr(g.state.players[self.owner if player is None else player], zone)
            if g.state.entities[i].card_id == cid)
    def play(self, g, cid=CARD, target=None):
        eid = self.ids(g, cid)[0]; g.apply(PlayCard(self.owner, eid, target)); return eid
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); independent = registry.__wrapped__(self.mode)
        restored = Game.from_snapshot(deepcopy(saved), independent)
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), independent).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())
            for key in ('discard_history', 'hand_entry_id', 'rng_state', 'spell_submission'):
                self.assertNotIn(key, public)
        return restored

    def test_complete_root_child_and_evidence_only_sources(self):
        from hs_sim.cards import build_registry
        r = build_registry(); data = load_batch()
        self.assertEqual(len(data['official_observations']), 4)
        self.assertEqual((r.card(CARD).cost, r.card(CARD).attack, r.card(CARD).health), (4, 5, 6))
        self.assertEqual(r.card(CARD).metadata.tribes, ('beast',))
        self.assertEqual((r.card(BANANA).cost, r.card(BANANA).metadata.collectible), (1, False))
        self.assertNotIn('TIME_042te', r.cards)
        self.assertIsNone(r.card(BANANA).hand_repeat)

    def test_actual_battlecry_discards_own_original_hand_and_gets_named_banana(self):
        for owner in (1, 2):
            g = self.game(owner=owner); original = self.ids(g, FILL)
            source = self.play(g)
            self.assertEqual(g.state.players[owner].mana, 26)
            self.assertEqual([x.entity_id for x in g.state.discard_history], list(original))
            self.assertTrue(all(g.state.entities[i].zone == Zone.GRAVEYARD for i in original))
            self.assertEqual(len(self.ids(g, BANANA)), 1)
            self.assertEqual(g.state.entities[source].zone, Zone.BOARD); self.portable(g)

    def test_empty_original_hand_still_gets_banana_without_random_selection(self):
        g = self.game((CARD,)); rng = g.snapshot()['rng_state']; self.play(g)
        self.assertFalse(g.state.discard_history); self.assertEqual(len(self.ids(g, BANANA)), 1)
        self.assertEqual(g.snapshot()['rng_state'], rng); self.portable(g)

    def test_discard_reactions_do_not_add_new_cards_to_original_discard_group(self):
        g = self.game(board=(WATCH,), mode='discard_add'); original = self.ids(g, FILL)
        self.play(g)
        self.assertEqual(len(g.state.discard_history), 2)
        self.assertEqual(len(self.ids(g, FILL)), 2)
        self.assertTrue(set(original).isdisjoint(g.state.players[1].hand))
        self.assertEqual(len(self.ids(g, BANANA)), 1); self.portable(g)

    def test_plain_summoning_does_not_discard_or_generate_banana(self):
        g = self.game((CMD+'summon', FILL)); self.play(g, CMD+'summon')
        self.assertEqual(len(self.ids(g, CARD, 'board')), 1)
        self.assertEqual(len(self.ids(g, FILL)), 1); self.assertFalse(g.state.discard_history)
        self.assertFalse(self.ids(g, BANANA)); self.portable(g)

    def test_each_paid_banana_buffs_and_creates_one_new_ordinary_hand_copy(self):
        g = self.game((FILL, BANANA, FILL)); target = self.ids(g, BODY, 'board')[0]; spent = []
        for _ in range(3): spent.append(self.play(g, BANANA, target))
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (5, 9))
        self.assertEqual(g.state.players[1].mana, 27)
        self.assertEqual(len(set(spent)), 3); self.assertTrue(set(spent).isdisjoint(self.ids(g, BANANA)))
        self.assertTrue(all(g.state.entities[i].zone == Zone.GRAVEYARD for i in spent))
        self.assertEqual(g.state.players[1].hand[-1], self.ids(g, BANANA)[0])
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history)), (3, 3))
        self.assertTrue(all(c.completed for c in g.state.cast_history)); self.portable(g)

    def test_banana_can_buff_enemy_minion_and_bad_hero_target_is_atomic(self):
        g = self.game((BANANA,), board=(), enemy=(BODY,)); target = self.ids(g, BODY, 'board', 2)[0]
        saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, BANANA, g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(), saved); self.play(g, BANANA, target)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (3, 7)); self.portable(g)

    def test_new_base_banana_does_not_inherit_original_one_card_discount(self):
        g = self.game((CMD+'discount', BANANA)); self.play(g, CMD+'discount')
        target = self.ids(g, BODY, 'board')[0]; original = self.ids(g, BANANA)[0]
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[original]).amount, 0)
        self.play(g, BANANA, target); new = self.ids(g, BANANA)[0]
        self.assertNotEqual(new, original)
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[new]).amount, 1)
        self.assertIsNone(g.state.entities[new].hand_lifetime); self.portable(g)

    def test_countered_banana_loses_payload_and_has_no_return_creation(self):
        g = self.game((BANANA,), board=(BODY, WATCH), mode='counter'); target = self.ids(g, BODY, 'board')[0]
        self.play(g, BANANA, target)
        self.assertFalse(self.ids(g, BANANA)); self.assertEqual(g.state.entities[target].health, 6)
        self.assertEqual(g.state.players[1].mana, 29)
        self.assertEqual(g.state.cast_history[-1].failure, 'countered'); self.portable(g)

    def test_repeated_payload_buffs_twice_and_creates_two_bananas_for_one_payment(self):
        g = self.game((BANANA,), board=(BODY, REPEAT)); target = self.ids(g, BODY, 'board')[0]
        self.play(g, BANANA, target)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (4, 8))
        self.assertEqual((len(self.ids(g, BANANA)), g.state.players[1].mana), (2, 29))
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history)), (1, 2)); self.portable(g)

    def test_automatic_and_original_stored_casts_reuse_shared_execution_and_acquisition(self):
        for command, hand in (('auto', (CMD+'auto',)), ('stored', (CMD+'stored', BANANA))):
            g = self.game(hand); target = self.ids(g, BODY, 'board')[0]; self.play(g, CMD+command)
            self.assertEqual(g.state.entities[target].health, 7)
            self.assertEqual((len(self.ids(g, BANANA)), g.state.players[1].mana), (1, 30))
            self.assertEqual(len(g.state.play_history), 1)
            self.assertEqual(g.state.cast_history[-1].origin, 'effect'); self.portable(g)

    def test_automatic_no_target_fails_without_creating_banana(self):
        g = self.game((CMD+'auto',), board=()); self.play(g, CMD+'auto')
        self.assertFalse(self.ids(g, BANANA)); self.assertIsNotNone(g.state.cast_history[-1].failure); self.portable(g)

    def test_return_uses_actual_post_buff_capacity_and_normal_overflow(self):
        g = self.game((BANANA,), board=(BODY, WATCH), mode='fill'); target = self.ids(g, BODY, 'board')[0]
        self.play(g, BANANA, target)
        self.assertEqual(len(g.state.players[1].hand), 10); self.assertFalse(self.ids(g, BANANA))
        self.assertEqual(g.state.entities[target].health, 7)
        self.assertEqual(len([e for e in g.state.entities.values() if e.card_id == BANANA]), 2); self.portable(g)

    def test_target_destroyed_after_buff_does_not_cancel_ordinary_return_tail(self):
        g = self.game((BANANA,), board=(BODY, WATCH), mode='kill'); target = self.ids(g, BODY, 'board')[0]
        self.play(g, BANANA, target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(len(self.ids(g, BANANA)), 1); self.portable(g)

    def test_each_original_discard_wait_restores_and_failed_selection_is_atomic(self):
        g = self.game(board=(WATCH,), mode='wait_discard'); self.play(g)
        for remaining in (1, 2):
            self.assertIsNotNone(g.state.pending_choice); self.assertEqual(len(g.state.discard_history), remaining)
            self.assertFalse(self.ids(g, BANANA)); g = self.portable(g); saved = g.snapshot()
            with self.assertRaises(ResolutionError): self.choose(g, 'fail')
            self.assertEqual(g.snapshot(), saved); self.choose(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(self.ids(g, BANANA)), 1); self.portable(g)

    def test_buff_wait_retains_original_paid_tail_and_independent_restore_replay(self):
        g = self.game((BANANA,), board=(BODY, WATCH), mode='wait_buff'); target = self.ids(g, BODY, 'board')[0]
        self.play(g, BANANA, target)
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(self.ids(g, BANANA))
        self.assertEqual((g.state.entities[target].health, g.state.players[1].mana), (7, 29))
        g = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g)
        self.assertEqual(len(self.ids(g, BANANA)), 1); self.portable(g)
