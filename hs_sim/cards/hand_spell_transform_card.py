"""Bootleg Alchemist chooses an original hand card and reuses stored transformation."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.costs import local_cost, quote_unselected_cost
from hs_sim.engine.effects import ChoiceOption, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, Zone
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.stored_pool_transforms import TransformStoredFromPool
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'JAIL_313'
POOL_ID = 'constructed.cards'
PREFIX = 'cards.hand_spell_transform.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/hand-spell-transform-card-v1.json'
BATCH_HASH = 'f08782a266feaac92e7e6e29c9c6e193026e161425c5f3f38a4d7995402d8d13'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or [x['record']['id'] for x in data['cards']] != [CARD]
            or [x['record']['id'] for x in data['evidence_only']] != ['JAIL_313e']
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))
            or any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards']+data['evidence_only'])):
        raise TargetValidationError('Bootleg Alchemist lost its complete original source')
    return data


def register_hand_spell_transform_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != ('MINION', 5, 3, 3, 1):
        raise TargetValidationError('Bootleg Alchemist changed its real Battlecry face')

    def offer(c):
        options = []
        for eid in c.state.players[c.player_id].hand:
            e = c.state.entities[eid]
            value = dict(reference=asdict(CardReference.capture(e)),
                         cost=quote_unselected_cost(c.state, registry, e).amount,
                         retained_cost=local_cost(e)[0])
            options.append(ChoiceOption(json.dumps(value, sort_keys=True), registry.card(e.card_id).name,
                                        card_id=e.card_id, entity_id=e.id))
        return (RequestChoice(c.player_id, tuple(options), c.source_id,
                              on_select=PREFIX+'selected'),) if options else ()

    def selected(c):
        result = c.choice
        if (result is None or len(result.selected) != 1
                or (result.choice.source_id, result.choice.player_id) != (c.source_id, c.player_id)):
            raise ResolutionError('Bootleg Alchemist requires its original single hand choice')
        item, = result.selected
        value = json.loads(item.id)
        if set(value) != {'reference', 'cost', 'retained_cost'}:
            raise ResolutionError('Bootleg Alchemist lost its original numeric material')
        row = dict(value['reference']); row['zone'] = Zone(row['zone']); ref = CardReference(**row)
        if (ref.zone != Zone.HAND or ref.player_id != c.player_id
                or (item.entity_id, item.card_id) != (ref.entity_id, ref.card_id)
                or any(type(value[k]) is not int or value[k] < 0 for k in ('cost', 'retained_cost'))):
            raise ResolutionError('Bootleg Alchemist changed its original card or costs')
        current = c.state.entities.get(ref.entity_id)
        if current is None or (current.controller, current.zone, current.card_id, current.zone_epoch) != (
                ref.player_id, ref.zone, ref.card_id, ref.zone_epoch):
            return ()
        tier = value['cost']+5
        return (TransformStoredFromPool(ref, POOL_ID,
            PoolQuery(kinds=(CardType.SPELL,), collectible=True, min_cost=tier, max_cost=tier),
            c.source_id, retained_cost=value['retained_cost']),)

    registry.register_behavior(PREFIX+'offer', offer)
    registry.register_behavior(PREFIX+'selected', selected)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], battlecry=PREFIX+'offer', metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
