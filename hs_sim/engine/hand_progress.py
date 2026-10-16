"""Hand-zone progress with immutable witnesses and continuous upgrade stages."""
from copy import deepcopy
from dataclasses import dataclass, replace

from .costs import quote_unselected_cost
from .effects import Effect
from .errors import ResolutionError
from .hand_upgrades import upgrade_face
from .lifecycle import refresh_entity
from .model import CardType, Event, HandProgressCandidate, Zone, _int
from .registry import RuleContext


def progress_ability(entity):
    return next((a for a in entity.abilities if a.kind == 'hand_progress'), None)


def identity(entity, ability):
    return HandProgressCandidate(entity.id, ability.id, entity.controller)


def advance_value(ability,key,units=1):
    spec=ability.hand_progress
    _int(units, 'progress increment', 1)
    if spec.amount_basis == 'one' and units != 1:
        raise ValueError('Unit progress advances once per witness')
    # Each actual event can finish at most this stage. Excess is discarded,
    # never forwarded into a newly printed stage or a second completion.
    accepted=min(units,spec.goal-ability.progress_value)
    completed=ability.progress_value+accepted==spec.goal
    return replace(ability,progress_value=0 if completed and spec.repeat else ability.progress_value+accepted,
        consumed=completed and not spec.repeat,progress_completions=ability.progress_completions+int(completed),
        progress_keys=(*ability.progress_keys,key),progress_units=(*ability.progress_units,accepted))


def corrupt_candidates(state, registry, source, quote):
    candidates = []
    for entity_id in state.players[source.controller].hand:
        entity = state.entities[entity_id]
        ability = progress_ability(entity)
        if (entity_id != source.id and ability is not None and not ability.consumed and
                ability.hand_progress.kind == 'corrupt' and quote.amount > quote_unselected_cost(state, registry, entity).amount):
            candidates.append(identity(entity, ability))
    return tuple(candidates)


@dataclass(frozen=True)
class AdvanceHandProgress(Effect):
    candidate: HandProgressCandidate
    event: Event

    def __post_init__(self):
        if type(self.candidate) is not HandProgressCandidate or type(self.event) is not Event:
            raise ValueError('Hand progress requires captured identity and event')
        self.candidate.__post_init__()


def capture_hand_progress(r, event):
    """Original hand listeners precede native deck listeners in physical order."""
    result = []
    for zone in (Zone.HAND, Zone.DECK):
        for player_id in (r.state.active_player, 3-r.state.active_player):
            for entity_id in getattr(r.state.players[player_id], zone.value):
                entity = r.state.entities[entity_id]
                ability = progress_ability(entity)
                if (ability is None or ability.consumed or zone not in ability.hand_progress.zones or
                        ability.hand_progress.event_kind != event.kind):
                    continue
                spec = ability.hand_progress
                candidate = identity(entity, ability)
                if spec.kind == 'corrupt':
                    from .play_history import play_record
                    play_id = dict(event.data).get('play_id')
                    if play_id is None or candidate not in play_record(r.state, play_id).corrupt_candidates:
                        continue
                elif spec.kind == 'infuse' and event.player_id != player_id:
                    continue
                result.append(AdvanceHandProgress(candidate, deepcopy(event)))
    # Original native sources are separate from a transformed face's progress.
    if event.kind == 'turn_started':
        for player_id in (r.state.active_player, 3-r.state.active_player):
            if event.player_id != player_id:
                continue
            for entity_id in r.state.players[player_id].hand:
                entity = r.state.entities[entity_id]
                for ability in entity.abilities:
                    if ability.kind == 'defining_hand_source':
                        r.registry.validate_defining_hand_binding(entity, ability)
                        result.append(AdvanceHandProgress(identity(entity, ability), deepcopy(event)))
    return result


def advance(r, effect):
    candidate = effect.candidate
    entity = r.state.entities.get(candidate.source_id)
    if entity is None or entity.controller != candidate.player_id:
        return
    ability = next((a for a in entity.abilities if a.kind in ('hand_progress', 'defining_hand_source')
                    and a.id == candidate.ability_id), None)
    if ability is None or ability.consumed:
        return
    spec, event = ability.hand_progress, effect.event
    if (entity.zone not in spec.zones or
            entity.id not in getattr(r.state.players[candidate.player_id], entity.zone.value)):
        return
    if event.kind != spec.event_kind:
        return
    if ability.kind == 'defining_hand_source':
        r.registry.validate_defining_hand_binding(entity, ability)
        if event.player_id != entity.controller:
            return
        if event.sequence > len(r.game._events) or r.game._events[event.sequence - 1] != event:
            raise ResolutionError('Defining source requires the actual owner-turn event')
    play = death = cast = None
    if spec.kind == 'corrupt':
        from .play_history import play_record
        play_id = dict(event.data).get('play_id')
        if play_id is None:
            return
        play = play_record(r.state, play_id)
        if not play.completed or candidate not in play.corrupt_candidates:
            return
        key = f'play:{play.id}'
    elif spec.kind == 'infuse':
        death_id = dict(event.data).get('death_id')
        death = next((d for d in r.state.death_history if d.id == death_id), None)
        if (death is None or death.entity_id != event.source_id or death.controller != candidate.player_id or
                death.zone != Zone.BOARD or r.registry.card(death.card_id).kind != CardType.MINION):
            return
        key = f'death:{death.id}'
    elif event.kind == 'spell_cast_accepted':
        from .spell_casts import accepted_cast
        cast = accepted_cast(r.state, event)
        if event.sequence > len(r.game._events) or r.game._events[event.sequence - 1] != event:
            raise ResolutionError('Hand progress requires the actual cast acceptance fact')
        key = f'cast:{cast.id}'
    else:
        key = f'event:{event.sequence}'
    if key in ability.progress_keys:
        return
    context = RuleContext(deepcopy(r.state), entity.id, entity.controller, event.target_id,
                          deepcopy(event), death=death, play=play, trigger=ability, cast=cast)
    eligible = r.registry.trigger_condition(spec.condition_id)(context)
    if type(eligible) is not bool:
        raise ResolutionError('Hand progress condition must return bool')
    if not eligible:
        return
    units = event.amount if spec.amount_basis == 'event_amount' else 1
    if type(units) is not int:
        raise ResolutionError('Hand progress event amount requires an exact integer')
    if units <= 0:
        return
    completed = ability.progress_value + units >= spec.goal
    updated = advance_value(ability,key,units)
    entity.abilities[entity.abilities.index(ability)] = updated
    if completed and spec.upgrade_card_id is not None:
        upgrade_face(r, entity, spec.upgrade_card_id, health_to_durability=spec.health_to_durability,
                     cost_policy=spec.upgrade_cost_policy,
                     spell_to_minion=(entity.kind,r.registry.card(spec.upgrade_card_id).kind)==(CardType.SPELL,CardType.MINION)
                         and spec.kind=='event'and spec.event=='spell_cast_accepted')
        following = progress_ability(entity)
        if following is None:
            entity.abilities.append(updated)
        else:
            # This is one continuous progress chain, not a newly acquired card.
            # Reuse its guarded identity so remaining witnesses in this batch
            # can feed the next stage. External upgrades never do this.
            if following.id == updated.id:
                raise ResolutionError('A progress upgrade must change its printed form')
            updated = replace(following, id=updated.id, progress_completions=updated.progress_completions,
                              progress_keys=updated.progress_keys,progress_units=updated.progress_units)
            entity.abilities[entity.abilities.index(following)] = updated
        r.emit('hand_card_upgraded', target_id=entity.id, player_id=entity.controller)
    refresh_entity(entity)
    if entity.zone == Zone.HAND and ability.kind == 'hand_progress':
        r.emit('hand_progressed', target_id=entity.id, player_id=entity.controller,
               amount=updated.progress_value, progress_kind=spec.kind)
    work = []
    for behavior in (spec.on_progress, spec.on_complete if completed else None):
        if behavior is not None:
            work.append(r.call(behavior, entity.id, entity.controller, event.target_id,
                               event=event, death=death, play=play, trigger=updated, cast=cast))
    return work


def validate_cast_progress(state, ability):
    spec = ability.hand_progress
    if spec.kind != 'event' or spec.event != 'spell_cast_accepted':
        return
    from .spell_casts import cast_record
    for key in ability.progress_keys:
        if not key.startswith('cast:'):
            raise ValueError('Cast progress requires physical cast witnesses')
        record = cast_record(state, int(key[5:]))
        if not record.payload_started or record.failure is not None:
            raise ValueError('Cast progress references an unaccepted physical payload')


def public_progress(entity):
    ability = progress_ability(entity)
    if ability is None or Zone.HAND not in ability.hand_progress.zones:
        return None
    if type(ability.hand_progress.zone) is tuple and entity.zone != Zone.HAND:
        return None
    return {'kind': ability.hand_progress.kind, 'value': ability.progress_value,
            'goal': ability.hand_progress.goal, 'completions': ability.progress_completions,
            'completed': ability.consumed}


def validate_defining_history(game):
    for entity in game._state.entities.values():
        for ability in entity.abilities:
            if ability.kind != 'defining_hand_source':
                continue
            numbers = [int(k.split(':')[1]) for k in ability.progress_keys]
            if any(a >= b for a, b in zip(numbers, numbers[1:])):
                raise ValueError('Defining source requires chronological owner-turn witnesses')
            for number in numbers:
                if number > len(game._events):
                    raise ValueError('Defining source references a missing owner-turn event')
                event = game._events[number - 1]
                if event.kind != 'turn_started' or event.player_id != entity.controller:
                    raise ValueError('Defining source witness is not its owner-turn event')


def register_hand_progress(mechanics):
    mechanics.register(AdvanceHandProgress, advance)
