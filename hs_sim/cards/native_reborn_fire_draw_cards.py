"""Real native retained Reborn and Kindred's original drawn FIRE spell."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SpellSchool
from hs_sim.engine.owner_turns import query_for_definition,query_previous_owner_turn
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.stored_spell_damage import DrawMatchingSpellDamage
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-reborn-fire-draw-v1.json'
BATCH_HASH='d5c855c4d38e26b8ff610307187e702f8105d31eaef9f7092f6fabfc71348153'
PREFIX='cards.native_reborn_fire.'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Native Reborn/FIRE draw recipes lost their full reviewed pin')
    return value


def register_native_reborn_fire_draw_cards(registry):
    def thrasher(c):
        matched=query_previous_owner_turn(c.state,c.player_id,query_for_definition(registry.card(c.source.card_id))).matched
        query=PoolQuery(kinds=(CardType.SPELL,),spell_schools=(SpellSchool.FIRE,))
        return(DrawMatchingSpellDamage(c.player_id,query,c.source_id,2),)if matched else(
            DrawMatching(c.player_id,query,'skip',source_id=c.source_id),)
    registry.register_behavior(PREFIX+'thrasher',thrasher)
    data=load_batch();rows={x['record']['id']:x for x in data['cards']}
    if set(rows)!={'CAP_800','TLC_223'}:raise TargetValidationError('Unreviewed native Reborn/FIRE draw family')
    for cid,row in rows.items():
        raw=row['record'];recipe=row['recipe']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or not raw['collectible']:
            raise TargetValidationError('Unreviewed native Reborn/FIRE draw face')
        kwargs=dict(keywords=(Keyword.REBORN,),reborn_policy='full_health_enchantments')if cid=='CAP_800'else dict(battlecry=PREFIX+'thrasher')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
