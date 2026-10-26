"""Native Neptulon delegates its accepted hand attacks to ordinary combat."""
import json
from pathlib import Path

from hs_sim.engine.attack_substitution import AttackSubstitutionProfile,original_listener
from hs_sim.engine.model import AppendageSpec,CardDefinition,CardType,Keyword,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='TID_712'
HANDS=('TID_712t','TID_712t2')
BODY='cards.neptulon.attack_substitution'
PROFILE='native-neptulon-attack-substitution-cn37-local-v1'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/neptulon-substitution-v1.json'
BATCH_HASH='176b88d5601dcf791b80a6fff65101466d1fb98f7d856a2cb63c5aabe6163037'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['policy_id']!=PROFILE or
            tuple(x['record']['id']for x in data['cards'])!=(CARD,) or
            tuple(x['record']['id']for x in data['existing_dependencies'])!=HANDS or
            any(data[k]for k in ('dependencies','evidence_only','skipped')) or len(data['official_faces'])!=2 or
            data['formal_pool_complete']is not False or data['cn_calibrated']is not False or
            any(canonical_digest(x['record'])!=x['record_sha256']for k in ('cards','existing_dependencies')for x in data[k])):
        raise TargetValidationError('Neptulon requires complete parent/hand identities and explicit substitution policy')
    return data


def register_neptulon_substitution(registry):
    data=load_batch();raw=data['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags']['CLASS'])!=('MINION',10,7,7,12):
        raise TargetValidationError('Neptulon lost its actual neutral 10-mana 7/7 face')
    if CARD in registry.cards:raise TargetValidationError('Neptulon cannot overwrite a native identity')
    for cid in HANDS:
        card=registry.card(cid)
        if (card.kind,card.cost,card.attack,card.health,card.keywords)!=(CardType.MINION,4,4,2,(Keyword.IMMUNE_WHILE_ATTACKING,)):
            raise TargetValidationError('Neptulon requires the existing original native hand definitions')
    registry.register_behavior(BODY,lambda c:original_listener(c,PROFILE))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(Keyword.COLOSSAL,Keyword.RUSH,Keyword.WINDFURY),
        colossal=(AppendageSpec(HANDS[0],'left'),AppendageSpec(HANDS[1],'right')),
        triggers=(TriggerSpec('attack_declared',BODY),),metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_attack_substitution_profile(AttackSubstitutionProfile(PROFILE,CARD,BODY,HANDS))
