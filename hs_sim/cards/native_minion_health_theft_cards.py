"""Dread Leviathan delegates its three choices and atomic transfers to the kernel."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_theft import ChooseHealthForMinion
from hs_sim.engine.model import CardDefinition, CardType, Keyword, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CATA_699'
BODY = 'cards.dread_leviathan.choose_health'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-minion-health-theft-v1.json'
BATCH_HASH = 'afd7bb87faf5d64e534560f1b2f96a54076e33af8dca6a9ea3ce32f698583d52'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Dread Leviathan requires its complete reviewed source')
    return data


def register_native_minion_health_theft_cards(registry):
    raw = load_batch()['cards'][0]['record']
    def choose(c):
        if c.source.kind != CardType.MINION:
            raise ResolutionError('Dread Leviathan health theft requires an actual minion recipient')
        if c.source.zone != Zone.BOARD:
            return ()
        return (ChooseHealthForMinion(MinionReference.capture(c.source), 3, 3, c.source_id),)
    registry.register_behavior(BODY, choose)
    definition = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], keywords=(Keyword.TAUNT,),
        battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(definition)
    registry.register_pool_card(PoolCard.from_definition(definition))
