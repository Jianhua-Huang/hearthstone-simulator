"""Lotus Troublemaker's native stored growth and actual unit damage packets."""
from functools import lru_cache
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry as assembled
from hs_sim.cards.jade_hellraiser_card import ROOT, load_batch, register_jade_hellraiser_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.battlecry_sources import RepeatBattlecry, TriggerBattlecry
from hs_sim.engine.effects import (ChoiceOption, Destroy, InvokeBehavior, RandomDamage,
    RequestChoice, ReturnToHand, Silence, SpendMana, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CostSpec, DamageKind, PaymentType
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE as PHYSICAL_PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference, CopyCard, ModifyStoredCost, MoveCard

P = 'lotus.test.'
TWO, THREE, HEALTH, AUTO, SPEND, REDUCE, FREE, COPY, BASE, OUT, RESET, IN, BOUNCE, TRIGGER, HISTORY, MIRROR, TINY = (
    P+x for x in ('two', 'three', 'health', 'auto', 'spend', 'reduce', 'free', 'copy',
                 'base', 'out', 'reset', 'in', 'bounce', 'trigger', 'history', 'mirror', 'tiny'))
WAIT, COMMIT, COUNTER, SILENCE, MORPH, KILL = (
    P+x for x in ('wait', 'commit', 'counter', 'silence', 'morph', 'kill'))
FILL = 'CS2_182'


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer', 'reader')
    r = build_registry(); register_jade_hellraiser_card(r)
    meta = replace(r.card(FILL).metadata, deck_identity=None)
    def ref(c): return CardReference.capture(c.state.entities[c.target_id])
    def historical(c):
        selected = next(p.id for p in c.state.play_history if p.card_id == ROOT)
        query = WholeCardHistoryQuery(c.player_id, c.play.id, kinds=(CardType.MINION,),
            exclude_play_ids=tuple(p.id for p in c.state.play_history
                if p.id < c.play.id and p.id != selected))
        return (ReplayWholeCards(c.player_id, c.source_id, query, physical_profile=PHYSICAL_PROFILE),)
    bodies = {
        TWO: lambda c: (), THREE: lambda c: (), HEALTH: lambda c: (),
        AUTO: lambda c: (CastSpell(c.player_id, TWO, c.source_id),),
        SPEND: lambda c: (SpendMana(c.player_id, 2, c.source_id),),
        REDUCE: lambda c: (ModifyStoredCost(ref(c), CostSpec(set_to=2), c.source_id),),
        FREE: lambda c: (ModifyStoredCost(ref(c), CostSpec(set_to=0), c.source_id),),
        COPY: lambda c: (CopyCard(ref(c), c.player_id, mode='current', source_id=c.source_id),),
        BASE: lambda c: (CopyCard(ref(c), c.player_id, mode='base', source_id=c.source_id),),
        OUT: lambda c: (MoveCard(ref(c), c.player_id, Zone.DECK, source_id=c.source_id),),
        RESET: lambda c: (MoveCard(ref(c), c.player_id, Zone.DECK, reset=True, source_id=c.source_id),),
        IN: lambda c: (MoveCard(ref(c), c.player_id, Zone.HAND, draw=True, source_id=c.source_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        TRIGGER: lambda c: (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]), c.source_id),),
        HISTORY: historical,
    }
    for name, body in bodies.items():
        r.register_behavior(name, body); kw = {}
        if name in (REDUCE, FREE, COPY, BASE, OUT, RESET, IN, BOUNCE, TRIGGER):
            kw['targeting'] = TargetSpec(zones=(Zone.DECK,) if name == IN else
                (Zone.BOARD,) if name in (BOUNCE, TRIGGER) else (Zone.HAND,),
                kinds=(CardType.MINION, CardType.SPELL), relation='friendly')
        if name == HEALTH: kw['cost_payment'] = PaymentType.HEALTH
        r.register_card(CardDefinition(name, name, CardType.SPELL,
            cost=2 if name in (TWO, HEALTH) else 3 if name == THREE else 0,
            on_play=name, metadata=meta, **kw))
    def mirror(c):
        original = next(b.id for b in c.state.battlecry_history if b.payload.card_id == ROOT and b.completed)
        return (RepeatBattlecry(c.player_id, c.source_id, original),)
    r.register_behavior(MIRROR, mirror)
    r.register_card(CardDefinition(MIRROR, MIRROR, CardType.MINION, health=9, battlecry=MIRROR, metadata=meta))
    r.register_card(CardDefinition(TINY, TINY, CardType.MINION, health=1, metadata=meta))
    def fail(c): raise ResolutionError('Lotus deliberate rollback')
    r.register_behavior(P+'fail', fail)
    for mode in (WAIT, COMMIT, COUNTER, SILENCE, MORPH, KILL):
        def watch(c, mode=mode):
            source = c.state.entities.get(c.event.source_id)
            if source is None or source.card_id != (TWO if mode in (COMMIT, COUNTER) else ROOT): return ()
            if mode == COUNTER: return (CounterSpell(dict(c.event.data)['window_id']),)
            if mode == SILENCE: return (Silence(c.event.source_id),)
            if mode == MORPH: return (Transform(c.event.source_id, FILL),)
            if mode == KILL: return (Destroy(c.event.source_id),)
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('morph', 'Change original source', (Transform(c.event.source_id, FILL),)),
                ChoiceOption('fail', 'Fail', (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
                    InvokeBehavior(P+'fail', c.source_id, c.player_id)))), c.source_id),)
        r.register_behavior(mode, watch)
        event = ('card_committed' if mode in (COMMIT, COUNTER) else
                 'battlecry_started' if mode in (SILENCE, MORPH) else 'damage_dealt')
        r.register_card(CardDefinition(mode, mode, CardType.MINION, health=9, metadata=meta,
            triggers=(TriggerSpec(event, mode),)))
    r.validate(); r.freeze(); return r


class LotusTroublemakerTests(unittest.TestCase):
    def game(self, hand=(ROOT,), *, deck=(), board=(), enemy=(), other_hand=(), seed=243470):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, deck=deck+(FILL,)*12, board=board,
                        mana=30, max_mana=10, temporary_mana=20),
            PlayerSetup('HERO_08', hand=other_hand, board=enemy, deck=(FILL,)*12,
                        mana=30, max_mana=10, temporary_mana=20)), seed=seed), registry('writer'))
    def source(self, g, cid=ROOT, pid=None):
        return next(i for i in g.state.players[pid or g.state.active_player].hand if g.state.entities[i].card_id == cid)
    def play(self, g, cid=ROOT, target=None, *, eid=None):
        return g.apply(PlayCard(g.state.active_player, eid or self.source(g, cid), target))
    def count(self, g, eid): return progress_ability(g.state.entities[eid]).progress_completions
    def shots(self, result): return tuple(e for e in result.events if e.kind == 'damage_dealt')
    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        return g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        r = registry('reader' if g.registry is registry('writer') else 'writer')
        saved = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(saved, r)
        for candidate in (other, g.clone(), replay(build_replay(g), r)):
            self.assertEqual(candidate.snapshot(), saved)
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for secret in ('progress_keys', 'resolution_frame', 'split_damage_history', 'rng_state'):
                self.assertNotIn(secret, wire)
        return other

    def test_a00_complete_source_bilingual_faces_and_exact_assembled_card(self):
        from tools.card_batch import check_face
        d = load_batch(); raw = d['cards'][0]['record']
        for item in d['official_observations']:
            check_face(raw, item['face'], item['locale'], d['display_normalizations'][ROOT])
        self.assertEqual(registry('writer').card(ROOT), assembled().card(ROOT))
        self.assertEqual((raw['cost'], raw['attack'], raw['health'], raw['tags']['TAG_SCRIPT_DATA_NUM_1']), (3, 2, 2, 1))

    def test_b00_base_one_unit_ignores_spell_damage(self):
        g = self.game(board=('EX1_012',)); result = self.play(g)
        self.assertEqual([e.amount for e in self.shots(result)], [1])
        root = g.state.split_damage_history[-1]
        self.assertEqual((root.request.amount, root.quote.spell_bonus, root.request.kind), (1, 0, DamageKind.MINION_ABILITY))
        self.portable(g)

    def test_b01_hand_two_original_paid_plays_produce_three_independent_shots(self):
        g = self.game((ROOT, TWO, TWO)); source = self.source(g)
        self.play(g, TWO); self.play(g, TWO); self.assertEqual(self.count(g, source), 2)
        result = self.play(g); self.assertEqual([e.amount for e in self.shots(result)], [1, 1, 1])
        self.assertEqual(g.state.players[1].mana, 23); self.portable(g)

    def test_b02_deck_growth_survives_real_draw_then_grows_in_hand(self):
        g = self.game((TWO, TWO, IN), deck=(ROOT,)); source = g.state.players[1].deck[0]
        self.play(g, TWO); self.assertEqual(self.count(g, source), 1)
        self.assertFalse(any(e.kind == 'hand_progressed' for e in g.events if e.target_id == source))
        self.play(g, IN, source); self.play(g, TWO); self.assertEqual(self.count(g, source), 2)
        self.assertEqual(len(self.shots(self.play(g))), 3); self.portable(g)

    def test_b03_actual_two_mana_not_printed_cost_or_other_resource(self):
        g = self.game((ROOT, TWO, THREE, HEALTH, REDUCE, FREE, AUTO, SPEND)); source = self.source(g)
        self.play(g, REDUCE, self.source(g, THREE)); self.play(g, THREE)
        self.assertEqual(self.count(g, source), 1)
        self.play(g, FREE, self.source(g, TWO)); self.play(g, TWO)
        self.play(g, HEALTH); self.play(g, AUTO); self.play(g, SPEND)
        self.assertEqual(self.count(g, source), 1)
        self.assertEqual(len(self.shots(self.play(g))), 2); self.portable(g)

    def test_b04_discounted_self_play_does_not_grant_its_own_extra_shot(self):
        g = self.game((ROOT, REDUCE)); source = self.source(g)
        self.play(g, REDUCE, source); result = self.play(g)
        self.assertEqual(g.state.play_history[-1].cost, 2)
        self.assertEqual(len(self.shots(result)), 1); self.assertEqual(self.count(g, source), 0)

    def test_b05_opponent_plays_do_not_feed_my_stored_source(self):
        g = self.game((ROOT,), other_hand=(TWO,)); source = self.source(g)
        g.apply(EndTurn(1)); self.play(g, TWO); self.assertEqual(self.count(g, source), 0); self.portable(g)

    def test_b06_commit_wait_does_not_count_until_actual_play_completes(self):
        g = self.game((ROOT, TWO), board=(COMMIT,)); source = self.source(g)
        self.play(g, TWO); self.assertEqual(self.count(g, source), 0)
        g = self.portable(g); self.choose(g); self.assertEqual(self.count(g, source), 1)
        self.assertEqual(len(self.shots(self.play(g))), 2); self.portable(g)

    def test_b07_countered_two_mana_spell_still_counts_completed_play(self):
        g = self.game((ROOT, TWO), board=(COUNTER,)); source = self.source(g)
        self.play(g, TWO); self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(self.count(g, source), 1); self.assertEqual(len(self.shots(self.play(g))), 2); self.portable(g)

    def test_c00_current_copy_preserves_native_growth_base_copy_is_one(self):
        g = self.game((ROOT, TWO, COPY, BASE)); source = self.source(g)
        self.play(g, TWO); self.play(g, COPY, source); current = g.state.players[1].hand[-1]
        self.play(g, BASE, source); base = g.state.players[1].hand[-1]
        self.assertEqual((self.count(g, current), self.count(g, base)), (1, 0))
        self.assertEqual(len(self.shots(self.play(g, eid=current))), 2)
        self.assertEqual(len(self.shots(self.play(g, eid=base))), 1); self.portable(g)

    def test_c01_nonreset_hand_deck_moves_keep_count_explicit_reset_clears_it(self):
        for move in (OUT, RESET):
            with self.subTest(move=move):
                g = self.game((ROOT, TWO, move, IN)); source = self.source(g)
                self.play(g, TWO); self.play(g, move, source); self.play(g, IN, source)
                self.assertEqual(self.count(g, source), int(move == OUT))
                self.assertEqual(len(self.shots(self.play(g))), 2 if move == OUT else 1); self.portable(g)

    def test_c02_board_no_longer_grows_direct_activation_keeps_current_card_value_bounce_resets(self):
        g = self.game((ROOT, TWO, TWO, TRIGGER, BOUNCE)); source = self.source(g)
        self.play(g, TWO); self.play(g); self.play(g, TWO)
        self.assertEqual(self.count(g, source), 1)
        self.assertEqual(len(self.shots(self.play(g, TRIGGER, source))), 2)
        self.play(g, BOUNCE, source); self.assertEqual(self.count(g, source), 0)
        self.assertEqual(len(self.shots(self.play(g))), 1); self.portable(g)

    def test_d00_frozen_battlecry_context_keeps_count_across_start_silence_or_morph(self):
        for mode in (SILENCE, MORPH):
            with self.subTest(mode=mode):
                g = self.game((ROOT, TWO), board=(mode,)); source = self.source(g)
                self.play(g, TWO); self.assertEqual(len(self.shots(self.play(g))), 2)
                if mode == MORPH: self.assertEqual(g.state.entities[source].card_id, FILL)
                else: self.assertTrue(g.state.entities[source].silenced)
                self.portable(g)

    def test_d01_wait_restore_source_morph_does_not_change_accepted_remaining_packets(self):
        g = self.game((ROOT, TWO), board=(WAIT,)); source = self.source(g)
        self.play(g, TWO); first = self.play(g); self.assertEqual(len(self.shots(first)), 1)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g)
        result = self.choose(g, 'morph'); self.assertEqual(len(self.shots(result)), 1)
        self.assertEqual(g.state.entities[source].card_id, FILL)
        self.assertEqual(g.state.split_damage_history[-1].request.amount, 2); self.portable(g)

    def test_d02_failed_wait_restores_rng_original_count_and_pending_packet(self):
        g = self.game((ROOT, TWO), board=(WAIT,)); self.play(g, TWO); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        while g.state.pending_choice is not None: self.choose(g)
        self.portable(g)

    def test_d03_source_death_after_first_packet_does_not_cancel_remaining_shots(self):
        g = self.game((ROOT, TWO, TWO), board=(KILL,)); source = self.source(g)
        self.play(g, TWO); self.play(g, TWO)
        self.assertEqual(len(self.shots(self.play(g))), 3)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD); self.portable(g)

    def test_d04_current_enemy_pool_rechecks_after_first_minion_dies(self):
        g = self.game((ROOT, TWO, TWO), enemy=(TINY,), seed=0); target = g.state.players[2].board[0]
        self.play(g, TWO); self.play(g, TWO); shots = self.shots(self.play(g))
        self.assertEqual([e.target_id for e in shots], [target, g.state.players[2].hero_id, g.state.players[2].hero_id])
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD); self.portable(g)

    def test_e00_foreign_history_carrier_and_fresh_whole_card_replay_use_printed_base(self):
        for driver in (MIRROR, HISTORY):
            with self.subTest(driver=driver):
                g = self.game((ROOT, TWO, driver)); self.play(g, TWO)
                self.assertEqual(len(self.shots(self.play(g))), 2)
                self.assertEqual(len(self.shots(self.play(g, driver))), 1); self.portable(g)

    def test_e01_second_player_uses_own_stored_counter(self):
        g = self.game(other_hand=(ROOT, TWO)); g.apply(EndTurn(1))
        self.play(g, TWO); self.assertEqual(len(self.shots(self.play(g))), 2); self.portable(g)


if __name__ == '__main__': unittest.main()
