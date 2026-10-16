"""Finite reviewed health-effect cards, composing the existing effect instructions."""

from dataclasses import dataclass, replace
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch, Draw, Heal, HealBatch, SplitDamage
from hs_sim.engine.model import (
    CardDefinition, CardType, DamageKind, HealingKind, Keyword,
    SpellSchool, TargetMode, TargetSpec, Zone,
)
from hs_sim.engine.pools import PoolCard
from .metadata import metadata_from_record
from hs_sim.targets import TargetValidationError, canonical_digest


BATCH_PATH = Path(__file__).resolve().parents[2] / "data/cards/health-effects-v1.json"
BATCH_HASH = "b9e530e2f17662f4e98c7a1efb5c515d970f8d28b0181838a10d80149e50da66"
SCHOOLS = {1: SpellSchool.ARCANE, 2: SpellSchool.FIRE, 3: SpellSchool.FROST,
           4: SpellSchool.NATURE, 5: SpellSchool.HOLY, 6: SpellSchool.SHADOW, 7: SpellSchool.FEL}


@dataclass(frozen=True)
class HealthStep:
    operation: str
    scope: str
    amount: int
    basis: str = "constant"
    opponent_amount: int | None = None

    def __post_init__(self):
        if self.operation not in ("damage", "heal", "draw", "split_damage"):
            raise ValueError("Unsupported reviewed health operation")
        if self.scope not in ("target", "self", "own_hero", "enemy_hero", "both_heroes",
                              "enemy_minions", "friendly_minions", "other_friendly_minions",
                              "all_minions", "other_minions", "all_characters",
                              "other_characters", "friendly_characters", "all_enemies"):
            raise ValueError("Unsupported reviewed health recipient scope")
        if type(self.amount) is not int or self.amount < 0:
            raise ValueError("Health recipe amount must be nonnegative integer")
        if self.basis not in ("constant", "source_health", "hero_armor", "opponent_turn"):
            raise ValueError("Unsupported reviewed health amount basis")
        if self.basis == "opponent_turn":
            if type(self.opponent_amount) is not int or self.opponent_amount < 0:
                raise ValueError("Opponent-turn amount requires an explicit nonnegative integer")
        elif self.opponent_amount is not None:
            raise ValueError("Only opponent-turn basis has an alternate amount")
        if self.operation == "draw" and (self.scope != "own_hero" or self.basis != "constant"):
            raise ValueError("Draw uses a constant amount for the executing player")
        if self.operation == "split_damage" and (self.scope != "all_enemies" or self.basis != "constant"):
            raise ValueError("This batch only declares ordinary constant enemy split damage")


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding="utf-8"))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError("Health card batch differs from its pinned reviewed records")
    return data


def _amount(context, step):
    if step.basis == "source_health":
        return max(0, context.state.entities[context.source_id].health)
    if step.basis == "hero_armor":
        return context.state.entities[context.state.players[context.player_id].hero_id].armor
    if step.basis == "opponent_turn" and context.state.active_player != context.player_id:
        return step.opponent_amount
    return step.amount


def _recipients(context, scope):
    own = context.state.players[context.player_id]
    enemy = context.state.players[3-context.player_id]
    if scope == "target":
        return () if context.target_id is None else (context.target_id,)
    if scope == "self":
        return (context.source_id,)
    if scope == "own_hero":
        return (own.hero_id,)
    if scope == "enemy_hero":
        return (enemy.hero_id,)
    if scope == "both_heroes":
        return (own.hero_id, enemy.hero_id)
    if scope in ("enemy_minions", "all_enemies"):
        boards = (enemy,)
    elif scope in ("friendly_minions", "other_friendly_minions", "friendly_characters"):
        boards = (own,)
    else:
        boards = (own, enemy)
    minions = tuple(eid for player in boards for eid in player.board
                    if context.state.entities[eid].kind == CardType.MINION
                    and context.state.entities[eid].active)
    if scope in ("all_characters", "other_characters"):
        result = (own.hero_id, enemy.hero_id, *minions)
    elif scope == "friendly_characters":
        result = (own.hero_id, *minions)
    elif scope == "all_enemies":
        result = (enemy.hero_id, *minions)
    else:
        result = minions
    if scope in ("other_characters", "other_minions", "other_friendly_minions"):
        result = tuple(eid for eid in result if eid != context.source_id)
    return result


def health_body(context, steps, is_spell):
    """Return immutable public effects; the kernel owns every state change."""
    effects = []
    for step in steps:
        amount = _amount(context, step)
        if step.operation == "draw":
            effects.append(Draw(context.player_id, amount))
            continue
        if step.operation == "split_damage":
            effects.append(SplitDamage(3-context.player_id, amount, context.source_id))
            continue
        ids = _recipients(context, step.scope)
        if step.operation == "damage":
            hits = tuple(Damage(eid, amount, context.source_id,
                DamageKind.SPELL if is_spell else DamageKind.EFFECT) for eid in ids)
            effects.extend(hits if step.scope in ("target", "self", "own_hero", "enemy_hero")
                           else (DamageBatch(hits),))
        else:
            heals = tuple(Heal(eid, amount, context.source_id,
                HealingKind.SPELL if is_spell else HealingKind.EFFECT) for eid in ids)
            effects.extend(heals if step.scope in ("target", "self", "own_hero", "enemy_hero")
                           else (HealBatch(heals),))
    return tuple(effects)


def register_health_cards(registry):
    registered_behaviors = set()
    for row in load_batch()["cards"]:
        raw, recipe = row["record"], row["recipe"]
        if canonical_digest(raw) != row["record_sha256"]:
            raise TargetValidationError("Health card record differs from its pinned identity")
        kind = CardType(raw["type"].lower())
        if raw["collectible"] is not True or kind not in (CardType.SPELL, CardType.MINION):
            raise TargetValidationError("Reviewed health cards require ordinary collectible roots")
        cost = raw["cost"]
        if cost is None and raw["id"] == "Core_CS2_008":
            cost = 0  # The sole audited zero-cost missing tag in this batch.
        if type(cost) is not int or cost < 0:
            raise TargetValidationError("Health card printed cost is unreviewed")
        keywords = tuple(Keyword(k) for k in recipe["keywords"])
        if set(keywords) - {Keyword.TAUNT, Keyword.LIFESTEAL}:
            raise TargetValidationError("Unexpected keyword in the reviewed health batch")
        kwargs = {}
        for entry, raw_steps in recipe["bodies"].items():
            if entry not in (("on_play",) if kind == CardType.SPELL else ("battlecry", "deathrattle")):
                raise TargetValidationError("Health body uses an unsupported trigger entry")
            steps = tuple(HealthStep(**step) for step in raw_steps)
            if not steps:
                raise TargetValidationError("Reviewed health bodies cannot be placeholders")
            behavior_id = "cards.health."+canonical_digest({"entry": entry, "spell": kind == CardType.SPELL,
                                                           "steps": raw_steps})[:24]
            if behavior_id not in registered_behaviors:
                registry.register_behavior(behavior_id,
                    lambda c, steps=steps, is_spell=kind == CardType.SPELL: health_body(c, steps, is_spell))
                registered_behaviors.add(behavior_id)
            kwargs[entry] = behavior_id
        if not kwargs:
            raise TargetValidationError("Health card requires a complete executable body")
        target = recipe["target"]
        if target is not None:
            if target not in ("character", "friendly_character", "minion", "enemy_minion"):
                raise TargetValidationError("Unsupported health card target domain")
            minion_only = target in ("minion", "enemy_minion")
            kwargs["targeting"] = TargetSpec(
                TargetMode.REQUIRED if kind == CardType.SPELL else TargetMode.IF_AVAILABLE,
                zones=(Zone.BOARD,) if minion_only else (Zone.HERO, Zone.BOARD),
                kinds=(CardType.MINION,) if minion_only else (CardType.HERO, CardType.MINION),
                relation="enemy" if target == "enemy_minion" else
                         "friendly" if target == "friendly_character" else "any",
            )
        school = raw["tags"].get("SPELL_SCHOOL")
        if school is not None and (type(school) is not int or school not in SCHOOLS):
            raise TargetValidationError("Unreviewed spell-school value")
        definition = CardDefinition(raw["id"], raw["name"], kind, cost=cost,
            attack=raw["attack"] or 0, health=raw["health"] or 0, keywords=keywords,
            spell_school=SCHOOLS.get(school),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe["deck_identity"]), **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
