"""Ordered physical draws and rewards over their original hand arrivals.

This is a continuation over draw_one, not another draw/history implementation.
Normal slots take the top card and fatigue; matching slots randomly tutor and
skip an empty match. No candidate list or group material is player information.
"""
from dataclasses import dataclass, field

from .costs import local_cost
from .copy_materials import CapturedCardCopyMaterial, validate_captured_card_copy
from .draw_casts import draw_one, draw_record
from .effects import ChoiceOption, Effect, RequestChoice, _behavior, _integer, _player
from .errors import ResolutionError, ResolutionLimitExceeded
from .hand_upgrades import BuffStoredCard, SetStoredMinionStats
from .kindred import has_native_kindred
from .model import BoardPresenceReference, CardType, CostSpec, Keyword, PaymentType, SpellSchool, Zone
from .play_history import starting_deck_identity
from .pools import PoolQuery
from .registry import UnsupportedDefinitionError
from .tribes import TribeState, tribe_state
from .zones import CardReference, CopyCard, ModifyStoredCost, MoveCard, reference_entity, zone_candidates

SPELL_COST_FOLLOWUP = 'qualified_spell_cost_followup'
FROST_FOLLOWUP = 'qualified_both_frost_spells_followup'
SOURCE_KEYWORDS = 'source_rush_taunt_shield'
SOURCE_SPELL_STATS = 'source_spell_cost_stats'
TUTOR_KEYWORDS = (Keyword.RUSH, Keyword.TAUNT, Keyword.DIVINE_SHIELD)
QUALIFIED_FOLLOWUPS = frozenset(('qualified_non_minion_followup', 'qualified_both_minions_followup', SPELL_COST_FOLLOWUP, FROST_FOLLOWUP))
COPY_REWARDS = frozenset(('copy_other', 'copy_self', 'discover_spell_copy', SPELL_COST_FOLLOWUP, SOURCE_SPELL_STATS))


@dataclass(frozen=True)
class DrawGroupSlot:
    query: PoolQuery | None = None
    current_cost: int | None = None
    starting_deck: bool | None = None
    different_tribes: bool = False
    different_costs: bool = False
    max_current_cost: int | None = None
    current_deathrattle: bool | None = None
    different_cards: bool = False
    current_keywords_all: tuple[Keyword, ...] = ()

    def __post_init__(self):
        if self.query is not None:
            if type(self.query) is not PoolQuery: raise ValueError('Draw slot requires a typed query')
            self.query.__post_init__()
        if self.current_cost is not None: _integer(self.current_cost, 'draw slot current deck cost', 0)
        if self.max_current_cost is not None:
            _integer(self.max_current_cost,'draw slot maximum current deck cost',0)
            if self.current_cost is not None and self.current_cost>self.max_current_cost:raise ValueError('Draw current cost exceeds its maximum')
        if self.current_deathrattle is not None and(type(self.current_deathrattle)is not bool or self.query is None or self.query.kinds not in((),(CardType.MINION,))):
            raise ValueError('Current Deathrattle draw filter requires its broad/minion query and exact boolean')
        if (type(self.current_keywords_all) is not tuple or self.current_keywords_all and (
                self.query is None or len(self.current_keywords_all) != 1 or
                self.current_keywords_all[0] not in (*TUTOR_KEYWORDS, Keyword.LIFESTEAL) or
                type(self.current_keywords_all[0]) is not Keyword)):
            raise ValueError('Current keyword tutor requires one actual Rush/Taunt/Shield/Lifesteal filter')
        if self.starting_deck is not None and type(self.starting_deck) is not bool:
            raise ValueError('Draw origin requires an explicit boolean or no filter')
        if any(type(v) is not bool for v in (self.different_tribes,self.different_costs,self.different_cards)): raise ValueError('Distinct draw filters require booleans')
        if self.query is None and (self.current_cost is not None or self.starting_deck is not None or self.different_tribes or self.different_costs or self.max_current_cost is not None or self.current_deathrattle is not None or self.different_cards):
            raise ValueError('An ordinary top draw cannot carry matching filters')
        if self.different_tribes and self.query.kinds != (CardType.MINION,):
            raise ValueError('Distinct tribes require an explicit physical minion query')


@dataclass(frozen=True)
class DrawGroupReward:
    kind: str = 'none'
    amount: int = 0
    repetitions: int = 1
    source: BoardPresenceReference | None = None
    behavior_id: str | None = None
    target_id: int | None = field(default=None, kw_only=True)

    def __post_init__(self):
        if type(self.repetitions)is not int or self.repetitions not in(1,2)or self.repetitions!=1 and self.kind not in('cost_all','set_cost_all'):
            raise ValueError('Only the actual native Kindred whole-group cost reward repeats')
        if self.kind == 'trigger_drawn_deathrattles':
            if (type(self.amount) is not int or self.amount != 0 or self.repetitions != 1 or
                    self.source is not None or self.behavior_id is not None or self.target_id is not None):
                raise ValueError('Drawn Deathrattles require the plain original draw reward')
            return
        if self.kind not in ('none', 'cost_all', 'cost_drawn_minions', 'cost_drawn_spells', 'cost_original_spells', 'combine_original_choose_one', 'set_cost_all', 'set_stats_cost_all', 'set_drawn_minion_stats', 'buff_all', 'cost_one', 'give_one', 'lock_all', 'copy_other', 'copy_self', 'discover_spell_copy', 'source_charge_if_both_minions', 'non_minion_followup', 'refresh_drawn_spells', 'discard_drawn_spells', 'discard_drawn_minions', 'destroy_drawn_after_ends', 'health_payment_all', 'give_drawn_spells', SOURCE_KEYWORDS, SOURCE_SPELL_STATS) and self.kind not in QUALIFIED_FOLLOWUPS:
            raise ValueError('Unknown physical draw-group reward')
        if self.kind == 'non_minion_followup' or self.kind in QUALIFIED_FOLLOWUPS:
            _behavior(self.behavior_id)
        elif self.behavior_id is not None:
            raise ValueError('Only original non-minion draw followups declare a callback')
        if self.kind in ('source_charge_if_both_minions', SOURCE_KEYWORDS, SOURCE_SPELL_STATS) or self.kind in QUALIFIED_FOLLOWUPS and self.source is not None:
            if type(self.source) is not BoardPresenceReference: raise ValueError('Draw-conditioned Charge requires its original board residence')
            self.source.__post_init__()
        elif self.source is not None: raise ValueError('Only the native draw-conditioned source reward captures board residence')
        if self.target_id is not None:
            _integer(self.target_id, 'original draw followup target', 1)
            if self.kind not in QUALIFIED_FOLLOWUPS:
                raise ValueError('Only qualified selected rewards carry an original target')
        _integer(self.amount, 'draw reward amount', 0)
        if self.kind!='set_cost_all'and(self.kind in ('cost_all', 'cost_drawn_minions', 'cost_drawn_spells', 'cost_original_spells', 'set_stats_cost_all', 'set_drawn_minion_stats', 'buff_all', 'cost_one', 'lock_all', 'refresh_drawn_spells', 'destroy_drawn_after_ends')) != (self.amount > 0):
            raise ValueError('Draw reward amount differs from its operation')


@dataclass(frozen=True)
class DrawGroupArrival:
    slot: int
    draw_id: int | None
    hand: CardReference | None = None
    tribes: TribeState | None = None
    hand_cursor: int = 0
    cost: int | None = None
    copy: CapturedCardCopyMaterial | None = None

    def __post_init__(self):
        _integer(self.slot, 'original draw slot', 0); _integer(self.hand_cursor, 'original hand-entry cursor', 0)
        if self.draw_id is not None: _integer(self.draw_id, 'original group draw', 1)
        elif self.hand is not None or self.tribes is not None or self.hand_cursor or self.cost is not None or self.copy is not None:
            raise ValueError('An empty matching slot cannot claim an actual draw or hand arrival')
        if self.hand is not None:
            if type(self.hand) is not CardReference or self.hand.zone != Zone.HAND:
                raise ValueError('Draw-group beneficiary requires an original hand reference')
            self.hand.__post_init__()
        if self.tribes is not None:
            if type(self.tribes) is not TribeState: raise ValueError('Draw type requires a complete effective tribe state')
            self.tribes.__post_init__()
            if not self.tribes.members: raise ValueError('A typed draw cannot capture an empty tribe set')
        if self.cost is not None: _integer(self.cost,'original selected deck cost',0)
        if self.copy is not None:
            if type(self.copy)is not CapturedCardCopyMaterial: raise ValueError('Draw copy requires complete original material')
            self.copy.__post_init__()


@dataclass(frozen=True)
class DrawPhysicalGroup(Effect):
    player_id: int
    source_id: int
    slots: tuple[DrawGroupSlot, ...]
    reward: DrawGroupReward = DrawGroupReward()
    kindred_pair: bool = field(default=False, kw_only=True)

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'physical draw source', 1)
        if type(self.slots) is not tuple or not self.slots or any(type(s) is not DrawGroupSlot for s in self.slots):
            raise ValueError('Draw group requires ordered immutable typed slots')
        for slot in self.slots: slot.__post_init__()
        if type(self.reward) is not DrawGroupReward: raise ValueError('Draw group requires a typed reward')
        self.reward.__post_init__()
        if type(self.kindred_pair) is not bool: raise ValueError('Kindred draw pair requires an exact boolean')
        if self.kindred_pair and self.slots != (DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,CardType.SPELL))),)*2:
            raise ValueError('Native Kindred draw pair requires exactly two broad physical card slots')
        if self.reward.kind in ('buff_all', 'set_stats_cost_all') and any(s.query is None or s.query.kinds != (CardType.MINION,) for s in self.slots):
            raise ValueError('Minion draw buffs require explicit minion slots')
        if self.reward.kind == 'cost_original_spells' and (
                self.kindred_pair or self.slots != (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)*2):
            raise ValueError('Original spell discount requires exactly two physical spell tutor roots')
        if self.reward.kind == 'combine_original_choose_one' and (
                self.kindred_pair or self.slots != (DrawGroupSlot(PoolQuery(choose_one=True)),)):
            raise ValueError('Combined original draw requires exactly one Choose One tutor root')
        if self.reward.kind == 'source_charge_if_both_minions' and (self.slots != (DrawGroupSlot(), DrawGroupSlot()) or self.reward.source.entity_id != self.source_id):
            raise ValueError('Draw-conditioned Charge requires exactly two ordinary draws and the original source')
        if self.reward.kind == SOURCE_KEYWORDS and (self.kindred_pair or self.reward.source.entity_id != self.source_id or
                self.slots != tuple(DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,)), current_keywords_all=(key,)) for key in TUTOR_KEYWORDS)):
            raise ValueError('Native source keywords require the complete Rush/Taunt/Shield minion tutor sequence')
        if self.reward.kind==SOURCE_SPELL_STATS and(self.kindred_pair or self.reward.source.entity_id!=self.source_id or
                self.slots!=(DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)*2):
            raise ValueError('Original spell/stat swap requires its exact two spell slots and original source')
        if self.reward.kind == FROST_FOLLOWUP and (self.kindred_pair or self.reward.source is not None or self.reward.target_id is not None or
                self.slots != (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)*2):
            raise ValueError('Frost draw followup requires its complete original two-spell tutor sequence')
        if self.reward.kind == SPELL_COST_FOLLOWUP and (
                self.slots != (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,),exclude_source=True)),) or
                self.kindred_pair or self.reward.source is not None or self.reward.target_id is not None):
            raise ValueError('Selected spell-cost followup requires one source-excluding original spell tutor')
        if self.reward.kind in QUALIFIED_FOLLOWUPS-{SPELL_COST_FOLLOWUP, FROST_FOLLOWUP} and (self.slots != (DrawGroupSlot(),)*2 or
                self.kindred_pair or self.reward.source is not None and self.reward.source.entity_id != self.source_id):
            raise ValueError('Qualified text rewards require exactly two original ordinary draws')
        if self.reward.kind in ('refresh_drawn_spells','discard_drawn_spells','discard_drawn_minions') and (
                self.kindred_pair or self.slots != (DrawGroupSlot(),)*(2 if self.reward.kind=='refresh_drawn_spells' else 3)):
            raise ValueError('Native spell-draw rewards require their complete two/three ordinary root slots')
        if self.reward.kind == 'discover_spell_copy' and (
                self.kindred_pair or self.slots != (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)*3):
            raise ValueError('Original spell-copy discovery requires exactly three matching spell slots')
        if self.reward.kind == 'destroy_drawn_after_ends' and (
                self.kindred_pair or self.slots != (DrawGroupSlot(),)*3 or self.reward.amount != 3):
            raise ValueError('Burndown requires its three original ordinary draws and three owner ends')
        if self.reward.kind == 'trigger_drawn_deathrattles' and (
                self.kindred_pair or self.source_id is None or self.slots != (DrawGroupSlot(),)*5):
            raise ValueError('Drawn Deathrattles require five original ordinary source-bound draws')
        if self.reward.kind in ('health_payment_all','give_drawn_spells') and (
                self.kindred_pair or self.slots != (DrawGroupSlot(),)*(2 if self.reward.kind=='health_payment_all' else 5)):
            raise ValueError('Native payment/gift rewards require their complete two/five ordinary draw slots')


@dataclass(frozen=True)
class ContinuePhysicalDrawGroup(DrawPhysicalGroup):
    index: int = 0
    arrivals: tuple[DrawGroupArrival, ...] = ()

    def __post_init__(self):
        super().__post_init__(); _integer(self.index, 'next draw slot', 0)
        if self.index > len(self.slots) or type(self.arrivals) is not tuple or len(self.arrivals) != self.index:
            raise ValueError('Draw group exceeds its accepted slot plan')
        previous_slot = previous_draw = -1
        for row in self.arrivals:
            if type(row) is not DrawGroupArrival: raise ValueError('Draw group requires typed original arrivals')
            row.__post_init__()
            if row.slot != previous_slot + 1 or row.draw_id is not None and row.draw_id <= previous_draw:
                raise ValueError('Draw group changed its ordered unique slot/draw identities')
            if row.hand is not None and row.hand.player_id != self.player_id:
                raise ValueError('Draw group changed its original hand beneficiary')
            if row.draw_id is not None and self.slots[row.slot].different_tribes != (row.tribes is not None):
                raise ValueError('Draw group lost its original selected minion type')
            if row.draw_id is not None and self.slots[row.slot].different_costs != (row.cost is not None):
                raise ValueError('Draw group lost its original selected deck cost')
            if self.reward.kind not in COPY_REWARDS and row.copy is not None: raise ValueError('Draw group invented copy material for another reward')
            if row.draw_id is None and self.slots[row.slot].query is None:
                raise ValueError('A normal draw cannot skip its original attempt')
            previous_slot = row.slot
            if row.draw_id is not None: previous_draw = row.draw_id


@dataclass(frozen=True)
class CapturePhysicalDrawGroup(ContinuePhysicalDrawGroup):
    draw_id: int = 1
    hand_cursor: int = 0
    tribes: TribeState | None = None
    cost: int | None = None
    copy: CapturedCardCopyMaterial | None = None

    def __post_init__(self):
        super().__post_init__(); _integer(self.draw_id, 'pending original root draw', 1)
        _integer(self.hand_cursor, 'pending original hand-entry cursor', 0)
        if self.index >= len(self.slots): raise ValueError('Pending draw is outside its original slot plan')
        DrawGroupArrival(self.index, self.draw_id, None, self.tribes, self.hand_cursor,self.cost,self.copy).__post_init__()
        if self.slots[self.index].different_tribes != (self.tribes is not None):
            raise ValueError('Pending draw changed its original minion type')
        if self.slots[self.index].different_costs != (self.cost is not None): raise ValueError('Pending draw changed its selected deck cost')
        if self.reward.kind not in COPY_REWARDS and self.copy is not None: raise ValueError('Pending draw invented copy material')


def arrival_reference(state, root_id, hand_cursor):
    """Follow only this root's replacement chain, then its original entry.

    Each accepted draw binds its actual hand entry. Explicit transformations
    carry their resulting residence without borrowing a later reacquisition.
    """
    root = record = draw_record(state, root_id)
    if not root.completed: raise ValueError('Physical draw reward precedes root completion')
    while record.replacement_id is not None:
        child = draw_record(state, record.replacement_id)
        if child.parent_id != record.id or not child.completed: raise ValueError('Physical draw lost its completed replacement chain')
        record = child
    if hand_cursor > len(state.hand_entries): raise ValueError('Physical draw borrowed a future hand-entry cursor')
    if record.outcome != 'hand' and record.transformation is None: return None
    from .draw_transformations import hand_reference
    if record.hand_entry_id is not None and record.hand_entry_id<=hand_cursor:
        raise ValueError('Physical draw borrowed a hand entry before its accepted group')
    return hand_reference(state,record,completed=True)


def validate_material(state, registry, request, *, completed=False):
    """Also used by the frame codec; no query, randomness or state mutation."""
    request.__post_init__()
    if request.source_id not in state.entities: raise ValueError('Draw group source does not exist')
    if request.reward.behavior_id is not None:
        registry.behavior(request.reward.behavior_id)
    if request.reward.target_id is not None and request.reward.target_id not in state.entities:
        raise ValueError('Draw followup changed its original selected target')
    if request.reward.source is not None:
        ref = request.reward.source
        if ref.presence_id >= state.next_order or state.entities[ref.entity_id].kind != CardType.MINION:
            raise ValueError('Draw reward borrowed an unknown or future source residence')
    for slot in request.slots:
        if slot.starting_deck is not None: starting_deck_identity(state)
    for row in getattr(request, 'arrivals', ()):
        if row.draw_id is None: continue
        record = draw_record(state, row.draw_id)
        validate_distinct_card(state,registry,request,row.slot,record)
        if (request.reward.kind in ('non_minion_followup', SOURCE_KEYWORDS) or request.reward.kind in QUALIFIED_FOLLOWUPS) and record.parent_id is not None:
            raise ValueError('Original type reward cannot borrow a replacement draw')
        validate_copy(state,registry,request,row,record)
        if record.player_id != request.player_id or record.source_id != request.source_id or completed and not record.completed:
            raise ValueError('Draw group lost its original completed source/player draw')
        validate_kindred_draw(state,registry,request,row.slot,record)
        if arrival_reference(state, row.draw_id, row.hand_cursor) != row.hand:
            raise ValueError('Draw group changed its original root/replacement hand outcome')
        if row.hand is not None:
            ref = row.hand; registry.card(ref.card_id); entity = state.entities.get(ref.entity_id)
            if entity is None or ref.zone_epoch > entity.zone_epoch:
                raise ValueError('Draw group changed its original physical arrival or borrowed a future residency')
        if row.tribes is not None and (record.card_id is None or registry.card(record.card_id).kind != CardType.MINION):
            raise ValueError('Typed draw group borrowed a non-minion draw')
    if type(request) is CapturePhysicalDrawGroup:
        record = draw_record(state, request.draw_id)
        validate_distinct_card(state,registry,request,request.index,record)
        validate_copy(state,registry,request,request,record)
        previous = next((row.draw_id for row in reversed(request.arrivals) if row.draw_id is not None), 0)
        if (record.player_id, record.source_id, record.parent_id) != (request.player_id, request.source_id, None) or record.id <= previous:
            raise ValueError('Pending physical draw lost its own original root attempt')
        validate_kindred_draw(state,registry,request,request.index,record)
        if request.hand_cursor > len(state.hand_entries): raise ValueError('Pending physical draw borrowed a future hand entry')


def validate_distinct_card(state,registry,request,index,record):
    if not request.slots[index].different_cards:return
    if record.parent_id is not None:raise ValueError('Different-card draw borrowed a replacement attempt')
    if record.card_id is None:return
    identity=registry.pool_card(record.card_id).generation_identity
    previous=(draw_record(state,row.draw_id)for row in request.arrivals[:index]if row.draw_id is not None)
    if any(old.card_id is not None and registry.pool_card(old.card_id).generation_identity==identity for old in previous):
        raise ValueError('Different-card draw repeated its original card identity')


def validate_copy(state,registry,request,row,record):
    if (request.reward.kind in COPY_REWARDS and record.outcome!='fatigue') != (row.copy is not None):
        raise ValueError('Draw group lost its complete original drawn-card copy material')
    if row.copy is not None:
        value=row.copy;validate_captured_card_copy(state,registry,value)
        if (value.origin.entity_id,value.origin.card_id,value.origin.controller,value.origin.zone)!=(record.entity_id,record.card_id,request.player_id,Zone.DECK):
            raise ValueError('Draw copy material differs from its original actual deck draw')


def begin(r, request):
    validate_material(r.state, r.registry, request)
    if len(request.slots) > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Physical draw group exceeds resolution budget')
    return (ContinuePhysicalDrawGroup(request.player_id, request.source_id, request.slots, request.reward,kindred_pair=request.kindred_pair),)


def shares_tribes(first, second):
    if first.members == ('all',):
        return second.members == ('all',) or first.matches_any(second.members)
    if second.members == ('all',): return second.matches_any(first.members)
    return bool(set(first.members).intersection(second.members))


def candidates(r, request, slot):
    values = zone_candidates(r, request.player_id, Zone.DECK, slot.query, request.player_id, request.source_id)
    original = None
    if slot.starting_deck is not None:
        entities, _ = starting_deck_identity(r.state); original = set(entities[request.player_id - 1])
    prior = tuple(row.tribes for row in request.arrivals if row.tribes is not None)
    prior_costs = {row.cost for row in request.arrivals if row.cost is not None}
    prior_cards={r.registry.pool_card(record.card_id).generation_identity for row in request.arrivals
        if slot.different_cards and row.draw_id is not None and (record:=draw_record(r.state,row.draw_id)).card_id is not None}
    result = []
    for ref in values:
        entity = r.state.entities[ref.entity_id]
        if slot.different_cards and r.registry.pool_card(entity.card_id).generation_identity in prior_cards:continue
        if request.kindred_pair:
            if request.index == 0:
                if not has_native_kindred(r.registry,entity.card_id): continue
            elif not activates_original_kindred(r,request,entity): continue
        if not set(slot.current_keywords_all).issubset(entity.keywords): continue
        price=max(0,local_cost(entity)[0]) if slot.current_cost is not None or slot.different_costs or slot.max_current_cost is not None else None
        if slot.current_cost is not None and price != slot.current_cost: continue
        if slot.max_current_cost is not None and price>slot.max_current_cost:continue
        if slot.current_deathrattle is not None and(bool(any(a.kind=='deathrattle'and not a.consumed for a in entity.abilities))!=slot.current_deathrattle):continue
        if slot.different_costs and price in prior_costs: continue
        if original is not None and ((entity.id in original and not entity.face_replaced) != slot.starting_deck): continue
        tribes = None
        if slot.different_tribes:
            tribes = tribe_state(r.registry, entity)
            if tribes is None: raise UnsupportedDefinitionError('Unknown complete current tribe set in physical draw group: ' + entity.card_id)
            if not tribes.members or any(shares_tribes(tribes, old) for old in prior): continue
        result.append((ref, tribes, price if slot.different_costs else None))
    return tuple(result)


def activates_original_kindred(r,request,entity):
    """The same printed type relation used by actual native Kindred accepts.

    The original first root retains its selected face through burning, draw
    replacement and later transforms. A missing first match cannot invent it.
    """
    first=request.arrivals[0]
    if first.draw_id is None:return False
    original=draw_record(r.state,first.draw_id)
    if not has_native_kindred(r.registry,original.card_id):raise ValueError('Kindred tutor lost its original selected native face')
    return kindred_type_matches(r.registry,original.card_id,entity.card_id)


def kindred_type_matches(registry,original_card_id,candidate_card_id):
    from .owner_turns import query_for_definition, share_tribes
    query=query_for_definition(registry.card(original_card_id));card=registry.card(candidate_card_id)
    if card.kind!=query.kind:return False
    if card.kind==CardType.MINION:
        if query.tribes is None or card.metadata is None or card.metadata.tribes is None:
            raise UnsupportedDefinitionError('Kindred tutor requires complete original and candidate minion tribes')
        return share_tribes(query.tribes,card.metadata.tribes)
    return query.spell_school is not None and card.spell_school==query.spell_school


def validate_kindred_draw(state,registry,request,index,record):
    if not request.kindred_pair:return
    if index==0:
        if not has_native_kindred(registry,record.card_id):raise ValueError('Kindred tutor root is not its original native Kindred face')
    else:
        first=request.arrivals[0]
        if first.draw_id is None or not kindred_type_matches(registry,draw_record(state,first.draw_id).card_id,record.card_id):
            raise ValueError('Kindred activator differs from its original selected type relation')


def advance(r, request):
    validate_material(r.state, r.registry, request, completed=True)
    if len(request.slots) > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Physical draw group exceeds resolution budget')
    if request.index == len(request.slots): return finish(r, request)
    slot = request.slots[request.index]; rows = request.arrivals; work = ()
    if slot.query is None:
        ref = tribes = price = None
    else:
        pool = candidates(r, request, slot)
        if not pool:
            return (ContinuePhysicalDrawGroup(request.player_id, request.source_id, request.slots, request.reward, request.index + 1,
                (*rows, DrawGroupArrival(request.index, None)),kindred_pair=request.kindred_pair),)
        ref, tribes, price = r.game._rng.choice(pool)
    index = len(r.state.draw_history); hand_cursor = len(r.state.hand_entries)
    original=r.state.entities[ref.entity_id]if ref is not None else r.state.entities[r.player(request.player_id).deck[0]]if r.player(request.player_id).deck else None
    material=CapturedCardCopyMaterial.capture(r.state,original)if request.reward.kind in COPY_REWARDS and original is not None else None
    work = draw_one(r, request.player_id, card=ref, source_id=request.source_id)
    if len(r.state.draw_history) != index + 1: raise ResolutionError('Physical group draw did not produce its original root attempt')
    record = r.state.draw_history[index]
    return (*work, CapturePhysicalDrawGroup(request.player_id, request.source_id, request.slots, request.reward,
        request.index, rows, record.id, hand_cursor, tribes,price,material,kindred_pair=request.kindred_pair))


def capture(r, request):
    validate_material(r.state, r.registry, request, completed=True)
    hand = arrival_reference(r.state, request.draw_id, request.hand_cursor)
    row = DrawGroupArrival(request.index, request.draw_id, hand, request.tribes, request.hand_cursor,request.cost,request.copy)
    work = ()
    if request.reward.kind == SOURCE_KEYWORDS:
        from .board_presence import resolve_board_presence
        from .sacrifice import GrantCapturedKeyword, MinionReference
        source = resolve_board_presence(r.state, request.reward.source)
        if source is not None and source.active and source.health > 0 and not source.doomed:
            work = (GrantCapturedKeyword(MinionReference.capture(source), TUTOR_KEYWORDS[request.index], request.source_id),)
    return (*work, ContinuePhysicalDrawGroup(request.player_id, request.source_id, request.slots, request.reward,
        request.index + 1, (*request.arrivals, row),kindred_pair=request.kindred_pair))


@dataclass(frozen=True)
class TriggerDrawnDeathrattle(Effect):
    player_id: int
    source_id: int
    draw_id: int
    card: CardReference

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id,'original draw source',1)
        _integer(self.draw_id,'original draw',1)
        if type(self.card) is not CardReference or self.card.player_id != self.player_id or self.card.zone != Zone.HAND:
            raise ValueError('Drawn Deathrattle requires its original physical hand arrival')
        self.card.__post_init__()

    def validate_in_state(self, state, registry):
        self.__post_init__(); row=draw_record(state,self.draw_id)
        registry.card(self.card.card_id)
        if (self.source_id not in state.entities or not row.completed or row.parent_id is not None or
                row.outcome != 'hand' or row.entity_id != self.card.entity_id or row.card_id != self.card.card_id or
                (row.player_id,row.source_id)!=(self.player_id,self.source_id)):
            raise ValueError('Drawn Deathrattle borrowed another original physical draw')
        from .hand_history import hand_entry
        entry=hand_entry(state,row.hand_entry_id)
        if (entry.entity_id,entry.player_id,entry.card_id,entry.zone_epoch)!=(
                self.card.entity_id,self.player_id,self.card.card_id,self.card.zone_epoch):
            raise ValueError('Drawn Deathrattle changed its original hand admission')


def trigger_drawn_deathrattle(r, effect):
    effect.validate_in_state(r.state,r.registry)
    entity=reference_entity(r,effect.card)
    if entity is None:return ()
    from .lifecycle import active_abilities
    from .deathrattles import schedule_group
    return tuple(schedule_group(r,entity.id,effect.player_id,tuple(active_abilities(entity,'deathrattle')),
        trigger_source_id=effect.source_id))


def finish(r, request):
    reward = request.reward
    if reward.kind == 'trigger_drawn_deathrattles':
        return tuple(TriggerDrawnDeathrattle(request.player_id,request.source_id,row.draw_id,row.hand)
            for row in request.arrivals if row.hand is not None and row.draw_id is not None and
            (record:=draw_record(r.state,row.draw_id)).outcome=='hand' and record.parent_id is None and
            (record.entity_id,record.card_id)==(row.hand.entity_id,row.hand.card_id))
    if reward.kind==SOURCE_SPELL_STATS:
        from .draw_spell_stat_swaps import swap_original_spell_costs
        return swap_original_spell_costs(r,request)
    if reward.kind in ('none', SOURCE_KEYWORDS): return ()
    if reward.kind == 'destroy_drawn_after_ends':
        from .hand_deadlines import ScheduleHandRemoval
        return (ScheduleHandRemoval(request.player_id,reward.amount,request.source_id,'destroy',
            cards=tuple(row.hand for row in request.arrivals if row.hand is not None)),)
    if reward.kind == 'refresh_drawn_spells':
        from .effects import RefreshMana
        return tuple(RefreshMana(request.player_id,reward.amount) for row in request.arrivals
            if row.draw_id is not None and (record:=draw_record(r.state,row.draw_id)).outcome in ('hand','cast') and
            record.card_id is not None and r.registry.card(record.card_id).kind==CardType.SPELL)
    if reward.kind == 'cost_original_spells':
        # The ordinary arrival policy may follow a draw-cast's replacement.
        # This native "they" reward belongs to the two original physical cards.
        # Keep an explicit same-entity transformation, but never its child draw.
        return tuple(ModifyStoredCost(row.hand,CostSpec(delta=-reward.amount),request.source_id)
            for row in request.arrivals if row.draw_id is not None and row.hand is not None and
            reference_entity(r,row.hand) is not None and
            ((record:=draw_record(r.state,row.draw_id)).outcome=='hand' or record.transformation is not None) and
            record.entity_id==row.hand.entity_id)
    if reward.kind == 'combine_original_choose_one':
        from .choose_branch_state import SetChooseBranch
        results = []
        for row in request.arrivals:
            if row.draw_id is None or row.hand is None or reference_entity(r,row.hand) is None: continue
            record = draw_record(r.state,row.draw_id)
            if record.entity_id != row.hand.entity_id or (record.outcome != 'hand' and record.transformation is None): continue
            definition = r.registry.card(row.hand.card_id)
            if definition.choose_one is None: continue
            origins = {CardType.MINION:('hand','physical'),CardType.SPELL:('hand','cast_effect','cast_draw','cast_history'),
                CardType.WEAPON:('hand',)}.get(definition.kind)
            if origins is None: raise ResolutionError('Original combined draw has no supported physical activation origin')
            results.append(SetChooseBranch(row.hand,definition.choose_one.combined.id,origins,source_id=request.source_id))
        return tuple(results)
    if reward.kind in ('discard_drawn_spells', 'discard_drawn_minions'):
        from .zones import DiscardCard, discard_cards
        kind = CardType.SPELL if reward.kind == 'discard_drawn_spells' else CardType.MINION
        targets=tuple(DiscardCard(row.hand,request.source_id) for row in request.arrivals
            if row.draw_id is not None and row.hand is not None and
            reference_entity(r,row.hand) is not None and
            ((record:=draw_record(r.state,row.draw_id)).outcome=='hand' or record.transformation is not None) and
            record.entity_id==row.hand.entity_id and r.registry.card(row.hand.card_id).kind==kind)
        return discard_cards(r,targets)
    if reward.kind == 'discover_spell_copy':
        from .draw_group_discoveries import discover
        return discover(r, request)
    if reward.kind in QUALIFIED_FOLLOWUPS:
        records = qualified_records(r.state, r.registry, request)
        return tuple(r.call(reward.behavior_id, request.source_id, request.player_id,
            target_id=reward.target_id, draw=record, draw_group=request) for record in records)
    if reward.kind == 'non_minion_followup':
        # Original root attempts determine type, including burns and draw-casts.
        # Replacement and reaction draws are not additional accepted slots.
        records = tuple(draw_record(r.state, row.draw_id) for row in request.arrivals
            if row.draw_id is not None)
        return tuple(r.call(reward.behavior_id, request.source_id, request.player_id, draw=record)
            for record in records if record.card_id is not None and
                r.registry.card(record.card_id).kind != CardType.MINION)
    if reward.kind == 'source_charge_if_both_minions':
        from .board_presence import resolve_board_presence
        from .effects import GrantKeyword
        # The roots are the actual two attempts, even when a card burned or a
        # draw-cast created a replacement chain. Never count unrelated draws.
        records = tuple(draw_record(r.state, row.draw_id) for row in request.arrivals)
        if not all(row.card_id is not None and r.registry.card(row.card_id).kind == CardType.MINION for row in records): return ()
        source = resolve_board_presence(r.state, reward.source)
        if source is None or not source.active or source.health <= 0 or source.doomed: return ()
        return (GrantKeyword(source.id, Keyword.CHARGE, request.source_id),)
    results = []; options = []
    for row in request.arrivals:
        if reward.kind in ('copy_other','copy_self'):
            recipient=request.player_id if reward.kind=='copy_self'else 3-request.player_id
            if row.copy is not None: results.append(CopyCard(row.copy,recipient,Zone.HAND,mode='current',source_id=request.source_id))
            continue
        if row.hand is None or reference_entity(r, row.hand) is None: continue
        ref = row.hand
        if reward.kind in ('cost_drawn_minions','cost_drawn_spells'):
            kind=CardType.MINION if reward.kind=='cost_drawn_minions' else CardType.SPELL
            if r.registry.card(ref.card_id).kind!=kind:continue
            effect=ModifyStoredCost(ref,CostSpec(delta=-reward.amount),request.source_id)
        elif reward.kind=='health_payment_all':
            effect=ModifyStoredCost(ref,CostSpec(payment=PaymentType.HEALTH),request.source_id)
        elif reward.kind=='give_drawn_spells':
            if r.registry.card(ref.card_id).kind!=CardType.SPELL:continue
            effect=MoveCard(ref,3-request.player_id,Zone.HAND,source_id=request.source_id)
        elif reward.kind in ('cost_all', 'cost_one'):
            effect = ModifyStoredCost(ref, CostSpec(delta=-reward.amount), request.source_id)
        elif reward.kind=='set_cost_all':
            effect=ModifyStoredCost(ref,CostSpec(set_to=reward.amount),request.source_id)
        elif reward.kind=='set_stats_cost_all':
            if r.registry.card(ref.card_id).kind!=CardType.MINION:
                effect=ModifyStoredCost(ref,CostSpec(set_to=reward.amount),request.source_id)
            else:effect=SetStoredMinionStats(ref,reward.amount,reward.amount,request.source_id,CostSpec(set_to=reward.amount))
        elif reward.kind=='set_drawn_minion_stats':
            if r.registry.card(ref.card_id).kind!=CardType.MINION:continue
            effect=SetStoredMinionStats(ref,reward.amount,reward.amount,request.source_id)
        elif reward.kind == 'buff_all':
            if r.registry.card(ref.card_id).kind!=CardType.MINION:continue
            effect = BuffStoredCard(ref, reward.amount, reward.amount, request.source_id)
        elif reward.kind == 'lock_all':
            from .hand_play_locks import LockHandCard
            effect=LockHandCard(ref,reward.amount,request.source_id)
        else:
            effect = MoveCard(ref, 3-request.player_id, Zone.HAND, source_id=request.source_id)
        if reward.kind in ('cost_one', 'give_one'):
            options.append(ChoiceOption('draw:' + str(row.draw_id), r.registry.card(ref.card_id).name, (effect,), card_id=ref.card_id, entity_id=ref.entity_id))
        else: results.append(effect)
    if options:
        results.append(RequestChoice(request.player_id, tuple(options), request.source_id,
            prompt='选择一张抽到的牌'))
    return tuple(results)*reward.repetitions


def qualified_records(state, registry, request):
    if type(request) is not ContinuePhysicalDrawGroup or request.index != len(request.slots):
        raise ValueError('Qualified draw reward requires its entire completed original group')
    validate_material(state, registry, request, completed=True)
    records = tuple(draw_record(state, row.draw_id) for row in request.arrivals if row.draw_id is not None)
    if request.reward.kind == SPELL_COST_FOLLOWUP:
        return tuple(row for row in records if row.outcome in ('hand','cast') and row.card_id is not None and
            registry.card(row.card_id).kind==CardType.SPELL)
    if request.reward.kind == 'qualified_non_minion_followup':
        return tuple(row for row in records if row.card_id is not None and
            registry.card(row.card_id).kind != CardType.MINION)
    if request.reward.kind == 'qualified_both_minions_followup':
        return records[-1:] if all(row.card_id is not None and
            registry.card(row.card_id).kind == CardType.MINION for row in records) else ()
    if request.reward.kind == FROST_FOLLOWUP:
        return records[-1:] if len(records) == 2 and all(row.card_id is not None and
            registry.card(row.card_id).kind == CardType.SPELL and registry.card(row.card_id).spell_school == SpellSchool.FROST
            for row in records) else ()
    raise ValueError('Unknown qualified draw reward')


def validate_qualified_call(call, registry):
    validate_qualified_context(call.context, registry, behavior_id=call.behavior_id)


def validate_qualified_context(context, registry, *, behavior_id=None):
    if context.draw_group is None:
        return
    request = context.draw_group
    records = qualified_records(context.state, registry, request)
    if ((context.source_id, context.player_id, context.target_id) !=
            (request.source_id, request.player_id, request.reward.target_id) or
            behavior_id is not None and behavior_id != request.reward.behavior_id or
            context.draw is None or context.draw not in records):
        raise ValueError('Qualified draw callback changed its original group, target or accepted attempt')


def register(mechanics):
    mechanics.register(TriggerDrawnDeathrattle, trigger_drawn_deathrattle)
    for kind in (DrawGroupSlot, DrawGroupReward, DrawGroupArrival): mechanics.register_payload_type(kind)
    mechanics.register(DrawPhysicalGroup, begin)
    mechanics.register(ContinuePhysicalDrawGroup, advance)
    mechanics.register(CapturePhysicalDrawGroup, capture)
