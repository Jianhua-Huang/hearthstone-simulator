"""Continuous keyword contributions, separate from intrinsic/granted abilities."""
from dataclasses import dataclass

from .effects import Effect, _integer, _source
from .lifecycle import active_abilities, attachment_id, local_keywords, refresh_entity
from .model import AbilityInstance, CardType, Keyword, KeywordAuraSpec, PlayerKeywordConditionAuraSpec, Zone


POSITIONAL_TARGETS = ('friendly_leftmost_minion', 'friendly_rightmost_minion')


def native_scope(spec):
    return (spec.condition != 'always' or spec.tribes_any or spec.card_ids or
            spec.target in POSITIONAL_TARGETS)


def validate_definition(card):
    if type(card.keyword_auras) is not tuple or any(type(a) is not KeywordAuraSpec for a in card.keyword_auras):
        raise ValueError('keyword_auras requires a tuple of KeywordAuraSpec')
    if card.keyword_auras and card.kind != CardType.MINION:
        raise ValueError('Keyword aura sources must be minions')
    for spec in card.keyword_auras:
        spec.__post_init__()
    conditional = tuple(s for s in card.keyword_auras if native_scope(s))
    if conditional:
        from .stat_relations import validate_ordinary_face
        validate_ordinary_face(card)
        if len(set(conditional)) != len(conditional):
            raise ValueError('Duplicate printed native keyword aura declaration')


def validate_carrier(registry, card_id, kind, abilities, components=()):
    rows = []
    card = registry.card(card_id)
    tribal_native = any(native_scope(s) for s in card.keyword_auras)
    for ability in abilities:
        if ability.kind == 'keyword_aura':
            ability.__post_init__()
            if (native_scope(ability.keyword_aura) or
                    tribal_native and ability.origin == 'printed'):
                rows.append(ability)
    if not rows: return
    if kind != CardType.MINION or components:
        raise ValueError('Native keyword auras require a non-composite minion carrier')
    validate_definition(card)
    from .stat_relations import validate_ordinary_face
    validate_ordinary_face(card)
    if len({a.keyword_aura for a in rows}) != len(rows):
        raise ValueError('Duplicate native keyword aura instance')
    for ability in rows:
        if ability.keyword_aura not in card.keyword_auras:
            raise ValueError('Native keyword aura differs from its declaration')


def conditional_keywords(state, entity):
    """Pure state-dependent self contributions; local damaged Windfury stays local."""
    from .equipment import equipped_weapon
    specs = tuple(a.keyword_aura for a in active_abilities(entity, 'keyword_aura')
                  if a.keyword_aura.condition == 'controller_has_weapon')
    result={spec.keyword for spec in specs}if specs and equipped_weapon(state,state.players[entity.controller])is not None else set()
    alone=tuple(a.keyword_aura for a in active_abilities(entity,'keyword_aura')if a.keyword_aura.condition=='controller_no_other_minions')
    if alone and entity.kind==CardType.MINION and entity.zone==Zone.BOARD and entity.active:
        others=any(i!=entity.id and(e:=state.entities[i]).kind==CardType.MINION and not e.starship_building and not e.interactable_object
            for i in state.players[entity.controller].board)
        if not others:result.update(spec.keyword for spec in alone)
    if (entity.kind == CardType.MINION and entity.zone == Zone.BOARD and entity.active and
            entity.controller != state.active_player):
        result.update(a.keyword_aura.keyword for a in active_abilities(entity, 'keyword_aura')
                      if a.keyword_aura.condition == 'controller_opponent_turn')
    return result


def refresh_conditional_keywords(state):
    """Normalize only self-condition carriers before event contexts are frozen."""
    for entity in state.entities.values():
        keywords = conditional_keywords(state, entity)
        changed = entity.conditional_keywords != keywords
        entity.conditional_keywords = keywords
        if changed or any(a.kind == 'keyword_aura' and a.keyword_aura.condition != 'always'
                          for a in entity.abilities):
            refresh_entity(entity)


@dataclass(frozen=True)
class GrantKeywordAura(Effect):
    target_id: int
    spec: KeywordAuraSpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'keyword aura holder', 1)
        _source(self.source_id)
        if type(self.spec) is not KeywordAuraSpec:
            raise ValueError('Keyword aura requires KeywordAuraSpec')
        self.spec.__post_init__()
        if self.spec.condition != 'always':
            raise ValueError('Conditional keyword grants are not supported')
        if self.spec.tribes_any or self.spec.card_ids:
            raise ValueError('Filtered keyword grants are not supported')
        if self.spec.target in POSITIONAL_TARGETS:
            raise ValueError('Positional keyword auras require their native declaration')
        if self.expires_turn is not None:
            _integer(self.expires_turn, 'keyword aura expiry', 1)


def refresh_keyword_auras(state, registry, *, include_dying=False):
    contributions = {i: set() for i in state.entities}
    for player in state.players.values():
        for effect in player.player_effects:
            for spec in registry.player_effect(effect.spec_id).keyword_auras:
                if type(spec) is PlayerKeywordConditionAuraSpec:
                    continue
                from .tribes import has_any_tribe
                for target_id in player.board:
                    target = state.entities[target_id]
                    if (target.kind == CardType.MINION and target.active and
                            has_any_tribe(registry, target, spec.tribes_any, basis='current')):
                        contributions[target_id].add(spec.keyword)
        for index, source_id in enumerate(player.board):
            source = state.entities[source_id]
            if (source.kind != CardType.MINION or not source.active or
                    not include_dying and (source.health <= 0 or source.doomed)):
                continue
            for ability in active_abilities(source, 'keyword_aura'):
                spec = ability.keyword_aura
                if spec.condition=='rush_summon_turn':continue
                if spec.condition == 'controller_turn' and source.controller != state.active_player:
                    continue
                if spec.target == 'self':
                    # Self contributions use local/state-dependent keyword unions.
                    continue
                if spec.target.startswith('friendly_hand'):
                    continue
                targets = (player.hero_id,) if spec.target == 'friendly_hero' else player.board
                if spec.target == 'enemy_minions':
                    targets = state.players[3-source.controller].board
                if spec.target in POSITIONAL_TARGETS:
                    # Select the actual edge minion before active-recipient filtering.
                    # A dormant minion keeps its place; locations/building objects do not.
                    minions = tuple(i for i in player.board if state.entities[i].kind == CardType.MINION
                                    and not state.entities[i].interactable_object
                                    and not state.entities[i].starship_building)
                    targets = minions[:1] if spec.target == 'friendly_leftmost_minion' else minions[-1:]
                if spec.adjacent_only:
                    targets = player.board[max(0, index - 1):index] + player.board[index + 1:index + 2]
                for target_id in targets:
                    target = state.entities[target_id]
                    if (target.active and target.is_character and
                            (target_id != source_id or spec.include_self)):
                        if spec.tribes_any:
                            from .tribes import has_any_tribe
                            if not has_any_tribe(registry, target, spec.tribes_any, basis='current'):
                                continue
                        from .stat_auras import matches_card_identity
                        if not matches_card_identity(target, spec.card_ids):
                            continue
                        contributions[target_id].add(spec.keyword)
    # Native Rush immunity and the player Rush-to-Charge predicate read
    # fresh ordinary contributions, never the previous derived keyword cache.
    # Neither produces Rush, so removal settles in this same refresh pass.
    from .successful_summons import original_entry_turn
    for player in state.players.values():
        native=tuple(a.keyword_aura for source_id in player.board
            if (source:=state.entities[source_id]).kind==CardType.MINION and source.active and
                (include_dying or source.health>0 and not source.doomed)
            for a in active_abilities(source,'keyword_aura')if a.keyword_aura.condition=='rush_summon_turn')
        if not native:continue
        for target_id in player.board:
            target=state.entities[target_id]
            if target.kind!=CardType.MINION or not target.active:continue
            ordinary=local_keywords(target)|conditional_keywords(state,target)|contributions[target_id]
            if Keyword.RUSH in ordinary and original_entry_turn(state,target)==state.turn:
                contributions[target_id].update(spec.keyword for spec in native)
    for player in state.players.values():
        predicates = tuple(spec for effect in player.player_effects
            for spec in registry.player_effect(effect.spec_id).keyword_auras
            if type(spec) is PlayerKeywordConditionAuraSpec)
        if not predicates:
            continue
        for target_id in player.board:
            target = state.entities[target_id]
            if target.kind != CardType.MINION or not target.active:
                continue
            ordinary = local_keywords(target) | conditional_keywords(state,target) | contributions[target_id]
            for spec in predicates:
                if spec.required_keyword in ordinary:
                    contributions[target_id].add(spec.keyword)
    for entity_id, entity in state.entities.items():
        entity.aura_keywords = contributions[entity_id]
    refresh_conditional_keywords(state)
    refresh_hand_keyword_auras(state, include_dying=include_dying)


def refresh_turn_keywords(state, registry):
    """Update existing keyword caches before the new actual turn captures work."""
    if not any(a.kind == 'keyword_aura' and a.keyword_aura.condition in ('controller_turn','controller_opponent_turn','rush_summon_turn')
               for player in state.players.values() for source_id in player.board
               for a in state.entities[source_id].abilities):
        return
    refresh_keyword_auras(state, registry)
    for entity in state.entities.values():
        refresh_entity(entity)


def refresh_summon_keywords(state,registry):
    if any(entity.zone==Zone.BOARD and entity.active and any(a.kind=='keyword_aura'and
            a.keyword_aura.condition=='rush_summon_turn'for a in entity.abilities)
            for entity in state.entities.values()):
        refresh_keyword_auras(state,registry)
        for entity in state.entities.values():refresh_entity(entity)


def refresh_hand_keyword_auras(state, *, include_dying=False):
    """Recompute hand-only contributions without changing board aura timing.

    Also used before events freeze their context, because zone effects can move
    or generate a card and emit its acquisition in the same effect handler.
    """
    contributions = {}
    kinds = {'friendly_hand_minions': (CardType.MINION,),
             'friendly_hand_spells': (CardType.SPELL,),
             'friendly_hand': (CardType.MINION, CardType.SPELL)}
    for player in state.players.values():
        for source_id in player.board:
            source = state.entities[source_id]
            if (source.kind != CardType.MINION or not source.active or
                    not include_dying and (source.health <= 0 or source.doomed)):
                continue
            for ability in active_abilities(source, 'keyword_aura'):
                spec = ability.keyword_aura
                if spec.target not in kinds:
                    continue
                for target_id in player.hand:
                    if state.entities[target_id].kind in kinds[spec.target]:
                        contributions.setdefault(target_id, set()).add(spec.keyword)
    for entity_id, entity in state.entities.items():
        keywords = contributions.get(entity_id, set())
        if entity.hand_aura_keywords != keywords:
            entity.hand_aura_keywords = keywords
            refresh_entity(entity)


def grant_keyword_aura(r, effect):
    from .resolver import validate_attachment_source
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD or not entity.active:
        r.stale(effect, effect.target_id)
        return ()
    ability = AbilityInstance(attachment_id(r.state), 'keyword_aura', source_id=effect.source_id,
                             keyword_aura=effect.spec, expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.refresh_auras()
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind=ability.kind)


def register(mechanics):
    mechanics.register_payload_type(KeywordAuraSpec)
    mechanics.register(GrantKeywordAura, grant_keyword_aura)
