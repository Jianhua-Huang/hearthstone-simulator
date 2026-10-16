"""Reviewed conditional bodies, explicit choices and complete named generation."""
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.summon_quantities import card_summon

from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, CopyMinion, Damage,
    Draw, FillBoardWithCopies, GainArmor, GrantDeathrattle, GrantKeyword, Heal, InvokeBehavior, ModifyWeapon,
    RefreshMana, RequestChoice, SetStats, Summon)
from hs_sim.engine.equipment import equipped_weapon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, ChooseBranch, ChooseOneSpec,
    DamageKind, EndTurnSpec, HealingKind, Keyword, SpellSchool, TargetMode, TargetSpec,
    TriggerSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import RandomSplitDamage
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import AddToDeck, ChooseFromZone
from hs_sim.targets import TargetValidationError, canonical_digest

from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .utility_cards import compile_body

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/conditional-effects-v1.json'
BATCH_HASH='2eaf231d7ce0f76f0bd50e9ff8f95d954d2889275a0eb4d5b9c42bdabeaf3a26'
PREFIX='cards.conditions.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Conditional batch differs from its reviewed source pin')
    return data


def live_target(c):
    e=c.state.entities.get(c.target_id)
    return e if e is not None and e.zone==Zone.BOARD and e.kind==CardType.MINION and e.active and not e.doomed else None


def named_hand(c,cid,count=1,opponent=False):
    return tuple(AddToHand(3-c.player_id if opponent else c.player_id,cid,c.source_id) for _ in range(count))


def invoke(c,name):
    return InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,
                          None if c.play is None else c.play.id)


def poison(c,r):
    weapon=equipped_weapon(c.state,c.state.players[c.player_id])
    return () if weapon is None else (ModifyWeapon(weapon.id,attack=2,source_id=c.source_id),)


def beast_axe(c,r):
    if any(e.active and not e.doomed and e.kind==CardType.MINION and has_any_tribe(r,e,('beast',))
           for eid in c.state.players[c.player_id].board for e in (c.state.entities[eid],)):
        return (ModifyWeapon(c.source_id,durability=1,source_id=c.source_id),)
    return ()


def shadow_in_hand(c,r):
    if any(e.kind==CardType.SPELL and r.card(e.card_id).spell_school==SpellSchool.SHADOW
           for eid in c.state.players[c.player_id].hand for e in (c.state.entities[eid],)):
        return (Buff(c.source_id,1,1,c.source_id),)
    return ()


def dragon_refresh(c,r):
    if any(e.kind==CardType.MINION and has_any_tribe(r,e,('dragon',))
           for eid in c.state.players[c.player_id].hand for e in (c.state.entities[eid],)):
        return (RefreshMana(c.player_id,2),)
    return ()


def weapon_damage(c,r):
    return () if equipped_weapon(c.state,c.state.players[c.player_id]) is None or c.target_id is None else (
        Damage(c.target_id,2,c.source_id),)


def reborn_or_copy(c,r):
    e=live_target(c)
    if e is None:return ()
    return (CopyMinion(e.id,c.player_id),) if Keyword.REBORN in e.keywords else (
        GrantKeyword(e.id,Keyword.REBORN,c.source_id),)


def keyword_choice(c,r,raptor=False):
    if raptor:
        options=(ChoiceOption('attack','+3攻击力',(Buff(c.source_id,attack=3,source_id=c.source_id),)),
            ChoiceOption('shield','圣盾',(GrantKeyword(c.source_id,Keyword.DIVINE_SHIELD,c.source_id),)),
            ChoiceOption('plants','亡语：召唤两个植物',(
                GrantDeathrattle(c.source_id,PREFIX+'plants',c.source_id),)))
    else:
        options=(ChoiceOption('taunt','嘲讽',(GrantKeyword(c.source_id,Keyword.TAUNT,c.source_id),)),
            ChoiceOption('poisonous','剧毒',(GrantKeyword(c.source_id,Keyword.POISONOUS,c.source_id),)),
            ChoiceOption('stats','+1/+1',(Buff(c.source_id,1,1,c.source_id),)))
    return (RequestChoice(c.player_id,options,c.source_id,prompt='选择一项效果'),)


def arcane_missiles(c,r):
    if c.cast is None or c.cast.source_id!=c.source_id:
        raise ResolutionError('Arcane Missiles requires its real spell cast record')
    return (RandomSplitDamage(c.player_id,c.cast.id,c.source_id,3),)


def spider(c,amount,next_card=None):
    return (Buff(c.state.players[c.player_id].hero_id,attack=amount,source_id=c.source_id,
                 expires_turn=c.state.turn),GainArmor(c.player_id,amount),
            *(() if next_card is None else named_hand(c,next_card)))


SCRIPTS={
    'poison':poison,
    'tracking':lambda c,r:(ChooseFromZone(c.player_id,c.player_id,Zone.DECK,
        operation='take',distinct='entity',source_id=c.source_id,prompt='从牌库中发现一张牌'),),
    'bananas':lambda c,r:named_hand(c,'EX1_014t',2,True),
    'banana_buff':lambda c,r:(Buff(c.target_id,1,1,c.source_id),),
    'hand_health':lambda c,r:(Buff(c.source_id,health=len(c.state.players[c.player_id].hand),source_id=c.source_id),),
    'flame_elemental':lambda c,r:named_hand(c,'UNG_809t1'),
    'combo_buff':lambda c,r:() if c.target_id is None else (Buff(c.target_id,attack=4,source_id=c.source_id),),
    'beast_axe':beast_axe,
    'quick_shot':lambda c,r:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),invoke(c,'empty_hand_draw')),
    'empty_hand_draw':lambda c,r:() if c.state.players[c.player_id].hand else (Draw(c.player_id,1,c.source_id),),
    'copy_self_twice':lambda c,r:(CopyMinion(c.source_id,c.player_id),CopyMinion(c.source_id,c.player_id)),
    'shadow_in_hand':shadow_in_hand,
    'first_flame':lambda c,r:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),*named_hand(c,'SW_108t')),
    'second_flame':lambda c,r:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
    'unused_mana_draw':lambda c,r:() if c.state.players[c.player_id].mana<=0 else (Draw(c.player_id,1,c.source_id),),
    'weapon_damage':weapon_damage,
    'reborn_or_copy':reborn_or_copy,
    'bat_mask':lambda c,r:(SetStats(c.target_id,1,1,c.source_id),FillBoardWithCopies(c.target_id,c.player_id)),
    'devilsaur_mask':lambda c,r:(SetStats(c.target_id,8,8,c.source_id),GrantKeyword(c.target_id,Keyword.CHARGE,c.source_id)),
    'panther_mask':lambda c,r:(SetStats(c.target_id,5,4,c.source_id),GrantKeyword(c.target_id,Keyword.STEALTH,c.source_id),Draw(c.player_id,2,c.source_id)),
    'stegodon_choice':keyword_choice,
    'raptor_choice':lambda c,r:keyword_choice(c,r,True),
    'plants':lambda c,r:(card_summon(c,c.player_id,'UNG_999t2t1'),card_summon(c,c.player_id,'UNG_999t2t1')),
    'raptor_deck':lambda c,r:shuffled(c,(AddToDeck(c.player_id,'UNG_920t2',source_id=c.source_id) for _ in range(10))),
    'draw_one':lambda c,r:(Draw(c.player_id,1,c.source_id),),
    'missile_hand':lambda c,r:named_hand(c,'EX1_277',3),
    'arcane_missiles':arcane_missiles,
    'spider_bite':lambda c,r:spider(c,1,'JAIL_436t'),
    'spider_meal':lambda c,r:spider(c,2,'JAIL_436t2'),
    'spider_feast':lambda c,r:spider(c,4),
    'detective_gift':lambda c,r:named_hand(c,'JAIL_447t'),
    'detective_suit':lambda c,r:(Buff(c.target_id,4,4,c.source_id),GrantKeyword(c.target_id,Keyword.RUSH,c.source_id)),
    'coin_gift':lambda c,r:named_hand(c,'GAME_005'),
    'light_embrace':lambda c,r:(Heal(c.target_id,4,c.source_id,HealingKind.SPELL),*named_hand(c,'JAIL_941t')),
    'dark_embrace':lambda c,r:(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),),
    'dragon_refresh':dragon_refresh,
}


def target_spec(raw,kind):
    if raw is None:return None
    if set(raw)!= {'kind','relation'} or raw['kind'] not in ('minion','character'):
        raise TargetValidationError('Unreviewed conditional target declaration')
    character=raw['kind']=='character'
    return TargetSpec(TargetMode.IF_AVAILABLE if kind==CardType.MINION else TargetMode.REQUIRED,
        zones=(Zone.HERO,Zone.BOARD) if character else (Zone.BOARD,),
        kinds=(CardType.HERO,CardType.MINION) if character else (CardType.MINION,),relation=raw['relation'])


def register_conditional_cards(registry):
    registered=set()
    for name,handler in SCRIPTS.items():
        registry.register_behavior(PREFIX+name,lambda c,handler=handler:handler(c,registry))
    def weapon_target(c):
        own=next(p for p in c.observation['players'] if p['id']==c.player_id)
        return own['weapon'] is not None
    registry.register_target_rule(PREFIX+'weapon_target',weapon_target,visibility='player')
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe']
        if canonical_digest(raw)!=row['record_sha256']:
            raise TargetValidationError('Conditional record differs from its full source identity')
        kind=CardType(raw['type'].lower());cost=raw['cost']
        if type(cost) is not int or cost<0:
            raise TargetValidationError('Conditional printed cost must be explicit')
        kwargs={}
        script=recipe['script']
        if script is not None:
            if script not in SCRIPTS:raise TargetValidationError('Unknown conditional card body')
            entry=recipe['entry']
            if entry=='on_trigger' and recipe.get('trigger')=='own_turn_end':
                kwargs['triggers']=(TriggerSpec('turn_ended',PREFIX+script,EndTurnSpec()),)
            elif entry in ('on_play','battlecry','deathrattle'):
                kwargs[entry]=PREFIX+script
            else:raise TargetValidationError('Unreviewed conditional body entry')
        kwargs['targeting']=target_spec(recipe['targeting'],kind)
        if recipe.get('target_condition'):
            kwargs['target_condition']=recipe['target_condition']
        if recipe.get('weapon_target'):
            kwargs['target_rule']=PREFIX+'weapon_target'
        if recipe.get('requires_weapon'):
            kwargs['requires_weapon']=True
        choices=recipe['choices']
        if choices is not None:
            if script is not None or len(choices)!=3:raise TargetValidationError('Choose One requires two branches and their real combined body')
            branches=tuple(ChooseBranch(b['id'],b['label'],
                compile_body(registry,b['steps'],kind==CardType.SPELL,registered),
                target_spec(b['targeting'],kind)) for b in choices)
            kwargs['choose_one']=ChooseOneSpec(branches[:2],branches[2])
        school=raw['tags'].get('SPELL_SCHOOL')
        if school is not None and school not in SCHOOLS:raise TargetValidationError('Unreviewed conditional spell school')
        definition=CardDefinition(raw['id'],raw['name'],kind,cost=cost,attack=raw['attack'] or 0,
            health=raw['health'] if kind==CardType.MINION else 0,
            durability=raw['health'] if kind==CardType.WEAPON else 0,
            keywords=tuple(Keyword(k) for k in recipe['keywords']),spell_school=SCHOOLS.get(school),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
