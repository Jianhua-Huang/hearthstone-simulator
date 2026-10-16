"""Real Wingman grants two existing abilities to the same original minion."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.attack_policies import GrantAttackPolicy
from hs_sim.engine.model import AttackPolicySpec, CardDefinition, CardType, Keyword, TargetMode, TargetSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import GrantCapturedKeyword, MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/captured-attack-grants-v1.json'
BATCH_HASH = '85745347a0fe5bf9febee1f5802f3370e7c4c36d37470026e3df3d5c501f00ee'
WINGMAN = 'CATA_564'
PREFIX = 'cards.captured_attack_grant.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Captured attack grant complete source pin changed')
    if tuple(row['record']['id'] for row in data['cards']) != (WINGMAN,) or data['dependencies'] or data['evidence_only']:
        raise TargetValidationError('Unreviewed captured attack grant family')
    if tuple(row['record']['id'] for row in data['existing_consumers']) != ('TIME_043',):
        raise TargetValidationError('Unreviewed existing attack grant consumer')
    for row in data['cards']+data['existing_consumers']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Captured attack grant full source row changed')
    return data


def register_captured_attack_grant_cards(registry):
    data=load_batch()
    for row in data['existing_consumers']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Existing attack consumer complete definition changed')
    def wingman(c):
        if c.target_id is None:return ()
        original=MinionReference.capture(c.state.entities[c.target_id])
        return (GrantCapturedKeyword(original,Keyword.MEGA_WINDFURY,c.source_id),
                GrantAttackPolicy(original.entity_id,AttackPolicySpec('cannot_attack_heroes'),c.source_id,recipient=original))
    registry.register_behavior(PREFIX+'wingman',wingman)
    row,=data['cards'];raw=row['record']
    if (raw['id'],raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],raw['tags'].get('BATTLECRY')) != (WINGMAN,'MINION',5,5,5,True,1):
        raise TargetValidationError('Wingman lost its full actual battlecry face')
    card=CardDefinition(WINGMAN,raw['name'],CardType.MINION,cost=5,attack=5,health=5,
        battlecry=PREFIX+'wingman',targeting=TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,),
            relation='friendly',exclude_source=False),metadata=replace(metadata_from_record(raw),deck_identity=WINGMAN))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
