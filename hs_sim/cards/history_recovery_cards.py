"""Real death resurrection and previous-own-turn spell recovery consumers."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand
from hs_sim.engine.model import CardDefinition,CardType,PlayedTypeQuery
from hs_sim.engine.owner_turns import query_previous_owner_turn,validate_face
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery,Resurrect
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/history-recovery-effects-v1.json'
BATCH_HASH='a1058c66a02ae8e343a80c471e464640eaa867196d3ef60872bb560e5faf2523'
PREFIX='cards.history_recovery.'
SCRIPTS={'CORE_CATA_002':'highest_death','CORE_TRL_345':'previous_spells'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:
        raise TargetValidationError('History recovery cards differ from their complete reviewed pin')
    return value


def register_history_recovery_cards(registry):
    def previous_spells(c):
        # The query's rows include every spell, even an unschooled false match.
        # Its matched aggregate answers a different question and is not a filter.
        previous=query_previous_owner_turn(c.state,c.player_id,PlayedTypeQuery(CardType.SPELL))
        for row in previous.rows:validate_face(row.face,registry)
        return tuple(AddToHand(c.player_id,row.face.card_id,c.source_id)for row in previous.rows)

    bodies=dict(highest_death=lambda c:(Resurrect(c.player_id,query=DeathQuery(cost_extreme='highest'),
        source_id=c.source_id,cause=SummonCause.capture(c)),),previous_spells=previous_spells)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    batch=load_batch()
    for row in batch['historical_identity_evidence']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Historical recovery identity changed')
    for row in batch['cards']:
        raw,recipe=row['record'],row['recipe']
        if(canonical_digest(raw)!=row['record_sha256']or SCRIPTS.get(raw['id'])!=recipe['script']
                or raw['type']!='MINION'or raw['collectible']is not True or raw['tags'].get('BATTLECRY')!=1):
            raise TargetValidationError('Unreviewed history recovery face')
        definition=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],
            attack=raw['attack'],health=raw['health'],battlecry=PREFIX+recipe['script'],
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']))
        registry.register_card(definition);registry.register_pool_card(PoolCard.from_definition(definition))
