"""Constructed opening, using the same suspendable interpreter as combat."""
from .hand_capacity import hand_capacity
from dataclasses import dataclass, replace

from .effects import AddToHand, ChoiceOption, Draw, Effect, RequestChoice
from .errors import ResolutionError
from .model import CardType, ChoicePurpose, Zone
from .resources import begin_mana_turn


@dataclass(frozen=True)
class BeginGame(Effect):
    pass


@dataclass(frozen=True)
class DealOpeningHands(Effect):
    pass


@dataclass(frozen=True)
class OfferMulligan(Effect):
    player_id: int


@dataclass(frozen=True)
class MarkMulligan(Effect):
    player_id: int
    entity_id: int


@dataclass(frozen=True)
class FinishMulligan(Effect):
    player_id: int


@dataclass(frozen=True)
class CompleteOpening(Effect):
    pass


@dataclass(frozen=True)
class StartFirstTurn(Effect):
    pass


@dataclass(frozen=True)
class ExecuteOpeningHook(Effect):
    source_id: int
    player_id: int
    behavior_id: str


def opening_order(state):
    first = state.opening.first_player
    return first, 3 - first


def hooks(r, phase):
    from .opening_deck_copies import hook_pairs
    return [ExecuteOpeningHook(entity_id, player_id, hook.behavior_id)
            for player_id in opening_order(r.state)
            for entity_id, card_id in hook_pairs(r.state,player_id)
            for hook in r.registry.card(card_id).opening_hooks if hook.phase == phase]


def begin_game(r, effect):
    if r.state.opening.stage != 'dealing':
        raise ResolutionError('Opening already began')
    from .opening_deck_copies import prepare
    prepare(r)
    for player in r.state.players.values():
        r.game._rng.shuffle(player.deck)
    r.emit('game_created', player_id=r.state.active_player, policy_id=r.game._match_setup.policy.id,
           mode=r.game._match_setup.policy.mode)
    return [*hooks(r, 'before_deal'), DealOpeningHands()]


def execute_hook(r, effect):
    r.emit('opening_effect', source_id=effect.source_id, player_id=effect.player_id,
           behavior_id=effect.behavior_id, stage=r.state.opening.stage)
    return [r.call(effect.behavior_id, effect.source_id, effect.player_id)]


def deal_opening_hands(r, effect):
    opening = r.state.opening
    if opening.stage != 'dealing':
        raise ResolutionError('Opening hand was already dealt')
    offered = [(), ()]
    for player_id in opening_order(r.state):
        player = r.player(player_id)
        amount = 3 if player_id == opening.first_player else 4
        if len(player.deck) < amount or len(player.hand) + amount > hand_capacity(player, r.rules):
            raise ResolutionError('Opening hand cannot be dealt with current deck/hand capacity')
        guaranteed = [i for i in player.deck if (q := r.registry.card(r.state.entities[i].card_id).quest)
                      is not None and q.starts_in_hand]
        if len(guaranteed) > amount:
            raise ResolutionError('Too many guaranteed opening cards for the configured hand')
        cards = tuple(guaranteed + [i for i in player.deck if i not in guaranteed][:amount - len(guaranteed)])
        for entity_id in cards:
            r.move(r.state.entities[entity_id], Zone.HAND)
        offered[player_id - 1] = cards
    r.state.opening = replace(opening, stage='mulligan', offered=tuple(offered))
    for player_id in opening_order(r.state):
        r.emit('opening_hand_dealt', player_id=player_id, entity_ids=offered[player_id - 1])
    first, second = opening_order(r.state)
    return [OfferMulligan(first), FinishMulligan(first), OfferMulligan(second), FinishMulligan(second), CompleteOpening()]


def offer_mulligan(r, effect):
    opening = r.state.opening
    if (opening.stage != 'mulligan' or len(opening.completed) >= 2 or
            opening_order(r.state)[len(opening.completed)] != effect.player_id):
        raise ResolutionError('Mulligan is out of sequence')
    offered = opening.offered[effect.player_id - 1]
    options = tuple(ChoiceOption(str(i), r.registry.card(r.state.entities[i].card_id).name,
                    (MarkMulligan(effect.player_id, i),), card_id=r.state.entities[i].card_id, entity_id=i) for i in offered)
    return [RequestChoice(effect.player_id, options, r.player(effect.player_id).hero_id,
                          prompt='选择要替换的起始手牌', min_count=0, max_count=len(options), purpose=ChoicePurpose.MULLIGAN)]


def mark_mulligan(r, effect):
    opening = r.state.opening
    selected = list(opening.selected)
    index = effect.player_id - 1
    if (opening.stage != 'mulligan' or effect.player_id in opening.completed or
            effect.entity_id not in opening.offered[index] or effect.entity_id in selected[index]):
        raise ResolutionError('Invalid mulligan entity')
    selected[index] += (effect.entity_id,)
    r.state.opening = replace(opening, selected=tuple(selected))


def finish_mulligan(r, effect):
    opening = r.state.opening
    if (opening.stage != 'mulligan' or len(opening.completed) >= 2 or
            effect.player_id != opening_order(r.state)[len(opening.completed)]):
        raise ResolutionError('Mulligan submitted twice or out of sequence')
    r.state.opening = replace(opening, completed=opening.completed + (effect.player_id,))
    r.emit('mulligan_submitted', player_id=effect.player_id, count=len(opening.selected[effect.player_id - 1]))


def complete_opening(r, effect):
    opening = r.state.opening
    if opening.stage != 'mulligan' or len(opening.completed) != 2:
        raise ResolutionError('Both players must submit mulligans first')
    for player_id in opening_order(r.state):
        player = r.player(player_id)
        selected = opening.selected[player_id - 1]
        if any(i not in player.hand for i in opening.offered[player_id - 1]):
            raise ResolutionError('An offered mulligan entity left the hand')
        if len(player.deck) < len(selected):
            raise ResolutionError('Not enough replacement cards outside the opening hand')
        if selected:
            hand = tuple(player.hand)
            # Capture replacements before putting rejected entities into the deck.
            replacements = tuple(player.deck[:len(selected)])
            for entity_id in replacements:
                r.move(r.state.entities[entity_id], Zone.HAND)
            # Reserve the actual replacement slots first. A full runtime deck
            # must not reject an atomic mulligan whose final size is unchanged.
            for entity_id in selected:
                r.move(r.state.entities[entity_id], Zone.DECK)
            slots = dict(zip(selected, replacements))
            player.hand[:] = [slots.get(i, i) for i in hand]
            r.game._rng.shuffle(player.deck)
            r.emit('mulligan_replaced', player_id=player_id, rejected=selected, replacements=replacements)
    r.state.opening = replace(opening, stage='starting')
    r.emit('mulligan_completed')
    return [AddToHand(3 - opening.first_player, r.game._match_setup.coin_card_id, revealed_to=(1, 2)),
            *hooks(r, 'after_mulligan'), StartFirstTurn()]


def start_first_turn(r, effect):
    opening = r.state.opening
    if opening.stage != 'starting':
        raise ResolutionError('First turn has already started')
    from .shatter import settle_hands
    settle_hands(r, opening_ready=True)
    from .starting_hands import capture
    capture(r)
    r.state.active_player = opening.first_player
    r.state.turn = 1
    player = r.player(opening.first_player)
    from .owner_turns import start_owner_turn
    start_owner_turn(r.state, len(r.game._events))
    begin_mana_turn(player)
    r.refresh_auras()
    r.emit('game_started', player_id=player.id)
    from .player_effects import turn_countdowns
    countdowns = turn_countdowns(r, player, 'turn_started')
    event = r.emit('turn_started', player_id=player.id, turn=1)
    from .owner_turns import publish_owner_start
    publish_owner_start(r.state, event)
    from .turn_start_draws import DrawAtTurnStart
    return [*countdowns, DrawAtTurnStart(player.id)]


def add_to_hand(r, effect):
    create_hand_card(r, effect)


def validate_hand_card(r, effect, *, origin_entity_id=None):
    """Validate the original creation recipe before allocation or deferral."""
    r.player(effect.player_id)
    from .carved_spells import validate_creation as validate_carved_creation
    validate_carved_creation(r.registry,effect)
    definition = r.registry.card(effect.card_id)
    if not definition.hand_playable:
        raise ResolutionError('Unsupported generated hand card type')
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Generated card source does not exist')
    if origin_entity_id is not None:
        from .effects import _integer
        _integer(origin_entity_id, 'generated historical origin', 1)
        if origin_entity_id not in r.state.entities:
            raise ResolutionError('Generated historical origin does not exist')
    from .costs import validate_creation_cost
    validate_creation_cost(r.state, effect, (definition,))
    from .card_creation import validate_creation
    validate_creation(r.state, effect, (definition,))
    return definition


def create_hand_card(r, effect, *, origin_entity_id=None, native_spell_value=None, aura_duration_source=None, live_hand_source=None, defer_publication=False):
    """Shared generated materialization; public AddToHand still returns no work."""
    definition = validate_hand_card(r,effect,origin_entity_id=origin_entity_id)
    player = r.player(effect.player_id)
    from .card_creation import install
    from .carved_spells import install as install_carved
    zone = Zone.HAND if len(player.hand) < hand_capacity(player, r.rules) else Zone.GRAVEYARD
    entity = r.create_entity(player.id, definition.id, zone, hand_entry_source_id=effect.source_id)
    entity.origin_entity_id = origin_entity_id
    if effect.cost is not None:
        from .costs import attach_cost
        attach_cost(r.state, entity, effect.cost, effect.source_id, effect.expires_turn)
    install(r.state, entity, effect, resolver=r)
    install_carved(r.registry,entity,getattr(effect,'carved_spell_id',None))
    if native_spell_value is not None:
        from .native_spell_values import install as install_native_spell_value
        install_native_spell_value(r.state,r.registry,entity,native_spell_value)
    if aura_duration_source is not None:
        from .aura_duration import install as install_aura_duration
        install_aura_duration(r.state, r.registry, entity, aura_duration_source)
    if live_hand_source is not None:
        from .live_hand_spells import bind_created
        bind_created(r, entity, live_hand_source)
    if not defer_publication:announce_hand_card(r,effect,entity)
    return entity


def announce_hand_card(r,effect,entity):
    player=r.player(effect.player_id);zone=entity.zone
    for viewer in effect.revealed_to:
        r.game._information.players[viewer].remember(entity)
    r.emit('card_created', source_id=effect.source_id, target_id=entity.id, player_id=player.id)
    if zone==Zone.GRAVEYARD:
        from .zones import emit_burn
        emit_burn(r,entity,profile='created_overflow',source_id=effect.source_id,reason='generated')
    else:
        r.emit('card_added_to_hand',source_id=effect.source_id,target_id=entity.id,player_id=player.id,reason='generated')


def register_opening(mechanics):
    for kind, handler in ((BeginGame, begin_game), (ExecuteOpeningHook, execute_hook),
                          (DealOpeningHands, deal_opening_hands), (OfferMulligan, offer_mulligan),
                          (MarkMulligan, mark_mulligan), (FinishMulligan, finish_mulligan),
                          (CompleteOpening, complete_opening), (StartFirstTurn, start_first_turn),
                          (AddToHand, add_to_hand)):
        mechanics.register(kind, handler)


def original_deck_entities(setup):
    """MatchSetup creates one hero, one power, then each original deck row.

    This is the allocation order of Game.from_decks' fixed Scenario, before
    any opening hook, draw, generated entity or later lifecycle operation.
    Current faces/zones/hero slots cannot reconstruct those original rows.
    """
    cursor = 1
    groups = []
    for deck in setup.decks:
        cursor += 2
        groups.append(tuple(range(cursor, cursor + len(deck.cards))))
        cursor += len(deck.cards)
    return tuple(groups)


def validate_opening_boundary(game):
    from .opening_turn_order import validate_boundary as validate_turn_order,fixed_first
    validate_turn_order(game)
    setup, opening = game._match_setup, game._state.opening
    if setup is None:
        if opening is not None:
            raise ValueError('Opening state requires a match setup')
        return
    if opening is None:
        raise ValueError('Constructed match requires an opening record')
    from .opening_deck_copies import validate_boundary as validate_deck_copies
    validate_deck_copies(game)
    from .starting_hands import validate_boundary as validate_starting_hands
    validate_starting_hands(game)
    expected_first=fixed_first(setup,game.registry)
    if expected_first is not None and expected_first != opening.first_player:
        raise ValueError('First player differs from the fixed setup')
    if opening.original_entities != original_deck_entities(setup):
        raise ValueError('Starting deck physical allocation differs from the match setup')
    for player_id, deck in enumerate(setup.decks, 1):
        player = game._state.players[player_id]
        if (player.deck_class != deck.card_class or player.runes != deck.runes or player.original_deck != deck.cards or
                len(opening.original_entities[player_id - 1]) != len(deck.cards)):
            raise ValueError('Starting deck identity differs from the match setup')
    if opening.stage == 'complete' or game._state.status != 'playing':
        return
    if game._state.turn != 1 or game._state.active_player != opening.first_player or game._state.pending_choice is None:
        raise ValueError('An unfinished opening requires a pending choice on turn 1')
    if opening.stage == 'mulligan' and game._state.pending_choice.purpose == ChoicePurpose.MULLIGAN:
        if len(opening.completed) >= 2:
            raise ValueError('Completed mulligans must advance the opening')
        chooser = opening_order(game._state)[len(opening.completed)]
        choice = game._state.pending_choice
        offered = opening.offered[chooser - 1]
        if (choice.player_id != chooser or choice.min_count != 0 or choice.max_count != len(offered) or
                tuple(o.entity_id for o in choice.options) != offered or
                any(i not in game._state.players[chooser].hand for i in offered)):
            raise ValueError('Pending mulligan and opening hand differ')
