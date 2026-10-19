"""Picklock uses native hand numbers and an ordinary frozen Battlecry scalar."""
import json
from pathlib import Path
from hs_sim.engine.effects import Damage
from hs_sim.engine.model import CardDefinition,CardType,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.remaining_mana_numbers import RemainingManaNumbersProfile
from hs_sim.targets import canonical_digest,TargetValidationError
from .metadata import metadata_from_record

CARD='JAIL_501'
PREFIX='cards.remaining_mana_numbers.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/remaining-mana-numbers-v1.json'
BATCH_HASH='715102a562a3cf3b64fdb0fea2456800121087cf45e556141e925b9140cd25dd'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id'] for x in d['cards'])!=(CARD,) or
            any(d[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped')) or d['policy']['floor']!=1):
        raise TargetValidationError('Picklock requires its complete original remaining-mana source')
    if any(canonical_digest(x['record'])!=x['record_sha256'] for x in d['cards']):
        raise TargetValidationError('Picklock complete source pin changed')
    return d


def register_remaining_mana_numbers_card(registry):
    raw=load_batch()['cards'][0]['record']
    def battlecry(c):
        value=None if c.battlecry is None else c.battlecry.payload.remaining_mana_number
        if value is None:raise UnsupportedDefinitionError('Picklock needs its originally captured native Battlecry number')
        return () if c.target_id is None else (Damage(c.target_id,value,c.source_id),)
    registry.register_behavior(PREFIX+'damage',battlecry)
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=PREFIX+'damage',targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),
            kinds=(CardType.MINION,),relation='enemy'),metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_remaining_mana_numbers_profile(RemainingManaNumbersProfile(CARD))
