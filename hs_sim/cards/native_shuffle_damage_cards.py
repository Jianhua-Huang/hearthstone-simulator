"""Native damage reads committed semantic shuffle facts, never diagnostic logs."""
import json
from pathlib import Path
from hs_sim.engine.deck_shuffles import capture_cost
from hs_sim.engine.effects import Damage
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-shuffle-damage-v1.json'
BATCH_HASH='a543984b85df606f2209db0414e8eaef39c3aa8a9fbcecc9d380af43fe34f6de'
KNOCKBACK='TLC_517';BODY='cards.native_shuffle_damage.knockback'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(KNOCKBACK,)
            or any(d[k]for k in ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Native shuffle damage lost its complete reviewed source')
    if any(canonical_digest(x['record'])!=x['record_sha256']for x in d['cards']):
        raise TargetValidationError('Native shuffle damage original full row changed')
    return d


def register_native_shuffle_damage_cards(registry):
    row,=load_batch()['cards'];raw=row['record']
    if raw['type']!='SPELL' or raw['tags'].get('TAG_SCRIPT_DATA_NUM_1')!=1:
        raise TargetValidationError('Knockback requires its actual native spell profile')
    def body(c):
        amount=raw['tags']['TAG_SCRIPT_DATA_NUM_1']+capture_cost(c.state,c.player_id).quantity
        return (Damage(c.target_id,amount,c.source_id,DamageKind.SPELL),)
    registry.register_behavior(BODY,body)
    card=CardDefinition(KNOCKBACK,raw['name'],CardType.SPELL,cost=raw['cost'],
        metadata=metadata_from_record(raw),on_play=BODY,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
