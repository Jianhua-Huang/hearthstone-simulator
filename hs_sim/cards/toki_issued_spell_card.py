"""Timelooper Toki issues three actual past spells and an independent program."""
import json
from pathlib import Path

from hs_sim.engine.issued_spell_sets import CreateIssuedSpellSet,PROGRESS,progress
from hs_sim.engine.model import CardDefinition,CardType,PlayerEffectSpec,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='TIME_861';POOL_ID='constructed.past.spells';SPEC='cards.toki.issued_set';BODY='cards.toki.create'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/toki-issued-spells-v1.json'
BATCH_HASH='26eb672465a814b1868ea1020febe67b4e9281db34d198516a6f150225ec1c38'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'));rows=(*data['cards'],*data['existing_dependencies'],*data['evidence_only'])
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in rows)!=(CARD,'EX1_277','CS2_024','EX1_279','EX1_287',CARD+'e1',CARD+'e2')or
            data['dependencies']or data['skipped']or any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Issued spell source lost its complete original Toki, spells or two enchantment observations')
    raw=data['cards'][0]['record']
    if(raw['cost'],raw['attack'],raw['health'])!=(3,3,3):raise TargetValidationError('Toki changed its original3mana3/3body')
    return data


def register_toki_issued_spell_card(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        raw=row['record'];old=registry.card(raw['id'])
        if(old.cost,old.metadata)!=(raw['cost'],metadata_from_record(raw)):raise TargetValidationError('Original existing historical spell changed')
    def body(c):
        if c.battlecry is None:raise ValueError('Issued spells require the actual accepted Toki Battlecry')
        return(CreateIssuedSpellSet(c.battlecry.id,POOL_ID,SPEC),)
    registry.register_behavior(BODY,body);registry.register_behavior(PROGRESS,progress)
    raw=data['cards'][0]['record'];card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(SPEC,CARD,triggers=(TriggerSpec('card_played',PROGRESS),)))
