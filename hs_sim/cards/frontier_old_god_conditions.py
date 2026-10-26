"""Two real Old Gods compose current-zone conditions and original play history."""
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand, Destroy, InvokeBehavior
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOTS=('BOT_424','DMF_188')
EXISTING=('DMF_064','DMF_064t')
PREFIX='cards.frontier_old_god_conditions.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/frontier-old-god-conditions-v1.json'
BATCH_HASH='c3482dd75ced26f72a3f6300fd28c7aa61999735cff4ab8a9264cc420ed6be68'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=value['cards']+value['existing_dependencies']
    if (canonical_digest(value)!=BATCH_HASH or value['schema']!=1 or value['dependencies'] or
            tuple(x['record']['id']for x in value['cards'])!=ROOTS or
            tuple(x['record']['id']for x in value['existing_dependencies'])!=EXISTING or
            len(value['official_faces'])!=4 or value['formal_pool_complete']is not False or
            value['cn_calibrated']is not False or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Old God conditions lost their complete original native scope')
    return value


def register_frontier_old_god_conditions(registry):
    value=load_batch();rows={x['record']['id']:x['record']for x in value['cards']}
    if any(cid in registry.cards for cid in ROOTS) or not all(cid in registry.cards for cid in EXISTING):
        raise TargetValidationError('Old God identities cannot overwrite or omit original native dependencies')
    def check_mechathun(c):
        player=c.state.players[c.player_id]
        return (Destroy(c.state.players[3-c.player_id].hero_id,c.source_id),)if not (
            player.deck or player.hand or player.board)else ()
    def mechathun(c):
        # The captured Deathrattle context precedes earlier reactions/payloads.
        # Defer only this real condition to the ordinary execution queue.
        return (InvokeBehavior(PREFIX+'check_mechathun',c.source_id,c.player_id),)
    def yshaarj(c):
        # Freeze the accepted occurrences now. Ordinary hand creation owns
        # capacity, reactions, generated-card costs and attachment expiry.
        return tuple(AddToHand(c.player_id,p.card_id,c.source_id,cost=CostSpec(set_to=0),expires_turn=c.state.turn)
            for p in c.state.play_history if p.player_id==c.player_id and
            Keyword.CORRUPTED in registry.card(p.card_id).keywords)
    for name,body in (('mechathun',mechathun),('check_mechathun',check_mechathun),('yshaarj',yshaarj)):
        registry.register_behavior(PREFIX+name,body)
    for cid,raw in rows.items():
        body={'deathrattle':PREFIX+'mechathun'}if cid=='BOT_424'else {'battlecry':PREFIX+'yshaarj'}
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=metadata_from_record(raw),**body)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
