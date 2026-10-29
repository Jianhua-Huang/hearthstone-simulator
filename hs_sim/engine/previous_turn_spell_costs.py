"""Finite flat price condition over actual casts in the last closed own turn."""
from .model import CardType,PreviousOwnerSpellCastMatch,OwnerTurnQueryBoundaryFact,PlayerSpellCountCostRow,SpellSchool
from .player_spell_count_costs import row_for

CONDITION='previous_owner_turn_spell_cast'
HISTORY='casts.previous-closed-owner-v1'


def validate_definition(definition):
    from dataclasses import fields
    if not definition.intrinsic_costs or definition.intrinsic_costs[0].condition!=CONDITION:return
    if (definition.kind!=CardType.SPELL or len(definition.intrinsic_costs)!=1 or
            not definition.hand_playable or any(getattr(definition,f.name)is not None
                for f in fields(definition)if f.name.endswith('_cost'))):
        raise ValueError('Previous spell-cast price requires one independent physical Spell condition')


def capture(state,registry,player_id,boundary):
    from .spell_casts import validate_history
    validate_history(state,registry)
    interval=next((r for r in reversed(state.owner_turn_history)if r.player_id==player_id and r.closed),None)
    # Closed-interval prefixes are stable. Do not copy current unfinished CASTs
    # or recursively nest their source-cost receipts in every later quote.
    rows=tuple(row_for(r,registry)for r in state.cast_history if interval is not None and r.turn<=interval.turn)
    matched=interval is not None and any(r.player_id==player_id and r.turn==interval.turn and r.payload_started and r.failure is None for r in rows)
    result=PreviousOwnerSpellCastMatch(player_id,boundary,interval,state.next_entity_id,rows,matched)
    validate_match(result,registry);return result


def validate_match(fact,registry):
    if type(fact)is not PreviousOwnerSpellCastMatch:raise ValueError('Previous spell casts lost their exact frozen shape')
    fact.__post_init__()
    for row in fact.rows:
        card=registry.card(row.card_id)
        if card.kind!=CardType.SPELL or row.spell_school!=card.spell_school:
            raise ValueError('Previous spell casts changed a complete original spell identity or school')


def validate_prefix(fact,state,registry,*,_within_cast_history_check=False):
    from .spell_casts import validate_history
    if type(_within_cast_history_check)is not bool:raise ValueError('Cast history validation context requires bool')
    if not _within_cast_history_check:validate_history(state,registry)
    validate_match(fact,registry);boundary=fact.boundary
    if (boundary.owner_history_length>len(state.owner_turn_history)or fact.next_entity_id>state.next_entity_id or
            any(row.source_id not in state.entities for row in fact.rows)):
        raise ValueError('Previous spell casts lost the original allocation or owner-history prefix')
    history=list(state.owner_turn_history[:boundary.owner_history_length])
    if history:history[-1]=boundary.last_owner_turn
    interval=next((r for r in reversed(history)if r.player_id==fact.player_id and r.closed),None)
    if interval!=fact.owner_turn:raise ValueError('Previous spell casts changed the latest original closed own interval')
    expected=tuple(row_for(r,registry)for r in state.cast_history if interval is not None and r.turn<=interval.turn)
    if expected!=fact.rows:raise ValueError('Previous spell casts omitted, invented or rewrote an original closed prefix row')


def from_dict(value):
    from .serialization import _row,_list,_owner_turn_from_dict
    row=_row(value,PreviousOwnerSpellCastMatch)
    boundary=_row(row['boundary'],OwnerTurnQueryBoundaryFact)
    if boundary['last_owner_turn']is not None:boundary['last_owner_turn']=_owner_turn_from_dict(boundary['last_owner_turn'])
    row['boundary']=OwnerTurnQueryBoundaryFact(**boundary)
    if row['owner_turn']is not None:row['owner_turn']=_owner_turn_from_dict(row['owner_turn'])
    rows=[]
    for item in _list(row['rows'],'previous own spell-cast prefix'):
        item=_row(item,PlayerSpellCountCostRow)
        if item['spell_school']is not None:item['spell_school']=SpellSchool(item['spell_school'])
        rows.append(PlayerSpellCountCostRow(**item))
    row['rows']=tuple(rows);return PreviousOwnerSpellCastMatch(**row)


def register(mechanics):mechanics.register_payload_type(PreviousOwnerSpellCastMatch)
