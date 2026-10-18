"""Actual card creation results shared by Battlecry and independent Combo.

No hand search or entity-allocation cursor reconstructs the recipient. Pool
selection, creation and stored Attack changes keep their existing executors.
The last matching Battlecry and original-hand residency are local CN policies.
"""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import AddToHand, Effect, _integer
from .model import CardType, Zone
from .pools import GenerateFromCandidates, GenerateFromPool
from .serialization import canonical_hash
from .zones import CardReference

EVENT = 'battlecry_weapon_bound'


@dataclass(frozen=True)
class BattlecryWeaponOutput:
    id: int
    battlecry_id: int
    created: SourceAllocationFact | None
    event_cursor: int

    def __post_init__(self):
        for field in ('id', 'battlecry_id', 'event_cursor'):
            _integer(getattr(self, field), field, 1)
        if self.created is not None:
            if type(self.created) is not SourceAllocationFact:
                raise ValueError('Weapon output requires its actual physical creation fact')
            self.created.__post_init__()
            if self.created.kind not in (CardType.WEAPON, CardType.SPELL) or self.created.zone not in (Zone.HAND, Zone.GRAVEYARD):
                raise ValueError('Weapon output must record its original hand delivery or burn')


# Retain the existing record and wire names; there is only one output journal.
BattlecryCardOutput = BattlecryWeaponOutput


@dataclass(frozen=True)
class GenerateBattlecryCard(Effect):
    battlecry_id: int
    request: GenerateFromPool | GenerateFromCandidates

    def __post_init__(self):
        _integer(self.battlecry_id, 'original Battlecry', 1)
        request = self.request
        if type(request) not in (GenerateFromPool, GenerateFromCandidates):
            raise ValueError('Card output requires an ordinary pool or finite generation request')
        request.__post_init__()
        if request.source_id is None:
            raise ValueError('Card output requires its original Battlecry source')
        if type(request) is GenerateFromCandidates:
            return
        if (request.count != 1 or not request.replacement or
                request.destination != 'hand' or request.query.kinds not in ((CardType.WEAPON,), (CardType.SPELL,)) or
                request.query.collectible is not True or any(v is not None for v in (
                    request.cost, request.expires_turn, request.spell_repeat, request.cause,
                    request.producer_profile_id, request.temporary_until_turn, request.board_position,
                    request.minion_stats, request.shuffle_actor_id, request.entry_grant,
                    request.minion_grant)) or request.combined_shatter):
            raise ValueError('Card output supports one plain source-bound collectible weapon or spell')


@dataclass(frozen=True)
class GenerateBattlecryWeapon(GenerateBattlecryCard):
    """Compatibility entry point; its weapon-only contract remains strict."""
    def __post_init__(self):
        super().__post_init__()
        if type(self.request) is not GenerateFromPool or self.request.query.kinds != (CardType.WEAPON,):
            raise ValueError('Weapon output requires its ordinary weapon pool request')


def validate_work(effect, registry, state=None):
    effect.__post_init__()
    if type(effect.request) is GenerateFromCandidates:
        kinds = {registry.card(cid).kind for cid in effect.request.card_ids}
        if len(kinds) != 1 or not kinds.issubset((CardType.WEAPON, CardType.SPELL)):
            raise ValueError('A bound finite output requires one weapon or spell kind')
    if state is None:
        return
    from .battlecries import battlecry_record, validate_record
    record = battlecry_record(state, effect.battlecry_id)
    validate_record(state, registry, record)
    if (record.completed or record.interrupted or record.failure is not None or not record.payload_started or
            (record.source_id, record.player_id) != (effect.request.source_id, effect.request.player_id)):
        raise ValueError('Weapon creation lost its actual active Battlecry')
    if any(o.battlecry_id == record.id for o in state.battlecry_weapon_outputs):
        raise ValueError('This Battlecry already delivered its one weapon output')


def generate(r, effect):
    from .opening import create_hand_card
    from .pools import generate_from_candidates, generate_from_pool
    validate_work(effect, r.registry, r.state)
    # The ordinary generator validates every eligible member and samples once.
    # Its one selected AddToHand is materialized by the shared creation helper,
    # which returns the actual entity before queued reactions can change it.
    generator = generate_from_candidates if type(effect.request) is GenerateFromCandidates else generate_from_pool
    work = generator(r, effect.request)
    if len(work) > 1 or any(type(w) is not AddToHand for w in work):
        raise ValueError('Weapon generator returned another delivery protocol')
    entity = create_hand_card(r, work[0]) if work else None
    created = SourceAllocationFact.capture(r.state, entity) if entity is not None else None
    row = BattlecryWeaponOutput(len(r.state.battlecry_weapon_outputs) + 1,
        effect.battlecry_id, created, len(r.game._events) + 1)
    r.state.battlecry_weapon_outputs.append(row)
    r.emit(EVENT, source_id=effect.request.source_id, target_id=None if entity is None else entity.id,
           player_id=effect.request.player_id, output_id=row.id, battlecry_id=row.battlecry_id,
           created=None if created is None else created.payload())
    return ()


def validate_history(state, registry):
    from .battlecries import battlecry_record
    if type(state.battlecry_weapon_outputs) is not list:
        raise ValueError('Battlecry weapon outputs require their ordered original journal')
    seen = set()
    previous = 0
    for index, row in enumerate(state.battlecry_weapon_outputs, 1):
        if type(row) is not BattlecryWeaponOutput:
            raise ValueError('Unknown Battlecry weapon output')
        row.__post_init__()
        record = battlecry_record(state, row.battlecry_id)
        if row.id != index or row.battlecry_id in seen or row.event_cursor <= previous:
            raise ValueError('Battlecry weapon outputs changed their original order or uniqueness')
        if record.failure is not None or not record.payload_started:
            raise ValueError('Disabled Battlecry cannot have a weapon output')
        if row.created is not None:
            validate_allocation(state, registry, row.created)
            if (row.created.owner, row.created.controller) != (record.player_id, record.player_id):
                raise ValueError('Weapon output changed its original receiving player')
        previous = row.event_cursor; seen.add(row.battlecry_id)


def validate_events(game):
    from .hero_health_history import effective_events
    rows = game._state.battlecry_weapon_outputs
    events = tuple(effective_events(game._events))
    bound = tuple(e for e in events if e.kind == EVENT)
    if tuple(e.sequence for e in bound) != tuple(row.event_cursor for row in rows):
        raise ValueError('Weapon output journal differs from its actual effective events')
    for row, event in zip(rows, bound):
        record = game._state.battlecry_history[row.battlecry_id - 1]
        expected = dict(output_id=row.id, battlecry_id=row.battlecry_id,
                        created=None if row.created is None else row.created.payload())
        target = None if row.created is None else row.created.entity_id
        if ((event.source_id, event.player_id, event.target_id) != (record.source_id, record.player_id, target) or
                canonical_hash(dict(event.data)) != canonical_hash(expected)):
            raise ValueError('Weapon output changed its actual creation binding')
        starts = [e.sequence for e in events if e.kind == 'battlecry_started' and
                  dict(e.data).get('battlecry_id') == row.battlecry_id]
        ends = [e.sequence for e in events if e.kind == 'battlecry_finished' and
                dict(e.data).get('battlecry_id') == row.battlecry_id]
        if len(starts) != 1 or starts[0] >= event.sequence or any(e <= event.sequence for e in ends):
            raise ValueError('Weapon creation is outside its original Battlecry window')


def combo_card(context, registry, *, kind):
    """The last matching native Battlecry in this exact physical body/result."""
    if kind not in (CardType.WEAPON, CardType.SPELL):
        raise ValueError('Combo output requires its declared weapon or spell kind')
    from .combos import combo_record
    combo = context.combo
    if combo is None or combo != combo_record(context.state, combo.id):
        raise ValueError('Weapon reward requires its actual independent Combo')
    matches = []
    for record in context.state.battlecry_history:
        if ((record.source_id, record.player_id, record.payload.card_id, record.outcome_id, record.iteration) !=
                (combo.source_id, combo.player_id, combo.payload.card_id, combo.outcome_id, combo.iteration)):
            continue
        same_body = (record.origin == 'hand' and record.play_id == combo.play_id
                     if combo.physical_child_id is None else record.physical_child_id == combo.physical_child_id)
        if same_body and record.completed and not record.interrupted and record.failure is None and record.payload_started:
            matches.append(record)
    if not matches:
        return None
    original = matches[-1]
    outputs = [o for o in context.state.battlecry_weapon_outputs if o.battlecry_id == original.id]
    if len(outputs) != 1:
        raise ValueError('Combo lost the matching Battlecry original weapon output')
    created = outputs[0].created
    if created is not None and created.kind != kind:
        raise ValueError('Combo output changed its declared original card kind')
    if created is None or created.zone != Zone.HAND:
        return None
    return CardReference(created.entity_id, combo.player_id, Zone.HAND, created.card_id, created.zone_epoch)


def combo_weapon(context, registry):
    return combo_card(context, registry, kind=CardType.WEAPON)


def validate_context(context, state, events):
    if context.combo is None or not (state.battlecry_weapon_outputs or context.state.battlecry_weapon_outputs):
        return
    from .hero_health_history import effective_events
    starts = [e.sequence for e in effective_events(events) if e.kind == 'combo_started' and
              dict(e.data).get('combo_id') == context.combo.id]
    if len(starts) != 1:
        raise ValueError('Combo weapon context lost its actual start event')
    expected = [o for o in state.battlecry_weapon_outputs if o.event_cursor < starts[0]]
    if context.state.battlecry_weapon_outputs != expected:
        raise ValueError('Combo context changed its complete original weapon-output prefix')


def from_dict(value):
    if type(value) is not dict or set(value) != {'id', 'battlecry_id', 'created', 'event_cursor'}:
        raise ValueError('Invalid Battlecry weapon-output fields')
    row = dict(value)
    if row['created'] is not None:
        row['created'] = allocation_from_dict(row['created'])
    return BattlecryWeaponOutput(**row)


def register(mechanics):
    mechanics.register_payload_type(BattlecryWeaponOutput)
    mechanics.register(GenerateBattlecryCard, generate)
    mechanics.register(GenerateBattlecryWeapon, generate)
