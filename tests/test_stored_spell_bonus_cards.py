"""Actual Bomber and Archmage bonuses remain on original physical spells."""
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.stored_spell_bonus_cards import BOMBER, KALEC, ROOTS, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import AddToHand, ChoiceOption, Destroy, Draw, InvokeBehavior, RequestChoice, Silence, Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard

FIRE = 'CORE_CS2_029'
FROST = 'CORE_CS2_024'
YETI = 'CORE_CS2_182'
PREFIX = 'k93.'


def registry():
    r = build_registry()
    r.register_behavior(PREFIX+'fail', lambda c: (AddToHand(c.player_id, 'unknown.k93'),))
    def watch(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != KALEC:
            return ()
        other = next((c.state.entities[i] for i in c.state.players[c.player_id].deck
                      if c.state.entities[i].card_id == FROST), None)
        move = (MoveCard(CardReference.capture(other), c.player_id, Zone.HAND),) if other is not None else ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(PREFIX+'fail', c.source_id, c.player_id),)),
            ChoiceOption('move', 'Move original queued card', move),
            ChoiceOption('kill', 'Source departs', (Destroy(c.event.source_id, c.source_id),)),
        ), source_id=c.source_id),)
    r.register_behavior(PREFIX+'watch', watch)
    r.register_card(CardDefinition(PREFIX+'watch', 'Local grant observer', CardType.MINION, health=8,
                                   triggers=(TriggerSpec('stored_spell_damage_granted', PREFIX+'watch'),)))
    def first(c, cid):
        return next(e for e in c.state.entities.values() if e.card_id == cid and e.zone == Zone.BOARD)
    scripts = {
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'kill': lambda c: (Destroy(first(c, KALEC).id, c.source_id),),
        'silence': lambda c: (Silence(first(c, KALEC).id),),
        'summon': lambda c: tuple(Summon(c.player_id, cid) for cid in ROOTS),
        'copy': lambda c: (CopyCard(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == FIRE)), c.player_id, mode='current'),),
    }
    for key, body in scripts.items():
        r.register_behavior(PREFIX+key, body)
        r.register_card(CardDefinition(PREFIX+key, key, CardType.SPELL, on_play=PREFIX+key))
    return r


class StoredSpellBonusCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(), board=(), deck=(YETI,)*8, enemy_hand=(), enemy_deck=(YETI,)*8):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=enemy_deck, mana=40, max_mana=40, mana_cap=40),
        ), seed=93), self.r)

    def play(self, g, cid, target=None):
        i = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, i, target, position=len(g.state.players[1].board) if cid in ROOTS else None))
        return i

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def bonus(self, g, i):
        return sum(a.spell_damage for a in g.state.entities[i].abilities if a.kind == 'spell_damage' and not a.consumed)

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for hidden in ('CardReference', 'local_spell_damage', 'resolution_frame', 'rng_state', 'stored_spell_damage'):
                self.assertNotIn(hidden, public)
        return other

    def test_two_complete_real_faces_use_no_global_provider_or_new_native_kind(self):
        d = load_batch()
        self.assertEqual(len(d['official_observations']), 4)
        self.assertFalse(d['dependencies'])
        for cid, values in ((BOMBER, (123124, 3, 3, 4)), (KALEC, (122632, 4, 4, 4))):
            raw = next(x['record'] for x in d['cards'] if x['record']['id'] == cid); card = self.r.card(cid)
            self.assertEqual((raw['dbf_id'], card.cost, card.attack, card.health), values)
            self.assertEqual(card.spell_damage, 0)
            self.assertIsNotNone(card.battlecry)

    def test_bomber_chosen_original_hand_spell_gets_one_local_bonus_only(self):
        g = self.game((BOMBER, FIRE, FIRE)); chosen, other = g.state.players[1].hand[1:]
        source = self.play(g, BOMBER, chosen)
        self.assertEqual((self.bonus(g, chosen), self.bonus(g, other), g.state.players[1].mana), (1, 0, 37))
        a = next(a for a in g.state.entities[chosen].abilities if a.kind == 'spell_damage')
        self.assertEqual(a.source_id, source); self.assertEqual(len(g.state.battlecry_history), 1)

    def test_bomber_requires_eligible_target_but_allows_no_spell_in_hand(self):
        g = self.game((BOMBER, FIRE)); before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, BOMBER)
        self.assertEqual(g.snapshot(), before)
        g = self.game((BOMBER, YETI)); self.play(g, BOMBER)
        self.assertEqual(g.state.players[1].mana, 37)

    def test_bomber_rejects_own_minion_enemy_hand_and_own_deck_without_payment(self):
        g = self.game((BOMBER, YETI, FIRE), deck=(FROST,), enemy_hand=(FIRE,))
        targets = (g.state.players[1].hand[1], g.state.players[2].hand[0], g.state.players[1].deck[0])
        for target in targets:
            before = g.snapshot()
            with self.subTest(target=target), self.assertRaises(IllegalAction):
                self.play(g, BOMBER, target)
            self.assertEqual(g.snapshot(), before)

    def test_kalec_captures_only_own_hand_and_deck_spells(self):
        g = self.game((KALEC, FIRE, YETI), deck=(FROST, YETI), enemy_hand=(FIRE,), enemy_deck=(FROST,))
        hand = g.state.players[1].hand[1]; deck = g.state.players[1].deck[0]
        enemy = (g.state.players[2].hand[0], g.state.players[2].deck[0]); self.play(g, KALEC)
        self.assertEqual([self.bonus(g, i) for i in (hand, deck, *enemy)], [1, 1, 0, 0])
        self.assertEqual(g.state.players[1].mana, 36)
        self.assertEqual(len([e for e in g.events if e.kind == 'stored_spell_damage_granted']), 2)

    def test_kalec_empty_spell_inventory_still_has_ordinary_paid_battlecry(self):
        g = self.game((KALEC,), deck=(YETI,)); self.play(g, KALEC)
        self.assertEqual(g.state.players[1].mana, 36)
        self.assertEqual(len(g.state.battlecry_history), 1)
        self.assertFalse([e for e in g.events if e.kind == 'stored_spell_damage_granted'])

    def test_real_bonus_changes_only_its_physical_spell_damage_payload(self):
        g = self.game((BOMBER, FIRE, FIRE)); selected, other = g.state.players[1].hand[1:]
        self.play(g, BOMBER, selected); hero = g.state.players[2].hero_id
        self.play(g, FIRE, hero); first = g.state.cast_history[-1]
        self.assertEqual(sum(a.spell_damage for a in first.local_spell_damage), 1)
        self.play(g, FIRE, hero)
        self.assertFalse(g.state.cast_history[-1].local_spell_damage)
        self.assertEqual(g.state.entities[hero].health, 17)
        self.assertEqual(spell_bonus(g.state, 1, self.r), 0); self.portable(g)

    def test_two_actual_battlecries_stack_distinct_local_attachments(self):
        g = self.game((BOMBER, KALEC, FIRE)); spell = g.state.players[1].hand[2]
        first = self.play(g, BOMBER, spell); second = self.play(g, KALEC)
        abilities = [a for a in g.state.entities[spell].abilities if a.kind == 'spell_damage']
        self.assertEqual(self.bonus(g, spell), 2)
        self.assertEqual({a.source_id for a in abilities}, {first, second})
        self.assertEqual(len({a.id for a in abilities}), 2)
        self.play(g, FIRE, g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 22)

    def test_source_death_or_silence_does_not_remove_independent_spell_bonus(self):
        for action in ('kill', 'silence'):
            with self.subTest(action=action):
                g = self.game((KALEC, FIRE, PREFIX+action)); spell = g.state.players[1].hand[1]
                self.play(g, KALEC); self.play(g, PREFIX+action)
                self.assertEqual(self.bonus(g, spell), 1)
                self.play(g, FIRE, g.state.players[2].hero_id)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 23)

    def test_deck_bonus_follows_original_draw_into_actual_payload(self):
        g = self.game((KALEC, PREFIX+'draw'), deck=(FIRE, YETI)); original = g.state.players[1].deck[0]
        self.play(g, KALEC); self.play(g, PREFIX+'draw')
        self.assertIn(original, g.state.players[1].hand); self.assertEqual(self.bonus(g, original), 1)
        self.play(g, FIRE, g.state.players[2].hero_id)
        self.assertEqual(sum(a.spell_damage for a in g.state.cast_history[-1].local_spell_damage), 1)
        self.portable(g)

    def test_current_copy_keeps_bonus_and_uses_independent_attachments(self):
        g = self.game((BOMBER, FIRE, PREFIX+'copy')); original = g.state.players[1].hand[1]
        self.play(g, BOMBER, original); self.play(g, PREFIX+'copy')
        copies = [i for i in g.state.players[1].hand if g.state.entities[i].card_id == FIRE]
        self.assertEqual(len(copies), 2); self.assertTrue(all(self.bonus(g, i) == 1 for i in copies))
        ids = [{a.id for a in g.state.entities[i].abilities if a.kind == 'spell_damage'} for i in copies]
        self.assertFalse(ids[0] & ids[1]); self.portable(g)

    def test_direct_summon_and_initial_board_have_no_spell_grants(self):
        g = self.game((PREFIX+'summon', FIRE), board=ROOTS); spell = g.state.players[1].hand[1]
        self.play(g, PREFIX+'summon')
        self.assertEqual(self.bonus(g, spell), 0); self.assertFalse(g.state.battlecry_history)

    def test_real_grant_waiting_failure_restore_and_replay_keeps_original_queue(self):
        g = self.game((KALEC, FIRE), board=(PREFIX+'watch',), deck=(FROST,))
        self.play(g, KALEC); before = g.snapshot(); other = self.portable(g)
        self.assertIn('GrantStoredSpellDamage', str(before))
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        for current in (g, other):
            while current.state.pending_choice is not None:
                self.choose(current)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.players[1].mana, 36); self.portable(g)

    def test_actual_queued_deck_reference_does_not_rebind_after_move_into_hand(self):
        g = self.game((KALEC, FIRE), board=(PREFIX+'watch',), deck=(FROST,))
        original = g.state.players[1].deck[0]; self.play(g, KALEC); self.choose(g, 'move')
        self.assertIn(original, g.state.players[1].hand); self.assertEqual(self.bonus(g, original), 0)
        self.assertIsNone(g.state.pending_choice); self.portable(g)

    def test_departed_kalec_keeps_accepted_queue_and_original_source_identity(self):
        g = self.game((KALEC, FIRE), board=(PREFIX+'watch',), deck=(FROST,))
        original = g.state.players[1].deck[0]; source = self.play(g, KALEC); self.choose(g, 'kill')
        while g.state.pending_choice is not None:
            self.choose(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.bonus(g, original), 1)
        self.assertTrue(all(a.source_id == source for a in g.state.entities[original].abilities if a.kind == 'spell_damage'))
        self.portable(g)

    def test_legal_projection_is_pure_and_does_not_publish_enemy_hidden_spell(self):
        g = self.game((BOMBER, FIRE), enemy_hand=(FROST,)); before = g.snapshot()
        for p in (1, 2):
            g.for_player(p).observe(); g.for_player(p).legal_actions()
        self.assertEqual(g.snapshot(), before)
        self.assertNotIn(FROST, json.dumps(g.for_player(1).observe()))


if __name__ == '__main__':
    unittest.main()
