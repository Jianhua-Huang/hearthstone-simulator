"""Reviewed native Battlecries composing original attributes, health and draw."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Buff,Damage,DamageBatch,Freeze,InvokeBehavior
from hs_sim.engine.imbue import Imbue
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-battlecry-effects-v1.json'
BATCH_HASH='e42a292ec1289d0e27cc35d6d1979fccfe190b6e6fe1d3ab0eac69bc85c0e045'
PREFIX='cards.simple_battlecry.'
SCRIPTS={'CORE_NEW1_018':'raider','CORE_OG_149':'ghoul','CORE_TRL_240':'striker',
    'CORE_UNG_205':'shard','CORE_GIL_623':'grizzly','EDR_226':'hound',
    'EDR_449':'moonwing','EDR_800':'guardian'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Simple Battlecry cards differ from complete reviewed source pin')
    return data


def register_simple_battlecry_cards(registry):
    def invoke(c,name):
        return (InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,
            None if c.play is None else c.play.id),)

    def raider(c):
        weapon=c.state.players[c.player_id].weapon_id
        amount=0 if weapon is None else c.state.entities[weapon].attack
        return (Buff(c.source_id,attack=amount,source_id=c.source_id),) if amount else ()

    def striker(c):
        if c.target_id is None:return ()
        amount=c.state.entities[c.state.players[c.player_id].hero_id].attack
        return (Damage(c.target_id,amount,c.source_id,DamageKind.MINION_ABILITY),)

    def grizzly(c):
        count=len(c.state.players[3-c.player_id].hand)
        return (Buff(c.source_id,health=-count,source_id=c.source_id),) if count else ()

    bodies={
        'raider':lambda c:invoke(c,'raider_now'),'raider_now':raider,
        'ghoul':lambda c:invoke(c,'ghoul_now'),
        'ghoul_now':lambda c:(DamageBatch(tuple(Damage(eid,1,c.source_id,DamageKind.MINION_ABILITY)
            for pid in (1,2) for eid in minions(c,registry,pid) if eid!=c.source_id)),),
        'striker':lambda c:invoke(c,'striker_now'),'striker_now':striker,
        'shard':lambda c:(Freeze(c.target_id),) if c.target_id is not None else (),
        'grizzly':lambda c:invoke(c,'grizzly_now'),'grizzly_now':grizzly,
        'hound':lambda c:(DrawMatching(c.player_id,PoolQuery(kinds=(CardType.MINION,),tribes_any=('beast',)),
            'skip',selection='random',source_id=c.source_id),Imbue(c.player_id,c.source_id)),
        'moonwing':lambda c:(Imbue(c.player_id,c.source_id),),
        'guardian':lambda c:(Imbue(c.player_id,c.source_id),),
    }
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe'];cid=raw['id']
        if (canonical_digest(raw)!=row['record_sha256'] or raw['type']!='MINION'
                or SCRIPTS.get(cid)!=recipe['script'] or raw['tags'].get('BATTLECRY')!=1
                or (raw['cost'],raw['attack'],raw['health'],raw['collectible'])!=
                   (recipe['cost'],recipe['attack'],recipe['health'],recipe['collectible'])):
            raise TargetValidationError('Simple Battlecry lost its reviewed complete face')
        kwargs={}
        target=recipe['target']
        if target is not None:
            if target not in ('enemy_minion','enemy_character'):
                raise TargetValidationError('Unreviewed Battlecry target domain')
            kwargs['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,
                zones=(Zone.BOARD,) if target=='enemy_minion' else (Zone.HERO,Zone.BOARD),
                kinds=(CardType.MINION,) if target=='enemy_minion' else (CardType.HERO,CardType.MINION),relation='enemy')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=recipe['cost'],attack=recipe['attack'],
            health=recipe['health'],keywords=tuple(Keyword(value) for value in recipe['keywords']),
            battlecry=PREFIX+recipe['script'],metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),
            **kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
