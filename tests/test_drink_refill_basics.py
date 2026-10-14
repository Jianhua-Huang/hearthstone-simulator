"""Finite Drink uses are named fresh hand cards, not a new keyword or counter."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CastSpell, CostSpec,
    CounterSpell, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Rarity,
    ResolutionError, Scenario, SecretSpec, SelectChoice, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, Damage, DamageBatch, RequestChoice
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry

FORMS = ('VAC_323', 'VAC_323t', 'VAC_323t2')
ROOT, TWO, LAST = FORMS
SECRET = 'EX1_287'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/drink-refill-basics.json'
PIN = '44d7055323b0db8d1905cf95d77df7ebac827faa7f6006b328d97246de1fccc8'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN: raise ValueError('Complete Drink evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original Drink record changed')
    return {row['id']: row['data'] for row in raw['records']}


def registry(scripts=(), *, probe=None, fault=None):
    r = opening_registry(); rows = evidence()
    for index, cid in enumerate(FORMS):
        next_form = FORMS[index+1] if index < 2 else None
        def body(c, next_form=next_form):
            enemy = c.state.players[3-c.player_id]
            targets = (enemy.hero_id, *(i for i in enemy.board
                if c.state.entities[i].kind == CardType.MINION and c.state.entities[i].active))
            effects = (DamageBatch(tuple(Damage(i, 1, c.source_id, DamageKind.SPELL) for i in targets)),)
            if next_form is not None:
                effects += (AddToHand(c.player_id, 'missing.refill' if fault == 'missing' else next_form,
                    source_id=c.source_id),)
            if fault == 'late':
                effects += (AddToDeck(c.player_id, 'card.1', source_id=c.source_id),
                    AddToHand(c.player_id, 'missing.refill', source_id=c.source_id))
            return effects
        r.register_behavior('body.' + cid, body)
        row = rows[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.SPELL, cost=row['cost'],
            on_play='body.' + cid, spell_school=SpellSchool.FIRE,
            metadata=metadata(CardClass.SHAMAN, collectible=cid == ROOT)))
    r.register_secret_condition('counter', lambda c: c.event.player_id == 3-c.player_id and
        c.window is not None and c.window.kind == 'spell' and not c.window.countered)
    r.register_behavior('counter', lambda c: (CounterSpell(c.window.id),))
    row = rows[SECRET]
    r.register_card(CardDefinition(SECRET, row['name'], CardType.SPELL, cost=row['cost'],
        keywords=(Keyword.SECRET,), secret=SecretSpec(SECRET, ('card_committed',), 'counter', 'counter'),
        spell_school=SpellSchool.ARCANE, metadata=metadata(CardClass.MAGE, rarity=Rarity.RARE)))
    # This opening substrate is synthetic; it is not the Shaman hero power.
    r.register_card(CardDefinition('probe.shaman.power', 'Synthetic Shaman power', CardType.HERO_POWER,
        cost=2, on_use='power', metadata=metadata(CardClass.SHAMAN, collectible=False)))
    r.register_card(CardDefinition('probe.shaman.hero', 'Synthetic Shaman hero', CardType.HERO, health=30,
        initial_hero_power='probe.shaman.power', metadata=metadata(CardClass.SHAMAN, collectible=False)))
    if probe:
        event = 'card_added_to_hand' if probe == 'after' else 'damage_dealt'
        def reaction(c):
            if probe == 'after':
                if c.event.target_id is None or c.state.entities[c.event.target_id].card_id != TWO: return ()
            elif c.event.target_id != c.state.players[2].hero_id: return ()
            if probe == 'fill': return (AddToHand(1, 'card.1', source_id=c.source_id),)
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),), c.source_id),)
        r.register_behavior('probe.reaction', reaction)
        r.register_card(CardDefinition('probe.reaction', 'Ordinary event probe', CardType.MINION,
            health=4, triggers=(TriggerSpec(event, 'probe.reaction'),), metadata=metadata()))
    r.register_card(CardDefinition('probe.fragile', 'One health test minion', CardType.MINION,
        attack=1, health=1, metadata=metadata()))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    return r


class DrinkRefillTests(unittest.TestCase):
    def setUp(self): self.scripts = []; self.options = {}
    def script(self, name, callback): self.scripts.append((name, callback))
    def game(self, hand=(ROOT,), *, enemy_hand=(), board=(), enemy_board=(), deck_cards=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('probe.shaman.hero', hand=hand, deck=deck_cards, board=board, max_mana=10, mana=10),
            PlayerSetup('mage.hero', hand=enemy_hand, board=enemy_board, max_mana=10, mana=10)), seed=86),
            registry(self.scripts, **self.options))
    def entity(self, g, cid=None, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if (cid is None and g.state.entities[i].card_id in FORMS) or g.state.entities[i].card_id == cid)
    def ref(self, c, cid=None, player=1, zone=Zone.HAND):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[player], zone.value)
            if (cid is None and c.state.entities[i].card_id in FORMS) or c.state.entities[i].card_id == cid))
    def play(self, g, cid):
        source = self.entity(g, cid, g.state.active_player).id
        g.apply(PlayCard(g.state.active_player, source)); return source
    def drinks(self, g, player=1):
        return [g.state.entities[i] for i in g.state.players[player].hand if g.state.entities[i].card_id in FORMS]
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored
    def select(self, g):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))

    def test_complete_three_faces_and_counterspell_evidence(self):
        rows = evidence(); self.assertEqual(set(rows), {*FORMS, SECRET})
        self.assertEqual([rows[c]['cost'] for c in FORMS], [2]*3)
        for cid, text in zip(FORMS, ('3 Drinks left!', '2 Drinks left!', 'Last Drink!')):
            self.assertIn(text, rows[cid]['text_en']); self.assertIn('all enemies', rows[cid]['text_en'])
            self.assertEqual(rows[cid]['tags']['SPELL_SCHOOL'], 2)
        self.assertEqual(rows[ROOT]['related_dbf_ids'], [rows[TWO]['dbf_id'], rows[LAST]['dbf_id']])

    def test_existing_effects_need_no_keyword_counter_or_derivative(self):
        r = registry(); r.freeze()
        for cid in FORMS:
            self.assertEqual(r.card(cid).keywords, ())
            self.assertIsNone(r.card(cid).hand_progress)
            self.assertEqual(r.card(cid).hand_derivatives, ())

    def test_exact_three_paid_casts_new_physical_refills_and_no_fourth(self):
        g = self.game(); spent = []
        for index, cid in enumerate(FORMS):
            spent.append(self.play(g, cid))
            self.assertEqual([c.card_id for c in self.drinks(g)], [FORMS[index+1]] if index < 2 else [])
            self.assertEqual(g.state.players[1].mana, 10-2*(index+1))
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30-index-1)
            self.portable(g)
        self.assertEqual(len(set(spent)), 3)
        self.assertEqual([g.state.entities[i].zone for i in spent], [Zone.GRAVEYARD]*3)
        self.assertEqual([c.card_id for c in g.state.cast_history], list(FORMS))
        self.assertTrue(all(c.origin == 'hand' and c.completed and c.failure is None for c in g.state.cast_history))
        self.assertEqual([p.source_id for p in g.state.play_history], spent)
        generated = [e for e in g.events if e.kind == 'card_created' and e.source_id in spent]
        self.assertEqual([(e.source_id, e.target_id) for e in generated], list(zip(spent, spent[1:])))

    def test_each_remaining_face_has_only_its_remaining_uses(self):
        for start in (1, 2):
            with self.subTest(remaining=3-start):
                g = self.game((FORMS[start],))
                for cid in FORMS[start:]: self.play(g, cid)
                self.assertEqual(self.drinks(g), [])
                self.assertEqual(g.state.players[1].mana, 10-2*(3-start)); self.portable(g)

    def test_actual_all_enemies_includes_hero_and_minions_but_not_own_side(self):
        g = self.game(board=('card.1',), enemy_board=('card.2', 'card.3'))
        own = [g.state.players[1].hero_id, *g.state.players[1].board]
        enemy = [g.state.players[2].hero_id, *g.state.players[2].board]
        before = {i: g.state.entities[i].health for i in (*own, *enemy)}
        source = self.play(g, ROOT)
        self.assertEqual({i: g.state.entities[i].health for i in own}, {i: before[i] for i in own})
        self.assertEqual({i: g.state.entities[i].health for i in enemy}, {i: before[i]-1 for i in enemy})
        self.assertEqual({e.target_id for e in g.events if e.kind == 'damage_dealt' and e.source_id == source}, set(enemy))
        self.portable(g)

    def test_damage_deaths_settle_before_body_tail_refill(self):
        g = self.game(enemy_board=('probe.fragile', 'probe.fragile'))
        victims = g.state.players[2].board; source = self.play(g, ROOT)
        self.assertEqual(g.state.players[2].board, [])
        self.assertEqual([g.state.entities[i].zone for i in victims], [Zone.GRAVEYARD]*2)
        self.assertEqual(len(g.state.death_history), 2)
        refill = next(e.sequence for e in g.events if e.kind == 'card_created' and e.source_id == source)
        deaths = [e.sequence for e in g.events if e.kind == 'minion_died']
        self.assertEqual(len(deaths), 2); self.assertLess(max(deaths), refill); self.portable(g)

    def test_countered_each_face_spends_once_without_damage_or_refill(self):
        self.script('secret', lambda c: (SetSecret(2, SECRET),))
        for cid in FORMS:
            with self.subTest(face=cid):
                g = self.game((cid, 'secret')); self.play(g, 'secret'); source = self.play(g, cid)
                self.assertEqual(self.drinks(g), []); self.assertEqual(g.state.players[1].mana, 8)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
                cast = g.state.cast_history[-1]
                self.assertEqual((cast.card_id, cast.failure, cast.payload_started), (cid, 'countered', False))
                self.assertFalse(any(e.kind == 'card_created' and e.source_id == source for e in g.events))
                self.portable(g)

    def test_two_separate_physical_drinks_do_not_share_uses(self):
        g = self.game((ROOT, ROOT)); first, second = [c.id for c in self.drinks(g)]
        g.apply(PlayCard(1, first)); self.assertEqual(g.state.entities[second].card_id, ROOT)
        self.play(g, TWO); self.play(g, LAST)
        self.assertEqual([(c.id, c.card_id) for c in self.drinks(g)], [(second, ROOT)])
        self.assertEqual(g.state.players[1].mana, 4); self.portable(g)

    def test_named_generation_of_initial_face_starts_three_uses(self):
        self.script('get', lambda c: (AddToHand(1, ROOT, source_id=c.source_id),))
        g = self.game(('get',)); self.play(g, 'get')
        for cid in FORMS: self.play(g, cid)
        self.assertEqual(self.drinks(g), []); self.assertEqual(g.state.players[1].mana, 4); self.portable(g)

    def test_current_and_base_copy_keep_remaining_face_not_root(self):
        for mode in ('current', 'base'):
            for cid in (TWO, LAST):
                with self.subTest(mode=mode, face=cid):
                    self.scripts = []
                    self.script('copy', lambda c, mode=mode: (CopyCard(self.ref(c), 1, mode=mode),))
                    g = self.game((cid, 'copy')); self.play(g, 'copy')
                    cards = self.drinks(g); self.assertEqual([c.card_id for c in cards], [cid]*2)
                    self.assertEqual(len({c.id for c in cards}), 2)
                    g.apply(PlayCard(1, cards[1].id))
                    self.assertEqual(g.state.entities[cards[0].id].card_id, cid)
                    self.assertEqual([c.card_id for c in self.drinks(g)], [cid, LAST] if cid == TWO else [cid])
                    self.portable(g)

    def test_hand_deck_return_preserves_same_remaining_physical_card(self):
        self.script('away', lambda c: (MoveCard(self.ref(c), 1, Zone.DECK),))
        self.script('back', lambda c: (MoveCard(self.ref(c, zone=Zone.DECK), 1, Zone.HAND),))
        g = self.game((TWO, 'away', 'back')); source = self.entity(g).id
        self.play(g, 'away'); self.play(g, 'back')
        self.assertEqual((self.entity(g).id, self.entity(g).card_id), (source, TWO))
        self.play(g, TWO); self.play(g, LAST); self.assertEqual(self.drinks(g), []); self.portable(g)

    def test_transfer_preserves_remaining_face_and_refills_for_new_caster(self):
        self.script('give', lambda c: (MoveCard(self.ref(c), 2, Zone.HAND),))
        g = self.game((TWO, 'give')); source = self.entity(g).id
        self.play(g, 'give'); g.apply(EndTurn(1))
        self.assertEqual((self.entity(g, player=2).id, self.entity(g, player=2).card_id), (source, TWO))
        # Enemy's natural empty-deck draw loses one health; the actual spell targets player 1.
        target = g.state.players[1].hero_id; health = g.state.entities[target].health
        self.play(g, TWO)
        self.assertEqual(g.state.entities[target].health, health-1)
        self.assertEqual([c.card_id for c in self.drinks(g, 2)], [LAST])
        self.assertEqual(self.drinks(g, 1), []); self.portable(g)

    def test_local_discount_does_not_attach_to_new_refill(self):
        self.script('get', lambda c: (AddToHand(1, ROOT, cost=CostSpec(delta=-1)),))
        g = self.game(('get',)); self.play(g, 'get')
        self.assertEqual(quote_unselected_cost(g.state, g.registry, self.entity(g)).amount, 1)
        old = self.play(g, ROOT); refill = self.entity(g)
        self.assertNotEqual(old, refill.id)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, refill).amount, 2)
        self.assertEqual(g.state.players[1].mana, 9); self.portable(g)

    def test_base_copy_clears_local_discount_but_keeps_two_uses(self):
        self.script('get', lambda c: (AddToHand(1, TWO, cost=CostSpec(delta=-1)),))
        self.script('copy', lambda c: (CopyCard(self.ref(c), 1, mode='base'),))
        g = self.game(('get', 'copy')); self.play(g, 'get'); self.play(g, 'copy')
        cards = self.drinks(g); self.assertEqual([c.card_id for c in cards], [TWO]*2)
        self.assertEqual([quote_unselected_cost(g.state, g.registry, c).amount for c in cards], [1, 2])
        self.portable(g)

    def test_full_starting_hand_has_space_after_play_for_one_refill(self):
        g = self.game((ROOT, *(f'card.{i}' for i in range(1, 10))))
        source = self.play(g, ROOT)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual([c.card_id for c in self.drinks(g)], [TWO])
        self.assertFalse(any(e.kind == 'card_burned' and e.source_id == source for e in g.events)); self.portable(g)

    def test_reaction_fills_freed_space_then_refill_burns(self):
        self.options['probe'] = 'fill'
        g = self.game((ROOT, *(f'card.{i}' for i in range(1, 10))), board=('probe.reaction',))
        source = self.play(g, ROOT)
        self.assertEqual(len(g.state.players[1].hand), 10); self.assertEqual(self.drinks(g), [])
        burned = [e for e in g.events if e.kind == 'card_burned' and e.source_id == source]
        self.assertEqual(len(burned), 1)
        self.assertEqual((g.state.entities[burned[0].target_id].card_id, g.state.entities[burned[0].target_id].zone),
            (TWO, Zone.GRAVEYARD)); self.portable(g)

    def test_basic_automatic_cast_executes_once_and_creates_only_one_refill(self):
        self.script('cast', lambda c: (CastSpell(1, ROOT, c.source_id),))
        g = self.game(('cast',)); self.play(g, 'cast')
        self.assertEqual(g.state.players[1].mana, 10)
        self.assertEqual([c.card_id for c in self.drinks(g)], [TWO])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 29)
        casts = [c for c in g.state.cast_history if c.card_id == ROOT]
        self.assertEqual(len(casts), 1); self.assertEqual(casts[0].origin, 'effect'); self.assertTrue(casts[0].completed)
        self.portable(g)

    def test_waiting_after_damage_before_refill_continues_generation_once(self):
        self.options['probe'] = 'before'; g = self.game(board=('probe.reaction',)); self.play(g, ROOT)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.drinks(g), [])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 29)
        restored = self.portable(g)
        for instance in (g, restored):
            self.select(instance); self.assertEqual([c.card_id for c in self.drinks(instance)], [TWO])
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_waiting_after_refill_preserves_already_created_physical_card(self):
        self.options['probe'] = 'after'; g = self.game(board=('probe.reaction',)); self.play(g, ROOT)
        self.assertIsNotNone(g.state.pending_choice); refill = self.entity(g).id
        restored = self.portable(g)
        for instance in (g, restored):
            self.select(instance); self.assertEqual([(c.id, c.card_id) for c in self.drinks(instance)], [(refill, TWO)])
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_missing_next_form_errors_and_rolls_back_damage_and_payment(self):
        self.options['fault'] = 'missing'; g = self.game(); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, ROOT)
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_late_error_rolls_back_new_refill_rng_histories_and_information(self):
        self.options['fault'] = 'late'; g = self.game(deck_cards=('card.2', 'card.3')); before = g.snapshot()
        rng = g._rng.getstate(); views = (g.observe(1), g.observe(2))
        with self.assertRaises(ResolutionError): self.play(g, ROOT)
        self.assertEqual(g.snapshot(), before); self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual((g.observe(1), g.observe(2)), views); self.portable(g)

    def test_player_sees_own_remaining_face_without_hidden_opponent_identity(self):
        g = self.game(enemy_hand=(TWO,)); self.play(g, ROOT)
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['card_id'], TWO)
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        self.assertIsNone(g.observe(1)['players'][1]['hand'][0]['card_id'])
        for viewer in (1, 2):
            text = json.dumps(g.observe(viewer))
            for private in ('hand_entries', 'cast_history', 'zone_epoch', 'rng_state'):
                self.assertNotIn(private, text)
        for event in g.player_events(2):
            if event['kind'] == 'card_added_to_hand': self.assertIsNone(event['target']['card_id'])
        self.portable(g)
