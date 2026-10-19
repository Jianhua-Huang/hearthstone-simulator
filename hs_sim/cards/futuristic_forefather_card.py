"""A real private hand guess; its health reward uses the original minion reference."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.cross_zone import BuffCapturedMinion
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_inspection import GuessOpponentHandCard, selected_hand_guess
from hs_sim.engine.model import CardDefinition, CardType, Keyword, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TIME_041'
PREFIX = 'cards.futuristic_forefather.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/futuristic-forefather-v1.json'
BATCH_HASH = '831915b7b67e7838ad5c4a077f90805bd1e4d0e71c63852907a309f848e5f9a6'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (CARD,) or
            any(d[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Forefather requires its complete original body and primary faces')
    row, = d['cards']; raw = row['record']
    if (canonical_digest(raw) != row['record_sha256'] or
            (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags']['CLASS'],raw['tags']['RARITY']) !=
                ('MINION',4,4,4,12,4) or raw['tags'].get('TAUNT') != 1 or raw['tags'].get('BATTLECRY') != 1):
        raise TargetValidationError('Forefather original Neutral Epic Taunt/Battlecry changed')
    return d


def register_futuristic_forefather_card(registry):
    raw = load_batch()['cards'][0]['record']
    def guess(c):
        source = c.source
        ref = MinionReference.capture(source) if (source.kind == CardType.MINION and
            source.zone == Zone.BOARD and source.active and source.health > 0 and not source.doomed) else None
        return (GuessOpponentHandCard(c.player_id, 3-c.player_id, c.source_id, PREFIX+'selected',
            json.dumps(dict(source=None if ref is None else asdict(ref)), sort_keys=True)),)
    def selected(c):
        correct, material = selected_hand_guess(c, registry)
        if set(material) != {'source'}:
            raise ResolutionError('Forefather lost its original reward recipient')
        if not correct or material['source'] is None:
            return ()
        ref = MinionReference(**material['source'])
        if (ref.entity_id, ref.player_id) != (c.source_id, c.player_id):
            raise ResolutionError('Forefather borrowed another original reward recipient')
        return (BuffCapturedMinion(ref, 0, 4, c.source_id),)
    registry.register_behavior(PREFIX+'guess', guess)
    registry.register_behavior(PREFIX+'selected', selected)
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=4,attack=4,health=4,
        keywords=(Keyword.TAUNT,),battlecry=PREFIX+'guess',metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
