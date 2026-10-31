"""Original past Arcane secrets, board copies and ordinary damage consumers."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope, TransformCapturedMinion
from hs_sim.engine.effects import CopyMinion, Damage, InvokeBehavior, RandomDamage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import attack_live
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, DamageKind, Keyword,
    SecretSpec, SpellSchool, SummonStats, TargetSpec, Zone)
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.random_split_damage import RandomSplitDamage, SplitDamageScope
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import death_record
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .core_secret_cards import event_play
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-secrets-copy-damage-v1.json'
BATCH_HASH = '4b434163fd9057da8f80d0ed1cfa417ad6a2c3cfd115d37743c5bfcd33d4c30c'
LEAVES = DEPENDENCIES = ('BAR_541','BT_003','CFM_620','DRG_106','FP1_018','GVG_005',
    'JAM_002','MIS_107','SCH_352','TOY_877','TRL_400')
SECRETS = ('BT_003','CFM_620','FP1_018','TRL_400')
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_secrets_copy_damage.'
POOL = 'constructed.cards'
SPELLS = PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current')
FOURS = PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=4,max_cost=4)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(v['record']['id'] for v in data['dependencies']) != LEAVES or
            tuple(v['record']['id'] for v in data['existing_dependencies']) != ('CORE_BAR_541','CS2_tk1') or
            tuple(data['secret_source_ids']) != SECRETS or
            data['existing_body_aliases'] != {'BAR_541':'CORE_BAR_541'} or
            data['star_printed_base_hits'] != [5,4,3,2,1] or
            data['malfunction_printed_budgets'] != {'with_minion':3,'without_minion':6} or
            any(data[k] for k in ('cards','evidence_only','skipped','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            len(data['official_observations']) != 26 or not set(LEAVES) <= set(reference['candidate_ids'])):
        raise TargetValidationError('Past Arcane consumers require their full original records and reviewed contracts')
    if any(canonical_digest(v['record']) != v['record_sha256']
            for v in data['dependencies']+data['existing_dependencies']):
        raise TargetValidationError('Past Arcane consumer original row changed')
    return data


def register_past_arcane_secrets_copy_damage(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Past Arcane consumer changed a full native dependency: '+cid)

    def finished_enemy_spell(c):
        if c.event is None or c.event.kind != 'spell_cast_finished': return False
        row = cast_record(c.state,dict(c.event.data)['cast_id'])
        if (row.source_id,row.player_id) != (c.event.source_id,c.event.player_id) or not row.completed:
            raise ResolutionError('Netherwind Portal lost the actual completed spell cast')
        return row.player_id != c.player_id and row.payload_started and row.failure is None and not row.interrupted

    def played_enemy_minion(c):
        row = event_play(c)
        if row is None or row.player_id == c.player_id or row.kind != CardType.MINION or row.countered:
            return None
        target = c.state.entities.get(row.source_id)
        if (row.minion_result != 'summoned' or target is None or target.zone != Zone.BOARD or
                target.kind != CardType.MINION or target.controller == c.player_id or not target.active or
                target.doomed or target.health <= 0): return None
        return MinionReference.capture(target)

    def friendly_death(c):
        if c.event is None or c.event.kind != 'minion_died': return None
        fields = dict(c.event.data); row = death_record(c.state,fields['death_id'])
        if (row.entity_id,row.controller,row.batch,row.turn) != (
                c.event.source_id,c.event.player_id,fields['batch'],c.state.turn):
            raise ResolutionError('Duplicate lost its original committed minion death')
        return row if row.controller == c.player_id and row.zone == Zone.BOARD else None

    def attacked_friendly_minion(c):
        if not attack_live(c.state,c.window): return False
        attacker = c.state.entities[c.window.source_id]; target = c.state.entities[c.window.target_id]
        return attacker.controller != c.player_id and target.controller == c.player_id and target.kind == CardType.MINION

    conditions = {'BT_003':finished_enemy_spell,'CFM_620':lambda c:played_enemy_minion(c) is not None,
        'FP1_018':lambda c:friendly_death(c) is not None,'TRL_400':attacked_friendly_minion}
    specs = {cid:SecretSpec(cid,(event,),PREFIX+cid,PREFIX+cid,requires_board_space=space)
        for cid,event,space in (('BT_003','spell_cast_finished',True),('CFM_620','card_played',False),
            ('FP1_018','minion_died',False),('TRL_400','attack_declared',True))}

    prepared = []
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards: raise TargetValidationError('Past Arcane consumers cannot overwrite a native identity: '+cid)
        if raw['type'] != 'SPELL' or raw['tags'].get('SPELL_SCHOOL') != 1 or (cid in SECRETS) != (raw['tags'].get('SECRET') == 1):
            raise TargetValidationError('Past Arcane consumer changed its original spell or Secret face')
        if cid == 'BAR_541':
            card = replace(registry.card('CORE_BAR_541'),id=cid,name=raw['name'],cost=raw['cost'],metadata=metadata_from_record(raw))
        else:
            card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.ARCANE,
                secret=specs.get(cid),keywords=(Keyword.SECRET,) if cid in SECRETS else (),
                on_play=None if cid in SECRETS else PREFIX+cid,
                targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)) if cid == 'DRG_106' else None,
                metadata=metadata_from_record(raw))
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Past Arcane consumer contradicts complete original metadata: '+cid)
        prepared.append(card)

    def portal(c):
        return (GenerateFromPool(c.player_id,POOL,FOURS,source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),)
    def polymorph(c):
        target = played_enemy_minion(c)
        return () if target is None else (TransformCapturedMinion(target,'CS2_tk1',c.source_id),)
    def duplicate(c):
        row = friendly_death(c)
        return () if row is None else (CopyCard(row,c.player_id,mode='base',source_id=c.source_id),)*2
    def breath(c):
        holding = any(has_any_tribe(registry,c.state.entities[i],('dragon',)) for i in c.state.players[c.player_id].hand)
        return (Damage(c.target_id,2,c.source_id,DamageKind.SPELL),
            *((DiscoverFromPool(c.player_id,POOL,SPELLS,source_id=c.source_id),) if holding else ()))
    def copies(c,small=False):
        return tuple(CopyCard(MinionReference.capture(c.state.entities[i]),c.player_id,mode='base',source_id=c.source_id,
            stats=SummonStats(attack=1,health=1) if small else None,cost=CostSpec(set_to=1) if small else None)
            for i in minions(c,registry,c.player_id))
    def malfunction(c):
        if c.cast is None or c.cast.source_id != c.source_id: raise ResolutionError('Malfunction requires its actual current spell cast')
        amount = 3 if any(c.state.entities[i].kind == CardType.MINION for i in c.state.players[c.player_id].deck) else 6
        return (RandomSplitDamage(c.player_id,c.cast.id,c.source_id,amount,scope=SplitDamageScope(kinds=(CardType.MINION,))),)

    bodies = {'BT_003':portal,'CFM_620':polymorph,'FP1_018':duplicate,
        'TRL_400':lambda c:(CopyMinion(c.window.attack_target_presence,c.player_id,cause=SummonCause.capture(c)),),
        'DRG_106':breath,'GVG_005':copies,'SCH_352':lambda c:copies(c,True),'MIS_107':malfunction,
        'TOY_877':lambda c:(BuffMinionsInZones(c.player_id,2,3,
            MinionScope(zones=(Zone.HAND,Zone.DECK,Zone.BOARD)),c.source_id),),
        'JAM_002':lambda c:tuple(InvokeBehavior(PREFIX+'star_'+str(amount),c.source_id,c.player_id)for amount in range(5,0,-1))}
    for amount in range(5,0,-1):
        bodies['star_'+str(amount)] = lambda c,amount=amount:(RandomDamage(minions(c,registry,3-c.player_id),amount,c.source_id,DamageKind.SPELL),)
    for cid,condition in conditions.items(): registry.register_secret_condition(PREFIX+cid,condition)
    for cid,body in bodies.items(): registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
