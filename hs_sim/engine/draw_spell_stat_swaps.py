"""The two actual original spell draws exchange with one original source."""
from .board_presence import resolve_board_presence
from .costs import local_cost,quote_cost
from .model import CardType,CostSpec
from .sacrifice import MinionReference,SetCapturedMinionStats
from .zones import ModifyStoredCost,reference_entity


def swap_original_spell_costs(r,request):
    from .physical_draw_groups import ContinuePhysicalDrawGroup,SOURCE_SPELL_STATS,validate_material
    from .draw_casts import draw_record
    if(type(request)is not ContinuePhysicalDrawGroup or request.reward.kind!=SOURCE_SPELL_STATS or
            request.index!=len(request.slots)):
        raise ValueError('Spell/stat swap requires its complete original two-draw group')
    validate_material(r.state,r.registry,request,completed=True)
    source=resolve_board_presence(r.state,request.reward.source)
    if source is None or not source.active or source.doomed or source.health<=0:return()
    outgoing=(source.attack,source.health);values=[None,None];work=[]
    for row in request.arrivals:
        if row.draw_id is None:continue
        record=draw_record(r.state,row.draw_id);material=row.copy
        if material is None or material.origin.kind!=CardType.SPELL or record.entity_id!=material.origin.entity_id:
            raise ValueError('Spell/stat swap lost its exact original spell draw material')
        card=reference_entity(r,row.hand)if row.hand is not None and row.hand.entity_id==record.entity_id else None
        # A replacement draw is never one of "their" original spells. Burned or
        # draw-cast originals keep their pre-draw local price for source stats.
        values[row.slot]=quote_cost(r.state,r.registry,card).amount if card is not None and card.kind==CardType.SPELL else max(0,local_cost(material.entity())[0])
        if card is not None and card.kind==CardType.SPELL:
            work.append(ModifyStoredCost(row.hand,CostSpec(set_to=outgoing[row.slot]),request.source_id))
    if any(value is not None for value in values):
        work.append(SetCapturedMinionStats(MinionReference.capture(source),values[0],values[1],request.source_id))
    return tuple(work)
