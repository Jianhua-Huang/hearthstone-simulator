"""Two genuine Nathria Discover sources and their original delayed riddles."""
import json
from pathlib import Path

from hs_sim.engine.discovery_guesses import (DiscoveryGuessProfile, DiscoveryGuessTarget,
    LEGENDARIES, SPELLS, register_behaviors)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, Zone
from hs_sim.engine.pools import DiscoverFromPool, PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ALCHEMIST, USHER = 'REV_000', 'REV_002'
DEPENDENCIES = (ALCHEMIST, USHER)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_suspicious_guess.'
POOL_ID = 'constructed.cards'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-suspicious-guess-cards-v1.json'
BATCH_HASH = 'c33e3966db798fe7203aa97dbc2f4e8dac07f4679e13fd9f3893808552f3508b'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('REV_000e',) or
            any(data[k] for k in ('cards','existing_dependencies','choice_only','skipped',
                'numeric_normalizations','display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256']
                for x in (*data['dependencies'],*data['evidence_only']))):
        raise TargetValidationError('Suspicious sources lost their full original cards and riddle evidence')
    return data


def register_past_suspicious_guess_cards(registry):
    register_behaviors(registry)
    for item in load_batch()['dependencies']:
        raw = item['record']; cid = raw['id']; query = SPELLS if cid == ALCHEMIST else LEGENDARIES
        if (raw['type'],raw['collectible'],raw['cost'],raw['attack'],raw['health'],
                raw['tags'].get('BATTLECRY')) != ('MINION',True,1,1,3,1):
            raise TargetValidationError('Suspicious source changed its original printed body')
        body_id = PREFIX+cid
        def discover(c, source_card_id=cid, native_query=query):
            if c.battlecry is None:
                raise ResolutionError('Suspicious discovery requires its actual accepted Battlecry')
            source = c.source
            reference = MinionReference.capture(source) if (source.kind==CardType.MINION and
                source.zone==Zone.BOARD and source.active and source.health>0) else None
            target = DiscoveryGuessTarget(source_card_id,c.battlecry.id,reference)
            return (DiscoverFromPool(c.player_id,POOL_ID,native_query,source_id=c.source_id,
                memory_target=target),)
        registry.register_behavior(body_id,discover)
        card = CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=1,health=3,
            metadata=metadata_from_record(raw),battlecry=body_id)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
        registry.register_discovery_guess_profile(DiscoveryGuessProfile(cid,body_id,query))
