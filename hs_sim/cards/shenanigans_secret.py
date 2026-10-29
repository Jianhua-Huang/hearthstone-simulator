"""Shenanigans over the original second draw and the existing real Bananas."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.draw_transformations import TransformDrawnCard,successful_prefix,HAND_ENTRY_KEY,BANANA
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/shenanigans-secret-v1.json'
BATCH_HASH='9f400369650735946cc396265bd0e59ad7f398c38caf8f6e72878d9d51df6b0e'
CARD='YOP_017'
LEAVES=(CARD,)
COLLECTIBLE_ROOTS=()
PREFIX='cards.shenanigans_secret.'
BANANA_HASH='d5329ae6b151d67066d51a49c38408c116722e880b618f0880e8342dbebd8252'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-shenanigans-secret-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id']for x in d['dependencies'])!=LEAVES or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=(BANANA,) or len(d['official_observations'])!=2 or
            any(d[k]for k in('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in (*d['dependencies'],*d['existing_dependencies']))):
        raise TargetValidationError('Shenanigans lost its complete original Secret/Bananas source')
    p=ROOT/d['reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256'] or CARD not in json.loads(p.read_text(encoding='utf8'))['candidate_ids']:
        raise TargetValidationError('Shenanigans lost the complete unfiltered past Secret reference')
    return d


def original_draw(c):
    e=c.event
    if e is None or e.kind!='card_drawn' or e.player_id==c.player_id:return None
    number=dict(e.data).get('draw_id')
    if type(number)is not int or not 1<=number<=len(c.state.draw_history):return None
    row=c.state.draw_history[number-1];entity=c.state.entities.get(row.entity_id)
    if (row.completed or row.interrupted or row.transformation is not None or row.turn!=c.state.turn or
            row.outcome not in('hand','cast') or len(successful_prefix(c.state,row))!=2 or entity is None or
            (e.source_id,e.target_id,e.player_id,e.action)!=(row.source_id,row.entity_id,row.player_id,row.action)):
        return None
    if row.outcome=='hand':
        if (dict(e.data).get(HAND_ENTRY_KEY)!=row.hand_entry_id or
                (entity.zone,entity.controller,entity.hand_entry_id)!=(Zone.HAND,row.player_id,row.hand_entry_id)):return None
    elif row.phase!='pending_cast' or (entity.zone,entity.controller,entity.card_id)!=(Zone.GRAVEYARD,row.player_id,row.card_id):return None
    return row


def register_shenanigans_secret(registry):
    d=load_batch();raw=d['dependencies'][0]['record']
    if canonical_digest(asdict(registry.card(BANANA)))!=BANANA_HASH:
        raise TargetValidationError('Shenanigans must reuse the unchanged complete real Bananas definition')
    if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1 or CARD in registry.cards or CARD in registry.pool_cards:
        raise TargetValidationError('Shenanigans requires its original new Secret spell')
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
        secret=SecretSpec(CARD,('card_drawn',),PREFIX+CARD,PREFIX+CARD),metadata=metadata_from_record(raw))
    registry._validate_card(card)
    def body(c):
        row=original_draw(c)
        return ()if row is None else(TransformDrawnCard(row,SourceAllocationFact.capture(c.state,c.source),c.event,
            SourceAllocationFact.capture(c.state,c.state.entities[row.entity_id]),c.state.action_number),)
    registry.register_secret_condition(PREFIX+CARD,lambda c:original_draw(c)is not None)
    registry.register_behavior(PREFIX+CARD,body);registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
