"""Teron's actual original friendly destruction, frozen native memory and base resummons."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.destroyed_group_memory import DestroyForDeathrattleGroup, ResummonDestroyedGroups, RESUMMON_GRANT
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import CardDefinition, CardType, NativeDeathrattleSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-destroyed-group-memory-v1.json'
BATCH_HASH='ae9260685c66490020481e0416128fa7f1345d2843e6b8914d659f4fa1d93481'
TERON, = ROOTS = ('BT_126',)
DEPENDENCIES = EXISTING = ()
EVIDENCE = ('BT_126e', 'BT_126e2', 'MIS_701')
PREFIX = 'cards.past_destroyed_group_memory.'
SPEC = NativeDeathrattleSpec('destroyed_group')


def make_definition(raw):
    if (raw['id'] != TERON or raw['type'] != 'MINION' or
            any(type(raw[k]) is not int for k in ('cost', 'attack', 'health'))):
        raise TargetValidationError('Teron lost its complete original physical minion face')
    return CardDefinition(raw['id'], raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], battlecry=PREFIX+'battlecry', deathrattle=PREFIX+'deathrattle',
        native_deathrattle=SPEC, metadata=metadata_from_record(raw))


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            d['dependencies'] or d['existing_dependencies'] or
            tuple(x['record']['id'] for x in d['evidence_only']) != EVIDENCE or
            len(d['official_observations']) != 4 or canonical_digest(d['actual_resummon_grant']) != canonical_digest(asdict(RESUMMON_GRANT)) or
            any(d[k] for k in ('complete_past_source_bound', 'new_standard_roots',
                'membership_uses_executable_coverage', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Teron changed complete source roles or claimed a full past pool')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for key in ('cards', 'evidence_only') for x in d[key]):
        raise TargetValidationError('Teron changed an original complete source row')
    path = ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest() != d['full_reference_sha256']:
        raise TargetValidationError('Teron changed the complete past reference')
    ref = json.loads(path.read_text(encoding='utf8')); rows = {x['record']['id']: x['record'] for x in ref['candidate_records']}
    if (len(ref['candidate_ids']) != 732 or d['original_candidate_ids'] != ref['candidate_ids'] or
            any(x['record'] != rows[x['record']['id']] for x in d['cards'])):
        raise TargetValidationError('Teron cropped the complete original past source')
    return d


def register_past_destroyed_group_memory(registry):
    d = load_batch(); prepared = []
    for row in d['cards']:
        card = make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card)) != row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card))) != row['pool_card_sha256']):
            raise TargetValidationError('Teron cannot replace another registered original face')
        registry._validate_card(card); prepared.append(card)
    def battlecry(c):
        if (c.battlecry is None or c.battlecry.payload.behavior_id != PREFIX+'battlecry' or
                (c.battlecry.source_id, c.battlecry.player_id) != (c.source_id, c.player_id)):
            raise UnsupportedDefinitionError('Teron requires its actual original accepted Battlecry')
        source = c.source
        reference = MinionReference.capture(source) if source.zone == Zone.BOARD and source.kind == CardType.MINION else None
        identities = tuple(a.id for a in active_abilities(source, 'deathrattle')
            if reference is not None and a.deathrattle_memory is not None and a.deathrattle_memory.spec == SPEC)
        return (DestroyForDeathrattleGroup(c.battlecry.id, reference, identities),)
    def deathrattle(c):
        memory = None if c.deathrattle is None else c.deathrattle.ability.deathrattle_memory
        if memory is None or memory.spec != SPEC:
            raise UnsupportedDefinitionError('Teron requires its actual frozen destroyed-group Deathrattle memory')
        return (ResummonDestroyedGroups(c.deathrattle.id),)
    registry.register_behavior(PREFIX+'battlecry', battlecry)
    registry.register_behavior(PREFIX+'deathrattle', deathrattle)
    for card in prepared:
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
