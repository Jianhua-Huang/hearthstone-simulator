"""Independent E.T.C. construction, original-band selection and persistence."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, DeckValidationError,
    DiscoverSideboard, EndTurn, Game, MatchSetup, OpeningHook, PlayCard, Rarity,
    ResolutionError, Runes, SelectChoice, SideboardProfile, SideboardSpec,
    SideboardState, SnapshotError, TargetSpec, TriggerSpec, Zone, validate_deck)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, GainTemporaryMana,
    InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, policy, registry as opening_registry, setup
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ETC = 'ETC_080'
MEMBERS = ('band.spell', 'band.weapon', 'band.location')
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/sideboard-basics.json'
PIN = '16f59d3104f03aecbc1424896cc4479e302ac1db893ddf856c6b3a015dffc1cf'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete E.T.C. evidence changed')
    row = raw['records'][0]
    if row['id'] != ETC or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Original E.T.C. row changed')
    return row['data']


def registry(*, watch=False, fault=False, profile=None):
    r = opening_registry(); row = evidence()
    r.register_behavior('etc.band', lambda c: (DiscoverSideboard(c.player_id, ETC, c.source_id),))
    r.register_card(CardDefinition(ETC, row['name'], CardType.MINION, cost=row['cost'],
        attack=row['attack'], health=row['health'], battlecry='etc.band',
        metadata=metadata(rarity=Rarity.LEGENDARY)))
    r.register_behavior('band.spell', lambda c: (GainTemporaryMana(c.player_id, 1),))
    r.register_card(CardDefinition('band.spell', 'Sideboard spell fixture', CardType.SPELL,
        cost=1, on_play='band.spell', metadata=metadata()))
    r.register_card(CardDefinition('band.weapon', 'Sideboard weapon fixture', CardType.WEAPON,
        cost=1, attack=1, durability=2, metadata=metadata()))
    r.register_card(CardDefinition('band.location', 'Sideboard location fixture', CardType.LOCATION,
        cost=1, durability=2, on_use='power', metadata=metadata()))
    r.register_behavior('bounce', lambda c: (ReturnToHand(c.target_id),))
    r.register_card(CardDefinition('bounce', 'Return fixture', CardType.SPELL,
        on_play='bounce', targeting=TargetSpec(), metadata=metadata()))
    r.register_card(CardDefinition('foreign', 'Foreign fixture', CardType.MINION,
        health=1, metadata=metadata(CardClass.WARRIOR)))
    r.register_card(CardDefinition('dk.member', 'Rune fixture', CardType.MINION,
        health=1, metadata=metadata(CardClass.DEATH_KNIGHT, runes=Runes(frost=2))))
    r.register_card(CardDefinition('legendary', 'Legendary fixture', CardType.MINION,
        health=1, metadata=metadata(rarity=Rarity.LEGENDARY)))
    r.register_card(CardDefinition('identity.a', 'Identity fixture A', CardType.MINION,
        health=1, metadata=metadata(deck_identity='same.member')))
    r.register_card(CardDefinition('identity.b', 'Identity fixture B', CardType.MINION,
        health=1, metadata=metadata(deck_identity='same.member')))
    if watch:
        r.register_behavior('late.fault', lambda c: (AddToHand(c.player_id, 'missing.after.sideboard'),))
        def acquired(c):
            if watch == 'full':
                if not any(str(option).startswith('band:') for option in dict(c.event.data).get('option_ids', ())):
                    return ()
                return tuple(AddToHand(c.player_id, 'card.38', c.source_id)
                    for _ in range(10 - len(c.state.players[c.player_id].hand)))
            if c.event.target_id is None or c.state.entities[c.event.target_id].card_id not in MEMBERS:
                return ()
            if fault == 'immediate':
                return (AddToHand(c.player_id, 'missing.after.sideboard'),)
            work = [RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id)]
            if fault:
                work.append(InvokeBehavior('late.fault', c.source_id, c.player_id))
            return tuple(work)
        r.register_behavior('watch', acquired)
        r.register_card(CardDefinition('watch', 'Acquisition observer fixture', CardType.MINION,
            health=2, triggers=(TriggerSpec('choice_selected' if watch == 'full' else 'card_added_to_hand', 'watch'),), metadata=metadata()))
    r.register_sideboard(profile or SideboardProfile(ETC))
    return r


def main(*prefix):
    return tuple(prefix) + tuple(f'card.{n}' for n in range(1, 9-len(prefix)))


class SideboardConstructionTests(unittest.TestCase):
    def report(self, members=MEMBERS, *, prefix=(ETC,), cls=CardClass.MAGE,
            runes=None, r=None, p=None, bands=None):
        r = r or registry()
        bands = (SideboardSpec(ETC, members),) if bands is None else bands
        d = replace(deck(cls, main(*prefix), runes), sideboards=bands)
        return validate_deck(d, r, p or policy(r, deck_size=8))

    def codes(self, report):
        return [issue.code for issue in report.issues]

    def test_full_raw_and_necessary_complete_ETC_body_are_pinned(self):
        row = evidence()
        original = next(r for r in json.loads((FIXTURE.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8')) if r['id'] == ETC)
        self.assertEqual(row, original)
        self.assertEqual((row['cost'], row['attack'], row['health']), (4, 4, 4))
        self.assertEqual((row['tags']['MAX_SIDEBOARD_CARDS'], row['tags']['SIDEBOARD_TYPE']), (3, 1))
        self.assertIsNotNone(registry().card(ETC).battlecry)

    def test_sideboard_types_share_ordinary_legality_without_adding_main_size(self):
        self.assertTrue(self.report().valid)
        self.assertTrue(self.report(('card.39', 'band.spell', 'band.weapon')).valid)

    def test_missing_duplicate_source_and_unknown_policy_are_explicit(self):
        self.assertIn('sideboard_source', self.codes(self.report(prefix=())))
        self.assertIn('sideboard_duplicate', self.codes(self.report(bands=(SideboardSpec(ETC, ()),) * 2)))
        self.assertIn('unsupported_sideboard', self.codes(self.report(bands=(SideboardSpec('card.1', ()),))))

    def test_maximum_three_and_explicit_incomplete_band_policy(self):
        for members in ((), MEMBERS[:1], MEMBERS[:2], MEMBERS):
            self.assertTrue(self.report(members).valid)
        self.assertIn('sideboard_size', self.codes(self.report(MEMBERS + ('card.39',))))
        self.assertTrue(self.report(bands=()).valid)

    def test_main_and_sideboard_aggregate_normal_and_legendary_copy_limits(self):
        self.assertTrue(self.report(('card.39',) * 2).valid)
        self.assertIn('copy_limit', self.codes(self.report(('card.1',) * 2)))
        self.assertIn('copy_limit', self.codes(self.report(('legendary',), prefix=(ETC, 'legendary'))))
        self.assertIn('copy_limit', self.codes(self.report((ETC,))))

    def test_reviewed_deck_identity_is_shared_across_main_and_band(self):
        self.assertIn('copy_limit', self.codes(self.report(('identity.b',) * 2,
            prefix=(ETC, 'identity.a'))))

    def test_foreign_uncollectible_unknown_and_format_banned_members_fail(self):
        self.assertIn('class', self.codes(self.report(('foreign',))))
        self.assertIn('uncollectible', self.codes(self.report(('coin',))))
        self.assertIn('unsupported_definition', self.codes(self.report(('missing',))))
        r = registry(); p = replace(policy(r, deck_size=8), banned_card_ids=('band.spell',))
        self.assertIn('format_legality', self.codes(self.report(r=r, p=p)))

    def test_sideboard_runes_use_the_original_deck_loadout(self):
        self.assertTrue(self.report(('dk.member',), cls=CardClass.DEATH_KNIGHT, runes=Runes(1, 2)).valid)
        self.assertIn('rune_requirements', self.codes(self.report(('dk.member',),
            cls=CardClass.DEATH_KNIGHT, runes=Runes(3))))
        self.assertIn('class', self.codes(self.report(('dk.member',))))

    def test_opening_hooks_and_reviewed_specific_bans_are_excluded(self):
        r = registry(profile=SideboardProfile(ETC, banned_card_ids=('band.spell',)))
        self.assertIn('sideboard_banned', self.codes(self.report(r=r)))
        r = registry()
        r.register_card(CardDefinition('start', 'Opening fixture', CardType.MINION,
            health=1, opening_hooks=(OpeningHook('before_deal', 'power'),), metadata=metadata()))
        self.assertIn('sideboard_banned', self.codes(self.report(('start',), r=r)))

    def test_strict_specs_profile_registration_freeze_and_fingerprint(self):
        for factory in (lambda: SideboardSpec('', ()), lambda: SideboardSpec(ETC, []),
                lambda: SideboardProfile(ETC, max_cards=True), lambda: SideboardProfile(ETC, max_cards=4),
                lambda: SideboardState(ETC, MEMBERS, (True,)),
                lambda: SideboardState(ETC, MEMBERS, (0, 0)),
                lambda: DiscoverSideboard(True, ETC)):
            with self.assertRaises(ValueError): factory()
        r = registry()
        with self.assertRaises(ValueError): r.register_sideboard(SideboardProfile(ETC))
        with self.assertRaises(TypeError): r.sideboards[ETC] = SideboardProfile(ETC)
        normal = r.fingerprint()
        self.assertNotEqual(normal, registry(profile=SideboardProfile(ETC, banned_card_ids=('band.spell',))).fingerprint())
        r.freeze()
        with self.assertRaises(ValueError): r.register_sideboard(SideboardProfile('other'))

    def test_unknown_ban_and_invalid_source_cannot_freeze(self):
        for profile in (SideboardProfile(ETC, banned_card_ids=('missing',)), SideboardProfile('card.1')):
            with self.assertRaises(ValueError): registry(profile=profile).freeze()

    def test_invalid_deck_rejects_before_freeze_and_opening(self):
        r = registry(); own = replace(deck(cards=main(ETC)), sideboards=(SideboardSpec(ETC, ('missing',)),))
        with self.assertRaises(DeckValidationError):
            Game.from_decks(setup(r, decks=(own, deck(CardClass.WARRIOR, main())), deck_size=8), r)
        r.register_behavior('still.mutable', lambda c: ())

    def test_host_setup_roundtrip_optional_default_and_strict_sideboard_rows(self):
        r = registry(); own = replace(deck(cards=main(ETC)), sideboards=(SideboardSpec(ETC, MEMBERS),))
        config = setup(r, decks=(own, deck(CardClass.WARRIOR, main())), deck_size=8)
        self.assertEqual(MatchSetup.from_dict(config.to_dict()), config)
        empty = setup(r, decks=(deck(cards=main()), deck(CardClass.WARRIOR, main())), deck_size=8).to_dict()
        for row in empty['decks']: row.pop('sideboards')
        self.assertEqual(MatchSetup.from_dict(empty).decks[0].sideboards, ())
        bad = config.to_dict(); bad['decks'][0]['sideboards'][0]['extra'] = 1
        with self.assertRaises(ValueError): MatchSetup.from_dict(bad)


class SideboardRuntimeTests(unittest.TestCase):
    def game(self, *, actor=1, members=MEMBERS, band=True, bounce=False, watch=False, fault=False, enemy_members=None):
        self.options = {'watch':watch, 'fault':fault}
        r = registry(**self.options)
        prefix = (ETC,) + (('bounce', 'bounce') if bounce else ()) + (('watch',) if watch else ())
        own = replace(deck(cards=main(*prefix)),
            sideboards=(SideboardSpec(ETC, members),) if band else ())
        other = deck(CardClass.WARRIOR, main())
        if enemy_members is not None:
            other = replace(deck(CardClass.WARRIOR, main(ETC)), sideboards=(SideboardSpec(ETC, enemy_members),))
        return Game.from_decks(setup(r, first=actor, seed=71,
            decks=(own, other) if actor == 1 else (other, own), deck_size=8), r)

    def opening(self, g):
        while g.state.pending_choice is not None:
            q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ()))
        return g

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry(**self.options))
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(**self.options)).snapshot(), saved)
        for actor in (1, 2): self.assertEqual(restored.observe(actor), g.observe(actor))
        return restored

    def reach(self, g, cid, actor=1):
        for _ in range(24):
            source = next((i for i in g.state.players[actor].hand if g.state.entities[i].card_id == cid), None)
            if source is not None and g.state.active_player == actor and g.state.players[actor].mana >= g.registry.card(cid).cost:
                return source
            g.apply(EndTurn(g.state.active_player))
        self.fail('Necessary physical card did not reach its paid action')

    def play(self, g, cid=ETC, actor=1, target=None):
        source = self.reach(g, cid, actor)
        g.apply(PlayCard(actor, source, target))
        return source

    def choose(self, g, slot=0):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (f'band:{slot}',)))

    def band(self, g, actor=1):
        return g.state.players[actor].sideboards[0]

    def test_real_opening_sideboards_outside_deck_restore_both_seats(self):
        for actor in (1, 2):
            g = self.game(actor=actor)
            self.portable(g)
            self.assertEqual(self.band(g, actor).cards, MEMBERS)
            self.assertEqual(len(g.state.players[actor].original_deck), 8)
            self.assertFalse(any(e.card_id in MEMBERS for e in g.state.entities.values()))
            q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ()))
            self.portable(g); self.opening(g); self.portable(g)

    def test_paid_ETC_uses_shared_choice_adds_new_entity_and_consumes_one_slot(self):
        for actor in (1, 2):
            g = self.opening(self.game(actor=actor)); source = self.reach(g, ETC, actor)
            mana = g.state.players[actor].mana; rng = g._rng.getstate(); count = len(g.state.entities)
            g.apply(PlayCard(actor, source))
            self.assertEqual(g.state.players[actor].mana, mana - 4)
            self.assertEqual([o.card_id for o in g.state.pending_choice.options], list(MEMBERS))
            self.assertEqual(self.band(g, actor).taken_slots, ())
            self.assertEqual(len(g.state.entities), count)
            self.portable(g); self.choose(g, 1)
            added = g.state.entities[g.state.players[actor].hand[-1]]
            self.assertEqual((added.card_id, added.owner, added.controller, added.zone), (MEMBERS[1], actor, actor, Zone.HAND))
            self.assertEqual(self.band(g, actor).taken_slots, (1,))
            self.assertEqual(g._rng.getstate(), rng)
            self.portable(g)

    def test_returned_ETC_reuses_player_band_and_does_not_restore_consumed_member(self):
        g = self.opening(self.game(bounce=True)); source = self.play(g); self.choose(g, 2)
        self.play(g, 'bounce', target=source)
        self.assertEqual(g.state.entities[source].zone, Zone.HAND)
        self.play(g); self.assertEqual([o.id for o in g.state.pending_choice.options], ['band:0', 'band:1'])
        self.choose(g, 0); self.play(g, 'bounce', target=source); self.play(g)
        self.assertEqual([o.id for o in g.state.pending_choice.options], ['band:1'])
        self.choose(g, 1)
        self.assertEqual(self.band(g).taken_slots, (2, 0, 1))
        from hs_sim.engine.resolver import Resolution
        from hs_sim.engine.sideboards import discover
        rng = g._rng.getstate()
        self.assertEqual(discover(Resolution(g), DiscoverSideboard(1, ETC, source)), [])
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_empty_and_absent_original_bands_have_no_choice_or_rng(self):
        for band in (True, False):
            g = self.opening(self.game(members=(), band=band))
            source = self.reach(g, ETC); rng = g._rng.getstate()
            g.apply(PlayCard(1, source))
            self.assertIsNone(g.state.pending_choice)
            self.assertEqual(g._rng.getstate(), rng)
            self.assertFalse(any(e.kind == 'sideboard_card_taken' for e in g.events))
            self.portable(g)

    def test_duplicate_faces_keep_separate_original_slots(self):
        g = self.opening(self.game(members=('card.39', 'card.39'), bounce=True))
        source = self.play(g)
        self.assertEqual([o.id for o in g.state.pending_choice.options], ['band:0', 'band:1'])
        self.choose(g, 1); self.play(g, 'bounce', target=source); self.play(g)
        self.assertEqual([o.id for o in g.state.pending_choice.options], ['band:0'])
        self.choose(g, 0)
        copies = [i for i in g.state.players[1].hand if g.state.entities[i].card_id == 'card.39']
        self.assertEqual(len(copies), 2); self.assertNotEqual(*copies)
        self.portable(g)

    def test_selected_card_uses_ordinary_weapon_payment_and_lifecycle(self):
        g = self.opening(self.game()); self.play(g); self.choose(g, 1)
        added = self.play(g, 'band.weapon')
        self.assertEqual(g.state.players[1].weapon_id, added)
        self.assertEqual(g.state.entities[added].durability, 2)
        self.assertEqual(self.band(g).taken_slots, (1,))
        self.portable(g)

    def test_selected_spell_location_and_minion_use_ordinary_hand_play(self):
        for cid, kind, zone in (('band.spell', CardType.SPELL, Zone.GRAVEYARD),
                ('band.location', CardType.LOCATION, Zone.BOARD), ('card.39', CardType.MINION, Zone.BOARD)):
            g = self.opening(self.game(members=(cid,)))
            self.play(g); self.choose(g)
            added = self.play(g, cid)
            self.assertEqual((g.state.entities[added].kind, g.state.entities[added].zone), (kind, zone))
            self.assertEqual(self.band(g).taken_slots, (0,))
            self.portable(g)

    def test_same_source_definition_uses_each_players_own_original_band(self):
        g = self.opening(self.game(members=('card.39',), enemy_members=('card.31',)))
        self.play(g); self.assertEqual([o.card_id for o in g.state.pending_choice.options], ['card.39'])
        self.choose(g)
        self.play(g, actor=2); self.assertEqual([o.card_id for o in g.state.pending_choice.options], ['card.31'])
        self.choose(g)
        self.assertEqual(self.band(g, 1).taken_slots, (0,)); self.assertEqual(self.band(g, 2).taken_slots, (0,))
        self.portable(g)

    def test_selection_is_private_and_opponent_sees_only_pending_owner(self):
        g = self.opening(self.game()); self.play(g)
        own = g.observe(1); enemy = g.observe(2)
        self.assertEqual([o['card_id'] for o in own['pending_choice']['options']], list(MEMBERS))
        self.assertEqual(enemy['pending_choice'], {'player_id':1})
        self.assertNotIn('sideboards', json.dumps(own))
        for cid in MEMBERS: self.assertNotIn(cid, json.dumps(enemy))
        self.choose(g)
        for cid in MEMBERS: self.assertNotIn(cid, json.dumps(g.observe(2)))
        self.assertFalse(any(e['kind'] == 'sideboard_card_taken' for e in g.player_events(1)))

    def test_choice_owner_wrong_slot_and_double_selection_reject_without_change(self):
        g = self.opening(self.game()); self.play(g); q = g.state.pending_choice
        before = g.snapshot()
        for action in (SelectChoice(2, q.id, ('band:0',)), SelectChoice(1, q.id, ('band:3',))):
            with self.assertRaises(ValueError): g.apply(action)
            self.assertEqual(g.snapshot(), before)
        self.choose(g)
        before = g.snapshot()
        with self.assertRaises(ValueError): g.apply(SelectChoice(1, q.id, ('band:0',)))
        self.assertEqual(g.snapshot(), before)

    def test_acquisition_reaction_waiting_preserves_consumption_and_resumes(self):
        g = self.opening(self.game(watch=True)); self.play(g, 'watch'); self.play(g)
        self.choose(g)
        self.assertEqual(self.band(g).taken_slots, (0,))
        self.assertEqual(g.state.pending_choice.options[0].id, 'ok')
        self.portable(g)
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ('ok',)))
        self.assertEqual(self.band(g).taken_slots, (0,)); self.portable(g)

    def test_late_acquisition_error_rolls_back_resumed_action_and_original_band(self):
        g = self.opening(self.game(watch=True, fault=True)); self.play(g, 'watch'); self.play(g); self.choose(g)
        before = g.snapshot(); q = g.state.pending_choice
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(q.player_id, q.id, ('ok',)))
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.band(g).taken_slots, (0,))
        self.portable(g)

    def test_full_hand_burn_consumes_member_and_never_rediscovers_it(self):
        g = self.opening(self.game(watch='full', bounce=True))
        self.play(g, 'watch'); self.play(g); self.choose(g, 1)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(self.band(g).taken_slots, (1,))
        self.assertNotIn('band.weapon', [g.state.entities[i].card_id for i in g.state.players[1].hand])
        burned = [e for e in g.events if e.kind == 'card_burned' and g.state.entities[e.target_id].card_id == 'band.weapon']
        self.assertEqual(len(burned), 1)
        self.portable(g)

    def test_immediate_late_error_restores_choice_member_hand_rng_and_information(self):
        g = self.opening(self.game(watch=True, fault='immediate'))
        self.play(g, 'watch'); self.play(g)
        before = g.snapshot(); own = g.observe(1); other = g.observe(2)
        with self.assertRaises(ResolutionError): self.choose(g)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.band(g).taken_slots, ())
        self.assertEqual(g.observe(1), own); self.assertEqual(g.observe(2), other)
        self.portable(g)

    def resign(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        value = {k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')}
        saved['state_hash'] = canonical_hash(value)
        return saved

    def test_snapshot_rejects_changed_origin_consumption_and_omitted_layout(self):
        g = self.opening(self.game()); self.play(g); self.choose(g, 1)
        saved = g.snapshot()
        for edit in (lambda s: s['state']['players']['1']['sideboards'][0]['cards'].__setitem__(0, 'card.39'),
                lambda s: s['state']['players']['1']['sideboards'][0].__setitem__('taken_slots', []),
                lambda s: s['state']['players']['1']['sideboards'][0].__setitem__('taken_slots', [1,1]),
                lambda s: s['state']['players']['1'].pop('sideboards'),
                lambda s: s['match_setup']['decks'][0].pop('sideboards'),
                lambda s: s['state']['players']['1'].__setitem__('deck_class', CardClass.WARRIOR.value),
                lambda s: s['state']['players']['1'].__setitem__('runes', {'blood':3, 'frost':0, 'unholy':0})):
            bad = deepcopy(saved); edit(bad)
            with self.assertRaises(SnapshotError): Game.from_snapshot(self.resign(bad), registry())

    def test_sideboard_candidates_are_bound_after_signed_waiting_roundtrip(self):
        g = self.opening(self.game()); self.play(g); self.portable(g)
        g._frame = replace(g._frame, options=g._frame.options[:1])
        with self.assertRaisesRegex(ValueError, 'Sideboard waiting options'):
            g._assert_stable()

    def test_new_layout_versions_and_old_schema_explicitly_rejected(self):
        g = self.game(); saved = g.snapshot()
        self.assertEqual((saved['schema_version'], g.ruleset.id, g.mechanics.version),
            (SNAPSHOT_SCHEMA_VERSION, 'prototype-v302', CORE_EFFECTS_VERSION))
        for version in (168, 167, 1):
            bad = deepcopy(saved); bad['schema_version'] = version
            with self.assertRaisesRegex(SnapshotError, f'1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
                Game.from_snapshot(bad, registry())
