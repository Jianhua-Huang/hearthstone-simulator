"""Shared, pure target eligibility for action validation and enumeration."""
from copy import deepcopy

from .errors import ResolutionError
from .model import CardType, Keyword, TargetMode, TargetSpec, Zone
from .registry import RuleContext


def target_spec(definition):
    if definition.targeting is not None:
        return definition.targeting
    return TargetSpec() if definition.requires_target else None


def effective_target_spec(state,registry,source,definition):
    from .spell_target_conditions import effective_spec
    from .hero_health_targets import effective_spec as health_spec
    from .kindred_targets import effective_spec as kindred_spec
    return kindred_spec(state,registry,source,definition,
                       health_spec(state,registry,source,definition,
                       effective_spec(state,registry,source,definition,target_spec(definition))))


def accepts_target(state, registry, source, definition, target_id, *, context_factory=None, automatic=False):
    spec = effective_target_spec(state,registry,source,definition)
    target = state.entities.get(target_id)
    if spec is None or target is None or not target.active or target.zone not in spec.zones:
        return False
    if registry.card(target.card_id).kind not in spec.kinds:
        return False
    from .player_effects import target_allowed
    if not target_allowed(state, registry, source.controller, definition.kind, target.kind):
        return False
    if spec.exclude_source and target.id == source.id:
        return False
    if spec.relation == 'friendly' and target.controller != source.controller:
        return False
    if spec.relation == 'enemy' and target.controller == source.controller:
        return False
    if target.zone in (Zone.HERO, Zone.BOARD):
        if target.doomed or (target.health <= 0 if target.is_character else target.durability <= 0):
            return False
        if not automatic and Keyword.ELUSIVE in target.keywords and definition.kind in (CardType.SPELL, CardType.HERO_POWER):
            return False
        from .combat import is_immune
        from .spell_mana_budget import blocks_enemy_spell
        if not automatic and target.controller!=source.controller and blocks_enemy_spell(target,definition):
            return False
        if not automatic and target.controller != source.controller and (is_immune(state, target) or Keyword.STEALTH in target.keywords):
            return False
    try:
        if registry.target_visibility(definition.target_rule) == 'player':
            if context_factory is None:
                raise ValueError('Player target rules require an observation context')
            ctx = context_factory(source.id, target_id)
            if ctx.target is None:
                return False
        else:
            ctx = RuleContext(deepcopy(state), source.id, source.controller, target_id)
        valid = registry.target_rule(definition.target_rule)(ctx)
    except Exception as exc:
        raise ResolutionError(f'Target rule {definition.target_rule} failed: {exc}') from exc
    if type(valid) is not bool:
        raise ResolutionError('Target rule must return bool')
    return valid


def legal_target_ids(state, registry, source, definition, *, context_factory=None):
    return tuple(i for i in sorted(state.entities)
                 if accepts_target(state, registry, source, definition, i, context_factory=context_factory))


def target_choices(state, registry, source, definition, *, context_factory=None):
    spec = effective_target_spec(state,registry,source,definition)
    if spec is None:
        return (None,)
    targets = legal_target_ids(state, registry, source, definition, context_factory=context_factory)
    if spec.mode == TargetMode.OPTIONAL or (spec.mode == TargetMode.IF_AVAILABLE and not targets):
        return (None, *targets)
    return targets


def target_error(state, registry, source, definition, target_id, *, context_factory=None):
    spec = effective_target_spec(state,registry,source,definition)
    if target_id is not None:
        if not accepts_target(state, registry, source, definition, target_id, context_factory=context_factory):
            return 'Target rejected by the target rule or domain'
    elif spec is not None:
        if spec.mode == TargetMode.REQUIRED:
            return 'A target is required'
        if spec.mode == TargetMode.IF_AVAILABLE and legal_target_ids(state, registry, source, definition, context_factory=context_factory):
            return 'A target is required when one is available'
    return None


def effect_policies(targeting, target_id, choices):
    from .effects import _source
    _source(target_id)
    if targeting not in ('random','explicit') or choices not in ('random','player'):
        raise ValueError('Unknown effect activation policy')
    if targeting == 'random' and target_id is not None:
        raise ValueError('Random activation cannot prescribe a target')


def effect_target_context(r, entity):
    """Player predicates see the usual detached DTO, including a cast source off board."""
    from .player_api import visible_entities
    from .registry import PlayerRuleContext
    cached = []
    source = {'card_id': entity.card_id, 'kind': entity.kind.value, 'controller': entity.controller,
              'zone': entity.zone.value, 'attack': entity.attack, 'health': entity.health,
              'keywords': sorted(k.value for k in entity.keywords)}
    if entity.kind == CardType.MINION:
        from .tribes import tribe_state
        current = tribe_state(r.registry, entity)
        source['tribes'] = None if current is None else list(current.members)
        source['tribes_excluded'] = [] if current is None else list(current.excluded)
    def context(source_id, target_id):
        if not cached:
            r.game._information.sync(r.game)
            observation = r.game._information.observe(r.game, entity.controller)
            cached.append((observation, visible_entities(observation)))
        observation, visible = cached[0]
        refs = r.game._information.players[entity.controller].refs
        target = visible.get(refs.get(str(target_id)))
        return PlayerRuleContext(entity.controller, deepcopy(observation), deepcopy(source), deepcopy(target))
    return context


def select_effect_target(r, source, definition, targeting, target_id, *, excluded_ids=()):
    """Automatic activation domains, separate from manual selectable protection."""
    spec = effective_target_spec(r.state,r.registry,source,definition)
    context = effect_target_context(r,source)
    targets = tuple(i for i in sorted(r.state.entities) if i not in excluded_ids and accepts_target(r.state,r.registry,
        source,definition,i,context_factory=context,automatic=True)) if spec else ()
    failure = None
    if targeting == 'random':
        if targets: target_id = r.game._rng.choice(targets)
        elif spec is not None and spec.mode == TargetMode.REQUIRED: failure = 'no_target'
    elif target_id is not None and target_id not in targets: failure = 'invalid_target'
    elif target_id is None and spec is not None and (spec.mode == TargetMode.REQUIRED or
            spec.mode == TargetMode.IF_AVAILABLE and targets): failure = 'no_target'
    if target_id not in r.state.entities: target_id = None
    return target_id, failure
