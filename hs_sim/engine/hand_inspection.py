"""Private physical hand offers and their finite native follow-up material."""
from dataclasses import asdict, dataclass, replace
import json

from .effects import ChoiceOption, Effect, RequestChoice, _integer, _player
from .errors import ResolutionError, ResolutionLimitExceeded
from .hand_history import hand_entry
from .model import HandInvestigation, Zone
from .pools import PoolQuery
from .zones import CardReference, DiscardCard, discard_card, source_exists, zone_candidates
from .sacrifice import MinionReference, reference_value, same_instance


@dataclass(frozen=True)
class InspectHandCards(Effect):
    player_id: int
    owner_id: int
    count: int
    source_id: int
    on_select: str
    context: str = '{}'

    def __post_init__(self):
        _player(self.player_id); _player(self.owner_id)
        _integer(self.count, 'private hand offer size', 1)
        _integer(self.source_id, 'private hand inspection source', 1)
        if self.player_id == self.owner_id or type(self.on_select) is not str or not self.on_select.strip():
            raise ValueError('Private inspection requires the other hand and a named continuation')
        if type(self.context) is not str or type(json.loads(self.context)) is not dict:
            raise ValueError('Private inspection context must be a serialized material object')


def inspect(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id)
    r.registry.behavior(effect.on_select)
    candidates = zone_candidates(r, effect.owner_id, Zone.HAND, PoolQuery(), effect.player_id, effect.source_id)
    count = min(effect.count, len(candidates))
    if count > r.rules.max_choice_options:
        raise ResolutionLimitExceeded('Private hand inspection exceeds the offered option limit')
    if not count:
        return ()
    offered = tuple(r.game._rng.sample(candidates, count))
    options = []
    for ref in offered:
        entity = r.state.entities[ref.entity_id]
        r.game._information.players[effect.player_id].remember(entity)
        material = dict(card=asdict(ref), hand_entry_id=entity.hand_entry_id, context=json.loads(effect.context))
        options.append(ChoiceOption(json.dumps(material, sort_keys=True), r.registry.card(ref.card_id).name,
            card_id=ref.card_id, entity_id=ref.entity_id))
    return (RequestChoice(effect.player_id, tuple(options), effect.source_id,
        prompt='秘密选择一张对手手牌', on_select=effect.on_select),)


def selected_hand(context):
    choice = context.choice
    if choice is None or len(choice.selected_ids) != 1:
        raise ResolutionError('Private hand follow-up requires one original selected option')
    option = next((o for o in choice.choice.options if o.id == choice.selected_ids[0]), None)
    if option is None:
        raise ResolutionError('Private hand selection was not in the original offer')
    material = json.loads(option.id)
    if set(material) != {'card', 'hand_entry_id', 'context'} or type(material['context']) is not dict:
        raise ResolutionError('Private hand selection lost its complete original material')
    ref = CardReference(**dict(material['card'], zone=Zone(material['card']['zone'])))
    entry = validate_hand_link(context.state, ref, material['hand_entry_id'])
    if (option.entity_id, option.card_id) != (ref.entity_id, ref.card_id):
        raise ResolutionError('Private hand offer substituted its original physical face')
    return ref, entry, material['context']


@dataclass(frozen=True)
class GuessOpponentHandCard(Effect):
    """One original hand face and up to two absent original-deck decoys."""
    player_id: int
    owner_id: int
    source_id: int
    on_select: str
    context: str = '{}'

    def __post_init__(self):
        _player(self.player_id); _player(self.owner_id); _integer(self.source_id, 'hand guess source', 1)
        if self.player_id == self.owner_id or type(self.on_select) is not str or not self.on_select.strip():
            raise ValueError('Hand guess requires the other hand and a named continuation')
        if type(self.context) is not str or type(json.loads(self.context)) is not dict:
            raise ValueError('Hand guess context must be a serialized material object')


def guess_identity(registry, card_id):
    card = registry.card(card_id)
    if not card.hand_playable:
        raise ResolutionError('Hand guess requires complete physical card faces')
    return registry.pool_card(card_id).generation_identity if card_id in registry.pool_cards else card_id


def guess_decoys(registry, hand, original_deck):
    held = {guess_identity(registry, ref.card_id) for ref in hand}
    choices = {}
    for card_id in original_deck:
        identity = guess_identity(registry, card_id)
        if identity not in held:
            choices.setdefault(identity, card_id)
    return tuple(choices.values())


def guess_hand(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id); r.registry.behavior(effect.on_select)
    hand = zone_candidates(r, effect.owner_id, Zone.HAND, PoolQuery(), effect.player_id, effect.source_id)
    if not hand:
        return ()
    origin = r.game._generation_context
    if r.state.opening is None and (origin is None or origin.starting_decks is None):
        raise ResolutionError('Hand guess requires the original opponent deck inventory')
    original = r.state.players[effect.owner_id].original_deck
    candidates = guess_decoys(r.registry, hand, original)
    size = 1 + min(2, len(candidates))
    if size > r.rules.max_choice_options:
        raise ResolutionLimitExceeded('Hand guess exceeds the offered option limit')
    chosen = r.game._rng.choice(hand)
    decoys = tuple(r.game._rng.sample(candidates, size - 1))
    faces = [chosen.card_id, *decoys]
    r.game._rng.shuffle(faces)
    material = dict(player_id=effect.player_id, owner_id=effect.owner_id, source_id=effect.source_id,
        hand=[dict(card=asdict(ref), entry_id=r.state.entities[ref.entity_id].hand_entry_id) for ref in hand],
        chosen_id=chosen.entity_id, original_deck=list(original), decoys=list(decoys), faces=faces,
        context=json.loads(effect.context))
    # All offered faces are unbound previews. Remembering the real entity or
    # attaching its entity_id would reveal which option is actually in hand.
    options = tuple(ChoiceOption(json.dumps(dict(card_id=cid, material=material), sort_keys=True),
        r.registry.card(cid).name, card_id=cid) for cid in faces)
    return (RequestChoice(effect.player_id, options, effect.source_id,
        prompt='猜测哪张牌在对手手牌中', on_select=effect.on_select),)


def selected_hand_guess(context, registry):
    choice = context.choice
    if choice is None or len(choice.selected_ids) != 1:
        raise ResolutionError('Hand guess requires one original selected option')
    option = next((o for o in choice.choice.options if o.id == choice.selected_ids[0]), None)
    if option is None:
        raise ResolutionError('Hand guess was not in the original offer')
    raw = json.loads(option.id)
    if type(raw) is not dict or set(raw) != {'card_id', 'material'}:
        raise ResolutionError('Hand guess lost its original material')
    m = raw['material']
    if (type(m) is not dict or set(m) != {'player_id','owner_id','source_id','hand','chosen_id',
            'original_deck','decoys','faces','context'} or type(m['context']) is not dict or
            (m['player_id'], m['owner_id'], m['source_id']) != (context.player_id, 3-context.player_id, context.source_id)):
        raise ResolutionError('Hand guess borrowed another original source or player')
    _player(m['player_id']); _player(m['owner_id'])
    _integer(m['source_id'], 'hand guess original source', 1)
    _integer(m['chosen_id'], 'hand guess chosen physical card', 1)
    if (type(m['hand']) is not list or any(type(m[k]) is not list or
            any(type(cid) is not str or not cid for cid in m[k]) for k in ('original_deck','decoys','faces'))):
        raise ResolutionError('Hand guess requires complete original typed card inventories')
    if tuple(m['original_deck']) != context.state.players[m['owner_id']].original_deck:
        raise ResolutionError('Hand guess changed the original opponent deck')
    refs = []
    for row in m['hand']:
        if type(row) is not dict or set(row) != {'card','entry_id'}:
            raise ResolutionError('Hand guess lost an original hand acquisition')
        ref = CardReference(**dict(row['card'], zone=Zone(row['card']['zone'])))
        validate_hand_link(context.state, ref, row['entry_id'])
        if ref.player_id != m['owner_id']:
            raise ResolutionError('Hand guess borrowed a foreign hand')
        refs.append(ref)
    if not refs or len({r.entity_id for r in refs}) != len(refs):
        raise ResolutionError('Hand guess lost its distinct original hand inventory')
    chosen = next((r for r in refs if r.entity_id == m['chosen_id']), None)
    candidates = guess_decoys(registry, refs, m['original_deck'])
    if (chosen is None or len(m['decoys']) != min(2,len(candidates)) or
            len(set(m['decoys'])) != len(m['decoys']) or not set(m['decoys']) <= set(candidates) or
            len(m['faces']) != 1+len(m['decoys']) or set(m['faces']) != {chosen.card_id,*m['decoys']}):
        raise ResolutionError('Hand guess substituted its accepted true face or original-deck decoys')
    if tuple(o.card_id for o in choice.choice.options) != tuple(m['faces']):
        raise ResolutionError('Hand guess changed the complete ordered offer')
    for offered in choice.choice.options:
        if (offered.entity_id is not None or json.loads(offered.id) != dict(card_id=offered.card_id, material=m)):
            raise ResolutionError('Hand guess leaked or changed an original option binding')
    return option.card_id == chosen.card_id, m['context']


def validate_hand_link(state, ref, entry_id):
    if type(ref) is not CardReference:
        raise ValueError('Hand selection requires a typed original reference')
    ref.__post_init__(); entry = hand_entry(state, entry_id)
    entity = state.entities.get(ref.entity_id)
    if (ref.zone != Zone.HAND or entity is None or entry.entity_id != ref.entity_id or
            entry.player_id != ref.player_id or entry.zone_epoch > ref.zone_epoch or entity.zone_epoch < ref.zone_epoch):
        raise ValueError('Hand selection differs from its original physical acquisition')
    return entry


@dataclass(frozen=True)
class RememberHandForDeathrattle(Effect):
    card: CardReference
    hand_entry_id: int
    reference: MinionReference
    ability_ids: tuple[int, ...]

    def __post_init__(self):
        if type(self.card) is not CardReference:
            raise ValueError('Native hand selection requires its typed original physical card')
        self.card.__post_init__(); reference_value(self.reference)
        _integer(self.hand_entry_id, 'selected original acquisition', 1)
        if self.card.zone != Zone.HAND or self.card.player_id != 3 - self.reference.player_id:
            raise ValueError('Native selection requires the original opposing hand')
        if type(self.ability_ids) is not tuple or len(set(self.ability_ids)) != len(self.ability_ids):
            raise ValueError('Native hand memory requires distinct original ability identities')
        for identity in self.ability_ids:
            _integer(identity, 'original hand-selection ability', 1)

    def validate_in_state(self, state, registry):
        self.__post_init__()
        from .deathrattle_memory import validate_reference
        validate_reference(state, self.reference, self.ability_ids)
        validate_hand_link(state, self.card, self.hand_entry_id)
        registry.card(self.card.card_id)


def remember(r, effect):
    effect.validate_in_state(r.state, r.registry)
    source = same_instance(r.state, effect.reference)
    entity = r.state.entities[effect.card.entity_id]
    if source is None or (entity.zone, entity.controller, entity.hand_entry_id) != (
            Zone.HAND, effect.card.player_id, effect.hand_entry_id):
        return ()
    from .deathrattle_memory import validate_ability
    replacements = {}
    for ability in source.abilities:
        if ability.id not in effect.ability_ids:
            continue
        validate_ability(r.state, r.registry, ability)
        memory = ability.deathrattle_memory
        if memory is None or memory.spec.kind != 'hand_selection':
            raise ResolutionError('Original native hand-selection ability changed its declaration')
        replacements[ability.id] = replace(ability, deathrattle_memory=replace(memory,
            hand_entry_ids=(*memory.hand_entry_ids, effect.hand_entry_id)))
    source.abilities = [replacements.get(a.id, a) for a in source.abilities]


@dataclass(frozen=True)
class DiscardRememberedHand(Effect):
    deathrattle_id: int
    hand_entry_id: int

    def __post_init__(self):
        _integer(self.deathrattle_id, 'actual native Deathrattle invocation', 1)
        _integer(self.hand_entry_id, 'remembered original hand acquisition', 1)


def discard(r, effect):
    effect.__post_init__()
    from .deathrattles import record
    row = record(r.state, effect.deathrattle_id)
    memory = row.capture.ability.deathrattle_memory
    if (row.execution_order is None or row.completed or row.interrupted or memory is None or
            memory.spec.kind != 'hand_selection' or effect.hand_entry_id not in memory.hand_entry_ids):
        raise ResolutionError('Selected hand discard lost its actual accepted Deathrattle payload')
    entry = hand_entry(r.state, effect.hand_entry_id)
    entity = r.state.entities[entry.entity_id]
    if (entity.zone, entity.controller, entity.hand_entry_id) != (Zone.HAND, entry.player_id, entry.id):
        return ()
    return discard_card(r, DiscardCard(CardReference.capture(entity), row.capture.carrier_id))


def validate_program(state, registry, player_id, instance):
    spec = registry.player_effect(instance.spec_id)
    value = instance.investigation
    if spec.kind != 'hand_investigation':
        if value is not None:
            raise ValueError('Unrelated player effect borrowed private investigation material')
        return
    validate_investigation(state, registry, player_id, value)


def validate_investigation(state, registry, player_id, value):
    if type(value) is not HandInvestigation:
        raise ValueError('An investigation requires its original typed target')
    value.__post_init__()
    entry = hand_entry(state, value.hand_entry_id)
    from .owner_turns import owner_turn_index
    if (entry.player_id != 3 - player_id or value.opponent_id != entry.player_id or
            value.owner_turn_index > owner_turn_index(state, value.opponent_id) + 1 or
            not registry.card(value.card_id).hand_playable):
        raise ValueError('Investigation borrowed another opponent, future interval or unknown selected face')


def register(mechanics):
    for cls, handler in ((InspectHandCards, inspect), (RememberHandForDeathrattle, remember),
                         (DiscardRememberedHand, discard), (GuessOpponentHandCard, guess_hand)):
        mechanics.register(cls, handler)
    mechanics.register_payload_type(HandInvestigation)
