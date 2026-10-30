"""Actual Msshi'fn Prime Choose One and the three named Fungal bodies."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.choose_one import normalize
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.model import CardDefinition, CardType, ChooseBranch, ChooseOneSpec, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/msshifn-prime-v1.json'
BATCH_HASH = 'f0fe96ff60a859265d60b2dd9106d499f5282e43fb16d9692c933a74931a7fc3'
MSSHIFN, PRIME = 'BT_136', 'BT_136t'
TAUNT_OPTION, RUSH_OPTION = CHOICES = ('BT_136ta', 'BT_136tb')
GUARDIAN, BRUISER, GARGANTUAN = TOKENS = ('BT_136tt', 'BT_136tt2', 'BT_136tt3')
ROOTS = (MSSHIFN,)
DEPENDENCIES = (PRIME, *CHOICES, *TOKENS)
PHYSICAL = (MSSHIFN, PRIME, *TOKENS)
EXISTING = ()
EVIDENCE = ('MIS_701',)
PREFIX = 'cards.msshifn_prime.'


def make_definition(raw):
    cid = raw['id']
    if cid in CHOICES:
        if raw['type'] != 'SPELL' or raw['collectible'] or type(raw['cost']) is not int:
            raise TargetValidationError('Msshi fn choice requires its complete original presentation face')
        return CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'], choice_only=True,
            metadata=metadata_from_record(raw))
    if cid not in PHYSICAL or raw['type'] != 'MINION' or any(type(raw[k]) is not int for k in ('cost', 'attack', 'health')):
        raise TargetValidationError('Msshi fn lost a complete original physical minion')
    kwargs = dict(keywords=tuple(k for k in (Keyword.TAUNT, Keyword.RUSH) if raw['tags'].get(k.name) == 1))
    if cid == MSSHIFN: kwargs['deathrattle'] = PREFIX+'shuffle'
    if cid == PRIME:
        kwargs['choose_one'] = ChooseOneSpec((ChooseBranch(TAUNT_OPTION, '姆希菲防护', PREFIX+'guardian'),
            ChooseBranch(RUSH_OPTION, '姆希菲出击', PREFIX+'bruiser')),
            ChooseBranch('both', '两者兼得', PREFIX+'gargantuan'))
    return normalize(CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], metadata=metadata_from_record(raw), **kwargs))


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES or d['existing_dependencies'] or
            tuple(x['record']['id'] for x in d['evidence_only']) != EVIDENCE or d['actual_choice_only_ids'] != list(CHOICES) or
            d['actual_physical_dependency_ids'] != [PRIME, *TOKENS] or len(d['official_observations']) != 12 or
            any(d[k] for k in ('complete_past_source_bound', 'new_standard_roots', 'membership_uses_executable_coverage',
                'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Msshi fn changed original roles or claimed a complete past pool')
    if any(canonical_digest(x['record']) != x['record_sha256'] for key in ('cards', 'dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('Msshi fn changed a full original source row')
    by_id = {x['record']['id']: x['record'] for x in d['cards']+d['dependencies']}
    for locale in ('zh_CN', 'en_US'):
        links = d['complete_primary_parent_links'][locale]
        if (links['root']['id'] != by_id[MSSHIFN]['dbf_id'] or by_id[PRIME]['dbf_id'] not in links['root']['childIds'] or
                links['prime']['id'] != by_id[PRIME]['dbf_id'] or links['prime']['parentId'] != by_id[MSSHIFN]['dbf_id']):
            raise TargetValidationError('Msshi fn changed its actual named Prime relationship')
    path = ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest() != d['full_reference_sha256']:
        raise TargetValidationError('Msshi fn changed its complete past reference')
    ref = json.loads(path.read_text(encoding='utf8')); rows = {x['record']['id']: x['record'] for x in ref['candidate_records']}
    if len(ref['candidate_ids']) != 732 or d['original_candidate_ids'] != ref['candidate_ids'] or d['cards'][0]['record'] != rows[MSSHIFN]:
        raise TargetValidationError('Msshi fn cropped the complete original past source')
    return d


def register_msshifn_prime_cards(registry):
    d = load_batch(); prepared = []
    for row in d['cards']+d['dependencies']:
        card = make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card)) != row['definition_sha256'] or
                (not card.choice_only and canonical_digest(asdict(PoolCard.from_definition(card))) != row['pool_card_sha256'])):
            raise TargetValidationError('Msshi fn cannot replace an original registered face')
        registry._validate_card(card); prepared.append(card)
    registry.register_behavior(PREFIX+'shuffle', lambda c: shuffled(c, (AddToDeck(c.player_id, PRIME, source_id=c.source_id),)))
    for name, cid in (('guardian', GUARDIAN), ('bruiser', BRUISER), ('gargantuan', GARGANTUAN)):
        def summon(c, cid=cid):
            return (SummonByCard(c.player_id, (SummonEntryMaterial(cid),), SummonCause.capture(c)),)
        registry.register_behavior(PREFIX+name, summon)
    for card in prepared:
        registry.register_card(card)
        if not card.choice_only: registry.register_pool_card(PoolCard.from_definition(card))
