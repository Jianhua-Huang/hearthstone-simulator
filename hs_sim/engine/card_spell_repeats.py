"""R-133: repeat attachments belong to one physical spell, frozen on hand play.

They do not grant player budgets or board auras. Explicit current copies inherit
independent attachments; physical storage moves retain them unless reset=True.
Automatic casts and history recasts do not use this hand-play-only property.
"""
from dataclasses import dataclass

from .effects import Effect, _integer, _source
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import AbilityInstance, CardType, SpellRepeatSpec
from .zones import CardReference, reference_entity, reference_value


@dataclass(frozen=True)
class GrantCardSpellRepeat(Effect):
    card: CardReference
    casts: int = 2
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        reference_value(self.card)
        _integer(self.casts, 'card spell casts', 2)
        _source(self.source_id)
        if self.expires_turn is not None: _integer(self.expires_turn, 'card spell expiry', 1)


@dataclass(frozen=True)
class RemoveCardSpellRepeat(Effect):
    card: CardReference
    ability_id: int
    source_id: int | None = None

    def __post_init__(self):
        reference_value(self.card)
        _integer(self.ability_id, 'card spell attachment', 1)
        _source(self.source_id)


def target(r, effect):
    from .resolver import validate_attachment_source
    effect.__post_init__()
    validate_attachment_source(r, effect.source_id, getattr(effect, 'expires_turn', None))
    if r.registry.card(effect.card.card_id).kind != CardType.SPELL:
        raise ResolutionError('Card spell repetition requires a stored spell')
    return reference_entity(r, effect.card)


def attach(state, entity, casts, source_id=None, expires_turn=None):
    ability = AbilityInstance(attachment_id(state), 'card_spell_repeat',
        source_id=source_id, expires_turn=expires_turn,
        spell_repeat=SpellRepeatSpec(casts, class_mode='any'))
    entity.abilities.append(ability)
    return ability


def grant(r, effect):
    entity = target(r, effect)
    if entity is None: return
    ability = attach(r.state, entity, effect.casts, effect.source_id, effect.expires_turn)
    r.emit('card_spell_repeat_added', target_id=entity.id, source_id=effect.source_id,
        player_id=entity.controller, amount=effect.casts, ability_id=ability.id)


def remove(r, effect):
    entity = target(r, effect)
    if entity is None: return
    ability = next((a for a in entity.abilities if a.kind=='card_spell_repeat' and a.id==effect.ability_id), None)
    if ability is None: return
    entity.abilities.remove(ability)
    r.emit('card_spell_repeat_removed', target_id=entity.id, source_id=effect.source_id,
        player_id=entity.controller, amount=ability.spell_repeat.casts, ability_id=ability.id)


def capture(entity):
    return tuple(a for a in entity.abilities if a.kind=='card_spell_repeat')


def execution_count(play):
    return max((a.spell_repeat.casts for a in play.card_spell_repeats), default=1)


def public_repeats(entity):
    return [dict(casts=a.spell_repeat.casts, expires_turn=a.expires_turn) for a in capture(entity)]


def validate_history(state):
    """A capture can outlive its attachment; an existing identity cannot mutate."""
    plays = [p for p in state.play_history if p.card_spell_repeats]
    if not plays: return
    live = {a.id:(entity.id,a) for entity in state.entities.values() for a in entity.abilities}
    unrelated = {a.id for entity in state.entities.values() for a in entity.enchantments}
    for p in state.players.values():
        unrelated.update(a.id for a in (*p.cost_modifiers,*p.player_effects,*p.battlecry_modifiers,*p.combo_modifiers,*p.spell_modifiers,*p.choose_both_modifiers))
    captured = {}
    for play in plays:
        for a in play.card_spell_repeats:
            if (a.id>=state.next_attachment_id or a.id in unrelated or
                    a.source_id is not None and a.source_id not in state.entities or
                    a.expires_turn is not None and a.expires_turn<play.turn):
                raise ValueError('Invalid captured card spell attachment')
            value = (play.source_id,a)
            if a.id in live and live[a.id]!=value or a.id in captured and captured[a.id]!=value:
                raise ValueError('Card spell capture identity or content changed')
            captured[a.id] = value
        repeat = next((x for x in state.spell_repeats if x.play_id==play.id), None)
        if repeat is not None and repeat.casts<execution_count(play):
            raise ValueError('Spell repetition lost a captured card contribution')
        if play.completed and not play.countered and repeat is None:
            raise ValueError('Accepted card spell repeat requires a repetition record')


def register(mechanics):
    mechanics.register(GrantCardSpellRepeat, grant)
    mechanics.register(RemoveCardSpellRepeat, remove)
