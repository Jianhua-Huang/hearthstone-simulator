"""Complete current Explosive Runes using one shared SPELL damage budget."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.excess_damage import DamageExcessToHero
from hs_sim.engine.model import CardDefinition, CardType, Keyword, SecretSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .health_cards import SCHOOLS

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/excess-secret-effects-v1.json'
BATCH_HASH='2b29db90982b228cda92141c9846b16dea61832876666351e22d0ae1fdc5ad9f'
BODY='cards.excess_secret.runes'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Excess secret content differs from its reviewed complete source pin')
    return data


def runes(c):
    target=c.state.entities[c.event.source_id]
    return (DamageExcessToHero(MinionReference.capture(target),6,c.source_id),)


def register_excess_secret_cards(registry):
    registry.register_behavior(BODY,runes)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe']
        if raw['id']!='CORE_LOOT_101' or canonical_digest(raw)!=row['record_sha256'] or (
                raw['cost']!=recipe['cost'] or raw['tags'].get('SECRET')!=1):
            raise TargetValidationError('Unreviewed Explosive Runes record')
        definition=CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=raw['cost'],
            keywords=(Keyword.SECRET,),spell_school=SCHOOLS[raw['tags']['SPELL_SCHOOL']],
            secret=SecretSpec('LOOT_101',('card_played',),'m4.minion_played',BODY),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']))
        registry.register_card(definition);registry.register_pool_card(PoolCard.from_definition(definition))
