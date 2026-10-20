"""Original Osk keeps one physical root and selects reviewed Battlecry bodies."""
import json
from pathlib import Path

from hs_sim.engine.held_battlecry_forms import HeldBattlecryFormsProfile, target_allowed
from hs_sim.engine.model import CardDefinition, CardType, TargetMode, TargetSpec
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='TLC_452'; RULE='cards.osk.held_battlecry_target'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/titanographer-osk-v1.json'
BATCH_HASH='be613ebcd11115be184bb7e2a7ddf9632e6c081ddcdd0bae5015ca5b6f6b29fc'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'));forms=data['forms']
    rows=(*data['cards'],*data['existing_dependencies'])
    if (canonical_digest(data)!=BATCH_HASH or len(forms)!=31 or len(set(forms))!=31 or
            tuple(x['record']['id']for x in rows)!=(CARD,*forms) or
            any(data[k]for k in ('dependencies','evidence_only','skipped')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Osk requires its complete root and all31 reviewed actual forms')
    raw=rows[0]['record']
    if (raw['type'],raw['collectible'],raw['cost'],raw['attack'],raw['health'])!=('MINION',True,6,6,6):
        raise TargetValidationError('Original Osk printed root changed')
    primary=next(x['face']for x in data['official_observations']if x['card_id']==CARD and x['locale']=='en_US')
    if primary['childIds']!=[row['record']['dbf_id']for row in data['existing_dependencies']]:
        raise TargetValidationError('Osk real forms differ from complete official family links')
    return data


def register_titanographer_osk_card(registry):
    data=load_batch();raw=data['cards'][0]['record']
    registry.register_player_target_rule(PlayerTargetRuleSpec(RULE,'v1'),lambda c:target_allowed(registry,c))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=6,attack=6,health=6,
        metadata=metadata_from_record(raw),targeting=TargetSpec(TargetMode.IF_AVAILABLE),target_rule=RULE)
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_held_battlecry_forms_profile(HeldBattlecryFormsProfile(CARD,tuple(data['forms'])))
