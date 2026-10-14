"""Frozen board policies for hero-power payload repetitions (R-142).

Counts set the number of payload executions; they do not grant more uses.
The source merge and acceptance window remain pending CN calibration.
"""
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _player, _source
from .lifecycle import active_abilities, attachment_id
from .model import (AbilityInstance, CardType, Zone, HeroPowerRepeatSpec,
                    HeroPowerRepeatContributor, HeroPowerRepeatPlan)


def capture_plan(state, registry, player_id):
    from .repeat_source_conditions import validate_source_declaration, qualifying_repeat_witnesses
    from .repeat_provenance import checked_live_attachments
    from .registry import Registry
    if not isinstance(registry, Registry):
        raise ValueError('Hero power repeat capture requires its Registry')
    _player(player_id)
    inventory = checked_live_attachments(state)
    # Validate all declarations before any presence/condition exit. False or
    # inactive policies cannot hide unknown profiles or an illegal carrier.
    for family, carrier_id, ability in inventory.values():
        if family == 'ability' and ability.kind == 'hero_power_repeat':
            ability.__post_init__()
            validate_source_declaration(registry, ability.hero_power_repeat)
            if state.entities[carrier_id].kind != CardType.MINION:
                raise ValueError('Hero power repeat sources require physical minion carriers')
    sources=[]
    for entity_id in state.players[player_id].board:
        entity=state.entities[entity_id]
        if entity.kind!=CardType.MINION or not entity.active or entity.doomed or entity.health<=0:
            continue
        for ability in active_abilities(entity,'hero_power_repeat'):
            condition = validate_source_declaration(registry, ability.hero_power_repeat)
            if condition is None or qualifying_repeat_witnesses(state, registry,
                    player_id=player_id, carrier_id=entity.id, eligibility=condition):
                sources.append(HeroPowerRepeatContributor(entity.id,entity.card_id,player_id,ability))
    sources.sort(key=lambda source:source.key)
    return HeroPowerRepeatPlan(max((source.spec.repetitions for source in sources),default=1),tuple(sources))


def validate_plan(state, registry, plan, player_id, turn=None):
    from .repeat_source_conditions import validate_source_declaration
    from .repeat_provenance import checked_live_attachments
    _player(player_id)
    if turn is not None: _integer(turn, 'Hero power acceptance turn', 1)
    if type(plan) is not HeroPowerRepeatPlan:
        raise ValueError('Expected hero power repeat plan')
    plan.__post_init__()
    inventory = checked_live_attachments(state)
    for source in plan.contributors:
        validate_source_declaration(registry, source.spec)
        if (source.player_id!=player_id or source.carrier_id not in state.entities or
                registry.card(source.card_id).kind!=CardType.MINION or
                source.ability.id>=state.next_attachment_id or
                turn is not None and source.ability.expires_turn is not None and source.ability.expires_turn<turn or
                source.ability.source_id is not None and source.ability.source_id not in state.entities):
            raise ValueError('Invalid captured hero power repeat source')
        # A later silence/removal/transform may erase an accepted ability. If
        # its original ID survives, its immutable policy cannot be rewritten
        # in history to shorten an already accepted batch.
        current=inventory.get(source.ability.id)
        if current is not None:
            family, carrier_id, ability = current
            if (family!='ability' or carrier_id!=source.carrier_id or
                    replace(ability,consumed=source.ability.consumed)!=source.ability):
                raise ValueError('Captured hero power repeat source changed its complete surviving ability identity')


@dataclass(frozen=True)
class GrantHeroPowerRepeatAura(Effect):
    target_id: int
    spec: HeroPowerRepeatSpec = HeroPowerRepeatSpec()
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id,'Hero power repeat carrier',1);_source(self.source_id)
        if type(self.spec) is not HeroPowerRepeatSpec:
            raise ValueError('Expected hero power repeat specification')
        self.spec.__post_init__()
        if self.expires_turn is not None: _integer(self.expires_turn,'Hero power repeat expiry',1)


def grant(r, effect):
    from .resolver import validate_attachment_source
    from .repeat_source_conditions import validate_source_declaration
    effect.__post_init__()
    validate_source_declaration(r.registry, effect.spec)
    validate_attachment_source(r,effect.source_id,effect.expires_turn)
    entity=r.state.entities.get(effect.target_id)
    if entity is None or entity.kind!=CardType.MINION or entity.zone!=Zone.BOARD or not entity.active:
        r.stale(effect,effect.target_id);return
    ability=AbilityInstance(attachment_id(r.state),'hero_power_repeat',source_id=effect.source_id,
        hero_power_repeat=effect.spec,expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.emit('ability_granted',target_id=entity.id,source_id=effect.source_id,
           ability_id=ability.id,ability_kind=ability.kind)


def register(mechanics):
    mechanics.register(GrantHeroPowerRepeatAura,grant)
