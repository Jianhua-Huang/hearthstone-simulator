"""Bottom-three physical selection with a resumable, captured-card continuation.

R-094: offer order is randomized; unselected deck order is preserved. The
selection callback captures the successful placement before its reactions.
"""
from dataclasses import dataclass

from .effects import Effect, ChoiceOption, RequestChoice, _player, _source
from .model import CardPreview, ChoicePurpose, Zone
from .zones import CardReference, reference_value, reference_entity, source_exists
from .registry import RuleContext


@dataclass(frozen=True)
class Dredge(Effect):
    player_id: int
    owner_id: int | None = None
    source_id: int | None = None
    on_select: str | None = None
    reveal: bool = False

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        if self.owner_id is not None: _player(self.owner_id)
        if self.on_select is not None and (type(self.on_select) is not str or not self.on_select.strip()):
            raise ValueError('Dredge continuation requires a registered behavior ID')
        if type(self.reveal) is not bool: raise ValueError('Dredge reveal must be boolean')


@dataclass(frozen=True)
class SelectDredgedCard(Effect):
    spec: Dredge
    card: CardReference

    def __post_init__(self):
        if type(self.spec) is not Dredge: raise ValueError('Expected Dredge specification')
        self.spec.__post_init__(); reference_value(self.card)
        if self.card.zone != Zone.DECK or self.card.player_id != (self.spec.owner_id or self.spec.player_id):
            raise ValueError('Dredge selection must reference its specified deck')


@dataclass(frozen=True)
class DredgeWithSourceStats(Effect):
    original: RuleContext

    def __post_init__(self):
        from .model import CardType
        c = self.original
        if (type(c) is not RuleContext or c.source.kind != CardType.MINION or c.battlecry is None or
                not c.battlecry.payload_started or c.battlecry.failure is not None or
                (c.battlecry.source_id,c.battlecry.player_id) != (c.source_id,c.player_id)):
            raise ValueError('Dredge source stats require their original accepted minion Battlecry')


@dataclass(frozen=True)
class SelectDredgedCardWithSourceStats(SelectDredgedCard):
    request: DredgeWithSourceStats

    def __post_init__(self):
        super().__post_init__()
        if type(self.request) is not DredgeWithSourceStats:
            raise ValueError('Dredge stat reward requires its complete original request')
        self.request.__post_init__(); c = self.request.original
        if self.spec != Dredge(c.player_id,source_id=c.source_id):
            raise ValueError('Dredge stat reward changed its original owner, source or query')


def dredge(r, effect, *, request=None):
    from .continuations import FrameCodec
    effect.__post_init__(); source_exists(r, effect.source_id)
    # Validate even on an empty deck: unsupported callbacks never become no-ops.
    codec = FrameCodec(r.game.mechanics, r.registry)
    codec.decode(codec.encode(effect))
    deck = r.player(effect.owner_id or effect.player_id).deck
    candidates = tuple(deck[-3:])
    if not candidates: return ()
    # Only membership is revealed, not the precise relative bottom positions.
    offered = r.game._rng.sample(candidates, len(candidates)) if len(candidates) > 1 else candidates
    options = []
    for n, entity_id in enumerate(offered, 1):
        entity = r.state.entities[entity_id]
        branch = (SelectDredgedCard(effect,CardReference.capture(entity)) if request is None else
            SelectDredgedCardWithSourceStats(effect,CardReference.capture(entity),request))
        options.append(ChoiceOption(f'dredge-{n}', entity.display_name or r.registry.card(entity.card_id).name,
            (branch,), card_id=entity.card_id,
            preview=CardPreview.capture(entity, r.registry)))
    return (RequestChoice(effect.player_id, tuple(options), source_id=effect.source_id,
                          prompt='探底：选择一张牌置于牌库顶', purpose=ChoicePurpose.DREDGE),)


def dredge_with_source_stats(r, effect):
    effect.__post_init__(); c = effect.original
    return dredge(r,Dredge(c.player_id,source_id=c.source_id),request=effect)


def select_with_source_stats(r, effect):
    from .hand_upgrades import BuffStoredCard
    from .model import CardType
    effect.__post_init__()
    entity = reference_entity(r,effect.card)
    if entity is None: return ()
    # The common reorder retires the old deck reference and announces before
    # reactions. Capture the new physical residence in the same window.
    work = select_card(r,SelectDredgedCard(effect.spec,effect.card))
    if entity.kind != CardType.MINION: return work
    c = effect.request.original
    return (*work,BuffStoredCard(CardReference.capture(entity),c.source.attack,max(0,c.source.health),c.source_id))


def select_card(r, effect):
    effect.__post_init__(); spec = effect.spec
    source_exists(r, spec.source_id)
    entity = reference_entity(r, effect.card)
    if entity is None: return ()
    deck = r.player(entity.controller).deck
    deck.remove(entity.id); deck.insert(0, entity.id)
    # This is a reorder, not a new hand entry, draw, summon or entity reset.
    # Retire references captured before this successful operation.
    entity.zone_epoch += 1
    r.game._information.conceal(entity.id)
    preview = CardPreview.capture(entity, r.registry)
    from .serialization import preview_to_dict
    r.emit('card_dredged', source_id=spec.source_id, target_id=entity.id, player_id=spec.player_id,
           owner_id=entity.controller, card_id=entity.card_id, preview=preview_to_dict(preview), reveal=spec.reveal)
    if spec.on_select is None: return ()
    return (r.call(spec.on_select, spec.source_id or r.player(spec.player_id).hero_id,
                   spec.player_id, target_id=entity.id),)


def register(mechanics):
    mechanics.register(Dredge, dredge)
    mechanics.register(SelectDredgedCard, select_card)
    mechanics.register(DredgeWithSourceStats, dredge_with_source_stats)
    mechanics.register(SelectDredgedCardWithSourceStats, select_with_source_stats)


def validate_choice(game):
    choice = game._state.pending_choice
    if choice is None or choice.purpose != ChoicePurpose.DREDGE: return
    frame = game._frame
    if (choice.min_count != 1 or choice.max_count != 1 or not 1 <= len(choice.options) <= 3 or
            choice.repeat_key is not None or frame.on_select is not None):
        raise ValueError('Invalid Dredge choice cardinality or continuation')
    refs = set(); spec = None; request = None; kind = None
    for n, option in enumerate(frame.options, 1):
        if len(option.effects) != 1 or type(option.effects[0]) not in (SelectDredgedCard,SelectDredgedCardWithSourceStats):
            raise ValueError('Dredge choice requires a physical selection branch')
        effect = option.effects[0]
        if kind is not None and kind is not type(effect):
            raise ValueError('Dredge choices cannot mix native stat and ordinary source requests')
        if type(effect) is SelectDredgedCardWithSourceStats:
            effect.__post_init__()
            if request is not None and request != effect.request:
                raise ValueError('Dredge choices cannot borrow different original stat windows')
            request = effect.request
        kind = type(effect)
        if (option.id != f'dredge-{n}' or option.card_id != effect.card.card_id or
                option.preview is None or option.entity_id is not None or
                effect.spec.player_id != choice.player_id or effect.spec.source_id != choice.source_id or
                spec is not None and spec != effect.spec or effect.card.entity_id in refs):
            raise ValueError('Dredge choice metadata and physical branches disagree')
        refs.add(effect.card.entity_id); spec = effect.spec
