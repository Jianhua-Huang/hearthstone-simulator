"""N'Zoth's four real skills compose existing discovery/resurrection/Deathrattles."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch, GrantDeathrattle, TriggerDeathrattles
from hs_sim.engine.model import (ActivatedAbilitySpec, CardDefinition, CardType, DamageKind,
    Keyword, PlayerSummonCountCostSpec, TargetMode, TargetSpec)
from hs_sim.engine.player_summon_count_costs import DEATHRATTLE_PROFILE
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery, Resurrect
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_017'
CALL, ARMY, DOMAIN, CONTROL = 'BE_017t3', 'BE_017t5', 'BE_017t6', 'BE_017t4'
SKILLS = (CALL, ARMY, DOMAIN, CONTROL)
PREFIX = 'cards.nzoth.'
DEATH = PREFIX+'granted_deathrattle'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/nzoth-v1.json'
BATCH_HASH = '4181e1d2691558c7c3b2c62e1957753bcf016dc966e57f6c7a6ad67452f8459e'
DISCOVERY = PoolQuery(kinds=(CardType.MINION,), min_cost=5, collectible=True, class_mode="current", deathrattle=True)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != (CARD,) or
            tuple(r['record']['id'] for r in data['dependencies']) != SKILLS or
            any(data[k] for k in ('existing_dependencies', 'evidence_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['cards']+data['dependencies']) or
            data['official_faces_verified'] != 10):
        raise TargetValidationError('Nzoth requires five complete original records and ten full primary faces')
    return data


def register_nzoth_card(registry):
    batch = load_batch(); raw = batch['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible'],
            raw['tags'].get('OLD_GOD')) != ('MINION', 15, 5, 7, True, 1):
        raise TargetValidationError('Nzoth lost its actual fifteen-cost 5/7 Old God face')
    def call(c):
        return (DiscoverFromPool(c.player_id, 'constructed.cards', DISCOVERY, source_id=c.source_id,
            destination='board', cause=SummonCause.capture(c)),)
    def army(c):
        return (Resurrect(c.player_id, 4,
            DeathQuery(has_deathrattle=True, deathrattle_basis='printed'), distinct='card',
            source_id=c.source_id, cause=SummonCause.capture(c)),)
    def domain(c):
        return (GrantDeathrattle(c.target_id, DEATH, c.source_id),)
    def control(c):
        return (TriggerDeathrattles(c.target_id, c.source_id, times=2),)
    def death(c):
        targets = tuple(c.state.entities[i] for i in c.state.players[3-c.player_id].board)
        return (DamageBatch(tuple(Damage(e.id, 2, c.source_id, DamageKind.MINION_ABILITY)
            for e in targets if e.kind == CardType.MINION and e.active and e.health > 0 and not e.doomed)),)
    registry.register_behavior(DEATH, death)
    for cid, body in ((CALL, call), (ARMY, army), (DOMAIN, domain), (CONTROL, control)):
        registry.register_behavior(PREFIX+cid, body)
    targeting = TargetSpec(TargetMode.REQUIRED, kinds=(CardType.MINION,), relation='friendly', exclude_source=True)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=15, attack=5, health=7,
        keywords=(Keyword.OLD_GOD,), metadata=metadata_from_record(raw),
        player_summon_count_cost=PlayerSummonCountCostSpec(DEATHRATTLE_PROFILE),
        activated_abilities=tuple(ActivatedAbilitySpec(cid, PREFIX+cid, card_id=cid,
            targeting=targeting if cid in (DOMAIN, CONTROL) else None) for cid in SKILLS))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    for entry in batch['dependencies']:
        r = entry['record']
        registry.register_card(CardDefinition(r['id'], r['name'], CardType.SPELL, cost=0,
            choice_only=True, metadata=metadata_from_record(r)))
