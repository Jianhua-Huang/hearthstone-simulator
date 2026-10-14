"""Actual source-qualified self-damage upgrades use frozen HealthResult facts."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, EndTurn, Game,
    HandProgressSpec, HealthFlow, Keyword, PaymentType, PlayCard, PlayerSetup, Rarity,
    ResolutionError, Scenario, SelectChoice, SpellSchool, TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeControl, ChoiceOption, Damage,
    DamageBatch, Draw, GainArmor, GrantKeyword, Heal, ModifyCost, RandomDamage, RequestChoice)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry


FORMS = ('LOOT_043', 'LOOT_043t2', 'LOOT_043t3')
IMP, HELLFIRE, TAP, LIBRARIAN = 'EX1_319', 'CS2_062', 'CS2_056_H3', 'LOOT_014'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/amethyst-qualification.json'
PIN = '32d8bc19bdd2e4a1c99b1074b68af8d007ecfa2eebf184ac2c20eaa5ebd682a6'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN: raise ValueError('Complete Amethyst evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original Amethyst source row changed')
    return {row['id']: row['data'] for row in raw['records']}


def registry(scripts=(), *, wait=False, bad_condition=False, transfer_source=False):
    r = opening_registry(); rows = evidence()
    def eligible(c):
        value = c.health_result
        return (value is not None and value.flow == HealthFlow.DAMAGE.value and value.damage_dealt > 0
            and value.target_kind == CardType.HERO.value and value.target_controller == c.player_id
            and value.source_controller == c.player_id and value.source_card_id is not None
            and value.damage_kind not in (DamageKind.HERO_POWER.value, DamageKind.FATIGUE.value)
            and r.card(value.source_card_id).hand_playable)
    r.register_trigger_condition('amethyst.eligible', (lambda c: 'invalid') if bad_condition else eligible)
    for stage in (2, 1, 0):
        cid = FORMS[stage]; row = rows[cid]
        r.register_behavior('amethyst.' + cid, lambda c, n=3+2*stage:
            (Damage(c.target_id, n, c.source_id, DamageKind.SPELL),))
        spec = None if stage == 2 else HandProgressSpec('event', 1, FORMS[stage + 1],
            event='health_resolved', condition_id='amethyst.eligible', upgrade_cost_policy='clear_local')
        r.register_card(CardDefinition(cid, row['name'], CardType.SPELL, cost=row['cost'],
            on_play='amethyst.' + cid, hand_progress=spec, keywords=(Keyword.LIFESTEAL,),
            spell_school=SpellSchool.SHADOW,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)),
            metadata=metadata(CardClass.WARLOCK, rarity=Rarity.RARE, collectible=stage == 0)))
    r.register_behavior('imp', lambda c: (Damage(c.state.players[c.player_id].hero_id, 3,
        c.source_id, DamageKind.MINION_ABILITY),))
    r.register_behavior('librarian', lambda c: (Draw(c.player_id, source_id=c.source_id),
        Damage(c.state.players[c.player_id].hero_id, 2, c.source_id, DamageKind.MINION_ABILITY)))
    for cid, behavior, tribes in ((IMP, 'imp', ('demon',)), (LIBRARIAN, 'librarian', ())):
        row = rows[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'], battlecry=behavior,
            metadata=metadata(CardClass.WARLOCK, tribes=tribes)))
    r.register_behavior('hellfire', lambda c: (DamageBatch(tuple(Damage(i, 3, c.source_id, DamageKind.SPELL)
        for p in (1, 2) for i in (c.state.players[p].hero_id, *c.state.players[p].board))),))
    r.register_card(CardDefinition(HELLFIRE, rows[HELLFIRE]['name'], CardType.SPELL, cost=rows[HELLFIRE]['cost'],
        on_play='hellfire', spell_school=SpellSchool.FIRE,
        metadata=metadata(CardClass.WARLOCK, rarity=Rarity.FREE)))
    r.register_behavior('tap', lambda c: (Draw(c.player_id, source_id=c.source_id),
        Damage(c.state.players[c.player_id].hero_id, 2, c.source_id, DamageKind.HERO_POWER)))
    r.register_card(CardDefinition(TAP, rows[TAP]['name'], CardType.HERO_POWER, cost=rows[TAP]['cost'],
        on_use='tap', metadata=metadata(CardClass.WARLOCK, rarity=Rarity.FREE, collectible=False)))
    r.register_card(CardDefinition('probe.unit', 'Source and target probe', CardType.MINION,
        attack=1, health=12, metadata=metadata()))
    if transfer_source:
        r.register_behavior('transfer', lambda c: (ChangeControl(c.event.source_id, 2),)
            if c.health_result.source_card_id == 'probe.unit' else ())
        r.register_card(CardDefinition('probe.transfer', 'Packet source transfer probe', CardType.MINION,
            health=12, triggers=(TriggerSpec('health_resolved', 'transfer'),), metadata=metadata()))
    if wait:
        r.register_behavior('wait', lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue', ()),), c.source_id),))
        r.register_behavior('noop', lambda c: ())
        r.register_card(CardDefinition('probe.progress', 'Waiting self-damage progress probe', CardType.SPELL,
            on_play='noop', hand_progress=HandProgressSpec('event', 1, on_complete='wait',
                event='health_resolved', condition_id='amethyst.eligible'), metadata=metadata()))
    for name, callback, cost in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=cost, on_play=name, metadata=metadata()))
    return r


class AmethystQualificationTests(unittest.TestCase):
    def setUp(self): self.scripts = []; self.options = {}
    def script(self, name, callback, cost=0): self.scripts.append((name, callback, cost))
    def hit(self, name, amount, player=1):
        self.script(name, lambda c: (Damage(c.state.players[player].hero_id, amount, c.source_id, DamageKind.SPELL),))
    def game(self, hand=(), *, board=(), enemy_board=('probe.unit',), enemy_hand=(), armor=0,
        deck=('card.1',)*12, power=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=deck, mana=10, max_mana=10,
                armor=armor, hero_power_card_id=power),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',)*12,
                mana=10, max_mana=10)), seed=74), registry(self.scripts, **self.options))
    def entity(self, g, cid, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if g.state.entities[i].card_id == cid)
    def progress(self, g, cid, player=1): return progress_ability(self.entity(g, cid, player))
    def play(self, g, cid, target=None):
        source = self.entity(g, cid, g.state.active_player).id
        g.apply(PlayCard(g.state.active_player, source, target)); return source
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored

    def test_full_raw_and_instance_threshold_not_damage_three(self):
        rows = evidence(); r = registry(); self.assertEqual(len(rows), 7)
        for cid in FORMS[:2]:
            self.assertEqual((r.card(cid).hand_progress.goal, r.card(cid).hand_progress.amount_basis), (1, 'one'))
            self.assertIn('Take damage from your cards', rows[cid]['text_en'])
        self.assertEqual(r.card(HELLFIRE).cost, 3)

    def test_one_actual_damage_and_large_damage_each_upgrade_once(self):
        for n in (1, 7):
            with self.subTest(amount=n):
                self.scripts = []; self.hit('hit', n)
                g = self.game(('hit', FORMS[0])); self.play(g, 'hit')
                self.assertEqual(self.progress(g, FORMS[1]).progress_units, (1,))
                self.assertEqual(self.progress(g, FORMS[1]).progress_completions, 1)

    def test_two_packets_in_one_batch_can_complete_both_stages(self):
        self.script('two', lambda c: (DamageBatch((Damage(c.state.players[1].hero_id, 1, c.source_id),
            Damage(c.state.players[1].hero_id, 7, c.source_id))),))
        g = self.game(('two', FORMS[0])); self.play(g, 'two')
        self.assertEqual(self.progress(g, FORMS[2]).progress_units, (1, 1))
        rows = [health_result(e) for e in g.events if e.kind == 'health_resolved']
        self.assertEqual(len({v.batch_id for v in rows}), 1); self.portable(g)

    def test_real_flame_imp_counts_its_battlecry_source(self):
        g = self.game((IMP, FORMS[0])); self.play(g, IMP)
        self.assertEqual(self.progress(g, FORMS[1]).progress_completions, 1)
        value = next(health_result(e) for e in g.events if e.kind == 'health_resolved')
        self.assertEqual((value.source_card_id, value.source_controller, value.damage_dealt), (IMP, 1, 3))
        self.portable(g)

    def test_real_hellfire_counts_own_hero_once_not_all_targets(self):
        g = self.game((HELLFIRE, FORMS[0]), board=('probe.unit',), enemy_hand=(FORMS[0],))
        self.play(g, HELLFIRE)
        self.assertEqual(self.progress(g, FORMS[1]).progress_units, (1,))
        self.assertEqual(self.progress(g, FORMS[0], 2).progress_value, 0)
        self.assertEqual(sum(e.kind == 'health_resolved' for e in g.events), 4); self.portable(g)

    def test_real_librarian_draws_then_new_spellstone_upgrades(self):
        g = self.game((LIBRARIAN,), deck=(FORMS[0], 'card.1'))
        self.play(g, LIBRARIAN)
        self.assertEqual(self.progress(g, FORMS[1]).progress_completions, 1); self.portable(g)

    def test_real_life_tap_and_its_newly_drawn_card_do_not_upgrade(self):
        g = self.game(deck=(FORMS[0], 'card.1'), power=TAP)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual(self.progress(g, FORMS[0]).progress_value, 0)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 28); self.portable(g)

    def test_fatigue_from_empty_deck_does_not_count_as_card_damage(self):
        self.script('draw', lambda c: (Draw(1, source_id=c.source_id),))
        g = self.game(('draw', FORMS[0]), deck=()); self.play(g, 'draw')
        self.assertEqual(self.progress(g, FORMS[0]).progress_value, 0)
        value = next(health_result(e) for e in g.events if e.kind == 'health_resolved')
        self.assertEqual(value.damage_kind, DamageKind.FATIGUE.value)

    def test_health_payment_and_direct_health_loss_do_not_count_as_damage(self):
        self.script('setup', lambda c: (AddCostModifier(1, CostSpec(payment=PaymentType.HEALTH),
            source_id=c.source_id),))
        self.script('paid', lambda c: (), cost=3)
        self.script('loss', lambda c: (LoseHealth(c.state.players[1].hero_id, 2, c.source_id),))
        g = self.game(('setup', 'paid', 'loss', FORMS[0])); self.play(g, 'setup'); self.play(g, 'paid'); self.play(g, 'loss')
        self.assertEqual(self.progress(g, FORMS[0]).progress_value, 0)
        self.assertTrue(any(e.kind == 'health_spent' for e in g.events))
        self.assertFalse(any(e.kind == 'health_resolved' for e in g.events)); self.portable(g)

    def test_enemy_source_and_own_minion_recipient_do_not_qualify(self):
        self.script('other', lambda c: (Damage(c.state.players[1].hero_id, 1, c.state.players[2].board[0]),
            Damage(c.state.players[1].board[0], 1, c.source_id)))
        g = self.game(('other', FORMS[0]), board=('probe.unit',)); self.play(g, 'other')
        self.assertEqual(self.progress(g, FORMS[0]).progress_value, 0)

    def test_unattributed_damage_and_initial_hero_source_do_not_qualify(self):
        self.script('other', lambda c: (Damage(c.state.players[1].hero_id, 1),
            Damage(c.state.players[1].hero_id, 1, c.state.players[1].hero_id)))
        g = self.game(('other', FORMS[0])); self.play(g, 'other')
        self.assertEqual(self.progress(g, FORMS[0]).progress_value, 0)

    def test_zero_and_immune_damage_results_do_not_upgrade(self):
        self.script('protected', lambda c: (Damage(c.state.players[1].hero_id, 0, c.source_id),
            GrantKeyword(c.state.players[1].hero_id, Keyword.IMMUNE),
            Damage(c.state.players[1].hero_id, 3, c.source_id)))
        g = self.game(('protected', FORMS[0])); self.play(g, 'protected')
        self.assertEqual(self.progress(g, FORMS[0]).progress_value, 0)
        rows = [health_result(e) for e in g.events if e.kind == 'health_resolved']
        self.assertEqual([v.damage_dealt for v in rows], [0, 0]); self.portable(g)

    def test_armor_absorbed_is_actual_damage_under_internal_policy(self):
        self.hit('hit', 1); g = self.game(('hit', FORMS[0]), armor=5); self.play(g, 'hit')
        self.assertEqual(self.progress(g, FORMS[1]).progress_units, (1,))
        value = next(health_result(e) for e in g.events if e.kind == 'health_resolved')
        self.assertEqual((value.health_lost, value.armor_absorbed, value.damage_dealt), (0, 1, 1))

    def test_own_minion_combat_packet_qualifies_without_excluding_all_combat(self):
        # Only the result predicate is tested; no Misdirection adapter or combat permission is added.
        self.script('packet', lambda c: (Damage(c.state.players[1].hero_id, 1,
            c.state.players[1].board[0], DamageKind.COMBAT),))
        g = self.game(('packet', FORMS[0]), board=('probe.unit',)); self.play(g, 'packet')
        self.assertEqual(self.progress(g, FORMS[1]).progress_units, (1,))

    def test_original_source_player_survives_later_control_change(self):
        self.options['transfer_source'] = True
        self.script('packet', lambda c: (Damage(c.state.players[1].hero_id, 1, c.state.players[1].board[0]),))
        g = self.game(('packet', FORMS[0]), board=('probe.unit', 'probe.transfer'))
        source = self.entity(g, 'probe.unit', zone=Zone.BOARD).id; self.play(g, 'packet')
        self.assertEqual(g.state.entities[source].controller, 2)
        self.assertEqual(self.progress(g, FORMS[1]).progress_units, (1,)); self.portable(g)

    def test_acquisition_after_damage_does_not_receive_old_packet_credit(self):
        self.script('late', lambda c: (Damage(c.state.players[1].hero_id, 1, c.source_id), AddToHand(1, FORMS[0])))
        g = self.game(('late',)); self.play(g, 'late')
        self.assertEqual(self.progress(g, FORMS[0]).progress_value, 0)

    def test_enemy_turn_own_source_is_not_limited_to_owner_turn(self):
        self.script('packet', lambda c: (Damage(c.state.players[1].hero_id, 1, c.state.players[1].board[0]),))
        g = self.game((FORMS[0],), board=('probe.unit',), enemy_hand=('packet',))
        g.apply(EndTurn(1)); self.play(g, 'packet')
        self.assertEqual(self.progress(g, FORMS[1]).progress_units, (1,)); self.portable(g)

    def test_real_lifesteal_bodies_use_three_five_seven_actual_damage(self):
        self.script('hurt', lambda c: (Damage(c.state.players[1].hero_id, 15),))
        for cid, n in zip(FORMS, (3, 5, 7)):
            with self.subTest(cid=cid):
                g = self.game(('hurt', cid)); self.play(g, 'hurt')
                target = g.state.players[2].board[0]; self.play(g, cid, target)
                self.assertEqual(g.state.entities[target].health, 12-n)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 15+n)
                self.assertEqual(g.state.players[1].mana, 6); self.portable(g)

    def test_real_body_and_lifesteal_do_not_upgrade_other_held_spellstone(self):
        self.script('hurt', lambda c: (Damage(c.state.players[1].hero_id, 5),))
        g = self.game(('hurt', FORMS[2], FORMS[0])); self.play(g, 'hurt')
        self.play(g, FORMS[2], g.state.players[2].board[0])
        self.assertEqual(self.progress(g, FORMS[0]).progress_value, 0)

    def test_same_actual_health_result_is_one_progress_witness(self):
        self.hit('hit', 1); g = self.game(('hit', FORMS[0])); self.play(g, 'hit')
        a = self.progress(g, FORMS[1]); event = next(e for e in g.events if e.kind == 'health_resolved')
        self.assertEqual(a.progress_keys, (f'event:{event.sequence}',))
        self.assertEqual(sum(e.kind == 'hand_card_upgraded' for e in g.events), 1); self.portable(g)

    def test_last_stage_stops_after_two_real_instances(self):
        self.script('three', lambda c: tuple(Damage(c.state.players[1].hero_id, 1, c.source_id) for _ in range(3)))
        g = self.game(('three', FORMS[0])); self.play(g, 'three')
        self.assertEqual(self.progress(g, FORMS[2]).progress_units, (1, 1))
        self.assertEqual(sum(e.kind == 'hand_card_upgraded' for e in g.events), 2)

    def test_current_copy_inherits_stage_and_base_copy_starts_from_current_face(self):
        self.hit('hit', 1)
        def copies(c):
            e = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == FORMS[1])
            ref = CardReference.capture(e)
            return (CopyCard(ref, 1, mode='current'), CopyCard(ref, 1, mode='base'))
        self.script('copy', copies); g = self.game(('hit', 'copy', FORMS[0])); self.play(g, 'hit'); self.play(g, 'copy')
        rows = [progress_ability(g.state.entities[i]) for i in g.state.players[1].hand]
        self.assertEqual([a.progress_completions for a in rows], [1, 1, 0]); self.portable(g)

    def test_nonhand_zone_pauses_and_return_keeps_stage(self):
        self.hit('one', 1); self.hit('two', 1); self.hit('three', 1)
        def move(c, src, dst):
            e = next(c.state.entities[i] for i in getattr(c.state.players[1], src.value) if c.state.entities[i].card_id == FORMS[1])
            return (MoveCard(CardReference.capture(e), 1, dst),)
        self.script('away', lambda c: move(c, Zone.HAND, Zone.DECK)); self.script('back', lambda c: move(c, Zone.DECK, Zone.HAND))
        g = self.game(('one', 'away', 'two', 'back', 'three', FORMS[0])); self.play(g, 'one'); self.play(g, 'away')
        self.play(g, 'two'); self.play(g, 'back'); self.play(g, 'three')
        self.assertEqual(self.progress(g, FORMS[2]).progress_completions, 2); self.portable(g)

    def test_upgrade_clears_local_discount_but_retains_physical_identity(self):
        def cost(c):
            e = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == FORMS[0])
            return (ModifyCost(e.id, CostSpec(delta=-2)),)
        self.script('discount', cost); self.hit('hit', 1)
        g = self.game(('discount', 'hit', FORMS[0])); source = self.entity(g, FORMS[0]).id
        self.play(g, 'discount'); self.assertEqual(g.quote_cost(source).amount, 2); self.play(g, 'hit')
        self.assertEqual(self.entity(g, FORMS[1]).id, source); self.assertEqual(g.quote_cost(source).amount, 4)

    def test_waiting_progress_uses_one_frozen_result_after_restore(self):
        self.options['wait'] = True; self.hit('hit', 1)
        g = self.game(('hit', 'probe.progress')); self.play(g, 'hit')
        self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g)
        for game in (g, restored):
            choice = game.state.pending_choice
            game.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))
            self.assertEqual(self.progress(game, 'probe.progress').progress_units, (1,))
            self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 29)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_invalid_condition_rolls_back_paid_action_and_consumed_rng(self):
        self.options['bad_condition'] = True
        self.script('bad', lambda c: (RandomDamage(tuple(c.state.players[2].board), 1, c.source_id),
            Damage(c.state.players[1].hero_id, 1, c.source_id)), cost=2)
        g = self.game(('bad', FORMS[0]), enemy_board=('probe.unit', 'probe.unit')); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'condition must return bool'): self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_private_result_and_witnesses_are_not_player_information(self):
        self.hit('hit', 1); g = self.game(('hit', FORMS[0])); self.play(g, 'hit')
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['hand_progress']['completions'], 1)
        self.assertNotIn('hand_progress', g.observe(2)['players'][0]['hand'][0])
        for viewer in (1, 2):
            text = json.dumps(g.observe(viewer))
            for field in ('health_resolved', 'progress_keys', 'progress_units', 'source_card_id', 'source_zone_epoch'):
                self.assertNotIn(field, text)

