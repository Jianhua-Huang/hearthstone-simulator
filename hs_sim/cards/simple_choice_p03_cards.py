"""Four P03 roots, exact named summons and native ordinary Choose One branches."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.cross_zone import MinionScope, minion_references
from hs_sim.engine.effects import Damage, EquipWeapon
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition, CardType, ChooseBranch, ChooseOneSpec, DamageKind, Keyword, Rarity, Zone
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-choice-p03-v1.json'
BATCH_HASH = 'eff0069348844a03d0f2554a814117f081357a0ec5ef799afe6bc354978edf21'
KEEPER = 'EDR_457'
RELEASE = 'JAIL_387'
FOREST = 'EDR_233'
GRACE = 'EDR_263'
THORN = 'EDR_525'
SWORD = 'EDR_457t'
WOLF = 'EX1_tk11'
FALCON = 'EDR_233t2'
PUP = 'EDR_850pe'
FOREST_WOLVES = 'EDR_233a'
FOREST_FALCONS = 'EDR_233b'
GRACE_DAMAGE = 'EDR_263a'
GRACE_PUPS = 'EDR_263b'
ROOTS = (KEEPER, RELEASE, FOREST, GRACE)
DEPENDENCIES = (SWORD, WOLF, FALCON, FOREST_WOLVES, FOREST_FALCONS, GRACE_DAMAGE, GRACE_PUPS)
CHOICE_ONLY = (FOREST_WOLVES, FOREST_FALCONS, GRACE_DAMAGE, GRACE_PUPS)
PREFIX = 'cards.simple_choice_p03.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('P03 lost its complete reviewed source pin')
    if (tuple(row['record']['id'] for row in data['cards']) != ROOTS or
            tuple(row['record']['id'] for row in data['dependencies']) != DEPENDENCIES or
            tuple(data['choice_only_ids']) != CHOICE_ONLY or
            tuple(row['record']['id'] for row in data['skipped']) != (THORN,)):
        raise TargetValidationError('Unreviewed P03 root, dependency or descriptor set')
    for group in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only', 'skipped'):
        for row in data[group]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P03 full source row changed')
    return data


def register_simple_choice_p03_cards(registry):
    data = load_batch()
    reused, = data['existing_dependencies']
    if reused['record']['id'] != PUP or canonical_digest(asdict(registry.card(PUP))) != reused['definition_sha256']:
        raise TargetValidationError('P03 requires the complete existing Playful Pup definition')
    raws = {row['record']['id']: row['record'] for row in data['cards'] + data['dependencies']}

    def summon(c, cid, count):
        return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(cid),), SummonCause.capture(c)) for _ in range(count))

    def keeper(c):
        if not any(has_any_tribe(registry, c.state.entities[i], ('dragon',))
                   for i in c.state.players[c.player_id].hand):
            return ()
        return (EquipWeapon(c.player_id, SWORD),)

    def release(c):
        # Both lists capture the same original window before any buff reaction.
        original = minion_references(c.state, registry, c.player_id, MinionScope(zones=(Zone.HAND,)), c.source_id)
        legendary = minion_references(c.state, registry, c.player_id,
            MinionScope(zones=(Zone.HAND,), query=PoolQuery(rarities=(Rarity.LEGENDARY,))), c.source_id)
        return (*tuple(BuffStoredCard(ref, 1, 1, c.source_id) for ref in original),
                *tuple(BuffStoredCard(ref, 2, 1, c.source_id) for ref in legendary))

    def damage(c):
        return (Damage(c.state.players[3-c.player_id].hero_id, 4, c.source_id, DamageKind.SPELL),)

    bodies = {
        'keeper': keeper,
        'release': release,
        'forest_wolves': lambda c: summon(c, WOLF, 3),
        'forest_falcons': lambda c: summon(c, FALCON, 2),
        'forest_both': lambda c: (*summon(c, WOLF, 3), *summon(c, FALCON, 2)),
        'grace_damage': damage,
        'grace_pups': lambda c: summon(c, PUP, 2),
        'grace_both': lambda c: (*damage(c), *summon(c, PUP, 2)),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for row in data['cards'] + data['dependencies']:
        raw = row['record']
        cid = raw['id']
        kind = CardType(raw['type'].lower())
        choice = cid in CHOICE_ONLY
        if raw['collectible'] != (cid in ROOTS):
            raise TargetValidationError('P03 collectible identity changed')
        kwargs = {}
        if cid == KEEPER:
            kwargs['battlecry'] = PREFIX+'keeper'
        elif cid == RELEASE:
            kwargs['on_play'] = PREFIX+'release'
        elif cid in (FOREST, GRACE):
            first, second, name = ((FOREST_WOLVES, FOREST_FALCONS, 'forest') if cid == FOREST
                                   else (GRACE_DAMAGE, GRACE_PUPS, 'grace'))
            scripts = {FOREST_WOLVES: 'forest_wolves', FOREST_FALCONS: 'forest_falcons',
                       GRACE_DAMAGE: 'grace_damage', GRACE_PUPS: 'grace_pups'}
            kwargs['choose_one'] = ChooseOneSpec(
                tuple(ChooseBranch(option, raws[option]['name'], PREFIX+scripts[option]) for option in (first, second)),
                ChooseBranch(cid+':combined', '兼得', PREFIX+name+'_both'),
            )
        elif cid == SWORD:
            kwargs['durability'] = raw['health']
        elif cid in (WOLF, FALCON):
            kwargs['keywords'] = (Keyword.TAUNT if cid == WOLF else Keyword.WINDFURY,)
        card = CardDefinition(
            cid, raw['name'], kind, cost=0 if choice else raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'] if kind == CardType.MINION else 0, choice_only=choice,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs,
        )
        registry.register_card(card)
        if not choice:
            registry.register_pool_card(PoolCard.from_definition(card))
