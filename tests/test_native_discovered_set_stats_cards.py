"""Hero's Welcome uses the selected actual summon and the ordinary stat setter."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_discovered_set_stats_cards import CARD, BODY, load_batch, register_native_discovered_set_stats_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword,
    PlayCard, PlayerSetup, Rarity, Registry, RewindSpec, Scenario, SelectChoice, SpellRepeatSpec,
    SummonQuantitySpec, Zone)
from hs_sim.engine.discovery_summons import SetDiscoveredMinionStats
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Summon, Transform)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import DiscoverFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial

P = 'k153.'
HERO, PLAIN, A, B, OWN, OTHER, COMMON, UNKNOWN = (
    P + s for s in ('hero', 'plain', 'legend_a', 'legend_b', 'legend_mage', 'legend_warrior', 'common', 'unknown'))
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.NONE, tribes=())
CTX = GenerationContext('k153', 'experimental')


@lru_cache(maxsize=6)
def registry(role, mode='normal'):
    assert role in ('writer', 'reader') and mode in ('normal', 'empty', 'unknown')
    r = Registry('k153-native-discovered-stats-' + mode + '-v1')
    register_native_discovered_set_stats_cards(r)
    r.register_card(CardDefinition(HERO, 'Mage fixture', CardType.HERO, health=30,
        metadata=CardMetadata(False, (CardClass.MAGE,), Rarity.NONE, tribes=())))
    r.register_card(CardDefinition(PLAIN, 'Plain fixture', CardType.MINION, attack=1, health=3, metadata=META))
    for cid, cls, rarity in ((A, CardClass.NEUTRAL, Rarity.LEGENDARY),
            (B, CardClass.NEUTRAL, Rarity.LEGENDARY), (OWN, CardClass.MAGE, Rarity.LEGENDARY),
            (OTHER, CardClass.WARRIOR, Rarity.LEGENDARY), (COMMON, CardClass.NEUTRAL, Rarity.COMMON),
            (UNKNOWN, CardClass.NEUTRAL, Rarity.LEGENDARY)):
        d = CardDefinition(cid, cid, CardType.MINION, cost=5, attack=2, health=4,
            metadata=CardMetadata(True, (cls,), rarity, tribes=()))
        if cid != UNKNOWN:
            r.register_card(d)
        r.register_pool_card(PoolCard.from_definition(d))
    members = (OTHER, COMMON) if mode == 'empty' else (A, B, OWN, OTHER, COMMON)
    if mode == 'unknown': members = (*members, UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards', 'k153-v1', 'k153', 'experimental',
        tuple(PoolMember(cid) for cid in members), complete=True))
    r.register_card(CardDefinition(P + 'quantity', 'Quantity fixture', CardType.MINION, health=8,
        summon_quantities=(SummonQuantitySpec(),), metadata=META))
    r.register_card(CardDefinition(P + 'repeat', 'Repeat spell fixture', CardType.MINION, health=8,
        spell_repeats=(SpellRepeatSpec(class_mode='any'),), metadata=META))
    r.register_card(CardDefinition(P + 'rewind', 'Rewind alias fixture', CardType.SPELL, cost=8,
        keywords=(Keyword.REWIND,), rewind=RewindSpec(), on_play=BODY, metadata=META))
    r.register_behavior(P + 'auto', lambda c: (CastSpell(c.player_id, CARD, c.source_id, choices='random'),))
    r.register_card(CardDefinition(P + 'auto', 'Automatic spell fixture', CardType.SPELL,
        on_play=P + 'auto', metadata=META))
    def fail(c): raise ResolutionError('deliberate K153 rollback')
    r.register_behavior(P + 'raise_failure', fail)
    def eligible(c):
        return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id == A
    r.register_trigger_condition(P + 'eligible', eligible)
    for action in ('wait', 'kill', 'reenter', 'control', 'transform', 'damage', 'fail', 'terminal'):
        key = P + action
        def watch(c, action=action):
            target = c.event.target_id
            if action == 'wait':
                return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id),)
            if action == 'kill': return (Destroy(target), SummonByCard(c.player_id, (SummonEntryMaterial(A),), SummonCause.capture(c)))
            if action == 'reenter': return (ReturnToHand(target), SummonByCard(c.player_id, (SummonEntryMaterial(A),), SummonCause.capture(c)))
            if action == 'control': return (ChangeControl(target, 2),)
            if action == 'transform': return (Transform(target, PLAIN),)
            if action == 'damage': return (GainArmor(c.player_id, c.state.entities[target].attack), Damage(target, 1, c.source_id))
            if action == 'terminal': return (Damage(c.state.players[2].hero_id, 100, c.source_id),)
            return (InvokeBehavior(P + 'raise_failure', c.source_id, c.player_id),)
        r.register_behavior(key, watch)
        event = 'stats_changed' if action in ('fail', 'terminal') else 'minion_summoned'
        r.register_card(CardDefinition(key, key, CardType.MINION, health=8, metadata=META,
            limited_triggers=(LimitedTriggerSpec(event, key, condition_id=P + 'eligible'),)))
    r.validate(); r.freeze()
    return r


class NativeDiscoveredSetStatsTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(), mode='normal', context=CTX):
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=(PLAIN,) * 6, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup(HERO, deck=(PLAIN,) * 6)), seed=112, generation_context=context), registry('writer', mode))

    def play(self, g, cid=CARD):
        state = g.state
        eid = next(i for i in state.players[1].hand if state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid))
        return eid

    def pick(self, g, cid=A):
        q = g.state.pending_choice
        option = next(o for o in q.options if o.card_id == cid)
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))

    def choose(self, g, option='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def bodies(self, g, cid=A, player=1):
        state = g.state
        return [state.entities[i] for i in state.players[player].board if state.entities[i].card_id == cid]

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot()))
        reader, writer = registry('reader', mode), registry('writer', mode)
        self.assertIsNot(reader, writer)
        self.assertEqual(reader.fingerprint(), writer.fingerprint())
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            for field in ('stat_acceptances', 'set_summoned_stats', 'discovery_summon_stats_started',
                          'discovery_summon_history', 'resolution_frame'):
                self.assertNotIn('"' + field + '"', public)
        return other

    def rehash(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return saved

    def test_actual_paid_discovery_class_rarity_one_payment_and_original_recipient(self):
        g = self.game(board=(A,)); old = self.bodies(g)[0].id
        source = self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {A, B, OWN})
        self.assertEqual(g.state.players[1].mana, 22); other = self.portable(g)
        rng = g.snapshot()['rng_state']
        for game in (g, other): self.pick(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(g.state.entities[old].attack, 2)
        new, = [m for m in self.bodies(g) if m.id != old]
        self.assertEqual((new.attack, new.health, new.max_health), (10, 10, 10))
        root, = g.state.discovery_summon_history
        self.assertEqual((root.stat_acceptances, root.status), ((0,), 'completed'))
        child = g.state.card_summon_history[root.entry_root_ids[0] - 1]
        self.assertEqual(child.deliveries[0].entity.entity_id, new.id)
        self.assertTrue(any(e.kind == 'stats_changed' and e.target_id == new.id and e.source_id == source for e in g.events))
        self.assertFalse(g.state.battlecry_history); self.portable(g)

    def test_entry_reactions_finish_before_stat_setting_and_damage_resets(self):
        g = self.game(board=(P + 'damage',)); self.play(g); self.pick(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        body, = self.bodies(g)
        self.assertEqual((body.attack, body.health, body.damage), (10, 10, 0)); self.portable(g)

    def test_automatic_spell_uses_real_attribution_without_generated_payment(self):
        g = self.game(hand=(P + 'auto',)); self.play(g, P + 'auto')
        self.assertIsNone(g.state.pending_choice)
        root, = g.state.discovery_summon_history
        self.assertEqual(root.spec.cause.cast_card_id, CARD)
        self.assertEqual(root.stat_acceptances, (0,)); self.assertEqual(g.state.players[1].mana, 30)
        new = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([(m.attack, m.health) for m in new], [(10, 10)]); self.portable(g)

    def test_rewind_retires_first_result_and_repeats_real_discovery(self):
        g = self.game(hand=(P + 'rewind',)); self.play(g, P + 'rewind'); self.pick(g)
        self.portable(g); self.choose(g, 'retry')
        self.assertFalse(self.bodies(g)); self.portable(g); self.pick(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual((len(g.state.play_history), g.state.players[1].mana), (1, 22))
        self.assertEqual([(m.attack, m.health) for m in self.bodies(g)], [(10, 10)]); self.portable(g)

    def test_waiting_entry_restores_exact_owed_setter_and_no_extra_random(self):
        g = self.game(board=(P + 'wait',)); self.play(g); self.pick(g)
        self.assertEqual(self.bodies(g)[0].attack, 2)
        self.assertEqual(g.state.discovery_summon_history[0].stat_acceptances, ())
        other = self.portable(g); rng = g.snapshot()['rng_state']
        for game in (g, other): self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(self.bodies(g)[0].attack, 10); self.portable(g)

    def test_removed_or_forged_owed_setter_rejects_waiting_restore(self):
        g = self.game(board=(P + 'wait',)); self.play(g); self.pick(g)
        for wrong in (False, True):
            bad = g.clone(); frame = bad._frame
            self.assertEqual(sum(type(w) is SetDiscoveredMinionStats for w in (*frame.prefix, *frame.continuation)), 1)
            def change(work):
                return tuple(replace(w, index=1) if type(w) is SetDiscoveredMinionStats and wrong else w
                    for w in work if wrong or type(w) is not SetDiscoveredMinionStats)
            bad._frame = replace(frame, prefix=change(frame.prefix), continuation=change(frame.continuation))
            with self.assertRaises((ValueError, SnapshotError)):
                Game.from_snapshot(bad.snapshot(), registry('reader'))

    def test_quantity_extras_remain_independent_original_only_set_to_ten(self):
        g = self.game(board=(P + 'quantity',)); self.play(g); self.pick(g)
        self.assertEqual([(m.attack, m.health) for m in self.bodies(g)], [(10, 10), (2, 4)])
        self.portable(g)

    def test_repeated_spell_accepts_independent_discoveries_and_original_recipients(self):
        g = self.game(board=(P + 'repeat',)); self.play(g); self.pick(g, A)
        self.assertIsNotNone(g.state.pending_choice); self.portable(g); self.pick(g, B)
        self.assertEqual([(m.attack, m.health) for m in self.bodies(g, A)], [(10, 10)])
        self.assertEqual([(m.attack, m.health) for m in self.bodies(g, B)], [(10, 10)])
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual([r.stat_acceptances for r in g.state.discovery_summon_history], [(0,), (0,)])
        self.assertEqual(g.state.players[1].mana, 22); self.portable(g)

    def test_dead_departed_transformed_and_transferred_originals_do_not_rebind(self):
        for action in ('kill', 'reenter', 'transform', 'control'):
            with self.subTest(action=action):
                g = self.game(board=(P + action,)); self.play(g); self.pick(g)
                self.assertEqual(g.state.discovery_summon_history[0].stat_acceptances, (0,))
                self.assertTrue(all(m.attack == 2 for m in self.bodies(g)))
                self.assertTrue(all(m.attack == 2 for m in self.bodies(g, player=2)))
                self.portable(g)

    def test_full_board_acknowledges_failed_actual_entry_without_changing_old_minions(self):
        g = self.game(board=(A,) * 7); self.play(g); self.pick(g)
        self.assertEqual([m.attack for m in self.bodies(g)], [2] * 7)
        self.assertEqual(g.state.discovery_summon_history[0].stat_acceptances, (0,)); self.portable(g)

    def test_empty_complete_pool_has_no_choice_or_rng_draw(self):
        g = self.game(mode='empty'); before = g.snapshot()['rng_state']; self.play(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(g.state.discovery_summon_history[0].stat_acceptances, ()); self.portable(g, 'empty')

    def test_unknown_eligible_or_missing_context_rolls_back_paid_action(self):
        for mode, context in (('unknown', CTX), ('normal', None)):
            g = self.game(mode=mode, context=context); saved = g.snapshot()
            with self.assertRaises((ValueError, ResolutionError)): self.play(g)
            self.assertEqual(g.snapshot(), saved)

    def test_failed_stat_reaction_restores_original_choice_rng_payment_and_delivery(self):
        g = self.game(board=(P + 'fail',)); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g)
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_stat_triggered_terminal_keeps_acceptance_and_interrupts_parent(self):
        g = self.game(board=(P + 'terminal',)); self.play(g); self.pick(g)
        self.assertNotEqual(g.state.status, 'playing')
        self.assertEqual(g.state.discovery_summon_history[0].stat_acceptances, (0,))
        self.assertEqual(g.state.discovery_summon_history[0].status, 'interrupted'); self.portable(g)

    def test_rehashed_removed_receipt_or_acceptance_rejects_completed_restore(self):
        g = self.game(); self.play(g); self.pick(g)
        for events in (False, True):
            saved = g.snapshot()
            if events:
                saved['events'] = [e for e in saved['events'] if e['kind'] != 'discovery_summon_stats_started']
            else:
                saved['state']['discovery_summon_history'][0]['stat_acceptances'] = []
            with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(saved), registry('reader'))
        saved = g.snapshot(); saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry('reader'))

    def test_stat_setting_declaration_is_finite_and_does_not_invent_combinations(self):
        g = self.game(); self.play(g); spec = g.state.discovery_summon_history[0].spec
        for change in (dict(destination='hand'), dict(cause=None), dict(discoveries=2),
                dict(freeze_summoned=True), dict(set_summoned_stats=10), dict(source_id=None),
                dict(delivery='after_all'), dict(query=replace(spec.query, collectible=False))):
            with self.subTest(change=change):
                with self.assertRaises(ValueError): replace(spec, **change)
        self.assertIsNone(DiscoverFromPool(1, 'constructed.cards').set_summoned_stats)

    def test_real_full_source_main_assembly_and_actual_legendary_query(self):
        data = load_batch()
        self.assertEqual((len(data['cards']), len(data['official_observations'])), (1, 2))
        from hs_sim.cards.constructed import build_registry
        r = build_registry(); r.freeze()
        self.assertEqual(asdict(r.card(CARD)), asdict(registry('writer').card(CARD)))
        self.assertEqual(r.card(CARD).cost, 8)


if __name__ == '__main__': unittest.main()
