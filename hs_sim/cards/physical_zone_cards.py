"""Real discard, complete deck destruction and summon/equip card bodies."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import EquipWeapon
from hs_sim.engine.model import CardDefinition, CardType, Keyword, Zone
from hs_sim.engine.play_history import starting_deck_identity
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, DestroyDeckBatch, DiscardMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/physical-zone-effects-v1.json'
BATCH_HASH='16e4dc9606e64adba3f7cf30a671a3e5089f100cc1a0750a7325849cd8e99083'
PREFIX='cards.physical_zones.'
SCRIPTS={'CORE_EX1_310':'doomguard','CORE_REV_946':'steamcleaner','CORE_GVG_061':'muster','CS2_091':'weapon'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:
        raise TargetValidationError('Physical zone cards differ from their complete reviewed source pin')
    return value


def register_physical_zone_cards(registry):
    batch=load_batch();dependency=batch['reused_dependencies'][0];raw=dependency['record']
    recruit=registry.card(raw['id'])
    if (canonical_digest(raw)!=dependency['record_sha256']or(raw['id'],raw['dbf_id'])!=('CS2_101t',1652)
            or(recruit.kind,recruit.cost,recruit.attack,recruit.health)!=(CardType.MINION,1,1,1)):
        raise TargetValidationError('Muster lost its complete named Silver Hand Recruit')

    def steamcleaner(c):
        originals,_cards=starting_deck_identity(c.state)
        original_ids={eid for group in originals for eid in group}
        targets=[]
        for player_id in (1,2):
            for entity_id in c.state.players[player_id].deck:
                entity=c.state.entities[entity_id]
                registry.card(entity.card_id)  # Validate the whole inventory, including protected rows.
                if entity_id not in original_ids or entity.face_replaced:
                    targets.append(CardReference.capture(entity))
        return (DestroyDeckBatch(tuple(targets),c.source_id),)

    def muster(c):
        cause=SummonCause.capture(c)
        return (*(SummonByCard(c.player_id,(SummonEntryMaterial('CS2_101t'),),cause)for _ in range(3)),
                EquipWeapon(c.player_id,'CS2_091'))

    bodies=dict(doomguard=lambda c:(DiscardMatching(c.player_id,count=2,source_id=c.source_id),),
                steamcleaner=steamcleaner,muster=muster)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    identities={row['record']['id']:row for row in batch['historical_identity_evidence']}
    for row in identities.values():
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Physical zone historical identity changed')
    for row in batch['cards']:
        raw,recipe=row['record'],row['recipe'];kind=CardType(raw['type'].lower())
        if (canonical_digest(raw)!=row['record_sha256']or SCRIPTS.get(raw['id'])!=recipe['script']
                or raw['cost']!=recipe['cost']or(raw['attack']or 0)!=recipe['attack']):
            raise TargetValidationError('Unreviewed physical-zone card face')
        if recipe['role']=='root':
            if not raw['collectible']or recipe['deck_identity']not in identities:
                raise TargetValidationError('Physical zone root lost its reviewed identity')
        elif(raw['id'],kind)!=( 'CS2_091',CardType.WEAPON):
            raise TargetValidationError('Unknown physical-zone dependency')
        kwargs={}
        if kind==CardType.MINION:
            if raw['health']!=recipe['health']:raise TargetValidationError('Physical zone minion health changed')
            kwargs['battlecry']=PREFIX+recipe['script']
        elif kind==CardType.SPELL:kwargs['on_play']=PREFIX+recipe['script']
        elif kind==CardType.WEAPON:
            if raw['health']!=recipe['durability']:raise TargetValidationError('Weapon durability must match the source HEALTH field')
            kwargs['durability']=recipe['durability']
        else:raise TargetValidationError('Unsupported physical-zone card kind')
        definition=CardDefinition(raw['id'],raw['name'],kind,cost=recipe['cost'],attack=recipe['attack'],
            health=recipe['health'],keywords=tuple(Keyword(k)for k in recipe['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(definition);registry.register_pool_card(PoolCard.from_definition(definition))
