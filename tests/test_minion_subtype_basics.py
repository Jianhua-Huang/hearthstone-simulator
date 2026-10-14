"""Printed Imp/Whelp identity is independent of tribes, factions and card names."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    Keyword, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice,
    SnapshotError, SpellSchool, TargetSpec, TribeChangeSpec, UnsupportedDefinitionError, Zone,
    has_any_subtype, has_any_tribe)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import MinionScope, minion_references
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy, Draw,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.pools import (GenerationContext, GenerateFromPool, PoolCard, PoolDefinition,
    PoolMember, PoolQuery, resolve_candidates)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError, canonical_digest
from opening_fixtures import metadata

ROOT = Path(__file__).resolve().parents[1]
PIN = '666331ff578b23f14f4d5ba5f0ffa222d83cbde79b0d3db1fbd57b0f2ea611c7'
IMP = 'EX1_598'; WHELP = 'ds1_whelptoken'; SPELL = 'REV_245'
CONTEXT = GenerationContext('subtype-test', 'experimental')


def evidence():
    data = json.loads((ROOT / 'data/support/minion-subtype-basics.json').read_bytes())
    if canonical_digest(data) != PIN:
        raise ValueError('Subtype evidence changed')
    for row in data['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Subtype raw row changed')
    return data


def registry(*, unknown=False, missing=False, equivalent=False):
    r = Registry('isolated-minion-subtypes-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=80,
        metadata=metadata(CardClass.WARLOCK, tribes=(), subtypes=())))
    rows = {row['id']: row['data'] for row in evidence()['records']}
    for cid in (IMP, WHELP):
        raw = rows[cid]
        r.register_card(CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw)))
    def catastrophe(c):
        count = sum(has_any_subtype(r, c.state.entities[i], ('imp',))
            for i in c.state.players[c.player_id].board if c.state.entities[i].active
            and c.state.entities[i].health > 0 and not c.state.entities[i].doomed)
        return (Draw(c.player_id, 1 + count),)
    raw = rows[SPELL]
    r.register_behavior('catastrophe', catastrophe)
    r.register_card(CardDefinition(SPELL, raw['name'], CardType.SPELL, cost=raw['cost'],
        on_play='catastrophe', spell_school=SpellSchool.SHADOW, metadata=metadata_from_record(raw)))
    for cid, name, tribes, subtypes in (
        ('plain', 'Plain', (), ()), ('demon', 'Imp in display name only', ('demon',), ()),
        ('dragon', 'Whelp in display name only', ('dragon',), ()), ('all', 'All tribes', ('all',), ()),
        ('renamed', 'Unrelated displayed name', ('demon',), ('imp',))):
        r.register_card(CardDefinition(cid, name, CardType.MINION, cost=1, attack=1, health=3,
            metadata=metadata(tribes=tribes, factions=(), subtypes=subtypes)))
    if unknown:
        r.register_card(CardDefinition('unknown', 'Unknown subtype', CardType.MINION, attack=1, health=3,
            metadata=metadata(tribes=('demon',))))
    def ref(c):
        return MinionReference.capture(c.state.entities[c.target_id])
    def generation(c):
        return GenerateFromPool(c.player_id, 'pool', query=PoolQuery(subtypes_any=('imp',)), source_id=c.source_id)
    scripts = {
        'copy': lambda c: (CopyCard(ref(c), c.player_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'transform': lambda c: (Transform(c.target_id, 'demon'),),
        'into-imp': lambda c: (Transform(c.target_id, IMP),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'return': lambda c: (ReturnToHand(c.target_id),),
        'destroy': lambda c: (Destroy(c.target_id, c.source_id),),
        'sleep': lambda c: (MakeDormant(c.target_id, None),),
        'tribe': lambda c: (ChangeMinionTribes(ref(c), TribeChangeSpec('set', ('beast',)), c.source_id),),
        'generate': lambda c: (generation(c),),
        'fault': lambda c: (generation(c), InvokeBehavior('late-fault', c.source_id, c.player_id)),
        'wait': lambda c: (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Generate an Imp', (generation(c),)),
            ChoiceOption('fault', 'Generate then fail', (generation(c), InvokeBehavior('late-fault', c.source_id, c.player_id)))), c.source_id),),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(kinds=(CardType.MINION,)) if cid in ('copy', 'silence', 'transform', 'into-imp',
                'control', 'return', 'destroy', 'sleep', 'tribe') else None,
            metadata=metadata(tribes=(), subtypes=())))
    r.register_behavior('late-fault', lambda c: (AddToHand(c.player_id, 'unknown.subtype-fault'),))
    ids = (IMP, WHELP, 'demon', 'dragon', 'all', 'plain', 'renamed')
    for cid in ids:
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if unknown:
        r.register_pool_card(PoolCard.from_definition(r.card('unknown'))); ids += ('unknown',)
    if missing:
        r.register_pool_card(PoolCard('unimplemented.imp', CardType.MINION, 1,
            metadata(tribes=('demon',), subtypes=('imp',)))); ids += ('unimplemented.imp',)
    if equivalent:
        for cid, subtypes in (('alias.a', ()), ('alias.b', ('imp',))):
            r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=1, health=1,
                metadata=metadata(tribes=('demon',), factions=(), subtypes=subtypes)))
            r.register_pool_card(PoolCard.from_definition(r.card(cid), identity='same'))
            ids += (cid,)
    r.register_pool(PoolDefinition('pool', 'subtypes-v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid) for cid in ids), complete=False))
    return r


class MinionSubtypeBasicsTests(unittest.TestCase):
    def game(self, hand=(), *, board=(IMP,), enemy=(), unknown=False, missing=False, cap=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('plain',) * 8,
                mana=10, max_mana=10, hand_cap=cap),
            PlayerSetup('hero', board=enemy, deck=('plain',) * 8)), seed=97, generation_context=CONTEXT),
            registry(unknown=unknown, missing=missing))
    def play(self, g, name, target=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, eid, target))
    def entity(self, g, name, player=1, zone=Zone.BOARD):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
                    if g.state.entities[i].card_id == name)
    def candidates(self, r, subtypes=('imp',), **fields):
        return tuple(m.card_id for m in resolve_candidates(r, CONTEXT, 'pool',
            PoolQuery(subtypes_any=subtypes, **fields)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        h = Game.from_snapshot(saved, registry())
        self.assertEqual(h.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        return h
    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        return g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def test_full_raw_pins_and_only_required_spell_and_vanilla_tokens(self):
        data = evidence(); r = registry()
        self.assertEqual(data['new_real_card_adapters'], [SPELL, IMP, WHELP])
        self.assertEqual(r.card(IMP).metadata.subtypes, ('imp',))
        self.assertEqual(r.card(WHELP).metadata.subtypes, ('whelp',))
        self.assertNotIn('ONY_004', r.cards); self.assertNotIn('REV_835', r.cards)

    def test_producer_query_json_restores_default_and_subtype_filters(self):
        from dataclasses import asdict
        from hs_sim.engine.pool_summons import query_from_dict
        r = registry()
        for subtypes in ((), ('imp',), ('whelp',), ('imp', 'whelp')):
            with self.subTest(subtypes=subtypes):
                original = PoolQuery(kinds=(CardType.MINION,), subtypes_any=subtypes)
                wire = json.loads(json.dumps(asdict(original)))
                before = json.loads(json.dumps(wire))
                restored = query_from_dict(wire)
                self.assertEqual(restored, original)
                self.assertEqual(resolve_candidates(r, CONTEXT, 'pool', restored),
                                 resolve_candidates(r, CONTEXT, 'pool', original))
                self.assertEqual(wire, before)

    def test_producer_query_json_rejects_malformed_subtype_filters(self):
        from dataclasses import asdict
        from hs_sim.engine.pool_summons import query_from_dict
        wire = json.loads(json.dumps(asdict(PoolQuery())))
        for values in (None, True, 0, 'imp', {'imp': True},
                       ['imp', 'imp'], ['all'], [True], [[]]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                query_from_dict(dict(wire, subtypes_any=values))

    def test_strict_finite_metadata_and_query(self):
        for value in (['imp'], ('imp', 'imp'), ('all',), ('demon',), (True,), ({},)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                metadata(subtypes=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                PoolQuery(subtypes_any=value)
        self.assertIsNone(metadata().subtypes)
        self.assertEqual(metadata(subtypes=()).subtypes, ())

    def test_importer_rejects_unknown_flag_values_and_nonminions(self):
        raw = evidence()['records'][1]['data']
        for value in (True, -1, 2, '1'):
            with self.subTest(value=value), self.assertRaises(TargetValidationError):
                metadata_from_record(dict(raw, tags=dict(raw['tags'], IMP=value)))
        with self.assertRaises(TargetValidationError):
            metadata_from_record(dict(raw, type='SPELL'))

    def test_nonminion_positive_subtype_declarations_reject(self):
        meta = metadata(subtypes=('imp',))
        with self.assertRaises(ValueError):
            Registry('invalid-subtype').register_card(CardDefinition('x', 'x', CardType.SPELL, metadata=meta))
        with self.assertRaises(ValueError):
            PoolCard('x', CardType.SPELL, 1, meta)

    def test_ordinary_tribes_all_and_names_do_not_supply_subtypes(self):
        g = self.game(board=(IMP, WHELP, 'demon', 'dragon', 'all', 'renamed'))
        for cid in ('demon', 'dragon', 'all'):
            self.assertFalse(has_any_subtype(g.registry, self.entity(g, cid), ('imp', 'whelp')))
        self.assertTrue(has_any_subtype(g.registry, self.entity(g, 'renamed'), ('imp',)))
        self.assertTrue(has_any_subtype(g.registry, self.entity(g, WHELP), ('whelp',)))
        self.assertTrue(has_any_tribe(g.registry, self.entity(g, 'all'), ('demon',)))

    def test_unknown_metadata_is_not_silently_negative(self):
        g = self.game(board=('unknown',), unknown=True)
        with self.assertRaises(UnsupportedDefinitionError):
            has_any_subtype(g.registry, self.entity(g, 'unknown'), ('imp',))
        before = g.snapshot()
        h = self.game((SPELL,), board=('unknown',), unknown=True); saved = h.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(h, SPELL)
        self.assertEqual(h.snapshot(), saved); self.assertEqual(g.snapshot(), before)
        with self.assertRaisesRegex(ValueError, 'Unknown candidate minion subtypes'):
            self.candidates(g.registry)

    def test_subtype_pool_queries_filter_exact_membership_and_existing_tribes(self):
        r = registry()
        self.assertEqual(self.candidates(r), tuple(sorted((IMP, 'renamed'))))
        self.assertEqual(self.candidates(r, ('whelp',)), (WHELP,))
        self.assertEqual(self.candidates(r, tribes_any=('demon',)), tuple(sorted((IMP, 'renamed'))))
        self.assertEqual(self.candidates(r, ('imp', 'whelp')), tuple(sorted((IMP, WHELP, 'renamed'))))

    def test_subtype_difference_blocks_false_generation_equivalence(self):
        r = registry(equivalent=True)
        a, b = (r.pool_card(cid).filter_signature() for cid in ('alias.a', 'alias.b'))
        self.assertEqual(a[:-1], b[:-1])
        self.assertNotEqual(a[-1], b[-1])
        with self.assertRaisesRegex(ValueError, 'Conflicting generation aliases'):
            r.validate()

    def test_physical_zone_query_reuses_original_reference_and_metadata(self):
        g = self.game(hand=(IMP, 'demon'), board=(IMP, WHELP, 'all'))
        refs = minion_references(g.state, g.registry, 1,
            MinionScope(zones=(Zone.HAND, Zone.BOARD), query=PoolQuery(subtypes_any=('imp',))))
        self.assertEqual([g.state.entities[r.entity_id].card_id for r in refs], [IMP, IMP])
        self.assertEqual([type(r).__name__ for r in refs], ['CardReference', 'MinionReference'])

    def test_real_catastrophe_counts_only_friendly_active_imps_and_pays_once(self):
        g = self.game((SPELL,), board=(IMP, IMP, 'demon', 'all', WHELP), enemy=(IMP,))
        self.play(g, SPELL)
        self.assertEqual(len(g.state.players[1].hand), 3)
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(sum(e.kind == 'card_drawn' for e in g.events), 3)
        self.portable(g)

    def test_real_zero_imps_still_draws_the_base_card(self):
        g = self.game((SPELL,), board=('demon', 'all', WHELP))
        self.play(g, SPELL); self.assertEqual(len(g.state.players[1].hand), 1); self.portable(g)

    def test_silence_keeps_printed_subtype(self):
        g = self.game(('silence', SPELL)); self.play(g, 'silence', self.entity(g, IMP).id)
        self.assertTrue(self.entity(g, IMP).silenced)
        self.play(g, SPELL); self.assertEqual(len(g.state.players[1].hand), 2); self.portable(g)

    def test_ordinary_tribe_change_does_not_grant_or_remove_subtype(self):
        g = self.game(('tribe', SPELL)); self.play(g, 'tribe', self.entity(g, IMP).id)
        e = self.entity(g, IMP)
        self.assertTrue(has_any_tribe(g.registry, e, ('beast',)))
        self.assertFalse(has_any_tribe(g.registry, e, ('demon',)))
        self.assertTrue(has_any_subtype(g.registry, e, ('imp',)))
        self.play(g, SPELL); self.portable(g)

    def test_copy_and_return_reuse_current_face_membership(self):
        g = self.game(('copy', 'return')); original = self.entity(g, IMP).id
        self.play(g, 'copy', original); copied = self.entity(g, IMP, zone=Zone.HAND)
        self.assertNotEqual(copied.id, original)
        self.assertTrue(has_any_subtype(g.registry, copied, ('imp',)))
        self.play(g, 'return', original)
        self.assertTrue(has_any_subtype(g.registry, g.state.entities[original], ('imp',)))
        self.portable(g)

    def test_transform_reads_new_face_instead_of_physical_origin(self):
        g = self.game(('transform', 'into-imp')); eid = self.entity(g, IMP).id
        self.play(g, 'transform', eid)
        self.assertFalse(has_any_subtype(g.registry, g.state.entities[eid], ('imp',)))
        self.play(g, 'into-imp', eid)
        self.assertTrue(has_any_subtype(g.registry, g.state.entities[eid], ('imp',))); self.portable(g)

    def test_control_transfer_uses_current_controller_for_count(self):
        g = self.game(('control', SPELL)); self.play(g, 'control', self.entity(g, IMP).id)
        self.play(g, SPELL); self.assertEqual(len(g.state.players[1].hand), 1); self.portable(g)

    def test_dormant_source_keeps_identity_but_is_not_live_count(self):
        g = self.game(('sleep', SPELL)); eid = self.entity(g, IMP).id
        self.play(g, 'sleep', eid)
        self.assertTrue(has_any_subtype(g.registry, g.state.entities[eid], ('imp',)))
        self.play(g, SPELL); self.assertEqual(len(g.state.players[1].hand), 1); self.portable(g)

    def test_death_history_keeps_original_face_queryable_without_live_count(self):
        g = self.game(('destroy', SPELL)); eid = self.entity(g, IMP).id
        self.play(g, 'destroy', eid)
        self.assertEqual(g.state.death_history[-1].card_id, IMP)
        self.assertTrue(has_any_subtype(g.registry, g.state.entities[eid], ('imp',)))
        self.play(g, SPELL); self.assertEqual(len(g.state.players[1].hand), 1); self.portable(g)

    def test_unimplemented_matching_candidate_is_not_removed(self):
        g = self.game(('generate',), missing=True)
        with self.assertRaisesRegex(UnsupportedDefinitionError, 'unimplemented.imp'):
            self.candidates(g.registry)
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'unimplemented.imp'):
            self.play(g, 'generate')
        self.assertEqual(g.snapshot(), before)

    def test_waiting_query_restores_clone_replay_and_resumes_once(self):
        g = self.game(('wait',)); self.play(g, 'wait'); h = self.portable(g)
        self.choose(g); self.choose(h); self.assertEqual(g.snapshot(), h.snapshot())
        e = g.state.entities[g.state.players[1].hand[-1]]
        self.assertTrue(has_any_subtype(g.registry, e, ('imp',))); self.portable(g)

    def test_direct_and_waiting_generation_failure_roll_back_rng_and_state(self):
        g = self.game(('fault',)); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        g = self.game(('wait',)); self.play(g, 'wait'); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.choose(g); self.portable(g)

    def test_query_codec_and_player_view_keep_private_metadata_private(self):
        g = self.game((IMP, 'wait')); query = PoolQuery(subtypes_any=('imp',))
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(query)), query)
        before = g.observe(2); self.play(g, 'wait')
        visible = json.dumps(g.observe(2)) + json.dumps(g.for_player(2).legal_actions())
        for key in ('subtypes', 'subtypes_any', 'resolution_frame', 'MinionReference'):
            self.assertNotIn('"' + key + '"', visible)
        self.assertIsNone(before['players'][0]['hand'][0]['card_id']); self.portable(g)

    def test_positive_played_face_metadata_is_frozen_restored_and_strictly_decoded(self):
        g = self.game((IMP, 'transform'), board=())
        self.play(g, IMP)
        face = g.state.play_history[-1].played_face
        self.assertEqual(face.metadata.subtypes, ('imp',))
        self.play(g, 'transform', self.entity(g, IMP).id)
        self.assertEqual(g.state.play_history[0].played_face.metadata.subtypes, ('imp',))
        self.assertEqual(self.portable(g).state.play_history[0].played_face.metadata.subtypes, ('imp',))
        saved = g.snapshot()
        self.assertEqual(saved['state']['play_history'][0]['played_face']['metadata']['subtypes'], ['imp'])
        for values in (['all'], [True], ['imp', 'imp'], ['whelp']):
            bad = json.loads(json.dumps(saved))
            bad['state']['play_history'][0]['played_face']['metadata']['subtypes'] = values
            with self.subTest(values=values), self.assertRaises(SnapshotError):
                Game.from_snapshot(bad, registry())
