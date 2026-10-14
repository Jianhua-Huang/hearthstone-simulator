"""Instance-guarded finite triggers, shared by Spellburst, Frenzy and extensions."""
from copy import deepcopy
from dataclasses import dataclass, replace

from .effects import Effect
from .errors import ResolutionError
from .lifecycle import active_abilities, attachment_id, refresh_entity
from .model import AbilityInstance, CardType, Event, Keyword, LimitedTriggerSpec, TriggerCandidate, Zone, _int, _optional_id
from .registry import RuleContext


def supports_carrier(kind, spec):
    """Generic finite text and keyword-specific eligibility stay distinct."""
    if spec.keyword == Keyword.FRENZY:
        return kind == CardType.MINION
    if spec.keyword == Keyword.SPELLBURST:
        return kind in (CardType.MINION, CardType.WEAPON)
    return kind in (CardType.MINION, CardType.WEAPON, CardType.HERO)


def live_source(entity):
    return (entity.active and not entity.doomed and
            ((entity.zone == Zone.BOARD and entity.kind == CardType.MINION and entity.health > 0) or
             (entity.zone == Zone.WEAPON and entity.kind == CardType.WEAPON and entity.durability > 0) or
             (entity.zone == Zone.HERO and entity.kind == CardType.HERO and entity.health > 0)))


def candidate(entity, ability):
    return TriggerCandidate(entity.id, ability.id, entity.controller, entity.entered_order)


def validate_candidates(state, candidates, player_id=None):
    if type(candidates) is not tuple or any(type(c) is not TriggerCandidate for c in candidates):
        raise ValueError('Invalid captured trigger candidates')
    if len({c.ability_id for c in candidates}) != len(candidates):
        raise ValueError('Duplicate captured trigger')
    for value in candidates:
        value.__post_init__()
        if (value.source_id not in state.entities or value.ability_id >= state.next_attachment_id or
                value.entered_order >= state.next_order):
            raise ValueError('Captured trigger has invalid provenance')
        if player_id is not None and value.player_id != player_id:
            raise ValueError('Captured Spellburst belongs to another player')
        if state.entities[value.source_id].kind not in (CardType.MINION, CardType.WEAPON):
            raise ValueError('Captured trigger has an invalid carrier')
        for entity in state.entities.values():
            ability = next((a for a in entity.abilities if a.id == value.ability_id), None)
            if ability is not None and (entity.id != value.source_id or ability.kind != 'limited_trigger' or
                    ability.limited_trigger.keyword != Keyword.SPELLBURST):
                raise ValueError('Captured Spellburst identity does not match its instance')


def spellburst_candidates(state, player_id):
    player=state.players[player_id]
    sources=[*player.board,*([player.weapon_id] if player.weapon_id is not None else [])]
    return tuple(candidate(state.entities[i],a) for i in sources if live_source(state.entities[i])
        for a in active_abilities(state.entities[i],'limited_trigger') if a.limited_trigger.keyword==Keyword.SPELLBURST)


@dataclass(frozen=True)
class CheckLimitedTrigger(Effect):
    candidate: TriggerCandidate
    event: Event
    end_turn_context: RuleContext | None = None
    budget_turn: int | None = None

    def __post_init__(self):
        if type(self.candidate) is not TriggerCandidate or type(self.event) is not Event:
            raise ValueError('Limited trigger check requires captured identity and event')
        self.candidate.__post_init__()
        if self.budget_turn is not None: _int(self.budget_turn, 'captured trigger budget turn', 1)
        if self.end_turn_context is not None:
            context=self.end_turn_context
            if type(context) is not RuleContext or context.end_turn is None:
                raise ValueError('Classified finite trigger requires its end-turn acceptance')
            subject=context.end_turn.subject
            if (context.event!=self.event or subject.ability is None or
                    subject.ability.kind!='limited_trigger' or
                    (subject.source_id,subject.player_id,subject.entered_order,subject.ability.id)!=
                    (self.candidate.source_id,self.candidate.player_id,self.candidate.entered_order,self.candidate.ability_id)):
                raise ValueError('Finite trigger differs from its end-turn subject')


@dataclass(frozen=True)
class GrantLimitedTrigger(Effect):
    target_id: int
    spec: LimitedTriggerSpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _int(self.target_id,'trigger target',1)
        _optional_id(self.source_id,'trigger source');_optional_id(self.expires_turn,'trigger expiry')
        if type(self.spec) is not LimitedTriggerSpec:
            raise ValueError('GrantLimitedTrigger requires a specification')
        self.spec.__post_init__()


def capture(r, entity, ability, event, spell_candidates):
    if not live_source(entity):return None
    spec=ability.limited_trigger
    if spec.event!=event.kind:return None
    identity=candidate(entity,ability)
    play=None
    if (play_id:=dict(event.data).get('play_id')) is not None:
        from .play_history import play_record
        play=play_record(r.state,play_id)
    if spec.keyword==Keyword.SPELLBURST:
        if (identity not in spell_candidates or play is None or play.kind!=CardType.SPELL or
                play.player_id!=entity.controller):return None
    elif spec.keyword==Keyword.FRENZY:
        if event.target_id!=entity.id or event.amount<=0:return None
    context=RuleContext(deepcopy(r.state),entity.id,entity.controller,event.target_id,event,play=play,trigger=ability)
    eligible=r.registry.trigger_condition(spec.condition_id)(context)
    if type(eligible) is not bool:raise ResolutionError('Trigger condition must return bool')
    return CheckLimitedTrigger(identity,event,budget_turn=r.state.turn if spec.reset == 'turn' else None) if eligible else None


def check(r, effect):
    effect.__post_init__()
    def rejected():
        if effect.end_turn_context is not None:
            from .end_turns import skip
            skip(r,effect.end_turn_context.end_turn)
    identity=effect.candidate;entity=r.state.entities.get(identity.source_id)
    if (entity is None or not live_source(entity) or entity.controller!=identity.player_id or
            entity.entered_order!=identity.entered_order):return rejected()
    ability=next((a for a in active_abilities(entity,'limited_trigger') if a.id==identity.ability_id),None)
    if ability is None:return rejected()
    if effect.budget_turn != (r.state.turn if ability.limited_trigger.reset == 'turn' else None):
        return rejected()
    if effect.end_turn_context is not None and ability!=effect.end_turn_context.end_turn.subject.ability:
        # Another accepted end-turn root may have spent this exact attachment.
        # The old queued guard cannot borrow its newer consumption window.
        return rejected()
    updated=replace(ability,uses_remaining=ability.uses_remaining-1,consumed=ability.uses_remaining==1)
    entity.abilities[entity.abilities.index(ability)]=updated
    refresh_entity(entity)
    guard=effect.end_turn_context.end_turn if effect.end_turn_context is not None else None
    guard_data={'end_turn_guard_id':guard.id,'end_turn_ability_id':ability.id} if guard else {}
    r.emit('limited_trigger_used',source_id=entity.id,player_id=entity.controller,
           amount=updated.uses_remaining,trigger_keyword=ability.limited_trigger.keyword.value if ability.limited_trigger.keyword else None,
           _end_turn_guard=guard,**guard_data)
    call=r.call(ability.limited_trigger.behavior_id,entity.id,entity.controller,
                effect.event.target_id,event=effect.event,trigger=updated,
                end_turn=effect.end_turn_context.end_turn if effect.end_turn_context else None)
    if effect.end_turn_context is not None:
        from .end_turns import InvokeEndTurn
        return [InvokeEndTurn(call.context,effect.end_turn_context)]
    return [call]


def grant(r, effect):
    r.registry.validate_limited_trigger(effect.spec)
    entity=r.state.entities.get(effect.target_id)
    if entity is None or not live_source(entity):return
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Unknown limited trigger source')
    if effect.spec.keyword==Keyword.FRENZY and entity.kind!=CardType.MINION:
        raise ResolutionError('Frenzy requires a minion')
    if not supports_carrier(entity.kind,effect.spec):
        raise ResolutionError('Spellburst requires a minion or weapon')
    if effect.expires_turn is not None and effect.expires_turn<r.state.turn:
        raise ResolutionError('Limited trigger already expired')
    entity.abilities.append(AbilityInstance(attachment_id(r.state),'limited_trigger',source_id=effect.source_id,
        limited_trigger=effect.spec,uses_remaining=effect.spec.uses,expires_turn=effect.expires_turn,
        trigger_turn=r.state.turn if effect.spec.reset == 'turn' else None))
    refresh_entity(entity)
    r.emit('ability_granted',source_id=effect.source_id,target_id=entity.id,ability_kind='limited_trigger')


def refresh_turn_budgets(state):
    """Each actual new turn refreshes each physical attachment independently."""
    for entity in state.entities.values():
        changed = False
        for i, ability in enumerate(entity.abilities):
            if (ability.kind == 'limited_trigger' and ability.limited_trigger.reset == 'turn' and
                    ability.trigger_turn != state.turn):
                entity.abilities[i] = replace(ability, uses_remaining=ability.limited_trigger.uses,
                    consumed=False, trigger_turn=state.turn)
                changed = True
        if changed: refresh_entity(entity)


def public_triggers(entity):
    return [{'keyword':a.limited_trigger.keyword.value if a.limited_trigger.keyword else None,
             'uses_remaining':a.uses_remaining} for a in entity.abilities if a.kind=='limited_trigger']


def register_limited_triggers(mechanics):
    mechanics.register(CheckLimitedTrigger,check)
    mechanics.register(GrantLimitedTrigger,grant)
