"""A real after-cast consumer reads the accepted original target material."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Draw
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_casts import cast_record
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

FRAGMENT='END_026';PREFIX='cards.native_cast_target.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-cast-target-v1.json'
BATCH_HASH='04d663edab84f9058bcda5dfe5099cb31cecfd2a3c16986361b52ab493d2beb4'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Native cast target lost its complete source pin')
    if tuple(x['record']['id']for x in data['cards'])!=(FRAGMENT,)or data['dependencies']:
        raise TargetValidationError('Unreviewed original-target consumer')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original cast-target source')
    return data


def register_native_cast_target_cards(registry):
    def fragment(c):
        cast=cast_record(c.state,dict(c.event.data)['cast_id'])
        if (cast.source_id,cast.player_id,cast.target_id)!=(c.event.source_id,c.event.player_id,c.event.target_id):
            raise ResolutionError('Fragment lost its original successful cast')
        if not cast.completed or not cast.payload_started or cast.failure is not None or cast.interrupted:
            raise ResolutionError('Fragment requires an actual successful cast completion')
        if (cast.player_id!=c.player_id or not living_source(c)or cast.target_origin is None or
                cast.target_origin.kind!=CardType.MINION):return ()
        return(Draw(c.player_id,source_id=c.source_id),)
    registry.register_behavior(PREFIX+'fragment',fragment)
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['collectible'],raw['cost'],raw['attack'],raw['health'])!=('MINION',True,4,3,6):
        raise TargetValidationError('Unreviewed native Fragment face')
    card=CardDefinition(FRAGMENT,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=replace(metadata_from_record(raw),deck_identity=FRAGMENT),triggers=(TriggerSpec('spell_cast_finished',PREFIX+'fragment'),))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
