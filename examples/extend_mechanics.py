"""从项目根目录运行：python -m examples.extend_mechanics

演示扩展路径：不可变 Effect → 处理器注册 → 卡牌行为 → 公开操作。
示例完全独立于客户端、提取数据和真实卡牌，只组合已有护甲与抽牌效果。

快照和回放只保存状态、操作及版本标识，JSON 不保存或执行 Python 代码。
恢复时须提供相同模块名下的扩展类型、规则注册表及机制版本；本例复用同一
registry/mechanics 实例。变更回调语义时必须提升相应版本，不能只改函数体。
"""

from dataclasses import dataclass
import json

from hs_sim.engine.actions import PlayCard
from hs_sim.engine.effects import Draw, Effect, GainArmor
from hs_sim.engine.game import Game, PlayerSetup, Scenario
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.registry import Registry, RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics


@dataclass(frozen=True)
class ArmorAndDraw(Effect):
    """A small extension instruction; it owns no state and executes no logic."""

    player_id: int
    armor: int = 4
    cards: int = 1

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError("player_id must be 1 or 2")
        for name in ("armor", "cards"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")


def resolve_armor_and_draw(_resolution, effect: ArmorAndDraw):
    """Compose existing instructions; their usual checkpoints still apply."""
    return (GainArmor(effect.player_id, effect.armor), Draw(effect.player_id, effect.cards))


def prepare_supplies(context: RuleContext):
    """A card behavior reads a detached context and returns effect instructions."""
    return (ArmorAndDraw(context.player_id, armor=4, cards=1),)


def run_example():
    registry = Registry("example-registry-v1")
    registry.register_behavior("prepare_supplies", prepare_supplies)
    registry.register_card(CardDefinition("hero", "示例英雄", CardType.HERO, health=30))
    registry.register_card(CardDefinition("supplies", "示例补给", CardType.SPELL,
                                          cost=1, on_play="prepare_supplies"))

    mechanics = default_mechanics("example-effects-v1")
    mechanics.register(ArmorAndDraw, resolve_armor_and_draw)

    scenario = Scenario((
        PlayerSetup("hero", hand=("supplies",), deck=("supplies",), max_mana=1, mana=1),
        PlayerSetup("hero"),
    ), seed=42, name="自定义效果示例")
    game = Game.from_scenario(scenario, registry, mechanics=mechanics)
    branch = game.clone()
    action = PlayCard(1, game.state.players[1].hand[0])
    result = game.apply(action)
    assert branch.apply(action) == result
    assert branch.snapshot() == game.snapshot()

    restored = Game.from_snapshot(game.snapshot(), registry, mechanics=mechanics)
    assert restored.snapshot() == game.snapshot()
    # JSON round-trip demonstrates that data, not code objects, crosses this boundary.
    payload = json.loads(json.dumps(build_replay(game), ensure_ascii=False))
    reproduced = replay(payload, registry, mechanics=mechanics)
    assert reproduced.snapshot() == game.snapshot()

    state = game.state
    player = state.players[1]
    hero = state.entities[player.hero_id]
    assert (hero.armor, len(player.hand), len(player.deck), player.mana) == (4, 1, 0, 0)
    print(f"Effect resolved: armor={hero.armor}, hand={len(player.hand)}, mana={player.mana}.")
    print("Clone, snapshot restore, and JSON replay agree.")


if __name__ == "__main__":
    # Keep the type identity stable: examples.extend_mechanics.ArmorAndDraw.
    # This is also the module path used when another program imports the example.
    from examples.extend_mechanics import run_example as run_from_canonical_module

    run_from_canonical_module()
