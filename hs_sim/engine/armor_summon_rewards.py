"""One exact armor debit rewards the original successful fixed summon group."""
from .runtime_copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass, replace
from .armor_consumption import SpendArmor, result_at
from .board_presence import resolve_board_presence
from .death_neighbors import BuffBoardPresence, apply_buff as buff_board_presence
from .effects import Effect, _integer
from .model import BoardPresenceReference, CardType, GameState, Zone, _name
from .original_summon_groups import recipients, root_prefix
from .owner_turns import validate_accepted_prefix
from .registry import RuleContext

ACCEPTED = 'armor_summon_reward_accepted'
FINISHED = 'armor_summon_reward_finished'


def caller(c):
    if (type(c) is not RuleContext or c.source.kind != CardType.LOCATION or c.source.zone != Zone.BOARD or
            c.source.controller != c.player_id or c.source.uses_this_turn < 1 or c.source.location_cooldown != 2):
        raise ValueError('Armor summon reward requires its original activated Location context')


@dataclass(frozen=True)
class SpendArmorForSummonedGroup(Effect):
    original: RuleContext
    card_id: str
    amount: int
    attack: int
    health: int

    def __post_init__(self):
        caller(self.original); _name(self.card_id, 'armor reward fixed minion')
        _integer(self.amount, 'armor reward exact debit', 1)
        _integer(self.attack, 'armor reward attack', 0); _integer(self.health, 'armor reward health', 0)


@dataclass(frozen=True)
class FinishArmorSummonReward(Effect):
    request: SpendArmorForSummonedGroup
    accepted: RuleContext
    summon_ids: tuple[int, ...]
    event_cursor: int
    root_action_number: int

    def __post_init__(self):
        if type(self.request) is not SpendArmorForSummonedGroup:
            raise ValueError('Armor reward requires its complete original request')
        self.request.__post_init__()
        if type(self.accepted) is not RuleContext or (self.accepted.source_id, self.accepted.player_id) != (
                self.request.original.source_id, self.request.original.player_id):
            raise ValueError('Armor reward changed its accepted caller')
        if (type(self.summon_ids) is not tuple or any(type(x) is not int or x < 1 for x in self.summon_ids) or
                len(set(self.summon_ids)) != len(self.summon_ids)):
            raise ValueError('Armor reward requires complete unique original recipients')
        _integer(self.event_cursor, 'armor reward acceptance event', 1)
        _integer(self.root_action_number, 'armor reward root action', 0)


def references(state, ids):
    return tuple(BoardPresenceReference(state.successful_summon_history[i-1].entity_id,
        state.successful_summon_history[i-1].minion.entered_order) for i in ids)


def live(state, ref, player_id):
    entity = resolve_board_presence(state, ref)
    return entity is not None and entity.controller == player_id and entity.active and entity.health > 0 and not entity.doomed


def validate_request(registry, request):
    request.__post_init__()
    if registry.card(request.card_id).kind != CardType.MINION or registry.card(request.original.source.card_id).on_use is None:
        raise ValueError('Armor reward requires an actual named minion and printed Location body')


def acceptance_data(effect):
    q = effect.request; c = effect.accepted
    return dict(card_id=q.card_id, armor_cost=q.amount, attack=q.attack, health=q.health,
        summon_ids=effect.summon_ids, root_action_number=effect.root_action_number,
        source_card_id=q.original.source.card_id, turn=c.state.turn)


def validate_finish(game, effect):
    effect.__post_init__(); q = effect.request; old = q.original; c = effect.accepted
    validate_request(game.registry, q)
    if effect.summon_ids != recipients(old, c, game.registry, q.card_id, 1):
        raise ValueError('Armor reward changed its complete original summon group')
    validate_accepted_prefix(c.state, game._state, game.registry); root_prefix(c.state, game._state)
    if game._state.successful_summon_history[:len(c.state.successful_summon_history)] != c.state.successful_summon_history:
        raise ValueError('Armor reward changed its original successful entries')
    if not any(live(c.state, ref, c.player_id) for ref in references(c.state, effect.summon_ids)):
        raise ValueError('Armor reward paid without a live original recipient')
    from .hero_health_history import effective_events
    event = next((e for e in effective_events(game._events) if e.sequence == effect.event_cursor), None)
    if (event is None or event.kind != ACCEPTED or dict(event.data) != acceptance_data(effect) or
            (event.source_id, event.player_id, event.action) != (old.source_id, old.player_id, c.state.action_number)):
        raise ValueError('Armor reward lost its original complete acceptance')
    row = result_at(game, effect.event_cursor+1)
    hero = c.state.entities[c.state.players[c.player_id].hero_id]
    if (row.source_id, row.player_id, row.hero_id, row.requested, row.before, row.turn, row.action, row.root_action_number) != (
            old.source_id, old.player_id, hero.id, q.amount, hero.armor, c.state.turn, c.state.action_number, effect.root_action_number):
        raise ValueError('Armor reward borrowed another debit, amount or Hero')
    return row


def resolve(r, request):
    validate_request(r.registry, request); old = request.original
    accepted = replace(old, state=deepcopy(r.state))
    ids = recipients(old, accepted, r.registry, request.card_id, 1)
    if not any(live(r.state, ref, old.player_id) for ref in references(accepted.state, ids)):
        r.emit('armor_summon_reward_skipped', source_id=old.source_id, player_id=old.player_id,
            reason='no_live_original_recipient', _capture=False)
        return ()
    finish = FinishArmorSummonReward(request, accepted, ids, len(r.game._events)+1, r.root_action_number)
    r.emit(ACCEPTED, source_id=old.source_id, player_id=old.player_id, _capture=False, **acceptance_data(finish))
    return (SpendArmor(old.player_id, request.amount, old.source_id), finish)


def finish(r, effect):
    row = validate_finish(r.game, effect); q = effect.request; old = q.original
    if row.actual:
        from .resolver import buff
        for ref in references(effect.accepted.state, effect.summon_ids):
            for work in buff_board_presence(r, BuffBoardPresence(ref, old.player_id, q.attack, q.health, old.source_id)):
                buff(r, work)
    r.emit(FINISHED, source_id=old.source_id, player_id=old.player_id, acceptance=effect.event_cursor,
        actual=row.actual, _capture=False)
    return ()


def validate_boundary(game):
    if game._frame is None:
        return
    def visit(value, depth=0):
        if depth > 64: raise ValueError('Armor reward frame nesting exceeds limit')
        if type(value) is FinishArmorSummonReward: validate_finish(game, value); return
        if type(value) is SpendArmorForSummonedGroup: validate_request(game.registry, value); return
        if type(value) in (RuleContext, GameState): return
        if isinstance(value, (tuple, list)):
            for item in value: visit(item, depth+1)
        elif isinstance(value, dict):
            for item in value.values(): visit(item, depth+1)
        elif is_dataclass(value) and not isinstance(value, type):
            for field in fields(value): visit(getattr(value, field.name), depth+1)
    f = game._frame
    visit((f.prefix, f.continuation, f.options, f.paid_hand_choice_boundary))


def register(mechanics):
    mechanics.register(SpendArmorForSummonedGroup, resolve)
    mechanics.register(FinishArmorSummonReward, finish)
