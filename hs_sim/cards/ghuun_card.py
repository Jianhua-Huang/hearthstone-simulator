"""G'huun uses completed original Blood Runes, including cards played before drawing it."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_theft import StealLowestEnemyHealthToMinion
from hs_sim.engine.model import CardDefinition, CardType, Zone
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_287'
BODY = 'cards.ghuun.theft'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/ghuun-v1.json'
BATCH_HASH = 'ef2f81f40963eb10e253133301f3275e19a88e5ae829c84dcd7efef0ed020a7e'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256'] or
            data['display_normalizations'] != {CARD: {'@': ''}} or data['official_faces_verified'] != 2):
        raise TargetValidationError('Ghuun requires its complete triple-Blood source and explicit omitted live number')
    return data


def theft_amount(state, player_id):
    """The current unfinished hand root is absent, so a normal G'huun excludes itself."""
    amount = 6
    for record in played_cards(state, player_id, completed=True):
        meta = record.played_face.metadata
        if meta is None: raise UnsupportedDefinitionError('Ghuun completed original Blood Rune metadata is unknown')
        if meta.runes is not None: amount += meta.runes.blood
    return amount


def register_ghuun_card(registry):
    raw = load_batch()['cards'][0]['record']; metadata = metadata_from_record(raw)
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY'),
            raw['tags'].get('TAG_SCRIPT_DATA_NUM_1'), metadata.runes.blood,
            metadata.runes.frost, metadata.runes.unholy) != ('MINION',8,8,1,1,6,3,0,0):
        raise TargetValidationError('Ghuun lost its actual eight-Mana 8/1 six-base triple-Blood face')

    def body(c):
        if c.battlecry is None or c.battlecry.payload.card_id != CARD:
            raise ResolutionError('Ghuun requires its original actual Battlecry')
        if c.source.kind != CardType.MINION:
            raise ResolutionError('Ghuun health beneficiary requires a physical minion')
        if c.source.zone != Zone.BOARD or not c.source.active or c.source.health <= 0 or c.source.doomed:
            return ()
        return (StealLowestEnemyHealthToMinion(MinionReference.capture(c.source),
            theft_amount(c.state, c.player_id), c.source_id),)

    registry.register_behavior(BODY, body)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=8, attack=8, health=1,
        metadata=metadata, battlecry=BODY)
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
