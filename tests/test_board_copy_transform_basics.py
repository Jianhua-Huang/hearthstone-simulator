"""Current copy material is installed in the original physical board recipient."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, AuraSpec, CardDefinition, CardType, CostSpec, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice,
    SummonStats, TargetMode, TargetSpec, TransformMinionIntoCopy, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, Damage,
    Destroy, Freeze, GainArmor, InvokeBehavior, ModifyCost, RequestChoice,
    ReturnToHand, Silence, Transform)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

PIN = 'b85fa55ee81adc60055f45ceffd201f468c2a7789c9030746b62a550428d8267'
CARD = 'EX1_564'


def evidence():
    data = json.loads((Path(__file__).resolve().parents[1] / 'data/support/board-copy-transform-basics.json').read_bytes())
    if canonical_digest(data) != PIN:
        raise ValueError('Board copy-transform evidence changed')
    for row in data['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Board copy-transform raw row changed')
    return data


def registry():
    r = Registry('isolated-board-copy-transform-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=80, metadata=metadata(tribes=())))
    r.register_behavior('cry', lambda c: (GainArmor(c.player_id, 5),))
    r.register_card(CardDefinition('body', 'Body', CardType.MINION, cost=6, attack=4, health=7,
        keywords=(Keyword.TAUNT,), battlecry='cry', metadata=metadata(tribes=())))
    r.register_card(CardDefinition('recipient', 'Recipient', CardType.MINION, cost=2, attack=2, health=8,
        metadata=metadata(tribes=())))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, cost=2, attack=2, health=4,
        metadata=metadata(tribes=())))
    def operation(c, *, fixed=False, self_copy=False):
        target = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'recipient')
        return TransformMinionIntoCopy(MinionReference.capture(c.state.entities[target]),
            MinionReference.capture(c.state.entities[target if self_copy else c.target_id]),
            c.source_id, SummonStats(3, 3) if fixed else None)
    raw = evidence()['records'][0]['data']
    r.register_behavior('faceless', lambda c: () if c.target_id is None else (
        TransformMinionIntoCopy(MinionReference.capture(c.state.entities[c.source_id]),
                               MinionReference.capture(c.state.entities[c.target_id]), c.source_id),))
    r.register_card(CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry='faceless',
        targeting=TargetSpec(TargetMode.IF_AVAILABLE, kinds=(CardType.MINION,)),
        metadata=metadata_from_record(raw)))
    def wait(c):
        effect = operation(c)
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Copy', (effect,)),
            ChoiceOption('fault', 'Copy then fail', (effect, InvokeBehavior('late-fault', c.source_id, c.player_id)))), c.source_id),)
    def delayed_change(c, change):
        return (change(c), operation(c))
    scripts = {
        'copy': lambda c: (operation(c),),
        'fixed': lambda c: (operation(c, fixed=True),),
        'self': lambda c: (operation(c, self_copy=True),),
        'prep': lambda c: (Buff(c.target_id, 3, 2, c.source_id), Damage(c.target_id, 3, c.source_id),
                           ModifyCost(c.target_id, CostSpec(set_to=1), c.source_id), Freeze(c.target_id)),
        'silence': lambda c: (Silence(c.target_id),),
        'alter-then-copy': lambda c: delayed_change(c, lambda c: Buff(c.target_id, 1, 2, c.source_id)),
        'stale-source-destroy': lambda c: delayed_change(c, lambda c: Destroy(c.target_id, c.source_id)),
        'stale-source-transform': lambda c: delayed_change(c, lambda c: Transform(c.target_id, 'plain')),
        'stale-source-control': lambda c: delayed_change(c, lambda c: ChangeControl(c.target_id, 1)),
        'stale-source-return': lambda c: delayed_change(c, lambda c: ReturnToHand(c.target_id)),
        'stale-source-sleep': lambda c: delayed_change(c, lambda c: MakeDormant(c.target_id, None)),
        'stale-target': lambda c: delayed_change(c, lambda c: Transform(operation(c).target.entity_id, 'plain')),
        'wait': wait,
        'fault': lambda c: (operation(c), InvokeBehavior('late-fault', c.source_id, c.player_id)),
        'ordinary': lambda c: (Transform(c.target_id, 'plain'),),
    }
    for name, fn in scripts.items():
        r.register_behavior(name, fn)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
            targeting=TargetSpec(kinds=(CardType.MINION,)), metadata=metadata(tribes=())))
    r.register_behavior('late-fault', lambda c: (AddToHand(c.player_id, 'unknown.copy-transform'),))
    def observer(c):
        if dict(c.event.data).get('old_card_id') != 'recipient':
            return ()
        entity = c.state.entities[c.event.target_id]
        return (GainArmor(2, entity.attack * 100 + entity.health * 10 + entity.cost),)
    r.register_behavior('observe', observer)
    r.register_card(CardDefinition('observer', 'Observer', CardType.MINION, health=3,
        triggers=(TriggerSpec('transformed', 'observe'),), metadata=metadata(tribes=())))
    r.register_card(CardDefinition('aura', 'Aura', CardType.MINION, attack=1, health=3,
        auras=(AuraSpec(attack=2, health=1),), metadata=metadata(tribes=())))
    return r


class BoardCopyTransformBasicsTests(unittest.TestCase):
    def game(self, hand=(), *, board=('recipient',), enemy=('body',)):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('plain',) * 3, mana=10, max_mana=10),
            PlayerSetup('hero', board=enemy, deck=('plain',) * 3, mana=10, max_mana=10)), seed=73), registry())
    def source(self, g):
        return next(i for i in g.state.players[2].board if g.state.entities[i].card_id == 'body')
    def recipient(self, g):
        return g.state.players[1].board[0]
    def play(self, g, name, target=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, eid, target))
    def choose(self, g, name='ok'):
        q = g.state.pending_choice
        return g.apply(SelectChoice(q.player_id, q.id, (name,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        h = Game.from_snapshot(saved, registry())
        self.assertEqual(h.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        return h

    def test_complete_raw_pins_and_only_faceless_is_adapted(self):
        data = evidence(); c = registry().card(CARD)
        self.assertEqual(data['new_real_card_adapters'], [CARD])
        self.assertEqual((c.cost, c.attack, c.health), (5, 3, 3))
        self.assertNotIn('ETC_110', registry().cards)

    def test_typed_original_endpoints_and_stats_only(self):
        g = self.game(); a = MinionReference.capture(g.state.entities[self.recipient(g)])
        b = MinionReference.capture(g.state.entities[self.source(g)])
        self.assertEqual(TransformMinionIntoCopy(a, b).target, a)
        for args in ((a.entity_id, b), (a, b.entity_id), (a, b, None, {'attack': 3})):
            with self.subTest(args=args), self.assertRaises(ValueError):
                TransformMinionIntoCopy(*args)
        with self.assertRaises(ValueError):
            CardReference.capture(g.state.entities[b.entity_id])

    def test_real_battlecry_keeps_original_played_entity_and_payment(self):
        g = self.game((CARD,)); source = self.source(g)
        eid = g.state.players[1].hand[0]; old_source = g.state.entities[source]
        self.play(g, CARD, source); e = g.state.entities[eid]
        self.assertEqual((e.card_id, e.owner, e.controller, e.zone), ('body', 1, 1, Zone.BOARD))
        self.assertEqual(g.state.players[1].board[-1], eid)
        self.assertEqual(g.state.players[1].mana, 5)
        self.assertEqual(g.state.entities[source], old_source)
        self.assertEqual(g.state.play_history[-1].card_id, CARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.portable(g)

    def test_real_optional_battlecry_without_other_minions(self):
        g = self.game((CARD,), board=(), enemy=()); eid = g.state.players[1].hand[0]
        self.play(g, CARD)
        self.assertEqual(g.state.entities[eid].card_id, CARD)
        self.assertFalse(any(e.kind == 'transformed' for e in g.events))
        self.portable(g)

    def test_copy_preserves_identity_position_presence_and_source(self):
        g = self.game(('copy',), board=('recipient', 'plain')); source = self.source(g)
        target = self.recipient(g); before = g.state.entities[target]; original = g.state.entities[source]
        board = g.state.players[1].board; next_id = g.state.next_entity_id
        self.play(g, 'copy', source); e = g.state.entities[target]
        self.assertEqual((e.id, e.owner, e.controller, e.entered_order, e.board_presence_id),
                         (before.id, before.owner, before.controller, before.entered_order, before.board_presence_id))
        self.assertEqual(e.zone_epoch, before.zone_epoch + 1)
        self.assertEqual(g.state.players[1].board, board)
        self.assertEqual(g.state.next_entity_id, next_id)
        self.assertEqual(g.state.entities[source], original)
        self.assertFalse(g.state.death_history)
        self.portable(g)

    def test_current_local_buffs_cost_damage_and_frozen_state(self):
        g = self.game(('prep', 'copy')); source = self.source(g)
        self.play(g, 'prep', source); self.play(g, 'copy', source)
        e = g.state.entities[self.recipient(g)]
        self.assertEqual((e.attack, e.max_health, e.damage, e.health, e.cost), (7, 9, 3, 6, 1))
        self.assertTrue(e.frozen); self.assertIn(Keyword.TAUNT, e.keywords)
        self.assertTrue({a.id for a in e.abilities}.isdisjoint({a.id for a in g.state.entities[source].abilities}))
        self.portable(g)

    def test_fixed_stats_install_before_transform_event_and_clear_damage(self):
        g = self.game(('prep', 'fixed'), enemy=('body', 'observer')); source = self.source(g)
        self.play(g, 'prep', source); self.play(g, 'fixed', source)
        e = g.state.entities[self.recipient(g)]
        self.assertEqual((e.attack, e.max_health, e.health, e.damage, e.cost), (3, 3, 3, 0, 1))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor, 331)
        self.portable(g)

    def test_recipient_uses_are_preserved_not_copied_from_source(self):
        g = self.game(('copy',)); target = self.recipient(g)
        g.apply(Attack(1, target, self.source(g)))
        before = g.state.entities[target]
        self.play(g, 'copy', self.source(g)); e = g.state.entities[target]
        self.assertEqual((e.attacks_this_turn, e.summoned_turn), (before.attacks_this_turn, before.summoned_turn))
        self.assertEqual(e.attacks_this_turn, 1)
        with self.assertRaises(IllegalAction):
            g.apply(Attack(1, target, self.source(g)))
        self.portable(g)

    def test_old_recipient_material_is_replaced(self):
        g = self.game(('prep', 'copy')); target = self.recipient(g)
        self.play(g, 'prep', target); old = g.state.entities[target]
        self.play(g, 'copy', self.source(g)); e = g.state.entities[target]
        self.assertEqual((e.attack, e.max_health, e.damage, e.cost), (4, 7, 0, 6))
        self.assertFalse(e.frozen)
        self.assertTrue({a.id for a in old.enchantments}.isdisjoint({a.id for a in e.enchantments}))
        self.portable(g)

    def test_silenced_source_stays_silenced_without_printed_ability_reinstallation(self):
        g = self.game(('silence', 'copy')); source = self.source(g)
        self.play(g, 'silence', source); self.play(g, 'copy', source)
        e = g.state.entities[self.recipient(g)]
        self.assertTrue(e.silenced); self.assertNotIn(Keyword.TAUNT, e.keywords)
        self.assertFalse(e.abilities); self.portable(g)

    def test_source_external_aura_is_not_permanent_copy_material(self):
        g = self.game(('copy',), enemy=('body', 'aura'))
        self.assertEqual(g.state.entities[self.source(g)].attack, 6)
        self.play(g, 'copy', self.source(g))
        e = g.state.entities[self.recipient(g)]
        self.assertEqual((e.attack, e.max_health), (4, 7)); self.portable(g)

    def test_earlier_local_source_modification_is_read_at_actual_execution(self):
        g = self.game(('alter-then-copy',)); self.play(g, 'alter-then-copy', self.source(g))
        e = g.state.entities[self.recipient(g)]
        self.assertEqual((e.attack, e.max_health), (5, 9)); self.portable(g)

    def test_self_copy_reads_material_before_reset(self):
        g = self.game(('prep', 'self')); target = self.recipient(g)
        self.play(g, 'prep', target); before = g.state.entities[target]
        self.play(g, 'self', self.source(g)); e = g.state.entities[target]
        self.assertEqual((e.card_id, e.attack, e.max_health, e.damage, e.cost),
                         (before.card_id, before.attack, before.max_health, before.damage, before.cost))
        self.assertEqual(e.zone_epoch, before.zone_epoch + 1); self.portable(g)

    def test_changed_original_source_is_skipped(self):
        for name in ('destroy', 'transform', 'control', 'return', 'sleep'):
            g = self.game(('stale-source-' + name,)); target = self.recipient(g)
            self.play(g, 'stale-source-' + name, self.source(g))
            self.assertEqual(g.state.entities[target].card_id, 'recipient')
            self.assertTrue(any(e.kind == 'zone_target_skipped' for e in g.events))
            self.portable(g)

    def test_changed_original_recipient_is_skipped(self):
        g = self.game(('stale-target',)); target = self.recipient(g)
        self.play(g, 'stale-target', self.source(g))
        self.assertEqual(g.state.entities[target].card_id, 'plain')
        self.assertEqual(sum(e.kind == 'transformed' for e in g.events), 1); self.portable(g)

    def test_original_capacity_does_not_block_in_place_transformation(self):
        g = self.game(('copy',), board=('recipient',) + ('plain',) * 6)
        self.play(g, 'copy', self.source(g))
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(g.state.entities[self.recipient(g)].card_id, 'body')
        self.assertFalse(any(e.kind == 'summon_failed' for e in g.events)); self.portable(g)

    def test_waiting_restore_clone_replay_and_same_resumption(self):
        g = self.game(('wait',)); self.play(g, 'wait', self.source(g))
        other = self.portable(g); self.choose(g); self.choose(other)
        self.assertEqual(other.snapshot(), g.snapshot()); self.portable(g)

    def test_direct_and_waiting_late_errors_roll_back_full_transaction(self):
        g = self.game(('fault',)); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'fault', self.source(g))
        self.assertEqual(g.snapshot(), before)
        g = self.game(('wait',)); self.play(g, 'wait', self.source(g)); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.choose(g); self.portable(g)

    def test_codec_and_player_boundary(self):
        g = self.game(); a = MinionReference.capture(g.state.entities[self.recipient(g)])
        b = MinionReference.capture(g.state.entities[self.source(g)])
        effect = TransformMinionIntoCopy(a, b, stats=SummonStats(3, 3))
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(effect)), effect)
        for player in (1, 2):
            public = json.dumps(g.observe(player)) + json.dumps(g.for_player(player).legal_actions())
            for key in ('resolution_frame', 'zone_epoch', 'MinionReference', 'TransformMinionIntoCopy'):
                self.assertNotIn('"' + key + '"', public)

    def test_ordinary_printed_transform_keeps_existing_behavior(self):
        g = self.game(('prep', 'ordinary')); source = self.source(g)
        self.play(g, 'prep', source); self.play(g, 'ordinary', source)
        e = g.state.entities[source]
        self.assertEqual((e.card_id, e.attack, e.max_health, e.damage, e.cost), ('plain', 2, 4, 0, 2))
        self.assertFalse(e.frozen); self.portable(g)
