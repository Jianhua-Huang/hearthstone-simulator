"""Complete fixed companion family and real Halazzi hand refill."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import ChoiceOption,RequestChoice
from hs_sim.engine.model import AuraSpec,CardDefinition,CardType,Keyword,SummonProducerProfile
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.producer_amounts import decisions,source_kind
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial,validate_cause
from hs_sim.engine.zones import FillHandWithCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/fixed-companion-effects-v1.json'
BATCH_HASH='f2449788713574047bda45e1cb3aec96251998b0f59ad9c83e8d5c5474547aaf'
PREFIX='cards.fixed_companions.'
COMPANIONS=('NEW1_034','NEW1_033','NEW1_032')
COMPANION_UNIT=PREFIX+'animal_companions'
SCRIPTS={'CORE_NEW1_031':'random_companion','CORE_OG_211':'all_companions','CORE_TRL_900':'fill_lynx',
    'NEW1_034':'huffer','NEW1_033':'leokk','NEW1_032':'misha','TRL_348t':'lynx'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Fixed companion complete source pin changed')
    return value


def companion_effects(context,registry,mode='random'):
    """Quote one card body, retaining its complete tail through player choices.

    Additional companions are independent random entries after the original
    body. Ordinary summon multipliers still apply to each selected entry.
    The original no-program recipes and their RNG/choice identities are kept.
    """
    if mode not in ('random','all','choice'):
        raise ValueError('Unknown Animal Companion body')
    cause=SummonCause.capture(context)
    validate_cause(context.state,registry,cause)
    materials=tuple(SummonEntryMaterial(cid)for cid in COMPANIONS)
    for cid in COMPANIONS:
        if registry.card(cid).kind!=CardType.MINION:
            raise ValueError('Animal Companions require complete minion definitions')
    profile=registry.summon_producer_profile(PREFIX+mode)
    inventory=tuple(context.state.players[context.player_id].player_effects)
    rows=decisions(registry,profile,cause,source_kind(registry,cause),
        3 if mode=='all'else 1,inventory)
    additional=sum(row.additional for row in rows)
    random_entry=SummonByCard(context.player_id,materials,cause,selection='random')
    tail=(random_entry,)*additional
    if mode=='random':return(random_entry,*tail)
    def fixed(material):return SummonByCard(context.player_id,(material,),cause)
    if mode=='all':return(*(fixed(material)for material in materials),*tail)
    options=tuple(ChoiceOption(material.card_id,registry.card(material.card_id).name,
        (fixed(material),*tail),card_id=material.card_id)for material in materials)
    return(RequestChoice(context.player_id,options,context.source_id),)


def register_fixed_companion_cards(registry):
    batch=load_batch();order=tuple(batch['companion_order'])
    if order!=('NEW1_034','NEW1_033','NEW1_032')or batch['lynx_card_id']!='TRL_348t':
        raise TargetValidationError('Fixed companion identities/order changed')
    for mode,policy in (('random','single_random_board'),('all','ordered_board_group'),('choice','choice_board')):
        registry.register_summon_producer_profile(SummonProducerProfile(PREFIX+mode,COMPANION_UNIT,mode=policy))
    bodies=dict(random_companion=lambda c:companion_effects(c,registry),
        all_companions=lambda c:companion_effects(c,registry,'all'),
        fill_lynx=lambda c:(FillHandWithCard(c.player_id,batch['lynx_card_id'],c.source_id),))
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for row in batch['historical_identity_evidence']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Fixed companion identity changed')
    for row in batch['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script'];kind=CardType(raw['type'].lower())
        if(canonical_digest(raw)!=row['record_sha256']or SCRIPTS.get(raw['id'])!=script or
                raw['collectible']!=(recipe['role']=='root')):raise TargetValidationError('Unreviewed fixed companion face')
        kwargs={}
        if script in bodies:kwargs['on_play'if kind==CardType.SPELL else'battlecry']=PREFIX+script
        if script=='leokk':kwargs['auras']=(AuraSpec(attack=1),)
        card=CardDefinition(raw['id'],raw['name'],kind,cost=raw['cost'],attack=raw['attack']or 0,
            health=raw['health']if kind==CardType.MINION else 0,keywords=tuple(Keyword(k)for k in recipe['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
