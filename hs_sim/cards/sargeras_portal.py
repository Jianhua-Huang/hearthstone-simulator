"""Sargeras opens an autonomous untouchable portal; native skills use its link."""
import hashlib, json
from pathlib import Path

from hs_sim.engine.effects import InvokeBehavior
from hs_sim.engine.model import (ActivatedAbilitySpec, BoardPresenceReference, CardDefinition,
    CardType, EndTurnSpec, Keyword, PassiveBoardObjectSpec, SummonStats, TriggerSpec)
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.passive_objects import InstallPassiveObject, UpgradePassiveObject, bound_object, units
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/sargeras-portal-v1.json'
BATCH_HASH = '8d34898449f8462662630a73b94bd083e2f4c9a2c3cc735d55f3361e06a244f4'
SARGERAS, PORTAL, INFERNAL, IMP = 'TTN_960', 'TTN_960t', 'TTN_960t5', 'TTN_960t6'
SKILLS = ('TTN_960t2', 'TTN_960t3', 'TTN_960t4')
ROOTS = (SARGERAS,); DEPENDENCIES = (PORTAL, IMP) + SKILLS; COLLECTIBLE_ROOTS = ()
EXISTING_DEPENDENCIES = (INFERNAL,)
EVIDENCE = ('TTN_960t4e', 'TTN_960t4e2')
PREFIX = 'cards.sargeras_portal.'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or
            tuple(r['record']['id'] for r in d['cards']) != ROOTS or
            tuple(r['record']['id'] for r in d['dependencies']) != DEPENDENCIES or
            tuple(r['record']['id'] for r in d['evidence_only']) != EVIDENCE or
            tuple(r['record']['id'] for r in d['existing_dependencies']) != EXISTING_DEPENDENCIES or
            tuple(d['choice_only_ids']) != SKILLS or tuple(d['new_token_ids']) != (IMP,) or
            tuple(d['passive_object_ids']) != (PORTAL,) or len(d['official_observations']) != 14 or
            any(d[k] for k in ('source_scope_bound', 'formal_pool_complete',
                'cn_calibrated', 'real_excavate_profile_bound')) or
            any(canonical_digest(r['record']) != r['record_sha256']
                for key in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only') for r in d[key])):
        raise TargetValidationError('Sargeras requires complete original portal, token and native descriptor roles')
    for ref in d['references']:
        if hashlib.sha256((ROOT / ref['path']).read_bytes()).hexdigest() != ref['sha256']:
            raise TargetValidationError('Sargeras changed the complete original Titan inventory')
    return d


def register_sargeras_portal(registry):
    d = load_batch(); prepared = []
    bodies = {SARGERAS: (9, 6, 12), PORTAL: (11, None, 1), INFERNAL: (6, 6, 6), IMP: (2, 3, 2)}
    for row in d['cards'] + d['dependencies'] + d['existing_dependencies']:
        raw = row['record']; cid = raw['id']; kind = CardType[raw['type']]; extra = {}
        if cid in registry.cards and cid not in EXISTING_DEPENDENCIES:
            raise TargetValidationError('Sargeras cannot overwrite an existing definition')
        if cid in bodies:
            if kind != CardType.MINION or (raw['cost'], raw['attack'], raw['health']) != bodies[cid]:
                raise TargetValidationError('Sargeras changed a complete original physical body')
            if cid == SARGERAS:
                if not raw['collectible'] or raw['tags'].get('TITAN') != 1 or raw['tags'].get('BATTLECRY') != 1:
                    raise TargetValidationError('Sargeras lost its original Titan or Battlecry')
                extra.update(keywords=(Keyword.TITAN,), battlecry=PREFIX + 'open', activated_abilities=tuple(
                    ActivatedAbilitySpec(skill, PREFIX + skill, card_id=skill) for skill in SKILLS))
            elif cid == PORTAL:
                if raw['collectible'] or raw['tags'].get('UNTOUCHABLE') != 1 or raw['tags'].get('HIDE_STATS') != 1:
                    raise TargetValidationError('The portal requires its real untouchable carrier')
                extra.update(corpse_value=0, interactable=PassiveBoardObjectSpec(PREFIX + 'imps', SARGERAS, EVIDENCE[1]),
                    triggers=(TriggerSpec('turn_ended', PREFIX + 'imps', EndTurnSpec()),))
            elif raw['collectible'] or raw['tags'].get('CARDRACE') != 15:
                raise TargetValidationError('Portal summon dependencies must remain noncollectible Demons')
        else:
            if kind != CardType.SPELL or raw['cost'] is not None or raw['collectible']:
                raise TargetValidationError('Sargeras skills require nonphysical zero-cost descriptors')
            extra['choice_only'] = True
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'] or 0, attack=raw['attack'] or 0,
            health=raw['health'] or 0, metadata=metadata_from_record(raw), **extra)
        registry._validate_card(card)
        if cid not in SKILLS and cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Sargeras changed original printed pool metadata')
        if cid in EXISTING_DEPENDENCIES:
            if registry.card(cid) != card:
                raise TargetValidationError('Sargeras changed an already implemented Infernal dependency')
            continue
        prepared.append(card)
    if any(r['record']['type'] != 'ENCHANTMENT' for r in d['evidence_only']):
        raise TargetValidationError('Portal evidence enchantments are not physical executable faces')

    def summon(c, cid):
        amount = units(registry, c.source)
        material = SummonEntryMaterial(cid,
            stats=SummonStats(health=registry.card(cid).health + 2 * amount) if amount else None,
            keywords=(Keyword.TAUNT,) if amount else ())
        effect = SummonByCard(c.player_id, (material,), SummonCause.capture(c))
        return (effect, effect)

    def skill(c, skill_id):
        portal = bound_object(c.state, registry, c.source, c.player_id, PORTAL)
        if portal is None:
            return ()
        if skill_id == SKILLS[0]:
            refs = tuple(MinionReference.capture(c.state.entities[i]) for p in (1, 2)
                for i in minions(c, registry, p) if i != c.source_id)
            return (RemoveFromGame(refs, c.source_id),) if refs else ()
        if skill_id == SKILLS[1]:
            return (InvokeBehavior(PREFIX + 'infernal', portal.id, c.player_id),)
        return (UpgradePassiveObject(BoardPresenceReference.capture(c.state, portal.id), c.source_id),)

    registry.register_behavior(PREFIX + 'open', lambda c: (
        InstallPassiveObject(c.player_id, PORTAL, MinionReference.capture(c.source)),))
    registry.register_behavior(PREFIX + 'imps', lambda c: summon(c, IMP))
    registry.register_behavior(PREFIX + 'infernal', lambda c: summon(c, INFERNAL))
    for skill_id in SKILLS:
        registry.register_behavior(PREFIX + skill_id, lambda c, sid=skill_id: skill(c, sid))
    for card in prepared:
        registry.register_card(card)
        if card.id not in SKILLS and card.id not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
