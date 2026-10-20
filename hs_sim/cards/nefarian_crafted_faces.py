"""Original Nefarian creation blueprint; this does not authorize its curated pool."""
import json
from pathlib import Path
from dataclasses import replace

from hs_sim.engine.crafted_faces import CraftedMinionBlueprint
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='CATA_470'
TEMPLATE=CARD+'t1'
EXISTING=(TEMPLATE,'TIME_045','CORE_OG_149','CORE_EX1_043','CORE_EX1_012')
DECK_IDENTITIES={'CORE_OG_149':'OG_149','CORE_EX1_043':'EX1_043','CORE_EX1_012':'EX1_012'}
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/nefarian-crafted-faces-v1.json'
BATCH_HASH='7993001b660be0c90810037bae02ccdbd8914e6977d81000260a52aae986263c'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'));rows=data['cards']+data['existing_dependencies']
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in rows)!=(CARD,*EXISTING)or
            data['dependencies']or data['evidence_only']or data['skipped']or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Crafted face foundation lost its complete original creator/template/ingredients')
    return data


def register_nefarian_crafted_faces(registry):
    for row in load_batch()['existing_dependencies']:
        raw=row['record'];old=registry.card(raw['id'])
        metadata=metadata_from_record(raw)
        if raw['id']in DECK_IDENTITIES:metadata=replace(metadata,deck_identity=DECK_IDENTITIES[raw['id']])
        if (old.cost,old.attack,old.health,old.metadata)!=(raw['cost'],raw['attack'],raw['health'],metadata):
            raise TargetValidationError('Crafted face foundation changed an existing complete physical ingredient')
    # Native donation capability is not generation eligibility. Curated source
    # inventories must never be reduced to this reviewed executable subset.
    for card_id in EXISTING[1:]:registry.register_crafted_minion_part(card_id)
    registry.register_crafted_minion_blueprint(CraftedMinionBlueprint(TEMPLATE,'dragon','undead'))
