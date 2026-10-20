"""Aya's real second-player deck rule, three counterfeits and permanent choice."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.coin_replacements import CoinReplacementChoice,CoinReplacementProfile
from hs_sim.engine.composed_spells import CreateRandomComposedSpell
from hs_sim.engine.effects import AddToHand,ChoiceOption,GainTemporaryMana,RequestChoice
from hs_sim.engine.jade import JadeGolemFamily,SummonJadeGolem
from hs_sim.engine.model import CardDefinition,CardType,PlayerEffectSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_coin_hand_cost_cards import load_batch as coin_family_source
from .kazakus_potion_cards import TEMPLATE as POTION,load_batch as potion_source

CARD='JAIL_504';JADE=CARD+'t';GRIMY=CARD+'t2';KABAL=CARD+'t3'
COINS=(JADE,GRIMY,KABAL);FORMS=tuple(CARD+'tt'+i for i in('01','04','07','20'))
FAMILY='jade.violet';PREFIX='cards.aya.coin.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/aya-counterfeit-coins-v1.json'
BATCH_HASH='36d1514b1501627827760aa9dbdd5f7ee4ddfe8f79aa5e83c57edc763f92c92b'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=(*data['cards'],*data['dependencies'],*data['existing_dependencies'])
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or
            tuple(x['record']['id']for x in data['dependencies'])!=(JADE,KABAL,*FORMS)or
            tuple(x['record']['id']for x in data['existing_dependencies'])!=(GRIMY,POTION)or
            any(data[k]for k in('choice_only','evidence_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Aya requires her complete root, three actual Coins and real Jade/Potion templates')
    raw={x['record']['id']:x['record']for x in rows}
    if (raw[CARD]['cost'],raw[CARD]['attack'],raw[CARD]['health'])!=(6,6,3)or any(
            raw[c]['type']!='SPELL'or raw[c]['tags'].get('COIN_CARD')!=1 for c in COINS):
        raise TargetValidationError('Aya original body or native Coin classifications changed')
    return data


def register_aya_counterfeit_cards(registry):
    data=load_batch();rows={x['record']['id']:x['record']for x in(*data['cards'],*data['dependencies'])}
    for cid,pin in data['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid)))!=pin['sha256']or canonical_digest(pin['definition'])!=pin['sha256']:
            raise TargetValidationError('Aya must preserve the complete existing dependency: '+cid)
    # Full dependency content is pinned independently of checkout line endings.
    family=coin_family_source();potion=potion_source()
    for field,content in(('coin_family_source',family),('potion_dependency',potion)):
        if canonical_digest(content)!=data[field+'_canonical_sha256']:
            raise TargetValidationError('Aya original shared dependency packet changed')
    def choose(c):
        return(RequestChoice(c.player_id,tuple(ChoiceOption(cid,registry.card(cid).name,
            (AddPlayerEffect(c.player_id,PREFIX+cid,c.source_id),
             *(AddToHand(c.player_id,cid,source_id=c.source_id)for _ in range(3))),card_id=cid)for cid in COINS),
            c.source_id,prompt='选择一种升级后的伪造幸运币'),)
    registry.register_behavior(PREFIX+'battlecry',choose)
    registry.register_behavior(PREFIX+JADE,lambda c:(GainTemporaryMana(c.player_id,1),SummonJadeGolem(c.player_id,c.source_id,FAMILY)))
    registry.register_behavior(PREFIX+KABAL,lambda c:(GainTemporaryMana(c.player_id,1),CreateRandomComposedSpell(c.player_id,POTION,c.source_id)))
    for cid,raw in rows.items():
        kind=CardType(raw['type'].lower());fields={}
        if kind==CardType.MINION:fields.update(attack=raw['attack'],health=raw['health'])
        if cid==CARD:fields['battlecry']=PREFIX+'battlecry'
        elif cid in(JADE,KABAL):fields['on_play']=PREFIX+cid
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost']if kind==CardType.MINION else 0,
            metadata=metadata_from_record(raw),**fields)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_jade_family(JadeGolemFamily(FAMILY,'jade-basics-v1',FORMS))
    choices=tuple(CoinReplacementChoice(PREFIX+cid,cid)for cid in COINS)
    for choice in choices:registry.register_player_effect(PlayerEffectSpec(choice.program_id,CARD))
    registry.register_coin_replacement_profile(CoinReplacementProfile(CARD,tuple(family['coin_spell_ids']),choices))
    registry.register_second_player_card(CARD)
