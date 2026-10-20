"""Two native conditions using original price and neighboring-residence facts."""
import json
from pathlib import Path
from hs_sim.engine.death_neighbors import BuffBoardPresence, references as neighbor_references
from hs_sim.engine.effects import Damage, DamageBatch, InvokeBehavior
from hs_sim.engine.hand_cost_rank import HandCostRankProfile, satisfied
from hs_sim.engine.model import CardDefinition, CardType, DamageKind
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters

BLASPHEMY, GUARD = 'BE_086', 'BE_151'
ROOTS = COLLECTIBLE_ROOTS = (BLASPHEMY, GUARD)
DEPENDENCIES = ()
PREFIX = 'cards.hand_rank_death_neighbors.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/hand-rank-death-neighbors-v1.json'
BATCH_HASH = '76b2120e2dbf15e66506a7664e813929dcd91806811dd21495b35eb176b2b714'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != ROOTS or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['cards'])):
        raise TargetValidationError('Native hand rank and neighbors lost their complete source')
    return data


def register_hand_rank_death_neighbor_cards(registry):
    registry.register_behavior(PREFIX+'blasphemy', lambda c: tuple(
        InvokeBehavior(PREFIX+'wave', c.source_id, c.player_id) for _ in range(2 if satisfied(c) else 1)))
    registry.register_behavior(PREFIX+'wave', lambda c: (DamageBatch(tuple(
        Damage(i, 2, c.source_id, DamageKind.SPELL) for i in characters(c, registry, 3-c.player_id))),))
    registry.register_behavior(PREFIX+'guard', lambda c: tuple(
        BuffBoardPresence(ref, c.player_id, 2, 2, c.source_id) for ref in neighbor_references(c)))
    for item in load_batch()['cards']:
        raw = item['record']; cid = raw['id']; kind = CardType(raw['type'].lower())
        kwargs = (dict(on_play=PREFIX+'blasphemy', spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')))
            if cid == BLASPHEMY else dict(attack=raw['attack'], health=raw['health'],
                battlecry=PREFIX+'guard', deathrattle=PREFIX+'guard'))
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_hand_cost_rank_profile(HandCostRankProfile(BLASPHEMY))
