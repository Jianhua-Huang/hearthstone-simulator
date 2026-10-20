"""Two native Battlecries consume the existing frozen held-spell witnesses."""
import json
from pathlib import Path

from hs_sim.engine.effects import CopyMinion, Damage, DamageBatch
from hs_sim.engine.held_spells import DIFFERENT_PLAYED_SCHOOLS, different_played_schools, satisfied
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, DamageKind, HandProgressSpec, Keyword, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

DREAD, SAGE = 'BE_171', 'BE_303'
PREFIX = 'cards.held_spell_schools.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/held-spell-school-cards-v1.json'
BATCH_HASH = '7c8226864d608a21991a08cd5fbae377ecd8a2f3c12db69da8f690e604b4a195'
PROGRESS = HandProgressSpec('spell_cast', goal=2, condition_id=DIFFERENT_PLAYED_SCHOOLS)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (DREAD, SAGE) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'])):
        raise TargetValidationError('Held-school cards require complete reviewed original records')
    return data


def register_held_spell_school_cards(registry):
    registry.register_trigger_condition(DIFFERENT_PLAYED_SCHOOLS, lambda c: different_played_schools(c, registry))
    def dread(c):
        if not satisfied(c): return ()
        if (c.source.zone != Zone.BOARD or not c.source.active or c.source.health <= 0 or c.source.doomed): return ()
        return (CopyMinion(BoardPresenceReference.capture(c.state, c.source_id), c.player_id,
            cause=SummonCause.capture(c)),)
    def sage(c):
        if not satisfied(c): return ()
        return (DamageBatch(tuple(Damage(eid, 4, c.source_id, DamageKind.MINION_ABILITY)
            for eid in characters(c, registry, 3-c.player_id))),)
    registry.register_behavior(PREFIX+'dread', dread)
    registry.register_behavior(PREFIX+'sage', sage)
    for item in load_batch()['cards']:
        raw = item['record']; cid = raw['id']
        expected = (4, 4, 5) if cid == DREAD else (5, 3, 3)
        if (raw['type'] != 'MINION' or (raw['cost'], raw['attack'], raw['health']) != expected or
                raw['tags'].get('BATTLECRY') != 1):
            raise TargetValidationError('Held-school Battlecry lost its original complete face')
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
            keywords=(Keyword.TAUNT,) if cid == DREAD else (), hand_progress=PROGRESS,
            battlecry=PREFIX+('dread' if cid == DREAD else 'sage'), metadata=metadata_from_record(raw))
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
