"""Reviewed independent Deathrattles using original snapshots and zone effects."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from hs_sim.engine.effects import AddToHand,Buff,ChoiceOption,CopyMinion,Damage,DamageBatch,Draw,EquipWeapon,InvokeBehavior,ModifyWeapon,RandomDamage,RequestChoice,SplitDamage
from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.imbue import Imbue
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,DamageKind,Keyword
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.resurrection_summons import primary_resurrected_body
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery,Resurrect
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.spell_sequences import DrawMatchingWithCostReduction
from hs_sim.engine.zones import AddToDeck,CardReference,DestroyDeckBatch,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .conditional_cards import load_batch as conditional_batch
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/death-followup-effects-v1.json'
BATCH_HASH='409c9eddb7740d9856a29ee766b0161803e988b6892e00d79d2385c99d59b508'
PREFIX='cards.death_followup.'
SCRIPTS={'CORE_AT_123':'chillmaw','CORE_BT_201':'porcupine','CORE_DRG_107':'spellwing',
    'CORE_EX1_383':'tirion','CORE_WC_701':'rattler','EDR_227':'bear','EDR_890':'whelp','EDR_978':'meadow',
    'CORE_YOD_026':'servant','CAP_004':'operator','EDR_110':'spore',
    'EDR_495':'twisted','END_002':'blightspawn','EDR_572':'dreadwing',
    'TLC_621':'watcher','TLC_244':'explorer','EDR_891':'felhunter','EDR_892':'felbat'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Death followup cards differ from complete reviewed source pin')
    return data


def register_death_followup_cards(registry):
    def invoke(c,name):return (InvokeBehavior(PREFIX+name,c.source_id,c.player_id),)

    def chillmaw(c):
        if not any(c.state.entities[eid].kind==CardType.MINION and
            has_any_tribe(registry,c.state.entities[eid],('dragon',)) for eid in c.state.players[c.player_id].hand):
            return ()
        return (DamageBatch(tuple(Damage(eid,3,c.source_id,DamageKind.MINION_ABILITY)
            for pid in (1,2) for eid in minions(c,registry,pid))),)

    def porcupine(c):
        amount=c.death.attack if c.death is not None else c.source.attack
        return (SplitDamage(3-c.player_id,amount,c.source_id,kind=DamageKind.MINION_ABILITY),)

    def rightmost(c):
        hand=c.state.players[c.player_id].hand
        if not hand:return ()
        return (ModifyStoredCost(CardReference.capture(c.state.entities[hand[-1]]),CostSpec(delta=-2),c.source_id),)

    def servant(c):
        amount = c.death.attack if c.death is not None else c.source.attack
        ids = minions(c, registry, c.player_id)
        if not ids: return ()
        if len(ids) == 1: return (Buff(ids[0], amount, source_id=c.source_id),)
        options = tuple(ChoiceOption(json.dumps(dict(target=asdict(MinionReference.capture(c.state.entities[eid])),
            attack=amount), sort_keys=True, separators=(',', ':')), 'Random friendly minion', entity_id=eid) for eid in ids)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
                              sample_size=1, on_select=PREFIX+'servant_selected'),)

    def servant_selected(c):
        result = c.choice
        if result is None or result.selected_ids or len(result.choice.options) != 1:
            raise TargetValidationError('Servant lost its one automatic sampled target')
        item = result.choice.options[0]; material = json.loads(item.id)
        if set(material) != {'target', 'attack'} or type(material['attack']) is not int or material['attack'] < 0:
            raise TargetValidationError('Servant lost its frozen attack operand')
        ref = MinionReference(**material['target']); ref.__post_init__()
        if item.entity_id != ref.entity_id or result.choice.player_id != c.player_id:
            raise TargetValidationError('Servant target identity differs from the original offer')
        if (ref.entity_id not in minions(c, registry, c.player_id) or
                MinionReference.capture(c.state.entities[ref.entity_id]) != ref): return ()
        return (Buff(ref.entity_id, material['attack'], source_id=c.source_id),)

    def blightspawn(c):
        weapon_id=c.state.players[c.player_id].weapon_id
        return (EquipWeapon(c.player_id,'CS2_082'),)if weapon_id is None else(
            ModifyWeapon(weapon_id,attack=2,source_id=c.source_id),)

    def resurrect_copy(c,high):
        query=PoolQuery(min_cost=5,exclude_source=True)if high else PoolQuery(max_cost=4)
        return (Resurrect(c.player_id,query=DeathQuery(cards=query,has_deathrattle=True,deathrattle_basis='printed'),
            source_id=c.source_id,cause=SummonCause.capture(c),on_summon=PREFIX+'copy_resurrected_primary'),)

    bodies={
        'chillmaw':lambda c:invoke(c,'chillmaw_now'),'chillmaw_now':chillmaw,
        'porcupine':porcupine,
        'spellwing':lambda c:(AddToHand(c.player_id,'EX1_277',c.source_id),),
        'tirion':lambda c:(EquipWeapon(c.player_id,'EX1_383t'),),
        'rattler':lambda c:invoke(c,'rattler_now'),
        'rattler_now':lambda c:(DamageBatch(tuple(Damage(eid,1,c.source_id,DamageKind.MINION_ABILITY)
            for eid in minions(c,registry,3-c.player_id))),),
        'bear':lambda c:(Imbue(c.player_id,c.source_id),),
        'whelp':lambda c:invoke(c,'whelp_now'),'whelp_now':rightmost,
        'servant':servant,'servant_selected':servant_selected,
        'operator':lambda c:(Draw(3-c.player_id,2,c.source_id),),
        'spore':lambda c:invoke(c,'spore_now'),
        'spore_now':lambda c:(RandomDamage(minions(c,registry,3-c.player_id),1,c.source_id,DamageKind.MINION_ABILITY),),
        'twisted':lambda c:tuple(RandomBuffStoredMinion(pid,attack=-2,source_id=c.source_id)
                                 for pid in (c.player_id,3-c.player_id)),
        'blightspawn':lambda c:invoke(c,'blightspawn_now'),'blightspawn_now':blightspawn,
        'dreadwing':lambda c:tuple(DrawMatchingWithCostReduction(c.player_id,1,c.source_id,
            PoolQuery(kinds=(CardType.MINION,),tribes_any=('dragon',)))for _ in range(2)),
        'watcher':lambda c:invoke(c,'watcher_now'),
        'watcher_now':lambda c:(DestroyDeckBatch(tuple(CardReference.capture(c.state.entities[eid])
            for eid in c.state.players[c.player_id].deck[:3]),c.source_id),),
        'explorer':lambda c:(RandomBuffStoredMinion(3-c.player_id,cost=CostSpec(delta=-2),source_id=c.source_id),),
        'felhunter':lambda c:resurrect_copy(c,False),'felbat':lambda c:resurrect_copy(c,True),
        'copy_resurrected_primary':lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),)
            if primary_resurrected_body(c)else(),
        'meadow':lambda c:(AddToDeck(c.player_id,'EDR_978',position='bottom',source_id=c.source_id,
            cost=CostSpec(set_to=1)),),
    }
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    data=load_batch();prior={row['record']['id']:row['record'] for row in conditional_batch()['cards']}
    for row in data['existing_dependencies']:
        raw=row['record'];card=registry.card(raw['id'])
        if canonical_digest(raw)!=row['record_sha256']:
            raise TargetValidationError('Existing death dependency lost its complete source pin')
        if raw['id']=='EX1_277':
            if (prior.get(raw['id'])!=raw or card.kind!=CardType.SPELL or card.on_play is None
                    or card.cost!=raw['cost'] or card.spell_school!=SCHOOLS[raw['tags']['SPELL_SCHOOL']]):
                raise TargetValidationError('Existing dependency lost its complete native spell face')
        elif raw['id']=='CS2_082':
            if (raw['dbf_id']!=485 or card.kind!=CardType.WEAPON or card.on_play is not None
                    or(card.cost,card.attack,card.durability)!=(raw['cost'],raw['attack'],raw['health'])):
                raise TargetValidationError('Existing Dagger differs from the reviewed original weapon')
        else:raise TargetValidationError('Unreviewed existing death dependency')
    for link in data['dependency_links']:
        root=next(row['record'] for row in data['cards'] if row['record']['id']==link['source_id'])
        dep=next(row['record'] for row in (*data['cards'],*data['existing_dependencies']) if row['record']['id']==link['card_id'])
        if root['tags']['COLLECTION_RELATED_CARD_DATABASE_ID']!=dep['dbf_id'] or dep['dbf_id']!=link['dbf_id']:
            raise TargetValidationError('Deathrattle dependency differs from original DBF reference')
    for link in data['gallery_dependency_links']:
        root=next(row['record']for row in data['cards']if row['record']['id']==link['source_id'])
        dep=next(row['record']for row in (*data['cards'],*data['existing_dependencies'])if row['record']['id']==link['card_id'])
        gallery=link['source_gallery_record']
        if (canonical_digest(gallery)!=link['source_gallery_record_sha256']or gallery['id']!=root['dbf_id']
                or link['dbf_id']!=dep['dbf_id']or dep['dbf_id']not in gallery['child_ids']):
            raise TargetValidationError('Deathrattle dependency differs from the complete official gallery link')
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];kind=CardType(raw['type'].lower())
        if (canonical_digest(raw)!=row['record_sha256'] or raw['collectible']!=recipe['collectible']
                or (raw['cost'],raw['attack'],raw['health'])!=(recipe['cost'],recipe['attack'],recipe['source_health'])):
            raise TargetValidationError('Death followup lost its reviewed complete face')
        kwargs={}
        if kind==CardType.MINION:
            if SCRIPTS.get(raw['id'])!=recipe['script']:raise TargetValidationError('Unreviewed death body')
            kwargs.update(health=raw['health'],deathrattle=PREFIX+recipe['script'])
            if raw['id']=='CAP_004':kwargs['disguised']=raw['tags']['DISGUISED']==1
        elif kind==CardType.WEAPON and raw['id']in('EX1_383t','CS2_082_H1'):kwargs['durability']=raw['health']
        else:raise TargetValidationError('Unsupported death dependency type')
        card=CardDefinition(raw['id'],raw['name'],kind,cost=recipe['cost'],attack=recipe['attack'],
            keywords=tuple(Keyword(value) for value in recipe['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
