"""Original Arcane damage-result, physical-card and transformation consumers."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.card_spell_repeats import DrawMatchingTurnSpellRepeat
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.cross_zone import MinionScope, TransformMinionFromPool, TransformMinionsInZones
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import ChoiceOption, Damage, DamageBatch, Draw, InvokeBehavior, RandomDamageBatch, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, ChooseBranch, ChooseOneSpec, CostSpec, DamageKind,
    Keyword, SecretSpec, SpellSchool, SummonStats, TargetMode, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CopyCard, CopyDeckSpellAtCurrentCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-physical-values-v1.json'
BATCH_HASH = 'a72e254cdd062659608dd4caf0eeb3f095ed4e275fc33bc8ab1a50e60517ba38'
LEAVES = ('AV_116','DED_517','DEEP_003','GDB_851','NEW1_007','RLK_804','SCH_235','TTN_485','UNG_024','WW_425')
GOO = 'DED_517t'
CHOICES = ('GDB_851a','GDB_851b','NEW1_007a','NEW1_007b')
DEPENDENCIES = (*LEAVES,GOO)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_physical_values.'
POOL = 'constructed.cards'
MINION = TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
ENEMY = replace(MINION,relation='enemy')
STARGAZING = PoolQuery(kinds=(CardType.SPELL,),spell_schools=(SpellSchool.ARCANE,),exclude_card_ids=('WW_425',))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(v['record']['id']for v in data['dependencies']) != DEPENDENCIES or
            tuple(v['record']['id']for v in data['choice_only']) != CHOICES or
            tuple(v['record']['id']for v in data['evidence_only']) != ('GDB_851e','TTN_485e1','WW_425e') or
            any(data[k]for k in ('cards','existing_dependencies','skipped','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            len(data['official_observations']) != 26 or data['raw_only_choice_ids'] != ['NEW1_007a','NEW1_007b'] or
            data['current_deck_copy_costs'] != [7,8,9,10] or data['stargazing_policy'] != 'same-turn-physical-hand-play-only' or
            not set(LEAVES) <= set(reference['candidate_ids']) or
            any(canonical_digest(v['record']) != v['record_sha256']
                for v in data['dependencies']+data['choice_only']+data['evidence_only'])):
        raise TargetValidationError('Past Arcane physical consumers changed their full original source or finite policies')
    return data


def register_past_arcane_physical_values(registry):
    data = load_batch()
    rows = {v['record']['id']:v['record']for v in data['dependencies']+data['choice_only']}
    secret = SecretSpec('UNG_024',('spell_cast_started',),PREFIX+'bind_condition',PREFIX+'bind')
    prepared = []
    for cid,raw in rows.items():
        if cid in registry.cards:
            raise TargetValidationError('Past Arcane physical consumers cannot overwrite an original identity: '+cid)
        choice = cid in CHOICES
        if cid == GOO:
            card = CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
                metadata=metadata_from_record(raw))
        else:
            if raw['type'] != 'SPELL' or raw['tags'].get('SPELL_SCHOOL') != 1:
                raise TargetValidationError('Past Arcane physical consumer changed its original spell face')
            fields = {}
            if cid in ('NEW1_007','GDB_851'):
                names = ('NEW1_007b','NEW1_007a')if cid == 'NEW1_007' else ('GDB_851a','GDB_851b')
                targeting = (MINION,None)if cid == 'NEW1_007' else (None,ENEMY)
                fields['choose_one'] = ChooseOneSpec(tuple(ChooseBranch(i,rows[i]['name'],PREFIX+i,t)
                    for i,t in zip(names,targeting)),ChooseBranch(cid+':combined','兼得',PREFIX+cid+':combined',
                        replace(MINION if cid == 'NEW1_007' else ENEMY,mode=TargetMode.IF_AVAILABLE)))
            elif cid == 'UNG_024':
                fields.update(secret=secret,keywords=(Keyword.SECRET,))
            elif not choice:
                fields['on_play'] = PREFIX+cid
                if cid == 'RLK_804': fields['targeting'] = MINION
                if cid == 'DED_517': fields['targeting'] = ENEMY
                if cid == 'DEEP_003': fields['targeting'] = TargetSpec()
            card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=0 if choice else raw['cost'],choice_only=choice,
                spell_school=SpellSchool.ARCANE,metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card)
        if not choice and cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Past Arcane physical consumer differs from original printed metadata: '+cid)
        prepared.append(card)

    def health(c):
        result = c.health_result
        if result is None or (result.source_id,result.source_controller) != (c.source_id,c.player_id):
            raise ResolutionError('Arcane consumer requires its original committed health result')
        return result
    def overflow(c):
        result = health(c); amount = max(0,result.damage_dealt-max(0,result.health_before))
        if not amount: return ()
        return (SummonByCard(c.player_id,(SummonEntryMaterial(GOO,SummonStats(attack=amount,health=amount)),),
            SummonCause.capture(c)),)
    def shimmer(c):
        amount = health(c).damage_dealt
        return (SummonFromPool(c.player_id,POOL,
            PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=amount,max_cost=amount),
            source_id=c.source_id,cause=SummonCause.capture(c)),)
    def arrows(c):
        callback = PREFIX+'arrows_draw'if c.state.players[c.player_id].max_mana >= 6 else None
        return (Damage(c.target_id,2,c.source_id,DamageKind.SPELL,callback),)
    def starfall_aoe(c):
        return (DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)for i in minions(c,registry,3-c.player_id))),)
    def starfall_both(c):
        return (*((Damage(c.target_id,5,c.source_id,DamageKind.SPELL),)if c.target_id is not None else ()),
            InvokeBehavior(PREFIX+'NEW1_007a',c.source_id,c.player_id))
    def rays(c):
        return (RandomDamageBatch(minions(c,registry,3-c.player_id),2,2,c.source_id,DamageKind.SPELL),)
    def ray_both(c):
        return (*rays(c),*((MakeDormant(c.target_id,2,c.source_id),)if c.target_id is not None else ()))
    def missile(c):
        options = tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])),sort_keys=True),
            'Original enemy minion')for i in minions(c,registry,3-c.player_id))
        return (RequestChoice(c.player_id,options,c.source_id,min_count=0,max_count=0,sample_size=1,
            on_select=PREFIX+'missile_target'),)if options else ()
    def missile_target(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
            raise ResolutionError('Devolving Missiles lost its original single sampled minion')
        ref = MinionReference(**json.loads(c.choice.choice.options[0].id))
        return (TransformMinionFromPool(ref,POOL,-1,cost_basis='local',source_id=c.source_id),)
    def enemy_cast(c):
        if c.event is None or c.event.kind != 'spell_cast_started': return None
        row = cast_record(c.state,dict(c.event.data)['cast_id'])
        if (row.source_id,row.player_id) != (c.event.source_id,c.event.player_id):
            raise ResolutionError('Mana Bind lost the original opponent CAST start')
        if row.player_id == c.player_id: return None
        source = c.state.entities[row.source_id]
        if source.card_id != row.card_id or source.kind != CardType.SPELL:
            raise ResolutionError('Mana Bind lost the original spell face')
        return source
    def bind(c):
        source = enemy_cast(c)
        return (CopyCard(CapturedCardCopyMaterial.capture(c.state,source),c.player_id,mode='base',
            source_id=c.source_id,cost=CostSpec(set_to=0)),)if source is not None else ()

    bodies = {
        'AV_116':lambda c:tuple(CopyDeckSpellAtCurrentCost(c.player_id,n,c.source_id)for n in (7,8,9,10)),
        'DED_517':lambda c:(Damage(c.target_id,8,c.source_id,DamageKind.SPELL,PREFIX+'overflow'),),
        'overflow':overflow,
        'DEEP_003':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL,PREFIX+'shimmer'),),
        'shimmer':shimmer,'RLK_804':arrows,
        'arrows_draw':lambda c:(Draw(c.player_id,health(c).damage_dealt,c.source_id),),
        'NEW1_007a':starfall_aoe,
        'NEW1_007b':lambda c:(Damage(c.target_id,5,c.source_id,DamageKind.SPELL),),
        'NEW1_007:combined':starfall_both,
        'GDB_851a':rays,'GDB_851b':lambda c:(MakeDormant(c.target_id,2,c.source_id),),
        'GDB_851:combined':ray_both,
        'SCH_235':lambda c:tuple(InvokeBehavior(PREFIX+'missile',c.source_id,c.player_id)for _ in range(3)),
        'missile':missile,'missile_target':missile_target,
        'TTN_485':lambda c:(TransformMinionsInZones(c.player_id,POOL,3,scope=MinionScope(zones=(Zone.HAND,)),
            cost_basis='local',retain_cost_basis='local',source_id=c.source_id),),
        'bind':bind,
        'WW_425':lambda c:(DrawMatchingTurnSpellRepeat(c.player_id,STARGAZING,c.source_id,SpellSchool.ARCANE),),
    }
    registry.register_secret_condition(PREFIX+'bind_condition',lambda c:enemy_cast(c) is not None)
    for key,body in bodies.items(): registry.register_behavior(PREFIX+key,body)
    for card in prepared:
        registry.register_card(card)
        if not card.choice_only and card.id not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
