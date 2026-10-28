"""Unleashed Yogg composes native control, enemy-side combat, fill and CAST."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.effects import ChangeControl
from hs_sim.engine.forced_attack_sequences import ForcePlayerMinionsAttackEachOther
from hs_sim.engine.model import (ActivatedAbilitySpec, CardDefinition, CardType, Keyword,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.zones import FillHandWithCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/yogg-unleashed-v1.json'
BATCH_HASH = 'f2e9972b91790ed1711ba475a45442404e8f6ce7cb12726b4bc2da059491fa92'
YOGG, TENDRIL = 'YOG_516', 'YOG_514'
SKILLS = ('YOG_516t', 'YOG_516t2', 'YOG_516t3')
ROOTS = (YOGG,); DEPENDENCIES = SKILLS; EXISTING_DEPENDENCIES = (TENDRIL,)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.yogg_unleashed.'
POOL = 'constructed.cards'
QUERY = PoolQuery(kinds=(CardType.SPELL,), collectible=True)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or
            tuple(r['record']['id'] for r in d['cards']) != ROOTS or
            tuple(r['record']['id'] for r in d['dependencies']) != SKILLS or
            tuple(r['record']['id'] for r in d['existing_dependencies']) != EXISTING_DEPENDENCIES or
            tuple(r['record']['id'] for r in d['evidence_only']) != ('YOG_516e',) or
            tuple(d['choice_only_ids']) != SKILLS or len(d['official_observations']) != 8 or
            any(d[k] for k in ('new_token_ids', 'source_scope_bound', 'formal_pool_complete',
                'cn_calibrated', 'real_excavate_profile_bound')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for key in
                ('cards', 'dependencies', 'existing_dependencies', 'evidence_only') for r in d[key])):
        raise TargetValidationError('Unleashed Yogg requires complete original native faces and existing Tendril')
    for ref in d['references']:
        if hashlib.sha256((ROOT / ref['path']).read_bytes()).hexdigest() != ref['sha256']:
            raise TargetValidationError('Unleashed Yogg changed an original complete Titan or Tendril reference')
    return d


def register_yogg_unleashed(registry):
    d = load_batch(); prepared = []
    for row in d['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_metadata_sha256']):
            raise TargetValidationError('Unleashed Yogg changed the actual existing Tendril implementation')
    for row in d['cards'] + d['dependencies']:
        raw = row['record']; cid = raw['id']; kind = CardType[raw['type']]; extra = {}
        if cid in registry.cards:
            raise TargetValidationError('Unleashed Yogg cannot overwrite a reviewed definition')
        if cid == YOGG:
            if (kind != CardType.MINION or (raw['cost'], raw['attack'], raw['health']) != (9, 7, 5) or
                    not raw['collectible'] or raw['tags'].get('CLASS') != 12 or raw['tags'].get('TITAN') != 1):
                raise TargetValidationError('Unleashed Yogg lost its real neutral nine-mana 7/5 Titan face')
            extra.update(keywords=(Keyword.TITAN,), activated_abilities=tuple(ActivatedAbilitySpec(
                skill, PREFIX + skill, card_id=skill, targeting=TargetSpec(zones=(Zone.BOARD,),
                    kinds=(CardType.MINION,), relation='enemy') if skill == SKILLS[0] else None) for skill in SKILLS),
                triggers=(TriggerSpec('minion_ability_used', PREFIX + 'after'),))
        else:
            if kind != CardType.SPELL or raw['cost'] is not None or raw['collectible'] or raw['tags'].get('HIDE_STATS') != 1:
                raise TargetValidationError('Unleashed Yogg skills require their nonphysical zero-cost descriptors')
            extra['choice_only'] = True
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'] or 0, attack=raw['attack'] or 0,
            health=raw['health'] or 0, metadata=metadata_from_record(raw), **extra)
        registry._validate_card(card)
        if cid == YOGG and cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Unleashed Yogg changed complete original printed pool metadata')
        prepared.append(card)

    def after(c):
        event = c.event
        if (event is None or event.kind != 'minion_ability_used' or event.source_id != c.source_id or
                dict(event.data).get('ability_id') not in SKILLS):
            return ()
        return (CastFromPool(c.player_id, POOL, QUERY, count=2, source_id=c.source_id,
            replacement=True, refresh='per_cast', targeting='random', choices='random', while_source_in_play=False),)

    registry.register_behavior(PREFIX + SKILLS[0], lambda c: (ChangeControl(c.target_id, c.player_id),))
    registry.register_behavior(PREFIX + SKILLS[1], lambda c: (ForcePlayerMinionsAttackEachOther(3 - c.player_id),))
    registry.register_behavior(PREFIX + SKILLS[2], lambda c: (FillHandWithCard(c.player_id, TENDRIL, c.source_id),))
    registry.register_behavior(PREFIX + 'after', after)
    for card in prepared:
        registry.register_card(card)
        if card.id not in SKILLS and card.id not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
