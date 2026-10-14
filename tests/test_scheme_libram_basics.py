"""Two independent real families expressed by existing progress and cost APIs."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, EndTurn, Game,
    HandProgressSpec, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, ResolutionError,
    Resource, Scenario, SelectChoice, SpellSchool, TargetSpec, Zone)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage, Destroy,
    GainArmor, Heal, RequestChoice, Silence, SpendResource, Summon)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import HealingKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry


SCHEME, ATTENDANT, TRUTH, HOPE, GUARDIAN, JUDGMENT = (
    'DAL_008', 'BT_020', 'BT_026', 'BT_024', 'BT_024t', 'YOP_011t')
FAMILY = (HOPE, JUDGMENT)  # Only the explicitly adapted, registered experiment.
PIN = '1debdcff7624e6b935476f22a42e71997ce845dcab4f76f80998cb47adbe97ad'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/scheme-libram-basics.json'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN: raise ValueError('Complete Scheme/Libram evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original record changed')
    return {row['id']: row['data'] for row in raw['records']}


def registry(scripts=(), *, bad_condition=False, choice_progress=False):
    r = opening_registry(); rows = evidence()
    r.register_behavior('scheme.noop', lambda c: ())
    r.register_trigger_condition('scheme.owner.end', (lambda c: 'invalid') if bad_condition else
        lambda c: c.event.player_id == c.player_id)
    spec = HandProgressSpec('event', 1, on_complete='scheme.noop', repeat=True,
        event='turn_ended', condition_id='scheme.owner.end')
    r.register_behavior('scheme.armor', lambda c: (GainArmor(c.player_id,
        1 + progress_ability(c.state.entities[c.source_id]).progress_completions),))
    r.register_card(CardDefinition(SCHEME, rows[SCHEME]['name'], CardType.SPELL, cost=4,
        on_play='scheme.armor', hand_progress=spec, metadata=metadata(CardClass.WARRIOR)))
    if choice_progress:
        r.register_behavior('scheme.wait', lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue', ()),), c.source_id),))
        r.register_card(CardDefinition('probe.scheme', 'Repeating hand progress probe', CardType.SPELL,
            on_play='scheme.noop', hand_progress=HandProgressSpec('event', 1, on_complete='scheme.wait',
                repeat=True, event='turn_ended', condition_id='scheme.owner.end'), metadata=metadata()))
    for cid, discount, rarity, keywords in ((ATTENDANT, 1, Rarity.COMMON, ()),
            (TRUTH, 2, Rarity.RARE, (Keyword.TAUNT,))):
        r.register_behavior('libram.' + cid, lambda c, n=discount: (AddCostModifier(c.player_id,
            CostSpec(delta=-n, minimum=0, card_ids=FAMILY), source_id=c.source_id),))
        row = rows[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'], keywords=keywords, battlecry='libram.' + cid,
            metadata=metadata(CardClass.PALADIN, rarity=rarity)))
    r.register_behavior('libram.hope', lambda c:
        (Heal(c.target_id, 8, c.source_id, HealingKind.SPELL), Summon(c.player_id, GUARDIAN)))
    r.register_card(CardDefinition(HOPE, rows[HOPE]['name'], CardType.SPELL, cost=9,
        on_play='libram.hope', targeting=TargetSpec(), spell_school=SpellSchool.HOLY,
        metadata=metadata(CardClass.PALADIN, rarity=Rarity.EPIC)))
    r.register_card(CardDefinition(GUARDIAN, rows[GUARDIAN]['name'], CardType.MINION,
        cost=8, attack=8, health=8, keywords=(Keyword.TAUNT, Keyword.DIVINE_SHIELD),
        metadata=metadata(CardClass.PALADIN, collectible=False)))
    r.register_card(CardDefinition(JUDGMENT, rows[JUDGMENT]['name'], CardType.WEAPON, cost=7,
        attack=5, durability=3, keywords=(Keyword.LIFESTEAL,),
        metadata=metadata(CardClass.PALADIN, collectible=False)))
    r.register_card(CardDefinition('probe.named_libram', 'Libram of Synthetic Probe', CardType.SPELL,
        cost=9, on_play='scheme.noop', metadata=metadata(CardClass.PALADIN)))
    for name, callback, cost in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=cost, on_play=name, metadata=metadata()))
    return r


class FamilyCase(unittest.TestCase):
    def setUp(self):
        self.scripts = []; self.options = {}

    def script(self, name, callback, cost=0): self.scripts.append((name, callback, cost))

    def game(self, hand=(), deck=('card.1',)*12, enemy_hand=(), board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, deck=deck, board=board, max_mana=10, mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, deck=('card.1',)*12, max_mana=10, mana=10)), seed=9),
            registry(self.scripts, **self.options))

    def entity(self, g, card, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if g.state.entities[i].card_id == card)

    def play(self, g, card, target=None):
        source = self.entity(g, card, g.state.active_player).id
        g.apply(PlayCard(g.state.active_player, source, target)); return source

    def round(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored


class SchemeBasicsTests(FamilyCase):
    def progress(self, g, card=SCHEME, player=1):
        return progress_ability(self.entity(g, card, player))

    def test_real_raw_and_existing_repeating_declaration(self):
        row = evidence()[SCHEME]; d = registry().card(SCHEME)
        self.assertEqual((d.name, d.cost), (row['name'], row['cost']))
        self.assertEqual(row['tags']['TAG_SCRIPT_DATA_NUM_1'], 1)
        self.assertTrue(d.hand_progress.repeat); self.assertEqual(d.hand_progress.goal, 1)

    def test_fresh_real_body_gains_one_armor(self):
        g = self.game(hand=(SCHEME,)); self.play(g, SCHEME)
        self.assertEqual((g.state.players[1].mana, g.state.entities[g.state.players[1].hero_id].armor), (6, 1))
        self.portable(g)

    def test_owner_end_grows_and_enemy_end_does_not(self):
        g = self.game(hand=(SCHEME,)); g.apply(EndTurn(1))
        self.assertEqual(self.progress(g).progress_completions, 1); g.apply(EndTurn(2))
        a = self.progress(g)
        self.assertEqual((a.progress_completions, a.progress_value, a.progress_units), (1, 0, (1,)))
        self.assertFalse(a.consumed); self.portable(g)

    def test_each_players_cards_use_their_own_end_boundary(self):
        g = self.game(hand=(SCHEME,), enemy_hand=(SCHEME,)); g.apply(EndTurn(1))
        self.assertEqual((self.progress(g).progress_completions, self.progress(g, player=2).progress_completions), (1, 0))
        g.apply(EndTurn(2))
        self.assertEqual((self.progress(g).progress_completions, self.progress(g, player=2).progress_completions), (1, 1))
        self.portable(g)

    def test_multiple_turns_keep_growing_without_consumption(self):
        g = self.game(hand=(SCHEME,))
        for _ in range(3): self.round(g)
        a = self.progress(g)
        self.assertEqual((a.progress_completions, a.progress_value, a.consumed, a.progress_units), (3, 0, False, (1, 1, 1)))
        self.play(g, SCHEME); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 4)
        self.portable(g)

    def test_same_name_physical_cards_have_separate_progress(self):
        g = self.game(hand=(SCHEME, SCHEME)); self.round(g)
        a, b = [progress_ability(g.state.entities[i]) for i in g.state.players[1].hand if g.state.entities[i].card_id == SCHEME]
        self.assertNotEqual(a.id, b.id); self.assertEqual((a.progress_completions, b.progress_completions), (1, 1))

    def test_new_hand_card_starts_at_one_without_past_turn_credit(self):
        self.script('probe.add', lambda c: (AddToHand(1, SCHEME),))
        g = self.game(hand=(SCHEME, 'probe.add')); self.round(g); self.play(g, 'probe.add')
        values = [progress_ability(g.state.entities[i]).progress_completions for i in g.state.players[1].hand
            if g.state.entities[i].card_id == SCHEME]
        self.assertEqual(values, [1, 0]); self.round(g)
        values = [progress_ability(g.state.entities[i]).progress_completions for i in g.state.players[1].hand
            if g.state.entities[i].card_id == SCHEME]
        self.assertEqual(values, [2, 1]); self.portable(g)

    def test_deck_card_does_not_grow(self):
        g = self.game(deck=(SCHEME, 'card.1'))
        g.apply(EndTurn(1))
        self.assertEqual(progress_ability(self.entity(g, SCHEME, zone=Zone.DECK)).progress_completions, 0)
        self.portable(g)

    def test_current_copy_inherits_counter_base_copy_starts_empty(self):
        def copy(c):
            e = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == SCHEME)
            ref = CardReference.capture(e)
            return (CopyCard(ref, 1, Zone.HAND, mode='current'), CopyCard(ref, 1, Zone.HAND, mode='base'))
        self.script('probe.copy', copy); g = self.game(hand=(SCHEME, 'probe.copy')); self.round(g); self.play(g, 'probe.copy')
        values = [progress_ability(g.state.entities[i]).progress_completions for i in g.state.players[1].hand
            if g.state.entities[i].card_id == SCHEME]
        self.assertEqual(values, [1, 1, 0]); self.portable(g)

    def test_generated_automatic_cast_uses_new_base_value(self):
        self.script('probe.cast', lambda c: (CastSpell(1, SCHEME, c.source_id),))
        g = self.game(hand=(SCHEME, 'probe.cast')); self.round(g); self.round(g)
        self.play(g, 'probe.cast'); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1)
        self.assertEqual(self.progress(g).progress_completions, 2); self.portable(g)

    def test_nonreset_move_preserves_counter_but_deck_pauses(self):
        def move(c, source, dest, reset=False):
            e = next(c.state.entities[i] for i in getattr(c.state.players[1], source.value) if c.state.entities[i].card_id == SCHEME)
            return (MoveCard(CardReference.capture(e), 1, dest, position='bottom', reset=reset),)
        self.script('probe.out', lambda c: move(c, Zone.HAND, Zone.DECK))
        self.script('probe.back', lambda c: move(c, Zone.DECK, Zone.HAND))
        g = self.game(hand=(SCHEME, 'probe.out', 'probe.back')); self.round(g); self.play(g, 'probe.out')
        g.apply(EndTurn(1))
        g.apply(EndTurn(2)); self.play(g, 'probe.back')
        self.assertEqual(self.progress(g).progress_completions, 1); self.portable(g)

    def test_private_counter_does_not_leak_to_opponent(self):
        g = self.game(hand=(SCHEME,)); self.round(g)
        own = g.observe(1)['players'][0]['hand'][0]; enemy = g.observe(2)['players'][0]['hand'][0]
        self.assertEqual(own['hand_progress']['completions'], 1); self.assertNotIn('hand_progress', enemy)
        self.assertFalse(any(e['kind'] == 'hand_progressed' for e in g.player_events(2)))

    def test_condition_failure_rolls_back_natural_end(self):
        self.options['bad_condition'] = True; g = self.game(hand=(SCHEME,)); before = g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), before)

    def test_repeat_completion_wait_recovers_without_double_growth(self):
        self.options['choice_progress'] = True; g = self.game(hand=('probe.scheme',)); g.apply(EndTurn(1))
        restored = self.portable(g)
        for game in (g, restored):
            pending = game.state.pending_choice; game.apply(SelectChoice(pending.player_id, pending.id, ('ok',)))
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(self.progress(g, 'probe.scheme').progress_completions, 1); self.portable(g)


class LibramBasicsTests(FamilyCase):
    def quote(self, g, card, player=1): return g.quote_cost(self.entity(g, card, player).id).amount

    def test_complete_raw_and_explicit_spell_weapon_family(self):
        rows = evidence(); r = registry()
        self.assertEqual(FAMILY, (HOPE, JUDGMENT))
        self.assertEqual((r.card(HOPE).kind, r.card(JUDGMENT).kind), (CardType.SPELL, CardType.WEAPON))
        for cid in (ATTENDANT, TRUTH, HOPE, GUARDIAN, JUDGMENT):
            self.assertEqual(r.card(cid).name, rows[cid]['name'])

    def test_attendant_adds_persistent_player_discount(self):
        g = self.game(hand=(ATTENDANT, HOPE, JUDGMENT)); source = self.play(g, ATTENDANT)
        self.assertEqual((self.quote(g, HOPE), self.quote(g, JUDGMENT)), (8, 6))
        modifier, = g.state.players[1].cost_modifiers
        self.assertEqual((modifier.source_id, modifier.uses_remaining, modifier.expires_turn), (source, None, None))
        self.assertEqual((self.entity(g, HOPE).cost, self.entity(g, HOPE).enchantments), (9, [])); self.portable(g)

    def test_truthseeker_reduces_by_two_and_has_real_body(self):
        g = self.game(hand=(TRUTH, HOPE, JUDGMENT)); source = self.play(g, TRUTH)
        self.assertEqual((self.quote(g, HOPE), self.quote(g, JUDGMENT)), (7, 5))
        e = g.state.entities[source]
        self.assertEqual((e.attack, e.health), (4, 6)); self.assertIn(Keyword.TAUNT, e.keywords); self.portable(g)

    def test_two_sources_stack_and_weapon_pays_discounted_cost(self):
        g = self.game(hand=(ATTENDANT, TRUTH, JUDGMENT, HOPE)); self.play(g, ATTENDANT); self.play(g, TRUTH)
        self.assertEqual((self.quote(g, HOPE), self.quote(g, JUDGMENT), g.state.players[1].mana), (6, 4, 4))
        source = self.play(g, JUDGMENT); weapon = g.state.entities[source]
        self.assertEqual((g.state.players[1].weapon_id, g.state.players[1].mana, weapon.attack, weapon.durability), (source, 0, 5, 3))
        self.assertIn(Keyword.LIFESTEAL, weapon.keywords)
        self.assertEqual(len(g.state.players[1].cost_modifiers), 2); self.portable(g)

    def test_discount_remains_after_source_death(self):
        self.script('probe.remove', lambda c: (Destroy(c.state.players[1].board[0]),))
        g = self.game(hand=(ATTENDANT, 'probe.remove', HOPE)); self.play(g, ATTENDANT); self.play(g, 'probe.remove')
        self.assertEqual(self.quote(g, HOPE), 8); self.assertEqual(len(g.state.players[1].cost_modifiers), 1); self.portable(g)

    def test_discount_remains_after_source_silence(self):
        self.script('probe.silence', lambda c: (Silence(c.state.players[1].board[0]),))
        g = self.game(hand=(ATTENDANT, 'probe.silence', HOPE)); self.play(g, ATTENDANT); self.play(g, 'probe.silence')
        self.assertEqual(self.quote(g, HOPE), 8); self.portable(g)

    def test_newly_generated_matching_card_receives_existing_discount(self):
        self.script('probe.add', lambda c: (AddToHand(1, HOPE),))
        g = self.game(hand=(ATTENDANT, 'probe.add')); self.play(g, ATTENDANT); self.play(g, 'probe.add')
        self.assertEqual(self.quote(g, HOPE), 8); self.assertEqual(self.entity(g, HOPE).enchantments, []); self.portable(g)

    def test_nonfamily_name_and_other_cards_are_not_matched(self):
        g = self.game(hand=(ATTENDANT, 'probe.named_libram', 'card.1', HOPE)); self.play(g, ATTENDANT)
        self.assertEqual((self.quote(g, 'probe.named_libram'), self.quote(g, 'card.1')), (9, 1))
        self.assertEqual(self.quote(g, HOPE), 8); self.portable(g)

    def test_player_discounts_are_independent(self):
        g = self.game(hand=(ATTENDANT, HOPE), enemy_hand=(HOPE,)); self.play(g, ATTENDANT)
        self.assertEqual(self.quote(g, HOPE), 8)
        g.apply(EndTurn(1)); self.assertEqual(self.quote(g, HOPE, player=2), 9); self.portable(g)

    def test_multiple_spell_payments_do_not_consume_permanent_modifier(self):
        g = self.game(hand=(ATTENDANT, HOPE, HOPE)); self.play(g, ATTENDANT)
        self.play(g, HOPE, g.state.players[1].hero_id); self.round(g)
        self.assertEqual(self.quote(g, HOPE), 8); self.play(g, HOPE, g.state.players[1].hero_id)
        modifier, = g.state.players[1].cost_modifiers
        self.assertIsNone(modifier.uses_remaining); self.assertEqual(g.state.players[1].mana, 2); self.portable(g)

    def test_real_hope_heals_and_summons_guardian(self):
        self.script('probe.wound', lambda c: (Damage(c.state.players[1].hero_id, 8, c.source_id),))
        g = self.game(hand=('probe.wound', ATTENDANT, HOPE)); self.play(g, 'probe.wound'); self.play(g, ATTENDANT)
        self.play(g, HOPE, g.state.players[1].hero_id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)
        e = self.entity(g, GUARDIAN, zone=Zone.BOARD)
        self.assertEqual((e.attack, e.health), (8, 8)); self.assertIn(Keyword.TAUNT, e.keywords)
        self.assertIn(Keyword.DIVINE_SHIELD, e.keywords); self.portable(g)

    def test_private_hand_quotes_expose_no_internal_modifier_ids(self):
        g = self.game(hand=(ATTENDANT, HOPE), enemy_hand=(HOPE,)); self.play(g, ATTENDANT)
        own = g.observe(1)['players'][0]['hand'][0]; enemy = g.observe(2)['players'][0]['hand'][0]
        self.assertEqual(own['cost']['amount'], 8); self.assertNotIn('cost', enemy)
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            self.assertNotIn('"cost_modifiers"', text); self.assertNotIn('"modifier_ids"', text)

    def test_illegal_payment_preserves_existing_modifiers(self):
        g = self.game(hand=(ATTENDANT, HOPE, HOPE)); self.play(g, ATTENDANT)
        self.play(g, HOPE, g.state.players[1].hero_id)
        self.assertEqual((g.state.players[1].mana, self.quote(g, HOPE)), (1, 8))
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, HOPE, g.state.players[1].hero_id)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(len(g.state.players[1].cost_modifiers), 1)
        self.portable(g)

    def test_choice_restoration_keeps_player_modifier_once(self):
        self.script('probe.discount', lambda c: (AddCostModifier(1, CostSpec(delta=-1, card_ids=FAMILY)),
            RequestChoice(1, (ChoiceOption('ok', 'Continue', ()),), c.source_id)))
        g = self.game(hand=('probe.discount', HOPE)); self.play(g, 'probe.discount'); restored = self.portable(g)
        for game in (g, restored):
            p = game.state.pending_choice; game.apply(SelectChoice(p.player_id, p.id, ('ok',)))
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(self.quote(g, HOPE), 8)
        self.assertEqual(len(g.state.players[1].cost_modifiers), 1); self.portable(g)

    def test_later_failure_rolls_back_added_modifier_payment_and_rng(self):
        self.script('probe.fail', lambda c: (AddToDeck(1, 'card.1'),
            AddCostModifier(1, CostSpec(delta=-1, card_ids=FAMILY)),
            SpendResource(1, Resource.CORPSES, 1, required=True)), cost=1)
        g = self.game(hand=('probe.fail', HOPE)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'probe.fail')
        self.assertEqual(g.snapshot(), before)
