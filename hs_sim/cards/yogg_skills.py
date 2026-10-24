"""Four original Yogg abilities; controlled-turn Battlecry is a separate source."""
import json
from pathlib import Path

from hs_sim.engine.costs import local_cost, quote_unselected_cost
from hs_sim.engine.effects import Damage
from hs_sim.engine.model import (ActivatedAbilitySpec, CardDefinition, CardType, DamageKind,
    SpellRepeatSpec, TargetMode, TargetSpec)
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier
from hs_sim.engine.stored_pool_transforms import TransformStoredFromPool
from hs_sim.engine.zones import CardReference, DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = 'BE_009'
WITS, MADNESS, ASCENT, DOMAIN = SKILLS = tuple(ROOT+'t'+str(i) for i in range(1, 5))
PREFIX = 'cards.yogg_skills.'
COLLECTIBLE_ROOTS = ()
CHOICE_ONLY = SKILLS
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/yogg-skills-v1.json'
BATCH_HASH = '0a3f416ae84ce22a9359027ab2022dce057d9a6aae2ffddc5e0973d663d444f5'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['choice_only'] + data['evidence_only']
    if (canonical_digest(data) != BATCH_HASH or tuple(row['record']['id'] for row in rows) != (*SKILLS, ROOT) or
            any(data[key] for key in ('cards', 'dependencies', 'existing_dependencies', 'skipped',
                'display_normalizations')) or data['numeric_normalizations'] != {cid: {'cost': 0} for cid in SKILLS} or
            data['source_root_unimplemented'] is not True or len(data['official_observations']) != 10 or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Yogg skills require their complete original labels and separate pending root')
    dbfs = [row['record']['dbf_id'] for row in data['choice_only']]
    for observation in data['official_observations']:
        if observation['card_id'] == ROOT and observation['face']['childIds'] != dbfs:
            raise TargetValidationError('Yogg skills changed their actual complete parent child list')
    return data


def skill_specs():
    targeting = TargetSpec(TargetMode.REQUIRED, kinds=(CardType.HERO, CardType.MINION), relation='any')
    return tuple(ActivatedAbilitySpec(cid, PREFIX+cid, card_id=cid,
        targeting=targeting if cid == MADNESS else None) for cid in SKILLS)


def register_yogg_skills(registry):
    data = load_batch()

    def wits(c):
        return (AddSpellRepeatModifier(c.player_id, SpellRepeatSpec(2, 'any'), c.source_id,
            uses=1, expires_turn=c.state.turn, automatic=True),)

    def madness(c):
        return (Damage(c.target_id, 10, c.source_id, DamageKind.MINION_ABILITY),)

    def ascent(c):
        work = []
        # The whole original hand and both kinds of costs are quoted before
        # any transformation or notification can change a later recipient.
        for entity_id in c.state.players[c.player_id].hand:
            entity = c.state.entities[entity_id]
            if registry.card(entity.card_id).kind != CardType.SPELL:
                continue
            tier = quote_unselected_cost(c.state, registry, entity).amount + 3
            work.append(TransformStoredFromPool(CardReference.capture(entity), 'constructed.cards',
                PoolQuery(kinds=(CardType.SPELL,), collectible=True, min_cost=tier, max_cost=tier),
                c.source_id, retained_cost=local_cost(entity)[0]))
        return tuple(work)

    def domain(c):
        return (DrawMatching(c.player_id, PoolQuery(kinds=(CardType.SPELL,)), 'skip', count=5,
            selection='random', source_id=c.source_id),)

    for cid, body in zip(SKILLS, (wits, madness, ascent, domain)):
        registry.register_behavior(PREFIX+cid, body)
    for row in data['choice_only']:
        raw = row['record']
        if (raw['type'], raw['cost'], raw['collectible'], raw['tags'].get('HIDE_COST')) != ('SPELL', None, False, 1):
            raise TargetValidationError('Yogg skill labels require their original hidden-cost noncollectible faces')
        registry.register_card(CardDefinition(raw['id'], raw['name'], CardType.SPELL, cost=0,
            choice_only=True, metadata=metadata_from_record(raw)))
