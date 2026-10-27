"""Fixed-unit native trigger upgrades are ordinary removable enchantments.

No scalar is encoded in labels: each approved physical marker is one +1 unit.
Copies and resets retain the existing ordered attachment lifecycle.
"""
from dataclasses import dataclass, fields

from .effects import Effect
from .model import CardType, Enchantment, EndTurnSpec, TriggerSpec, _int, _name
from .sacrifice import MinionReference, reference_value, live_minion

PREFIX = 'native_trigger_value.'


@dataclass(frozen=True)
class TriggerValueProfile:
    id: str
    source_card_id: str
    producer_behavior_id: str
    recipient_ids: tuple[str, ...]
    recipient_behavior_id: str
    initial_value: int
    enchantment_card_id: str


def validate_profile(registry, profile):
    if type(profile) is not TriggerValueProfile:
        raise ValueError('Typed native trigger value declaration required')
    for key in ('id', 'source_card_id', 'producer_behavior_id', 'recipient_behavior_id', 'enchantment_card_id'):
        _name(getattr(profile, key), 'native trigger ' + key)
    _int(profile.initial_value, 'native trigger initial value', 1)
    if (type(profile.recipient_ids) is not tuple or not profile.recipient_ids or
            len(set(profile.recipient_ids)) != len(profile.recipient_ids)):
        raise ValueError('Native trigger upgrades require distinct complete recipient identities')
    source = registry.card(profile.source_card_id)
    if (source.kind != CardType.MINION or
            sum(t == TriggerSpec('turn_started', profile.producer_behavior_id) for t in source.triggers) != 1):
        raise ValueError('Native unit upgrade requires its original start-turn minion producer')
    registry.behavior(profile.producer_behavior_id); registry.behavior(profile.recipient_behavior_id)
    for cid in profile.recipient_ids:
        card = registry.card(cid)
        if (card.kind != CardType.MINION or card.metadata is None or card.metadata.collectible is not False or
                card.triggers != (TriggerSpec('turn_ended', profile.recipient_behavior_id, end_turn=EndTurnSpec()),)):
            raise ValueError('Native unit value requires its original noncollectible end-turn minion body')


def marker_id(enchantment):
    label = enchantment.label
    return label[len(PREFIX):] if type(label) is str and label.startswith(PREFIX) else None


def validate_marker_shape(enchantment):
    pid = marker_id(enchantment)
    if pid is None: return
    _name(pid, 'native trigger marker profile')
    if enchantment.source_id is None:
        raise ValueError('Native trigger upgrade requires its original physical source')
    for field in fields(enchantment):
        if field.name not in ('id', 'source_id', 'label') and getattr(enchantment, field.name) != field.default:
            raise ValueError('A unit trigger marker cannot mix other attachment operations or lifetimes')


def validate_carrier(registry, card_id, kind, enchantments):
    for enchantment in enchantments:
        pid = marker_id(enchantment)
        if pid is None: continue
        validate_marker_shape(enchantment)
        profile = registry.trigger_value_profiles.get(pid)
        if profile is None or kind != CardType.MINION or card_id not in profile.recipient_ids:
            raise ValueError('Native trigger marker borrowed an unreviewed profile or recipient')


def amount(registry, entity, behavior_id, initial_value):
    validate_carrier(registry, entity.card_id, entity.kind, entity.enchantments)
    profiles = tuple(p for p in registry.trigger_value_profiles.values()
        if entity.card_id in p.recipient_ids and p.recipient_behavior_id == behavior_id)
    if not profiles:
        if any(marker_id(e) is not None for e in entity.enchantments):
            raise ValueError('Marked native trigger cannot borrow another behavior')
        return initial_value  # Original unmodified standalone token is still exact.
    if len(profiles) != 1 or profiles[0].initial_value != initial_value:
        raise ValueError('Native trigger amount lost its single original printed declaration')
    profile, = profiles
    return initial_value + sum(marker_id(e) == profile.id for e in entity.enchantments)


def public_damage(registry, entity):
    for profile in registry.trigger_value_profiles.values():
        if entity.card_id in profile.recipient_ids and any(a.kind == 'trigger' and not a.consumed and
                a.event == 'turn_ended' and a.behavior_id == profile.recipient_behavior_id for a in entity.abilities):
            return amount(registry, entity, profile.recipient_behavior_id, profile.initial_value)
    return None


@dataclass(frozen=True)
class UpgradeNativeTrigger(Effect):
    profile_id: str
    target: MinionReference
    source: MinionReference

    def __post_init__(self):
        _name(self.profile_id, 'native trigger upgrade profile')
        reference_value(self.target); reference_value(self.source)
        if self.target.player_id != self.source.player_id:
            raise ValueError('Native trigger upgrade retains its original friendly selection')


def upgrade(r, effect):
    effect.__post_init__()
    profile = r.registry.trigger_value_profiles[effect.profile_id]
    if (effect.source.card_id != profile.source_card_id or effect.target.card_id not in profile.recipient_ids or
            effect.source.entity_id not in r.state.entities or
            r.state.entities[effect.source.entity_id].zone_epoch < effect.source.zone_epoch):
        raise ValueError('Native trigger upgrade lost its original producer or recipient')
    target = live_minion(r.state, effect.target)
    if target is None:
        r.stale(effect, effect.target.entity_id); return ()
    from .lifecycle import attachment_id
    marker = Enchantment(attachment_id(r.state), source_id=effect.source.entity_id, label=PREFIX+profile.id)
    target.enchantments.append(marker)
    r.emit('native_trigger_upgraded', source_id=effect.source.entity_id, target_id=target.id,
        player_id=effect.target.player_id, amount=1, profile_id=profile.id, attachment_id=marker.id,
        enchantment_card_id=profile.enchantment_card_id,
        current_value=amount(r.registry, target, profile.recipient_behavior_id, profile.initial_value))
    return ()


def validate_game(game):
    r, state = game.registry, game._state
    for entity in state.entities.values():
        validate_carrier(r, entity.card_id, entity.kind, entity.enchantments)
    for death in state.death_history:
        # Only marked rows need the extra lookup, including dynamic compositions.
        if any(marker_id(e) is not None for e in death.enchantments):
            validate_carrier(r, death.card_id, r.card(death.card_id).kind, death.enchantments)
    # DiscardRecord retains base allocation facts, not an attachment snapshot.
    # Its still-existing physical carrier is covered by the entity pass above.


def register(mechanics):
    mechanics.register(UpgradeNativeTrigger, upgrade)
