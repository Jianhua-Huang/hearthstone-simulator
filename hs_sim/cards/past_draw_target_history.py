"""Four real past consumers of ordinary draws, private choices and CAST facts."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.deathrattle_memory import actual_target_facts
from hs_sim.engine.inspire import is_inspire
from hs_sim.engine.model import CardDefinition, CardType, Keyword, Rarity, TriggerSpec, Zone
from hs_sim.engine.physical_draw_chains import DrawBattlecryUntilNonDragon
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_history import SpellHistoryQuery, spell_history_candidates
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import ChooseFromZone, CopyCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record


ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-draw-target-history-v1.json'
BATCH_HASH = 'd185427e0a8a4f9f418cb140550993b1e0ea1f49879499c83bcba9e5c50411c8'
WRATHION, LAZUL, LIADRIN, PALETRESS = ROOTS = ('CFM_806', 'DAL_729', 'BT_334', 'AT_018')
DEPENDENCIES = EXISTING = ()
EVIDENCE = ('MIS_701',)
PREFIX = 'cards.past_draw_target_history.'
LEGENDARIES = PoolQuery(kinds=(CardType.MINION,), collectible=True, rarities=(Rarity.LEGENDARY,))


def make_definition(raw):
    cid = raw['id']
    if cid not in ROOTS or raw['type'] != 'MINION' or any(type(raw[k]) is not int for k in ('cost','attack','health')):
        raise TargetValidationError('Past draw/history consumer requires its complete physical minion face')
    return CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], battlecry=PREFIX+cid, metadata=metadata_from_record(raw),
        keywords=(Keyword.TAUNT,) if cid == WRATHION else (),
        triggers=(TriggerSpec('hero_power_used', PREFIX+'inspire'),) if cid == PALETRESS else ())


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            d['dependencies'] or d['existing_dependencies'] or
            tuple(x['record']['id'] for x in d['evidence_only']) != EVIDENCE or
            len(d['official_observations']) != 10 or any(d[k] for k in ('complete_past_source_bound',
                'new_standard_roots', 'membership_uses_executable_coverage', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Past draw/history consumer changed complete roles or claimed full support')
    if any(canonical_digest(x['record']) != x['record_sha256'] for key in ('cards','evidence_only') for x in d[key]):
        raise TargetValidationError('Past draw/history consumer changed a complete original row')
    path = ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest() != d['full_reference_sha256']:
        raise TargetValidationError('Past draw/history consumer changed its full past reference')
    ref = json.loads(path.read_text(encoding='utf8')); rows = {x['record']['id']:x['record'] for x in ref['candidate_records']}
    if len(ref['candidate_ids']) != 732 or d['original_candidate_ids'] != ref['candidate_ids'] or any(
            x['record'] != rows[x['record']['id']] for x in d['cards']):
        raise TargetValidationError('Past draw/history consumer cropped its complete past source')
    domain = d['complete_ordinary_legendary_domain']
    if (len(domain['complete_ordered_members']) != 178 or len(domain['members']) != 178 or
            not domain['membership_not_implementation_filter'] or any(
                canonical_digest(x['full_record']) != x['record_sha256'] for x in domain['members'])):
        raise TargetValidationError('Paletress changed its complete declared ordinary Legendary inventory')
    return d


def register_past_draw_target_history(registry):
    d = load_batch(); prepared = []
    for row in d['cards']:
        card = make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card)) != row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card))) != row['pool_card_sha256']):
            raise TargetValidationError('Past draw/history consumer cannot replace another full original face')
        registry._validate_card(card); prepared.append(card)

    def wrathion(c):
        if (c.battlecry is None or c.battlecry.payload.behavior_id != PREFIX+WRATHION or
                (c.battlecry.source_id, c.battlecry.player_id) != (c.source_id, c.player_id)):
            raise UnsupportedDefinitionError('Wrathion requires its actual accepted original Battlecry')
        return (DrawBattlecryUntilNonDragon(c.battlecry.id),)

    def liadrin(c):
        rows = spell_history_candidates(c.state, registry, c.player_id, SpellHistoryQuery(), c.source_id)
        return tuple(CopyCard(None, c.player_id, mode='base', source_id=c.source_id, cast_id=row.id)
            for row in rows if row.payload_started and not row.interrupted and any(
                fact.controller == c.player_id and fact.kind in (CardType.MINION, CardType.HERO) and
                fact.zone in (Zone.BOARD, Zone.HERO) for fact in actual_target_facts(row)))

    def legendary(c):
        return (SummonFromPool(c.player_id, 'constructed.minions', LEGENDARIES, c.source_id,
            cause=SummonCause.capture(c)),)

    registry.register_behavior(PREFIX+WRATHION, wrathion)
    registry.register_behavior(PREFIX+LAZUL, lambda c:(ChooseFromZone(c.player_id, 3-c.player_id, Zone.HAND,
        operation='copy_base', source_id=c.source_id, discovery=True, prompt='发现一张对手手牌的复制'),))
    registry.register_behavior(PREFIX+LIADRIN, liadrin)
    registry.register_behavior(PREFIX+PALETRESS, legendary)
    registry.register_behavior(PREFIX+'inspire', lambda c:legendary(c) if is_inspire(c.state,c.event,c.player_id) else ())
    for card in prepared:
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
