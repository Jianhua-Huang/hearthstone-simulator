"""Real secret bodies, original attack/death identities and attributed entry."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.reactive_secret_cards import load_batch
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, Keyword, LaunchStarship, PlayCard, PlayerSetup, Scenario,
    SelectChoice, SummonCause, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, DestroyBatch, EquipWeapon, Freeze, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import SpellSchool, SummonQuantitySpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.starships import construction
from hs_sim.engine.summon_quantities import SummonByCard, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest


def registry(mode=None):
    r = build_registry()
    meta = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    r.register_card(CardDefinition('k13c.hero', 'Hero', CardType.HERO, health=100, metadata=meta))
    r.register_behavior('k13c.bc', lambda c: (GainArmor(c.player_id, 4),))
    r.register_behavior('k13c.dr', lambda c: (GainArmor(c.player_id, 2),))
    r.register_card(CardDefinition('k13c.body', 'Printed body', CardType.MINION, cost=3,
        attack=4, health=5, keywords=(Keyword.CHARGE, Keyword.TAUNT),
        battlecry='k13c.bc', deathrattle='k13c.dr', metadata=meta))
    for cid, kwargs in (
        ('plain', dict(attack=3, health=6)),
        ('immune', dict(attack=3, health=6, keywords=(Keyword.CHARGE, Keyword.IMMUNE, Keyword.ELUSIVE))),
        ('quantity', dict(health=10, summon_quantities=(SummonQuantitySpec(),))),
        ('piece', dict(attack=3, health=4, keywords=(Keyword.STARSHIP_PIECE, Keyword.TAUNT))),
    ):
        r.register_card(CardDefinition('k13c.'+cid, cid, CardType.MINION, metadata=meta, **kwargs))
    r.register_card(CardDefinition('k13c.weapon', 'Weapon', CardType.WEAPON, attack=3, durability=2, metadata=meta))
    def reenter(c):
        eid = next(e for e in c.state.players[1].hand if c.state.entities[e].card_id == 'k13c.body')
        return (SummonStoredCard(CardReference.capture(c.state.entities[eid]), 1, cause=SummonCause.capture(c)),)
    r.register_behavior('k13c.reenter', reenter)
    scripts = {
        'noop': lambda c: (),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'clear': lambda c: (DestroyBatch(tuple(c.state.players[1].board), c.source_id),),
        'buff': lambda c: (Buff(c.target_id, 5, 7, c.source_id), Freeze(c.target_id)),
        'silence': lambda c: (Silence(c.target_id),),
        'transform_kill': lambda c: (Transform(c.target_id, 'CS2_tk1'), Destroy(c.target_id, c.source_id)),
        'return': lambda c: (ReturnToHand(c.target_id),),
        'return_reenter': lambda c: (ReturnToHand(c.target_id), InvokeBehavior('k13c.reenter', c.source_id, c.player_id)),
        'control_kill': lambda c: (ChangeControl(c.target_id, 2), ChangeControl(c.target_id, 1), Destroy(c.target_id, c.source_id)),
        'summon': lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial('k13c.plain'),), SummonCause.capture(c)),),
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id, cause=SummonCause.capture(c)),),
        'equip': lambda c: (EquipWeapon(c.player_id, 'k13c.weapon'),),
        'fail': lambda c: (AddToHand(c.player_id, 'missing.k13c'),),
    }
    targeted = {'kill', 'buff', 'silence', 'transform_kill', 'return', 'return_reenter', 'control_kill', 'copy'}
    for name, script in scripts.items():
        r.register_behavior('k13c.'+name, script)
        r.register_card(CardDefinition('k13c.'+name, name, CardType.SPELL,
            on_play='k13c.'+name, targeting=TargetSpec(kinds=(CardType.MINION,)) if name in targeted else None,
            metadata=meta))
    if mode:
        def watch(c):
            if mode == 'fill':
                return (SummonByCard(c.player_id, (SummonEntryMaterial('k13c.plain'),), SummonCause.capture(c)),)
            if mode == 'wait':
                return (RequestChoice(c.player_id, (
                    ChoiceOption('ok', 'Finish the original secret'),
                    ChoiceOption('bad', 'Rollback', (InvokeBehavior('k13c.fail', c.source_id, c.player_id),)),
                ), c.source_id),)
            attacker = c.state.action_windows[-1].source_id
            return ((ReturnToHand(attacker),) if mode == 'return' else (Transform(attacker, 'k13c.plain'),))
        r.register_behavior('k13c.watch', watch)
        r.register_card(CardDefinition('k13c.watch', 'Observer', CardType.MINION, health=20,
            triggers=(TriggerSpec('minion_died' if mode == 'fill' else 'secret_revealed', 'k13c.watch'),), metadata=meta))
    return r


class ReactiveSecretCardTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode=None):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('k13c.hero', hand=hand, board=board, deck=('k13c.noop',)*8,
                        mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('k13c.hero', hand=enemy_hand, board=enemy, deck=('k13c.noop',)*8,
                        mana=40, max_mana=40, mana_cap=40)), seed=227), registry(mode))
    def play(self, g, cid, player=1, target=None):
        eid = next(e for e in g.state.players[player].hand if g.state.entities[e].card_id == cid)
        g.apply(PlayCard(player, eid, target)); return eid
    def board(self, g, player=1): return [g.state.entities[e] for e in g.state.players[player].board]
    def hero(self, g, player=1): return g.state.entities[g.state.players[player].hero_id]
    def portable(self, g):
        saved = g.snapshot()
        other = Game.from_snapshot(saved, registry(self.mode))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.mode)).snapshot(), saved)
        return other
    def finish(self, g, option='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))
    def prepared(self, hand=(), board=(), mode=None):
        g = self.game(('TIME_620', 'k13c.body', *hand), board, enemy_hand=('k13c.kill',), mode=mode)
        target = self.play(g, 'k13c.body'); self.play(g, 'TIME_620'); return g, target

    def test_complete_pins_costs_schools_and_real_sheep_dependency(self):
        data = load_batch(); self.assertEqual(len(data['cards']), 3)
        r = registry()
        for row in data['cards']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        self.assertEqual((r.card('JAIL_315').cost, r.card('JAIL_315').spell_school), (3, SpellSchool.ARCANE))
        self.assertEqual((r.card('TIME_620').cost, r.card('TIME_620').spell_school), (2, None))
        self.assertEqual((r.card('CS2_tk1').attack, r.card('CS2_tk1').health, r.card('CS2_tk1').metadata.tribes), (1, 1, ('beast',)))

    def test_attack_transforms_same_resident_and_continues_with_sheep_damage(self):
        g = self.game(('JAIL_315',), enemy=('k13c.body',))
        self.play(g, 'JAIL_315'); self.assertEqual(g.state.players[1].mana, 37)
        g.apply(EndTurn(1)); old = self.board(g, 2)[0]
        g.apply(Attack(2, old.id, self.hero(g).id)); sheep = g.state.entities[old.id]
        self.assertEqual((sheep.card_id, sheep.attack, sheep.health, sheep.attacks_this_turn), ('CS2_tk1', 1, 1, 1))
        self.assertEqual(sheep.board_presence_id, old.board_presence_id)
        self.assertEqual(self.hero(g).health, 99); self.assertFalse(g.state.players[1].secrets); self.portable(g)

    def test_attacking_minion_target_uses_sheep_and_loses_original_deathrattle(self):
        g = self.game(('JAIL_315',), board=('k13c.plain',), enemy=('k13c.body',))
        self.play(g, 'JAIL_315'); g.apply(EndTurn(1)); old = self.board(g, 2)[0]
        g.apply(Attack(2, old.id, self.board(g)[0].id))
        self.assertEqual(self.board(g)[0].health, 5)
        self.assertEqual(g.state.entities[old.id].zone, Zone.GRAVEYARD)
        self.assertEqual(self.hero(g, 2).armor, 0); self.portable(g)

    def test_immune_elusive_attacker_is_transformed_without_explicit_targeting(self):
        g = self.game(('JAIL_315',), enemy=('k13c.immune',))
        self.play(g, 'JAIL_315'); g.apply(EndTurn(1)); target = self.board(g, 2)[0].id
        g.apply(Attack(2, target, self.hero(g).id))
        self.assertEqual(g.state.entities[target].card_id, 'CS2_tk1')
        self.assertNotIn(Keyword.IMMUNE, g.state.entities[target].keywords); self.portable(g)

    def test_enemy_hero_attack_does_not_reveal_minion_secret(self):
        g = self.game(('JAIL_315',), enemy_hand=('k13c.equip',))
        self.play(g, 'JAIL_315'); g.apply(EndTurn(1)); self.play(g, 'k13c.equip', 2)
        g.apply(Attack(2, self.hero(g, 2).id, self.hero(g).id))
        self.assertEqual(self.hero(g).health, 97); self.assertEqual(len(g.state.players[1].secrets), 1)

    def test_original_secret_order_checks_current_attack_after_return_or_transform(self):
        for first, second in (('CORE_EX1_611', 'JAIL_315'), ('JAIL_315', 'CORE_EX1_611')):
            with self.subTest(first=first):
                g = self.game((first, second), enemy=('k13c.body',))
                self.play(g, first); self.play(g, second); g.apply(EndTurn(1)); target = self.board(g, 2)[0].id
                g.apply(Attack(2, target, self.hero(g).id))
                self.assertEqual(self.hero(g).health, 100)
                self.assertEqual(g.state.entities[target].card_id, 'k13c.body' if first == 'CORE_EX1_611' else 'CS2_tk1')
                self.assertEqual(len(g.state.players[1].secrets), 1 if first == 'CORE_EX1_611' else 0)
                self.portable(g)

    def test_reveal_reactions_do_not_rebind_original_captured_attacker(self):
        for mode in ('return', 'transform'):
            g = self.game(('JAIL_315',), board=('k13c.watch',), enemy=('k13c.body',), mode=mode)
            self.play(g, 'JAIL_315'); g.apply(EndTurn(1)); target = self.board(g, 2)[0].id
            g.apply(Attack(2, target, self.hero(g).id))
            self.assertEqual(g.state.entities[target].card_id, 'k13c.body' if mode == 'return' else 'k13c.plain')
            self.assertEqual(self.hero(g).health, 100 if mode == 'return' else 97); self.portable(g)

    def test_attack_reveal_waiting_rollback_recovery_and_replay(self):
        g = self.game(('JAIL_315',), board=('k13c.watch',), enemy=('k13c.body',), mode='wait')
        self.play(g, 'JAIL_315'); g.apply(EndTurn(1)); target = self.board(g, 2)[0].id
        g.apply(Attack(2, target, self.hero(g).id)); self.assertIsNotNone(g.state.pending_choice)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.finish(g, 'bad')
        self.assertEqual(g.snapshot(), saved); other = self.portable(g)
        self.finish(g); self.finish(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.hero(g).health, 99); self.portable(g)

    def test_actual_previous_turn_play_resummons_clean_body_without_battlecry(self):
        g, target = self.prepared(('k13c.buff',)); self.play(g, 'k13c.buff', target=target)
        g.apply(EndTurn(1)); self.play(g, 'k13c.kill', 2, target)
        body = self.board(g)[0]
        self.assertNotEqual(body.id, target); self.assertEqual(body.origin_entity_id, target)
        self.assertEqual((body.card_id, body.attack, body.health, body.frozen), ('k13c.body', 4, 5, False))
        self.assertEqual(self.hero(g).armor, 6); self.assertEqual(len(g.state.play_history), 4)
        self.assertEqual(len(g.state.resurrection_history), 1); self.portable(g)

    def test_qualification_uses_minion_play_turn_not_secret_deployment_turn(self):
        g = self.game(('k13c.body', 'k13c.body', 'TIME_620'), enemy_hand=('k13c.kill', 'k13c.kill'))
        old = self.play(g, 'k13c.body'); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        new = self.play(g, 'k13c.body'); self.play(g, 'TIME_620'); g.apply(EndTurn(1))
        self.play(g, 'k13c.kill', 2, old); self.assertEqual(len(g.state.players[1].secrets), 1)
        self.play(g, 'k13c.kill', 2, new)
        self.assertEqual(g.state.resurrection_history[0].death_id, g.state.death_history[-1].id); self.portable(g)

    def test_summoned_child_and_scenario_board_do_not_borrow_played_status(self):
        for initial in (True, False):
            g = self.game(('TIME_620', 'k13c.summon'), board=('k13c.plain',) if initial else (), enemy_hand=('k13c.kill',))
            if not initial: self.play(g, 'k13c.summon')
            target = self.board(g)[0].id; self.play(g, 'TIME_620'); g.apply(EndTurn(1)); self.play(g, 'k13c.kill', 2, target)
            self.assertEqual(len(g.state.players[1].secrets), 1); self.assertFalse(g.state.resurrection_history)

    def test_later_same_physical_stored_entry_does_not_borrow_old_hand_play(self):
        g, target = self.prepared(('k13c.return_reenter',)); self.play(g, 'k13c.return_reenter', target=target)
        g.apply(EndTurn(1)); self.play(g, 'k13c.kill', 2, target)
        self.assertFalse(g.state.resurrection_history); self.assertEqual(len(g.state.players[1].secrets), 1); self.portable(g)

    def test_return_and_new_manual_play_use_latest_play_record(self):
        g = self.game(('TIME_620', 'k13c.body', 'k13c.return'), enemy_hand=('k13c.kill',))
        target = self.play(g, 'k13c.body'); self.play(g, 'k13c.return', target=target)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, 'k13c.body'); self.play(g, 'TIME_620')
        g.apply(EndTurn(1)); self.play(g, 'k13c.kill', 2, target)
        self.assertEqual(len(g.state.resurrection_history), 1); self.portable(g)

    def test_older_minion_and_own_turn_death_leave_secret(self):
        g, target = self.prepared(('k13c.kill',)); self.play(g, 'k13c.kill', target=target)
        self.assertEqual(len(g.state.players[1].secrets), 1); self.assertFalse(g.state.resurrection_history)
        g, target = self.prepared(); g.apply(EndTurn(1)); g.apply(EndTurn(2)); g.apply(EndTurn(1))
        self.play(g, 'k13c.kill', 2, target)
        self.assertEqual(len(g.state.players[1].secrets), 1); self.assertFalse(g.state.resurrection_history)

    def test_transformed_death_resummons_death_face_and_restores_printed_silenced_body(self):
        g = self.game(('TIME_620', 'k13c.body'), enemy_hand=('k13c.transform_kill',))
        target = self.play(g, 'k13c.body'); self.play(g, 'TIME_620'); g.apply(EndTurn(1))
        self.play(g, 'k13c.transform_kill', 2, target)
        self.assertEqual([e.card_id for e in self.board(g)], ['CS2_tk1']); self.portable(g)
        g, target = self.prepared(('k13c.silence',)); self.play(g, 'k13c.silence', target=target)
        g.apply(EndTurn(1)); self.play(g, 'k13c.kill', 2, target); body = self.board(g)[0]
        self.assertFalse(body.silenced); self.assertIn(Keyword.TAUNT, body.keywords); self.assertEqual(self.hero(g).armor, 4)

    def test_control_changes_keep_physical_play_qualification(self):
        g = self.game(('TIME_620', 'k13c.body'), enemy_hand=('k13c.control_kill',))
        target = self.play(g, 'k13c.body'); self.play(g, 'TIME_620'); g.apply(EndTurn(1))
        self.play(g, 'k13c.control_kill', 2, target)
        self.assertEqual(len(g.state.resurrection_history), 1); self.assertEqual(self.board(g)[0].controller, 1); self.portable(g)

    def test_full_board_after_earlier_death_reaction_does_not_consume_secret(self):
        g, target = self.prepared(board=('k13c.watch',)+('k13c.plain',)*5, mode='fill')
        g.apply(EndTurn(1)); self.play(g, 'k13c.kill', 2, target)
        self.assertEqual(len(self.board(g)), 7); self.assertEqual(len(g.state.players[1].secrets), 1)
        self.assertFalse(g.state.resurrection_history); self.portable(g)

    def test_simultaneous_deaths_consume_once_and_bind_original_death(self):
        g = self.game(('TIME_620', 'k13c.body', 'k13c.plain'), enemy_hand=('k13c.clear',))
        first = self.play(g, 'k13c.body'); self.play(g, 'k13c.plain'); self.play(g, 'TIME_620')
        g.apply(EndTurn(1)); self.play(g, 'k13c.clear', 2)
        self.assertEqual(len(g.state.resurrection_history), 1)
        self.assertEqual(g.state.entities[g.state.resurrection_history[0].entity_id].origin_entity_id, first); self.portable(g)

    def test_resummon_reveal_waiting_keeps_original_death_and_private_boundary(self):
        g, target = self.prepared(board=('k13c.watch',), mode='wait')
        g.apply(EndTurn(1)); self.play(g, 'k13c.kill', 2, target)
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(g.state.resurrection_history)
        for viewer in (1, 2):
            public = json.dumps(g.for_player(viewer).observe())+json.dumps(g.player_events(viewer))
            for field in ('death_id', 'zone_epoch', 'original_state_hash', 'secret_instance_id'):
                self.assertNotIn('"'+field+'"', public)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.finish(g, 'bad')
        self.assertEqual(g.snapshot(), saved); other = self.portable(g)
        self.finish(g); self.finish(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(g.state.resurrection_history), 1); self.portable(g)

    def test_current_colossal_death_reuses_appendage_entry_without_replaying_battlecry(self):
        g = self.game(('TIME_620', 'CATA_150'), enemy_hand=('k13c.clear',))
        self.play(g, 'CATA_150'); self.play(g, 'TIME_620'); g.apply(EndTurn(1)); self.play(g, 'k13c.clear', 2)
        self.assertEqual(sorted(e.card_id for e in self.board(g)), ['CATA_150', 'CATA_150t', 'CATA_150t1'])
        self.assertEqual(len(g.state.resurrection_history), 1); self.portable(g)

    def test_original_quantity_profile_duplicates_selected_resummoned_body(self):
        g, target = self.prepared(board=('k13c.quantity',)); g.apply(EndTurn(1)); self.play(g, 'k13c.kill', 2, target)
        self.assertEqual(len(g.state.resurrection_history), 2)
        self.assertEqual([e.card_id for e in self.board(g)].count('k13c.body'), 2)
        self.assertEqual(self.hero(g).armor, 6); self.portable(g)

    def test_composite_death_preserves_recorded_pieces_in_attributed_resurrection(self):
        g = self.game(('k13c.kill', 'k13c.return', 'TIME_620'), board=('k13c.piece',), enemy_hand=('k13c.kill',))
        self.play(g, 'k13c.kill', target=self.board(g)[0].id)
        ship = construction(g.state, 1); g.apply(LaunchStarship(1, ship.id))
        self.play(g, 'k13c.return', target=ship.id)
        self.play(g, g.state.entities[ship.id].card_id); self.play(g, 'TIME_620'); g.apply(EndTurn(1))
        self.play(g, 'k13c.kill', 2, ship.id); new = self.board(g)[0]
        self.assertEqual((new.components, new.attack, new.health), (('k13c.piece',), 3, 4))
        self.assertFalse(new.starship_building); self.assertEqual(len(g.state.starship_history), 1); self.portable(g)


if __name__ == '__main__': unittest.main()
