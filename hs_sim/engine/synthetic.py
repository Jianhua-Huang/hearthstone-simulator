"""Synthetic mechanism fixtures, deliberately unrelated to any official card set."""
from .effects import Buff, Damage, DamageBatch, Heal, RandomDamage, Summon
from .game import PlayerSetup, Scenario
from .model import AuraSpec, CardDefinition, CardType, DamageKind, Keyword, TriggerSpec, Zone
from .registry import Registry


def build_registry() -> Registry:
    registry = Registry('synthetic-mechanics-v3')
    registry.register_behavior('test.bolt', lambda ctx: [Damage(ctx.target_id, 3, ctx.source_id, DamageKind.SPELL)])
    registry.register_behavior('test.heal', lambda ctx: [Heal(ctx.target_id, 3, ctx.source_id)])
    registry.register_target_rule('test.friendly', lambda ctx: (
        ctx.target is not None and ctx.target['controller'] == ctx.player_id and
        ctx.target['zone'] in ('board', 'hero')), visibility='player')

    def random_bolt(ctx):
        enemy = ctx.state.players[3 - ctx.player_id]
        return [RandomDamage(tuple([enemy.hero_id, *enemy.board]), 2, ctx.source_id, DamageKind.SPELL)]

    def nova(ctx):
        return [DamageBatch(tuple(Damage(i, 2, ctx.source_id, DamageKind.SPELL) for i in ctx.state.players[3 - ctx.player_id].board))]

    def hatch(ctx):
        position = dict(ctx.event.data).get('position') if ctx.event else None
        return [Summon(ctx.player_id, 'test.token', position)]

    def grow(ctx):
        if ctx.event is not None and ctx.event.player_id == ctx.player_id:
            return [Buff(ctx.source_id, attack=1)]
        return []

    for name, behavior in [('test.random_bolt', random_bolt), ('test.nova', nova), ('test.hatch', hatch), ('test.grow', grow)]:
        registry.register_behavior(name, behavior)
    for card in (
        CardDefinition('test.hero', '测试英雄', CardType.HERO, health=30),
        CardDefinition('test.soldier', '测试随从', CardType.MINION, cost=2, attack=2, health=3),
        CardDefinition('test.guard', '测试嘲讽', CardType.MINION, cost=3, attack=2, health=4, keywords=(Keyword.TAUNT,)),
        CardDefinition('test.shield', '测试圣盾', CardType.MINION, cost=1, attack=1, health=1, keywords=(Keyword.DIVINE_SHIELD,)),
        CardDefinition('test.herald', '测试攻击光环', CardType.MINION, cost=2, attack=1, health=3, auras=(AuraSpec(1),)),
        CardDefinition('test.egg', '测试亡语', CardType.MINION, cost=1, health=2, deathrattle='test.hatch'),
        CardDefinition('test.token', '测试衍生物', CardType.MINION, attack=1, health=1),
        CardDefinition('test.bolt', '测试定向伤害', CardType.SPELL, cost=1, on_play='test.bolt', requires_target=True),
        CardDefinition('test.random_bolt', '测试随机伤害', CardType.SPELL, cost=1, on_play='test.random_bolt'),
        CardDefinition('test.nova', '测试批量伤害', CardType.SPELL, cost=2, on_play='test.nova'),
        CardDefinition('test.medic', '测试战吼治疗', CardType.MINION, cost=2, attack=1, health=3,
                       on_play='test.heal', requires_target=True, target_rule='test.friendly'),
        CardDefinition('test.drummer', '测试出牌触发', CardType.MINION, cost=2, attack=1, health=3,
                       triggers=(TriggerSpec('card_played', 'test.grow'),)),
    ):
        registry.register_card(card)
    return registry


def demo_scenario(seed=7):
    return Scenario(players=(
        PlayerSetup('test.hero', hand=('test.soldier', 'test.bolt', 'test.random_bolt'),
                    board=('test.herald', 'test.egg'), deck=('test.guard', 'test.medic', 'test.nova', 'test.soldier'),
                    mana=3, max_mana=3),
        PlayerSetup('test.hero', hand=('test.bolt', 'test.soldier', 'test.nova'),
                    board=('test.guard', 'test.shield'), deck=('test.drummer', 'test.random_bolt', 'test.shield', 'test.bolt'),
                    mana=3, max_mana=3),
    ), seed=seed, name='synthetic-mechanism-demo')
