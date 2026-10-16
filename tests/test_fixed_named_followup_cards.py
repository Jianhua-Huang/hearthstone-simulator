"""Real named dependencies across ordinary death, damage, hand and recovery."""
from dataclasses import asdict, replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.fixed_named_followup_cards import BLOODPETAL, SEEDLING, THUNDERQUAKE, STATIC_SHOCK, load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
                           Ruleset, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, SpellSchool
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import canonical_digest

YETI = 'CORE_CS2_182'
KHADGAR = 'CORE_DAL_575'
TARGET = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))


def registry():
    r = build_registry()
    scripts = dict(kill=lambda c: (Destroy(c.target_id, c.source_id),),
        buff=lambda c: (Buff(c.target_id, 3, 4, c.source_id),),
        silence=lambda c: (Silence(c.target_id),), bounce=lambda c: (ReturnToHand(c.target_id),),
        morph=lambda c: (Transform(c.target_id, YETI),), steal=lambda c: (ChangeControl(c.target_id, c.player_id),),
        copy=lambda c: (CopyMinion(c.target_id, c.player_id, cause=SummonCause.capture(c)),),
        trigger=lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        cast=lambda c: (CastSpell(c.player_id, THUNDERQUAKE, c.source_id),),
        bad=lambda c: (CastSpell(c.player_id, THUNDERQUAKE, c.source_id), AddToHand(c.player_id, 'unknown.k83')))
    for name, body in scripts.items():
        key = 'k83.' + name; r.register_behavior(key, body)
        r.register_card(CardDefinition(key, name, CardType.SPELL, on_play=key,
                                      targeting=None if name in ('cast', 'bad') else TARGET))
    r.register_behavior('k83.fail', lambda c: (AddToHand(c.player_id, 'unknown.k83'),))
    def wait(c):
        e = c.event
        if e.kind == 'minion_summoned':
            if c.state.entities[e.target_id].card_id != SEEDLING: return ()
        else:
            if c.state.entities[e.target_id].card_id != YETI: return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('fail', 'Fail', (InvokeBehavior('k83.fail', c.source_id, c.player_id),)),
        ), source_id=c.source_id),)
    r.register_behavior('k83.wait', wait)
    for name, event in (('summonwatch', 'minion_summoned'), ('damagewatch', 'damage_dealt')):
        r.register_card(CardDefinition('k83.' + name, name, CardType.MINION, health=8,
                                      triggers=(TriggerSpec(event, 'k83.wait'),)))
    r.register_behavior('k83.refill', lambda c: (AddToHand(c.player_id, YETI),)
                        if c.state.entities[c.event.target_id].card_id == YETI else ())
    r.register_card(CardDefinition('k83.refillwatch', 'refill', CardType.MINION, health=8,
                                  triggers=(TriggerSpec('damage_dealt', 'k83.refill'),)))
    return r


class FixedNamedFollowupCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r = registry()

    def game(self, hand=(), board=(), enemy=(), *, enemy_hand=(), cap=None, rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(YETI,)*8, mana=40, max_mana=40,
                        mana_cap=40, hand_cap=cap, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*8, mana=40,
                        max_mana=40, mana_cap=40, hero_power_card_id='HERO_08bp'),
        ), seed=483), self.r, ruleset=rules)

    def play(self, g, cid, target=None):
        p = g.state.active_player
        eid = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, eid, target, len(g.state.players[p].board) if self.r.card(cid).kind == CardType.MINION else None))
        return eid

    def board(self, g, p=1): return [g.state.entities[i].card_id for i in g.state.players[p].board]
    def hand(self, g, p=1): return [g.state.entities[i].card_id for i in g.state.players[p].hand]
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(s, registry())
        self.assertEqual(other.snapshot(), s); self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), s)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).legal_actions()) + json.dumps(g.player_events(p))
            for key in ('rng_state', 'resolution_frame', 'card_summon_history', 'hand_entry_history', 'SummonEntryMaterial'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_complete_faces_pins_and_existing_dependency_are_exact(self):
        data = load_batch()
        self.assertEqual((len(data['cards']), len(data['dependencies']), len(data['existing_dependencies']), len(data['evidence_only'])), (2, 1, 1, 3))
        for row in data['cards'] + data['dependencies'] + data['existing_dependencies'] + data['evidence_only']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        row, = data['existing_dependencies']
        self.assertEqual(canonical_digest(asdict(self.r.card(STATIC_SHOCK))), row['definition_sha256'])
        for row in data['cards'] + data['dependencies']:
            raw = row['record']; card = self.r.card(raw['id'])
            self.assertEqual(card.metadata, replace(metadata_from_record(raw), deck_identity=card.id))
        self.assertEqual((self.r.card(SEEDLING).cost, self.r.card(SEEDLING).attack, self.r.card(SEEDLING).health), (4, 0, 1))
        self.assertFalse(self.r.card(SEEDLING).metadata.collectible)
        self.assertEqual(self.r.card(THUNDERQUAKE).spell_school, SpellSchool.NATURE)

    def test_unknown_void_soul_sources_are_explicitly_unsupported(self):
        for cid in ('JAIL_730', 'JAIL_733', 'JAIL_732'):
            with self.assertRaises(UnsupportedDefinitionError): self.r.card(cid)

    def test_bloodpetal_paid_play_has_no_battlecry_summon(self):
        g = self.game((BLOODPETAL,)); eid = self.play(g, BLOODPETAL)
        self.assertEqual(self.board(g), [BLOODPETAL]); self.assertEqual(g.state.players[1].mana, 36)
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].health), (5, 1))
        self.assertFalse(g.state.card_summon_history)

    def test_both_deaths_create_fresh_base_entities_without_inherited_buffs(self):
        g = self.game((BLOODPETAL, 'k83.buff', 'k83.kill', 'k83.kill'))
        old = self.play(g, BLOODPETAL); self.play(g, 'k83.buff', old); self.play(g, 'k83.kill', old)
        seed, = g.state.players[1].board
        self.assertEqual((g.state.entities[seed].card_id, g.state.entities[seed].attack, g.state.entities[seed].health), (SEEDLING, 0, 1))
        self.play(g, 'k83.kill', seed); fresh, = g.state.players[1].board
        self.assertEqual((g.state.entities[fresh].card_id, g.state.entities[fresh].attack, g.state.entities[fresh].health), (BLOODPETAL, 5, 1))
        self.assertEqual(len({old, seed, fresh}), 3)
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD); self.portable(g)

    def test_silence_removes_either_native_deathrattle(self):
        for cid in (BLOODPETAL, SEEDLING):
            g = self.game(('k83.silence', 'k83.kill'), (cid,)); eid = g.state.players[1].board[0]
            self.play(g, 'k83.silence', eid); self.play(g, 'k83.kill', eid)
            self.assertEqual(self.board(g), []); self.assertFalse(g.state.card_summon_history)

    def test_bounce_and_transformation_are_not_death(self):
        for spell in ('k83.bounce', 'k83.morph'):
            g = self.game((spell,), (BLOODPETAL,)); self.play(g, spell, g.state.players[1].board[0])
            self.assertNotIn(SEEDLING, self.board(g)); self.assertFalse(g.state.death_history)

    def test_stolen_bloodpetal_delivers_to_current_death_controller(self):
        g = self.game(('k83.steal', 'k83.kill'), enemy=(BLOODPETAL,)); eid = g.state.players[2].board[0]
        self.play(g, 'k83.steal', eid); self.play(g, 'k83.kill', eid)
        self.assertEqual(self.board(g), [SEEDLING]); self.assertEqual(self.board(g, 2), [])
        self.portable(g)

    def test_current_copy_keeps_rattle_but_has_its_own_physical_source(self):
        g = self.game(('k83.copy', 'k83.kill'), (BLOODPETAL,)); old = g.state.players[1].board[0]
        self.play(g, 'k83.copy', old); copied = next(i for i in g.state.players[1].board if i != old)
        self.play(g, 'k83.kill', copied)
        self.assertEqual(self.board(g), [BLOODPETAL, SEEDLING])
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id, copied)

    def test_live_deathrattle_activation_does_not_remove_the_parent(self):
        g = self.game(('k83.trigger',), (BLOODPETAL,)); eid = g.state.players[1].board[0]
        self.play(g, 'k83.trigger', eid); self.assertEqual(self.board(g), [BLOODPETAL, SEEDLING])
        self.assertFalse(g.state.death_history)

    def test_full_board_and_quantity_provider_use_real_remaining_capacity(self):
        g = self.game(('k83.kill',), (BLOODPETAL, KHADGAR) + (YETI,)*5)
        self.play(g, 'k83.kill', g.state.players[1].board[0])
        self.assertEqual(len(self.board(g)), 7); self.assertEqual(self.board(g).count(SEEDLING), 1)
        self.portable(g)

    def test_no_slot_live_activation_creates_no_entity_and_uses_no_rng(self):
        g = self.game(('k83.trigger',), (BLOODPETAL,) + (YETI,)*6)
        saved = g.snapshot()['rng_state']; before = len(g.state.entities)
        self.play(g, 'k83.trigger', g.state.players[1].board[0])
        self.assertEqual(len(g.state.entities), before); self.assertNotIn(SEEDLING, self.board(g))
        self.assertEqual(g.snapshot()['rng_state'], saved)

    def test_seedling_summon_wait_restores_original_death_and_failed_choice(self):
        g = self.game(('k83.kill',), (BLOODPETAL, 'k83.summonwatch'))
        self.play(g, 'k83.kill', g.state.players[1].board[0]); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_thunderquake_empty_board_still_gets_static_shock_without_rng(self):
        g = self.game((THUNDERQUAKE,)); before = g.snapshot()['rng_state']
        eid = self.play(g, THUNDERQUAKE)
        self.assertEqual(self.hand(g), [STATIC_SHOCK]); self.assertEqual(g.state.players[1].mana, 38)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD); self.assertFalse(g.state.damage_history)
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_damage_hits_both_sides_and_never_heroes(self):
        g = self.game((THUNDERQUAKE,), (YETI,), (YETI,))
        self.play(g, THUNDERQUAKE)
        self.assertEqual([g.state.entities[g.state.players[p].board[0]].health for p in (1, 2)], [4, 4])
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in (1, 2)], [30, 30])
        self.assertEqual(len(g.state.damage_history), 2)

    def test_spell_bonus_is_applied_to_each_original_packet(self):
        g = self.game((THUNDERQUAKE,), ('CORE_EX1_012',), (YETI,))
        enemy = g.state.players[2].board[0]; self.play(g, THUNDERQUAKE)
        self.assertEqual(g.state.entities[enemy].health, 3)
        self.assertEqual([x.health_result.spell_bonus for x in g.state.damage_history], [1, 1])

    def test_dormant_and_shield_follow_ordinary_damage_protection(self):
        g = self.game((THUNDERQUAKE,), enemy=('CORE_BT_156', 'CORE_EX1_008'))
        dormant, shield = g.state.players[2].board; health = g.state.entities[dormant].health
        self.play(g, THUNDERQUAKE)
        self.assertEqual(g.state.entities[dormant].health, health)
        self.assertEqual(g.state.entities[shield].health, 1)
        self.assertEqual(len(g.state.damage_history), 1)

    def test_damage_batch_does_not_retarget_new_seedling(self):
        g = self.game((THUNDERQUAKE,), (BLOODPETAL,), (YETI,))
        old = g.state.players[1].board[0]; self.play(g, THUNDERQUAKE)
        seed, = g.state.players[1].board
        self.assertNotEqual(seed, old); self.assertEqual(self.board(g), [SEEDLING])
        self.assertEqual(g.state.entities[seed].health, 1)
        self.assertFalse(any(x.health_result.target_id == seed for x in g.state.damage_history))
        self.portable(g)

    def test_simultaneous_deaths_finish_once_before_named_hand_delivery(self):
        g = self.game((THUNDERQUAKE,), (BLOODPETAL, SEEDLING)); self.play(g, THUNDERQUAKE)
        self.assertCountEqual(self.board(g), [BLOODPETAL, SEEDLING])
        deaths = [e.sequence for e in g.events if e.kind == 'minion_died']
        added = [e.sequence for e in g.events if e.kind == 'card_added_to_hand']
        self.assertEqual(len(deaths), 2); self.assertLess(max(deaths), min(added))
        self.assertEqual(len(g.state.damage_history), 2)

    def test_hand_overflow_uses_burn_and_preserves_original_cards(self):
        g = self.game((THUNDERQUAKE, YETI), ('k83.refillwatch',), (YETI,), cap=2)
        self.play(g, THUNDERQUAKE); self.assertEqual(self.hand(g), [YETI, YETI])
        self.assertTrue(any(e.card_id == STATIC_SHOCK and e.zone == Zone.GRAVEYARD for e in g.state.entities.values()))
        self.assertFalse(g.state.draw_history); self.portable(g)

    def test_damage_wait_keeps_hand_tail_and_choice_rollback_private(self):
        g = self.game((THUNDERQUAKE,), ('k83.damagewatch',), (YETI,))
        self.play(g, THUNDERQUAKE); self.assertIsNotNone(g.state.pending_choice)
        self.assertNotIn(STATIC_SHOCK, self.hand(g)); saved = g.snapshot(); other = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(self.hand(g), [STATIC_SHOCK])

    def test_auto_cast_then_late_failure_rolls_back_damage_death_and_generation(self):
        g = self.game(('k83.bad',), (BLOODPETAL,), (YETI,)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'k83.bad')
        self.assertEqual(g.snapshot(), saved)

    def test_automatic_cast_uses_same_body_without_extra_hand_payment(self):
        g = self.game(('k83.cast',), (YETI,)); self.play(g, 'k83.cast')
        self.assertEqual(g.state.players[1].mana, 40); self.assertEqual(self.hand(g), [STATIC_SHOCK])
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health, 4)
        self.portable(g)

    def test_countered_thunderquake_has_no_damage_or_named_reward(self):
        g = self.game((THUNDERQUAKE,), (YETI,), enemy_hand=('CORE_EX1_287',))
        g.apply(EndTurn(1)); self.play(g, 'CORE_EX1_287'); g.apply(EndTurn(2))
        mana = g.state.players[1].mana; self.play(g, THUNDERQUAKE)
        self.assertEqual(g.state.players[1].mana, mana-2); self.assertNotIn(STATIC_SHOCK, self.hand(g))
        self.assertFalse(g.state.damage_history)

    def test_generated_static_shock_keeps_real_target_damage_attack_and_expiry(self):
        g = self.game((THUNDERQUAKE,), enemy=(YETI,)); self.play(g, THUNDERQUAKE)
        target = g.state.players[2].board[0]; self.play(g, STATIC_SHOCK, target)
        self.assertEqual(g.state.entities[target].health, 3)
        hero = g.state.players[1].hero_id; self.assertEqual(g.state.entities[hero].attack, 1)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[hero].attack, 0); self.portable(g)


if __name__ == '__main__': unittest.main()
