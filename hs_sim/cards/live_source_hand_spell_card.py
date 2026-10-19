"""Ido supplies one original Holy spell; the engine owns its live source lease."""
import json
from pathlib import Path
from hs_sim.engine.effects import Buff,GrantKeyword
from hs_sim.engine.live_hand_spells import LiveHandSpellProfile
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SpellSchool,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import canonical_digest,TargetValidationError
from .metadata import metadata_from_record

CARD,SPELL='TLC_241','TLC_241t'
BODY='cards.live_hand_spell.buff'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/live-source-hand-spell-v1.json'
BATCH_HASH='7591a9f3f3240b1e503338b71ece55e1078cf5e1710176aecfd3ed115a4cf68a'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id'] for x in d['cards'])!=(CARD,) or
            tuple(x['record']['id'] for x in d['dependencies'])!=(SPELL,) or
            tuple(x['record']['id'] for x in d['evidence_only'])!=('TLC_241e','TLC_241e2') or
            d['existing_dependencies'] or d['skipped']):raise TargetValidationError('Ido requires its complete real source and spell')
    for x in (*d['cards'],*d['dependencies'],*d['evidence_only']):
        if canonical_digest(x['record'])!=x['record_sha256']:raise TargetValidationError('Ido full source changed')
    return d


def register_live_source_hand_spell_card(registry):
    registry.register_behavior(BODY,lambda c:(Buff(c.target_id,2,2,c.source_id),GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id)))
    d=load_batch();raw=d['cards'][0]['record'];spell=d['dependencies'][0]['record']
    for card in (
        CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw)),
        CardDefinition(SPELL,spell['name'],CardType.SPELL,cost=spell['cost'],on_play=BODY,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='any'),
            spell_school=SpellSchool.HOLY,metadata=metadata_from_record(spell)),
    ):
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_live_hand_spell_profile(LiveHandSpellProfile(CARD,SPELL))
