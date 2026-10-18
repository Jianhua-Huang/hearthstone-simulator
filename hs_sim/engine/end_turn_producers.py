"""Structural carrier queries and one random end-turn activation.

Candidate presence never runs body conditions. Selection and the accepted body
plans share one handler window; additional executions do not sample again.
"""
from dataclasses import dataclass
from dataclasses import replace
import random

from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .model import (CardType, Event, EndTurnCarrier, EndTurnProducerRequest,
                    EndTurnRequest, EndTurnSelection, EndTurnSelector)


KINDS = {CardType.MINION: 'minion', CardType.WEAPON: 'weapon',
         CardType.HERO_POWER: 'hero_power', CardType.LOCATION: 'location', CardType.HERO: 'hero'}


def end_turn_carriers(state, registry, selector, profile_id='end_turn.candidates'):
    """Trusted-host pure query; one row per in-scope physical carrier.

Current identity sees classified surviving attachments; printed identity sees
the current physical card's definition, without borrowing magnetic components.
Active identity sees lifecycle-active, unconsumed attachments. None of these
queries evaluate EndTurnSpec or finite trigger conditions.
    """
    from .end_turns import listeners
    from .lifecycle import active_abilities
    if type(selector) is not EndTurnSelector:
        raise ValueError('End-turn candidates require EndTurnSelector')
    selector.__post_init__()
    profile = registry.end_turn_candidate_profile(profile_id)
    if any(i not in state.entities for i in selector.entity_ids):
        raise ResolutionError('Unknown selected end-turn candidate')
    if any(i >= state.next_attachment_id for i in selector.player_effect_ids):
        raise ResolutionError('Unknown selected end-turn candidate instance')
    rows = []
    seen = set()
    for owner, order, source_id, instance in listeners(state):
        entity = state.entities[source_id]
        kind = 'player_effect' if instance is not None else KINDS.get(entity.kind)
        if owner not in selector.player_ids or kind not in selector.carrier_kinds:
            continue
        if selector.mode == 'selected' and (instance.id not in selector.player_effect_ids
                if instance is not None else source_id not in selector.entity_ids):
            continue
        if instance is not None:
            # The live instance is the carrier, independently of its source's
            # present zone, type, health, dormancy or printed card declarations.
            spec = registry.player_effect(instance.spec_id)
            present = any(t.end_turn is not None for t in spec.triggers)
            if profile.dormant == 'only':
                continue
            row = EndTurnCarrier(kind, source_id, owner, instance.source_card_id,
                                 order, entity.zone_epoch, instance)
        else:
            dormant = entity.dormancy is not None
            if (profile.dormant == 'exclude' and dormant or
                    profile.dormant == 'only' and not dormant):
                continue
            if profile.live_only and (entity.doomed or
                    entity.kind in (CardType.MINION,CardType.HERO) and entity.health <= 0 or
                    entity.kind in (CardType.WEAPON, CardType.LOCATION) and entity.durability <= 0):
                continue
            definition = registry.card(entity.card_id)
            if profile.basis == 'printed':
                present = any(t.end_turn is not None for t in
                              (*definition.triggers, *definition.dormant_triggers,
                               *definition.limited_triggers))
            else:
                abilities = entity.abilities if profile.basis == 'current' else (
                    *active_abilities(entity, 'trigger'),
                    *active_abilities(entity, 'dormant_trigger'),
                    *active_abilities(entity, 'limited_trigger'))
                present = any(a.end_turn_spec is not None and
                              (profile.consumed == 'include' or not a.consumed)
                              for a in abilities)
            row = EndTurnCarrier(kind, source_id, owner, entity.card_id,
                                 order, entity.zone_epoch)
        if (profile.presence == 'has_body' and not present or
                profile.presence == 'lacks_body' and present):
            continue
        if row.key not in seen:
            registry.card(row.card_id)
            seen.add(row.key)
            rows.append(row)
    return tuple(rows)


def selected_request(selection):
    """Resolve one carrier while retaining the original candidate request."""
    request = selection.request
    chosen = selection.selected
    return EndTurnRequest(EndTurnSelector('selected', request.selector.player_ids,
        request.selector.carrier_kinds,
        () if chosen is None or chosen.kind == 'player_effect' else (chosen.source_id,),
        (chosen.player_effect.id,) if chosen is not None and chosen.kind == 'player_effect' else ()),
        request.activation_profile_id)


def validate_selection(state, registry, activation, *, acceptance=False):
    """Local sample proof; unsigned saves are not an authenticity protocol."""
    selection = activation.selection
    if selection is None:
        return
    selection.__post_init__()
    request = selection.request
    selector = request.selector
    registry.end_turn_candidate_profile(request.candidate_profile_id)
    profile = registry.end_turn_profile(request.activation_profile_id)
    if profile.kind != activation.kind or selected_request(selection) != activation.request:
        raise ValueError('End-turn selection differs from its resolved activation request')
    if (any(i not in state.entities for i in selector.entity_ids) or
            any(i >= state.next_attachment_id for i in selector.player_effect_ids)):
        raise ValueError('End-turn candidate request has invalid historical references')
    if acceptance and end_turn_carriers(state, registry, request.selector,
            request.candidate_profile_id) != selection.candidates:
        raise ValueError('End-turn selection differs from its complete candidate window')
    for row in selection.candidates:
        row.__post_init__()
        if (row.player_id not in selector.player_ids or row.kind not in selector.carrier_kinds or
                selector.mode == 'selected' and (row.player_effect.id not in selector.player_effect_ids
                    if row.kind == 'player_effect' else row.source_id not in selector.entity_ids)):
            raise ValueError('End-turn candidate is outside its original producer scope')
        card = registry.card(row.card_id)
        entity = state.entities.get(row.source_id)
        if (entity is None or row.entered_order >= state.next_order or
                row.zone_epoch > entity.zone_epoch):
            raise ValueError('End-turn candidate has invalid historical provenance')
        if row.kind != 'player_effect':
            if KINDS.get(card.kind) != row.kind:
                raise ValueError('End-turn candidate differs from its registered carrier kind')
        else:
            effect = row.player_effect
            spec = registry.player_effect(effect.spec_id)
            from .aura_duration import maximum_duration
            maximum = maximum_duration(registry, effect, state)
            if (effect.id >= state.next_attachment_id or effect.created_turn > state.turn or
                    (effect.remaining_turns is None) != (spec.duration is None) or
                    spec.duration is not None and effect.remaining_turns > maximum):
                raise ValueError('End-turn candidate has invalid player-instance provenance')
            for player in state.players.values():
                current = next((e for e in player.player_effects if e.id == effect.id), None)
                if current is not None and (player.id != row.player_id or
                        replace(current, remaining_turns=effect.remaining_turns) != effect):
                    raise ValueError('End-turn candidate changed its surviving player-instance identity')
    probe = random.Random()
    probe.setstate(selection.rng_before)
    chosen = probe.choice(selection.candidates) if selection.candidates else None
    if chosen != selection.selected or probe.getstate() != selection.rng_after:
        raise ValueError('End-turn selection differs from its one recorded random draw')


@dataclass(frozen=True)
class TriggerRandomEndTurnEffects(Effect):
    player_id: int
    request: EndTurnProducerRequest
    source_id: int | None = None
    cause: Event | None = None

    def __post_init__(self):
        _player(self.player_id)
        if type(self.request) is not EndTurnProducerRequest:
            raise ValueError('Expected end-turn producer request')
        self.request.__post_init__()
        if self.source_id is not None:
            _integer(self.source_id, 'End-turn producer issuer', 1)
        if self.cause is not None and type(self.cause) is not Event:
            raise ValueError('Expected real end-turn producer cause')


def trigger(r, effect):
    from .end_turns import TriggerEndTurnEffects, trigger as accept
    effect.__post_init__()
    r.registry.end_turn_profile(effect.request.activation_profile_id)
    candidates = end_turn_carriers(r.state, r.registry, effect.request.selector,
                                  effect.request.candidate_profile_id)
    before = r.game._rng.getstate()
    chosen = r.game._rng.choice(candidates) if candidates else None
    selection = EndTurnSelection(effect.request, candidates, chosen, before, r.game._rng.getstate())
    # Do not queue a second Effect: its checkpoint could alter the selected
    # carrier or its accepted subjects before the batch proof is captured.
    return accept(r, TriggerEndTurnEffects(effect.player_id, selected_request(selection),
                  effect.source_id, effect.cause), selection=selection)


def register(mechanics):
    mechanics.register(TriggerRandomEndTurnEffects, trigger)
