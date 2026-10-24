"""Real Ivus: original all-Mana debit and fixed stat/keyword rewards."""
import json
from pathlib import Path
from hs_sim.engine.bonus_effects import SpendManaForRandomGrowth
from hs_sim.engine.effects import SpendMana
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

IVUS='AV_142t'
DEPENDENCIES=(IVUS,)
COLLECTIBLE_ROOTS=()
BODY='cards.past_remaining_mana_rewards.ivus'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-remaining-mana-rewards-v1.json'
BATCH_HASH='86e410d6a938c4cdd8b87b0b664bf8b4a869b46f167bfc91b5de22a3746ad71c'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(d['collectible_leaf_ids'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            any(d[k]for k in('cards','existing_dependencies','evidence_only','choice_only','skipped',
                'numeric_normalizations','display_normalizations')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Ivus lost its complete original source and exact scope')
    return d


def register_past_remaining_mana_rewards_cards(registry):
    def body(c):
        if c.source.zone!=Zone.BOARD:return(SpendMana(c.player_id,source_id=c.source_id),)
        return(SpendManaForRandomGrowth(c.player_id,BoardPresenceReference.capture(c.state,c.source_id)),)
    registry.register_behavior(BODY,body);raw=load_batch()['dependencies'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),
            raw['tags'].get('RARITY'),raw['tags'].get('BATTLECRY'))!=('MINION',1,1,1,12,5,1):
        raise TargetValidationError('Ivus requires its real Neutral legendary 1/1 face')
    card=CardDefinition(IVUS,raw['name'],CardType.MINION,cost=1,attack=1,health=1,
        battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
