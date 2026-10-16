"""Reviewed matching-hand disruption and secret damage-fragile real copy."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import CopyMinion
from hs_sim.engine.copy_followups import original_copy_reference
from hs_sim.engine.hand_identity_shuffle import ShuffleSharedHandCard
from hs_sim.engine.hidden_damage_pairs import MarkHiddenDamagePair
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.sacrifice import DestroyCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/hand-mirror-demons-v1.json'
BATCH_HASH='7ec4749601a8d4c636ab8013fdf8ec122bdabf8fe57fa66175c920dc65e33cd0'
PREFIX='cards.hand_mirror.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Hand mirror content differs from its complete reviewed pin')
    return data


def register_hand_mirror_cards(registry):
    def illusion(c):return(CopyMinion(c.source_id,c.player_id,cause=SummonCause.capture(c),on_summon=PREFIX+'mark'),)
    def mark(c):
        return(MarkHiddenDamagePair(original_copy_reference(c),MinionReference.capture(c.state.entities[c.target_id]),
            PREFIX+'fragile',PREFIX+'real',c.source_id),)
    def fragile(c):
        event=c.event
        return(DestroyCapturedMinion(MinionReference.capture(c.source),c.source_id),)if event is not None and event.kind=='damage_dealt'and event.target_id==c.source_id and event.amount>0 else()
    for key,body in dict(assailant=lambda c:(ShuffleSharedHandCard(c.player_id,c.source_id),),illusion=illusion,
                         mark=mark,fragile=fragile,real=lambda c:()).items():registry.register_behavior(PREFIX+key,body)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or not raw['collectible']:
            raise TargetValidationError('Hand mirror card lost its complete printed face')
        if cid not in('EDR_524','EDR_780'):raise TargetValidationError('Unknown hand mirror recipe')
        metadata=replace(metadata_from_record(raw),deck_identity=row['recipe']['deck_identity'])
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=metadata,battlecry=PREFIX+('assailant'if cid=='EDR_524'else'illusion'))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
