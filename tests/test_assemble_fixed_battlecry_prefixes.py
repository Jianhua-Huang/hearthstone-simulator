"""Fixed printed Battlecries and independent movable death bodies stay separate."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import assemble_fixed_battlecry_prefixes as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleRecipe, printed_face
from hs_sim.engine.assemble_fixed_battlecry import AssembleFixedBattlecrySource
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_damage_health_followups import fixture as base_fixture
from test_assemble_card_play_followups import META, COIN, LOOT, N

TANK, NURSE = cards.SOURCES
FIRE, TOKEN, SERVANT = 'CORE_UNG_809', 'UNG_809t1', 'CORE_YOD_026'
CAIRNE, BRANN, AUCTION = 'CORE_EX1_110', 'LOE_077', 'JAIL_718'
MINIONS = (FIRE, SERVANT)
SPELLS = ('CORE_DS1_185', 'CORE_AT_055')
P = 'k438.'
KILL, MUTE, COPY, BASE_COPY, BOUNCE, CWATCH, GWATCH, FAIL = (
    P + key for key in ('kill', 'mute', 'copy', 'base_copy', 'bounce',
                       'copy_watch', 'generation_watch', 'fail'))
UNKNOWN = P + 'unknown'
CTX = GenerationContext('k438-fixed-original-battlecry-and-full-explicit-domains', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role); r._version += '.k438.' + mode
    scripts = {KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        MUTE: lambda c: (Silence(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='current'),),
        BASE_COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),)}
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    def fail(c): raise ResolutionError('K438 deliberate fixed prefix continuation failure')
    r.register_behavior(FAIL, fail)
    def choices(c):
        return (ChoiceOption('go', 'Continue'), ChoiceOption('bad', 'Fail',
            (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))))
    def copied(c):
        target = c.state.entities.get(c.event.target_id)
        if target is None or not target.card_id.startswith('assemble:') or target.origin_entity_id is None:
            return ()
        original = c.state.entities.get(target.origin_entity_id)
        if original is None or original.card_id != target.card_id: return ()
        return (RequestChoice(c.player_id, choices(c) + (ChoiceOption('depart', 'Original leaves',
            (Destroy(original.id, c.source_id),)),), c.source_id),)
    def generated(c):
        target = c.state.entities.get(c.event.target_id)
        if c.event.player_id != c.player_id or target is None or target.card_id not in MINIONS+SPELLS:
            return ()
        return (RequestChoice(c.player_id, choices(c), c.source_id),)
    for cid, body, event in ((CWATCH, copied, 'minion_summoned'), (GWATCH, generated, 'hand_card_entered')):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=20, metadata=META,
            triggers=(TriggerSpec(event, cid),)))
    if mode != 'no_pool':
        members = MINIONS+SPELLS+(LOOT, COIN)
        if mode.startswith('unknown_'):
            base = FIRE if mode == 'unknown_minion' else SPELLS[0]
            r.register_pool_card(replace(r.pool_card(base), card_id=UNKNOWN)); members += (UNKNOWN,)
        r.register_pool(PoolDefinition('constructed.cards', 'k438-two-one-cost-minions-two-one-cost-spells',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode == 'offer':
        r.register_pool(PoolDefinition(POOL_ID, 'k438-one-cost-nurse-six-cost-tank-nine-cost-donor',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (NURSE, TANK, AUCTION)), complete=True))
    r.validate(); return r


class AssembleFixedBattlecryTests(unittest.TestCase):
    def game(self, hand=(), board=(), mode='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_05', hand=hand, board=board, deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50)),
            seed=438, generation_context=CTX), fixture(mode))

    def eid(self, g, cid, zone='hand'):
        return next(i for i in getattr(g.state.players[1], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        source = self.eid(g, cid); g.apply(PlayCard(1, source, target)); return source

    def count(self, g, cid, zone='hand'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[1], zone))

    def generated(self, g, kind):
        ids = MINIONS if kind == CardType.MINION else SPELLS
        return sum(g.state.entities[i].card_id in ids for i in g.state.players[1].hand)

    def pick(self, g, key='go'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def drain(self, g):
        while g.state.pending_choice is not None: self.pick(g)

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'assemble_fixed_battlecry_sources', 'primary_candidates'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a_complete_rows_faces_original_bodies_queries_and_self_noops(self):
        d = cards.load_batch(); r = fixture(); rows = {x['record']['id']: x for x in d['existing_dependencies']}
        self.assertEqual(len(rows), 2); self.assertEqual(len(d['official_observations']), 4)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
        for cid in cards.SOURCES:
            old = r.card(cid); face = r.card(recipe(cid))
            self.assertEqual(canonical_digest(asdict(old)), rows[cid]['definition_sha256'])
            self.assertEqual((face.cost, face.attack, face.health, face.metadata, face.battlecry, face.deathrattle),
                (old.cost, old.attack, old.health, old.metadata, old.battlecry, old.deathrattle))
            self.assertEqual(recipe_options(r, cid, cid), ())
        self.assertEqual(set(d['native_queries']), {NURSE+'.bc', NURSE+'.dr'})

    def test_b_original_and_self_tank_pay_once_copy_current_face_twice_and_keep_three_deaths(self):
        for cid in (TANK, recipe(TANK)):
            g = self.game((cid, KILL, KILL, KILL)); source = self.play(g, cid)
            self.assertEqual(g.state.players[1].mana, 44); self.assertEqual(self.count(g, cid, 'board'), 3)
            bodies = tuple(g.state.players[1].board)
            self.assertEqual([g.state.entities[i].card_id for i in bodies], [cid]*3)
            for i in bodies: self.play(g, KILL, i)
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 21)
            self.assertEqual(len([d for d in g.state.death_history if d.card_id == cid]), 3)

    def test_c_original_and_self_nurse_keep_independent_one_cost_minion_and_spell_queries(self):
        for cid in (NURSE, recipe(NURSE)):
            g = self.game((cid, KILL)); source = self.play(g, cid)
            self.assertEqual(g.state.players[1].mana, 49)
            self.assertEqual((self.generated(g, CardType.MINION), self.generated(g, CardType.SPELL)), (1, 0))
            self.play(g, KILL, source)
            self.assertEqual((self.generated(g, CardType.MINION), self.generated(g, CardType.SPELL)), (1, 1))

    def test_d_borrowing_only_tank_damage_body_as_battlecry_does_not_borrow_fixed_copies(self):
        cid = recipe(FIRE, TANK); g = self.game((cid,)); self.play(g, cid)
        self.assertEqual(self.count(g, cid, 'board'), 1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
        self.assertIsNone(g.registry.card(cid).deathrattle)

    def test_e_replacing_nurse_prefix_clears_old_minion_battlecry_and_runs_only_spell_body(self):
        cid = recipe(NURSE, FIRE, 'top'); g = self.game((cid,)); self.play(g, cid)
        self.assertEqual((self.generated(g, CardType.MINION), self.generated(g, CardType.SPELL)), (0, 1))
        self.assertIsNone(g.registry.card(cid).deathrattle)

    def test_f_nurse_prefix_keeps_fixed_minion_battlecry_but_replaces_death_with_draw(self):
        cid = recipe(NURSE, LOOT); g = self.game((cid, KILL)); source = self.play(g, cid)
        self.assertEqual(self.generated(g, CardType.MINION), 1); self.play(g, KILL, source)
        self.assertEqual(self.count(g, COIN), 1); self.assertEqual(self.generated(g, CardType.SPELL), 0)

    def test_g_borrowed_nurse_prefix_uses_selected_fixed_body_and_primary_numbers(self):
        cid = recipe(FIRE, NURSE, 'top'); g = self.game((cid, KILL)); source = self.play(g, cid)
        face = g.registry.card(cid)
        self.assertEqual((face.cost, face.attack, face.health), (1, 1, 2))
        self.assertEqual(self.generated(g, CardType.MINION), 1); self.assertEqual(self.count(g, TOKEN), 0)
        self.play(g, KILL, source); self.assertEqual(self.count(g, TOKEN), 1)

    def test_h_replacing_tank_prefix_removes_old_fixed_copies_but_keeps_its_damage_body(self):
        cid = recipe(TANK, CAIRNE, 'top'); g = self.game((cid, KILL)); source = self.play(g, cid)
        self.assertEqual(self.count(g, cid, 'board'), 1); self.assertIsNone(g.registry.card(cid).battlecry)
        self.play(g, KILL, source); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)

    def test_i_native_board_capacity_keeps_one_payment_and_partial_original_copy_plan(self):
        cid = recipe(TANK); g = self.game((cid,), (N,)*5); self.play(g, cid)
        self.assertEqual(len(g.state.players[1].board), 7); self.assertEqual(self.count(g, cid, 'board'), 2)
        self.assertEqual(g.state.players[1].mana, 44)

    def test_j_fixed_battlecry_uses_native_repeat_plan_without_repeating_future_death(self):
        cid = recipe(TANK); g = self.game((cid, KILL), (BRANN,)); source = self.play(g, cid)
        self.assertEqual(self.count(g, cid, 'board'), 5); self.assertEqual(g.state.players[1].mana, 44)
        self.play(g, KILL, source); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)

    def test_k_silenced_current_copy_base_copy_and_return_keep_new_printed_fixed_material(self):
        cid = recipe(NURSE); g = self.game((MUTE, COPY, BASE_COPY, BOUNCE, KILL), (cid,))
        source = self.eid(g, cid, 'board'); self.play(g, MUTE, source)
        before = set(g.state.players[1].board); self.play(g, COPY, source)
        current = (set(g.state.players[1].board)-before).pop(); self.assertTrue(g.state.entities[current].silenced)
        before = set(g.state.players[1].board); self.play(g, BASE_COPY, source)
        base = (set(g.state.players[1].board)-before).pop(); self.assertFalse(g.state.entities[base].silenced)
        self.assertEqual(self.generated(g, CardType.MINION), 0)
        self.play(g, BOUNCE, base); replayed = self.play(g, cid)
        self.assertEqual(self.generated(g, CardType.MINION), 1); self.play(g, KILL, replayed)
        self.assertEqual(self.generated(g, CardType.SPELL), 1)

    def test_l_first_copy_wait_restores_and_original_departure_does_not_retarget_second_copy(self):
        cid = recipe(TANK, CAIRNE); g = self.game((cid,), (CWATCH,)); source = self.play(g, cid)
        reader = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.pick(g, 'depart'); self.pick(reader, 'depart')
        self.drain(g); self.drain(reader); self.assertEqual(g.snapshot(), reader.snapshot())
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.count(g, cid, 'board'), 1); self.assertEqual(g.state.players[1].mana, 44)

    def test_m_fixed_battlecry_and_death_generation_waits_restore_and_keep_original_query(self):
        cid = recipe(NURSE); g = self.game((cid, KILL), (GWATCH,)); source = self.play(g, cid)
        for phase in ('battlecry', 'death'):
            if phase == 'death': self.play(g, KILL, source)
            reader = self.portable(g); saved = g.snapshot()
            with self.assertRaises(ResolutionError): self.pick(g, 'bad')
            self.assertEqual(g.snapshot(), saved); self.drain(g); self.drain(reader)
            self.assertEqual(g.snapshot(), reader.snapshot())
        self.assertEqual((self.generated(g, CardType.MINION), self.generated(g, CardType.SPELL)), (1, 1))

    def test_n_real_mismatch_transfers_fixed_copy_prefix_and_all_copies_keep_new_spell_death(self):
        cid = recipe(NURSE, TANK, 'top'); g = self.game((MISMATCH, KILL, KILL, KILL), mode='offer')
        entry = self.play(g, MISMATCH); self.portable(g, 'offer')
        q = g.state.pending_choice; self.pick(g, next(o.id for o in q.options if o.card_id == cid))
        mana = g.state.players[1].mana; self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana-1); self.assertEqual(self.count(g, cid, 'board'), 3)
        self.assertEqual(self.generated(g, CardType.MINION), 0); self.assertIn(entry, g.state.players[1].board)
        bodies = [i for i in g.state.players[1].board if g.state.entities[i].card_id == cid]
        for eid in bodies: self.play(g, KILL, eid)
        self.assertEqual(self.generated(g, CardType.SPELL), 3)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_o_missing_pool_or_eligible_unknown_minion_rolls_back_fixed_battlecry_payment(self):
        for mode in ('no_pool', 'unknown_minion'):
            g = self.game((recipe(NURSE),), mode=mode); saved = g.snapshot()
            with self.assertRaises((ValueError, ResolutionError)): self.play(g, recipe(NURSE))
            self.assertEqual(g.snapshot(), saved)

    def test_p_eligible_unknown_spell_rolls_back_death_without_discarding_the_candidate(self):
        cid = recipe(NURSE); g = self.game((cid, KILL), mode='unknown_spell'); source = self.play(g, cid)
        saved = g.snapshot()
        with self.assertRaises((ValueError, ResolutionError)): self.play(g, KILL, source)
        self.assertEqual(g.snapshot(), saved)

    def test_q_complete_fixed_material_profiles_and_generation_queries_are_strict(self):
        r = fixture.__wrapped__('normal', 'strict'); profile = r.assemble_fixed_battlecry_sources[TANK]
        with self.assertRaises(TypeError): r.assemble_fixed_battlecry_sources['x'] = profile
        with self.assertRaises(ValueError): r.register_assemble_fixed_battlecry_source(profile)
        with self.assertRaises(ValueError): r.register_assemble_fixed_battlecry_source(replace(profile, battlecry_id=r.card(NURSE).battlecry))
        missing = fixture.__wrapped__(); missing._assemble_fixed_battlecry_sources.pop(TANK)
        with self.assertRaises(ValueError): recipe_options(missing, TANK, TANK)
        orphan = fixture.__wrapped__(); orphan._assemble_templates.pop(TANK)
        with self.assertRaises(ValueError): orphan.validate()
        t = r.assemble_templates[TANK]
        with self.assertRaises(ValueError): printed_face(r.card(TANK), AssemblePrefix('battlecry'),
            t.suffix, 'invalid.k438', fixed_battlecry=profile.battlecry_id)
        with patch.dict(cards.QUERIES, {NURSE+'.bc': PoolQuery(kinds=(CardType.SPELL,))}):
            with self.assertRaises(TargetValidationError): cards.load_batch()
        broken = fixture.__wrapped__(); broken._cards[TANK] = replace(broken.card(TANK), health=4)
        with self.assertRaises(TargetValidationError): cards.register_assemble_fixed_battlecry_prefixes(broken)


if __name__ == '__main__':
    unittest.main()
