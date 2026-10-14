"""Real held-price selection uses physical alternatives and existing entry."""
from dataclasses import replace
import json
from pathlib import Path
from random import Random
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, Game,
    PlayCard, PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice, SummonCause,
    SummonFromStoredCandidates, SummonStats, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Destroy,
    EquipWeapon, GainArmor, InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

PATH = Path(__file__).resolve().parents[1] / 'data/support/stored-candidate-summon-basics.json'
PIN = 'c83b2018904e04337d375480cb9fe73f25d6281356f718b8856faba5d0222481'
A = 'probe.private.a'; B = 'probe.private.b'; PLAIN = 'probe.private.plain'

def evidence():
    data = json.loads(PATH.read_bytes())
    if canonical_digest(data) != PIN:
        raise ValueError('Stored candidate source changed')
    return data['records'][0]

def candidates(c, registry, player=None):
    player = c.player_id if player is None else player
    return tuple(CardReference.capture(c.state.entities[i]) for i in c.state.players[player].hand
        if c.state.entities[i].kind == CardType.MINION
        and active_abilities(c.state.entities[i], 'deathrattle')
        and quote_unselected_cost(c.state, registry, c.state.entities[i]).amount <= 3)

def registry():
    row = evidence(); r = Registry('isolated-stored-candidate-summon-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=60, metadata=metadata()))
    r.register_behavior('death', lambda c: (GainArmor(c.player_id, 1),))
    r.register_behavior('cry', lambda c: (GainArmor(c.player_id, 20),))
    r.register_card(CardDefinition(A, 'Private priced minion', CardType.MINION,
        cost=5, attack=2, health=4, deathrattle='death', battlecry='cry', metadata=metadata()))
    r.register_card(CardDefinition(B, 'Private cheap minion', CardType.MINION,
        cost=2, attack=1, health=3, deathrattle='death', metadata=metadata()))
    r.register_card(CardDefinition(PLAIN, 'Private ordinary minion', CardType.MINION,
        cost=1, attack=1, health=3, metadata=metadata()))
    r.register_card(CardDefinition('filler.hidden', 'Private spell', CardType.SPELL, cost=9, metadata=metadata()))
    def pull(c, player=None):
        return SummonFromStoredCandidates(c.player_id, candidates(c, r, player), cause=SummonCause.capture(c))
    r.register_behavior('raw.boar', lambda c: (pull(c),))
    r.register_card(CardDefinition(row['id'], row['name'], CardType.MINION, cost=row['cost'],
        attack=row['attack'], health=row['health'], deathrattle='raw.boar',
        metadata=metadata(CardClass.DEMON_HUNTER, tribes=('beast',))))
    def ref(c):
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == A))
    def prepare(c):
        card = ref(c)
        return (ModifyCost(card.entity_id, CostSpec(delta=-2), c.source_id), BuffStoredCard(card, 2, 3, c.source_id))
    def stale(c, returned=False):
        card = ref(c)
        work = [MoveCard(card, 1, Zone.DECK)]
        if returned: work.append(MoveCard(replace(card, zone=Zone.DECK, zone_epoch=card.zone_epoch+1), 1, Zone.HAND))
        return (*work, SummonFromStoredCandidates(1, (card,), cause=SummonCause.capture(c)))
    def pause(c):
        return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),), c.source_id), pull(c))
    def fail(c): raise RuntimeError('Deliberate stored candidate entry failure')
    r.register_behavior('fail', fail)
    def bad_cause(c):
        request = pull(c)
        return (replace(request, cause=replace(request.cause, cast_id=999)),)
    scripts = {
        'pull': lambda c: (pull(c),),
        'prepare': prepare,
        'once': lambda c: (AddCostModifier(1, CostSpec(delta=-2, card_ids=(A,)), uses_remaining=1),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'stale': lambda c: stale(c), 'returned': lambda c: stale(c, True),
        'pause': pause,
        'bad.cause': bad_cause,
        'foreign': lambda c: (pull(c, 2),),
        'configured': lambda c: (replace(pull(c), position=0, stats=SummonStats(attack=7, health=8)),),
        'wrong': lambda c: (SummonFromStoredCandidates(1, (CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id=='filler.hidden')),)),),
        'unknown': lambda c: (SummonFromStoredCandidates(1, (CardReference(999, 1, Zone.HAND, 'absent.definition', 0),)),),
    }
    for cid, behavior in scripts.items():
        r.register_behavior(cid, behavior)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1, on_play=cid,
            requires_target=cid == 'kill', metadata=metadata()))
    r.register_behavior('watch', lambda c: (RequestChoice(1, (
        ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail', (EquipWeapon(1, A),))), c.source_id),))
    r.register_behavior('fault.watch', lambda c: (InvokeBehavior('fail', c.source_id, c.player_id),))
    for cid, behavior in (('watch', 'watch'), ('fault.watch', 'fault.watch')):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=5,
            triggers=(TriggerSpec('minion_summoned', behavior),), metadata=metadata()))
    return r

class StoredCandidateSummonTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), seed=156):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board, max_mana=10, mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy)), seed=seed), registry())
    def ids(self, g, cid, zone='hand', player=1):
        return [i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid]
    def play(self, g, cid, target=None): g.apply(PlayCard(1, self.ids(g, cid)[0], target))
    def choose(self, g, option='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))
    def portable(self, g):
        snap = g.snapshot()
        h = Game.from_snapshot(json.loads(json.dumps(snap)), registry())
        self.assertEqual(h.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap)
        return h
    def armor(self, g): return g.state.entities[g.state.players[1].hero_id].armor

    def test_raw_source_pin_and_exact_printed_body(self):
        row = evidence(); card = registry().card('BAR_325')
        self.assertEqual((card.cost, card.attack, card.health), (row['cost'], row['attack'], row['health']))
        self.assertEqual((card.cost, card.attack, card.health), (2, 3, 2))
        self.assertIn('（3）', row['text']); self.assertFalse(json.loads(PATH.read_bytes())['CN_calibrated'])

    def test_native_boar_uses_actual_hand_candidate_and_original_entity(self):
        g = self.game(('prepare', 'kill', A, A, PLAIN), board=('BAR_325',))
        copies = self.ids(g, A); self.play(g, 'prepare'); self.play(g, 'kill', self.ids(g, 'BAR_325', 'board')[0])
        self.assertEqual(self.ids(g, A, 'board'), [copies[0]]); self.assertEqual(self.ids(g, A), [copies[1]])
        self.assertEqual(len(g.state.death_history), 1); self.assertEqual(self.armor(g), 0)
        self.assertEqual((g.state.entities[copies[0]].attack, g.state.entities[copies[0]].health), (4, 7))
        self.assertFalse(g.state.draw_history); self.portable(g)

    def test_one_paid_spell_only_and_no_target_battlecry_or_payment(self):
        g = self.game(('prepare', 'pull', A)); self.play(g, 'prepare'); original = self.ids(g, A)[0]
        self.play(g, 'pull'); self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(self.ids(g, A, 'board'), [original]); self.assertEqual(self.armor(g), 0)
        self.assertEqual(len(g.state.play_history), 2); self.assertEqual(len(g.state.cast_history), 2)
        self.assertEqual(len(g.state.card_summon_history), 1); self.portable(g)

    def test_uniform_choice_counts_duplicate_cards_as_distinct_physical_options(self):
        for seed in (156, 991):
            with self.subTest(seed=seed):
                g = self.game(('pull', B, B, B), seed=seed); refs = self.ids(g, B)
                rng = Random(); rng.setstate(g._rng.getstate()); expected = rng.choice(refs)
                self.play(g, 'pull'); self.assertEqual(self.ids(g, B, 'board'), [expected])
                self.assertEqual(g._rng.getstate(), rng.getstate()); self.assertEqual(len(self.ids(g, B)), 2)
                self.portable(g)

    def test_query_does_not_spend_one_use_discount(self):
        g = self.game(('once', 'pull', A)); self.play(g, 'once'); before = g.snapshot()
        # The actual price is 3; the printed filter would exclude this entity.
        s = g.state; self.assertEqual(quote_unselected_cost(s, g.registry, s.entities[self.ids(g, A)[0]]).amount, 3)
        self.assertEqual(g.snapshot(), before); self.play(g, 'pull')
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, 1)
        self.assertEqual(g.state.players[1].mana, 8); self.portable(g)

    def test_empty_pool_does_not_move_draw_fatigue_or_advance_rng(self):
        g = self.game(('pull', A, PLAIN)); before = g._rng.getstate(); held = self.ids(g, A)
        self.play(g, 'pull'); self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(self.ids(g, A), held); self.assertFalse(g.state.players[1].board)
        self.assertFalse(g.state.draw_history); self.assertEqual(g.state.players[1].fatigue, 0); self.portable(g)

    def test_full_board_keeps_hidden_material_and_rng(self):
        g = self.game(('pull', B), board=(PLAIN,)*7); before = g._rng.getstate(); original = self.ids(g, B)
        self.play(g, 'pull'); self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(self.ids(g, B), original); self.assertFalse(g.state.card_summon_history); self.portable(g)

    def test_departed_reference_does_not_reenter_or_use_rng(self):
        g = self.game(('stale', A)); original = self.ids(g, A)[0]; before = g._rng.getstate()
        self.play(g, 'stale'); self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(self.ids(g, A, 'deck'), [original]); self.assertFalse(g.state.players[1].board); self.portable(g)

    def test_returned_same_entity_is_not_original_zone_lifetime(self):
        g = self.game(('returned', A)); original = self.ids(g, A)[0]; epoch = g.state.entities[original].zone_epoch
        before = g._rng.getstate(); self.play(g, 'returned')
        self.assertEqual(self.ids(g, A), [original]); self.assertEqual(g.state.entities[original].zone_epoch, epoch+2)
        self.assertEqual(g._rng.getstate(), before); self.assertFalse(g.state.players[1].board); self.portable(g)

    def test_original_owner_survives_foreign_hand_movement(self):
        g = self.game(('foreign',), enemy_hand=(B,)); original = self.ids(g, B, player=2)[0]
        self.play(g, 'foreign'); e = g.state.entities[original]
        self.assertEqual((e.owner, e.controller, e.zone), (2, 1, Zone.BOARD))
        self.assertEqual(self.ids(g, B, 'board'), [original]); self.portable(g)

    def test_configured_entry_uses_existing_position_and_stats(self):
        g = self.game(('configured', B), board=(PLAIN,)); original = self.ids(g, B)[0]
        self.play(g, 'configured'); self.assertEqual(g.state.players[1].board[0], original)
        self.assertEqual((g.state.entities[original].attack, g.state.entities[original].health), (7, 8)); self.portable(g)

    def test_waiting_before_selection_restores_typed_inventory(self):
        g = self.game(('pause', B, B)); before = g._rng.getstate(); self.play(g, 'pause')
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), before)
        h = self.portable(g); self.choose(g); self.choose(h)
        self.assertEqual(g.snapshot(), h.snapshot()); self.assertEqual(len(self.ids(g, B, 'board')), 1); self.portable(g)

    def test_waiting_after_entry_keeps_selected_physical_card(self):
        g = self.game(('pull', B, B), board=('watch',)); self.play(g, 'pull')
        self.assertIsNotNone(g.state.pending_choice); selected = self.ids(g, B, 'board'); before = g._rng.getstate()
        h = self.portable(g); self.choose(g); self.choose(h)
        self.assertEqual(g.snapshot(), h.snapshot()); self.assertEqual(self.ids(g, B, 'board'), selected)
        self.assertEqual(g._rng.getstate(), before); self.portable(g)

    def test_failed_choice_preserves_real_waiting_selection_and_rng(self):
        g = self.game(('pull', B, B), board=('watch',)); self.play(g, 'pull'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.portable(g); self.choose(g); self.portable(g)

    def test_late_entry_fault_rolls_back_payment_rng_and_physical_move(self):
        g = self.game(('pull', B, B), board=('fault.watch',)); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Deliberate'): self.play(g, 'pull')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_invalid_content_is_rejected_even_with_no_board_space(self):
        for cid in ('wrong', 'unknown'):
            with self.subTest(cid=cid):
                g = self.game((cid, 'filler.hidden'), board=(PLAIN,)*7); before = g.snapshot()
                with self.assertRaises(ResolutionError): self.play(g, cid)
                self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_codec_roundtrip_and_invalid_inventory_fields(self):
        g = self.game((B,)); ref = CardReference.capture(g.state.entities[self.ids(g, B)[0]])
        request = SummonFromStoredCandidates(1, (ref,)); codec = FrameCodec(g.mechanics, g.registry)
        encoded = codec.encode(request); self.assertEqual(codec.decode(encoded), request)
        for cards in ([ref], (ref, ref), (object(),), (ref, replace(ref, entity_id=999, player_id=2))):
            with self.subTest(cards=cards), self.assertRaises(ValueError): SummonFromStoredCandidates(1, cards)
        with self.assertRaises(ValueError): SummonFromStoredCandidates(1, (ref,), cause=object())

    def test_impossible_cause_rejected_on_empty_or_full_attempt(self):
        for hand, board in ((('bad.cause',), ()), (('bad.cause', B), (PLAIN,)*7)):
            with self.subTest(board=len(board)):
                g = self.game(hand, board=board); before = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'actual cast'): self.play(g, 'bad.cause')
                self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_pending_inventory_validator_rejects_foreign_cast_receipt(self):
        from hs_sim.engine.recruit_summons import validate_frame_references
        g = self.game(('pause', B)); self.play(g, 'pause')
        request = next(x for x in g._frame.continuation if type(x) is SummonFromStoredCandidates)
        validate_frame_references(g.state, g.registry, request)
        changed = replace(request, cause=replace(request.cause, cast_id=999))
        with self.assertRaisesRegex(ValueError, 'actual cast'):
            validate_frame_references(g.state, g.registry, changed)
        self.portable(g)

    def test_player_information_and_observation_are_pure(self):
        g = self.game(('pause', A, B, 'filler.hidden')); self.play(g, 'pause'); before = g.snapshot()
        port = g.for_player(2); text = json.dumps(port.observe()) + json.dumps(port.events())
        for private in (A, B, 'filler.hidden', 'SummonFromStoredCandidates', 'zone_epoch'):
            self.assertNotIn(private, text)
        self.assertEqual(g.snapshot(), before); self.portable(g)

if __name__ == '__main__': unittest.main()
