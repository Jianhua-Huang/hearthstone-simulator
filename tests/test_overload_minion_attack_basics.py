"""Native ordinary-minion Overload presence reuses the original accounts/layers."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, TargetSpec
from hs_sim.engine.effects import Buff, ChangeControl, CopyMinion, Destroy, ReturnToHand, Silence
from hs_sim.engine.model import StatRelationLayer, StatRelationOperand, StatRelationSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.stat_relations import GrantStatRelation
from opening_fixtures import metadata
from test_overload_weapon_attack_basics import CARD as WEAPON, registry as weapon_registry


CARD = 'diagnostic.overload-minion'
REBORN = CARD + '.reborn'
REL = StatRelationSpec(operand=StatRelationOperand.CONTROLLER_OVERLOADED_MANA,
    layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=1)


def registry():
    r = weapon_registry()
    for cid, keywords in ((CARD, ()), (REBORN, (Keyword.REBORN,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=1, health=3,
            stat_relations=(REL,), keywords=keywords, metadata=metadata(tribes=('elemental',))))
    for name, body in {
        'm-buff': lambda c: (Buff(c.target_id, attack=3, source_id=c.source_id),),
        'm-copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'm-take': lambda c: (ChangeControl(c.target_id, 2),),
        'm-silence': lambda c: (Silence(c.target_id),),
        'm-bounce': lambda c: (ReturnToHand(c.target_id),),
        'm-kill': lambda c: (Destroy(c.target_id, c.source_id),),
    }.items():
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, targeting=TargetSpec(), metadata=metadata(tribes=())))
    r.validate()
    return r


class OverloadMinionAttackTests(unittest.TestCase):
    def game(self, hand=(), *, board=(CARD,), owed=0, locked=0, enemy_owed=0, weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('plain',)*4, weapon_card_id=weapon,
                overload_owed=owed, overload_locked=locked, mana=10-locked, max_mana=10),
            PlayerSetup('hero', deck=('plain',)*4, overload_owed=enemy_owed, mana=10, max_mana=10)), seed=462), registry())

    def entity(self, g, player=1, cid=CARD):
        return next(g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id == cid)

    def cast(self, g, cid, target=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid, target)); return eid

    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(s, registry())
        self.assertEqual(other.snapshot(), s); self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), s)
        return other

    def test_only_one_native_ordinary_relation_and_no_granted_or_fusion_expansion(self):
        self.assertEqual(registry().card(CARD).stat_relations, (REL,))
        with self.assertRaises(ValueError): GrantStatRelation(1, REL, 1)
        for fields in ({'keywords': (Keyword.MAGNETIC,), 'magnetic_tribes': ('mech',)},
                       {'stat_relations': (REL, StatRelationSpec())},
                       {'stat_relations': (REL, REL)}):
            values = dict(stat_relations=(REL,)); values.update(fields)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                Registry('invalid-minion-relation').register_card(CardDefinition('bad', 'Bad', CardType.MINION,
                    health=3, metadata=metadata(tribes=('mech',)), **values))

    def test_owed_locked_or_both_add_one_presence_bonus_not_crystal_quantity(self):
        for owed, locked, expected in ((0, 0, 1), (1, 0, 2), (0, 2, 2), (3, 4, 2)):
            with self.subTest(owed=owed, locked=locked):
                g = self.game(owed=owed, locked=locked, enemy_owed=5)
                self.assertEqual((self.entity(g).attack, self.entity(g).conditional_attack), (expected, expected-1))

    def test_real_one_mana_hand_entry_and_waiting_payment_restore(self):
        g = self.game((CARD, 'wait'), board=(), owed=1)
        eid = self.cast(g, CARD); self.assertEqual((g.state.entities[eid].attack, g.state.players[1].mana), (2, 9))
        self.cast(g, 'wait'); self.assertIsNotNone(g.state.pending_choice); g = self.portable(g)
        q = g.state.pending_choice; before = g.snapshot()
        from hs_sim.engine import ResolutionError
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(1, q.id, ('fault',)))
        self.assertEqual(g.snapshot(), before)
        g.apply(SelectChoice(1, q.id, ('clear',)))
        self.assertEqual((g.state.entities[eid].attack, g.state.players[1].mana), (1, 9))

    def test_add_zero_and_clear_preserve_original_overload_history(self):
        g = self.game(('zero', 'add', 'more', 'clear')); rng = g._rng.getstate()
        self.cast(g, 'zero'); self.assertFalse(g.state.overload_history)
        self.cast(g, 'add'); self.assertEqual(self.entity(g).attack, 2)
        self.cast(g, 'more'); self.assertEqual((self.entity(g).attack, g.state.players[1].overload_owed), (2, 3))
        self.cast(g, 'clear'); self.assertEqual(self.entity(g).attack, 1)
        self.assertEqual(g._rng.getstate(), rng)

    def test_real_turn_moves_owed_to_locked_then_releases_without_accumulation(self):
        g = self.game(owed=1); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual((g.state.players[1].overload_owed, g.state.players[1].overload_locked, self.entity(g).attack), (0, 1, 2))
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(self.entity(g).attack, 1)
        self.portable(g)

    def test_control_transfer_uses_receiver_account_and_refreshes_public_attack(self):
        g = self.game(('m-take',), owed=1); eid = self.entity(g).id
        self.cast(g, 'm-take', eid)
        self.assertEqual((g.state.entities[eid].controller, g.state.entities[eid].attack), (2, 1))
        self.portable(g)

    def test_ordinary_buff_and_current_copy_do_not_bake_or_duplicate_conditional_bonus(self):
        g = self.game(('m-buff', 'm-copy'), owed=1); eid = self.entity(g).id
        self.cast(g, 'm-buff', eid); self.cast(g, 'm-copy', eid)
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board], [5, 5])
        for i in g.state.players[1].board:
            self.assertEqual(sum(a.kind == 'stat_relation' for a in g.state.entities[i].abilities), 1)
        self.portable(g)

    def test_silence_removes_native_relation_and_does_not_restore_it_on_account_change(self):
        g = self.game(('m-silence', 'clear', 'add'), owed=1); eid = self.entity(g).id
        self.cast(g, 'm-silence', eid); self.cast(g, 'clear'); self.cast(g, 'add')
        self.assertEqual(g.state.entities[eid].attack, 1)
        self.assertFalse(any(a.kind == 'stat_relation' for a in g.state.entities[eid].abilities))

    def test_bounce_then_native_reentry_installs_exactly_one_relation(self):
        g = self.game(('m-bounce',), owed=1); eid = self.entity(g).id
        self.cast(g, 'm-bounce', eid); self.cast(g, CARD)
        self.assertEqual(g.state.entities[eid].attack, 2)
        self.assertEqual(sum(a.kind == 'stat_relation' for a in g.state.entities[eid].abilities), 1)
        self.portable(g)

    def test_reborn_new_body_keeps_native_relation_with_one_health(self):
        g = self.game(('m-kill',), board=(REBORN,), owed=1); eid = self.entity(g, cid=REBORN).id
        self.cast(g, 'm-kill', eid); child = self.entity(g, cid=REBORN)
        self.assertNotEqual(child.id, eid); self.assertEqual((child.attack, child.health), (2, 1))
        self.assertNotIn(Keyword.REBORN, child.keywords); self.portable(g)

    def test_minion_and_original_likkim_share_account_without_sharing_bonus_amount(self):
        g = self.game(('clear',), owed=1, weapon=WEAPON)
        w = g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((self.entity(g).attack, w.attack), (2, 3))
        self.cast(g, 'clear')
        current_weapon = g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((self.entity(g).attack, current_weapon.attack), (1, 1))

    def test_late_account_failure_rolls_back_conditional_attack_and_original_payment(self):
        from hs_sim.engine import ResolutionError
        g = self.game(('fault',), owed=1); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'fault')
        self.assertEqual(g.snapshot(), before)

    def test_native_ability_cannot_be_reclassified_as_a_grant(self):
        g = self.game(owed=1); ability = next(a for a in self.entity(g).abilities if a.kind == 'stat_relation')
        with self.assertRaises(ValueError): replace(ability, origin='granted')


if __name__ == '__main__':
    unittest.main()
