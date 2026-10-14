"""Declaration-specific frozen conditions for actual BC/Combo invocations.

The physical paid root remains unchanged. Generated whole-card roots use their
own acceptance receipt and never fabricate paid-hand position/payment facts.
Other indirect origins require a separately declared condition window.
"""
from dataclasses import dataclass, fields

from .effects import Effect, ChoiceOption, _integer, _player, _behavior
from .errors import ResolutionError


@dataclass(frozen=True)
class BodyPlayReference:
    family: str
    activation_id: int
    source_id: int
    player_id: int
    declaration_card_id: str
    ability_id: int
    play_id: int | None
    physical_child_id: int | None
    outcome_id: int | None
    iteration: int
    repeat_index: int
    indirect_body_id: int | None = None
    historical_body_id: int | None = None

    def __post_init__(self):
        if type(self.family) is not str or self.family not in ('battlecry','combo'):
            raise ValueError('Body condition reference requires an explicit family')
        for name in ('activation_id','source_id','ability_id','iteration','repeat_index'):
            _integer(getattr(self,name),'body condition '+name,1)
        _player(self.player_id);_behavior(self.declaration_card_id)
        for name in ('play_id','physical_child_id','outcome_id','indirect_body_id','historical_body_id'):
            if getattr(self,name) is not None:_integer(getattr(self,name),'body condition '+name,1)
        if sum(value is not None for value in (self.play_id,self.physical_child_id,self.indirect_body_id,self.historical_body_id)) != 1:
            raise ValueError('Body conditions require exactly one actual paid or generated origin or connected indirect origin')
        if self.indirect_body_id is not None and self.family != 'battlecry':
            raise ValueError('The connected indirect producer only accepts Battlecry bodies')
        if self.historical_body_id is not None and self.family != 'battlecry':
            raise ValueError('Historical producer only accepts Battlecry bodies')

    @classmethod
    def capture(cls, context, family):
        from .registry import RuleContext
        if type(context) is not RuleContext or family not in ('battlecry','combo'):
            raise ValueError('Capture requires a body RuleContext and explicit family')
        record=getattr(context,family)
        if record is None or (record.source_id,record.player_id)!=(context.source_id,context.player_id):
            raise ValueError('Body context does not belong to the captured invocation')
        return cls.from_record(record,family)

    @classmethod
    def from_record(cls, record, family):
        from .model import BattlecryRecord, ComboRecord
        expected=BattlecryRecord if family=='battlecry' else ComboRecord if family=='combo' else None
        if type(record) is not expected:raise ValueError('Body reference family and record disagree')
        return cls(family,record.id,record.source_id,record.player_id,record.payload.card_id,
            record.payload.ability_id,record.play_id,record.physical_child_id,record.outcome_id,
            record.iteration,record.repeat_index,getattr(record,'indirect_body_id',None),getattr(record,'historical_body_id',None))


@dataclass(frozen=True)
class BodyPlayConditions:
    combo: bool
    outcast: bool
    finale: bool
    quickdraw: bool
    manathirst: bool
    mana_crystals: int
    manathirst_threshold: int | None

    def __post_init__(self):
        for name in ('combo','outcast','finale','quickdraw','manathirst'):
            if type(getattr(self,name)) is not bool:raise ValueError('Body conditions require explicit booleans')
        _integer(self.mana_crystals,'frozen body mana crystals',0)
        if self.manathirst_threshold is not None:_integer(self.manathirst_threshold,'body threshold',1)
        if self.manathirst!=(self.manathirst_threshold is not None and self.mana_crystals>=self.manathirst_threshold):
            raise ValueError('Body Manathirst differs from its own declaration and accepted crystals')


def invocation(state, registry, reference, *, active=False):
    if type(reference) is not BodyPlayReference:raise ValueError('Expected a captured BodyPlayReference')
    reference.__post_init__()
    if reference.family=='battlecry':
        from .battlecries import battlecry_record, validate_record
        record=battlecry_record(state,reference.activation_id)
    else:
        from .combos import combo_record, validate_record
        record=combo_record(state,reference.activation_id)
    if BodyPlayReference.from_record(record,reference.family)!=reference:
        raise ValueError('Body condition reference changed its original invocation identity')
    validate_record(state,registry,record)
    if active and (record.completed or record.interrupted or getattr(record,'failure',None) is not None
            or not getattr(record,'payload_started',True)):
        raise ValueError('Conditional body effect requires its still-running accepted invocation')
    return record


def body_play_conditions(state, registry, reference):
    record=invocation(state,registry,reference)
    threshold=registry.card(reference.declaration_card_id).manathirst
    if record.play_id is not None:
        from .play_history import play_record
        play=play_record(state,record.play_id)
        combo,outcast,finale,quickdraw=play.combo,play.outcast,play.finale,play.quickdraw
        crystals=play.mana_crystals
    elif record.physical_child_id is not None:
        from .whole_card_physical import child_for
        child=child_for(state,record.physical_child_id);progress=child.physical
        if progress is None or progress.activation is None:
            raise ValueError('Generated body lost its accepted condition receipt')
        receipt=progress.activation
        if (receipt.child_id,receipt.player_id,receipt.source.entity_id)!=(record.physical_child_id,record.player_id,record.source_id):
            raise ValueError('Body conditions borrowed another generated activation')
        combo=receipt.combo;outcast=finale=quickdraw=False;crystals=receipt.max_mana
    elif reference.indirect_body_id is not None:
        from .indirect_body_targets import receipt_for
        return receipt_for(state,record).conditions
    elif reference.historical_body_id is not None:
        from .historical_body_targets import receipt_for
        return receipt_for(state,record).conditions
    else:
        raise ValueError('Indirect body origin has no declared frozen condition window')
    return BodyPlayConditions(combo,outcast,finale,quickdraw,
        threshold is not None and crystals>=threshold,crystals,threshold)


@dataclass(frozen=True)
class IfBodyCondition(Effect):
    body: BodyPlayReference
    condition: str
    when_true: tuple[Effect,...] = ()
    when_false: tuple[Effect,...] = ()

    def __post_init__(self):
        if type(self.body) is not BodyPlayReference:raise ValueError('Conditional body effect requires its typed invocation')
        self.body.__post_init__()
        if type(self.condition) is not str or self.condition not in ('combo','outcast','finale','quickdraw','manathirst'):
            raise ValueError('Unknown body condition')
        for branch in (self.when_true,self.when_false):
            if type(branch) is not tuple or any(not isinstance(e,Effect)for e in branch):
                raise ValueError('Conditional body branches must be immutable effect tuples')


def resolve(r, effect):
    effect.__post_init__()
    try:
        record=invocation(r.state,r.registry,effect.body,active=True)
        facts=body_play_conditions(r.state,r.registry,effect.body)
    except ValueError as exc:
        raise ResolutionError(str(exc))from exc
    accepted=getattr(facts,effect.condition)
    r.emit('body_condition_checked',source_id=record.source_id,player_id=record.player_id,
        family=effect.body.family,body_id=record.id,declaration_card_id=effect.body.declaration_card_id,
        condition=effect.condition,result=accepted)
    return effect.when_true if accepted else effect.when_false


def queued_conditions(value):
    """Walk effect/choice containers only; do not traverse captured state trees."""
    if isinstance(value,IfBodyCondition):yield value
    if isinstance(value,(Effect,ChoiceOption)):
        for field in fields(value):yield from queued_conditions(getattr(value,field.name))
    elif type(value) in (tuple,list):
        for item in value:yield from queued_conditions(item)


def validate_boundary(game):
    if game._frame is None:return
    frame=game._frame
    for effect in queued_conditions((frame.prefix,frame.continuation,frame.options)):
        effect.__post_init__();invocation(game._state,game.registry,effect.body,active=True)
        body_play_conditions(game._state,game.registry,effect.body)


def register(mechanics):
    mechanics.register_payload_type(BodyPlayReference)
    mechanics.register(IfBodyCondition,resolve)
