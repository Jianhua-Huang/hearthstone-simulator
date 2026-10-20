"""Real current-turn friendly deaths through native prices and death queries."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, InvokeBehavior, RandomForceAttack
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Keyword, MinionDeathCostSpec, TargetSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_sources import DeathQuery, death_query_candidates
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters

CAVERN, BEAST = 'BE_877', 'BE_564'
ROOTS = COLLECTIBLE_ROOTS = (CAVERN, BEAST)
DEPENDENCIES = ()
PROFILE = 'cost.minion-deaths-friendly-turn-zero-v1'
PREFIX = 'cards.black_empire_death_conditions.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/black-empire-death-conditions-v1.json'
BATCH_HASH = 'fce72dc20241c2d3751bffcf8f702086de0614fb93a9856726576aad387fc13e'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != ROOTS or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['cards'])):
        raise TargetValidationError('Current-turn death consumers require both complete original faces')
    return data


def register_black_empire_death_condition_cards(registry):
    def beast(c):
        if not living_source(c): return ()
        deaths = death_query_candidates(registry, c.player_id,
            DeathQuery(min_turn=c.state.turn, max_turn=c.state.turn), tuple(c.state.death_history), None)
        if not deaths: return ()
        return (RandomForceAttack((c.source_id,), characters(c, registry, 3-c.player_id), c.source_id),)
    registry.register_behavior(PREFIX+'cavern', lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL),))
    registry.register_behavior(PREFIX+'beast', lambda c: (InvokeBehavior(PREFIX+'beast_now',
        c.source_id, c.player_id, c.target_id, None if c.play is None else c.play.id),))
    registry.register_behavior(PREFIX+'beast_now', beast)
    for row in load_batch()['cards']:
        raw = row['record']; cid = raw['id']; fields = {}
        if cid == CAVERN:
            fields.update(minion_death_cost=MinionDeathCostSpec(PROFILE), keywords=(Keyword.LIFESTEAL,),
                spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
                on_play=PREFIX+'cavern', targeting=TargetSpec())
        else: fields.update(attack=raw['attack'], health=raw['health'], battlecry=PREFIX+'beast')
        card = CardDefinition(cid, raw['name'], CardType(raw['type'].lower()), cost=raw['cost'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
