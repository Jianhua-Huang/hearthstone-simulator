"""The four native Follow spells share timed physical after-play attachments."""
from dataclasses import asdict,replace
import json
from pathlib import Path

from hs_sim.engine.after_play_grants import GrantRandomAfterPlay
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.deck_shuffles import ShuffleDeckCards
from hs_sim.engine.effects import RandomDamage
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,SpellSchool
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

FOOTSTEPS,FUSE,EVIDENCE,GHOSTS='CAP_002','CAP_101','CAP_402','CAP_802'
ROOTS=(FOOTSTEPS,FUSE,EVIDENCE,GHOSTS);IMP='CAP_400t2t';GHOST='CAP_802t'
PREFIX='cards.follow_hand.'
BODIES={FOOTSTEPS:PREFIX+'footsteps',FUSE:PREFIX+'fuse',EVIDENCE:PREFIX+'evidence',GHOSTS:PREFIX+'ghosts'}
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/follow-hand-v1.json'
BATCH_HASH='1c0ed88a613f844db05433496dbd3605480f2ccbc00b4611edc26bebe69c8442'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=(IMP,GHOST) or d['dependencies'] or
            any(canonical_digest(x['record'])!=x['record_sha256']
                for k in ('cards','existing_dependencies','evidence_only')for x in d[k])):
        raise TargetValidationError('Follow spells require their complete original shared source packet')
    return d


def register_follow_hand_cards(registry):
    d=load_batch()
    for cid,pin in d['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid)))!=pin:
            raise TargetValidationError('Follow spells must reuse their original Imp-formant and Ghost')

    def footsteps(c):
        return (DiscoverFromPool(c.player_id,'constructed.cards',
            PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current',keywords_all=(Keyword.STEALTH,)),
            source_id=c.source_id,minion_grant=CreatedMinionGrant(special='after_play',identity=BODIES[FOOTSTEPS])),)

    def fuse(c):
        kind=c.play.kind if c.play is not None else c.source.kind
        damage_kind=DamageKind.SPELL if kind==CardType.SPELL else DamageKind.MINION_ABILITY if kind==CardType.MINION else DamageKind.EFFECT
        return (RandomDamage(characters(c,registry,3-c.player_id),2,c.source_id,damage_kind),
            GrantRandomAfterPlay(c.player_id,BODIES[FUSE],c.source_id,('pirate',)))

    def evidence(c):
        return (ShuffleDeckCards(3-c.player_id,c.player_id,
            (AddToDeck(3-c.player_id,IMP,source_id=c.source_id),),c.source_id),
            GrantRandomAfterPlay(c.player_id,BODIES[EVIDENCE],c.source_id))

    def ghosts(c):
        return (SummonByCard(c.player_id,(SummonEntryMaterial(GHOST),),SummonCause.capture(c)),
            GrantRandomAfterPlay(c.player_id,BODIES[GHOSTS],c.source_id))

    for cid,body in zip(ROOTS,(footsteps,fuse,evidence,ghosts)):
        registry.register_behavior(BODIES[cid],body)
    for row in d['cards']:
        raw=row['record'];cid=raw['id']
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=BODIES[cid],
            spell_school=SpellSchool.SHADOW if cid==GHOSTS else None,
            metadata=replace(metadata_from_record(raw),deck_identity=cid))
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
