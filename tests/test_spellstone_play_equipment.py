"""Independent played-card and equipped-weapon upgrades on existing frozen facts."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, CounterSpell, EndTurn,
    Game, HandProgressSpec, Keyword, PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario,
    SecretSpec, SelectChoice, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, EquipWeapon, ModifyCost,
    ModifyWeapon, RandomDestroy, RequestChoice, Summon, Transform)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.play_history import matches_play_tribes, play_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.secrets import RemoveSecret, SetSecret
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry

RUBY = ('LOOT_103', 'LOOT_103t1', 'LOOT_103t2')
EMERALD = ('LOOT_080', 'LOOT_080t2', 'LOOT_080t3')
MITHRIL = ('LOOT_203', 'LOOT_203t2', 'LOOT_203t3')
ONYX = ('LOOT_503', 'LOOT_503t', 'LOOT_503t2')
FLY, FLAME, HARVEST, DAMAGED = 'UNG_809', 'UNG_809t1', 'EX1_556', 'skele21'
SECRET, AXE, WOLF, GOLEM = 'EX1_287', 'CS2_106', 'LOOT_077t', 'LOOT_203t4'
FAMILIES = (RUBY, EMERALD, MITHRIL, ONYX)
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/spellstone-play-equipment.json'
PIN = 'a6502a776924dfef1f85a03169a7de7847b4dc0d60c4a2fe938ff49546351342'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete played/equipment raw evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original played/equipment card changed')
    return {row['id']: row['data'] for row in raw['records']}


def physical_play(c):
    identity = dict(c.event.data).get('play_id')
    value = play_record(c.state, identity)
    if not value.completed or (value.source_id, value.player_id) != (c.event.source_id, c.event.player_id):
        raise ResolutionError('Qualification requires its completed physical hand play')
    return value if value.player_id == c.player_id else None


def registry(scripts=(), *, mutate=None, remove_equipped=False, wait=False, bad=False):
    r = opening_registry(); rows = evidence()
    def played(c, name):
        value = physical_play(c)
        if value is None:
            return False
        definition = r.card(value.card_id)
        if name == 'ruby':
            return value.kind == CardType.MINION and matches_play_tribes(r, value, ('elemental',))
        if name == 'emerald':
            return definition.secret is not None
        return definition.deathrattle is not None  # Necessary printed declaration profile.
    for name in ('ruby', 'emerald', 'onyx'):
        r.register_trigger_condition(name, (lambda c: 'invalid') if bad else
            lambda c, name=name: played(c, name))
    r.register_trigger_condition('mithril', (lambda c: 'invalid') if bad else
        lambda c: c.event.player_id == c.player_id)

    def ruby_body(c):
        raise ResolutionError('Ruby random Mage-spell body requires the complete M0 target pool')
    for family, name, goal, event, card_class, school in (
        (RUBY, 'ruby', 2, 'card_played', CardClass.MAGE, SpellSchool.FIRE),
        (EMERALD, 'emerald', 1, 'card_played', CardClass.HUNTER, SpellSchool.NATURE),
        (MITHRIL, 'mithril', 1, 'weapon_equipped', CardClass.WARRIOR, None),
        (ONYX, 'onyx', 3, 'card_played', CardClass.ROGUE, SpellSchool.SHADOW),
    ):
        for stage in (2, 1, 0):
            cid = family[stage]; row = rows[cid]
            spec = None if stage == 2 else HandProgressSpec('event', goal, family[stage + 1],
                event=event, condition_id=name, upgrade_cost_policy='clear_local')
            if name == 'ruby':
                body = ruby_body
            elif name in ('emerald', 'mithril'):
                token, count = (WOLF, stage + 2) if name == 'emerald' else (GOLEM, stage + 1)
                body = lambda c, token=token, count=count: tuple(Summon(c.player_id, token) for _ in range(count))
            else:
                def body(c, count=stage + 1):
                    targets = tuple(i for i in c.state.players[3-c.player_id].board
                        if c.state.entities[i].active and c.state.entities[i].kind == CardType.MINION)
                    return tuple(RandomDestroy(targets, c.source_id) for _ in range(count))
            r.register_behavior('body.' + cid, body)
            r.register_card(CardDefinition(cid, row['name'], CardType.SPELL, cost=row['cost'],
                on_play='body.' + cid, hand_progress=spec, spell_school=school,
                metadata=metadata(card_class, rarity=Rarity.RARE, collectible=stage == 0)))
    for cid, tribes in ((FLAME, ('elemental',)), (DAMAGED, ('mech',)), (WOLF, ('beast',)), (GOLEM, ())):
        row = rows[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'], metadata=metadata(collectible=False, tribes=tribes)))
    r.register_behavior('fly', lambda c: (AddToHand(c.player_id, FLAME),))
    r.register_behavior('harvest', lambda c: (Summon(c.player_id, DAMAGED),))
    for cid, battlecry, deathrattle, tribes in ((FLY, 'fly', None, ('elemental',)),
        (HARVEST, None, 'harvest', ('mech',))):
        row = rows[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'], battlecry=battlecry, deathrattle=deathrattle,
            metadata=metadata(tribes=tribes)))
    r.register_secret_condition('counter', lambda c: c.event.player_id == 3-c.player_id and
        c.window is not None and c.window.kind == 'spell' and not c.window.countered)
    r.register_behavior('counter', lambda c: (CounterSpell(c.window.id),))
    row = rows[SECRET]
    r.register_card(CardDefinition(SECRET, row['name'], CardType.SPELL, cost=row['cost'],
        keywords=(Keyword.SECRET,), secret=SecretSpec(SECRET, ('card_committed',), 'counter', 'counter'),
        spell_school=SpellSchool.ARCANE, metadata=metadata(CardClass.MAGE, rarity=Rarity.RARE)))
    row = rows[AXE]
    r.register_card(CardDefinition(AXE, row['name'], CardType.WEAPON, cost=row['cost'],
        attack=row['attack'], durability=row['health'], metadata=metadata(CardClass.WARRIOR, rarity=Rarity.FREE)))
    if mutate:
        source = FLAME if mutate == 'ruby' else HARVEST
        def change(c):
            value = physical_play(c)
            return (Transform(c.event.source_id, 'card.1'),) if value and value.card_id == source else ()
        r.register_behavior('mutate', change)
        r.register_card(CardDefinition('probe.mutator', 'Original face probe', CardType.MINION, health=8,
            triggers=(TriggerSpec('card_played', 'mutate'),), metadata=metadata()))
    if remove_equipped:
        r.register_behavior('remove.equipped', lambda c: (Destroy(c.event.source_id, c.source_id),))
        r.register_card(CardDefinition('probe.remover', 'Settled equipment probe', CardType.MINION, health=8,
            triggers=(TriggerSpec('weapon_equipped', 'remove.equipped'),), metadata=metadata()))
    if wait:
        r.register_behavior('wait', lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue', ()),), c.source_id),))
        r.register_behavior('noop', lambda c: ())
        r.register_card(CardDefinition('probe.counter', 'Waiting equipment counter', CardType.SPELL,
            on_play='noop', hand_progress=HandProgressSpec('event', 1, on_complete='wait',
                event='weapon_equipped', condition_id='mithril'), metadata=metadata()))
    for name, callback, cost in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=cost, on_play=name, metadata=metadata()))
    return r


class SpellstonePlayEquipmentTests(unittest.TestCase):
    def setUp(self): self.scripts = []; self.options = {}
    def script(self, name, callback, cost=0): self.scripts.append((name, callback, cost))
    def game(self, hand=(), *, deck=('card.1',)*20, board=(), enemy_hand=(), enemy_board=(), weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, deck=deck, board=board, weapon_card_id=weapon, mana=10, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',)*20,
                mana=10, max_mana=10)), seed=83), registry(self.scripts, **self.options))
    def entity(self, g, cid, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if g.state.entities[i].card_id == cid)
    def play(self, g, cid):
        p = g.state.active_player; source = self.entity(g, cid, p).id
        g.apply(PlayCard(p, source)); return source
    def progress(self, g, cid, player=1): return progress_ability(self.entity(g, cid, player))
    def ref(self, c, cid, zone=Zone.HAND):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[1], zone.value)
            if c.state.entities[i].card_id == cid))
    def round(self, g): g.apply(EndTurn(1)); g.apply(EndTurn(2))
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored

    def test_raw_twenty_rows_and_four_distinct_unit_goals(self):
        rows = evidence(); r = registry(); self.assertEqual(len(rows), 20)
        for family, goal in zip(FAMILIES, (2, 1, 1, 3)):
            for cid in family[:2]:
                spec = r.card(cid).hand_progress
                self.assertEqual((spec.goal, spec.amount_basis), (goal, 'one'))
        self.assertIn('Play 3', rows[ONYX[0]]['text_en'])
        self.assertEqual((rows[AXE]['cost'], rows[GOLEM]['attack'], rows[WOLF]['health']), (2, 5, 3))

    def test_ruby_two_real_elemental_plays_per_stage(self):
        g = self.game((RUBY[0], FLY, FLAME, FLAME, FLAME))
        self.play(g, FLY); self.assertEqual(self.progress(g, RUBY[0]).progress_value, 1)
        for expected in (RUBY[1], RUBY[1], RUBY[2]):
            self.play(g, FLAME); self.assertIsNotNone(self.progress(g, expected))
        self.assertEqual(self.progress(g, RUBY[2]).progress_completions, 2); self.portable(g)

    def test_ruby_summoned_elemental_does_not_count(self):
        self.script('summon', lambda c: (Summon(1, FLAME),))
        g = self.game((RUBY[0], 'summon')); self.play(g, 'summon')
        self.assertEqual(self.progress(g, RUBY[0]).progress_value, 0)

    def test_ruby_opponent_elemental_does_not_count(self):
        g = self.game((RUBY[0],), enemy_hand=(FLAME,)); g.apply(EndTurn(1)); self.play(g, FLAME)
        self.assertEqual(self.progress(g, RUBY[0]).progress_value, 0)

    def test_ruby_original_played_face_survives_later_transform(self):
        self.options['mutate'] = 'ruby'
        g = self.game((RUBY[0], FLAME), board=('probe.mutator',)); source = self.play(g, FLAME)
        self.assertEqual(g.state.entities[source].card_id, 'card.1')
        self.assertEqual(g.state.play_history[-1].played_face.card_id, FLAME)
        self.assertEqual(self.progress(g, RUBY[0]).progress_value, 1); self.portable(g)

    def test_ruby_body_rejects_missing_complete_pool_and_rolls_back(self):
        for cid in RUBY:
            with self.subTest(card=cid):
                g = self.game((cid,)); before = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'M0'):
                    self.play(g, cid)
                self.assertEqual(g.snapshot(), before)

    def test_emerald_real_secret_play_counts_once(self):
        g = self.game((EMERALD[0], SECRET)); self.play(g, SECRET)
        self.assertEqual(self.progress(g, EMERALD[1]).progress_units, (1,))
        self.assertEqual(len(g.state.players[1].secrets), 1); self.portable(g)

    def test_emerald_set_secret_without_physical_play_does_not_count(self):
        self.script('set', lambda c: (SetSecret(1, SECRET),))
        g = self.game((EMERALD[0], 'set')); self.play(g, 'set')
        self.assertEqual(len(g.state.players[1].secrets), 1)
        self.assertEqual(self.progress(g, EMERALD[0]).progress_value, 0)

    def test_emerald_countered_secret_play_and_later_secret_complete_two_stages(self):
        self.script('arm', lambda c: (SetSecret(2, SECRET),))
        g = self.game((EMERALD[0], 'arm', SECRET, SECRET)); self.play(g, 'arm'); self.play(g, SECRET)
        self.assertEqual(len(g.state.players[1].secrets), 0)
        self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(self.progress(g, EMERALD[1]).progress_completions, 1)
        self.play(g, SECRET); self.assertEqual(self.progress(g, EMERALD[2]).progress_units, (1, 1))
        self.portable(g)

    def test_emerald_ordinary_spell_does_not_count(self):
        g = self.game((EMERALD[0], 'coin')); self.play(g, 'coin')
        self.assertEqual(self.progress(g, EMERALD[0]).progress_value, 0)

    def test_mithril_actual_paid_weapon_equips_once(self):
        g = self.game((MITHRIL[0], AXE)); self.play(g, AXE)
        self.assertEqual(self.progress(g, MITHRIL[1]).progress_units, (1,))
        self.assertEqual(sum(e.kind == 'weapon_equipped' for e in g.events), 1); self.portable(g)

    def test_mithril_effect_equipment_does_not_require_weapon_hand_play(self):
        self.script('equip', lambda c: (EquipWeapon(1, AXE),))
        g = self.game((MITHRIL[0], 'equip')); self.play(g, 'equip')
        self.assertEqual(self.progress(g, MITHRIL[1]).progress_completions, 1)
        self.assertEqual(g.state.play_history[-1].card_id, 'equip')

    def test_mithril_replacement_is_a_second_actual_equipment(self):
        g = self.game((MITHRIL[0], AXE, AXE)); self.play(g, AXE)
        old = g.state.players[1].weapon_id; self.play(g, AXE)
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertEqual(self.progress(g, MITHRIL[2]).progress_units, (1, 1)); self.portable(g)

    def test_mithril_initial_weapon_does_not_retroactively_advance(self):
        g = self.game((MITHRIL[0],), weapon=AXE)
        self.assertEqual(self.progress(g, MITHRIL[0]).progress_value, 0)

    def test_mithril_opponent_equipment_does_not_count(self):
        g = self.game((MITHRIL[0],), enemy_hand=(AXE,)); g.apply(EndTurn(1)); self.play(g, AXE)
        self.assertEqual(self.progress(g, MITHRIL[0]).progress_value, 0)

    def test_mithril_weapon_stat_change_is_not_equipping(self):
        self.script('buff', lambda c: (ModifyWeapon(c.state.players[1].weapon_id, attack=1),))
        g = self.game((MITHRIL[0], 'buff'), weapon=AXE); self.play(g, 'buff')
        self.assertEqual(self.progress(g, MITHRIL[0]).progress_value, 0)

    def test_mithril_settled_equipment_counts_after_reaction_removes_weapon(self):
        self.options['remove_equipped'] = True
        g = self.game((MITHRIL[0], AXE), board=('probe.remover',)); source = self.play(g, AXE)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.progress(g, MITHRIL[1]).progress_completions, 1); self.portable(g)

    def test_onyx_three_actual_deathrattle_card_plays(self):
        g = self.game((ONYX[0], HARVEST, HARVEST, HARVEST))
        for n in (1, 2):
            self.play(g, HARVEST); self.assertEqual(self.progress(g, ONYX[0]).progress_value, n)
        self.play(g, HARVEST); self.assertEqual(self.progress(g, ONYX[1]).progress_units, (1, 1, 1))
        self.assertEqual(len(g.state.death_history), 0); self.portable(g)

    def test_onyx_three_deaths_and_real_deathrattles_are_not_play_qualification(self):
        self.script('kill', lambda c: tuple(Destroy(i, c.source_id) for i in c.state.players[1].board))
        g = self.game((ONYX[0], 'kill'), board=(HARVEST,)*3); self.play(g, 'kill')
        self.assertEqual(self.progress(g, ONYX[0]).progress_value, 0)
        self.assertEqual(len(g.state.players[1].board), 3)
        self.assertTrue(all(g.state.entities[i].card_id == DAMAGED for i in g.state.players[1].board))

    def test_onyx_summoning_deathrattle_card_is_not_a_play(self):
        self.script('summon', lambda c: (Summon(1, HARVEST),))
        g = self.game((ONYX[0], 'summon')); self.play(g, 'summon')
        self.assertEqual(self.progress(g, ONYX[0]).progress_value, 0)

    def test_onyx_original_declaration_survives_later_transform(self):
        self.options['mutate'] = 'onyx'
        g = self.game((ONYX[0], HARVEST), board=('probe.mutator',)); source = self.play(g, HARVEST)
        self.assertEqual(g.state.entities[source].card_id, 'card.1')
        self.assertEqual(self.progress(g, ONYX[0]).progress_value, 1); self.portable(g)

    def test_onyx_body_one_two_three_random_distinct_victims_and_replay(self):
        for stage, cid in enumerate(ONYX):
            with self.subTest(card=cid):
                g = self.game((cid,), enemy_board=('card.1',)*4); self.play(g, cid)
                self.assertEqual(len(g.state.players[2].board), 3-stage)
                self.assertEqual(len({d.entity_id for d in g.state.death_history}), stage+1); self.portable(g)

    def test_onyx_body_less_than_requested_and_empty_pool(self):
        for count in (0, 1):
            with self.subTest(count=count):
                g = self.game((ONYX[2],), enemy_board=('card.1',)*count); self.play(g, ONYX[2])
                self.assertEqual(g.state.players[2].board, []); self.portable(g)

    def test_emerald_and_mithril_actual_bodies_all_three_forms(self):
        for family, token, first in ((EMERALD, WOLF, 2), (MITHRIL, GOLEM, 1)):
            for stage, cid in enumerate(family):
                with self.subTest(card=cid):
                    g = self.game((cid,)); self.play(g, cid)
                    self.assertEqual(len(g.state.players[1].board), first+stage)
                    self.assertTrue(all(g.state.entities[i].card_id == token for i in g.state.players[1].board))
                    self.portable(g)

    def test_late_acquisition_does_not_copy_past_qualification(self):
        for family, source in zip(FAMILIES, (FLAME, SECRET, AXE, HARVEST)):
            with self.subTest(family=family[0]):
                self.scripts = []
                self.script('add', lambda c, cid=family[0]: (AddToHand(1, cid),))
                g = self.game((source, 'add')); self.play(g, source); self.play(g, 'add')
                self.assertEqual(self.progress(g, family[0]).progress_value, 0)
                self.assertEqual(self.progress(g, family[0]).progress_keys, ())

    def test_nonhand_zone_pauses_and_return_keeps_partial_progress(self):
        self.script('away', lambda c: (MoveCard(self.ref(c, RUBY[0]), 1, Zone.DECK),))
        self.script('back', lambda c: (MoveCard(self.ref(c, RUBY[0], Zone.DECK), 1, Zone.HAND),))
        g = self.game((RUBY[0], FLAME, FLAME, FLAME, 'away', 'back'))
        self.play(g, FLAME); self.play(g, 'away'); self.play(g, FLAME); self.play(g, 'back')
        self.assertEqual(self.progress(g, RUBY[0]).progress_value, 1)
        self.play(g, FLAME); self.assertEqual(self.progress(g, RUBY[1]).progress_completions, 1); self.portable(g)

    def test_current_and_base_copy_keep_or_reset_qualification_witness(self):
        self.script('copy', lambda c: (CopyCard(self.ref(c, RUBY[0]), 1, mode='current'),
            CopyCard(self.ref(c, RUBY[0]), 1, mode='base')))
        g = self.game((RUBY[0], FLAME, 'copy')); self.play(g, FLAME); self.play(g, 'copy')
        copies = [progress_ability(g.state.entities[i]) for i in g.state.players[1].hand
            if g.state.entities[i].card_id == RUBY[0]]
        self.assertEqual([a.progress_value for a in copies], [1, 1, 0])
        self.assertEqual(copies[0].progress_keys, copies[1].progress_keys); self.portable(g)

    def test_upgrade_keeps_physical_identity_clears_local_cost_and_stops_at_final(self):
        from hs_sim.engine.costs import quote_unselected_cost
        self.script('cost', lambda c: (ModifyCost(self.ref(c, MITHRIL[0]).entity_id, CostSpec(delta=-2)),))
        g = self.game((MITHRIL[0], 'cost', AXE, AXE, AXE)); entity = self.entity(g, MITHRIL[0])
        source = entity.id; ability = progress_ability(entity).id
        self.assertEqual(quote_unselected_cost(g.state, g.registry, entity).amount, 7)
        self.play(g, 'cost')
        self.assertEqual(quote_unselected_cost(g.state, g.registry, self.entity(g, MITHRIL[0])).amount, 5)
        self.play(g, AXE); upgraded = self.entity(g, MITHRIL[1])
        self.assertEqual((upgraded.id, progress_ability(upgraded).id), (source, ability))
        self.assertEqual(quote_unselected_cost(g.state, g.registry, upgraded).amount, 7)
        self.play(g, AXE); self.play(g, AXE)
        self.assertEqual(self.progress(g, MITHRIL[2]).progress_units, (1, 1)); self.portable(g)

    def test_equipment_waiting_restores_without_second_equipment_or_witness(self):
        self.options['wait'] = True
        g = self.game(('probe.counter', AXE)); self.play(g, AXE)
        self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g)
        for instance in (g, restored):
            instance.apply(SelectChoice(1, instance.state.pending_choice.id, ('ok',)))
            self.assertEqual(sum(e.kind == 'weapon_equipped' for e in instance.events), 1)
            self.assertEqual(self.progress(instance, 'probe.counter').progress_units, (1,))
            self.assertTrue(instance.state.play_history[-1].completed)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_bad_qualification_rolls_back_payment_and_actual_equipment(self):
        self.options['bad'] = True
        g = self.game((MITHRIL[0], AXE)); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'condition must return bool'):
            self.play(g, AXE)
        self.assertEqual(g.snapshot(), before)

    def test_players_do_not_observe_hidden_progress_records_or_witnesses(self):
        g = self.game((RUBY[0], FLAME)); self.play(g, FLAME)
        own = g.observe(1); enemy = g.observe(2)
        self.assertEqual(own['players'][0]['hand'][0]['hand_progress']['value'], 1)
        self.assertIsNone(enemy['players'][0]['hand'][0]['card_id'])
        self.assertNotIn('hand_progress', enemy['players'][0]['hand'][0])
        for view in (own, enemy):
            text = json.dumps(view)
            for private in ('played_face', 'progress_keys', 'progress_units', 'corrupt_candidates'):
                self.assertNotIn(private, text)

    def test_turn_boundary_keeps_partial_elemental_progress(self):
        g = self.game((RUBY[0], FLAME, FLAME)); self.play(g, FLAME); self.round(g)
        self.assertEqual(self.progress(g, RUBY[0]).progress_value, 1)
        self.play(g, FLAME); self.assertEqual(self.progress(g, RUBY[1]).progress_completions, 1); self.portable(g)

    def test_opponent_secret_and_deathrattle_plays_do_not_count(self):
        for family, source in ((EMERALD, SECRET), (ONYX, HARVEST)):
            with self.subTest(family=family[0]):
                g = self.game((family[0],), enemy_hand=(source,)); g.apply(EndTurn(1)); self.play(g, source)
                self.assertEqual(self.progress(g, family[0]).progress_value, 0)
