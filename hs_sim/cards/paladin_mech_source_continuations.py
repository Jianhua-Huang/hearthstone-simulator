"""Two real Paladin Mechs consume stored launch forms and physical Dredge rewards."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.dredge import DredgeWithSourceStats
from hs_sim.engine.model import AuraSpec, CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.stored_launch_forms import StoredLaunchFormProfile
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/paladin-mech-source-continuations-v1.json'
BATCH_HASH = '7ad599f9b03394805f221e8e7d08d782e3e043c5ea07dd1b7b1f7a9c6a907ea9'
HELLION, SAVIOR = LEAVES = ('SC_412','TSC_083')
HELLBAT = 'SC_412t'
COLLECTIBLE_ROOTS = ()
DEPENDENCIES = LEAVES
BODY = 'cards.paladin_mech_source_continuations.dredge'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(v['record']['id'] for v in data['dependencies']) != LEAVES or
            tuple(v['record']['id'] for v in data['existing_dependencies']) != (HELLBAT,) or
            tuple(v['record']['id'] for v in data['evidence_only']) != ('TSC_083e',) or
            any(data[k] for k in ('cards','skipped','formal_pool_complete','cn_calibrated')) or
            data['hellion_form'] != HELLBAT or data['hellion_zones'] != ['hand','deck'] or
            len(data['official_observations']) != 4 or not set(LEAVES)<=set(reference['candidate_ids'])):
        raise TargetValidationError('Paladin Mechs require their complete native forms and original reference')
    if any(canonical_digest(v['record']) != v['record_sha256'] for v in
            data['dependencies']+data['existing_dependencies']+data['evidence_only']):
        raise TargetValidationError('Paladin Mechs lost a complete original source row')
    return data


def register_paladin_mech_source_continuations(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Paladin Mechs changed their complete original Hellbat form')
    if HELLION in registry.stored_launch_form_profiles or HELLBAT in registry.stored_launch_form_profiles:
        raise TargetValidationError('Paladin launch form cannot overwrite or chain an existing source')
    prepared = []
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards: raise TargetValidationError('Paladin Mechs cannot overwrite an existing native card: '+cid)
        fields = dict(auras=(AuraSpec(attack=1),)) if cid == HELLION else dict(battlecry=BODY)
        card = CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
            health=raw['health'],metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card); prepared.append(card)
    registry.register_behavior(BODY,lambda c:(DredgeWithSourceStats(c),))
    for card in prepared:
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_stored_launch_form_profile(StoredLaunchFormProfile(HELLION,HELLBAT))
