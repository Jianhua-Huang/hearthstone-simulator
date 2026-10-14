"""Freeze broad raw scope and a deliberately bounded mechanism demonstration pool."""
from pathlib import Path
from collections import Counter,defaultdict
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from hs_sim.targets import canonical_digest
from hs_sim.engine.class_tags import classes_from_tags, CLASS_TAGS

SOURCE_HASH='fd0a3412afa031504f0553210670d6c14ce02ca952819f7524514a8003b86c08'
POOL_ID='representative.architect-spells'
# Chosen for distinct composition obligations, not by intersecting registry.cards.
SAMPLES={
    'CS2_028':'Enemy batch damage plus Freeze, reacquisition/copy and repeat targets.',
    'CS2_032':'Enemy batch damage, death checkpoints and later repeat with a changed board.',
    'EX1_279':'Original chosen character target, single payment, repeat and terminal handling.',
    'EX1_164':'Different current hero class, Choose One branch and repeated payload.',
    'CS2_029':'Below-five-cost spell counterexample.',
    'JAIL_123':'Source minion counterexample; Battlecry references a spell but is not a spell.',
}


def build_inventory(rows,source_sha256,enum_sha256,entity_base_sha256):
    by_id={r['id']:r for r in rows}
    raw=[r for r in rows if r['type']=='SPELL' and r['collectible'] and type(r['cost']) is int and r['cost']>=5]
    names=defaultdict(list);classes={};audited=[]
    for r in raw:
        decoded=[c.value for c in classes_from_tags(r['tags'])];classes[r['id']]=decoded
        names[r['name_en']].append(r['id'])
        audited.append(dict(data=r,data_sha256=canonical_digest(r),classes=decoded))
    return dict(schema_version=1,target_id='local-2026-09-23',source_sha256=source_sha256,
        enum_sha256=enum_sha256,entity_base_sha256=entity_base_sha256,
        raw_filter='type=SPELL, collectible=true, integer printed cost>=5; no executable, legality or identity filter',
        complete=False,mode_legality_verified=False,cn_source_availability_verified=False,
        class_decode='Nonzero uint32 MULTIPLE_CLASSES takes precedence; bit n maps to TAG_CLASS n+1; otherwise CLASS. Unknown/non-playable bits rejected.',
        generation_rules_applied=False,raw_spells=audited,
        raw_class_scopes={cls.value:[r['id'] for r in raw if cls.value in classes[r['id']] or 'neutral' in classes[r['id']]]
            for cls in CLASS_TAGS.values() if cls.value!='neutral'},
        name_groups_for_review=[dict(name=name,ids=ids,identity_merged=False) for name,ids in sorted(names.items()) if len(ids)>1],
        source=dict(data=by_id['JAIL_123'],data_sha256=canonical_digest(by_id['JAIL_123'])),
        experimental_pool=dict(id=POOL_ID,version='representative-architect-spells-v1',mode='experimental',complete=False,
            selection_basis='Explicit mechanism cases and negative controls; not all discoverable spells and not a formal CN pool.',
            members=list(SAMPLES),rows=[dict(data=by_id[cid],data_sha256=canonical_digest(by_id[cid]),reason=why) for cid,why in SAMPLES.items()]),
        unresolved=['CN release/format legality and patch-effective faces','Full candidate adaptation',
            'Generation identity aliases and special exclusions','Official current-class discovery and repeat interaction calibration'])


def main():
    path=ROOT/'data/extracted/cards.json';digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=SOURCE_HASH:raise ValueError('Raw source changed; review before updating inventory')
    enum_path=ROOT/'data/schema/enums.json';enums=json.loads(enum_path.read_text(encoding='utf-8'))
    expected={'DEATHKNIGHT':1,'DRUID':2,'HUNTER':3,'MAGE':4,'PALADIN':5,'PRIEST':6,'ROGUE':7,
              'SHAMAN':8,'WARLOCK':9,'WARRIOR':10,'NEUTRAL':12,'DEMONHUNTER':14}
    if any(enums['TAG_CLASS'].get(k)!=v for k,v in expected.items()):raise ValueError('Pinned class enums changed')
    evidence=ROOT/'reports/decompiled/entity/EntityBase.cs'
    inventory=build_inventory(json.loads(path.read_text(encoding='utf-8')),digest,
        hashlib.sha256(enum_path.read_bytes()).hexdigest(),hashlib.sha256(evidence.read_bytes()).hexdigest())
    destination=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'data/support/card-spell-source-inventory.json'
    destination.write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(inventory_hash=canonical_digest(inventory),raw_records=len(inventory['raw_spells']),
        raw_class_scopes={c:len(ids) for c,ids in inventory['raw_class_scopes'].items()},
        name_groups=len(inventory['name_groups_for_review']),formal_pool=False),ensure_ascii=False))


if __name__=='__main__':main()
