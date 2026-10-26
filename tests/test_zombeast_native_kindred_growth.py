"""Original Kindred and stored growth execute on actual crafted physical bodies."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER
from hs_sim.cards.storm_gates_card import TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_native_kindred_growth import (PARTS, load_batch,
    register_zombeast_native_kindred_growth)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, PlayerSetup, ResolutionError, Scenario, SnapshotError,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import CraftedMinionRecipe, native_domains, validate_part_shape
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.effects import (Buff, ChoiceOption, Destroy, Draw, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.kindred_targets import profile_for_definition
from hs_sim.engine.pools import PoolDefinition, PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k576.'
HERO, POWER, UNIT, WATCH = (P+x for x in ('hero', 'power', 'unit', 'watch'))
KILL, BOUNCE, SILENCE, BOOST, STORE, HANDCOPY, DECKCOPY, BASECOPY, FORGE = (
    P+x for x in ('kill', 'bounce', 'silence', 'boost', 'store', 'handcopy', 'deckcopy', 'basecopy', 'forge'))
META = CardMetadata(False, (CardClass.HUNTER,), None)
SECOND_PART, UNDEAD, CHALLENGER, YETI = 'LOOT_258', 'CORE_CS2_231', 'TLC_251', 'CORE_CS2_182'


def recipe(part):
    return CraftedMinionRecipe(TEMPLATE, part, SECOND_PART).card_id


@lru_cache(None)
def host(mode='END_015|normal', role='writer'):
    part, variant = mode.split('|'); fmt = build_cn37_local_pool_format(); r = fmt.registry
    r._version = r.version+':'+P+mode
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2, on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=100, metadata=META))
    def fail(c):
        raise ResolutionError('K576 intentional native continuation failure')
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        SILENCE: lambda c: (Silence(c.target_id),),
        BOOST: lambda c: (BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]), attack=3, source_id=c.source_id),),
        STORE: lambda c: (MoveCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, Zone.DECK, position='top', source_id=c.source_id),),
        HANDCOPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, mode='current', source_id=c.source_id),),
        DECKCOPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, destination=Zone.DECK, mode='current', position='top', source_id=c.source_id),),
        BASECOPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, mode='base', source_id=c.source_id),),
        FORGE: lambda c: (InvokeBehavior(r.card('END_015').on_play, c.target_id, c.player_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        zones = (Zone.HAND,) if cid in (BOOST, STORE, HANDCOPY, DECKCOPY, BASECOPY) else (Zone.BOARD,)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(TargetMode.REQUIRED, zones=zones, kinds=(CardType.MINION,), relation='friendly')))
    def watch(c):
        event = c.event
        eid = event.target_id if event.kind == 'hand_progressed' else event.source_id
        source = c.state.entities.get(eid)
        if source is None or source.card_id != recipe(part): return ()
        if (variant, event.kind) not in (('entry', 'minion_summoned'),
                ('generate', 'card_added_to_hand'), ('progress', 'hand_progressed')): return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'continue', ()),
            ChoiceOption('boost', 'boost actual body', (Buff(source.id, 3, 0, c.source_id),)),
            ChoiceOption('bad', 'fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=100, metadata=META,
        triggers=tuple(TriggerSpec(event, P+'watch') for event in
            ('minion_summoned', 'card_added_to_hand', 'hand_progressed'))))
    for pool, cid in ((FIRST, part), (SECOND, SECOND_PART)):
        r.register_pool(PoolDefinition(pool, 'explicit-kindred-growth-v1', fmt.context.target_id,
            fmt.context.mode, (PoolMember(cid),), complete=True))
    if variant == 'unadapted': r._crafted_minion_parts.remove(part)
    r.validate(); return r, fmt


def fixture(mode='END_015|normal', role='writer'):
    return host(mode, role)[0]


class ZombeastNativeKindredGrowthTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, part='END_015', *, hand=(TAMER,), own=(), enemy=(UNIT,), variant='normal', player=1):
        self.mode = part+'|'+variant; r, fmt = host(self.mode)
        if variant in ('entry', 'generate', 'progress'): own = (*own, WATCH)
        players = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else (), board=own if p == player else enemy,
            deck=(YETI,)*8, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        context = replace(fmt.context, starting_decks=tuple(p.deck for p in players))
        return Game.from_scenario(Scenario(players, active_player=player, seed=576,
            generation_context=context), r)

    def pick(self, g, cid):
        option = next(o for o in g._frame.options if any(type(x) is ResolveCraft and x.card_id == cid for x in o.effects))
        self.choose(g, option.id)

    def craft(self, g, part, player=1):
        self.play(g, TAMER, player=player); self.pick(g, part); self.pick(g, SECOND_PART)
        return self.entity(g, recipe(part), player).id

    def prior_undead(self, g, player=1):
        self.play(g, UNDEAD, player=player); g.apply(EndTurn(player)); g.apply(EndTurn(3-player))

    def cycle(self, g, player=1):
        g.apply(EndTurn(player)); g.apply(EndTurn(3-player))

    def created(self, g, source):
        return [g.state.entities[e.target_id] for e in g.events if e.kind == 'card_created' and e.source_id == source]

    def test_complete_original_faces_zero_attack_and_auxiliary_profiles_are_pinned(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['existing_dependencies']}
        self.assertEqual((len(rows), len(data['official_observations'])), (3, 6))
        for face in data['official_observations']:
            batch.check_face(rows[face['card_id']], face['face'], face['locale'],
                numeric_normalizations=data['numeric_normalizations'].get(face['card_id']))
        r = fixture(); self.assertEqual(r.card('TLC_827').attack, 0)
        self.assertTrue(set(PARTS) <= set(r.crafted_minion_parts))
        self.assertFalse(any(k[0] in (FIRST, SECOND) for k in build_registry().pools))

    def test_all_three_actual_tamers_and_paid_bodies_preserve_original_components_and_payment(self):
        for index, part in enumerate(PARTS):
            with self.subTest(part=part):
                player = 1+index%2; g = self.game(part, player=player); eid = self.craft(g, part, player)
                face = g.registry.card(recipe(part)); self.play(g, face.id, player=player)
                self.assertEqual(g.state.entities[eid].components, (part, SECOND_PART))
                self.assertEqual(g.state.players[player].mana, 29-face.cost)
                self.assertFalse(any(x.source_id == eid for x in g.state.battlecry_history))

    def test_rex_inactive_play_still_keeps_original_deathrattle_get_and_two_mana_discount(self):
        part = 'END_015'; g = self.game(part, hand=(TAMER, KILL)); eid = self.craft(g, part)
        self.play(g, recipe(part)); self.assertFalse(g.state.kindred_history[-1].condition.matched)
        self.assertFalse(self.created(g, eid)); self.play(g, KILL, eid)
        new, = self.created(g, eid); self.assertTrue(g.registry.card(new.card_id).deathrattle)
        self.assertEqual(new.cost, max(0, g.registry.card(new.card_id).cost-2))
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)

    def test_rex_actual_compound_undead_query_repeats_original_get_then_deathrattle_once(self):
        part = 'END_015'; g = self.game(part, hand=(TAMER, UNDEAD, CHALLENGER, KILL))
        self.prior_undead(g); self.play(g, CHALLENGER); eid = self.craft(g, part)
        self.play(g, recipe(part)); row = g.state.kindred_history[-1]
        self.assertEqual(row.card_id, part); self.assertEqual(row.source.card_id, recipe(part))
        self.assertEqual(row.condition.query.tribes, g.registry.card(recipe(part)).metadata.tribes)
        self.assertTrue(row.condition.matched); self.assertEqual(row.plan, ('active', 'active'))
        self.assertEqual(len(self.created(g, eid)), 2); self.assertFalse(g.state.players[1].player_effects)
        self.play(g, KILL, eid); self.assertEqual(len(self.created(g, eid)), 3)

    def test_current_turn_undead_does_not_replace_real_previous_owner_turn(self):
        part = 'END_015'; g = self.game(part, hand=(TAMER, UNDEAD)); self.play(g, UNDEAD)
        eid = self.craft(g, part); self.play(g, recipe(part))
        self.assertFalse(g.state.kindred_history[-1].condition.matched); self.assertFalse(self.created(g, eid))

    def test_foreign_composition_cannot_borrow_new_original_kindred_wrapper(self):
        foreign = recipe('TLC_827'); g = self.game(hand=(FORGE,), own=(foreign,)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, FORGE, g.state.players[1].board[0])
        self.assertEqual(g.snapshot(), saved)

    def test_original_get_wait_restores_compound_query_and_rolls_back_bad_resume(self):
        part = 'END_015'; g = self.game(part, hand=(TAMER, UNDEAD), variant='generate')
        self.prior_undead(g); eid = self.craft(g, part); self.play(g, recipe(part))
        saved = g.snapshot(); other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'K576 intentional'): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, other): self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(self.created(g, eid)), 1)

    def test_inactive_matriarch_has_no_arrow_and_rejects_spurious_target_atomically(self):
        part = 'TLC_825'; g = self.game(part); eid = self.craft(g, part); saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, recipe(part), g.state.players[2].board[0])
        self.assertEqual(g.snapshot(), saved); self.play(g, recipe(part))
        self.assertFalse(g.state.kindred_history[-1].condition.matched)
        self.assertEqual(g.state.entities[eid].zone, Zone.BOARD)

    def test_matriarch_actual_compound_query_requires_enemy_and_deals_summed_attack(self):
        part = 'TLC_825'; g = self.game(part, hand=(TAMER, UNDEAD)); self.prior_undead(g)
        eid = self.craft(g, part); target = g.state.players[2].board[0]
        own = next(p for p in g.observe(1)['players'] if p['id'] == 1)
        card = next(c for c in own['hand'] if c['card_id'] == recipe(part))
        self.assertIs(card['play_conditions']['kindred'], True)
        self.assertIsNone(g.for_player(1).legal_actions()['error']); saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, recipe(part))
        self.assertEqual(g.snapshot(), saved); self.play(g, recipe(part), target)
        self.assertEqual(g.state.entities[target].health, 100-g.state.entities[eid].attack)
        self.assertEqual(g.state.kindred_history[-1].card_id, part)

    def test_matriarch_active_empty_enemy_domain_still_allows_original_play(self):
        part = 'TLC_825'; g = self.game(part, hand=(TAMER, UNDEAD), enemy=()); self.prior_undead(g)
        self.craft(g, part); self.play(g, recipe(part))
        self.assertTrue(g.state.kindred_history[-1].condition.matched)

    def test_matriarch_actual_hand_buff_and_next_kindred_repeat_use_current_summed_attack(self):
        part = 'TLC_825'; g = self.game(part, hand=(TAMER, UNDEAD, BOOST, CHALLENGER))
        self.prior_undead(g); self.play(g, CHALLENGER); eid = self.craft(g, part); self.play(g, BOOST, eid)
        target = g.state.players[2].board[0]; self.play(g, recipe(part), target)
        self.assertEqual(g.state.entities[target].health, 100-2*g.state.entities[eid].attack)
        self.assertEqual(g.state.kindred_history[-1].plan, ('active', 'active'))

    def test_matriarch_entry_wait_restores_actual_arrow_and_later_closed_owner_prefix(self):
        part = 'TLC_825'; g = self.game(part, hand=(TAMER, UNDEAD), variant='entry')
        self.prior_undead(g); eid = self.craft(g, part); target = g.state.players[2].board[0]
        self.play(g, recipe(part), target); saved = g.snapshot(); other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'K576 intentional'): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, other): self.choose(current, 'boost')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[target].health, 100-g.state.entities[eid].attack)
        self.cycle(g); self.portable(g)

    def test_one_original_growth_instance_follows_hand_then_board_owner_clock(self):
        part = 'TLC_827'; g = self.game(part); eid = self.craft(g, part)
        base = g.state.entities[eid].attack; self.cycle(g)
        self.assertEqual(g.state.entities[eid].attack, base+1)
        self.assertEqual(progress_ability(g.state.entities[eid]).progress_completions, 1)
        self.play(g, recipe(part)); self.cycle(g)
        self.assertEqual(g.state.entities[eid].attack, base+2)
        self.assertEqual(sum(a.kind == 'hand_progress' for a in g.state.entities[eid].abilities), 1)
        self.assertEqual(progress_ability(g.state.entities[eid]).progress_completions, 1)

    def test_original_growth_reaches_hand_and_deck_copies_then_real_draw_preserves_both(self):
        part = 'TLC_827'; g = self.game(part, hand=(TAMER, DECKCOPY)); eid = self.craft(g, part)
        self.play(g, DECKCOPY, eid); copy = next(i for i in g.state.players[1].deck if g.state.entities[i].card_id == recipe(part))
        old = g.state.entities[eid].attack; g.apply(EndTurn(1))
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[copy].attack), (old+1, old+1))
        self.assertEqual(g.state.entities[copy].zone, Zone.DECK)
        self.assertNotIn(recipe(part), json.dumps(g.observe(2)))
        g.apply(EndTurn(2)); self.assertEqual(g.state.entities[copy].zone, Zone.HAND)
        self.assertEqual(g.state.entities[copy].attack, old+1)
        self.assertNotEqual(progress_ability(g.state.entities[eid]).id, progress_ability(g.state.entities[copy]).id)

    def test_current_and_base_hand_copies_keep_independent_original_growth_material(self):
        part = 'TLC_827'; g = self.game(part, hand=(TAMER, HANDCOPY, BASECOPY)); eid = self.craft(g, part)
        base = g.state.entities[eid].attack; self.cycle(g); self.play(g, HANDCOPY, eid); self.play(g, BASECOPY, eid)
        copies = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == recipe(part)]
        self.assertEqual(sorted(c.attack for c in copies), [base, base+1, base+1])
        self.assertEqual(len({progress_ability(c).id for c in copies}), 3)
        self.cycle(g); copies = [g.state.entities[c.id] for c in copies]
        self.assertEqual(sorted(c.attack for c in copies), [base+1, base+2, base+2])

    def test_private_growth_wait_restores_once_completion_and_rejects_failed_resume(self):
        part = 'TLC_827'; g = self.game(part, variant='progress'); eid = self.craft(g, part)
        old = g.state.entities[eid].attack; g.apply(EndTurn(1)); saved = g.snapshot(); other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'K576 intentional'): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, other): self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.state.entities[eid].attack, old+1)

    def test_growth_bounce_resets_stored_stats_and_silence_removes_board_growth(self):
        part = 'TLC_827'; g = self.game(part, hand=(TAMER, BOUNCE, SILENCE)); eid = self.craft(g, part)
        base = g.state.entities[eid].attack; self.cycle(g); self.play(g, recipe(part)); self.play(g, BOUNCE, eid)
        self.assertEqual(g.state.entities[eid].attack, base)
        self.assertEqual(progress_ability(g.state.entities[eid]).progress_completions, 0)
        self.play(g, recipe(part)); self.play(g, SILENCE, eid); self.cycle(g)
        self.assertEqual(g.state.entities[eid].attack, base)

    def test_missing_growth_adapter_keeps_known_first_member_and_original_action_atomic(self):
        part = 'TLC_827'; g = self.game(part, variant='unadapted'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, TAMER)
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(tuple(m.card_id for m in g.registry.pool(FIRST, g._generation_context).members), (part,))

    def test_missing_target_profile_or_changed_last_declaration_does_not_half_register_batch(self):
        for kind in ('profile', 'face'):
            with self.subTest(kind=kind):
                r = batch.registration_prefix(build_registry,
                    'hs_sim.cards.zombeast_native_kindred_growth.register_zombeast_native_kindred_growth',
                    register_zombeast_native_kindred_growth)
                if kind == 'profile': r._kindred_target_profiles.pop('TLC_825')
                else: r._cards['TLC_827'] = replace(r.card('TLC_827'), attack=1)
                with self.assertRaises(TargetValidationError): register_zombeast_native_kindred_growth(r)
                self.assertFalse(set(PARTS) & set(r.crafted_minion_parts))

    def test_rehashed_original_donor_query_cannot_replace_accepted_compound_query(self):
        part = 'END_015'; g = self.game(part, hand=(TAMER, UNDEAD)); self.prior_undead(g)
        self.craft(g, part); self.play(g, recipe(part)); bad = deepcopy(g.snapshot())
        row = bad['state']['kindred_history'][-1]
        row['condition']['query']['tribes'] = ['beast']
        bad['state_hash'] = canonical_hash(bad['state'])
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture(self.mode, 'independent-reader'))

    def test_other_progress_shapes_and_multiple_growth_donors_stay_explicitly_unsupported(self):
        r = fixture(); card = r.card('TLC_827')
        with self.assertRaisesRegex(ValueError, 'stored-growth domain'):
            validate_part_shape(r, replace(card, hand_progress=replace(card.hand_progress, zone=Zone.HAND)))
        with self.assertRaisesRegex(ValueError, 'multiple native stored-growth'):
            native_domains((card, card))


if __name__ == '__main__':
    unittest.main()
