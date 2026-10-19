"""One native current-board replacement of an already chosen minion destination."""
from dataclasses import dataclass, replace
from random import Random

from .allocation_facts import SourceAllocationFact, validate_allocation
from .construction import integer, name
from .errors import ResolutionError
from .model import AbilityInstance, CardType, Zone, validate_end_turn_rng
from .pools import GenerationContext, PoolMember, PoolQuery, resolve_candidates, sample_candidates

KIND = 'transform_destination_plus_two'
POOL = 'constructed.cards'
EVENT = 'native_transform_replacement_drawn'


@dataclass(frozen=True)
class TransformReplacementDraw:
    source: SourceAllocationFact
    ability: AbilityInstance
    requested_card_id: str
    context: GenerationContext
    pool_version: str
    candidates: tuple[tuple[str, int], ...]
    selected: tuple[str, ...]
    rng_before: tuple
    rng_after: tuple
    turn: int
    action: int
    next_attachment_id: int
    transformation_sequence: int | None = None

    def __post_init__(self):
        if type(self.source) is not SourceAllocationFact or type(self.ability) is not AbilityInstance:
            raise ValueError('Native transformation requires its original source and declaration')
        self.source.__post_init__(); self.ability.__post_init__()
        if (self.source.kind != CardType.MINION or self.source.zone != Zone.BOARD or
                self.ability.kind != 'transform_replacement' or self.ability.native_condition is None or
                self.ability.native_condition.kind != KIND or self.ability.source_id is None
                or self.ability.source_id >= self.source.next_entity_id):
            raise ValueError('Native transformation replaced an unrelated carrier')
        if type(self.context) is not GenerationContext:raise ValueError('Native transformation requires its original context')
        self.context.__post_init__(); name(self.pool_version, 'replacement pool version'); name(self.requested_card_id, 'original destination')
        for field, floor in (('turn', 1), ('action', 0), ('next_attachment_id', 1)):integer(getattr(self, field), field, floor)
        if self.ability.id >= self.next_attachment_id:raise ValueError('Replacement has a future original ability')
        if (type(self.candidates) is not tuple or any(type(row) is not tuple or len(row) != 2 for row in self.candidates)
                or len({row[0] for row in self.candidates}) != len(self.candidates)):
            raise ValueError('Replacement requires complete unique weighted candidates')
        for cid, weight in self.candidates:PoolMember(cid, weight).__post_init__()
        if type(self.selected) is not tuple or len(self.selected) != bool(self.candidates):
            raise ValueError('Replacement lost its one original result')
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)
        local=Random();local.setstate(self.rng_before)
        if (sample_candidates(local,tuple(PoolMember(cid,w) for cid,w in self.candidates),1,replacement=True) != self.selected
                or local.getstate() != self.rng_after):
            raise ValueError('Replacement changed its original integer sample or RNG')
        if self.transformation_sequence is not None:integer(self.transformation_sequence,'replacement transformation',1)
        if not self.selected and self.transformation_sequence is not None:raise ValueError('Empty replacement cannot transform')


def candidates(registry, context, requested):
    if registry.card(requested).kind != CardType.MINION:raise ValueError('Replacement requires a minion destination')
    cost=registry.card(requested).cost+2
    rows=resolve_candidates(registry,context,POOL,PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=cost,max_cost=cost))
    for row in rows:
        card=registry.card(row.card_id)
        if card.kind != CardType.MINION or card.choice_only:raise ResolutionError('Unsupported replacement minion destination')
    return rows


def choose_destination(r, entity, requested):
    from .native_conditions import validate_carrier, matches
    condition=r.registry.card(entity.card_id).native_condition
    rows=tuple(a for a in entity.abilities if a.kind == 'transform_replacement')
    if not rows and (condition is None or condition.kind != KIND):return requested,None
    validate_carrier(r.registry,entity.card_id,entity.kind,entity.abilities,entity.components)
    eligible=tuple(a for a in rows if not a.consumed and matches(r.state,entity,a.native_condition,registry=r.registry))
    if not eligible:return requested,None
    if len(eligible) != 1:raise ResolutionError('Native transformation has duplicate replacement declarations')
    context=r.game._generation_context
    if type(context) is not GenerationContext:raise ResolutionError('Native transformation needs a generation context')
    pool=candidates(r.registry,context,requested.id)
    before=r.game._rng.getstate();selected=sample_candidates(r.game._rng,pool,1,replacement=True);after=r.game._rng.getstate()
    draw=TransformReplacementDraw(SourceAllocationFact.capture(r.state,entity),eligible[0],requested.id,context,
        r.registry.pool(POOL,context).version,tuple((row.card_id,row.weight) for row in pool),selected,before,after,
        r.state.turn,r.state.action_number,r.state.next_attachment_id)
    return (None if not selected else r.registry.card(selected[0])),draw


def record_draw(r, draw, sequence):
    from .continuations import FrameCodec
    draw=replace(draw,transformation_sequence=sequence)
    r.emit(EVENT,source_id=draw.source.entity_id,target_id=draw.source.entity_id,player_id=draw.source.controller,
        draw=FrameCodec(r.game.mechanics,r.registry).encode(draw),_capture=False)


def validate_events(game):
    from .continuations import FrameCodec
    from .native_conditions import validate_carrier
    events=tuple(e for e in game._events if e.kind==EVENT)
    if not events:return
    by_sequence={e.sequence:e for e in game._events}
    codec=None
    for event in events:
        if set(dict(event.data)) != {'draw'}:raise ValueError('Replacement needs its complete private receipt')
        if codec is None:codec=FrameCodec(game.mechanics,game.registry)
        draw=codec.decode(dict(event.data)['draw'])
        if type(draw) is not TransformReplacementDraw:raise ValueError('Replacement has another receipt type')
        draw.__post_init__();validate_allocation(game._state,game.registry,draw.source,closed=True)
        validate_carrier(game.registry,draw.source.card_id,draw.source.kind,(draw.ability,))
        if (draw.turn>game._state.turn or draw.action>game._state.action_number or draw.next_attachment_id>game._state.next_attachment_id
                or (event.source_id,event.target_id,event.player_id,event.action)!=(draw.source.entity_id,draw.source.entity_id,draw.source.controller,draw.action)
                or draw.context != game._generation_context or game.registry.pool(POOL,draw.context).version != draw.pool_version):
            raise ValueError('Replacement changed its original source, context or capture bounds')
        actual=tuple((row.card_id,row.weight) for row in candidates(game.registry,draw.context,draw.requested_card_id))
        if actual != draw.candidates:raise ValueError('Replacement changed the complete original cost tier')
        if draw.selected:
            transformed=by_sequence.get(draw.transformation_sequence)
            if (transformed is None or transformed.kind != 'transformed' or transformed.target_id != draw.source.entity_id
                    or transformed.action != draw.action or transformed.sequence >= event.sequence
                    or dict(transformed.data) != {'old_card_id':draw.source.card_id,'card_id':draw.selected[0]}):
                raise ValueError('Replacement lost its actual one-step transformation')
        elif draw.transformation_sequence is not None:raise ValueError('Empty replacement invented a transformation')


def register(mechanics):mechanics.register_payload_type(TransformReplacementDraw)
