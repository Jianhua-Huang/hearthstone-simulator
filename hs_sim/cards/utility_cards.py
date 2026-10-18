"""Finite reviewed buffs, removals and summons over the public effect primitives."""
from hs_sim.engine.summon_quantities import card_summon

from dataclasses import dataclass, replace
import json
from pathlib import Path

from hs_sim.engine.effects import (Buff, Destroy, DestroyBatch, Draw, Freeze, GainArmor,
    GrantKeyword, InvokeBehavior, Overload, RandomDestroy, RandomReturnToHand, Silence,
    SpendResource, Summon, Transform)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.sacrifice import DestroyCapturedMinion,MinionReference
from hs_sim.engine.model import (CardDefinition, CardType, EndTurnSpec, HandActionSpec,
    Keyword, Resource, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest

from .health_cards import HealthStep, SCHOOLS, health_body
from .metadata import metadata_from_record


BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/utility-effects-v1.json'
BATCH_HASH = 'fc7649ad14b65ce1371bbd36035fa3c0b379cbf751c2e9e76ee1ced47ff003a7'
SCOPES = ('target','self','event_target','friendly','enemy','own_hero','enemy_weapon',
    'friendly_minions','other_friendly_minions','enemy_minions','all_minions',
    'all_board','adjacent_friendly_minions','friendly_hand_minions')


@dataclass(frozen=True)
class UtilityStep:
    operation: str
    scope: str = 'target'
    amount: int = 0
    attack: int = 0
    health: int = 0
    keyword: Keyword | None = None
    card_id: str | None = None
    count: int = 1
    temporary: bool = False
    tribes: tuple[str, ...] = ()
    keywords_all: tuple[Keyword, ...] = ()
    damaged: bool | None = None
    attack_min: int | None = None
    attack_max: int | None = None
    success: tuple['UtilityStep', ...] = ()
    failure: tuple['UtilityStep', ...] = ()

    def __post_init__(self):
        if self.operation not in ('buff','keyword','summon','destroy','destroy_batch',
            'destroy_location','transform','random_destroy','random_return','silence',
            'heal','damage','freeze','draw','armor','overload','spend_corpses') or self.scope not in SCOPES:
            raise ValueError('Unreviewed utility operation or recipient scope')
        for name in ('amount','attack','health','count'):
            if type(getattr(self,name)) is not int or getattr(self,name) < 0:
                raise ValueError('Reviewed utility quantities require nonnegative integers')
        if type(self.temporary) is not bool or self.damaged is not None and type(self.damaged) is not bool:
            raise ValueError('Utility predicates require exact boolean declarations')
        for value in (self.attack_min,self.attack_max):
            if value is not None and type(value) is not int:
                raise ValueError('Attack predicate requires an explicit integer')
        if self.operation == 'keyword':
            if type(self.keyword) is not Keyword:
                raise ValueError('Keyword grant requires a typed declared keyword')
        elif self.keyword is not None:
            raise ValueError('Only keyword operations declare a grant')
        if (self.operation in ('summon','transform')) != (type(self.card_id) is str and bool(self.card_id.strip())):
            raise ValueError('Summon/transform requires an explicit real definition ID')
        if any(type(values) is not tuple for values in (self.tribes,self.keywords_all,self.success,self.failure)):
            raise ValueError('Utility filters and branches must be immutable')
        if any(type(k) is not Keyword for k in self.keywords_all) or any(type(t) is not str or not t for t in self.tribes):
            raise ValueError('Utility filters require explicit typed values')
        if any(type(s) is not UtilityStep for s in (*self.success,*self.failure)):
            raise ValueError('Resource branches require reviewed utility steps')
        if self.operation != 'spend_corpses' and self.failure:
            raise ValueError('Only resource spending declares failure branches')
        if self.success and self.operation not in ('spend_corpses','destroy'):
            raise ValueError('Only resource spending and captured destruction declare success branches')
        if self.operation == 'destroy' and self.success and self.scope != 'target':
            raise ValueError('Destruction rewards require one original target')
        if self.operation != 'buff' and (self.attack or self.health or self.temporary):
            raise ValueError('Only buffs declare stats and expiry')
        if self.operation not in ('heal','damage','draw','armor','overload','spend_corpses') and self.amount:
            raise ValueError('This utility operation does not consume an amount')
        if self.operation != 'summon' and self.count != 1:
            raise ValueError('Only summons declare a count')
        if self.operation == 'summon' and self.scope not in ('friendly','enemy'):
            raise ValueError('Summon requires an explicit receiving side')
        if self.operation not in ('summon','transform') and self.card_id is not None:
            raise ValueError('Only summon/transform declares a card ID')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Utility card batch differs from its reviewed source pin')
    return data


def parse_step(raw):
    data = dict(raw)
    if 'keyword' in data: data['keyword'] = Keyword(data['keyword'])
    data['tribes'] = tuple(data.get('tribes', ()))
    data['keywords_all'] = tuple(Keyword(k) for k in data.get('keywords_all', ()))
    for name in ('success','failure'):
        data[name] = tuple(parse_step(s) for s in data.get(name, ()))
    return UtilityStep(**data)


def entities(context, step, registry):
    own = context.state.players[context.player_id]
    enemy = context.state.players[3-context.player_id]
    scope = step.scope
    if scope in ('target','event_target'): ids = () if context.target_id is None else (context.target_id,)
    elif scope == 'self': ids = (context.source_id,)
    elif scope == 'own_hero': ids = (own.hero_id,)
    elif scope == 'enemy_weapon': ids = () if enemy.weapon_id is None else (enemy.weapon_id,)
    elif scope == 'friendly_hand_minions': ids = tuple(own.hand)
    elif scope == 'adjacent_friendly_minions':
        if context.source_id not in own.board: ids = ()
        else:
            index=own.board.index(context.source_id)
            ids=tuple(own.board[i] for i in (index-1,index+1) if 0 <= i < len(own.board))
    else:
        players = (enemy,) if scope == 'enemy_minions' else (own,enemy) if scope in ('all_minions','all_board') else (own,)
        ids = tuple(e for player in players for e in player.board)
    result = []
    for eid in ids:
        entity = context.state.entities[eid]
        if scope in ('friendly_minions','other_friendly_minions','enemy_minions','all_minions',
                'all_board','adjacent_friendly_minions'):
            if not entity.active or entity.doomed:
                continue
            if entity.kind != CardType.MINION and not (scope == 'all_board' and entity.kind == CardType.LOCATION):
                continue
        if scope == 'friendly_hand_minions' and entity.kind != CardType.MINION:
            continue
        if scope == 'other_friendly_minions' and eid == context.source_id: continue
        if step.tribes and not has_any_tribe(registry,entity,step.tribes): continue
        if not set(step.keywords_all) <= entity.keywords: continue
        if step.damaged is not None and (entity.damage > 0) != step.damaged: continue
        if step.attack_min is not None and entity.attack < step.attack_min: continue
        if step.attack_max is not None and entity.attack > step.attack_max: continue
        result.append(eid)
    return tuple(result)


def step_body(context, step, registry, is_spell, success_id=None, failure_id=None):
    op = step.operation
    if op == 'summon':
        return tuple(card_summon(context,context.player_id if step.scope == 'friendly' else 3-context.player_id,
                            step.card_id) for _ in range(step.count))
    if op == 'draw': return (Draw(context.player_id,step.amount,context.source_id),)
    if op == 'armor': return (GainArmor(context.player_id,step.amount),)
    if op == 'overload': return (Overload(context.player_id,step.amount),)
    if op == 'spend_corpses':
        invoke = lambda name: () if name is None else (InvokeBehavior(name,context.source_id,
            context.player_id,context.target_id),)
        return (SpendResource(context.player_id,Resource.CORPSES,step.amount,
            on_success=invoke(success_id),on_failure=invoke(failure_id)),)
    ids = entities(context,step,registry)
    if op == 'destroy_batch': return (DestroyBatch(ids,context.source_id),)
    if op == 'random_destroy': return (RandomDestroy(ids,context.source_id),)
    if op == 'random_return': return (RandomReturnToHand(ids,context.source_id),)
    effects = []
    for eid in ids:
        if op == 'buff':
            expiry = context.state.turn if step.temporary else None
            entity=context.state.entities[eid]
            if step.scope == 'friendly_hand_minions':
                effects.append(BuffStoredCard(CardReference.capture(entity),step.attack,step.health,
                                              context.source_id,expiry))
            else: effects.append(Buff(eid,step.attack,step.health,context.source_id,expiry))
        elif op == 'keyword': effects.append(GrantKeyword(eid,step.keyword,context.source_id))
        elif op == 'destroy':
            if success_id is None:effects.append(Destroy(eid,context.source_id))
            else:
                victim=context.state.entities[eid]
                if victim.kind==CardType.MINION and victim.zone==Zone.BOARD and victim.active and victim.health>0 and not victim.doomed:
                    effects.append(DestroyCapturedMinion(MinionReference.capture(victim),context.source_id,
                        (InvokeBehavior(success_id,context.source_id,context.player_id,context.target_id),)))
        elif op == 'destroy_location': effects.append(DestroyLocation(eid,context.source_id))
        elif op == 'transform': effects.append(Transform(eid,step.card_id))
        elif op == 'silence': effects.append(Silence(eid))
        elif op == 'freeze': effects.append(Freeze(eid))
        elif op in ('damage','heal'):
            from dataclasses import replace as replace_context
            effects.extend(health_body(replace_context(context,target_id=eid),
                (HealthStep(op,'target',step.amount),),is_spell))
    return tuple(effects)


def compile_body(registry, raw_steps, is_spell, registered, trigger=None):
    identity=dict(steps=raw_steps,spell=is_spell,trigger=trigger)
    body_id='cards.utility.body.'+canonical_digest(identity)[:24]
    if body_id in registered: return body_id
    stage_ids=[]
    for index,raw in enumerate(raw_steps):
        spec=parse_step(raw)
        stage_id=body_id+f'.{index}'
        success=compile_body(registry,raw['success'],is_spell,registered) if raw.get('success') else None
        failure=compile_body(registry,raw['failure'],is_spell,registered) if raw.get('failure') else None
        registry.register_behavior(stage_id,lambda c,spec=spec,success=success,failure=failure:
            step_body(c,spec,registry,is_spell,success,failure))
        stage_ids.append(stage_id)
    def body(c,stages=tuple(stage_ids),trigger=trigger):
        if trigger == 'own_turn_start' and c.event.player_id != c.player_id: return ()
        if trigger == 'friendly_hero_attack' and c.event.source_id != c.state.players[c.player_id].hero_id: return ()
        if trigger == 'self_dealt_damage' and (c.event.source_id != c.source_id or c.event.amount <= 0): return ()
        target = c.event.target_id if trigger == 'self_dealt_damage' else c.target_id
        return tuple(InvokeBehavior(name,c.source_id,c.player_id,target,
            None if c.play is None else c.play.id) for name in stages)
    registry.register_behavior(body_id,body)
    registered.add(body_id)
    return body_id


def register_utility_cards(registry):
    registered=set()
    data=load_batch()
    for raw in data['reused_dependencies']:
        existing=registry.card(raw['id'])
        if (existing.attack,existing.health,existing.cost,existing.metadata.tribes) != (
                raw['attack'],raw['health'],raw['cost'],metadata_from_record(raw).tribes):
            raise TargetValidationError('Required existing dependency differs from current printed data')
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe']
        if canonical_digest(raw) != row['record_sha256']:
            raise TargetValidationError('Utility record differs from its source identity')
        kind=CardType(raw['type'].lower())
        if kind not in (CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION):
            raise TargetValidationError('Unreviewed utility root or dependency type')
        if recipe['root'] and raw['collectible'] is not True:
            raise TargetValidationError('Utility root requires its collectible source record')
        cost=recipe['cost']
        if type(cost) is not int or cost < 0 or cost != raw['cost'] and not (
                raw['id'] in ('TIME_218','hexfrog') and raw['cost'] is None and cost==0):
            raise TargetValidationError('Utility printed cost needs an explicit reviewed value')
        keywords=tuple(Keyword(k) for k in recipe['keywords'])
        kwargs={}
        trigger=recipe['trigger']
        if trigger not in (None,'own_turn_start','own_turn_end','friendly_hero_attack','self_dealt_damage'):
            raise TargetValidationError('Unreviewed utility trigger')
        for entry,steps in recipe['bodies'].items():
            if entry not in ('on_play','battlecry','combo','deathrattle','on_use','on_trigger') or not steps:
                raise TargetValidationError('Unreviewed or placeholder utility body')
            body=compile_body(registry,steps,kind==CardType.SPELL,registered,trigger if entry=='on_trigger' else None)
            if entry=='on_trigger':
                event={'own_turn_start':'turn_started','own_turn_end':'turn_ended',
                    'friendly_hero_attack':'attack_finished','self_dealt_damage':'damage_dealt'}[trigger]
                kwargs['triggers']=(TriggerSpec(event,body,EndTurnSpec() if trigger=='own_turn_end' else None),)
            else: kwargs[entry]=body
        target=recipe['targeting']
        if target is not None:
            target_kind=target['kind']
            if target_kind not in ('minion','character','location'):
                raise TargetValidationError('Unreviewed utility target type')
            kinds=((CardType.HERO,CardType.MINION) if target_kind=='character' else
                   (CardType.LOCATION,) if target_kind=='location' else (CardType.MINION,))
            kwargs['targeting']=TargetSpec(TargetMode.IF_AVAILABLE if kind==CardType.MINION else TargetMode.REQUIRED,
                zones=(Zone.HERO,Zone.BOARD) if target_kind=='character' else (Zone.BOARD,),
                kinds=kinds,relation=target['relation'])
            filters=dict(target['predicate'])
            if filters:
                predicate_id='cards.utility.target.'+canonical_digest(filters)[:24]
                if predicate_id not in registered:
                    for field in ('keywords_all','keywords_none'):
                        if field in filters: filters[field]=tuple(Keyword(k) for k in filters[field])
                    for field in ('current_tribes_any','printed_tribes_any'):
                        if field in filters: filters[field]=tuple(filters[field])
                    registry.register_target_predicate(TargetPredicateSpec(predicate_id,**filters))
                    registered.add(predicate_id)
                kwargs['target_rule']=predicate_id
        hand_actions=recipe['hand_actions']
        if any(value not in ('trade','prepare') for value in hand_actions):
            raise TargetValidationError('Unreviewed alternative hand/deck action')
        kwargs['hand_actions']=tuple(HandActionSpec(value,value,1) for value in hand_actions)
        school=raw['tags'].get('SPELL_SCHOOL')
        if school is not None and school not in SCHOOLS:
            raise TargetValidationError('Unreviewed utility school')
        definition=CardDefinition(raw['id'],raw['name'],kind,cost=cost,
            attack=recipe['attack'],health=recipe['health'],durability=recipe['durability'],
            keywords=keywords,spell_school=SCHOOLS.get(school),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
