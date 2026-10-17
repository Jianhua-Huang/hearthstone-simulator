"""Pinned experimental sources; their scope is independent of adapter coverage."""
import json
from pathlib import Path
from hs_sim.targets import canonical_digest, TargetValidationError
from .model import CardType, SpellSchool
from .pools import PoolCard, PoolDefinition, PoolMember

INVENTORY_HASH='31351ae51518fd617bfd382c8c2041a54ceef13bd66e586fc2b7786f2a9ba58e'
POOL_ID='representative.architect-spells'


def register_pool(registry, baseline, metadata_from_record):
    path=Path(__file__).resolve().parents[2]/'data/support/card-spell-source-inventory.json'
    inventory=json.loads(path.read_text(encoding='utf-8'))
    if canonical_digest(inventory)!=INVENTORY_HASH:
        raise TargetValidationError('Card spell source inventory differs from its pinned version')
    sample=inventory['experimental_pool']
    schools={1:SpellSchool.ARCANE,2:SpellSchool.FIRE,3:SpellSchool.FROST,4:SpellSchool.NATURE,
             5:SpellSchool.HOLY,6:SpellSchool.SHADOW,7:SpellSchool.FEL}
    for entry in sample['rows']:
        raw=entry['data'];cid=raw['id'];tag=raw['tags'].get('SPELL_SCHOOL')
        if canonical_digest(raw)!=entry['data_sha256']:
            raise TargetValidationError('Card spell pool raw record fingerprint mismatch')
        if tag is not None and tag not in schools:
            raise TargetValidationError('Unsupported card spell pool school')
        # Freeze/Discover text are behavior descriptions, not intrinsic keyword grants.
        row=PoolCard(cid,CardType(raw['type'].lower()),raw['cost'],metadata_from_record(raw),
            spell_school=schools.get(tag),battlecry=raw['tags'].get('BATTLECRY')==1,
            deathrattle=raw['tags'].get('DEATHRATTLE')==1,choose_one=raw['tags'].get('CHOOSE_ONE')==1)
        if cid in registry.pool_cards:
            if registry.pool_card(cid)!=row:
                raise TargetValidationError('Card spell pool metadata conflicts with another inventory')
        else:registry.register_pool_card(row)
    registry.register_pool(PoolDefinition(sample['id'],sample['version'],baseline.target['target_id'],
        sample['mode'],tuple(PoolMember(i) for i in sample['members']),complete=sample['complete']))
