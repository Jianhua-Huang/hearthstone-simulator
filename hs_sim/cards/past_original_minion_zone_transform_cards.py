"""Original minion deck residence and actual post-damage recipient identity."""
import json
from pathlib import Path

from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,TriggerSpec,Zone
from hs_sim.engine.original_minion_shuffles import from_context
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference,TransformCapturedMinion
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

WEASEL,SPORE,AMALGAM='CFM_095','BT_731','VAC_958'
DEPENDENCIES=(WEASEL,SPORE,AMALGAM)
COLLECTIBLE_ROOTS=()
PREFIX='cards.past_original_minion_zone_transforms.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-original-minion-zone-transforms-v1.json'
BATCH_HASH='c195c311108cab72194f1b0c8b152fee578d994fa8dae4b43676a982342b66a9'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(data['collectible_leaf_ids'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or
            any(data[k]for k in('cards','existing_dependencies','evidence_only','choice_only','skipped',
                                'numeric_normalizations','display_normalizations')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in data['dependencies'])):
        raise TargetValidationError('Original minion shuffle/transform sources changed')
    return data


def register_past_original_minion_zone_transform_cards(registry):
    def move(c,opponent=False,keep=False):
        recipient=3-c.player_id if opponent else c.player_id
        request=from_context(c,recipient,keep_enchantments=keep)
        return shuffled(c,(request,),player_id=recipient)if request is not None else()
    def spore(c):
        event=c.event
        if event is None or event.kind!='damage_dealt':
            raise ResolutionError('Sporeling requires its actual original damage event')
        if event.source_id!=c.source_id or event.amount<=0:return ()
        target=c.state.entities[event.target_id]
        if target.kind!=CardType.MINION or target.zone!=Zone.BOARD or not target.active or target.health<=0 or target.doomed:
            return ()
        return (TransformCapturedMinion(MinionReference.capture(target),SPORE,c.source_id),)
    registry.register_behavior(PREFIX+WEASEL,lambda c:move(c,opponent=True))
    registry.register_behavior(PREFIX+AMALGAM,lambda c:move(c,keep=True))
    registry.register_behavior(PREFIX+SPORE,spore)
    for row in load_batch()['dependencies']:
        raw=row['record'];cid=raw['id']
        if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'])!=(
                'MINION',1,1,1 if cid==WEASEL else 2,True):
            raise TargetValidationError('Original zone/transform minion body changed')
        fields={'triggers':(TriggerSpec('damage_dealt',PREFIX+cid),)}if cid==SPORE else{'deathrattle':PREFIX+cid}
        if cid!=SPORE and raw['tags'].get('DEATHRATTLE')!=1:
            raise TargetValidationError('Original self-shuffle requires its actual Deathrattle')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=1,health=raw['health'],
            metadata=metadata_from_record(raw),**fields)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
