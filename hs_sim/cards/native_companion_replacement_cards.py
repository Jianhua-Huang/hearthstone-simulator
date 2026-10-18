"""Three actual future Animal Companion upgrade roots share the existing family."""
import json
from pathlib import Path

from hs_sim.engine.effects import Draw,InvokeBehavior
from hs_sim.engine.minion_families import UpgradeMinionFamily
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .fixed_companion_cards import COMPANION_FAMILY,companion_effects
from .metadata import metadata_from_record

TAME,ELEKK,ROAM=ROOTS=('MEND_300','MEND_303','MEND_307')
PREFIX='cards.companion_replacement.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-companion-replacement-v1.json'
BATCH_HASH='956db139b4f2d77e7a0d85e10283ef83768841c4b4c786268b6fbece2bb359c5'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(value)!=BATCH_HASH or tuple(x['record']['id']for x in value['cards'])!=ROOTS or
            value['dependencies']or value['evidence_only']or value['skipped']):
        raise TargetValidationError('Future companions require complete reviewed three native roots')
    for row in value['cards']+value['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Future companion complete original row changed')
    return value


def register_native_companion_replacement_cards(registry):
    data=load_batch()
    def upgrade(c,increment):return UpgradeMinionFamily(COMPANION_FAMILY,SummonCause.capture(c),increment)
    bodies={TAME:lambda c:(upgrade(c,1),Draw(c.player_id,source_id=c.source_id)),
        ELEKK:lambda c:(upgrade(c,1),),
        ROAM:lambda c:(upgrade(c,2),InvokeBehavior(PREFIX+'choose',c.source_id,c.player_id)),
        'choose':lambda c:companion_effects(c,registry,'choice')}
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower())
        fields=dict(cost=raw['cost'],metadata=metadata_from_record(raw))
        if cid==ELEKK:fields.update(attack=raw['attack'],health=raw['health'],keywords=(Keyword.TAUNT,),battlecry=PREFIX+cid)
        else:
            fields['on_play']=PREFIX+cid
            if row['spell_school']is not None:fields['spell_school']=SpellSchool(row['spell_school'])
        card=CardDefinition(cid,raw['name'],kind,**fields)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
