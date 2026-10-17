"""Real consumers with immutable original captures and cached independent readers."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards import simple_followup_p64_cards as cards
from hs_sim.cards.simple_followup_p64_cards import (BLOOD, ASSASSIN, STRIKE, SHAW, SILENCE,
    STAFF, SYLVANAS, ALLERIA, VEREESA, MASK, PRISON, NESPIRAH, LIMBS, ROOTS, PREFIX, POOL_ID,
    load_batch, register_simple_followup_p64_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, DeckPolicy,
    DeckSpec, EndTurn, Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario,
    SelectChoice, SpellSchool, TargetSpec, TriggerSpec, UseLocation, Zone, expand_fabled_cards, validate_deck)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.body_grants import BodyReference, GrantBattlecry
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy, ForceAttack,
    Heal, InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest

TEST = 'p64.test.'
YETI = 'CORE_CS2_182'
A, B, STEALTH, NAGA, ALL, DRUID, NEUTRAL, MAGE, UNKNOWN, SEED, CHILD, WATCH = (TEST + i for i in
    ('a', 'b', 'stealth', 'naga', 'all', 'druid', 'neutral', 'mage', 'unknown', 'seed', 'child', 'watch'))
COLOSSAL_NAGA = 'CATA_151'
MEMBERS = (NAGA, ALL, DRUID, NEUTRAL, MAGE, COLOSSAL_NAGA)
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CONTEXT = GenerationContext('p64-complete-explicit-fixture', 'experimental')
SOURCE_PIN = hashlib.sha256(Path(__file__).read_bytes() + Path(cards.__file__).read_bytes()
    + cards.BATCH_PATH.read_bytes()).hexdigest()


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None): r = build_registry()
    present = tuple(i in r.cards for i in ROOTS)
    if not any(present): register_simple_followup_p64_cards(r)
    elif not all(present): raise AssertionError('P64 requires complete assigned assembly')
    register_candidate_pool_metadata(r); r.validate(); return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    for cid, attack, health, tribes, kw, collectible in ((A, 3, 12, (), (), False),
            (B, 0, 20, (), (), False), (STEALTH, 3, 12, (), (Keyword.STEALTH,), False),
            (NAGA, 2, 6, ('naga',), (), True), (ALL, 2, 6, ('all',), (), True),
            (CHILD, 1, 5, (), (), False)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=6, attack=attack, health=health, keywords=kw,
            metadata=CardMetadata(collectible, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=tribes)))
    r.register_behavior(TEST + 'noop', lambda c: ())
    for cid, cls in ((DRUID, CardClass.DRUID), (NEUTRAL, CardClass.NEUTRAL), (MAGE, CardClass.MAGE)):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=6, on_play=TEST + 'noop',
            metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=())))
    for name, school in (('fel', SpellSchool.FEL), ('fire', SpellSchool.FIRE)):
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=TEST + 'noop', spell_school=school, metadata=META))
    r.register_behavior(TEST + 'seed', lambda c: (SummonByCard(c.player_id,
        (SummonEntryMaterial(CHILD),), SummonCause.capture(c)),))
    r.register_card(CardDefinition(SEED, 'Wave witness', CardType.MINION, health=1, deathrattle=TEST + 'seed', metadata=META))
    def fail(c): raise ResolutionError('P64 deliberate continuation failure')
    def reenter(c):
        return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), 1, cause=SummonCause.capture(c)),)
    def copy(c, mode):
        e = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == SILENCE)
        return (CopyCard(CardReference.capture(e), 1, mode=mode, source_id=c.source_id),)
    scripts = dict(hit=lambda c: (Damage(c.target_id, 2, c.source_id),),
        heal=lambda c: (Heal(c.target_id, 3, c.source_id),), kill=lambda c: (Destroy(c.target_id, c.source_id),),
        buff=lambda c: (Buff(c.target_id, 2, 3, c.source_id),), bounce=lambda c: (ReturnToHand(c.target_id),),
        silence=lambda c: (Silence(c.target_id),), fail=fail, reenter=reenter,
        force=lambda c: (ForceAttack(c.state.players[1].board[-1], c.state.players[2].board[0]),),
        acquire=lambda c: (AddToHand(1, SILENCE, c.source_id),),
        auto=lambda c: (CastSpell(c.player_id, TEST + 'fel', c.source_id),),
        copy=lambda c: copy(c, 'current'), base=lambda c: copy(c, 'base'))
    def grant_sister(c):
        target = c.state.entities[c.target_id]
        return (GrantBattlecry(BodyReference.capture(target), SYLVANAS, c.source_id),
            TriggerBattlecry(MinionReference.capture(target), c.source_id))
    scripts['grant_sister'] = grant_sister
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        driver = name in ('auto', 'copy', 'base')
        r.register_card(CardDefinition(TEST + name, name, CardType.MINION if driver else CardType.SPELL,
            health=1 if driver else 0, on_play=None if driver else TEST + name,
            battlecry=TEST + name if driver else None,
            targeting=TargetSpec() if name in ('hit', 'heal', 'kill', 'buff', 'bounce', 'silence', 'grant_sister') else None, metadata=META))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 6,
        CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('naga',)),
        battlecry=False, deathrattle=False, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p64-finite-complete-v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        event = dict(attack='stealth_lost', stats='stats_changed', health='health_resolved', cast='spell_cast_finished')[mode]
        def watch(c):
            if mode == 'attack' and dict(c.event.data).get('reason') != 'attack': return ()
            if mode == 'stats' and (c.event.source_id is None or c.state.entities[c.event.source_id].card_id not in (MASK, STRIKE)): return ()
            if mode == 'health' and (c.health_result is None or c.health_result.healed <= 0): return ()
            if mode == 'cast' and c.state.entities[c.event.source_id].card_id != TEST + 'fel': return ()
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail', (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode == 'attack':
                target = c.event.source_id
                options.append(ChoiceOption('cycle', 'Original attacker leaves and reenters',
                    (ReturnToHand(target), InvokeBehavior(TEST + 'reenter', c.source_id, 1, target))))
            if mode == 'stats': options.append(ChoiceOption('bounce', 'Original target leaves', (ReturnToHand(c.event.target_id),)))
            if mode == 'health':
                target = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == BLOOD)
                options.append(ChoiceOption('kill', 'Original Blackblood dies', (Destroy(target, c.source_id),)))
            if mode == 'cast':
                target = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == PRISON)
                options.append(ChoiceOption('destroy', 'Original location dies', (DestroyLocation(target, c.source_id),)))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_behavior(TEST + 'watch', watch)
        r.register_card(CardDefinition(WATCH, 'Actual checkpoint witness', CardType.MINION, health=20,
            triggers=(TriggerSpec(event, TEST + 'watch'),), metadata=META))
    return r


@lru_cache(maxsize=None)
def fixture_registry(mode, members, role, source_pin):
    if role not in ('writer', 'reader') or source_pin != SOURCE_PIN: raise AssertionError('Incomplete immutable fixture key')
    r = registry(mode, members); r.freeze(); return r


class SimpleFollowupP64Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(YETI,) * 12, enemy_hand=(),
            mode=None, members=MEMBERS, weapon=None):
        self.config = mode, members
        if mode: board = (WATCH,) + board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=30, max_mana=30, mana_cap=40, hand_cap=None, weapon_card_id=weapon),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,) * 12,
                mana=30, max_mana=30, mana_cap=40)), seed=6464, generation_context=CONTEXT),
            fixture_registry(mode, members, 'writer', SOURCE_PIN))

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, player=1):
        e = self.first(g, cid, player=player); g.apply(PlayCard(player, e.id, target_id=target,
            position=len(g.state.players[player].board) if e.kind in (CardType.MINION, CardType.LOCATION) else None)); return e.id

    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        reader = fixture_registry(*self.config, 'reader', SOURCE_PIN)
        self.assertIsNot(g.registry, reader); self.assertEqual(g.registry.fingerprint(), reader.fingerprint())
        saved = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved); self.assertIsNot(g.state, other.state)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.for_player(p).legal_actions()) + json.dumps(g.player_events(p))
            for key in ('rng_state', 'resolution_frame', 'behavior_id', 'source_json', 'death_history'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def cycle(self, g): g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def test_complete_twelve_definitions_forty_one_raws_thirty_strict_faces_twelve_links(self):
        from tools.card_batch import check_face
        d = load_batch(); rows = {x['record']['id']: x['record'] for k in ('cards', 'existing_dependencies', 'evidence_only') for x in d[k]}
        self.assertEqual((len(d['cards']), len(rows), len(d['official_observations'])), (12, 41, 30))
        self.assertEqual((len(d['collectible_candidate_roots']), len(d['noncollectible_ids'])), (9, 3))
        faces = {(o['card_id'], o['locale']): o['face'] for o in d['official_observations']}
        for o in d['official_observations']:
            check_face(rows[o['card_id']], o['face'], o['locale'], display_normalizations=d['display_normalizations'].get(o['card_id']))
        self.assertEqual(len(d['exact_parent_child_links']), 12)
        for e in d['exact_parent_child_links']:
            self.assertEqual(rows[e['child']]['dbf_id'], e['dbf_id']); self.assertIn(e['dbf_id'], faces[e['parent'], e['locale']]['childIds'])
        self.assertEqual({c for c, row in rows.items() if row['type'] == 'MINION' and row['tags'].get('COLOSSAL') == 1}, set(d['printed_colossal_ids']))
        self.assertFalse(d['formal_pool_complete'] or d['cn_calibrated'] or d['reachability_complete'])

    def test_old_full_definitions_pool_rows_and_appendage_pins_remain_exact(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, value in before.cards.items(): self.assertEqual(value, after.card(cid))
        for cid, value in before.pool_cards.items(): self.assertEqual(value, after.pool_card(cid))
        for cid, pin in load_batch()['existing_dependency_definition_pins'].items(): self.assertEqual(canonical_digest(asdict(after.card(cid))), pin)

    def test_blackblood_real_colossal_play_pays_once_and_reuses_three_original_limb_definitions(self):
        g = self.game(hand=(BLOOD,)); mana = g.state.players[1].mana; source = self.play(g, BLOOD)
        self.assertEqual(g.state.players[1].mana, mana - 7)
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].board}, {BLOOD, *LIMBS})
        self.assertEqual(len(g.state.players[1].board), 4); self.assertEqual(g.state.entities[source].health, 9); self.portable(g)

    def test_blackblood_actual_owner_healing_attacks_enemy_and_overheal_or_enemy_healing_do_not(self):
        g = self.game(hand=(TEST + 'hit', TEST + 'heal', TEST + 'heal'), board=(BLOOD,), enemy=(B,), enemy_hand=(TEST + 'hit', TEST + 'heal'))
        hero = g.state.players[1].hero_id; enemy = self.first(g, B, 'board', 2).id
        self.play(g, TEST + 'hit', hero); self.play(g, TEST + 'heal', hero)
        self.assertEqual(g.state.entities[enemy].health, 15)
        rng = g._rng.getstate(); self.play(g, TEST + 'heal', hero)
        self.assertEqual(g.state.entities[enemy].health, 15); self.assertEqual(g._rng.getstate(), rng)
        g.apply(EndTurn(1)); self.play(g, TEST + 'hit', hero, player=2); self.play(g, TEST + 'heal', hero, player=2)
        self.assertEqual(g.state.entities[enemy].health, 15); self.portable(g)

    def test_blackblood_original_presence_dies_in_real_heal_wait_no_attack_rng_or_rebinding(self):
        g = self.game(hand=(TEST + 'hit', TEST + 'heal'), board=(BLOOD,), enemy=(B,), mode='health')
        hero = g.state.players[1].hero_id; self.play(g, TEST + 'hit', hero); rng = g._rng.getstate()
        self.play(g, TEST + 'heal', hero); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(saved, g.snapshot()); other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'kill'); self.assertEqual(self.first(running, B, 'board', 2).health, 20)
            self.assertEqual(running._rng.getstate(), rng)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_assassin_and_shaw_capture_real_friendly_stealth_attack_and_random_original_hand_discount(self):
        g = self.game(hand=(MAGE,), board=(ASSASSIN, SHAW, STEALTH), enemy=(B,))
        attacker = self.first(g, STEALTH, 'board').id; enemy = self.first(g, B, 'board', 2).id
        g.apply(Attack(1, attacker, enemy))
        self.assertEqual((g.state.entities[attacker].attack, g.state.entities[attacker].max_health), (5, 14))
        self.assertEqual(g.quote_cost(self.first(g, MAGE).id).amount, 3)
        self.assertNotIn(Keyword.STEALTH, g.state.entities[attacker].keywords); self.assertEqual(g.state.entities[enemy].health, 15); self.portable(g)

    def test_assassin_original_attacker_reentry_skips_buff_after_real_attack_wait(self):
        g = self.game(board=(ASSASSIN, STEALTH), enemy=(B,), mode='attack')
        attacker = self.first(g, STEALTH, 'board').id; g.apply(Attack(1, attacker, self.first(g, B, 'board', 2).id)); other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'cycle'); e = running.state.entities[attacker]
            self.assertEqual(e.zone, Zone.BOARD); self.assertEqual((e.attack, e.max_health), (3, 12))
            self.assertEqual(self.first(running, B, 'board', 2).health, 20)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_shaw_nonstealth_attack_and_empty_hand_do_not_use_randomness(self):
        for attacker_card in (A, STEALTH):
            g = self.game(board=(SHAW, attacker_card), enemy=(B,)); rng = g._rng.getstate()
            g.apply(Attack(1, self.first(g, attacker_card, 'board').id, self.first(g, B, 'board', 2).id))
            self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.players[1].hand); self.portable(g)

    def test_silent_strike_rechecks_original_buffed_target_attack_and_requires_current_stealth(self):
        for cid, expected in ((STEALTH, 14), (A, 20)):
            g = self.game(hand=(STRIKE,), board=(cid,), enemy=(B,)); target = self.first(g, cid, 'board').id; rng = g._rng.getstate()
            self.play(g, STRIKE, target); self.assertEqual(g.state.entities[target].attack, 6)
            self.assertEqual(self.first(g, B, 'board', 2).health, expected)
            if cid == A: self.assertEqual(g._rng.getstate(), rng)
            self.portable(g)

    def test_silent_strike_original_target_departure_skips_damage_after_stats_wait(self):
        g = self.game(hand=(STRIKE,), board=(STEALTH,), enemy=(B,), mode='stats'); rng = g._rng.getstate()
        self.play(g, STRIKE, self.first(g, STEALTH, 'board').id); other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'bounce'); self.assertEqual(self.first(running, B, 'board', 2).health, 20)
            self.assertEqual(running._rng.getstate(), rng)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_silence_damage_one_then_any_players_stealth_attack_while_held_counts_once(self):
        g = self.game(hand=(SILENCE, SILENCE), board=(B,), enemy=(STEALTH,))
        hero = g.state.players[2].hero_id; self.play(g, SILENCE, hero); self.assertEqual(g.state.entities[hero].health, 29)
        held = self.first(g, SILENCE).id; g.apply(EndTurn(1))
        g.apply(Attack(2, self.first(g, STEALTH, 'board', 2).id, self.first(g, B, 'board').id))
        self.assertEqual(progress_ability(g.state.entities[held]).progress_completions, 1)
        g.apply(EndTurn(2)); self.play(g, SILENCE, hero); self.assertEqual(g.state.entities[hero].health, 26); self.portable(g)

    def test_silence_current_copy_keeps_held_fact_base_copy_and_later_acquisition_start_fresh(self):
        g = self.game(hand=(SILENCE, TEST + 'copy', TEST + 'base', TEST + 'acquire'), board=(STEALTH,), enemy=(B,))
        g.apply(Attack(1, self.first(g, STEALTH, 'board').id, self.first(g, B, 'board', 2).id))
        self.play(g, TEST + 'copy'); self.play(g, TEST + 'base'); self.play(g, TEST + 'acquire')
        values = [progress_ability(g.state.entities[i]).progress_completions for i in g.state.players[1].hand if g.state.entities[i].card_id == SILENCE]
        self.assertEqual(values, [1, 1, 0, 0]); self.portable(g)

    def test_fabled_native_builder_expands_complete_group_and_requires_exact_physical_companions(self):
        r = batch_registry(); full = expand_fabled_cards((SYLVANAS,), r); self.assertEqual(full, (SYLVANAS, ALLERIA, VEREESA))
        policy = DeckPolicy('p64-fabled-fixture', CONTEXT.target_id, 'experimental', full, deck_size=3)
        hero = r.card('HERO_05'); deck = DeckSpec('HERO_05', hero.initial_hero_power, CardClass.HUNTER, full)
        self.assertTrue(validate_deck(deck, r, policy).valid)
        partial = DeckSpec('HERO_05', hero.initial_hero_power, CardClass.HUNTER, (SYLVANAS, ALLERIA, SYLVANAS))
        self.assertFalse(validate_deck(partial, r, policy).valid)
        with self.assertRaises(ValueError): expand_fabled_cards((ALLERIA,), r)

    def test_sisters_real_history_repetitions_native_discovery_and_deck_growth(self):
        g = self.game(hand=(SYLVANAS, ALLERIA, VEREESA), deck=(A, MAGE, NAGA), enemy=(B,))
        self.play(g, SYLVANAS); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)
        self.play(g, ALLERIA); other = self.portable(g)
        for running in (g, other):
            count = 0
            while running.state.pending_choice is not None:
                q = running.state.pending_choice; self.assertEqual({o.card_id for o in q.options}, {MAGE, NEUTRAL})
                self.choose(running, q.options[0].id); count += 1
            self.assertEqual(count, 2); self.play(running, VEREESA)
            self.assertEqual((self.first(running, A, 'deck').attack, self.first(running, A, 'deck').health), (6, 15))
            self.assertEqual(self.first(running, MAGE, 'deck').kind, CardType.SPELL)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_sylvanas_fresh_wave_targets_new_deathrattle_body_and_counts_each_actual_sibling_play(self):
        g = self.game(hand=(ALLERIA, ALLERIA, SYLVANAS), enemy=(SEED,))
        for _ in range(2):
            self.play(g, ALLERIA)
            while g.state.pending_choice: self.choose(g, g.state.pending_choice.options[0].id)
        self.play(g, SYLVANAS)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
        self.assertEqual(self.first(g, CHILD, 'board', 2).health, 1); self.portable(g)

    def test_granted_sylvanas_body_keeps_named_other_sisters_independent_of_current_carrier_face(self):
        g = self.game(hand=(SYLVANAS, TEST + 'grant_sister'), board=(A,))
        self.play(g, SYLVANAS); hero = g.state.players[2].hero_id
        self.assertEqual(g.state.entities[hero].health, 28)
        self.play(g, TEST + 'grant_sister', self.first(g, A, 'board').id)
        self.assertEqual(g.state.entities[hero].health, 26)
        self.assertEqual([r.card_id for r in g.state.play_history if r.kind == CardType.MINION], [SYLVANAS]); self.portable(g)

    def test_mask_actual_set_stats_lifesteal_and_forced_enemy_attack_including_same_enemy_controller(self):
        for target_player in (1, 2):
            g = self.game(hand=(MASK,), board=(A,), enemy=(B, A))
            target = self.first(g, A if target_player == 1 else B, 'board', target_player).id
            self.play(g, MASK, target); self.assertIn(Keyword.LIFESTEAL, g.state.entities[target].keywords)
            self.assertEqual(g.state.entities[target].attack, 8)
            if target_player == 2: self.assertEqual(g.state.entities[target].health, 7)
            self.assertTrue(any(r.declaration.forced for r in g.state.character_attack_history)); self.portable(g)

    def test_mask_empty_enemy_and_original_target_departure_skip_rng_and_bad_continuation_rolls_back(self):
        g = self.game(hand=(MASK,), board=(A,)); rng = g._rng.getstate()
        self.play(g, MASK, self.first(g, A, 'board').id); self.assertEqual(g._rng.getstate(), rng); self.portable(g)
        g = self.game(hand=(MASK,), board=(A,), enemy=(B,), mode='stats'); rng = g._rng.getstate()
        self.play(g, MASK, self.first(g, A, 'board').id); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); other = self.portable(g)
        for running in (g, other): self.choose(running, 'bounce'); self.assertEqual(running._rng.getstate(), rng)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_staff_actual_hero_attacks_native_druid_only_discovery_discount_and_last_durability(self):
        g = self.game(enemy=(B,), weapon=STAFF); target = self.first(g, B, 'board', 2).id
        weapon = g.state.players[1].weapon_id
        for n in range(4):
            g.apply(Attack(1, g.state.players[1].hero_id, target)); q = g.state.pending_choice
            self.assertEqual({o.card_id for o in q.options}, {DRUID}); self.portable(g)
            self.choose(g, q.options[0].id); card = self.first(g, DRUID)
            self.assertEqual(g.quote_cost(card.id).amount, 5)
            if n < 3: self.cycle(g)
        self.assertEqual(g.state.entities[weapon].zone, Zone.GRAVEYARD); self.assertEqual(len(g.state.players[1].hand), 7); self.portable(g)

    def test_nespirah_location_real_use_fel_reopens_last_use_summons_named_body(self):
        g = self.game(hand=(PRISON,) + (TEST + 'fel',) * 4); loc = self.play(g, PRISON)
        hero = g.state.players[2].hero_id
        for n in range(5):
            g.apply(UseLocation(1, loc, hero))
            if n < 4:
                self.assertEqual(g.state.entities[loc].location_cooldown, 2)
                self.play(g, TEST + 'fel'); self.assertEqual(g.state.entities[loc].location_cooldown, 0)
        self.assertEqual(g.state.entities[loc].zone, Zone.GRAVEYARD)
        self.assertEqual(self.first(g, NESPIRAH, 'board').attack, 6)
        self.assertEqual(g.state.entities[hero].health, 25); self.portable(g)

    def test_nespirah_accepted_fel_location_death_wait_restore_skips_original_refresh(self):
        g = self.game(hand=(PRISON, TEST + 'fel'), mode='cast'); loc = self.play(g, PRISON)
        g.apply(UseLocation(1, loc, g.state.players[2].hero_id)); self.play(g, TEST + 'fel'); other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'destroy'); self.assertEqual(running.state.entities[loc].zone, Zone.GRAVEYARD)
            self.assertEqual(self.first(running, NESPIRAH, 'board').health, 6)
            self.assertFalse(any(running.state.entities[i].card_id in (NAGA, ALL) for i in running.state.players[1].hand))
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_unshackled_own_fel_manual_and_effect_casts_generate_complete_noncolossal_naga_at_one(self):
        g = self.game(hand=(TEST + 'fel', TEST + 'fire', TEST + 'auto'), board=(NESPIRAH,))
        self.play(g, TEST + 'fire'); self.assertFalse(any(g.state.entities[i].card_id in (NAGA, ALL) for i in g.state.players[1].hand))
        self.play(g, TEST + 'fel'); self.play(g, TEST + 'auto')
        generated = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id in (NAGA, ALL)]
        self.assertEqual(len(generated), 2); self.assertTrue(all(g.quote_cost(e.id).amount == 1 for e in generated)); self.portable(g)
        g = self.game(hand=(TEST + 'fel',), board=(NESPIRAH,), members=(COLOSSAL_NAGA,)); rng = g._rng.getstate()
        self.play(g, TEST + 'fel'); self.assertFalse(g.state.players[1].hand); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_unshackled_unknown_eligible_naga_errors_atomically_before_rng_or_pool_trimming(self):
        g = self.game(hand=(TEST + 'fel',), board=(NESPIRAH,), members=MEMBERS + (UNKNOWN,)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, TEST + 'fel')
        self.assertEqual(saved, g.snapshot()); self.portable(g)

    def test_cached_independent_readers_frozen_and_wrong_registry_constructed_separately(self):
        g = self.game(hand=(SILENCE,)); reader = fixture_registry(*self.config, 'reader', SOURCE_PIN)
        self.assertIsNot(g.registry, reader); self.assertIs(reader, fixture_registry(*self.config, 'reader', SOURCE_PIN))
        with self.assertRaises(ValueError): reader.register_card(CardDefinition(TEST + 'forbidden', 'Forbidden', CardType.MINION, health=1))
        wrong = registry(None, (NAGA,)); wrong.freeze(); self.assertIsNot(wrong, reader)
        with self.assertRaises(ValueError): Game.from_snapshot(g.snapshot(), wrong)
        self.portable(g)


if __name__ == '__main__': unittest.main()
