"""Both real pool-entry keywords exist before the first ordinary summon reaction."""
from dataclasses import replace
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_pool_lifesteal_cards import FORM, POOL_ID, QUERY, KEYWORDS, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword,
    PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import ChoiceOption, Damage, InvokeBehavior, RequestChoice, Silence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, LimitedTriggerSpec, SummonQuantitySpec
from hs_sim.engine.pool_summons import validate_weighted_request
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, SummonFromPool
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonEntryMaterial

P = 'k141.'
PLAIN, PRINTED, WRONG, UNKNOWN = (P+n for n in ('plain', 'printed', 'wrong', 'unknown'))
YETI = 'CORE_CS2_182'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CTX = GenerationContext('k141-complete-explicit-fixture', 'experimental')


def registry(members=(PLAIN,), mode=None):
    r = build_registry()
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K141 deliberate failure')))
    for cid, cost, keywords in ((PLAIN, 6, ()), (PRINTED, 6, (Keyword.LIFESTEAL,)), (WRONG, 5, ())):
        card = CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=4, health=7,
            keywords=keywords, battlecry=P+'fail', metadata=replace(META, collectible=True))
        r.register_card(card)
        r.register_pool_card(PoolCard.from_definition(card))
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 6, replace(META, collectible=True)))
    r.register_card(CardDefinition(P+'twice', 'Existing summon quantity source', CardType.MINION,
        health=5, metadata=META, summon_quantities=(SummonQuantitySpec(),)))
    scripts = {
        'wound': lambda c: (Damage(c.state.players[1].hero_id, 7, c.source_id),),
        'hit': lambda c: (Damage(c.state.players[2].hero_id, 4, c.target_id, DamageKind.MINION_ABILITY),),
        'silence': lambda c: (Silence(c.target_id),),
    }
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        kw = {} if name == 'wound' else dict(targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='friendly'))
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name, metadata=META, **kw))
    r.register_pool(PoolDefinition(POOL_ID, 'k141-full-weighted-v1', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid, 3 if cid == PLAIN else 1) for cid in members), complete=True))
    if mode:
        def eligible(c):
            return any(root.request.cause.source.card_id == FORM and any(d.entity is not None and
                d.entity.entity_id == c.event.target_id for d in root.deliveries) for root in c.state.card_summon_history)

        def watch(c):
            body = c.state.entities[c.event.target_id]
            if not all(k in body.keywords for k in KEYWORDS):
                raise ResolutionError('Original summon observer saw missing entry keyword')
            if mode == 'fail':
                return (InvokeBehavior(P+'fail', c.source_id, 1),)
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, 1),))), c.source_id),)

        r.register_behavior(P+'watch', watch)
        r.register_trigger_condition(P+'eligible', eligible)
        r.register_card(CardDefinition(P+'watch', 'Actual original entry witness', CardType.WEAPON,
            durability=5, metadata=META,
            limited_triggers=(LimitedTriggerSpec('minion_summoned', P+'watch', condition_id=P+'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared(members, mode):
    return registry(members, mode)


class NativePoolLifestealTests(unittest.TestCase):
    def game(self, hand=(FORM,), board=(), members=(PLAIN,), mode=None):
        self.config = (members, mode)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=(YETI,)*8, mana=30, max_mana=30, mana_cap=30,
            weapon_card_id=P+'watch' if mode else None), PlayerSetup('HERO_08', deck=(YETI,)*8)),
            seed=141, generation_context=CTX), shared(*self.config))

    def play(self, g, cid=FORM, target=None):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, source, target))
        return source

    def root(self, g):
        return next(x for x in g.state.card_summon_history if x.request.cause.source.card_id == FORM)

    def bodies(self, g):
        return [g.state.entities[d.entity.entity_id] for d in self.root(g).deliveries if d.entity is not None]

    def choose(self, g, key='ok'):
        g.apply(SelectChoice(1, g.state.pending_choice.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in ('pool_basis', 'entry_keywords', 'card_summon_history', 'resolution_frame', 'rng_state'):
                self.assertNotIn('"'+key+'"', public)
        return other

    def test_full_source_four_faces_two_parent_links_and_native_face(self):
        from tools.card_batch import check_face
        data = load_batch()
        rows = {x['record']['id']: x['record'] for x in data['cards']+data['evidence_only']}
        self.assertEqual(len(data['official_observations']), 4)
        faces = {(x['card_id'], x['locale']): x['face'] for x in data['official_observations']}
        for o in data['official_observations']:
            check_face(rows[o['card_id']], o['face'], o['locale'])
        for link in data['exact_parent_child_links']:
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
        c = shared((PLAIN,), None).card(FORM)
        self.assertEqual((c.cost, c.attack, c.health, c.metadata, c.keywords),
            (6, 6, 6, metadata_from_record(rows[FORM]), ()))
        self.assertNotIn('TLC_452', shared((PLAIN,), None).cards)

    def test_real_paid_battlecry_summons_without_triggering_selected_battlecry(self):
        g = self.game()
        source = self.play(g)
        body, = self.bodies(g)
        self.assertEqual((body.card_id, body.attack, body.health), (PLAIN, 4, 7))
        self.assertTrue(all(k in body.keywords for k in KEYWORDS))
        self.assertFalse(g.registry.card(PLAIN).keywords)
        self.assertEqual(g.state.players[1].mana, 24)
        self.assertEqual(len(g.state.battlecry_history), 1)
        self.assertEqual(self.root(g).request.pool_basis.entry_keywords, KEYWORDS)
        self.assertEqual(self.root(g).request.materials, (SummonEntryMaterial(PLAIN, keywords=KEYWORDS),))
        self.assertTrue(all(any(a.keyword == k and a.source_id == source for a in body.abilities) for k in KEYWORDS))

    def test_exact_six_cost_full_weighted_pool_keeps_plain_and_printed_lifesteal(self):
        g = self.game(members=(PLAIN, PRINTED, WRONG))
        rng = random.Random()
        rng.setstate(g._rng.getstate())
        expected = PLAIN if rng.randrange(4) < 3 else PRINTED
        self.play(g)
        self.assertEqual(self.bodies(g)[0].card_id, expected)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual([(x.card_id, x.weight) for x in self.root(g).request.pool_basis.candidates], [(PLAIN, 3), (PRINTED, 1)])

    def test_actual_lifesteal_grant_heals_once_including_already_printed_lifesteal(self):
        for cid in (PLAIN, PRINTED):
            with self.subTest(cid=cid):
                g = self.game((FORM, P+'wound', P+'hit'), members=(cid,))
                self.play(g, P+'wound')
                self.play(g)
                self.play(g, P+'hit', self.bodies(g)[0].id)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 27)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)

    def test_quantity_extra_wait_restore_replay_and_failed_resume_keep_both_keywords(self):
        g = self.game(board=(P+'twice',), mode='wait')
        self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.bodies(g)), 1)
        self.assertTrue(all(k in self.bodies(g)[0].keywords for k in KEYWORDS))
        saved, rng = g.snapshot(), g._rng.getstate()
        other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            while game.state.pending_choice is not None:
                self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(len(self.bodies(g)), 2)
        self.assertEqual(self.root(g).plan.total, 2)
        self.assertTrue(all(k in b.keywords for b in self.bodies(g) for k in KEYWORDS))
        self.portable(g)

    def test_silence_removes_both_local_keywords_and_does_not_affect_old_body(self):
        g = self.game((FORM, P+'silence'), board=(PLAIN,))
        old = g.state.players[1].board[0]
        self.play(g)
        body, = self.bodies(g)
        self.play(g, P+'silence', body.id)
        self.assertTrue(g.state.entities[body.id].silenced)
        self.assertTrue(all(k not in g.state.entities[body.id].keywords for k in KEYWORDS))
        self.assertTrue(all(k not in g.state.entities[old].keywords for k in KEYWORDS))

    def test_full_board_and_empty_eligible_pool_do_not_draw_random(self):
        for board, members in (((YETI,)*6, (PLAIN,)), ((), (WRONG,))):
            with self.subTest(full=bool(board)):
                g = self.game(board=board, members=members)
                before = g._rng.getstate()
                self.play(g)
                self.assertEqual(g._rng.getstate(), before)
                self.assertFalse(self.bodies(g))
                self.assertEqual(g.state.players[1].mana, 24)

    def test_unknown_eligible_before_rng_even_full_and_entry_failure_roll_back_payment(self):
        for board, members, mode in (((), (PLAIN, UNKNOWN), None), ((YETI,)*6, (UNKNOWN,), None), ((), (PLAIN,), 'fail')):
            with self.subTest(mode=mode, full=bool(board)):
                g = self.game(board=board, members=members, mode=mode)
                saved = g.snapshot()
                if mode is None:
                    with patch.object(random.Random, 'randrange', side_effect=AssertionError('Must reject before RNG')):
                        with self.assertRaises(ResolutionError):
                            self.play(g)
                else:
                    with self.assertRaisesRegex(ResolutionError, 'deliberate'):
                        self.play(g)
                self.assertEqual(g.snapshot(), saved)

    def test_original_basis_and_each_complete_candidate_material_must_keep_both_keywords(self):
        g = self.game(mode='wait')
        self.play(g)
        request = self.root(g).request
        validate_weighted_request(g.state, g.registry, request)
        for changed in (replace(request, materials=(SummonEntryMaterial(PLAIN, keywords=(Keyword.TAUNT,)),)),
                replace(request, pool_basis=replace(request.pool_basis, entry_keywords=(Keyword.TAUNT,)))):
            with self.assertRaises(ValueError):
                validate_weighted_request(g.state, g.registry, changed)
        saved = g.snapshot()
        saved['state']['card_summon_history'][0]['request']['pool_basis']['entry_keywords'] = ['taunt']
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry(*self.config))

    def test_codec_keeps_exact_tuple_and_rejects_unreviewed_or_unattributed_variants(self):
        g = self.game()
        source = self.play(g)
        effect = SummonFromPool(1, POOL_ID, QUERY, source_id=source,
            cause=self.root(g).request.cause, entry_keywords=KEYWORDS)
        codec = FrameCodec(g.mechanics, g.registry)
        self.assertEqual(codec.decode(codec.encode(effect)), effect)
        for kw in ((Keyword.LIFESTEAL,), (Keyword.LIFESTEAL, Keyword.TAUNT), (Keyword.TAUNT, Keyword.TAUNT),
                (Keyword.TAUNT, Keyword.RUSH), ['taunt', 'lifesteal'], ('taunt', 'lifesteal')):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                replace(effect, entry_keywords=kw)
        for changes in ({'source_id': None}, {'cause': None}, {'entry_dormant_turns': 2}):
            with self.assertRaises(ValueError):
                replace(effect, **changes)
        old = g.snapshot()
        old['schema_version'] = 347
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(old, registry(*self.config))


if __name__ == '__main__':
    unittest.main()
