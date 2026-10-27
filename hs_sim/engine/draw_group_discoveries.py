"""A genuine discovery from three actual matching spell-draw root attempts."""
from .copy_materials import CapturedCardCopyMaterial
from .effects import ChoiceOption, RequestChoice
from .errors import ResolutionError
from .lifecycle import refresh_entity
from .model import CardPreview, CardType, ChoicePurpose
from .zones import CopyCard, reference_entity


def discover(r, request):
    from .physical_draw_groups import ContinuePhysicalDrawGroup, validate_material
    if (type(request) is not ContinuePhysicalDrawGroup or request.reward.kind != 'discover_spell_copy' or
            request.index != len(request.slots)):
        raise ValueError('Drawn-spell discovery requires its complete original three-slot group')
    validate_material(r.state, r.registry, request, completed=True)
    options = []
    for row in request.arrivals:
        if row.copy is None:
            continue
        material = row.copy
        if material.origin.kind != CardType.SPELL:
            raise ResolutionError('Original matching spell group supplied a nonspell copy')
        live = reference_entity(r, row.hand) if row.hand is not None else None
        if live is not None and (live.id, live.card_id) == (material.origin.entity_id, material.origin.card_id):
            material = CapturedCardCopyMaterial.capture(r.state, live)
        # Each actual physical root keeps its own option and material, including
        # duplicate faces, burned originals and drawn-cast originals.
        preview_entity = material.entity()
        refresh_entity(preview_entity)
        face = CardPreview.capture(preview_entity, r.registry)
        options.append(ChoiceOption('draw-copy-'+str(row.draw_id), r.registry.card(material.origin.card_id).name,
            (CopyCard(material, request.player_id, mode='current', source_id=request.source_id),),
            card_id=material.origin.card_id, preview=face))
    return (RequestChoice(request.player_id, tuple(options), request.source_id,
        prompt='发现一张本组抽到法术的复制', purpose=ChoicePurpose.CARD_DISCOVERY),) if options else ()
