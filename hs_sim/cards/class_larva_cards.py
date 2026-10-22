"""Three Larva sources and their complete playable-class native Combo family."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import Buff, Damage, Draw, EquipWeapon, GainArmor, Heal, RandomBuff
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (
    CardDefinition, CardType, DamageKind, EndTurnSpec, HealingKind, Keyword,
    PLAYABLE_CARD_CLASSES, TargetMode, TargetSpec, TriggerSpec,
)
from hs_sim.engine.pools import (
    GenerateFromCandidates, PoolCard, PoolQuery, SummonFromCandidates, matches_metadata,
)
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .basic_hero_roles import TOTEMS as BASIC_TOTEMS
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/class-larva-cards-v2.json'
BATCH_HASH = 'f5cd2fcc7ba53353c12af8fc345c7cbcb2316dc5b40bceff61cadbb69c07cb04'
ROOTS = ('BE_720', 'BE_722', 'BE_724')
LARVAE = tuple(f'BE_720t{i}' for i in range(1, 12))
STRENGTH_TOTEM = 'CS2_058'
EXISTING = ('CS2_050', 'CS2_051', 'NEW1_009', 'CS2_082', 'CS2_101t', 'HERO_11bpt', 'CS2_052')
PREFIX = 'cards.class_larva.'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=False,
    class_mode='other', include_neutral=False)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != ROOTS or
            tuple(row['record']['id'] for row in data['dependencies']) != LARVAE + (STRENGTH_TOTEM,) or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != EXISTING or
            tuple(row['record']['id'] for row in data['evidence_only']) != ('BE_720t12',) or
            tuple(data['finite_larva_ids']) != LARVAE or tuple(data['basic_totem_ids']) != BASIC_TOTEMS):
        raise TargetValidationError('Larvae require the complete reviewed source and class family')
    for section in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only'):
        for row in data[section]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('Incomplete original Larva source record')
    classes = [metadata_from_record(row['record']).classes for row in data['dependencies'][:-1]]
    if (any(len(value) != 1 for value in classes) or
            {value[0] for value in classes} != PLAYABLE_CARD_CLASSES or len(set(classes)) != 11):
        raise TargetValidationError('Larva leaves must cover each actual playable class exactly once')
    return data


def register_class_larva_cards(registry):
    data = load_batch()
    # Check whole existing definitions before installing any part of this family.
    for row in data['existing_dependencies']:
        if (canonical_digest(row['definition']) != row['definition_sha256'] or
                canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']):
            raise TargetValidationError('Larva summon/weapon dependency changed outside its complete review')

    def generate(c, count):
        current_class = c.state.players[c.player_id].hero_class
        if current_class not in PLAYABLE_CARD_CLASSES:
            raise ResolutionError('Larva generation requires a known current playable hero class')
        candidates = []
        for cid in LARVAE:
            row = registry.pool_card(cid)
            if matches_metadata(QUERY, card_id=cid, kind=row.kind, cost=row.cost,
                    meta=row.metadata, spell_school=row.spell_school, keywords=row.keywords,
                    current_class=current_class):
                candidates.append(cid)
        # No candidate is dropped because its executable definition is unknown.
        # The ordinary finite generator validates the entire eligible list,
        # including when a full hand will burn the sampled card.
        if len(candidates) != 10:
            raise ResolutionError('Larva generation lost the complete other-class family')
        return tuple(GenerateFromCandidates(c.player_id, tuple(candidates), c.source_id)
                     for _ in range(count))

    def summon(c, card_id):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(card_id),), SummonCause.capture(c)),)

    def strength(c):
        candidates = tuple(eid for eid in minions(c, registry, c.player_id) if eid != c.source_id)
        return (RandomBuff(candidates, attack=1, source_id=c.source_id),)

    bodies = {
        'one': lambda c: generate(c, 1),
        'two': lambda c: generate(c, 2),
        'three': lambda c: generate(c, 3),
        'priest': lambda c: () if c.target_id is None else
            (Heal(c.target_id, 2, c.source_id, HealingKind.EFFECT),),
        # Keep the prior recipe under its actual old identity. The current
        # printed leaf points to the corrected post-29.0 behavior below.
        'shaman': lambda c: (SummonFromCandidates(c.player_id, tuple(data['prior_shaman_totem_ids']),
            c.source_id, SummonCause.capture(c)),),
        'shaman.current_air': lambda c: (SummonFromCandidates(c.player_id, BASIC_TOTEMS,
            c.source_id, SummonCause.capture(c)),),
        'rogue': lambda c: (EquipWeapon(c.player_id, 'CS2_082'),),
        'paladin': lambda c: summon(c, 'CS2_101t'),
        'hunter': lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 2,
            c.source_id, DamageKind.MINION_ABILITY),),
        'druid': lambda c: (GainArmor(c.player_id, 1),
            Buff(c.state.players[c.player_id].hero_id, attack=1,
                source_id=c.source_id, expires_turn=c.state.turn)),
        'warlock': lambda c: (Draw(c.player_id, 1, c.source_id),
            Damage(c.state.players[c.player_id].hero_id, 2, c.source_id, DamageKind.MINION_ABILITY)),
        'mage': lambda c: () if c.target_id is None else
            (Damage(c.target_id, 1, c.source_id, DamageKind.MINION_ABILITY),),
        'warrior': lambda c: (GainArmor(c.player_id, 2),),
        'demon_hunter': lambda c: (Buff(c.state.players[c.player_id].hero_id, attack=1,
            source_id=c.source_id, expires_turn=c.state.turn),),
        'death_knight': lambda c: summon(c, 'HERO_11bpt'),
        'strength': strength,
    }
    definitions = []
    for row in data['cards'] + data['dependencies']:
        raw = row['record']
        cid = raw['id']
        kwargs = {}
        if cid == ROOTS[0]:
            kwargs['battlecry'] = PREFIX + 'one'
        elif cid == ROOTS[1]:
            kwargs['deathrattle'] = PREFIX + 'two'
        elif cid == ROOTS[2]:
            kwargs.update(on_play=PREFIX + 'three', spell_school=SCHOOLS[raw['tags']['SPELL_SCHOOL']])
        elif cid == STRENGTH_TOTEM:
            kwargs['triggers'] = (TriggerSpec('turn_ended', PREFIX + 'strength', EndTurnSpec()),)
        else:
            card_class, = metadata_from_record(raw).classes
            kwargs.update(keywords=(Keyword.COMBO,), combo=PREFIX + card_class.value)
            if cid == 'BE_720t2':
                kwargs['combo'] = PREFIX + 'shaman.current_air'
            if cid in (LARVAE[0], LARVAE[7]):
                kwargs.update(targeting=TargetSpec(TargetMode.IF_AVAILABLE), target_condition='combo')
        definitions.append(CardDefinition(cid, raw['name'], CardType[raw['type']],
            cost=raw['cost'], attack=raw['attack'] if raw['attack'] is not None else 0,
            health=raw['health'] if raw['health'] is not None else 0,
            metadata=metadata_from_record(raw), **kwargs))

    for key, body in bodies.items():
        registry.register_behavior(PREFIX + key, body)
    for definition in definitions:
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
