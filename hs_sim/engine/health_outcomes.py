"""Captured numeric health results and shared keyword predicates (R-109).

Results describe each settled packet, before later packets/reactions can change
its target. They are immutable event payloads, not a second mutable health ledger.
"""
from dataclasses import dataclass, fields

from .model import CardType, DamageKind, Event, HealingKind, HealthFlow, HealthFloorPlan, _int, _name, _optional_id
from .random_split_damage import SplitPacketLink


@dataclass(frozen=True)
class PlayerHealthOrigin:
    player_id: int
    instance_id: int
    spec_id: str

    def __post_init__(self):
        _int(self.player_id, 'logical health player', 1)
        if self.player_id not in (1, 2): raise ValueError('Unknown logical health player')
        _int(self.instance_id, 'logical health effect instance', 1)
        _name(self.spec_id, 'logical health program')

    def payload(self):
        return tuple((f.name, getattr(self, f.name)) for f in fields(self))


def player_origin_from_payload(raw):
    if raw is None: return None
    if (type(raw) is not tuple or len(raw) != 3 or
            any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str for row in raw) or
            set(dict(raw)) != {'player_id', 'instance_id', 'spec_id'}):
        raise ValueError('Logical health origin requires its complete frozen fields')
    return PlayerHealthOrigin(**dict(raw))


@dataclass(frozen=True)
class HealthResult:
    batch_id: int
    packet_index: int
    turn: int
    active_player: int
    source_id: int | None
    source_card_id: str | None
    source_controller: int | None
    source_zone_epoch: int | None
    source_entered_order: int | None
    weapon_id: int | None
    weapon_zone_epoch: int | None
    weapon_entered_order: int | None
    target_id: int
    target_card_id: str
    target_controller: int
    target_kind: str
    target_zone_epoch: int
    target_entered_order: int
    original_target_id: int
    original_flow: str
    flow: str
    damage_kind: str
    healing_kind: str
    base_amount: int
    modified_amount: int
    spell_bonus: int
    rule_ids: tuple[int, ...]
    redirect_path: tuple[int, ...]
    health_before: int
    max_health: int
    armor_before: int
    doomed_before: bool
    health_after: int
    max_health_after: int
    armor_after: int
    doomed_after: bool
    damage_dealt: int = 0
    armor_absorbed: int = 0
    health_lost: int = 0
    health_gained: int = 0
    health_replaced: int = 0
    healed: int = 0
    overheal: int = 0
    prevention: str | None = None
    converted: bool = False
    from_lifesteal: bool = False
    floor_plan: HealthFloorPlan | None = None
    floor_prevented: int = 0
    split_packet: SplitPacketLink | None = None
    player_origin: PlayerHealthOrigin | None = None

    def __post_init__(self):
        if self.player_origin is not None:
            if type(self.player_origin) is not PlayerHealthOrigin:
                raise ValueError('Logical health result requires its typed origin')
            self.player_origin.__post_init__()
            if (self.source_controller != self.player_origin.player_id or self.source_id is None or
                    self.original_flow != HealthFlow.DAMAGE.value or self.damage_kind != DamageKind.EFFECT.value or
                    self.from_lifesteal or self.weapon_id is not None):
                raise ValueError('Logical health result changed its original producer policy')
        for name in ('batch_id', 'packet_index', 'turn', 'target_id', 'original_target_id'):
            _int(getattr(self, name), name, 1)
        for name in ('target_zone_epoch', 'target_entered_order', 'base_amount', 'modified_amount', 'spell_bonus', 'max_health', 'max_health_after',
                     'armor_before', 'armor_after', 'damage_dealt', 'armor_absorbed', 'health_lost',
                     'health_gained', 'health_replaced', 'healed', 'overheal', 'floor_prevented'):
            _int(getattr(self, name), name, 0)
        for name in ('health_before', 'health_after'): _int(getattr(self, name), name)
        for name in ('doomed_before', 'doomed_after', 'converted', 'from_lifesteal'):
            if type(getattr(self, name)) is not bool: raise ValueError('Health result flags must be boolean')
        for name in ('active_player', 'target_controller'):
            if type(getattr(self, name)) is not int or getattr(self, name) not in (1, 2):
                raise ValueError('Invalid health result player')
        _name(self.target_card_id, 'health result target card')
        if self.target_kind not in (CardType.HERO.value, CardType.MINION.value):
            raise ValueError('Health result requires a character target')
        for name in ('original_flow', 'flow'): HealthFlow(getattr(self, name))
        DamageKind(self.damage_kind); HealingKind(self.healing_kind)
        if self.split_packet is not None:
            if type(self.split_packet) is not SplitPacketLink:
                raise ValueError('Health result requires exact split packet linkage')
            self.split_packet.__post_init__()
            if (self.damage_kind not in
                    (DamageKind.SPELL.value,DamageKind.MINION_ABILITY.value,DamageKind.EFFECT.value) or
                    self.base_amount != 1 or self.spell_bonus != 0 or self.from_lifesteal or
                    self.original_flow == HealthFlow.HEALING.value and (
                        self.healing_kind != HealingKind.SPELL.value or self.damage_kind != DamageKind.SPELL.value)):
                raise ValueError('Split health result is not its one original quoted unit')
        if self.converted != (self.original_flow != self.flow):
            raise ValueError('Health result conversion disagrees with its flow')
        source = (self.source_card_id, self.source_controller, self.source_zone_epoch, self.source_entered_order)
        if self.source_id is None:
            if any(v is not None for v in source): raise ValueError('Source-less result has source metadata')
        else:
            _int(self.source_id, 'health result source', 1); _name(self.source_card_id, 'source card')
            if type(self.source_controller) is not int or self.source_controller not in (1, 2):
                raise ValueError('Invalid health result source controller')
            _int(self.source_zone_epoch, 'source epoch', 0); _int(self.source_entered_order, 'source order', 0)
        _optional_id(self.weapon_id, 'health result weapon')
        if self.weapon_id is None:
            if self.weapon_zone_epoch is not None or self.weapon_entered_order is not None:
                raise ValueError('Weapon metadata has no weapon')
        else:
            _int(self.weapon_zone_epoch, 'weapon epoch', 0); _int(self.weapon_entered_order, 'weapon order', 1)
            if self.source_id is None or self.damage_kind != DamageKind.COMBAT.value:
                raise ValueError('Only combat packets can attribute equipped weapon damage')
        for name in ('rule_ids', 'redirect_path'):
            value = getattr(self, name)
            if type(value) is not tuple or len(set(value)) != len(value):
                raise ValueError('Invalid health result routing metadata')
            for item in value: _int(item, name, 1)
        if self.redirect_path and (self.redirect_path[0] != self.original_target_id or self.redirect_path[-1] != self.target_id):
            raise ValueError('Health result routing endpoints disagree')
        if self.prevention not in (None, 'rule_prevention', 'zero_damage', 'immune', 'divine_shield'):
            raise ValueError('Invalid health result prevention')
        if self.prevention in ('zero_damage', 'rule_prevention') and self.modified_amount != 0:
            raise ValueError('Zero or rule prevention requires a zero modified budget')
        if self.prevention in ('immune', 'divine_shield') and (
                self.modified_amount <= 0 or self.flow != HealthFlow.DAMAGE.value):
            raise ValueError('Immunity or shield prevention requires positive damage budget')
        if self.prevention == 'zero_damage' and self.flow != HealthFlow.DAMAGE.value:
            raise ValueError('Zero damage prevention requires damage flow')
        if self.health_before > self.max_health or self.health_after > self.max_health_after:
            raise ValueError('Health result exceeds maximum health')
        from .health_floors import validate_result_numbers
        validate_result_numbers(self)
        if self.prevention:
            if any((self.damage_dealt, self.armor_absorbed, self.health_lost, self.health_gained, self.health_replaced, self.healed, self.overheal)):
                raise ValueError('Prevented health result has numeric effects')
            if (self.health_before, self.armor_before, self.doomed_before) != (self.health_after, self.armor_after, self.doomed_after):
                raise ValueError('Prevented health result changed target')
        elif self.flow == HealthFlow.DAMAGE.value:
            if (self.healed or self.overheal or self.damage_dealt+self.floor_prevented != self.modified_amount or
                    self.armor_before-self.armor_after != self.armor_absorbed or
                    self.health_before-self.health_after != self.health_lost-self.health_gained or
                    self.damage_dealt != self.armor_absorbed+self.health_lost+self.health_replaced):
                raise ValueError('Damage result numbers disagree')
        else:
            if (any((self.damage_dealt, self.armor_absorbed, self.health_lost, self.health_replaced)) or
                    self.armor_before != self.armor_after or self.health_after-self.health_before != self.healed or self.health_gained != self.healed or
                    self.healed != min(self.max_health-self.health_before, self.modified_amount) or
                    self.healed+self.overheal != self.modified_amount):
                raise ValueError('Healing result numbers disagree')

    def payload(self):
        from .health_floors import plan_payload
        return tuple((f.name, plan_payload(self.floor_plan) if f.name == 'floor_plan' else
            self.player_origin.payload() if f.name == 'player_origin' and self.player_origin is not None else
            tuple((v.name,getattr(self.split_packet,v.name)) for v in fields(self.split_packet)) if f.name=='split_packet' and self.split_packet is not None else getattr(self, f.name)) for f in fields(self))


def result_from_payload(raw):
    """Shared strict decoder for event and persistent fatal-result payloads."""
    if type(raw) is not tuple:
        raise ValueError('Health result must be frozen')
    if any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str for row in raw):
        raise ValueError('Invalid frozen health result fields')
    values = dict(raw)
    if len(values) != len(raw) or set(values) != {f.name for f in fields(HealthResult)}:
        raise ValueError('Health result requires exactly its declared fields')
    from .health_floors import plan_from_payload
    values['floor_plan'] = plan_from_payload(values['floor_plan'])
    values['player_origin'] = player_origin_from_payload(values['player_origin'])
    if values['split_packet'] is not None:
        raw_link=values['split_packet']
        if type(raw_link) is not tuple or len(raw_link)!=2 or set(dict(raw_link))!={'root_id','index'}:
            raise ValueError('Split result link requires exactly its declared frozen fields')
        values['split_packet']=SplitPacketLink(**dict(raw_link))
    return HealthResult(**values)


def health_result(event):
    """Decode/validate a result; unrelated events have no health result."""
    if event is None: return None
    if type(event) is not Event: raise ValueError('Health result requires Event')
    if event.kind != 'health_resolved': return None
    data = dict(event.data)
    if len(data) != len(event.data) or set(data) not in (
            {'result'}, {'result', 'hero_health_transition', 'hero_health_change_id'}):
        raise ValueError('Health event requires exactly one frozen result')
    result = result_from_payload(data['result'])
    if (result.target_kind == CardType.HERO.value) != ('hero_health_transition' in data):
        raise ValueError('Health event lost its original hero transition envelope')
    if result.target_kind == CardType.HERO.value:
        from .hero_health_history import validate_transition
        value = validate_transition(data['hero_health_transition'])
        if value != (result.target_controller, result.target_id, result.target_card_id,
                result.health_before, result.max_health, result.target_id, result.target_card_id,
                result.health_after, result.max_health_after):
            raise ValueError('Hero transition differs from its original health result')
        change_id = data['hero_health_change_id']
        if result.health_before == result.health_after:
            if change_id is not None: raise ValueError('Unchanged health result invented a hero change')
        else:
            _int(change_id, 'health result hero change identity', 1)
    if ((event.source_id, event.target_id, event.player_id, event.amount) !=
            (result.source_id, result.target_id, result.target_controller, result.damage_dealt or result.healed) or
            result.batch_id > event.sequence):
        raise ValueError('Health event and captured result disagree')
    return result


def _kill_result(event, source_id):
    return _kill_result_value(health_result(event), source_id)


def _kill_result_value(result, source_id):
    _int(source_id, 'result condition source', 1)
    if (result is None or result.flow != HealthFlow.DAMAGE.value or result.prevention or
            source_id not in (result.source_id, result.weapon_id) or
            result.active_player != result.source_controller or result.health_before <= 0 or
            result.doomed_before or result.health_after > 0 or result.health_lost <= 0):
        return None
    return result


def is_overkill(event, source_id):
    result = _kill_result(event, source_id)
    return result is not None and result.health_lost > result.health_before


def is_honorable_kill(event, source_id):
    result = _kill_result(event, source_id)
    return (result is not None and result.target_controller != result.source_controller and
            result.health_lost == result.health_before)


def is_overheal(event, target_id):
    _int(target_id, 'result condition target', 1)
    result = health_result(event)
    return (result is not None and result.target_id == target_id and result.flow == HealthFlow.HEALING.value
            and result.prevention is None and result.health_before > 0 and not result.doomed_before and result.overheal > 0)


def capture_result(state, packet, target, before, batch_id, packet_index, combat, *,
                   damage=None, healed=0, replaced=0, prevention=None):
    """Called only by the mutating resolver, immediately after one packet settles."""
    source = state.entities.get(packet.source_id)
    split_source = packet.split_quote.source if packet.split_quote is not None else None
    original_source=packet.player_source or split_source
    weapon = (state.entities.get(combat.weapon_id) if combat is not None and
              combat.attacker_id == packet.source_id and packet.damage_kind == DamageKind.COMBAT else None)
    value = HealthResult(batch_id=batch_id, packet_index=packet_index, turn=state.turn, active_player=state.active_player,
        source_id=packet.source_id, source_card_id=original_source.card_id if original_source else source.card_id if source else None, source_controller=packet.source_controller,
        source_zone_epoch=original_source.zone_epoch if original_source else source.zone_epoch if source else None, source_entered_order=original_source.entered_order if original_source else source.entered_order if source else None,
        weapon_id=weapon.id if weapon else None, weapon_zone_epoch=weapon.zone_epoch if weapon else None,
        weapon_entered_order=weapon.entered_order if weapon else None, target_id=target.id, target_card_id=target.card_id,
        target_controller=target.controller, target_kind=target.kind.value, target_zone_epoch=target.zone_epoch,
        target_entered_order=target.entered_order, original_target_id=packet.original_target_id,
        original_flow=packet.original_flow.value, flow=packet.flow.value, damage_kind=packet.damage_kind.value,
        healing_kind=packet.healing_kind.value, base_amount=packet.base_amount, modified_amount=packet.amount,
        spell_bonus=packet.spell_bonus, rule_ids=packet.rule_ids, redirect_path=packet.redirect_path,
        health_before=before.health, max_health=before.max_health, armor_before=before.armor, doomed_before=before.doomed,
        health_after=target.health, max_health_after=target.max_health, armor_after=target.armor, doomed_after=target.doomed,
        damage_dealt=damage.dealt if damage else 0, armor_absorbed=damage.armor_absorbed if damage else 0,
        health_lost=max(0, before.health-target.health), health_gained=max(0, target.health-before.health), health_replaced=replaced, healed=healed,
        overheal=max(0, packet.amount-healed) if packet.flow == HealthFlow.HEALING and not prevention else 0,
        prevention=prevention, converted=packet.converted, from_lifesteal=packet.from_lifesteal,
        floor_plan=packet.floor_plan, floor_prevented=damage.floor_prevented if damage else 0, split_packet=packet.split_packet,
        player_origin=player_origin_from_payload(packet.player_origin))
    return dict(source_id=value.source_id, target_id=value.target_id, player_id=value.target_controller,
                amount=value.damage_dealt or value.healed, result=value.payload())


def validate_player_origin(state, result, registry=None):
    origin = result.player_origin
    if origin is None: return
    origin.__post_init__()
    if origin.instance_id >= state.next_attachment_id:
        raise ValueError('Logical health result borrowed a future program instance')
    if registry is not None: registry.player_effect(origin.spec_id)
    for player in state.players.values():
        current = next((e for e in player.player_effects if e.id == origin.instance_id), None)
        if current is None: continue
        if (player.id != origin.player_id or current.spec_id != origin.spec_id or
                current.source_player_id != origin.player_id or current.source_id != result.source_id or
                current.created_turn > result.turn or current.source_allocation is None):
            raise ValueError('Logical health result changed its original program binding')
        from .allocation_facts import allocation_from_payload
        fact = allocation_from_payload(current.source_allocation)
        if (fact.card_id, fact.zone_epoch, fact.entered_order) != (
                result.source_card_id, result.source_zone_epoch, result.source_entered_order):
            raise ValueError('Logical health result changed its original physical source capture')
