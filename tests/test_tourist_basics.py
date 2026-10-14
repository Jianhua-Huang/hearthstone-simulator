"""Tourist is an independent construction rule, never a live class rewrite."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, DeckValidationError,
    EndTurn, Game, PlayCard, PlayerSetup, Rarity, ResolutionError, Runes,
    Scenario, SelectChoice, SnapshotError, SpellSchool, TargetSpec, TouristSpec,
    TriggerSpec, Zone, validate_deck)
from hs_sim.engine.effects import Buff, Draw, Freeze, InvokeBehavior
from hs_sim.engine.pools import PoolQuery, matches_metadata
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tourists import native_tourist
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, policy, registry as opening_registry, setup

BUTTONS, DARKMARROW, RAYLLA, SKYLA, COOKIE = 'VAC_437', 'VAC_503', 'VAC_424', 'WORK_063', 'VAC_450'
TOTEM, SLOPE = 'WORK_011', 'VAC_513'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/tourist-basics.json'
PIN = '38d76abb20b96a69f57a36f33c0d89efee4729aeb2a5f48baa39deca3d1dad2d'
SPECS = (
    TouristSpec(BUTTONS, CardClass.SHAMAN, 'perils-reviewed-shaman-v1', (TOTEM,)),
    TouristSpec(DARKMARROW, CardClass.DEATH_KNIGHT, 'perils-reviewed-dk-v1', (SLOPE,)),
    TouristSpec(RAYLLA, CardClass.PALADIN, 'perils-reviewed-paladin-empty-v1', ()),
    TouristSpec(SKYLA, CardClass.ROGUE, 'perils-reviewed-rogue-empty-v1', ()),
    TouristSpec(COOKIE, CardClass.DEMON_HUNTER, 'perils-reviewed-dh-empty-v1', ()),
)


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete Tourist evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original Tourist row changed')
    return {row['id']: row['data'] for row in raw['records']}


def unsupported_body(context):
    raise ResolutionError('Only Tourist construction is adapted for this source; its battle body is unsupported')


def registry(*, specs=SPECS):
    r = opening_registry()
    rows = evidence()
    for cls in (CardClass.WARLOCK, CardClass.SHAMAN):
        r.register_card(CardDefinition(cls.value + '.power', 'Fixture power', CardType.HERO_POWER,
            cost=2, on_use='power', metadata=metadata(cls, collectible=False)))
        r.register_card(CardDefinition(cls.value + '.hero', 'Fixture hero', CardType.HERO, health=30,
            initial_hero_power=cls.value + '.power', metadata=metadata(cls, collectible=False)))
    r.register_behavior('tourist.unsupported_body', unsupported_body)
    r.register_behavior('buttons.draw', lambda c: tuple(DrawMatching(c.player_id,
        PoolQuery(kinds=(CardType.SPELL,), spell_schools=(school,)), 'skip', source_id=c.source_id)
        for school in SpellSchool))
    def totem(c):
        if c.event is None or c.event.player_id != c.source.controller:
            return ()
        board = c.state.players[c.source.controller].board
        at = board.index(c.source_id)
        return tuple(Buff(board[n], 1, 1, c.source_id) for n in (at-1, at+1)
            if 0 <= n < len(board) and c.state.entities[board[n]].kind == CardType.MINION)
    r.register_behavior('totem.end', totem)
    r.register_behavior('slope.draw', lambda c: (Draw(c.player_id,
        sum(e.frozen and e.active and e.is_character and e.zone in (Zone.HERO, Zone.BOARD)
            for e in c.state.entities.values()), c.source_id),))
    r.register_behavior('slope.play', lambda c: (Freeze(c.target_id, c.source_id),
        # Query the post-freeze board through the ordinary interpreter.
        InvokeBehavior('slope.draw', c.source_id, c.player_id)))
    for cid, cls in ((BUTTONS, CardClass.DEATH_KNIGHT), (DARKMARROW, CardClass.WARLOCK),
            (RAYLLA, CardClass.MAGE), (SKYLA, CardClass.MAGE), (COOKIE, CardClass.SHAMAN)):
        row = rows[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'],
            battlecry='buttons.draw' if cid == BUTTONS else
                'tourist.unsupported_body' if row['tags'].get('BATTLECRY') else None,
            on_play='tourist.unsupported_body' if cid != BUTTONS and not row['tags'].get('BATTLECRY') else None,
            metadata=metadata(cls, rarity=Rarity.LEGENDARY, runes=Runes() if cid == BUTTONS else None,
                tribes=('undead',) if cid in (BUTTONS, DARKMARROW) else None)))
    row = rows[TOTEM]
    r.register_card(CardDefinition(TOTEM, row['name'], CardType.MINION, cost=row['cost'],
        health=row['health'], triggers=(TriggerSpec('turn_ended', 'totem.end'),),
        metadata=metadata(CardClass.SHAMAN, tribes=('totem',))))
    row = rows[SLOPE]
    r.register_card(CardDefinition(SLOPE, row['name'], CardType.SPELL, cost=row['cost'],
        on_play='slope.play', targeting=TargetSpec(), spell_school=SpellSchool.FROST,
        metadata=metadata(CardClass.DEATH_KNIGHT, rarity=Rarity.EPIC, runes=Runes(frost=2))))
    for cid, school in (('probe.fire', SpellSchool.FIRE), ('probe.frost', SpellSchool.FROST)):
        r.register_card(CardDefinition(cid, 'Each-school draw fixture', CardType.SPELL,
            on_play='coin', spell_school=school, metadata=metadata()))
    for spec in specs:
        r.register_tourist(spec)
    return r


def cards(*prefix, size=8):
    return tuple(prefix) + tuple(f'card.{n}' for n in range(1, size-len(prefix)+1))


class TouristConstructionTests(unittest.TestCase):
    def report(self, *entries, cls=CardClass.DEATH_KNIGHT, runes=Runes(3), r=None, p=None):
        r = r or registry()
        return validate_deck(deck(cls, cards(*entries), runes), r, p or policy(r, deck_size=8))

    def codes(self, report):
        return [i.code for i in report.issues]

    def test_complete_raw_sources_and_printed_destination_identity(self):
        rows = evidence()
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[BUTTONS]['tags']['TOURIST'], 8)
        self.assertEqual(rows[DARKMARROW]['tags']['TOURIST'], 1)
        self.assertEqual(rows[SKYLA]['tags']['MINI_SET'], 1)
        self.assertEqual(rows[TOTEM]['tags']['MINI_SET'], 1)
        self.assertEqual(rows[SLOPE]['tags']['COST_FROST'], 2)
        r = registry()
        self.assertEqual(r.card(TOTEM).metadata.classes, (CardClass.SHAMAN,))
        self.assertEqual(r.card(SLOPE).metadata.classes, (CardClass.DEATH_KNIGHT,))

    def test_native_main_deck_tourist_authorizes_reviewed_foreign_card(self):
        self.assertTrue(self.report(BUTTONS, TOTEM).valid)
        self.assertTrue(self.report(TOTEM, BUTTONS).valid)
        self.assertIn('class', self.codes(self.report(TOTEM)))
        self.assertIn('class', self.codes(self.report(BUTTONS, TOTEM, cls=CardClass.MAGE, runes=None)))

    def test_permission_is_finite_and_does_not_extend_to_other_expansions(self):
        r = registry()
        r.register_card(CardDefinition('old.shaman', 'Other expansion fixture', CardType.MINION,
            health=1, metadata=metadata(CardClass.SHAMAN)))
        self.assertIn('class', self.codes(self.report(BUTTONS, 'old.shaman', r=r)))
        # Registration alone does not grant permission if the package did not declare Tourist.
        self.assertIn('class', self.codes(self.report(BUTTONS, TOTEM, r=registry(specs=()))))

    def test_foreign_tourist_is_excluded_and_cannot_chain(self):
        self.assertIn('class', self.codes(self.report(BUTTONS, COOKIE)))
        self.assertIn('tourist_limit', self.codes(self.report(BUTTONS, COOKIE)))
        self.assertIsNone(native_tourist(CardClass.DEATH_KNIGHT, cards(COOKIE), registry()))
        r = registry(specs=())
        for spec in SPECS:
            r.register_tourist(replace(spec, eligible_card_ids=(TOTEM, COOKIE)) if spec.card_id == BUTTONS else spec)
        with self.assertRaisesRegex(ValueError, 'excluding Tourists'):
            r.freeze()

    def test_one_tourist_limit_includes_two_native_alternatives(self):
        self.assertTrue(self.report(RAYLLA, cls=CardClass.MAGE, runes=None).valid)
        self.assertTrue(self.report(SKYLA, cls=CardClass.MAGE, runes=None).valid)
        self.assertIn('tourist_limit', self.codes(self.report(RAYLLA, SKYLA, cls=CardClass.MAGE, runes=None)))
        self.assertIn('tourist_limit', self.codes(self.report(BUTTONS, BUTTONS)))
        # An artificially relaxed copy policy must still obey the keyword's one-source rule.
        r = registry()
        self.assertIn('tourist_limit', self.codes(self.report(BUTTONS, BUTTONS, r=r,
            p=policy(r, deck_size=8, legendary_copies=2))))

    def test_source_ban_or_rotation_cannot_authorize_foreign_entries(self):
        r = registry(); p = policy(r, deck_size=8)
        for changed in (replace(p, banned_card_ids=(BUTTONS,)),
                replace(p, allowed_card_ids=tuple(cid for cid in p.allowed_card_ids if cid != BUTTONS))):
            report = self.report(BUTTONS, TOTEM, r=r, p=changed)
            self.assertIn('format_legality', self.codes(report))
            self.assertIn('class', self.codes(report))

    def test_destination_ban_rotation_and_normal_copy_limits_remain(self):
        r = registry(); p = policy(r, deck_size=8)
        self.assertTrue(self.report(BUTTONS, TOTEM, TOTEM, r=r).valid)
        self.assertIn('copy_limit', self.codes(self.report(BUTTONS, TOTEM, TOTEM, TOTEM, r=r)))
        for changed in (replace(p, banned_card_ids=(TOTEM,)),
                replace(p, allowed_card_ids=tuple(cid for cid in p.allowed_card_ids if cid != TOTEM))):
            report = self.report(BUTTONS, TOTEM, r=r, p=changed)
            self.assertIn('format_legality', self.codes(report))
            self.assertNotIn('class', self.codes(report))

    def test_normal_native_and_neutral_entries_need_no_tourist(self):
        self.assertTrue(self.report(TOTEM, cls=CardClass.SHAMAN, runes=None).valid)
        self.assertTrue(self.report(SLOPE, runes=Runes(1, 2)).valid)
        self.assertTrue(self.report(cls=CardClass.MAGE, runes=None).valid)

    def test_dk_destination_uses_existing_rune_requirements_without_changing_class(self):
        self.assertTrue(self.report(DARKMARROW, SLOPE, cls=CardClass.WARLOCK, runes=Runes(1, 2)).valid)
        self.assertIn('rune_requirements', self.codes(self.report(DARKMARROW, SLOPE,
            cls=CardClass.WARLOCK, runes=Runes(2, 1))))
        self.assertIn('class', self.codes(self.report(SLOPE, cls=CardClass.WARLOCK, runes=Runes(1, 2))))
        self.assertIn('rune_loadout', self.codes(self.report(SLOPE, cls=CardClass.WARLOCK, runes=Runes(1, 2))))

    def test_rune_loadout_only_for_original_dk_access_and_policy_slot_count(self):
        for runes in (None, Runes(2), Runes(4)):
            self.assertIn('rune_loadout', self.codes(self.report(DARKMARROW, cls=CardClass.WARLOCK, runes=runes)))
        self.assertIn('rune_loadout', self.codes(self.report(RAYLLA, cls=CardClass.MAGE, runes=Runes(3))))
        r = registry()
        self.assertTrue(self.report(DARKMARROW, SLOPE, cls=CardClass.WARLOCK,
            runes=Runes(2, 2), r=r, p=policy(r, deck_size=8, rune_slots=4)).valid)

    def test_shape_validation_is_strict_and_versioned(self):
        for change in ({'card_id': ''}, {'destination_class': 'shaman'},
                {'destination_class': CardClass.NEUTRAL}, {'pool_id': False},
                {'eligible_card_ids': [TOTEM]}, {'eligible_card_ids': (TOTEM, TOTEM)},
                {'eligible_card_ids': ('',)}, {'version': 'tourist-v2'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(SPECS[0], **change)
        r = registry()
        with self.assertRaises(ValueError): r.register_tourist(SPECS[0])
        with self.assertRaises(ValueError): r.register_tourist({})
        with self.assertRaises(TypeError): r.tourists[BUTTONS] = SPECS[0]
        r.freeze()
        with self.assertRaises(ValueError): r.register_tourist(SPECS[0])

    def test_registered_references_wrong_class_and_noncollectible_pool_reject(self):
        for cid in ('missing', 'card.1', 'coin'):
            r = registry(specs=())
            r.register_tourist(replace(SPECS[0], eligible_card_ids=(cid,)))
            with self.subTest(cid=cid), self.assertRaises(ValueError): r.freeze()
        for cid in ('missing', 'card.1', TOTEM):
            r = registry(specs=())
            r.register_tourist(replace(SPECS[0], card_id=cid))
            with self.subTest(source=cid), self.assertRaises(ValueError): r.freeze()
        r = registry(specs=())
        r.register_tourist(replace(SPECS[0], destination_class=CardClass.DEATH_KNIGHT, eligible_card_ids=()))
        with self.assertRaises(ValueError): r.freeze()

    def test_registry_fingerprint_binds_destinations_pool_identity_and_members(self):
        normal = registry().fingerprint()
        self.assertEqual(registry(specs=tuple(reversed(SPECS))).fingerprint(), normal)
        for spec in (replace(SPECS[0], pool_id='another-reviewed-pool'),
                replace(SPECS[0], eligible_card_ids=()),
                replace(SPECS[0], destination_class=CardClass.MAGE, eligible_card_ids=())):
            self.assertNotEqual(registry(specs=(spec, *SPECS[1:])).fingerprint(), normal)

    def test_unknown_definition_and_uncollectible_are_not_silently_discarded(self):
        r = registry(); p = policy(r, deck_size=8)
        p = replace(p, allowed_card_ids=p.allowed_card_ids + ('missing',))
        report = self.report(BUTTONS, 'missing', r=r, p=p)
        self.assertIn('unsupported_definition', self.codes(report))
        self.assertIn('uncollectible', self.codes(self.report(BUTTONS, 'coin')))

    def test_invalid_tourist_deck_fails_before_freeze_or_partial_opening(self):
        r = registry()
        config = setup(r, decks=(deck(CardClass.DEATH_KNIGHT, cards(TOTEM), Runes(3)),
            deck(CardClass.WARRIOR, cards())), deck_size=8)
        with self.assertRaises(DeckValidationError): Game.from_decks(config, r)
        r.register_behavior('still.mutable', lambda c: ())


class TouristRuntimeTests(unittest.TestCase):
    def game(self, *, actor=1, cls=CardClass.DEATH_KNIGHT, prefix=(BUTTONS, TOTEM), runes=Runes(3), seed=71):
        r = registry()
        own = deck(cls, cards(*prefix), runes)
        other = deck(CardClass.WARRIOR, cards())
        return Game.from_decks(setup(r, first=actor, seed=seed,
            decks=(own, other) if actor == 1 else (other, own), deck_size=8), r)

    def choose(self, g):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, ()))

    def finish(self, g):
        while g.state.pending_choice is not None: self.choose(g)
        return g

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry())
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for player in (1, 2): self.assertEqual(restored.observe(player), g.observe(player))
        return restored

    def reach(self, g, cid, actor):
        for _ in range(12):
            found = next((i for i in g.state.players[actor].hand if g.state.entities[i].card_id == cid), None)
            if found is not None and g.state.active_player == actor and g.state.players[actor].mana >= g.registry.card(cid).cost:
                return found
            g.apply(EndTurn(g.state.active_player))
        self.fail('Necessary card did not reach its paid action')

    def test_real_opening_waiting_both_seats_restore_clone_and_replay(self):
        for actor in (1, 2):
            g = self.game(actor=actor)
            self.portable(g)
            self.choose(g); self.portable(g)
            self.choose(g); self.portable(g)
            self.assertEqual(g.state.players[actor].deck_class, CardClass.DEATH_KNIGHT)
            self.assertEqual(g.state.players[actor].runes, Runes(3))

    def test_dk_destination_non_dk_opening_preserves_original_hero_and_runes(self):
        for actor in (1, 2):
            g = self.game(actor=actor, cls=CardClass.WARLOCK,
                prefix=(DARKMARROW, SLOPE), runes=Runes(1, 2))
            self.portable(g); self.finish(g); self.portable(g)
            p = g.state.players[actor]
            self.assertEqual((p.deck_class, p.hero_class, p.runes),
                (CardClass.WARLOCK, CardClass.WARLOCK, Runes(1, 2)))

    def test_foreign_miniset_card_pays_printed_cost_and_uses_ordinary_end_subject(self):
        for actor in (1, 2):
            g = self.finish(self.game(actor=actor))
            source = self.reach(g, TOTEM, actor)
            mana = g.state.players[actor].mana
            g.apply(PlayCard(actor, source))
            self.assertEqual(g.state.players[actor].mana, mana-2)
            self.assertEqual(g.registry.card(g.state.entities[source].card_id).metadata.classes, (CardClass.SHAMAN,))
            self.assertEqual(g.state.play_history[-1].player_id, actor)
            neighbour = next(i for i in g.state.players[actor].hand if g.state.entities[i].card_id.startswith('card.'))
            # Keep a normal 4/4 next to the totem for its complete printed body.
            if g.state.players[actor].mana < 1:
                g.apply(EndTurn(actor)); g.apply(EndTurn(3-actor))
            g.apply(PlayCard(actor, neighbour))
            g.apply(EndTurn(actor))
            e = g.state.entities[neighbour]
            self.assertEqual((e.attack, e.health), (5, 5))
            self.portable(g)

    def test_buttons_body_uses_existing_each_school_draw_and_retains_construction_fact(self):
        g = self.finish(self.game())
        source = self.reach(g, BUTTONS, 1)
        g.apply(PlayCard(1, source))
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        self.assertEqual(native_tourist(CardClass.DEATH_KNIGHT, g.state.players[1].original_deck, g.registry), SPECS[0])
        self.assertTrue(validate_deck(deck(CardClass.DEATH_KNIGHT, g.state.players[1].original_deck, Runes(3)),
            g.registry, policy(g.registry, deck_size=8)).valid)
        self.portable(g)
        # The original neutral fixture deck has no schools: failed filters skip without fatigue.
        self.assertEqual(g.state.players[1].fatigue, 0)
        g = Game.from_scenario(Scenario((PlayerSetup('death_knight.hero', hand=(BUTTONS,),
            deck=('probe.fire', 'probe.fire', 'probe.frost', 'card.1'), mana=4, max_mana=4),
            PlayerSetup('warrior.hero')), seed=71), registry())
        g.apply(PlayCard(1, g.state.players[1].hand[0]))
        self.assertEqual(sorted(g.state.entities[i].card_id for i in g.state.players[1].hand),
            ['probe.fire', 'probe.frost'])
        self.assertEqual(len(g.state.draw_history), 2)
        self.assertEqual(g.state.players[1].fatigue, 0)
        self.portable(g)

    def test_dk_destination_spell_keeps_real_printed_requirements_and_executes_normally(self):
        g = self.finish(self.game(cls=CardClass.WARLOCK, prefix=(DARKMARROW, SLOPE), runes=Runes(1, 2)))
        source = self.reach(g, SLOPE, 1)
        target = g.state.players[2].hero_id
        before_draws = len(g.state.draw_history)
        g.apply(PlayCard(1, source, target))
        self.assertTrue(g.state.entities[target].frozen)
        self.assertEqual(len(g.state.draw_history), before_draws+1)
        self.assertEqual(g.state.players[1].hero_class, CardClass.WARLOCK)
        self.portable(g)

    def test_construction_only_source_body_fails_and_payment_rolls_back(self):
        g = self.finish(self.game(cls=CardClass.WARLOCK, prefix=(DARKMARROW, SLOPE), runes=Runes(1, 2)))
        source = self.reach(g, DARKMARROW, 1)
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'battle body is unsupported'): g.apply(PlayCard(1, source))
        self.assertEqual(g.snapshot(), before)

    def test_destination_does_not_change_current_class_filters_or_public_deck_details(self):
        g = self.finish(self.game())
        r = g.registry; foreign = r.card(TOTEM)
        self.assertFalse(matches_metadata(PoolQuery(class_mode='current', include_neutral=False),
            card_id=TOTEM, kind=foreign.kind, cost=foreign.cost, meta=foreign.metadata,
            spell_school=None, keywords=(), current_class=g.state.players[1].hero_class))
        for viewer in (1, 2):
            text = json.dumps(g.observe(viewer), sort_keys=True)
            for key in ('original_deck', 'match_setup', 'eligible_card_ids', 'pool_id', 'tourists'):
                self.assertNotIn('"' + key + '"', text)

    def test_construction_permission_is_not_required_to_play_an_acquired_foreign_card(self):
        g = Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=(TOTEM,), mana=2, max_mana=2),
            PlayerSetup('warrior.hero')), seed=72), registry())
        g.apply(PlayCard(1, g.state.players[1].hand[0]))
        self.assertEqual(g.state.players[1].hero_class, CardClass.MAGE)
        self.assertEqual(g.state.players[1].original_deck, ())
        self.portable(g)

    def test_hidden_opponent_tourist_identity_does_not_change_acting_observation(self):
        games = []
        for source in (RAYLLA, SKYLA):
            r = registry()
            config = setup(r, decks=(deck(CardClass.DEATH_KNIGHT, cards(BUTTONS, TOTEM), Runes(3)),
                deck(CardClass.MAGE, cards(source))), first=1, seed=77, deck_size=8)
            games.append(Game.from_decks(config, r))
        self.assertNotEqual(games[0].state.players[2].original_deck, games[1].state.players[2].original_deck)
        self.assertEqual(games[0].observe(1), games[1].observe(1))

    def test_rehashed_origin_class_loadout_and_deck_forgeries_are_rejected(self):
        g = self.finish(self.game(cls=CardClass.WARLOCK, prefix=(DARKMARROW, SLOPE), runes=Runes(1, 2)))
        for fields in ({'deck_class': 'mage'}, {'runes': {'blood': 0, 'frost': 3, 'unholy': 0}},
                {'runes': None}, {'original_deck': list(cards(SLOPE))}):
            saved = deepcopy(g.snapshot())
            saved['state']['players']['1'].update(fields)
            saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.subTest(fields=fields), self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry())

    def test_different_pinned_tourist_pool_cannot_restore_existing_game(self):
        saved = self.game().snapshot()
        r = registry(specs=(replace(SPECS[0], eligible_card_ids=()), *SPECS[1:]))
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, r)


if __name__ == '__main__':
    unittest.main()
