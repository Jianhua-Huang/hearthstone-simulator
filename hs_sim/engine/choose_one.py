"""Pre-activation branch declarations shared by plays, casts and hero powers."""
from dataclasses import dataclass, replace
from .effects import Effect, _source, _integer
from .errors import ResolutionError
from .lifecycle import active_abilities, attachment_id
from .model import AbilityInstance, CardType, ChooseOneSpec, Keyword, Zone

DISPATCH = 'engine.choose_one'


def normalize(definition):
    if definition.choose_one is None:
        return definition
    if type(definition.choose_one) is not ChooseOneSpec:
        raise ValueError('Choose One requires ChooseOneSpec')
    definition.choose_one.__post_init__()
    # Only ordinary Choose One roots are supported. Further declarations need
    # a concrete card requirement before defining their activation semantics.
    if (any(value is not None for value in (definition.secret, definition.quest,
            definition.ongoing_effect_id, definition.shatter, definition.battlecry, definition.combo)) or
            definition.magnetic_tribes or Keyword.MAGNETIC in definition.keywords or
            Keyword.SHATTER in definition.keywords or Keyword.SHATTERED in definition.keywords):
        raise ValueError('Unsupported Choose One composite root declaration')
    if (definition.kind not in (CardType.MINION, CardType.SPELL, CardType.HERO_POWER) or
            definition.choice_only or definition.passive_hero_power or definition.target_condition or
            definition.requires_target or definition.targeting is not None or definition.target_rule != 'any_entity'):
        raise ValueError('Unsupported Choose One root declaration; targeting belongs to branches')
    name = 'on_use' if definition.kind == CardType.HERO_POWER else 'on_play'
    if getattr(definition, name) not in (None, DISPATCH):
        raise ValueError('Choose One owns its payload; declare behavior on each branch')
    return replace(definition, **{name: DISPATCH})


def branch(definition, branch_id):
    spec = definition.choose_one
    if spec is None:
        if branch_id is not None: raise ValueError('This card has no Choose One branches')
        return None
    if type(branch_id) is not str:
        raise ValueError('Choose One requires an explicit branch')
    result = next((b for b in (*spec.branches, spec.combined) if b.id == branch_id), None)
    if result is None: raise ValueError('Unknown Choose One branch')
    return result


def combined_sources(state, player_id):
    """Active board carriers; dying sources persist until the death checkpoint."""
    return tuple(a.id for i in state.players[player_id].board
                 for a in active_abilities(state.entities[i], 'choose_both'))


def branches(state, definition, player_id, *, origin=None, entity=None):
    if definition.choose_one is None: return (None,)
    spec = definition.choose_one
    from .choose_policies import matching
    origin = origin or ('power_manual' if definition.kind == CardType.HERO_POWER else 'hand')
    combined = combined_sources(state, player_id) or matching(state, definition, player_id, origin)
    from .choose_branch_state import options, for_entity
    return options(definition, bool(combined), origin, for_entity(entity))


def selection_error(state, definition, player_id, branch_id, rules, *, entity=None):
    try: selected = branch(definition, branch_id)
    except ValueError as exc: return str(exc)
    if branch_id not in branches(state, definition, player_id, entity=entity):
        return 'Choose One branch does not match the current combination policy'
    if selected and selected.requires_board_space and len(state.players[player_id].board) >= rules.max_board:
        return 'Chosen branch requires board space'
    return None


def effective(definition, branch_id):
    selected = branch(definition, branch_id)
    if selected is None: return definition
    return replace(definition, requires_target=False, targeting=selected.targeting,
                   target_rule=selected.target_rule, choose_one=None)


def automatic_branch(r, definition, player_id, explicit=None, *, origin=None, entity=None):
    """Effect sources randomly choose a branch unless explicitly prescribed.

    Branch selection precedes target selection, even when a chosen branch will
    fail for lack of targets. `choices` on effect sources governs payload choices.
    """
    origin = origin or ('power_effect' if definition.kind == CardType.HERO_POWER else 'cast_effect')
    options = branches(r.state, definition, player_id, origin=origin, entity=entity)
    if not options: raise ResolutionError('Preselected branch conflicts with the current combination policy')
    if explicit is not None:
        branch(definition, explicit)
        if explicit not in options:
            raise ResolutionError('Automatic branch violates the current combination policy')
        return explicit
    return options[0] if len(options) == 1 else r.game._rng.choice(options)


def dispatch(registry, context):
    record = next((x for x in (context.cast, context.play, context.power)
                   if x is not None and x.source_id == context.source_id), None)
    if record is None:
        if context.physical is not None:
            from .generated_choose_one import dispatch as dispatch_generated
            return dispatch_generated(registry, context)
        raise ResolutionError('Choose One payload requires a captured activation')
    selected = branch(registry.card(record.card_id), record.branch_id)
    if selected is None: raise ResolutionError('Choose One activation lacks its declaration')
    return registry.behavior(selected.behavior_id)(context)


@dataclass(frozen=True)
class GrantChooseBoth(Effect):
    target_id: int
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'Choose Both target', 1); _source(self.source_id)
        if self.expires_turn is not None: _integer(self.expires_turn, 'Choose Both expiry', 1)


def grant(r, effect):
    from .zones import source_exists
    effect.__post_init__(); source_exists(r, effect.source_id)
    if effect.expires_turn is not None and effect.expires_turn < r.state.turn:
        raise ResolutionError('Choose Both grant already expired')
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD:
        return
    entity.abilities.append(AbilityInstance(attachment_id(r.state), 'choose_both',
        source_id=effect.source_id, expires_turn=effect.expires_turn))
    r.emit('ability_granted', source_id=effect.source_id, target_id=entity.id, ability_kind='choose_both')


def register(mechanics):
    mechanics.register(GrantChooseBoth, grant)
