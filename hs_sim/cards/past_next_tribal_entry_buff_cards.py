"""Two real one-use tribal entry programs over the original public writers."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, Keyword, PlayerEffectSpec, SummonStats, TriggerSpec
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_entry_stats import SummonEntryStatsProfile
from hs_sim.engine.summon_completions import AFTER, original_receiver
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

MUSIC, STAR = 'ETC_831', 'GDB_720'
DEPENDENCIES = (MUSIC, STAR)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_next_tribal_entry_buffs.'
PROGRAMS = {cid:PREFIX+cid for cid in DEPENDENCIES}
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-next-tribal-entry-buffs-v1.json'
BATCH_HASH = '67aac7b609f81b2588301881fbb8bcc72eebf61571dae5008da069745d6aeb1a'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES or
            any(data[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only',
                'skipped', 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Next tribal entry sources lost their complete original pin')
    return data


def register_past_next_tribal_entry_buff_cards(registry):
    def finale(context):
        conditions = context.spell_conditions
        if conditions is None:
            raise ResolutionError('Musician Finale requires its actual original play conditions')
        return (AddPlayerEffect(context.player_id, PROGRAMS[MUSIC], context.source_id),) if conditions.finale else ()
    registry.register_behavior(PROGRAMS[MUSIC], finale)
    def reward(context):
        if context.player_effect is None or context.player_effect.spec_id != PROGRAMS[MUSIC]:
            raise ResolutionError('Musician reward requires its original independent programme')
        entity = original_receiver(context)
        if entity is None or not has_any_tribe(registry, entity, ('beast',)): return ()
        return (RemovePlayerEffect(context.player_id,context.player_effect.id),
            BuffCapturedMinion(MinionReference.capture(entity),1,1,context.source_id))
    registry.register_behavior(PROGRAMS[MUSIC]+'.reward',reward)
    registry.register_behavior(PROGRAMS[STAR], lambda c: (AddPlayerEffect(c.player_id, PROGRAMS[STAR], c.source_id),))
    for item in load_batch()['dependencies']:
        raw = item['record']; cid = raw['id']
        if (raw['type'], raw['collectible'], raw['cost'], raw['attack'], raw['health']) != (
                'MINION', True, 1, 1 if cid == MUSIC else 2, 3 if cid == MUSIC else 1):
            raise TargetValidationError('Next tribal entry changed its original printed body')
        if cid == MUSIC:
            if raw['tags'].get('FINALE') != 1:
                raise TargetValidationError('Musician lost its original Finale')
            fields = dict(on_play=PROGRAMS[cid], keywords=(Keyword.FINALE,))
        else:
            if raw['tags'].get('BATTLECRY') != 1:
                raise TargetValidationError('Wanderer lost its original Battlecry')
            fields = dict(battlecry=PROGRAMS[cid])
            tribes, stats, mode = ('draenei',), SummonStats(2, 1), 'next_play_add'
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=raw['attack'],
            health=raw['health'], metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
        if cid == MUSIC:
            registry.register_player_effect(PlayerEffectSpec(PROGRAMS[cid],cid,
                triggers=(TriggerSpec(AFTER,PROGRAMS[cid]+'.reward'),)))
        else:
            registry.register_player_effect(PlayerEffectSpec(PROGRAMS[cid],cid))
            registry.register_summon_entry_stats_profile(SummonEntryStatsProfile(PROGRAMS[cid],cid,tribes,stats,mode))
