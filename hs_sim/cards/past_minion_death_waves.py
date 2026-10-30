"""Lord Godfrey's original minion Battlecry, with ordinary death-wave settlement."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.minion_damage_waves import RepeatBattlecryMinionDamage
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-minion-death-waves-v1.json'
BATCH_HASH='81a515603ec84fb3cd4f71f6eceed6e2a19ab9cf11827ac1cab9529ba1ee0b13'
GODFREY, = ROOTS = ('GIL_825',)
DEPENDENCIES = EXISTING = ()
EVIDENCE = ('MIS_701',)
PREFIX = 'cards.past_minion_death_waves.'


def make_definition(raw):
    if (raw['id'] != GODFREY or raw['type'] != 'MINION' or
            any(type(raw[k]) is not int for k in ('cost', 'attack', 'health'))):
        raise TargetValidationError('Original Godfrey consumer lost its complete physical minion face')
    return CardDefinition(raw['id'], raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry=PREFIX+GODFREY,
        metadata=metadata_from_record(raw))


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            d['dependencies'] or d['existing_dependencies'] or
            tuple(x['record']['id'] for x in d['evidence_only']) != EVIDENCE or
            len(d['official_observations']) != 4 or any(d[k] for k in ('complete_past_source_bound',
                'new_standard_roots', 'membership_uses_executable_coverage', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Original Godfrey changed complete roles or claimed full source support')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for key in ('cards', 'evidence_only') for x in d[key]):
        raise TargetValidationError('Original Godfrey changed a complete original source row')
    path = ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest() != d['full_reference_sha256']:
        raise TargetValidationError('Original Godfrey changed the full past reference')
    ref = json.loads(path.read_text(encoding='utf8'))
    rows = {x['record']['id']: x['record'] for x in ref['candidate_records']}
    if (len(ref['candidate_ids']) != 732 or d['original_candidate_ids'] != ref['candidate_ids'] or
            any(x['record'] != rows[x['record']['id']] for x in d['cards'])):
        raise TargetValidationError('Original Godfrey cropped the complete original source domain')
    return d


def register_past_minion_death_waves(registry):
    d = load_batch()
    prepared = []
    for row in d['cards']:
        card = make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card)) != row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card))) != row['pool_card_sha256']):
            raise TargetValidationError('Original Godfrey cannot replace another registered face')
        registry._validate_card(card)
        prepared.append(card)
    def battlecry(c):
        if (c.battlecry is None or c.battlecry.payload.behavior_id != PREFIX+GODFREY or
                (c.battlecry.source_id, c.battlecry.player_id) != (c.source_id, c.player_id)):
            raise UnsupportedDefinitionError('Godfrey requires its actual accepted original Battlecry')
        return (RepeatBattlecryMinionDamage(c.battlecry.id, 2),)
    registry.register_behavior(PREFIX+GODFREY, battlecry)
    for card in prepared:
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
