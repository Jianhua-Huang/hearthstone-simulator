"""Real native and crafted Mammoths use shared Freeze and source life cycles."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.frozen_mammoth_card import CARD, BODY, load_batch, register_frozen_mammoth_card
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import TEMPLATE, FIRST, SECOND
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, IllegalAction, Keyword, PlayerSetup, Registry, ResolutionError,
    Scenario, SnapshotError, SpellSchool, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import CraftedMinionRecipe
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial, validate_captured_card_copy
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    Freeze, GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand, Silence,
    Summon, Unfreeze)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.school_freeze import KIND, SchoolFreezeProfile, locked
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from tools import card_batch as batch

P = 'k578.'
HERO, POWER, UNIT, WATCH, FREE, WAIT_FIRE = (P+x for x in ('hero', 'power', 'unit', 'watch', 'free', 'waitfire'))
KILL, BOUNCE, QUIET, COPY, BASE, HANDCOPY, UNFREEZE, FREEZE, PREVENT, GIVE, NATURAL, RESURRECT = (
    P+x for x in ('kill', 'bounce', 'silence', 'copy', 'base', 'handcopy', 'unfreeze', 'freeze', 'prevent', 'give', 'natural', 'resurrect'))
META = CardMetadata(False, (CardClass.HUNTER,), None)
FIRST_PART, FIRE, FROST, COUNTER = 'CORE_LOOT_413', 'CORE_CS2_029', 'CORE_CS2_024', 'CORE_EX1_287'
RECIPE = CraftedMinionRecipe(TEMPLATE, FIRST_PART, CARD)
CONTEXT = GenerationContext('k578-native-school-freeze', 'experimental')


@lru_cache(None)
def original():
    return build_registry()


@lru_cache(None)
def host(mode='normal', role='writer'):
    source = original()
    if mode == 'full':
        fmt = build_cn37_local_pool_format(); r, context = fmt.registry, fmt.context
    else:
        r = Registry(P+mode); context = CONTEXT
        for cid in (FIRST_PART, TAMER, TEMPLATE, FIRE, FROST):
            card = source.card(cid)
            for behavior in (card.on_play, card.battlecry, card.deathrattle):
                if behavior is not None: r.register_behavior(behavior, source.behavior(behavior))
            r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
        r.register_crafted_minion_part(FIRST_PART)
        r.register_crafted_minion_blueprint(source.crafted_minion_blueprints[TEMPLATE])
        register_frozen_mammoth_card(r)
    r._version += ':'+P+mode
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2, on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=40, metadata=META))
    def fail(c):
        raise ResolutionError('K578 intentional native Freeze continuation failure')
    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'continue', ()),
            ChoiceOption('bad', 'fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'wait', wait)
    for cid, body, school in ((FREE, lambda c: (), SpellSchool.FIRE), (WAIT_FIRE, wait, SpellSchool.FIRE)):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, spell_school=school, metadata=META))
    def resurrect(c):
        row = next(d for d in reversed(c.state.death_history) if d.card_id in (CARD, RECIPE.card_id))
        return (ResurrectMinion(c.player_id, row.id, source_id=c.source_id, cause=SummonCause.capture(c)),)
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        BASE: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        HANDCOPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, mode='current', source_id=c.source_id),),
        UNFREEZE: lambda c: (Unfreeze(c.target_id),),
        FREEZE: lambda c: (Freeze(c.target_id, c.source_id),),
        PREVENT: lambda c: (GrantKeyword(c.target_id, Keyword.CANT_BE_FROZEN, c.source_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        NATURAL: lambda c: (Summon(c.player_id, CARD),),
        RESURRECT: resurrect,
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        spec = None if cid in (NATURAL, RESURRECT) else TargetSpec(TargetMode.REQUIRED,
            zones=(Zone.HAND if cid == HANDCOPY else Zone.BOARD,), kinds=(CardType.MINION,))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=spec, metadata=META))
    def watch(c):
        e = c.state.entities.get(c.event.target_id)
        if c.event.kind != 'unfrozen' or e is None or e.card_id not in (CARD, RECIPE.card_id): return ()
        return (InvokeBehavior(P+'fail', c.source_id, c.player_id),) if mode == 'fail' else wait(c)
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=100, metadata=META,
        triggers=(TriggerSpec('unfrozen', P+'watch'),)))
    for pid, cid in ((FIRST, FIRST_PART), (SECOND, CARD)):
        r.register_pool(PoolDefinition(pid, 'explicit-native-school-freeze-v1', context.target_id,
            context.mode, (PoolMember(cid),), complete=True))
    r.validate(); return r, context


def fixture(mode='normal', role='writer'):
    return host(mode, role)[0]


class FrozenMammothTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(CARD, FIRE), *, own=(), enemy=(UNIT,), opposing=(), player=1, active=None, mode='normal'):
        self.mode = mode; r, context = host(mode)
        if mode in ('wait', 'fail'): own = (*own, WATCH)
        players = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else opposing, board=own if p == player else enemy,
            deck=(UNIT,)*8, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        context = replace(context, starting_decks=tuple(p.deck for p in players))
        return Game.from_scenario(Scenario(players, active_player=active or player, seed=578,
            generation_context=context), r)

    def cycle(self, g, player=1):
        g.apply(EndTurn(player)); g.apply(EndTurn(3-player))

    def fire(self, g, player=1):
        self.play(g, FIRE, g.state.players[3-player].hero_id, player)

    def pick(self, g, cid):
        option = next(o for o in g._frame.options if any(type(e) is ResolveCraft and e.card_id == cid for e in o.effects))
        self.choose(g, option.id)

    def craft(self, g, player=1):
        self.play(g, TAMER, player=player); self.pick(g, FIRST_PART); self.pick(g, CARD)
        return self.entity(g, RECIPE.card_id, player).id

    def test_complete_raw_bilingual_main_faces_and_original_profile_do_not_certify_a_formal_pool(self):
        data = load_batch(); row, = data['cards']; self.assertEqual(len(data['official_observations']), 2)
        for face in data['official_observations']: batch.check_face(row['record'], face['face'], face['locale'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        r = original(); self.assertIn(CARD, r.crafted_minion_parts)
        self.assertEqual(r.school_freeze_profiles[CARD], SchoolFreezeProfile(CARD, BODY))
        self.assertFalse(any(k[0] in (FIRST, SECOND) for k in r.pools))

    def test_real_paid_native_body_starts_frozen_and_two_owner_turns_cannot_naturally_thaw(self):
        g = self.game(); eid = self.play(g, CARD); self.assertEqual(g.state.players[1].mana, 26)
        for _ in range(2):
            self.cycle(g); self.assertTrue(g.state.entities[eid].frozen); self.assertTrue(locked(g.state.entities[eid]))
        saved = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(Attack(1, eid, g.state.players[2].board[0]))
        self.assertEqual(g.snapshot(), saved)

    def test_both_actors_real_tamers_and_composed_paid_bodies_keep_original_cost_and_native_gate(self):
        for player in (1, 2):
            with self.subTest(player=player):
                g = self.game((TAMER,), player=player); eid = self.craft(g, player)
                self.play(g, RECIPE.card_id, player=player)
                self.assertEqual(g.state.entities[eid].components, (FIRST_PART, CARD))
                self.assertTrue(g.state.entities[eid].frozen); self.assertTrue(locked(g.state.entities[eid]))
                self.assertEqual(g.state.players[player].mana, 29-g.registry.card(RECIPE.card_id).cost)

    def test_successful_own_fire_releases_original_gate_and_shared_attack_becomes_legal(self):
        g = self.game(); eid = self.play(g, CARD); self.cycle(g); self.fire(g)
        self.assertFalse(g.state.entities[eid].frozen); self.assertFalse(locked(g.state.entities[eid]))
        target = g.state.players[2].board[0]; g.apply(Attack(1, eid, target))
        self.assertEqual(g.state.entities[target].health, 34)

    def test_actual_frost_spell_cannot_release_fire_gate(self):
        g = self.game((CARD, FROST)); eid = self.play(g, CARD)
        self.play(g, FROST, g.state.players[2].board[0])
        self.assertTrue(g.state.entities[eid].frozen); self.assertTrue(locked(g.state.entities[eid]))

    def test_opponent_fire_does_not_release_original_controller_gate(self):
        g = self.game((CARD,), opposing=(FIRE,)); eid = self.play(g, CARD)
        g.apply(EndTurn(1)); self.fire(g, 2)
        self.assertTrue(g.state.entities[eid].frozen); self.assertTrue(locked(g.state.entities[eid]))

    def test_fire_while_native_card_is_in_hand_does_not_pre_unlock_later_entry(self):
        g = self.game(); self.fire(g); eid = self.play(g, CARD)
        self.assertTrue(g.state.entities[eid].frozen); self.assertTrue(locked(g.state.entities[eid]))

    def test_zero_mana_fire_cast_releases_without_spell_mana_budget(self):
        g = self.game((CARD, FREE)); eid = self.play(g, CARD); self.play(g, FREE)
        self.assertFalse(g.state.entities[eid].frozen); self.assertFalse(locked(g.state.entities[eid]))
        self.assertEqual(g.state.players[1].mana, 26)

    def test_real_counterspell_blocks_fire_completion_and_keeps_native_gate(self):
        g = self.game(opposing=(COUNTER,), active=2, mode='full')
        self.play(g, COUNTER, player=2); g.apply(EndTurn(2)); eid = self.play(g, CARD); self.fire(g)
        self.assertEqual(g.state.cast_history[-1].failure, 'countered')
        self.assertTrue(g.state.entities[eid].frozen); self.assertTrue(locked(g.state.entities[eid]))

    def test_natural_summon_and_real_resurrection_each_initialize_fresh_native_freeze(self):
        g = self.game((NATURAL, KILL, RESURRECT)); self.play(g, NATURAL)
        eid = self.entity(g, CARD, zone='board').id; self.assertTrue(g.state.entities[eid].frozen)
        self.play(g, KILL, eid); self.play(g, RESURRECT)
        new = self.entity(g, CARD, zone='board'); self.assertNotEqual(new.id, eid)
        self.assertTrue(new.frozen); self.assertTrue(locked(new)); self.assertFalse(g.state.battlecry_history)

    def test_current_and_base_board_copies_start_fresh_native_gates_without_relocking_original(self):
        g = self.game((CARD, FIRE, COPY, BASE)); eid = self.play(g, CARD); self.fire(g)
        self.play(g, COPY, eid); self.play(g, BASE, eid)
        copies = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == CARD and i != eid]
        self.assertEqual(len(copies), 2); self.assertTrue(all(e.frozen and locked(e) for e in copies))
        self.assertFalse(g.state.entities[eid].frozen); self.assertFalse(locked(g.state.entities[eid]))

    def test_current_hand_copy_keeps_independent_gate_and_both_real_entries_freeze(self):
        g = self.game((CARD, HANDCOPY)); eid = self.entity(g, CARD).id; self.play(g, HANDCOPY, eid)
        self.play(g, CARD); self.play(g, CARD)
        bodies = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == CARD]
        self.assertEqual(len(bodies), 2); self.assertTrue(all(e.frozen and locked(e) for e in bodies))
        self.assertEqual(len({next(a.id for a in e.abilities if a.kind == KIND) for e in bodies}), 2)

    def test_current_silenced_copy_drops_printed_freeze_but_base_copy_rebuilds_gate(self):
        g = self.game((CARD, QUIET, COPY, BASE)); eid = self.play(g, CARD); self.play(g, QUIET, eid)
        self.play(g, COPY, eid); self.play(g, BASE, eid)
        copies = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == CARD and i != eid]
        current, = [e for e in copies if e.silenced]; base, = [e for e in copies if not e.silenced]
        self.assertFalse(current.frozen); self.assertFalse(locked(current))
        self.assertTrue(base.frozen); self.assertTrue(locked(base))

    def test_normal_bounce_and_paid_replay_reset_original_gate_after_prior_fire(self):
        g = self.game((CARD, FIRE, BOUNCE)); eid = self.play(g, CARD); self.fire(g)
        old_presence = g.state.entities[eid].board_presence_id; self.play(g, BOUNCE, eid); self.play(g, CARD)
        self.assertNotEqual(g.state.entities[eid].board_presence_id, old_presence)
        self.assertTrue(g.state.entities[eid].frozen); self.assertTrue(locked(g.state.entities[eid]))

    def test_shared_silence_removes_native_gate_and_ordinary_freeze(self):
        g = self.game((CARD, QUIET)); eid = self.play(g, CARD); self.cycle(g); self.play(g, QUIET, eid)
        self.assertFalse(g.state.entities[eid].frozen); self.assertFalse(locked(g.state.entities[eid]))
        g.apply(Attack(1, eid, g.state.players[2].board[0]))

    def test_shared_cannot_be_frozen_releases_native_gate_and_prevents_relocking(self):
        g = self.game((CARD, PREVENT)); eid = self.play(g, CARD); self.play(g, PREVENT, eid)
        self.assertFalse(g.state.entities[eid].frozen); self.assertFalse(locked(g.state.entities[eid]))
        self.cycle(g); self.assertFalse(g.state.entities[eid].frozen)

    def test_control_change_keeps_gate_but_only_new_controller_fire_releases_it(self):
        g = self.game((CARD, FIRE, GIVE), opposing=(FIRE,)); eid = self.play(g, CARD)
        self.play(g, GIVE, eid); self.fire(g); self.assertTrue(g.state.entities[eid].frozen)
        g.apply(EndTurn(1)); self.fire(g, 2)
        self.assertFalse(g.state.entities[eid].frozen); self.assertFalse(locked(g.state.entities[eid]))

    def test_explicit_unfreeze_uses_shared_release_and_does_not_relock_on_next_owner_turn(self):
        g = self.game((CARD, UNFREEZE)); eid = self.play(g, CARD); self.play(g, UNFREEZE, eid)
        self.cycle(g); self.assertFalse(g.state.entities[eid].frozen); self.assertFalse(locked(g.state.entities[eid]))

    def test_later_ordinary_freeze_can_thaw_normally_and_another_fire_still_unfreezes(self):
        g = self.game((CARD, FIRE, FIRE, FREEZE, FREEZE)); eid = self.play(g, CARD); self.fire(g)
        self.play(g, FREEZE, eid); self.cycle(g); self.cycle(g)
        self.assertFalse(g.state.entities[eid].frozen); self.assertFalse(locked(g.state.entities[eid]))
        self.play(g, FREEZE, eid); self.fire(g); self.assertFalse(g.state.entities[eid].frozen)

    def test_fire_payload_wait_keeps_freeze_until_successful_completion_and_restores_exact_frame(self):
        g = self.game((CARD, WAIT_FIRE)); eid = self.play(g, CARD); self.play(g, WAIT_FIRE)
        self.assertTrue(g.state.entities[eid].frozen); saved = g.snapshot(); other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'K578 intentional'): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, other): self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertFalse(g.state.entities[eid].frozen)

    def test_unfreeze_notification_wait_restores_once_gate_release_without_private_profile_leak(self):
        g = self.game(mode='wait'); eid = self.play(g, CARD); self.fire(g)
        self.assertFalse(g.state.entities[eid].frozen); other = self.portable(g)
        for current in (g, other): self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot())
        for player in (1, 2): self.assertNotIn('school_freeze', json.dumps(g.observe(player)))

    def test_failed_unfreeze_reaction_rolls_back_fire_payment_cast_and_original_gate(self):
        g = self.game(mode='fail'); self.play(g, CARD); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K578 intentional'): self.fire(g)
        self.assertEqual(g.snapshot(), saved)

    def test_both_original_crafting_menus_restore_with_native_secondary_and_full_host_play_works(self):
        g = self.game((TAMER, FIRE), mode='full'); self.play(g, TAMER); self.portable(g)
        self.pick(g, FIRST_PART); self.portable(g); self.pick(g, CARD)
        eid = self.entity(g, RECIPE.card_id).id; self.play(g, RECIPE.card_id); self.fire(g)
        self.assertFalse(g.state.entities[eid].frozen); self.assertFalse(locked(g.state.entities[eid]))

    def test_rehashed_gate_body_source_and_missing_frozen_bit_are_rejected(self):
        g = self.game(); eid = self.play(g, CARD); saved = g.snapshot()
        for field in ('body', 'source', 'frozen'):
            with self.subTest(field=field):
                bad = deepcopy(saved); entity = bad['state']['entities'][str(eid)]
                row = next(a for a in entity['abilities'] if a['kind'] == KIND)
                if field == 'body': row['behavior_id'] = P+'noop'
                elif field == 'source': row['source_id'] = g.state.players[1].hero_id
                else: entity['frozen_until_owner_turn'] = None
                bad['state_hash'] = canonical_hash(bad['state'])
                with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture('normal', 'independent-reader'))

    def test_native_profile_and_gate_reject_duplicate_source_wrong_school_or_extra_fields(self):
        r = build_registry()
        with self.assertRaises(ValueError): r.register_school_freeze_profile(SchoolFreezeProfile(CARD, BODY))
        for school in (SpellSchool.FROST, 'fire'):
            with self.assertRaises(ValueError): SchoolFreezeProfile(CARD, BODY, school)
        g = self.game(); eid = self.play(g, CARD); row = next(a for a in g.state.entities[eid].abilities if a.kind == KIND)
        with self.assertRaisesRegex(ValueError, 'pure removable'): replace(row, expires_turn=5)

    def test_captured_hand_copy_material_cannot_borrow_another_physical_gate_source(self):
        g = self.game((CARD,)); entity = self.entity(g, CARD)
        material = CapturedCardCopyMaterial.capture(g.state, entity)
        validate_captured_card_copy(g.state, g.registry, material)
        abilities = tuple(replace(a, source_id=g.state.players[1].hero_id) if a.kind == KIND else a
            for a in material.local.abilities)
        bad = replace(material, local=replace(material.local, abilities=abilities))
        with self.assertRaisesRegex(ValueError, 'School Freeze'):
            validate_captured_card_copy(g.state, g.registry, bad)


if __name__ == '__main__':
    unittest.main()
