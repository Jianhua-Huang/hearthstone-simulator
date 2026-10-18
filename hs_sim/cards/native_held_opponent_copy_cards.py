"""Native opponent-copy consumers share original held-play facts."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch, Destroy, InvokeBehavior
from hs_sim.engine.held_opponent_copies import CONDITION, HISTORY, KIND, satisfied
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, HandProgressSpec, IntrinsicCostSpec, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

CARD, BODY = 'JAIL_433', 'cards.held_opponent_copy.unshackle_soul'
SWEEPER, SWEEP_BODY = 'JAIL_432', 'cards.held_opponent_copy.mind_sweeper'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-held-opponent-copy-v1.json'
BATCH_HASH = '70315b8314968502c249f73f81b5654cc8c0229be628fdf8f243a455236e0f55'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value) != BATCH_HASH or tuple(row['record']['id'] for row in value['cards']) != (CARD,SWEEPER) or
            any(value[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Unshackle Soul requires her complete reviewed source')
    for row in value['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Native opponent-copy original source changed')
    return value


def register_native_held_opponent_copy_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if raw['type'] != 'SPELL' or raw['cost'] != 5 or raw['tags'].get('SPELL_SCHOOL') != 6:
        raise TargetValidationError('Unshackle Soul changed her printed Shadow face')
    registry.register_behavior(BODY, lambda c: (Destroy(c.target_id, c.source_id),))
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'], on_play=BODY,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)), spell_school=SCHOOLS[6],
        hand_progress=HandProgressSpec(KIND),
        intrinsic_costs=(IntrinsicCostSpec(set_to=1, condition=CONDITION, history_profile_id=HISTORY),),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
    raw = load_batch()['cards'][1]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY')) != ('MINION',2,2,3,1):
        raise TargetValidationError('Mind Sweeper changed its complete native Battlecry face')
    def sweep(c):
        if not satisfied(c): return ()
        return (DamageBatch(tuple(Damage(eid,2,c.source_id,DamageKind.MINION_ABILITY)
            for eid in minions(c,registry,3-c.player_id))),)
    registry.register_behavior(SWEEP_BODY,lambda c:(InvokeBehavior(SWEEP_BODY+'.now',c.source_id,
        c.player_id,c.target_id,None if c.play is None else c.play.id),))
    registry.register_behavior(SWEEP_BODY+'.now',sweep)
    card = CardDefinition(SWEEPER,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=SWEEP_BODY,hand_progress=HandProgressSpec(KIND),metadata=metadata_from_record(raw))
    registry.register_card(card)
    if SWEEPER not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
