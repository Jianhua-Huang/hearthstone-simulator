"""Reviewed native end-turn bodies and complete fixed-token materials."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import (AddToHand, Buff, Damage, DamageBatch, GrantKeyword,
                                   ForceAttack, Heal, HealBatch, InvokeBehavior, RandomDamage)
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, EndTurnSpec, HealingKind,
                                 BoardPresenceReference, Keyword, SummonStats, TriggerSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.source_stat_summons import SummonBySourceStats
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions, load_batch as native_followup_batch

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-end-effects-v1.json'
BATCH_HASH='77f79e9b73955880285487c381fc2b82d077c38bb632120c475e2d520490cb47'
PREFIX='cards.native_end.'
SCRIPTS={'CAP_107':'cannonmaster','CATA_133':'flitterwing','CATA_305':'matriarch',
    'CATA_475':'bulwark','CATA_476':'keeper','CATA_478':'redeemer','CATA_999':'drake',
    'EDR_816':'mosquito','EDR_942':'cumulus','EDR_971':'caretaker','JAIL_883':'golem',
    'TIME_054':'skipper','CORE_TTN_866':'terror','DINO_132':'asphyxiodon'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Native ending cards differ from their complete reviewed source pin')
    return data


def register_native_end_cards(registry):
    def invoke(c,name):
        return (InvokeBehavior(PREFIX+'execute_'+name,c.source_id,c.player_id),)

    def summon(c,cid,stats=None):
        return (SummonByCard(c.player_id,(SummonEntryMaterial(cid,stats),),SummonCause.capture(c)),)

    def other_buffs(c,attack,health=0):
        return tuple(Buff(eid,attack,health,c.source_id) for eid in minions(c,registry,c.player_id)
                     if eid != c.source_id)

    def terror(c):
        if c.source_id not in minions(c,registry,c.player_id):return ()
        defender=BoardPresenceReference.capture(c.state,c.source_id)
        return tuple(ForceAttack(BoardPresenceReference.capture(c.state,eid),defender)
                     for eid in minions(c,registry,3-c.player_id))

    bodies={
        'cannonmaster':lambda c:(AddToHand(c.player_id,'CAP_107t',c.source_id),),
        'flitterwing':lambda c:other_buffs(c,1,1),
        'matriarch':lambda c:(Buff(c.source_id,health=3,source_id=c.source_id),)
            if c.source.health == c.source.max_health else (),
        'bulwark':lambda c:(DamageBatch(tuple(Damage(eid,2,c.source_id,DamageKind.MINION_ABILITY)
            for eid in characters(c,registry,3-c.player_id))),),
        'keeper':lambda c:summon(c,'CATA_476t'),
        'redeemer':lambda c:(SummonBySourceStats(c.player_id,'CATA_478t',MinionReference.capture(c.source),
            SummonStats(c.source.attack,c.source.health),SummonCause.capture(c)),),
        'drake':lambda c:(Damage(c.state.players[3-c.player_id].hero_id,4,c.source_id,DamageKind.MINION_ABILITY),),
        'mosquito':lambda c:other_buffs(c,1),
        'cumulus':lambda c:(GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.DIVINE_SHIELD,c.source_id),),
        'caretaker':lambda c:(HealBatch(tuple(Heal(c.state.players[pid].hero_id,3,c.source_id,
            HealingKind.EFFECT) for pid in (1,2))),),
        'golem':lambda c:(GrantKeyword(c.source_id,Keyword.REBORN,c.source_id),),
        'skipper':lambda c:(AddToHand(c.state.active_player,'GAME_005',c.source_id),),
        'terror':terror,
        'asphyxiodon':lambda c:(RandomDamage(minions(c,registry,3-c.player_id),5,c.source_id,DamageKind.MINION_ABILITY),),
    }
    for name,body in bodies.items():
        if name in ('cannonmaster','redeemer'):registry.register_behavior(PREFIX+name,body)
        else:
            registry.register_behavior(PREFIX+'execute_'+name,body)
            registry.register_behavior(PREFIX+name,lambda c,name=name:invoke(c,name))
    data=load_batch()
    for evidence in data['followup_identity_evidence']:
        raw=evidence['record'];row=next(x for x in data['cards']if x['record']['id']==evidence['root_id'])
        if (canonical_digest(raw)!=evidence['record_sha256']or row['record']['tags']['DECK_RULE_COUNT_AS_COPY_OF_CARD_ID']!=raw['dbf_id']
                or row['recipe']['deck_identity']!=raw['id']):
            raise TargetValidationError('Native ending alias lost its explicit original identity')
    prior={row['record']['id']:row['record'] for row in native_followup_batch()['cards']}
    for row in data['existing_dependencies']:
        raw=row['record'];card=registry.card(raw['id'])
        if (canonical_digest(raw) != row['record_sha256'] or prior.get(raw['id']) != raw
                or (card.cost,card.attack,card.health) != (raw['cost'],raw['attack'],raw['health'])):
            raise TargetValidationError('Existing end-token dependency lost its complete original material')
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe']
        if (canonical_digest(raw) != row['record_sha256'] or raw['type'] != 'MINION'
                or (raw['cost'],raw['attack'],raw['health'],raw['collectible']) !=
                   (recipe['cost'],recipe['attack'],recipe['health'],recipe['root'])):
            raise TargetValidationError('Native ending card lost its complete reviewed face')
        kwargs={};script=recipe['script']
        if script is not None:
            if SCRIPTS.get(raw['id']) != script:raise TargetValidationError('Unreviewed end body')
            if raw['id']=='CAP_107':kwargs['battlecry']=PREFIX+script
            else:kwargs['triggers']=(TriggerSpec('turn_ended',PREFIX+script,EndTurnSpec(recipe['turn_scope'])),)
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=recipe['cost'],
            attack=recipe['attack'],health=recipe['health'],
            keywords=tuple(Keyword(value) for value in recipe['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
