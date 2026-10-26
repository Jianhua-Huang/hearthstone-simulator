"""Native enemy destruction joined to existing consumed payloads and resurrection."""
from dataclasses import dataclass, replace

from .allocation_facts import SourceAllocationFact
from .copy_materials import CapturedCardCopyMaterial
from .effects import DestroyBatch, Effect, GrantDeathrattle, _integer
from .model import BoardPresenceReference, CardType, DeathCause, Zone
from .summon_quantities import SummonCause


def maw_profile(registry, card_id):
    profiles = [p for p in registry.consumption_profiles.values() if p.kind == 'board_minions'
        and registry.card(p.card_id).colossal[0].card_id == card_id]
    if len(profiles) != 1: raise ValueError('Devoured Maw requires one original native parent declaration')
    return profiles[0]


def validate_maw_link(state, registry, ability):
    parent = ability.devour_parent
    if parent is None: return
    if (type(parent) is not BoardPresenceReference or ability.kind != 'deathrattle' or
            ability.deathrattle_card_id is None):
        raise ValueError('Devoured Maw requires its original parent residence')
    parent.__post_init__(); profile = maw_profile(registry, ability.deathrattle_card_id)
    if (ability.behavior_id != registry.card(ability.deathrattle_card_id).deathrattle or
            parent.entity_id not in state.entities or parent.presence_id >= state.next_order or
            not any(v.entity_id == parent.entity_id and v.entered_order == parent.presence_id
                and v.card_id == profile.card_id for v in state.colossal_history)):
        raise ValueError('Devoured Maw lost its original Colossal parent residence')


def bind_maw(r, body, limb):
    profile = r.registry.consumption_profiles.get(body.card_id)
    if profile is None or profile.kind != 'board_minions': return
    if r.registry.card(body.card_id).colossal[0].card_id != limb.card_id:
        raise ValueError('Devoured Maw cannot borrow another appendage')
    parent = BoardPresenceReference.capture(r.state, body.id)
    limb.abilities = [replace(a, devour_parent=parent) if a.kind == 'deathrattle' and
        a.deathrattle_card_id == limb.card_id else a for a in limb.abilities]


def validate_destruction(state, registry, row):
    cause = row.destruction; origin = row.card.origin
    if type(cause) is not DeathCause: raise ValueError('Devoured minion lost its actual destruction cause')
    cause.__post_init__()
    if ((cause.kind, cause.reason, cause.source_id, cause.target_id, cause.target_card_id,
            cause.target_controller, cause.target_zone_epoch, cause.target_entered_order) !=
            ('destroy', 'Destroy', row.source.entity_id, origin.entity_id, origin.card_id,
             origin.controller, origin.zone_epoch, origin.entered_order)):
        raise ValueError('Devoured minion borrowed another original destruction')
    deaths = [v for v in state.death_history if v.cause == cause]
    target = state.entities[origin.entity_id]
    pending = (target.zone == Zone.BOARD and target.doomed and target.death_cause == cause
        and target.zone_epoch == origin.zone_epoch)
    if len(deaths) > 1 or not deaths and not pending:
        raise ValueError('Devoured minion lost its accepted original destruction or death')


@dataclass(frozen=True)
class DevourEnemyMinions(Effect):
    profile_id: str
    battlecry_id: int

    def __post_init__(self):
        from .model import _name
        _name(self.profile_id, 'original devour declaration'); _integer(self.battlecry_id, 'original devour Battlecry', 1)


def devour(r, effect):
    effect.__post_init__()
    from .battlecries import battlecry_record
    from .consumed_cards import ConsumedCardRecord, EVENT
    row = battlecry_record(r.state, effect.battlecry_id)
    profile = r.registry.consumption_profiles[effect.profile_id]
    if (profile.kind != 'board_minions' or row.payload.card_id != profile.card_id or
            row.payload.behavior_id != r.registry.card(profile.card_id).battlecry or
            not row.payload_started or row.completed or row.interrupted or row.failure is not None):
        raise ValueError('Devour requires its exact original active Battlecry')
    source = r.state.entities[row.source_id]
    receiver = source if source.zone == Zone.BOARD and source.kind == CardType.MINION and source.active and source.health > 0 and not source.doomed else None
    victims = tuple(r.state.entities[i] for i in r.player(3-row.player_id).board
        if r.state.entities[i].kind == CardType.MINION and r.state.entities[i].active
        and r.state.entities[i].health > 0 and not r.state.entities[i].doomed
        and r.registry.card(r.state.entities[i].card_id).interactable is None)
    materials = tuple(CapturedCardCopyMaterial.capture(r.state, e) for e in victims)
    original_source = None if receiver is None else SourceAllocationFact.capture(r.state, receiver)
    from .resolver import destroy_batch, _grant_to
    # All marks precede the ordinary death checkpoint. No reactions run inside
    # DestroyBatch, so the complete return inventory is bound before any deaths.
    destroy_batch(r, DestroyBatch(tuple(e.id for e in victims), row.source_id))
    if receiver is None: return ()
    granted = []
    for victim, material in zip(victims, materials):
        cause = victim.death_cause
        if cause is None: raise ValueError('Devour lost an original accepted destroy mark')
        consumed = ConsumedCardRecord(len(r.state.consumed_card_history)+1, profile.card_id,
            original_source, material, material.origin.zone_epoch+1, r.state.next_attachment_id,
            r.state.turn, r.state.action_number, len(r.game._events)+1, destruction=cause)
        r.state.consumed_card_history.append(consumed)
        _grant_to(r, GrantDeathrattle(receiver.id, r.registry.card(profile.card_id).deathrattle, receiver.id),
            receiver, notify=False, grant_card_id=profile.card_id, consumed_card_id=consumed.id)
        r.emit(EVENT, source_id=receiver.id, target_id=victim.id, player_id=receiver.controller,
            _capture=False, consumed_id=consumed.id)
        granted.append(consumed)
    # Publication captures immutable contexts. Every notification must already
    # contain the complete accepted group rather than its first partial prefix.
    for consumed in granted:
        r.emit('ability_granted', target_id=receiver.id, source_id=receiver.id,
            ability_id=consumed.ability_id, ability_kind='deathrattle')
    return ()


@dataclass(frozen=True)
class ReturnDevouredMinion(Effect):
    deathrattle_id: int
    cause: SummonCause

    def __post_init__(self):
        _integer(self.deathrattle_id, 'actual devoured return Deathrattle', 1)
        if type(self.cause) is not SummonCause: raise ValueError('Devoured return requires original card attribution')
        self.cause.__post_init__()


def activation(r, identity):
    from .deathrattles import record
    row = record(r.state, identity)
    if row.execution_order is None or row.completed or row.interrupted:
        raise ValueError('Devoured payload requires its actual running Deathrattle')
    return row.capture


def return_minion(r, effect):
    effect.__post_init__(); capture = activation(r, effect.deathrattle_id)
    from .consumed_cards import record, validate_payload
    validate_payload(r.state, r.registry, capture.ability)
    if capture.ability.consumed_card_id is None: return ()
    row = record(r.state, capture.ability.consumed_card_id)
    if r.registry.consumption_profiles[row.profile_id].kind != 'board_minions':
        raise ValueError('Devoured return cannot borrow another consumption family')
    validate_destruction(r.state, r.registry, row)
    deaths = [v for v in r.state.death_history if v.cause == row.destruction]
    if len(deaths) != 1:
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Devoured victim has not completed its original deferred destruction')
    if (effect.cause.source.entity_id, effect.cause.player_id) != (capture.carrier_id, capture.player_id):
        raise ValueError('Devoured return borrowed another actual causing card')
    from .summon_sources import ResurrectMinion
    return (ResurrectMinion(3-capture.player_id, deaths[0].id, source_id=capture.carrier_id, cause=effect.cause),)


@dataclass(frozen=True)
class DigestDevouredMinions(Effect):
    deathrattle_id: int

    def __post_init__(self): _integer(self.deathrattle_id, 'actual Maw Deathrattle', 1)


def digest(r, effect):
    effect.__post_init__(); capture = activation(r, effect.deathrattle_id)
    ability = capture.ability; validate_maw_link(r.state, r.registry, ability)
    if ability.devour_parent is None: return ()
    from .board_presence import resolve_board_presence
    parent = resolve_board_presence(r.state, ability.devour_parent)
    if parent is None: return ()  # Already accepted dead captures are immutable.
    from .consumed_cards import record
    profile = maw_profile(r.registry, ability.deathrattle_card_id)
    retired = tuple(a.id for a in parent.abilities if a.consumed_card_id is not None
        and record(r.state, a.consumed_card_id).profile_id == profile.card_id)
    parent.abilities = [a for a in parent.abilities if a.id not in retired]
    r.emit('devoured_minions_digested', source_id=capture.carrier_id, target_id=parent.id,
        player_id=capture.player_id, amount=len(retired), ability_ids=retired)
    return ()


def register(mechanics):
    mechanics.register(DevourEnemyMinions, devour)
    mechanics.register(ReturnDevouredMinion, return_minion)
    mechanics.register(DigestDevouredMinions, digest)
