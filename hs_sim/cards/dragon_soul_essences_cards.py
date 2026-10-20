"""Dragon Soul's actual opening split and six ordinary adjoining spell bodies."""
import json
from pathlib import Path
from dataclasses import asdict

from hs_sim.engine.adjoining_spells import AdjoiningSpellProfile
from hs_sim.engine.deck_shuffles import ShuffleDeckCards
from hs_sim.engine.effects import Damage,DamageBatch,GainArmor,RefreshMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,OpeningHook,TargetSpec,Zone
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck,CardReference,DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

CARD='CATA_EVENT_110'
RED,BLUE,BRONZE,BLACK,GREEN,STORM=(CARD+'t'+str(i)for i in(2,3,4,5,6,7))
ESSENCES=(RED,BLUE,BRONZE,BLACK,GREEN,STORM);DRAGON=GREEN+'t'
PREFIX='cards.dragon_soul.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/dragon-soul-essences-v1.json'
BATCH_HASH='d374eccbce0307c9316fc624d5cd22664a48d5144d02b09f698025107a82466e'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=(*data['cards'],*data['dependencies'],*data['existing_dependencies'])
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or
            {x['record']['id']for x in rows}!={CARD,*ESSENCES,DRAGON}or
            tuple(x['record']['id']for x in data['existing_dependencies'])!=(DRAGON,)or
            any(data[k]for k in('choice_only','evidence_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Dragon Soul requires its complete original root, six Essences and real Dragon')
    raw={x['record']['id']:x['record']for x in rows}
    if (any((raw[c]['type'],raw[c]['cost'])!=('SPELL',6)for c in(CARD,*ESSENCES))or
            any(raw[c]['tags'].get('4761')!=1 for c in ESSENCES)or raw[CARD]['tags'].get('DONT_PICK_FROM_SUBSETS')!=1 or
            (raw[DRAGON]['type'],raw[DRAGON]['cost'],raw[DRAGON]['attack'],raw[DRAGON]['health'])!=('MINION',8,8,8)):
        raise TargetValidationError('Dragon Soul original Essence or generated Dragon material changed')
    return data


def register_dragon_soul_essences_cards(registry):
    def opening(c):
        from hs_sim.engine.opening_deck_copies import is_hook_source
        if not is_hook_source(c.state,c.source_id,c.player_id,CARD)or c.source.zone!=Zone.DECK:
            raise ResolutionError('Dragon Soul split requires its genuine before-deal deck source')
        return(RemoveFromGame((CardReference.capture(c.source),),c.source_id),
            ShuffleDeckCards(c.player_id,c.player_id,tuple(AddToDeck(c.player_id,cid,position='random',
                source_id=c.source_id)for cid in ESSENCES),c.source_id))
    bodies={CARD:lambda c:(),
        RED:lambda c:(Damage(c.target_id,8,c.source_id,DamageKind.SPELL),),
        BLUE:lambda c:(DrawMatching(c.player_id,PoolQuery(kinds=(CardType.SPELL,)),'skip',count=3,source_id=c.source_id),),
        BRONZE:lambda c:(RefreshMana(c.player_id,8),),
        BLACK:lambda c:(GainArmor(c.player_id,12),),
        GREEN:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(DRAGON),),SummonCause.capture(c)),),
        STORM:lambda c:(DamageBatch(tuple(Damage(eid,4,c.source_id,DamageKind.SPELL)
            for eid in minions(c,registry,3-c.player_id))),)}
    registry.register_behavior(PREFIX+'opening',opening)
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    data=load_batch()
    pin=data['existing_dependency_definition_pins'][DRAGON]
    if canonical_digest(asdict(registry.card(DRAGON)))!=pin['sha256']or canonical_digest(pin['definition'])!=pin['sha256']:
        raise TargetValidationError('Dragon Soul must preserve its already registered complete Dragon body')
    for item in(*data['cards'],*data['dependencies']):
        raw=item['record'];cid=raw['id'];kind=CardType(raw['type'].lower());fields={}
        if kind==CardType.SPELL:fields['on_play']=PREFIX+cid
        else:fields.update(attack=8,health=8)
        if cid==CARD:fields['opening_hooks']=(OpeningHook('before_deal',PREFIX+'opening'),)
        if cid==RED:fields['targeting']=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION),relation='enemy')
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**fields)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_adjoining_spell_profile(AdjoiningSpellProfile(ESSENCES))
    registry.register_generation_exclusion(CARD)
