"""One actual Battlecry delegates different-edition selection to physical recruit."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.recruit_expansions import RecruitExpansionProfile
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .time_lord_nozdormu_card import load_batch as printed_inventory

CARD='WORK_043'
BODY='cards.dungar.distinct_printed_expansion'
PROFILE='physical-recruit.distinct-printed-expansion-cn37-v1'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/dungar-expansion-recruit-v1.json'
BATCH_HASH='a28c0b5da02422e55ae94478edc9fd97227483774c340293033066800822ac07'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['policy_id']!=PROFILE or
            tuple(x['record']['id']for x in data['cards'])!=(CARD,) or
            any(data[k]for k in ('dependencies','existing_dependencies','evidence_only','skipped')) or
            len(data['official_faces'])!=2 or data['formal_pool_complete']is not False or data['cn_calibrated']is not False or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in data['cards'])):
        raise TargetValidationError('Dungar requires its complete original source, primary faces and printed inventory policy')
    return data


def register_dungar_expansion_recruit(registry):
    data=load_batch();raw=data['cards'][0]['record'];inventory=printed_inventory()
    pin=data['printed_inventory'];editions=inventory['printed_card_sets']
    if (pin['file']!='data/cards/time-lord-nozdormu-v1.json' or canonical_digest(inventory)!=pin['canonical_sha256'] or
            canonical_digest(editions)!=pin['inventory_sha256'] or len(editions)!=pin['rows'] or pin['rows']!=23452 or
            raw['card_set_id']!=editions[CARD] or
            (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags']['CLASS'])!=('MINION',10,3,3,12)):
        raise TargetValidationError('Dungar lost the complete pinned native printed expansion table or actual face')
    if CARD in registry.cards:raise TargetValidationError('Dungar cannot overwrite an existing native identity')
    def recruit(c):
        if (c.battlecry is None or not c.battlecry.payload_started or c.battlecry.failure is not None or
                (c.battlecry.source_id,c.battlecry.player_id)!=(c.source_id,c.player_id)):
            raise ResolutionError('Dungar requires its original accepted Battlecry')
        return (SummonFromZone(c.player_id,count=3,source_id=c.source_id,cause=SummonCause.capture(c),
            expansion_profile=PROFILE),)
    registry.register_behavior(BODY,recruit)
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_recruit_expansion_profile(RecruitExpansionProfile(PROFILE,tuple(sorted(editions.items()))))
