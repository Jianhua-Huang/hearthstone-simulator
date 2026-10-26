"""Original Yogg composes accepted personal hand roots and public pool casting."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.spell_history import CastFromPool,SpellHistoryQuery,personal_hand_spell_count
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='OG_134'
BODY='cards.original_yogg.native_random_spells'
POOL='constructed.cards'
QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True)
HISTORY=SpellHistoryQuery(origins=('hand',),outcomes='attempts')
CAP=30
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/original-yogg-native-v1.json'
BATCH_HASH='148a43bc83a82ebd5c72d6a995f2e7bc20200803500fed815fe7183486b9655e'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            tuple(x['record']['id']for x in data['cards'])!=(CARD,) or
            any(data[k]for k in ('dependencies','existing_dependencies','evidence_only','skipped')) or
            len(data['official_faces'])!=2 or data['policy']['per_battlecry_cap']!=CAP or
            data['formal_pool_complete']is not False or data['cn_calibrated']is not False or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in data['cards'])):
        raise TargetValidationError('Original Yogg requires its complete native face and explicit local casting policy')
    return data


def register_original_yogg_native(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags']['CLASS'])!=('MINION',10,7,5,12):
        raise TargetValidationError('Original Yogg lost its actual neutral 10-mana 7/5 face')
    if CARD in registry.cards:raise TargetValidationError('Original Yogg cannot overwrite a reviewed native identity')
    def cast(c):
        if (c.battlecry is None or not c.battlecry.payload_started or c.battlecry.failure is not None or
                (c.battlecry.source_id,c.battlecry.player_id)!=(c.source_id,c.player_id)):
            raise ResolutionError('Original Yogg requires its actual accepted Battlecry')
        count=min(CAP,personal_hand_spell_count(c.state,registry,c.player_id,c.source_id))
        return ()if not count else(CastFromPool(c.player_id,POOL,QUERY,count=count,source_id=c.source_id,
            replacement=True,refresh='per_cast',targeting='random',choices='random',while_source_in_play=False),)
    registry.register_behavior(BODY,cast)
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
