"""Committed hand plays and shared pre-play conditions; no event-log inference."""
from dataclasses import replace

from .model import CardClass, CardType, PaymentType, PlayRecord, Zone
from .hand_history import hand_entry


def played_cards(state, player_id, *, turn=None, before_id=None, kind=None, completed=None,
                 registry=None, tribes_any=(), card_class=None):
    """Host/rule query. Countered plays still count; summons and powers do not."""
    if type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Invalid history player')
    if turn is not None and (type(turn) is not int or turn < 1):
        raise ValueError('Invalid history turn')
    if before_id is not None and (type(before_id) is not int or before_id < 1):
        raise ValueError('Invalid history bound')
    if kind is not None and not isinstance(kind, CardType):
        raise ValueError('Invalid history card kind')
    if completed is not None and type(completed) is not bool:
        raise ValueError('Invalid completion filter')
    from .pools import ids
    ids(tribes_any,'history tribes',unique=True)
    if tribes_any and registry is None:
        raise ValueError('Tribe history queries require the pinned registry')
    if card_class is not None:
        if type(card_class) is not CardClass or card_class == CardClass.NEUTRAL:
            raise ValueError('Class history queries require one playable class')
        if registry is None:
            raise ValueError('Class history queries require the pinned registry')
    return tuple(p for p in state.play_history if p.player_id == player_id and
        (turn is None or p.turn == turn) and (before_id is None or p.id < before_id) and
        (kind is None or p.kind == kind) and (completed is None or p.completed == completed) and
        (not tribes_any or matches_play_tribes(registry,p,tribes_any)) and
        (card_class is None or matches_played_class(p.played_face, card_class, registry=registry)))


def spell_schools_from_plays(records):
    """Ordered distinct schools of committed SPELL faces, never current entities.

    Callers supply their original seat/turn slice. Countered hand plays count;
    effect casts are absent from this ledger. No-school spells add no school.
    """
    return tuple(sorted({record.played_face.spell_school for record in records
        if record.kind == CardType.SPELL and record.played_face.spell_school is not None},
        key=lambda school: school.value))


def quests_from_plays(records, registry):
    """Original committed native Quest faces; progress is never another play."""
    return tuple(record for record in records if record.kind == CardType.SPELL and
        registry.card(record.played_face.card_id).quest is not None)


def matches_played_class(face, card_class, *, registry=None):
    """Pure original printed-class membership, independent of hero/current face."""
    from .model import FrozenPlayedFaceFact
    from .pools import PoolQuery, matches_metadata
    if type(face) is not FrozenPlayedFaceFact:
        raise ValueError('Class history requires its complete original frozen face')
    face.__post_init__()
    if type(card_class) is not CardClass or card_class == CardClass.NEUTRAL:
        raise ValueError('Class history requires one playable class')
    if registry is not None:
        from .owner_turns import validate_face
        validate_face(face, registry)
    return matches_metadata(PoolQuery(class_mode='specified', classes=(card_class,), include_neutral=False),
        card_id=face.card_id, kind=face.kind, cost=0, meta=face.metadata, spell_school=face.spell_school, keywords=())


def validate_starting_deck_identity(entities, cards, next_entity_id):
    """Complete immutable original inventory, independent of current card faces."""
    from .model import _int, _name
    _int(next_entity_id, 'starting-deck allocation bound', 1)
    if (type(entities) is not tuple or len(entities) != 2 or
            type(cards) is not tuple or len(cards) != 2):
        raise ValueError('Starting decks require two complete immutable player inventories')
    seen = set()
    for group, names in zip(entities, cards):
        if type(group) is not tuple or type(names) is not tuple or len(group) != len(names):
            raise ValueError('Starting physical identities and original card faces disagree')
        previous = 0
        for entity_id, card_id in zip(group, names):
            _int(entity_id, 'starting-deck physical identity', 1)
            _name(card_id, 'starting-deck original card face')
            if entity_id in seen or not previous < entity_id < next_entity_id:
                raise ValueError('Starting deck changed its original allocation inventory')
            seen.add(entity_id); previous = entity_id


def starting_deck_identity(state):
    """Host-only pure query; card names alone cannot recover physical membership."""
    from .model import GameState, OpeningState
    from .registry import UnsupportedDefinitionError
    if type(state) is not GameState:
        raise ValueError('Starting-deck identity requires typed State')
    if state.opening is None:
        raise UnsupportedDefinitionError('Starting-deck physical identity is unknown for this Scenario')
    if type(state.opening) is not OpeningState:
        raise ValueError('Starting-deck identity requires its original opening record')
    state.opening.__post_init__()
    entities = state.opening.original_entities
    cards = tuple(state.players[player_id].original_deck for player_id in (1, 2))
    validate_starting_deck_identity(entities, cards, state.next_entity_id)
    for player_id, group in enumerate(entities, 1):
        if any(entity_id not in state.entities or state.entities[entity_id].owner != player_id for entity_id in group):
            raise ValueError('Starting deck lost an original physical entity or owner')
    return entities, cards


def matches_outside_starting_deck(face, entities):
    from .model import FrozenPlayedFaceFact
    if type(face) is not FrozenPlayedFaceFact:
        raise ValueError('Starting-deck relation requires the original submitted face')
    face.__post_init__()
    return face.source_id not in entities[face.player_id - 1]


def played_outside_starting_deck(state, player_id, *, before_id=None):
    """Original paid hand roots; copies use their own physical allocation identity."""
    rows = played_cards(state, player_id, before_id=before_id)
    entities, _cards = starting_deck_identity(state)
    return tuple(row for row in rows if matches_outside_starting_deck(row.played_face, entities))


def matches_play_tribes(registry,record,tribes_any):
    """Use the frozen played identity, never the entity's later transformed face."""
    from .pools import PoolQuery,matches_metadata
    c=registry.card(record.card_id)
    return matches_metadata(PoolQuery(tribes_any=tribes_any),card_id=c.id,kind=c.kind,cost=c.cost,
        meta=c.metadata,spell_school=c.spell_school,keywords=c.keywords)


def is_first_play(state,record,*,registry=None,kind=None,tribes_any=()):
    if type(record) is not PlayRecord or record not in state.play_history:
        raise ValueError('First-play query requires an existing frozen play record')
    records=played_cards(state,record.player_id,turn=record.turn,before_id=record.id+1,
        registry=registry,kind=kind,tribes_any=tribes_any)
    return bool(records) and records[0].id==record.id


def preplay_conditions(state, source, registry=None):
    hand=state.players[source.controller].hand
    if source.zone != Zone.HAND or source.id not in hand:
        raise ValueError('Pre-play conditions require a hand entity')
    index=hand.index(source.id)
    result={'combo':bool(played_cards(state,source.controller,turn=state.turn)),
            'outcast':index in (0,len(hand)-1),
            'quickdraw':hand_entry(state,source.hand_entry_id).turn==state.turn}
    if registry is not None:
        from .costs import quote_cost
        quote = quote_cost(state,registry,source)
        player=state.players[source.controller]
        threshold=registry.card(source.card_id).manathirst
        result.update(finale=player.mana-(quote.amount if quote.payment==PaymentType.MANA else 0)==0,
                      manathirst=threshold is not None and player.max_mana>=threshold)
    return result


def play_definition(state, registry, source, record=None, *, branch_id=None):
    """Effective target declaration shared by host and player action paths."""
    definition=registry.card(record.card_id if record is not None else source.card_id)
    from .choose_one import effective
    definition=effective(definition, record.branch_id if record is not None else branch_id)
    condition=definition.target_condition
    active=(getattr(record,condition) if record is not None else preplay_conditions(state,source,registry)[condition]) if condition else True
    if definition.kind == CardType.LOCATION or not active:
        return replace(definition,requires_target=False,targeting=None,target_rule='any_entity')
    return definition


def prepare_play(state, registry, source, target_id, quote, *, position=None, magnetic_target_id=None, branch_id=None, body_targets=None, board_player_id=None):
    from .battlecries import capture as capture_battlecries
    from .combos import capture as capture_combos
    from .hand_progress import corrupt_candidates
    from .hand_derivatives import capture
    from .held_spells import capture as capture_held_spells
    from .held_mana import capture as capture_held_mana
    from .held_higher_cost import capture as capture_higher_cost
    from .card_spell_repeats import capture as capture_card_spell_repeats
    from .after_play_grants import capture as capture_after_play
    from .owner_turns import freeze_played_face
    player=state.players[source.controller]
    from .disguised import destination
    destination(registry.card(source.card_id), player.id, board_player_id)
    previous=played_cards(state,player.id)
    entry=hand_entry(state,source.hand_entry_id)
    from .model import HandNeighborFact
    index=player.hand.index(source.id)
    neighbors=tuple(HandNeighborFact(e.id,e.controller,e.card_id,e.zone_epoch)
        for i in (index-1,index+1) if 0<=i<len(player.hand) for e in (state.entities[player.hand[i]],))
    return PlayRecord(len(state.play_history)+1,source.id,player.id,source.card_id,
        registry.card(source.card_id).kind,state.turn,state.action_number,target_id,
        player.hand.index(source.id),len(player.hand),sum(p.turn==state.turn for p in previous),
        len(previous),quote.amount,quote.payment,
        player.mana,player.mana-(quote.amount if quote.payment==PaymentType.MANA else 0),player.max_mana,
        entry.id,entry.turn,registry.card(source.card_id).manathirst,
        corrupt_candidates=corrupt_candidates(state,registry,source,quote),held_spells=capture_held_spells(state,source),
        held_mana=capture_held_mana(state,source),
        held_higher_cost=capture_higher_cost(state,source),
        card_spell_repeats=capture_card_spell_repeats(source),
        after_play=capture_after_play(source),
        position=position,magnetic_target_id=magnetic_target_id,body_targets=body_targets,
        board_player_id=board_player_id,
        hand_neighbors=neighbors,
        hand_derivatives=capture(source,registry.card(source.card_id)),branch_id=branch_id,
        battlecries=capture_battlecries(source),combos=capture_combos(source),
        played_face=freeze_played_face(state,registry,source,len(state.play_history)+1),
        copy_origin=source.copy_origin)


def commit_play(state, record):
    """One paid append shared by execution and its complete payment projection."""
    if record.id != len(state.play_history) + 1:
        raise ValueError('Physical hand play must append its original next identity')
    state.play_history.append(record)
    from .held_opponent_copies import note_play
    note_play(state, record)


def play_record(state, play_id):
    if type(play_id) is not int or not 1 <= play_id <= len(state.play_history):
        raise ValueError('Unknown play record')
    return state.play_history[play_id-1]


def update_play(state, play_id, **outcome):
    record=play_record(state,play_id)
    if record.completed or record.interrupted:
        raise ValueError('Play record is already settled')
    if set(outcome)-{'countered','completed','interrupted','minion_result'}:
        raise ValueError('Play provenance is immutable')
    state.play_history[play_id-1]=replace(record,**outcome)
    return state.play_history[play_id-1]


def accept_battlecries(state, play_id, receipt):
    """Freeze once at payload acceptance, independently of the pending queue."""
    from .model import BattlecryAcceptanceReceipt
    record = play_record(state, play_id)
    if (type(receipt) is not BattlecryAcceptanceReceipt or record.battlecry_acceptance is not None or
            record.completed or record.interrupted):
        raise ValueError('Battlecry payload acceptance must occur once during an active play')
    receipt.__post_init__()
    from .paid_body_targets import bind_actual_payloads
    bind_actual_payloads(state, record, 'battlecry', receipt.payloads)
    value = replace(record, battlecry_acceptance=receipt)
    state.play_history[play_id-1] = value
    return value


def accept_combo_submission(state, play_id, receipt_id):
    record=play_record(state,play_id)
    if record.completed or record.interrupted or record.combo_submission_receipt_id is not None:
        raise ValueError('Combo submission must be accepted once during its physical paid root')
    value=replace(record,combo_submission_receipt_id=receipt_id)
    state.play_history[play_id-1]=value
    return value


def accept_combos(state, play_id, receipt):
    from .model import ComboAcceptanceReceipt
    record=play_record(state,play_id)
    if (type(receipt) is not ComboAcceptanceReceipt or record.combo_acceptance is not None or
            record.combo_submission_receipt_id is None or record.completed or record.interrupted):
        raise ValueError('Combo actual window must be accepted once during its submitted physical root')
    from .paid_body_targets import bind_actual_payloads
    bind_actual_payloads(state, record, 'combo', receipt.payloads)
    value=replace(record,combo_acceptance=receipt)
    state.play_history[play_id-1]=value
    return value


def requires_battlecry_acceptance(state, record, registry):
    return (record.kind in (CardType.WEAPON, CardType.HERO) or
            record.kind == CardType.MINION and record.minion_result == 'summoned')


def validate_history(state, registry):
    if type(state.play_history) is not list:
        raise ValueError('Play history must be a list')
    totals={1:0,2:0};turns={};last_turn=last_action=0
    for index,record in enumerate(state.play_history,1):
        from .after_play_grants import validate_record as validate_after_play
        validate_after_play(state,registry,record)
        if record.hand_neighbors is None:
            raise ValueError('Physical hand history lost its original neighbors')
        for neighbor in record.hand_neighbors:
            registry.card(neighbor.card_id)
            if neighbor.entity_id not in state.entities or neighbor.entity_id>=state.next_entity_id:
                raise ValueError('Hand history borrowed a missing/future neighbor')
        if type(record) is not PlayRecord:
            raise ValueError('History requires immutable play records')
        record.__post_init__()
        from .held_opponent_copies import validate_origin
        validate_origin(state, registry, record.copy_origin, record.source_id)
        if record.source_id not in state.entities or record.copy_origin != state.entities[record.source_id].copy_origin:
            raise ValueError('Hand play changed its original physical copy source')
        from .paid_body_targets import validate_receipt
        validate_receipt(state, registry, record)
        if record.submitted_cost is None:
            raise ValueError('Committed physical hand history requires its complete submitted price')
        for progress in (record.paid_hand_close, record.paid_hand_interrupt):
            if progress is not None and progress.action > state.action_number:
                raise ValueError('Paid hand progress is newer than its captured history state')
        if record.paid_hand_interrupt is not None and state.status == 'playing':
            raise ValueError('Interrupted paid hand acceptance requires a terminal history state')
        for candidate in record.corrupt_candidates:
            if candidate.source_id not in state.entities or candidate.ability_id >= state.next_attachment_id:
                raise ValueError('Invalid Corrupt candidate provenance')
        definition=registry.card(record.card_id)
        from .disguised import play_destination
        play_destination(registry, record)
        receipt = record.battlecry_acceptance
        if record.completed and requires_battlecry_acceptance(state, record, registry) and receipt is None:
            raise ValueError('Completed physical play lost its Battlecry acceptance receipt')
        if receipt is not None:
            from .battlecry_matching import validate_recipient
            validate_recipient(state, registry, receipt.recipient, record)
            if not definition.colossal and receipt.player_id != record.player_id:
                raise ValueError('Accepted Battlecry player differs from its hand play')
            if receipt.plan is not None:
                from .battlecry_repeats import validate_plan
                validate_plan(state, registry, receipt.plan, receipt.recipient)
            for payload in receipt.payloads:
                registry.behavior(payload.behavior_id)
                if (payload.ability_id >= state.next_attachment_id or
                        registry.card(payload.card_id).battlecry != payload.behavior_id):
                    raise ValueError('Invalid accepted Battlecry payload')
            batches = [b for b in state.battlecry_batches if b.play_id == record.id]
            if any((b.player_id, b.payloads, b.plan) != (receipt.player_id, receipt.payloads, receipt.plan)
                    for b in batches):
                raise ValueError('Battlecry batches differ from their durable root receipt')
            if record.completed and receipt.payloads and not batches:
                raise ValueError('Completed Battlecry acceptance lost all its batches')
            if record.completed and receipt.payloads:
                retained = next((r for r in state.rewind_outcomes if r.play_id == record.id and r.battlecries), None)
                if len(batches) != (retained.total if retained is not None else 1):
                    raise ValueError('Completed Battlecry acceptance lost a retained result batch')
        if record.held_spells is not None:
            from .held_spells import validate_progress
            validate_progress(state,registry,record.held_spells,record)
        if record.held_mana is not None:
            from .held_mana import validate_progress as validate_mana_progress
            validate_mana_progress(state,registry,record.held_mana,record)
        from .held_higher_cost import validate_play as validate_higher_cost_play
        validate_higher_cost_play(state, registry, record)
        from .combos import validate_payload
        for payload in record.combos: validate_payload(state,registry,payload)
        for payload in record.battlecries:
            registry.behavior(payload.behavior_id)
            if (payload.ability_id >= state.next_attachment_id or
                    registry.card(payload.card_id).battlecry != payload.behavior_id):
                raise ValueError('Invalid played Battlecry declaration')
        from .choose_one import branch
        branch(definition,record.branch_id)
        if record.hand_derivatives != tuple(s for s in definition.hand_derivatives if s in record.hand_derivatives):
            raise ValueError('Captured hand derivatives differ from their printed declaration order')
        entry=hand_entry(state,record.hand_entry_id)
        if ((entry.entity_id,entry.player_id,entry.turn)!=(record.source_id,record.player_id,record.hand_entry_turn) or
                entry.action>record.action or record.manathirst_threshold!=definition.manathirst):
            raise ValueError('Invalid acquisition or condition in play record')
        key=(record.player_id,record.turn)
        if (record.id!=index or record.source_id not in state.entities or
                record.target_id is not None and record.target_id not in state.entities or
                definition.kind!=record.kind or not definition.hand_playable or
                not last_turn<=record.turn<=state.turn or not last_action<record.action<=state.action_number or
                record.prior_game_plays!=totals[record.player_id] or record.prior_turn_plays!=turns.get(key,0)):
            raise ValueError('Invalid play provenance, chronology or counts')
        if record.interrupted and state.status=='playing':
            raise ValueError('Interrupted plays require a terminal game')
        totals[record.player_id]+=1;turns[key]=turns.get(key,0)+1
        last_turn,last_action=record.turn,record.action
    from .card_spell_repeats import validate_history as validate_card_spell_repeats
    validate_card_spell_repeats(state)
    for window in state.action_windows:
        if window.kind in ('spell','minion'):
            record=play_record(state,window.play_id)
            if (record.kind!=(CardType.SPELL if window.kind=="spell" else CardType.MINION) or record.source_id!=window.source_id or
                    record.player_id!=window.player_id or record.countered!=window.countered or
                    record.completed or record.interrupted):
                raise ValueError('Card window and play history disagree')
            if window.kind == 'minion' and record.minion_result is not None:
                raise ValueError('Pending minion already has an entry result')
    pending = [i for p in state.players.values() for i in p.pending_plays]
    if sorted(pending) != sorted(w.source_id for w in state.action_windows if w.kind == 'minion'):
        raise ValueError('Pending minion zone and windows disagree')
