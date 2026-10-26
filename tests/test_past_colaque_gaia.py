"""Real native bodies, current named presence and completed physical Mech attacks."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_colaque_gaia import (COLAQUE, GAIA, SHELL, DRILLS, BODY,
    load_batch, register_past_colaque_gaia)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, Keyword, KeywordAuraSpec, PlayerSetup, ResolutionError, Scenario,
    SnapshotError, TargetMode, TargetSpec, TriggerSpec, TribeChangeSpec, Zone)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, EquipWeapon, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.model import DamageKind
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k581.'
UNIT, MECH, TINY, UNKNOWN, WATCH = (P+x for x in ('unit', 'mech', 'tiny', 'unknown', 'watch'))
KILL, SHOT, QUIET, GIVE, BOUNCE, COPY, BASE, DORMANT, AWAY, SET_MECH, SET_BEAST, ADD_GAIA, EQUIP = (
    P+x for x in ('kill', 'shot', 'silence', 'give', 'bounce', 'copy', 'base', 'dormant', 'away', 'mech-type', 'beast-type', 'gaia', 'equip'))
SOURCE = 'CATA_EVENT_000'
CONTEXT = GenerationContext(P+'explicit-native-fixtures', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('beast',))


@lru_cache(None)
def host(mode='colaque', role='writer'):
    r = build_cn37_local_pool_format().registry
    cid = COLAQUE if mode.startswith('colaque') else GAIA
    r.register_pool(PoolDefinition('constructed.past.cards', P+'one-original-body:'+mode,
        CONTEXT.target_id, CONTEXT.mode, (PoolMember(cid),), complete=True))
    for name, attack, health, tribes in ((UNIT, 1, 20, ('beast',)), (MECH, 1, 1, ('mech',)),
            (TINY, 1, 1, ('beast',)), (UNKNOWN, 1, 2, None)):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=attack,
            health=health, metadata=replace(META, tribes=tribes)))
    def fail(c): raise ResolutionError('K581 deliberate late notification failure')
    def watch(c):
        accepted = (mode == 'gaia-wait' and c.event.kind == 'damage_dealt' and
            c.event.target_id == c.state.players[3-c.player_id].hero_id and
            c.state.entities[c.event.source_id].card_id == GAIA) or (
            mode == 'colaque-wait' and c.event.kind == 'armor_gained' and c.event.player_id == c.player_id and c.event.amount == 8)
        if not accepted: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'continue', ()),
            ChoiceOption('bad', 'fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=tuple(TriggerSpec(e, P+'watch') for e in ('damage_dealt', 'armor_gained'))))
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SHOT: lambda c: (Damage(c.target_id, 3, c.source_id, DamageKind.SPELL),),
        QUIET: lambda c: (Silence(c.target_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        BASE: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        DORMANT: lambda c: (MakeDormant(c.target_id, None, c.source_id),),
        AWAY: lambda c: (Transform(c.target_id, UNIT),),
        SET_MECH: lambda c: (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]), TribeChangeSpec('set', ('mech',)), c.source_id),),
        SET_BEAST: lambda c: (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]), TribeChangeSpec('set', ('beast',)), c.source_id),),
        ADD_GAIA: lambda c: (Summon(c.player_id, GAIA),),
        EQUIP: lambda c: (EquipWeapon(c.player_id, 'CS2_106'),),
    }
    for name, body in scripts.items():
        r.register_behavior(name, body)
        targeting = None if name in (ADD_GAIA, EQUIP) else TargetSpec(TargetMode.REQUIRED,
            zones=(Zone.BOARD,), kinds=(CardType.MINION,))
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, targeting=targeting, metadata=META))
    r.validate(); return r


def fixture(mode='colaque', role='writer'): return host(mode, role)


class PastColaqueGaiaTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)
    mode = 'colaque'

    def game(self, cid=COLAQUE, *, hand=(), own=(), enemy=(UNIT,), player=1, mode=None):
        self.mode = mode or ('colaque' if cid == COLAQUE else 'gaia')
        if self.mode.endswith('-wait'): own = (WATCH, *own)
        players = tuple(PlayerSetup('HERO_03' if p == player else 'HERO_08',
            hand=(SOURCE, *hand) if p == player else (), board=own if p == player else enemy,
            deck=(UNIT,)*8, mana=40, max_mana=40, mana_cap=40) for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=player, seed=581,
            generation_context=CONTEXT), host(self.mode))

    def reward(self, g, cid=COLAQUE, player=1):
        self.play(g, SOURCE, player=player); return self.play(g, cid, player=player)

    def immune(self, g, eid): return Keyword.IMMUNE in g.state.entities[eid].keywords

    def test_complete_original_faces_old_appendages_and_unmodified_thirteen_member_reference(self):
        data = load_batch(); self.assertEqual(len(data['official_observations']), 4)
        for row in data['cards']:
            for face in [x for x in data['official_observations'] if x['card_id'] == row['record']['id']]:
                batch.check_face(row['record'], face['face'], face['locale'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        reference = batch.read('data/cards/past-colossal-local-reference-v1.json')
        self.assertEqual(len(reference['candidate_ids']), 13); self.assertFalse(reference['runtime_bindings_added'])

    def test_both_actual_paid_parent_rewards_and_native_entry_in_both_seats_keep_explicit_fixture_scope(self):
        for player, cid in ((1, COLAQUE), (2, GAIA)):
            g = self.game(cid, player=player); self.reward(g, cid, player)
            ids = [g.state.entities[i].card_id for i in g.state.players[player].board]
            expected = [SOURCE, COLAQUE, SHELL] if cid == COLAQUE else [SOURCE, DRILLS[0], GAIA, DRILLS[1]]
            self.assertEqual(ids, expected)
            self.assertEqual(g.state.players[player].mana, 40-g.registry.card(SOURCE).cost-g.registry.card(cid).cost)
            self.assertEqual(tuple(m.card_id for m in g.registry.pool('constructed.past.cards', CONTEXT).members), (cid,))

    def test_colaque_immune_until_actual_shell_death_then_real_armor_and_damage(self):
        g = self.game(hand=(SHOT, KILL, SHOT)); body = self.reward(g)
        self.assertTrue(self.immune(g, body)); self.play(g, SHOT, body)
        self.assertEqual(g.state.entities[body].health, 5)
        shell = self.entity(g, SHELL, zone='board').id; self.play(g, KILL, shell)
        self.assertFalse(self.immune(g, body)); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 8)
        self.play(g, SHOT, body); self.assertEqual(g.state.entities[body].health, 2)

    def test_shell_silence_preserves_current_identity_but_source_silence_removes_native_immunity(self):
        g = self.game(hand=(QUIET, QUIET)); body = self.reward(g)
        self.play(g, QUIET, self.entity(g, SHELL, zone='board').id); self.assertTrue(self.immune(g, body))
        self.play(g, QUIET, body); self.assertFalse(self.immune(g, body))

    def test_other_friendly_shell_qualifies_and_two_control_transfers_follow_current_controller(self):
        g = self.game(hand=(KILL, KILL), own=(SHELL,)); body = self.reward(g)
        shells = [i for i in g.state.players[1].board if g.state.entities[i].card_id == SHELL]
        self.play(g, KILL, shells[-1]); self.assertTrue(self.immune(g, body))
        self.play(g, KILL, shells[0]); self.assertFalse(self.immune(g, body))
        h = self.game(hand=(GIVE, GIVE)); body = self.reward(h); shell = self.entity(h, SHELL, zone='board').id
        self.play(h, GIVE, body); self.assertFalse(self.immune(h, body))
        self.play(h, GIVE, shell); self.assertTrue(self.immune(h, body))

    def test_dormant_physical_shell_counts_but_transformed_identity_does_not(self):
        g = self.game(hand=(DORMANT,)); body = self.reward(g)
        self.play(g, DORMANT, self.entity(g, SHELL, zone='board').id); self.assertTrue(self.immune(g, body))
        h = self.game(hand=(AWAY,)); body = self.reward(h)
        self.play(h, AWAY, self.entity(h, SHELL, zone='board').id); self.assertFalse(self.immune(h, body))

    def test_current_and_silenced_current_copies_keep_their_own_native_presence(self):
        g = self.game(hand=(COPY,)); body = self.reward(g); self.play(g, COPY, body)
        bodies = [i for i in g.state.players[1].board if g.state.entities[i].card_id == COLAQUE]
        self.assertEqual(len(bodies), 2); self.assertTrue(all(self.immune(g, i) for i in bodies))
        h = self.game(hand=(QUIET, COPY)); body = self.reward(h); self.play(h, QUIET, body); self.play(h, COPY, body)
        bodies = [i for i in h.state.players[1].board if h.state.entities[i].card_id == COLAQUE]
        self.assertEqual(len(bodies), 2); self.assertFalse(any(self.immune(h, i) for i in bodies))

    def test_gaia_actual_drill_attack_deals_one_to_each_enemy_and_not_friends(self):
        g = self.game(GAIA, enemy=(UNIT, UNIT)); body = self.reward(g, GAIA)
        target, other = g.state.players[2].board
        g.apply(Attack(1, self.entity(g, DRILLS[0], zone='board').id, target))
        self.assertEqual((g.state.entities[target].health, g.state.entities[other].health), (17, 19))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 29)
        self.assertEqual(g.state.entities[body].health, 7)

    def test_gaia_dead_attacker_uses_original_frozen_changed_tribes_instead_of_printed_fallback(self):
        for original, change, expected_health in ((TINY, SET_MECH, 29), (MECH, SET_BEAST, 30)):
            g = self.game(GAIA, hand=(change,), own=(original,)); self.reward(g, GAIA)
            attacker = self.entity(g, original, zone='board').id; self.play(g, change, attacker)
            g.apply(Attack(1, attacker, g.state.players[2].board[0]))
            self.assertEqual(g.state.entities[attacker].zone, Zone.GRAVEYARD)
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, expected_health)

    def test_all_type_friendly_attacker_qualifies_without_finite_tribe_enumeration(self):
        g = self.game(GAIA, own=('GIL_681',)); self.reward(g, GAIA)
        g.apply(Attack(1, self.entity(g, 'GIL_681', zone='board').id, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,
            29-g.registry.card('GIL_681').attack)

    def test_non_mech_hero_attack_and_enemy_mech_do_not_trigger_own_gaia(self):
        g = self.game(GAIA, own=(UNIT,), hand=(EQUIP,)); self.reward(g, GAIA)
        g.apply(Attack(1, self.entity(g, UNIT, zone='board').id, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 29)
        self.play(g, EQUIP); g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        h = self.game(GAIA, own=(UNIT,), enemy=(MECH,)); self.reward(h, GAIA); h.apply(EndTurn(1))
        h.apply(Attack(2, h.state.players[2].board[0], self.entity(h, UNIT, zone='board').id))
        self.assertEqual(h.state.entities[h.state.players[1].hero_id].health, 30)

    def test_two_actual_gaia_sources_each_respond_once_and_silencing_one_removes_only_its_wave(self):
        g = self.game(GAIA, hand=(ADD_GAIA, QUIET)); body = self.reward(g, GAIA); self.play(g, ADD_GAIA)
        target = g.state.players[2].board[0]
        g.apply(Attack(1, self.entity(g, DRILLS[0], zone='board').id, target))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)
        self.play(g, QUIET, body)
        g.apply(Attack(1, self.entity(g, DRILLS[1], zone='board').id, target))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)

    def test_unknown_actual_attacker_types_fail_and_roll_back_whole_combat(self):
        g = self.game(GAIA, own=(UNKNOWN,)); self.reward(g, GAIA); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unknown completed minion attack types'):
            g.apply(Attack(1, self.entity(g, UNKNOWN, zone='board').id, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), before)

    def test_shell_death_notification_wait_restores_with_immunity_already_removed(self):
        g = self.game(hand=(KILL,), mode='colaque-wait'); body = self.reward(g)
        self.play(g, KILL, self.entity(g, SHELL, zone='board').id)
        self.assertFalse(self.immune(g, body)); restored = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g, 'ok'); self.choose(restored, 'ok'); self.assertEqual(g.snapshot(), restored.snapshot())

    def test_real_gaia_damage_notification_wait_restores_clone_replay_and_atomic_bad_branch(self):
        g = self.game(GAIA, mode='gaia-wait'); self.reward(g, GAIA)
        g.apply(Attack(1, self.entity(g, DRILLS[0], zone='board').id, g.state.players[2].board[0]))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 29)
        restored = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g, 'ok'); self.choose(restored, 'ok'); self.assertEqual(g.snapshot(), restored.snapshot())

    def test_named_presence_shape_and_rehashed_native_selector_are_closed(self):
        for changes in ({'card_ids': ()}, {'card_ids': (SHELL, UNIT)}, {'keyword': Keyword.RUSH}, {'target': 'friendly_minions'}):
            with self.assertRaises(ValueError): KeywordAuraSpec(**dict(dict(keyword=Keyword.IMMUNE, target='self',
                condition='controller_controls_named_minion', card_ids=(SHELL,)), **changes))
        g = self.game(); eid = self.reward(g); saved = g.snapshot()
        ability = next(a for a in saved['state']['entities'][str(eid)]['abilities'] if a['kind'] == 'keyword_aura')
        ability['keyword_aura']['card_ids'] = [UNIT]
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture('colaque', 'independent-reader'))

    def test_late_old_drill_failure_registers_neither_new_body_nor_behavior(self):
        r = build_registry()
        for cid in (COLAQUE, GAIA): del r._cards[cid]; del r._pool_cards[cid]
        del r._behaviors[BODY]; r._cards[DRILLS[1]] = replace(r.card(DRILLS[1]), attack=3)
        before = (dict(r.cards), dict(r.pool_cards), dict(r._behaviors))
        with self.assertRaises(TargetValidationError): register_past_colaque_gaia(r)
        self.assertEqual((dict(r.cards), dict(r.pool_cards), dict(r._behaviors)), before)


if __name__ == '__main__': unittest.main()
