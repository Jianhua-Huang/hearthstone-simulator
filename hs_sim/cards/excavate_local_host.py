"""Fixed complete local treasure tables and the real Cryopreservation producer."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.effects import Freeze
from hs_sim.engine.excavate import Excavate, ExcavationClass, ExcavationProfile, PLAYABLE_CLASSES
from hs_sim.engine.model import CardClass, CardDefinition, CardType, SpellSchool, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/excavate-local-host-v1.json'
BATCH_HASH = '976d5e11da6512025d2969cd35647c8ffa526189b2f78f3627c43f6ed24ac42d'
POLICY = 'cn37-local-full-excavate-v1'
SPELL = 'WW_009'
PREFIX = 'cards.excavate_local_host.'
DEPENDENCIES = (SPELL,)
COLLECTIBLE_ROOTS = ()
CLASS_IDS = {1:CardClass.DEATH_KNIGHT, 4:CardClass.MAGE, 5:CardClass.PALADIN,
    7:CardClass.ROGUE, 8:CardClass.SHAMAN, 9:CardClass.WARLOCK, 10:CardClass.WARRIOR}
REFERENCE_PATHS = ('data/cards/excavate-shared-treasures-v1.json',
    'data/cards/azerite-hawk-domain-v1.json', 'data/cards/azerite-reward-domains-v1.json')


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or
            d['cards'] or d['new_standard_roots'] or
            tuple(row['record']['id'] for row in d['dependencies']) != DEPENDENCIES or
            len(d['existing_dependencies']) != 25 or len(d['official_observations']) != 52 or
            d['source_scope_bound'] is not True or d['real_excavate_profile_bound'] is not True or
            d['formal_pool_complete'] is not False or d['cn_calibrated'] is not False or
            tuple(ref['path'] for ref in d['references']) != REFERENCE_PATHS):
        raise TargetValidationError('Excavate host requires its full local source and explicit evidence boundaries')
    for ref in d['references']:
        if hashlib.sha256((ROOT/ref['path']).read_bytes()).hexdigest() != ref['sha256']:
            raise TargetValidationError('Excavate host changed a complete original treasure or reward-domain reference')
    source = json.loads((ROOT/REFERENCE_PATHS[0]).read_text(encoding='utf8'))
    rows = {row['record']['id']: row for key in ('cards', 'existing_dependencies', 'evidence_only') for row in source[key]}
    if (d['inventory'] != dict(source['inventory'], runtime_bound=True) or
            [row['record']['id'] for row in d['existing_dependencies']] != source['inventory']['member_ids'] or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                row['record'] != rows[row['record']['id']]['record']
                for row in d['dependencies'] + d['existing_dependencies'])):
        raise TargetValidationError('Excavate host cannot crop, reorder, reweight or reinterpret its original full inventory')
    return d


def _require_existing(registry, data):
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_metadata_sha256']):
            raise TargetValidationError('Excavate host requires each complete original treasure body: ' + cid)


def _definition(data):
    row, = data['dependencies']; raw = row['record']
    if (raw['id'] != SPELL or raw['type'] != 'SPELL' or raw['cost'] != 2 or not raw['collectible'] or
            row['spell_school'] != SpellSchool.FROST):
        raise TargetValidationError('Cryopreservation requires its complete original two-mana Frost face')
    return CardDefinition(SPELL, raw['name'], CardType.SPELL, cost=raw['cost'],
        metadata=metadata_from_record(raw), spell_school=SpellSchool.FROST, on_play=PREFIX+SPELL,
        targeting=TargetSpec(zones=(Zone.HERO, Zone.BOARD), kinds=(CardType.HERO, CardType.MINION), relation='enemy'))


def register_cryopreservation(registry):
    data = load_batch(); _require_existing(registry, data); card = _definition(data)
    if SPELL in registry.cards or SPELL in registry.pool_cards:
        raise TargetValidationError('Cryopreservation cannot overwrite an existing definition or metadata')
    registry.register_behavior(PREFIX+SPELL, lambda c: (Freeze(c.target_id, c.source_id), Excavate(c.player_id, c.source_id)))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))


def local_pools(registry, context):
    data = load_batch(); _require_existing(registry, data)
    expected = _definition(data)
    if registry.card(SPELL) != expected or registry.pool_card(SPELL) != PoolCard.from_definition(expected):
        raise TargetValidationError('Excavate host requires the real original Cryopreservation producer')
    inventory = data['inventory']; version = POLICY + '-' + BATCH_HASH
    pools = [PoolDefinition('excavate.tier'+str(tier['tier']), version, context.target_id, context.mode,
        tuple(PoolMember(cid, w) for cid, w in zip(tier['member_ids'], tier['weights'])),
        excluded_card_ids=tuple(tier['excluded_card_ids']), complete=True) for tier in inventory['shared_tiers']]
    pools.extend(PoolDefinition('excavate.'+CLASS_IDS[row['class_id']].value, version, context.target_id, context.mode,
        (PoolMember(row['card_id'], row['weight']),), complete=True) for row in inventory['class_rewards'])
    return tuple(pools)


def profile(context):
    data = load_batch()
    rewards = {CLASS_IDS[row['class_id']] for row in data['inventory']['class_rewards']}
    if {cls.value for cls in PLAYABLE_CLASSES-rewards} != set(data['inventory']['classes_without_legendary']):
        raise TargetValidationError('Excavate host requires explicit rules for all eleven classes')
    return ExcavationProfile('excavate', POLICY+'-'+BATCH_HASH, context.target_id, context.mode,
        ('excavate.tier1', 'excavate.tier2', 'excavate.tier3'), tuple(ExcavationClass(cls,
            'excavate.'+cls.value if cls in rewards else None) for cls in sorted(PLAYABLE_CLASSES)), complete=True)
