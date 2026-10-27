"""Complete declared local Protoss spell inventory and its real native effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.card_conditions import UnknownCardFactError
from hs_sim.engine.effects import AddCostModifier, CopyMinion, Damage, GainArmor, GrantHealthRule
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.model import (BoardPresenceReference, CardAbilityCondition, CardDefinition, CardType,
    CostSpec, DamageKind, HealthFlow, HealthLayer, HealthOp, HealthRule, Keyword, SpellSchool, TargetSpec, Zone)
from hs_sim.engine.physical_draw_groups import DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.spell_sequences import DrawMatchingWithCostReduction
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/protoss-spell-domain-v1.json'
BATCH_HASH = 'e61d5594b6b8745a9ab633148a1323d2d8af3bcaffc8b5b4f7ba7379f14f03f8'
PREFIX = 'cards.protoss_spell_domain.'
LEAVES = ('SW_462','SC_750','SC_753','SC_755','SC_757','SC_759','SC_760','SC_761')
CANDIDATES = ('SC_750','SC_753','SC_755','SC_757','SC_759','SC_760','SC_761')
TOKEN = 'SC_751t'
POOL = 'constructed.protoss.spells'
POLICY = 'local-fixed-raw-protoss-spells-v1'
FIRE = CardAbilityCondition('fire_spell', basis='printed')
PROTOSS = CardAbilityCondition('protoss', basis='printed')
PROTO_CARDS = PoolQuery(factions_any=('protoss',))
PROTO_MINIONS = PoolQuery(kinds=(CardType.MINION,), factions_any=('protoss',))
DOUBLE_DAMAGE = HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2, layer=HealthLayer.TARGET, target_relation='self')
COLLECTIBLE_ROOTS = ()


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['schema'] != 1 or
            tuple(data['candidate_ids']) != CANDIDATES or tuple(data['collectible_leaf_ids']) != LEAVES or
            data['new_token_ids'] != [TOKEN] or data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[k] for k in ('cards','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Protoss domain lost its complete declared source or roles')
    rows = data['dependencies']
    if (tuple(row['record']['id'] for row in rows) != LEAVES+(TOKEN,) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows) or
            canonical_digest(data['enchantment_reference']['record']) != data['enchantment_reference']['record_sha256']):
        raise TargetValidationError('Protoss domain lost a complete original record')
    return data


def register_protoss_spell_domain(registry):
    data = load_batch(); prepared = []
    # Prepare every definition before registering even the first card/behavior.
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards:
            raise TargetValidationError('Protoss dependency would overwrite '+cid)
        fields = {}; cost = data['numeric_normalizations'].get(cid,{}).get('cost',raw['cost'])
        meta = metadata_from_record(raw)
        if asdict(meta) != row['metadata']:
            # JSON tuples are normalized only for comparison, never inferred.
            if json.loads(json.dumps(asdict(meta))) != row['metadata']:
                raise TargetValidationError('Protoss dependency changed complete printed metadata')
        if cid == TOKEN:
            if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],raw['tags'].get('CHARGE')) != ('MINION',3,3,4,False,1):
                raise TargetValidationError('Zealot requires its complete real 3-mana 3/4 Charge face')
            fields.update(attack=3,health=4,keywords=(Keyword.CHARGE,))
        else:
            if raw['type'] != 'SPELL' or raw['collectible'] is not True:
                raise TargetValidationError('Protoss spell dependency lost its printed collection role')
            fields['on_play'] = PREFIX+cid
            if cid == 'SW_462': fields['spell_school'] = SpellSchool.FIRE
            elif raw['tags'].get('PROTOSS') != 1 or row['spell_school'] is not None:
                raise TargetValidationError('Protoss spell lost its printed faction or school')
            if cid == 'SC_753':fields['targeting'] = TargetSpec()
            if cid == 'SC_760':fields['targeting'] = TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
            if cid == 'SC_757':fields.update(targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'),target_rule=PREFIX+'friendly_protoss')
        card = CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=cost,metadata=meta,**fields)
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Protoss dependency differs from existing pool metadata')
        prepared.append(card)

    def discount(c,amount,kinds=None,*,one=True,this_turn=False,ability=PROTOSS):
        spec = CostSpec(delta=-amount,ability=ability,**({'card_types':kinds} if kinds is not None else {}))
        return AddCostModifier(c.player_id,spec,uses_remaining=1 if one else None,source_id=c.source_id,
            expires_turn=c.state.turn if this_turn else None)

    def friendly_protoss(c):
        if c.target is None:return False
        meta = registry.card(c.target['card_id']).metadata
        if meta is None or meta.factions is None:raise UnknownCardFactError('Unknown target Protoss identity')
        return 'protoss' in meta.factions

    def photon_result(c):
        result = c.health_result
        return (InvokeHealthResult(PREFIX+'photon_reward',c.event),) if result.target_id == result.original_target_id and result.target_kind == CardType.MINION.value else ()

    def photon_reward(c):
        result = c.health_result
        killed = any(death.entity_id == result.original_target_id and death.cause is not None and
            death.cause.kind in ('damage','poison') and death.cause.result == result.payload() for death in c.state.death_history)
        return (discount(c,1,(CardType.MINION,),one=False),) if killed else ()

    def hallucinate(c):
        target = c.state.entities.get(c.target_id)
        if (target is None or target.zone != Zone.BOARD or target.kind != CardType.MINION or
                not target.active or target.health <= 0 or target.doomed):return ()
        return (CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c),on_summon=PREFIX+'hallucination_grant'),)

    bodies = {
        'SW_462':lambda c:(discount(c,2,(CardType.SPELL,),this_turn=True,ability=FIRE),),
        'SC_750':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(PROTO_CARDS),)*2),
            SummonByCard(c.player_id,(SummonEntryMaterial(TOKEN),),SummonCause.capture(c))),
        'SC_753':lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL,PREFIX+'photon_result'),),
        'SC_755':lambda c:(discount(c,2,this_turn=True),),
        'SC_757':hallucinate,
        'SC_759':lambda c:(GainArmor(c.player_id,6),discount(c,2,(CardType.SPELL,))),
        'SC_760':lambda c:(Damage(c.target_id,5,c.source_id,DamageKind.SPELL),
            GenerateFromPool(c.player_id,POOL,PoolQuery(kinds=(CardType.SPELL,),collectible=True,factions_any=('protoss',)),source_id=c.source_id)),
        'SC_761':lambda c:(DrawMatchingWithCostReduction(c.player_id,2 if c.spell_conditions.combo else 0,c.source_id,PROTO_MINIONS),),
        'photon_result':photon_result,'photon_reward':photon_reward,
        'hallucination_grant':lambda c:(GrantHealthRule(c.target_id,DOUBLE_DAMAGE,c.source_id),),
    }
    registry.register_target_rule(PREFIX+'friendly_protoss',friendly_protoss,visibility='player')
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))


def local_pool(registry,context):
    data = load_batch()
    for cid in CANDIDATES:
        card = registry.card(cid)
        if (card.kind != CardType.SPELL or card.metadata is None or card.metadata.collectible is not True or
                card.metadata.factions is None or 'protoss' not in card.metadata.factions or card.on_play != PREFIX+cid):
            raise TargetValidationError('Complete Protoss inventory lost an executable original member')
    return PoolDefinition(POOL,POLICY+'-'+BATCH_HASH[:16],context.target_id,context.mode,
        tuple(PoolMember(cid) for cid in data['candidate_ids']),complete=True)
