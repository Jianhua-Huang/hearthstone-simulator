"""Reviewed conditional/stat/zone Battlecries; original ledgers and executors."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.damage_history import hero_damage_taken
from hs_sim.engine.effects import Buff,Damage,DoubleStats,Draw,Freeze,GrantKeyword,InvokeBehavior
from hs_sim.engine.hero_powers import activated_powers
from hs_sim.engine.imbue import Imbue,imbue_count
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,DamageKind,Keyword,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.zones import CardReference,DrawMinionWithAttack,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/conditional-battlecry-effects-v1.json'
BATCH_HASH='b85ddfc4bbb8bab06992de843b09c4b3b84158a36b5846a1ffbc59597908947f'
PREFIX='cards.conditional_battlecry.'
SCRIPTS={'CATA_612':'frozen','DINO_411':'egg','EDR_472':'weaver','EDR_860':'dreamer',
    'EDR_970':'priestess','END_001':'saw','END_019':'survivor','FIR_777':'soul',
    'FIR_921':'attendant','FIR_961':'dryad','JAIL_456':'pickpocket','JAIL_513':'skull',
    'TIME_705':'krona','TIME_720':'soldier','TIME_871':'scion','TLC_633':'pest'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Conditional Battlecries differ from complete reviewed source pin')
    return data


def register_conditional_battlecry_cards(registry):
    def holding_spell(c):
        return any(e.kind==CardType.SPELL and quote_unselected_cost(c.state,registry,e).amount>=5
            for eid in c.state.players[c.player_id].hand for e in (c.state.entities[eid],))

    def imbued(c):return imbue_count(c.state,c.player_id)>=2

    def own(c):return next(p for p in c.observation['players'] if p['id']==c.player_id)

    def player_holding(c):
        return any(card['kind']=='spell' and card['cost']['amount']>=5 for card in own(c)['hand'])

    def player_typed(c):
        tribes=c.target.get('tribes')
        if tribes is None:raise UnsupportedDefinitionError('Minion type is unknown: '+c.target['card_id'])
        return bool(tribes)

    for name,rule in (('holding_spell',player_holding),('imbued',lambda c:own(c)['imbue']['count']>=2),('typed',player_typed)):
        registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+name,'v1'),rule)

    def invoke(c,name):
        return (InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,
            None if c.play is None else c.play.id),)

    def hit(c,amount,condition=lambda c:True):
        return (Damage(c.target_id,amount,c.source_id,DamageKind.MINION_ABILITY),) if c.target_id is not None and condition(c) else ()

    def priestess(c):
        return tuple(Buff(eid,attack=-2,source_id=c.source_id,until_owner_turn_start=c.player_id)
            for eid in minions(c,registry,3-c.player_id))+(Imbue(c.player_id,c.source_id),)

    def dryad(c):
        return tuple(GrantKeyword(c.source_id,key,c.source_id) for key in (Keyword.DIVINE_SHIELD,Keyword.LIFESTEAL)) if holding_spell(c) else ()

    def krona(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[eid]),CostSpec(set_to=1),c.source_id)
            for eid in c.state.players[c.player_id].deck[-5:])

    def scion(c):
        count=sum(c.state.entities[eid].health<c.state.entities[eid].max_health
            for pid in (1,2) for eid in minions(c,registry,pid))
        return (Buff(c.source_id,2*count,2*count,c.source_id),) if count else ()

    bodies={
        'frozen':lambda c:(Freeze(c.source_id),),
        'egg':lambda c:(DrawMinionWithAttack(c.player_id,0,c.source_id),),
        'weaver_now':lambda c:hit(c,3,holding_spell),
        'dreamer_now':lambda c:hit(c,4,imbued),
        'priestess_now':priestess,'saw':lambda c:(Imbue(c.player_id,c.source_id),),
        'survivor_now':lambda c:(Buff(c.source_id,3,3,c.source_id),)
            if hero_damage_taken(c.state,c.player_id,turn=c.state.turn)>0 else (),
        'soul_now':lambda c:(Buff(c.source_id,3,3,c.source_id),)
            if activated_powers(c.state,c.player_id,origin='manual',turn=c.state.turn) else (),
        'attendant_now':lambda c:(Draw(c.player_id,2,c.source_id),) if imbued(c) else (),
        'dryad_now':dryad,
        'pickpocket_now':lambda c:(Draw(c.player_id,source_id=c.source_id),)
            if len(c.state.players[c.player_id].deck)>=25 else (),
        'skull_now':lambda c:(Buff(c.source_id,health=len(c.state.players[c.player_id].hand),source_id=c.source_id),)
            if c.state.players[c.player_id].hand else (),
        'krona_now':krona,'soldier':lambda c:(DoubleStats(c.source_id,health=True,source_id=c.source_id),),
        'scion_now':scion,'pest':lambda c:hit(c,6),
    }
    for name in ('weaver','dreamer','priestess','survivor','soul','attendant','dryad','pickpocket','skull','krona','scion'):
        bodies[name]=lambda c,name=name:invoke(c,name+'_now')
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe'];cid=raw['id'];kind=CardType(raw['type'].lower())
        if (canonical_digest(raw)!=row['record_sha256'] or SCRIPTS.get(cid)!=recipe['script']
                or raw['tags'].get('BATTLECRY')!=1 or kind not in (CardType.MINION,CardType.WEAPON)
                or (raw['cost'],raw['attack'],raw['health'],raw['collectible'])!=
                   (recipe['cost'],recipe['attack'],recipe['source_health'],recipe['collectible'])):
            raise TargetValidationError('Conditional Battlecry lost its reviewed complete face')
        kwargs={'health':raw['health']} if kind==CardType.MINION else {'durability':raw['health']}
        target=recipe['target']
        if target is not None:
            kwargs['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,
                zones=(Zone.HERO,Zone.BOARD) if target=='character' else (Zone.BOARD,),
                kinds=(CardType.HERO,CardType.MINION) if target=='character' else (CardType.MINION,),
                relation='enemy' if target=='enemy_typed_minion' else 'any')
            kwargs['target_rule']=PREFIX+recipe['target_rule']
        card=CardDefinition(cid,raw['name'],kind,cost=recipe['cost'],attack=recipe['attack'],
            keywords=tuple(Keyword(value) for value in recipe['keywords']),battlecry=PREFIX+recipe['script'],
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
