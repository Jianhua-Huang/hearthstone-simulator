"""Native stat spells created by one original physical destruction.

The normal interpreter supplies deaths/reactions before delivery. Frozen bonuses
belong to the created card, survive current copies, and are captured by CAST.
"""
from dataclasses import dataclass

from .effects import AddToHand, Destroy, Effect, _integer, _player
from .lifecycle import attachment_id
from .model import AbilityInstance, CardType, SpellStatGrantValue, _name
from .sacrifice import MinionReference, live_minion, reference_value


@dataclass(frozen=True)
class SpellStatGrantProfile:
    card_id: str
    source_card_id: str
    value_kind: str = 'stat_grant'

    def __post_init__(self):
        _name(self.card_id, 'native stat spell'); _name(self.source_card_id, 'native destruction declaration')
        if self.value_kind != 'stat_grant': raise ValueError('Unsupported native spell value kind')


def validate_profile(registry, profile):
    if type(profile) is not SpellStatGrantProfile: raise ValueError('Expected native stat spell profile')
    profile.__post_init__()
    card, source = registry.card(profile.card_id), registry.card(profile.source_card_id)
    if (card.kind != CardType.SPELL or not card.hand_playable or card.on_play is None or
            source.kind != CardType.MINION or source.battlecry is None):
        raise ValueError('Native stat spell requires a real spell and minion Battlecry')


def validate_value(state, registry, value):
    if type(value) is not SpellStatGrantValue: raise ValueError('Expected complete native stat spell material')
    value.__post_init__()
    profile = registry.spell_value_profiles.get(value.card_id)
    validate_profile(registry, profile)
    from .death_causes import validate_in_state
    validate_in_state(state, registry, value.cause)
    cause = value.cause
    if (registry.card(cause.target_card_id).kind != CardType.MINION or
            registry.card(cause.source_card_id).kind != CardType.MINION or
            cause.target_controller != cause.source_controller or cause.target_id == cause.source_id):
        raise ValueError('Native stat material requires another original friendly minion')
    # The live branch is necessary during an existing deferred death window.
    victim = state.entities[cause.target_id]
    if not (any(d.cause == cause for d in state.death_history) or
            victim.doomed and victim.death_cause == cause):
        raise ValueError('Native stat spell lost its genuine original destruction')


def validate_ability(state, registry, ability):
    ability.__post_init__()
    if ability.kind != 'spell_stat_value': raise ValueError('Expected native physical stat spell')
    validate_value(state, registry, ability.spell_stat_value)


def install(state, registry, entity, value):
    validate_value(state, registry, value)
    if (entity.kind != CardType.SPELL or entity.card_id != value.card_id or
            any(a.kind in ('spell_base_value', 'spell_stat_value') for a in entity.abilities)):
        raise ValueError('Native stat spell cannot bind a foreign or already bound carrier')
    entity.abilities.append(AbilityInstance(attachment_id(state), 'spell_stat_value',
        source_id=value.cause.source_id, spell_stat_value=value))


@dataclass(frozen=True)
class DestroyMinionForStatSpell(Effect):
    player_id: int
    source_id: int
    victim: MinionReference
    card_id: str

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'native destruction source', 1)
        _name(self.card_id, 'native destruction reward'); reference_value(self.victim)
        if self.victim.player_id != self.player_id or self.victim.entity_id == self.source_id:
            raise ValueError('Native destruction requires another original friendly minion')


@dataclass(frozen=True)
class CompleteDestroyedStatSpell(Effect):
    player_id: int
    value: SpellStatGrantValue

    def __post_init__(self):
        _player(self.player_id)
        if type(self.value) is not SpellStatGrantValue: raise ValueError('Native reward lost frozen stat material')
        self.value.__post_init__()
        if self.player_id != self.value.cause.source_controller:
            raise ValueError('Native reward changed its original recipient')


def begin(r, request):
    request.__post_init__()
    validate_profile(r.registry, r.registry.spell_value_profiles.get(request.card_id))
    if request.source_id not in r.state.entities: raise ValueError('Native destruction has no source')
    victim = live_minion(r.state, request.victim)
    if victim is None:
        r.stale(request, request.victim.entity_id); return ()
    attack, health = victim.attack, victim.health
    from .resolver import destroy
    destroy(r, Destroy(victim.id, request.source_id))
    cause = victim.death_cause
    from .destruction_resources import matches, DestroyMinionsForResources
    original = DestroyMinionsForResources(request.player_id, request.source_id, (request.victim,))
    if not matches(cause, request.victim, original): return ()
    value = SpellStatGrantValue(request.card_id, attack, health, cause)
    validate_value(r.state, r.registry, value)
    return (CompleteDestroyedStatSpell(request.player_id, value),)


def finish(r, request):
    request.__post_init__(); validate_value(r.state, r.registry, request.value)
    cause = request.value.cause
    victim = r.state.entities[cause.target_id]
    dead = any(d.cause == cause for d in r.state.death_history)
    deferred = r.death_deferrals > 0 and victim.doomed and victim.death_cause == cause
    if not (dead or deferred): return ()
    from .opening import create_hand_card
    create_hand_card(r, AddToHand(request.player_id, request.value.card_id, cause.source_id),
        native_spell_value=request.value)
    return ()


def public_bonus(entity):
    rows = tuple(a.spell_stat_value for a in entity.abilities if a.kind == 'spell_stat_value')
    return None if not rows else {'attack': rows[0].attack, 'health': rows[0].health}


def register(mechanics):
    mechanics.register(DestroyMinionForStatSpell, begin)
    mechanics.register(CompleteDestroyedStatSpell, finish)
