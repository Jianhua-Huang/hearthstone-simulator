"""Hand of Infinity's actual Battlecry and existing equipped attack restriction."""
import json
from pathlib import Path

from hs_sim.engine.equipment import SetWeaponAttackForTurn
from hs_sim.engine.infinite_damage import INFINITE_HEALTH_VALUE
from hs_sim.engine.model import AttackPolicySpec, CardDefinition, CardType, EquippedWeaponReference, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='END_012'
BODY='cards.hand_of_infinity.set_attack'
INFINITE_ATTACK_VALUE=INFINITE_HEALTH_VALUE
NUMERIC_POLICY='int32-max-set-attack-v1'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/infinite-weapon-attack-v1.json'
BATCH_HASH='9c5e1ca366693a8847c46cabc7ef259bdec23915d71abc7113439cb082612f0d'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id'] for x in data['cards'])!=(CARD,) or
            tuple(x['record']['id'] for x in data['evidence_only'])!=('END_012e',) or
            (data['policy']['numeric_policy'],data['policy']['infinite_attack_value'])!=(NUMERIC_POLICY,INFINITE_ATTACK_VALUE)):
        raise TargetValidationError('Hand of Infinity requires its complete source and explicit numeric policy')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Hand of Infinity complete native raw row changed')
    return data


def register_infinite_weapon_attack_card(registry):
    raw=load_batch()['cards'][0]['record']
    def battlecry(c):
        if c.battlecry is None:
            raise ValueError('Hand of Infinity requires its actual Battlecry')
        e=c.source
        if (e.card_id!=CARD or e.kind!=CardType.WEAPON or e.zone!=Zone.WEAPON or e.controller!=c.player_id
                or not e.active or e.doomed or e.durability<=0 or c.state.players[c.player_id].weapon_id!=e.id):
            return ()
        return (SetWeaponAttackForTurn(EquippedWeaponReference.capture(e),INFINITE_ATTACK_VALUE,c.state.turn,c.source_id),)
    registry.register_behavior(BODY,battlecry)
    card=CardDefinition(CARD,raw['name'],CardType.WEAPON,cost=raw['cost'],attack=raw['attack'],durability=raw['health'],
        battlecry=BODY,attack_policies=(AttackPolicySpec('cannot_attack_heroes'),),metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
