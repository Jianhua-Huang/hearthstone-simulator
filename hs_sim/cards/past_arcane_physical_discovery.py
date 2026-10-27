"""Real original-deck copy play tracking and original drawn-spell discovery."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool, Zone
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.zones import ChooseFromZone
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-physical-discovery-v1.json'
BATCH_HASH = 'ccdd6601f41aacd4eb09be944ae313d3a9115cb7d6c1aaaad1b3f01073450d0b'
LEAVES = ('DED_002', 'ETC_205')
DEPENDENCIES = LEAVES
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_physical_discovery.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(x['record']['id']for x in data['dependencies']) != LEAVES or
            len(data['official_observations']) != 4 or not set(LEAVES) <= set(reference['candidate_ids']) or
            any(data[k]for k in ('cards', 'existing_dependencies', 'evidence_only', 'skipped', 'numeric_normalizations',
                'display_normalizations', 'source_scope_bound', 'formal_pool_complete', 'cn_calibrated')) or
            any(canonical_digest(x['record']) != x['record_sha256']for x in data['dependencies'])):
        raise TargetValidationError('Original Arcane physical discoveries changed their complete pinned source')
    return data


def register_past_arcane_physical_discovery(registry):
    prepared = []
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards:
            raise TargetValidationError('Original Arcane physical discovery cannot overwrite '+cid)
        if raw['type'] != 'SPELL' or raw['tags'].get('SPELL_SCHOOL') != 1:
            raise TargetValidationError('Original Arcane physical discovery changed its printed spell')
        card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'], spell_school=SpellSchool.ARCANE,
            on_play=PREFIX+cid, metadata=metadata_from_record(raw))
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Original Arcane physical discovery differs from printed metadata: '+cid)
        prepared.append(card)
    def moonlit(c):
        request = ChooseFromZone(c.player_id, c.player_id, Zone.DECK, operation='copy_current',
            distinct='card', source_id=c.source_id, discovery=True)
        return (DiscoverForPlayFollowup(request, reward_mode='draw_original'),)
    def volume(c):
        conditions = c.spell_conditions
        if conditions is None:
            raise ResolutionError('Volume Up requires its original spell conditions')
        reward = DrawGroupReward('discover_spell_copy') if conditions.finale else DrawGroupReward()
        return (DrawPhysicalGroup(c.player_id, c.source_id,
            (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)*3, reward),)
    registry.register_behavior(PREFIX+'DED_002', moonlit)
    registry.register_behavior(PREFIX+'ETC_205', volume)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
