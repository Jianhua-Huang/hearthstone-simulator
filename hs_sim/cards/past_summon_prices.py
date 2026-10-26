"""Real past spell prices, exact summon material and native pool consumers."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope
from hs_sim.engine.effects import Draw, GainArmor, InvokeBehavior
from hs_sim.engine.model import (BoardPresenceReference, CardClass, CardDefinition, CardType,
    CostSpec, HandCountCostSpec, TreantSummonCountCostSpec, Zone)
from hs_sim.engine.pools import (DiscoverFromPool, FillHandFromPool, GenerateFromPool,
    PoolCard, PoolQuery)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import active_cast
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.spell_targets import ApplySpellTarget, DamageResidentSpellTarget
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOTS = ('TTN_954', 'RLK_590', 'CORE_ICC_085', 'CORE_REV_365', 'GDB_857')
GHOUL = 'ICC_085t'
PREFIX = 'cards.past_summon_prices.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/past-summon-prices-v1.json'
BATCH_HASH = '709d83e5f31711453589673009622abccd32786192a60093c2d01b038dd4ed32'
SPELLS = PoolQuery(kinds=(CardType.SPELL,), collectible=True)
DRUID_SPELLS = PoolQuery(kinds=(CardType.SPELL,), collectible=True,
    class_mode='specified', classes=(CardClass.DRUID,), include_neutral=False)
PAST_TEN = PoolQuery(kinds=(CardType.MINION,), min_cost=10, max_cost=10,
    collectible=True, class_mode='current')


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = value['cards']+value['dependencies']+value['evidence_only']
    if (canonical_digest(value) != BATCH_HASH or value['schema'] != 1 or
            tuple(x['record']['id'] for x in value['cards']) != ROOTS or
            tuple(x['record']['id'] for x in value['dependencies']) != (GHOUL,) or
            value['formal_pool_complete'] is not False or value['cn_calibrated'] is not False or
            len(value['official_faces']) != 12 or
            len(value['treant_member_ids']) != 29 or
            value['treant_member_ids'] != sorted(set(value['treant_member_ids'])) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in rows)):
        raise TargetValidationError('Past price/pool spells lost their complete native source scope')
    originals = {x['record']['id']:x['record'] for x in rows}
    if any(originals[cid]['type']!='MINION' or originals[cid]['tags'].get('2831')!=1
            for cid in value['treant_member_ids']):
        raise TargetValidationError('Treant price family lost its complete fixed original marker inventory')
    for core, original in (('CORE_ICC_085','ICC_085'), ('CORE_REV_365','REV_365')):
        a, b = originals[core], originals[original]
        faces = [x for x in value['official_faces'] if x['card_id']==original]
        if (len(faces)!=2 or any(a['dbf_id'] not in x['face'].get('copyOfCardId',()) for x in faces) or
                any(a[k]!=b[k] for k in ('type','cost','text_en'))):
            raise TargetValidationError('Core reserve identity lost its full original spell and copy association')
    return value


def register_past_summon_prices(registry):
    value = load_batch(); rows = {x['record']['id']:x['record'] for x in value['cards']+value['dependencies']}
    if any(cid in registry.cards for cid in rows):
        raise TargetValidationError('Past price/pool cards cannot replace existing native identities')

    def ghoul(c):
        record = active_cast(c.state, c.source_id, c.player_id)
        if record is None or record.card_id!='CORE_ICC_085' or not record.payload_started:
            raise UnsupportedDefinitionError('Infestation summon requires its original active CAST')
        cause = SummonCause.capture(replace(c, cast=record))
        return (SummonByCard(c.player_id, (SummonEntryMaterial(GHOUL),), cause),)

    def infestation(c):
        target = c.state.entities.get(c.target_id)
        damage = ()
        if target is not None:
            if target.kind==CardType.MINION and target.zone==Zone.BOARD:
                damage = (DamageResidentSpellTarget(BoardPresenceReference.capture(c.state,target.id),c.source_id,5),)
            elif target.kind==CardType.HERO:
                damage = (ApplySpellTarget(target.id,c.source_id,'damage',5),)
        return (*damage, Draw(c.player_id,5,c.source_id), GainArmor(c.player_id,5),
            InvokeBehavior(PREFIX+'ghoul',c.source_id,c.player_id))

    bodies = {
        'TTN_954': lambda c: (BuffMinionsInZones(c.player_id,2,2,MinionScope((Zone.BOARD,)),c.source_id),),
        'RLK_590': lambda c: (FillHandFromPool(GenerateFromPool(c.player_id,'constructed.cards',
            SPELLS,source_id=c.source_id)),),
        'CORE_ICC_085': infestation,
        'ghoul': ghoul,
        'CORE_REV_365': lambda c: (CastFromPool(c.player_id,'constructed.cards',DRUID_SPELLS,
            count=8,source_id=c.source_id),),
        'GDB_857': lambda c: (DiscoverFromPool(c.player_id,'constructed.past.cards',PAST_TEN,
            source_id=c.source_id,cost=CostSpec(set_to=1)),),
    }
    for name,body in bodies.items(): registry.register_behavior(PREFIX+name,body)
    for cid,raw in rows.items():
        kind = CardType(raw['type'].lower()); fields = {}
        if cid=='TTN_954': fields['player_summon_count_cost']=TreantSummonCountCostSpec(tuple(value['treant_member_ids']))
        elif cid=='RLK_590': fields['hand_count_cost']=HandCountCostSpec()
        elif cid=='CORE_ICC_085': fields.update(requires_target=True,target_rule='any_character')
        if kind==CardType.MINION: fields.update(attack=raw['attack'],health=raw['health'])
        else: fields['on_play']=PREFIX+cid
        meta = metadata_from_record(raw)
        if cid in ('CORE_ICC_085','CORE_REV_365'):
            meta = replace(meta,deck_identity='ICC_085' if cid=='CORE_ICC_085' else 'REV_365')
        card = CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=meta,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),**fields)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
