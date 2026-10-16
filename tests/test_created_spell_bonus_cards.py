"""Real named creations carry local material before ordinary acquisition work."""
from copy import deepcopy
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.created_spell_bonus_cards import BALANCE, MOONFIRE, STARFIRE, load_batch
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import AddToHand, ChoiceOption, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.zones import CardReference, CopyCard

YETI = 'CORE_CS2_182'
PREFIX = 'k94.'


def registry():
    r = build_registry()
    r.register_behavior(PREFIX+'fail', lambda c: (AddToHand(c.player_id, 'unknown.k94'),))
    def wait(c):
        if c.state.entities[c.event.target_id].card_id != MOONFIRE:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(PREFIX+'fail', c.source_id, c.player_id),)),
        ), source_id=c.source_id),)
    def observe(c):
        e = c.state.entities[c.event.target_id]
        if e.card_id not in (MOONFIRE, STARFIRE):
            return ()
        return (GainArmor(c.player_id, sum(a.spell_damage for a in e.abilities if a.kind == 'spell_damage')),)
    for name, event, body in (('wait', 'card_created', wait), ('created', 'card_created', observe),
                              ('added', 'card_added_to_hand', observe)):
        r.register_behavior(PREFIX+name, body)
        r.register_card(CardDefinition(PREFIX+name, name, CardType.MINION, health=10,
                                       triggers=(TriggerSpec(event, PREFIX+name),)))
    r.register_behavior(PREFIX+'late_fail', lambda c: (AddToHand(c.player_id, 'unknown.k94'),)
        if c.state.entities[c.event.target_id].card_id == STARFIRE else ())
    r.register_card(CardDefinition(PREFIX+'late_fail', 'Late creation failure', CardType.MINION, health=10,
                                   triggers=(TriggerSpec('card_created', PREFIX+'late_fail'),)))
    r.register_card(CardDefinition(PREFIX+'provider', 'Ordinary spell damage provider', CardType.MINION,
                                   health=10, spell_damage=3))
    def balance(c):
        return next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == BALANCE)
    def defer(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Create', (AddToHand(c.player_id, MOONFIRE, c.source_id, spell_damage=1),)),
        ), source_id=c.source_id),)
    scripts = {
        'defer': defer,
        'plain': lambda c: (AddToHand(c.player_id, MOONFIRE, c.source_id),),
        'bad_kind': lambda c: (AddToHand(c.player_id, YETI, c.source_id, spell_damage=1),),
        'bad_source': lambda c: (AddToHand(c.player_id, MOONFIRE, 999999, spell_damage=1),),
        'parent_bonus': lambda c: (GrantStoredSpellDamage(CardReference.capture(balance(c)), 2, c.source_id),),
        'copy': lambda c: (CopyCard(CardReference.capture(next(c.state.entities[i] for i in c.state.players[c.player_id].hand
             if c.state.entities[i].card_id == MOONFIRE)), c.player_id, mode='current'),),
    }
    for name, body in scripts.items():
        r.register_behavior(PREFIX+name, body)
        r.register_card(CardDefinition(PREFIX+name, name, CardType.SPELL, on_play=PREFIX+name))
    return r


class CreatedSpellBonusCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(BALANCE,), board=(), deck=(YETI,)*8):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', deck=(YETI,)*8, mana=40, max_mana=40, mana_cap=40),
        ), seed=94), self.r)

    def play(self, g, cid=BALANCE, target=None):
        i = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, i, target)); return i

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def bonus(self, e):
        return [a for a in e.abilities if a.kind == 'spell_damage']

    def created(self, g):
        return [g.state.entities[e.target_id] for e in g.events if e.kind == 'card_created'
                and g.state.entities[e.target_id].card_id in (MOONFIRE, STARFIRE)]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for hidden in ('local_spell_damage', 'resolution_frame', 'rng_state', 'CardReference', 'behavior_id'):
                self.assertNotIn(hidden, public)
        return other

    def nodes(self, value):
        if isinstance(value, dict):
            if value.get('type', '').endswith('.AddToHand'):
                yield value['fields']
            for v in value.values():
                yield from self.nodes(v)
        elif isinstance(value, list):
            for v in value:
                yield from self.nodes(v)

    def reject(self, s):
        s['state_hash'] = canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(s, self.r)
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_exact_original_dependencies_full_faces_and_printed_zero_moonfire(self):
        data = load_batch()
        self.assertEqual(len(data['official_observations']), 6)
        self.assertEqual([row['record']['dbf_id'] for row in data['dependencies']], [467, 823])
        self.assertEqual([self.r.card(i).cost for i in (BALANCE, MOONFIRE, STARFIRE)], [2, 0, 6])
        self.assertIsNotNone(self.r.card('Core_CS2_008'))
        self.assertNotEqual(self.r.card('Core_CS2_008').id, MOONFIRE)

    def test_actual_spell_pays_once_and_creates_only_two_original_local_bonuses(self):
        g = self.game(); source = self.play(g); created = self.created(g)
        self.assertEqual([e.card_id for e in created], [MOONFIRE, STARFIRE])
        self.assertEqual(g.state.players[1].mana, 38)
        self.assertEqual(len(g.state.cast_history), 1)
        self.assertTrue(all([(a.spell_damage, a.source_id) for a in self.bonus(e)] == [(1, source)] for e in created))
        self.assertNotEqual(self.bonus(created[0])[0].id, self.bonus(created[1])[0].id)

    def test_created_named_spells_apply_actual_local_damage_and_starfire_draw(self):
        g = self.game(); self.play(g); hero = g.state.players[2].hero_id
        self.play(g, MOONFIRE, hero); self.play(g, STARFIRE, hero)
        self.assertEqual(g.state.entities[hero].health, 22)
        self.assertEqual(g.state.players[1].mana, 32)
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, YETI)
        self.assertEqual([sum(a.spell_damage for a in rec.local_spell_damage) for rec in g.state.cast_history], [0, 1, 1])
        self.portable(g)

    def test_existing_same_name_hand_spell_does_not_receive_creation_bonus(self):
        g = self.game((BALANCE, MOONFIRE)); original = g.state.players[1].hand[1]; self.play(g)
        self.assertFalse(self.bonus(g.state.entities[original]))
        self.assertTrue(all(len(self.bonus(e)) == 1 for e in self.created(g)))

    def test_first_created_and_added_reactions_see_complete_fixed_material(self):
        g = self.game(board=(PREFIX+'created', PREFIX+'added')); self.play(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 4)
        self.assertFalse([e for e in g.events if e.kind == 'stored_spell_damage_granted'])
        self.portable(g)

    def test_full_hand_allocates_burned_second_spell_with_same_complete_material(self):
        g = self.game((BALANCE,)+(YETI,)*9); source = self.play(g); created = self.created(g)
        self.assertEqual([e.zone for e in created], [Zone.HAND, Zone.GRAVEYARD])
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual([(self.bonus(e)[0].spell_damage, self.bonus(e)[0].source_id) for e in created], [(1, source), (1, source)])
        self.assertEqual(len(g.state.cast_history), 1); self.portable(g)

    def test_wait_after_first_creation_keeps_second_original_request_and_payment(self):
        g = self.game(board=(PREFIX+'wait',)); self.play(g); before = g.snapshot(); other = self.portable(g)
        self.assertEqual(len(self.created(g)), 1)
        self.assertTrue(any(row['spell_damage'] == 1 for row in self.nodes(before)))
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        for current in (g, other):
            self.choose(current)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.created(g)), 2)
        self.assertEqual(g.state.players[1].mana, 38); self.portable(g)

    def test_deferred_creation_parameter_restores_before_actual_allocation(self):
        g = self.game((PREFIX+'defer',)); self.play(g, PREFIX+'defer'); other = self.portable(g)
        self.assertFalse(self.created(g))
        for current in (g, other):
            self.choose(current)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.bonus(self.created(g)[0])[0].spell_damage, 1)

    def test_plain_creation_default_zero_remains_unenchanted(self):
        g = self.game((PREFIX+'plain',)); self.play(g, PREFIX+'plain')
        self.assertFalse(self.bonus(self.created(g)[0])); self.portable(g)

    def test_nonspell_carrier_and_unknown_source_reject_without_allocation_or_payment(self):
        for name in ('bad_kind', 'bad_source'):
            with self.subTest(name=name):
                g = self.game((PREFIX+name,)); before = g.snapshot()
                with self.assertRaises(ResolutionError):
                    self.play(g, PREFIX+name)
                self.assertEqual(g.snapshot(), before)

    def test_invalid_amount_type_negative_and_missing_original_source_reject(self):
        for amount in (-1, True, 1.5, '1'):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                AddToHand(1, MOONFIRE, 1, spell_damage=amount)
        with self.assertRaises(ValueError):
            AddToHand(1, MOONFIRE, spell_damage=1)

    def test_global_and_parent_local_spell_damage_do_not_change_fixed_child_material(self):
        g = self.game((PREFIX+'parent_bonus', BALANCE), board=(PREFIX+'provider',))
        self.play(g, PREFIX+'parent_bonus'); self.play(g)
        self.assertEqual(sum(a.spell_damage for a in g.state.cast_history[-1].local_spell_damage), 2)
        self.assertTrue(all(sum(a.spell_damage for a in self.bonus(e)) == 1 for e in self.created(g)))

    def test_current_copy_keeps_local_bonus_with_its_own_attachment_identity(self):
        g = self.game((BALANCE, PREFIX+'copy')); self.play(g); original = self.created(g)[0]
        self.play(g, PREFIX+'copy')
        copies = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == MOONFIRE]
        self.assertEqual(len(copies), 2)
        self.assertTrue(all(sum(a.spell_damage for a in self.bonus(e)) == 1 for e in copies))
        self.assertEqual(len({self.bonus(e)[0].id for e in copies}), 2); self.portable(g)

    def test_late_creation_failure_rolls_back_both_allocations_and_attachments(self):
        g = self.game(board=(PREFIX+'late_fail',)); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_rehashed_waiting_wrong_bonus_type_or_future_source_rejects(self):
        g = self.game((PREFIX+'defer',)); self.play(g, PREFIX+'defer')
        for field, value in (('spell_damage', True), ('source_id', 999999)):
            s = deepcopy(g.snapshot()); rows = list(self.nodes(s)); self.assertTrue(rows)
            for row in rows:
                row[field] = value
            with self.subTest(field=field):
                self.reject(s)

    def test_rehashed_waiting_missing_new_parameter_requires_current_complete_shape(self):
        g = self.game((PREFIX+'defer',)); self.play(g, PREFIX+'defer'); s = g.snapshot()
        rows = list(self.nodes(s)); self.assertTrue(rows)
        for row in rows:
            del row['spell_damage']
        self.reject(s)


if __name__ == '__main__':
    unittest.main()
