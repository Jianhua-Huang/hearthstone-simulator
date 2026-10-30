"""Original Battlecry damage waves; the shared health/death interpreters settle each wave."""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, validate_allocation
from .effects import Damage, Effect, _integer
from .model import CardType, DamageKind, HealthFlow, Zone
from .sacrifice import MinionReference, reference_value


@dataclass(frozen=True)
class RepeatBattlecryMinionDamage(Effect):
    battlecry_id: int
    amount: int

    def __post_init__(self):
        _integer(self.battlecry_id, 'original damage-wave Battlecry', 1)
        _integer(self.amount, 'minion damage-wave amount', 1)

    def validate_in_state(self, state, registry):
        from .battlecries import battlecry_record, validate_record
        self.__post_init__()
        record = battlecry_record(state, self.battlecry_id)
        validate_record(state, registry, record)
        if (record.completed or record.interrupted or record.failure is not None or
                not record.payload_started or registry.card(record.card_id).kind != CardType.MINION):
            raise ValueError('Damage wave lost its actual running minion Battlecry')
        return record


@dataclass(frozen=True)
class ContinueBattlecryDamageIfDeaths(Effect):
    request: RepeatBattlecryMinionDamage
    batch_id: int
    first_damage_id: int
    last_damage_id: int
    source: SourceAllocationFact
    victims: tuple[MinionReference, ...]

    def __post_init__(self):
        if type(self.request) is not RepeatBattlecryMinionDamage:
            raise ValueError('Damage continuation requires its complete original request')
        self.request.__post_init__()
        for key in ('batch_id', 'first_damage_id', 'last_damage_id'):
            _integer(getattr(self, key), 'original damage-wave '+key, 1)
        if self.first_damage_id > self.last_damage_id or type(self.source) is not SourceAllocationFact:
            raise ValueError('Damage continuation changed its original result range or source')
        self.source.__post_init__()
        if self.source.kind != CardType.MINION or type(self.victims) is not tuple or not self.victims:
            raise ValueError('Damage wave requires its original physical minion source and nonempty group')
        for victim in self.victims:
            reference_value(victim)
        ids = tuple(v.entity_id for v in self.victims)
        if len(set(ids)) != len(ids) or self.source.entity_id in ids:
            raise ValueError('Damage wave duplicated a victim or included its own carrier')

    def validate_in_state(self, state, registry):
        self.__post_init__()
        record = self.request.validate_in_state(state, registry)
        validate_allocation(state, registry, self.source)
        if self.source.entity_id != record.source_id or self.last_damage_id >= state.next_damage_id:
            raise ValueError('Damage continuation borrowed another source or future result')
        for ref in self.victims:
            entity = state.entities.get(ref.entity_id)
            if (registry.card(ref.card_id).kind != CardType.MINION or entity is None or
                    ref.zone_epoch > entity.zone_epoch or ref.entered_order >= self.source.next_order):
                raise ValueError('Damage wave lost an original physical victim')
        rows = tuple(row for row in state.damage_history
            if row.health_result.batch_id == self.batch_id)
        if tuple(row.id for row in rows) != tuple(range(self.first_damage_id, self.last_damage_id+1)):
            raise ValueError('Damage wave changed its complete original batch result range')
        hits = tuple(row.health_result for row in rows
            if row.health_result.original_flow == HealthFlow.DAMAGE.value and not row.health_result.from_lifesteal)
        if tuple(hit.original_target_id for hit in hits) != tuple(ref.entity_id for ref in self.victims):
            raise ValueError('Damage wave changed its complete ordered original victim group')
        for hit in hits:
            if ((hit.source_id, hit.source_card_id, hit.source_controller, hit.source_zone_epoch,
                    hit.source_entered_order, hit.damage_kind, hit.base_amount, hit.spell_bonus, hit.turn) !=
                    (self.source.entity_id, self.source.card_id, self.source.controller, self.source.zone_epoch,
                     self.source.entered_order, DamageKind.MINION_ABILITY.value, self.request.amount, 0, record.turn)):
                raise ValueError('Damage wave substituted another original source, kind or amount')
        if any(not record.action <= row.action <= state.action_number for row in rows):
            raise ValueError('Damage wave borrowed results outside its original Battlecry')
        return hits


def begin(r, request):
    record = request.validate_in_state(r.state, r.registry)
    victims = tuple(MinionReference.capture(r.state.entities[eid])
        for pid in (record.player_id, 3-record.player_id) for eid in r.player(pid).board
        if eid != record.source_id and r.state.entities[eid].kind == CardType.MINION
        and r.registry.card(r.state.entities[eid].card_id).interactable is None and r.state.entities[eid].active
        and r.state.entities[eid].health > 0 and not r.state.entities[eid].doomed)
    if not victims:
        return ()
    source = SourceAllocationFact.capture(r.state, r.state.entities[record.source_id])
    batch_id = len(r.game._events)+1
    first = r.state.next_damage_id
    from .resolver import settle_health_batch
    work = settle_health_batch(r, tuple(Damage(v.entity_id, request.amount, record.source_id,
        DamageKind.MINION_ABILITY) for v in victims))
    continuation = ContinueBattlecryDamageIfDeaths(request, batch_id, first, r.state.next_damage_id-1, source, victims)
    continuation.validate_in_state(r.state, r.registry)
    return (*work, continuation)


def continue_if_deaths(r, request):
    results = tuple(hit.payload() for hit in request.validate_in_state(r.state, r.registry))
    # Only genuine deaths caused by this original wave count. Other deaths
    # produced by its reactions never turn a nonlethal wave into a repeat.
    killed = any(death.zone == Zone.BOARD and r.registry.card(death.card_id).kind == CardType.MINION and
        death.cause is not None and death.cause.kind in ('damage', 'poison') and death.cause.result in results
        for death in r.state.death_history)
    return (request.request,) if killed else ()


def register(mechanics):
    mechanics.register(RepeatBattlecryMinionDamage, begin)
    mechanics.register(ContinueBattlecryDamageIfDeaths, continue_if_deaths)
