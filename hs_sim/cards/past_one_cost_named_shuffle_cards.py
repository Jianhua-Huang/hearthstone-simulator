"""Complete historical named summons, semantic shuffles and native copy rewards."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.effects import AddToHand, CopyMinion, Damage, Heal, RandomDamage
from hs_sim.engine.jade import CLASSIC, SummonJadeGolem
from hs_sim.engine.model import (
    BoardPresenceReference, CardDefinition, CardType, CastWhenDrawnSpec, DamageKind,
    HandActionSpec, HealingKind, Keyword, TargetMode, TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, deathrattle_position
from .recruit_cards import shuffle


RABBIT, LOUD, TASKMASTER, CATCH, FIEND, ZOMBIE, ZERGLING, HATCHLING, JAILER, CONDUCTOR, SALESMAN, SWARMER, SQUIRREL = (
    'SCH_133', 'LOOT_218', 'TRL_363', 'VAC_412', 'VAC_940', 'RLK_650', 'SC_010',
    'UNG_914', 'SCH_700', 'WW_044', 'WW_331', 'WON_067', 'SW_439')
LEAVES = (RABBIT, LOUD, TASKMASTER, CATCH, FIEND, ZOMBIE, ZERGLING, HATCHLING,
    JAILER, CONDUCTOR, SALESMAN, SWARMER, SQUIRREL)
ARMLESS, EMPTY, MINER, GRUB, FELBEAST, PATRIARCH, FRAGMENT, SLUDGE, OIL = (
    'RLK_650t', 'RLK_650t2', 'TRL_363t', 'VAC_412t', 'VAC_940t', 'UNG_914t1',
    'SCH_307t', 'WW_044t', 'WW_331t')
TOKENS = (ARMLESS, EMPTY, MINER, GRUB, FELBEAST, PATRIARCH, FRAGMENT, SLUDGE, OIL)
DEPENDENCIES = LEAVES + TOKENS
ACORN, SATISFIED = 'SW_439t', 'SW_439t2'
JADE_FORMS = ('CFM_712_t01', 'CFM_712_t04', 'CFM_712_t07', 'CFM_712_t20')
EXISTING = (ACORN, SATISFIED) + JADE_FORMS
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_named_shuffles.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-named-shuffles-v1.json'
BATCH_HASH = 'ebbd5b8ac5a393c1d47810db0d86b317f9bf6e7f7da65f3df82c3f86f5d7b0b8'
NUMERIC = {MINER: {'attack': 0}, FRAGMENT: {'cost': 0}, OIL: {'cost': 0}}
DISPLAY = {SWARMER: {'zh_CN': {'@': '', '{0}': ''}, 'en_US': {'@': '', '{0}': '', '{1}': ''}}}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != DEPENDENCIES or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != EXISTING or
            data['numeric_normalizations'] != NUMERIC or data['display_normalizations'] != DISPLAY or
            any(data[k] for k in ('cards', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256']
                for row in data['dependencies'] + data['existing_dependencies'])):
        raise TargetValidationError('Historical named consumers lost their complete reviewed sources')
    return data


def register_past_one_cost_named_shuffle_cards(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Named historical source changed its original Acorn or Jade dependency')
    if registry.jade_families[CLASSIC].forms != JADE_FORMS:
        raise TargetValidationError('Restored Swarmer requires the existing complete Classic Jade family')

    def summon(c, cid, *, enemy=False, count=1, death=False):
        request = SummonByCard(3-c.player_id if enemy else c.player_id,
            (SummonEntryMaterial(cid),), SummonCause.capture(c),
            position=deathrattle_position(c) if death and not enemy else None)
        return (request,) * count

    def rabbit(c):
        return (CopyMinion(BoardPresenceReference.capture(c.state, c.source_id), c.player_id,
            cause=SummonCause.capture(c)),) if living_source(c) else ()

    def loud(c):
        row = completed_attack(c)
        if (row is None or not living_source(c) or row.source_kind != CardType.MINION or
                row.declaration.source_id != c.source_id or row.combat.player_id != c.player_id or
                (row.combat.source_zone_epoch, row.combat.source_entered_order) !=
                (c.source.zone_epoch, c.source.entered_order) or
                c.state.entities[row.delivery.target_id].kind != CardType.HERO):
            return ()
        return (CopyCard(MinionReference.capture(c.source), c.player_id, mode='base', source_id=c.source_id),)

    def sludge(c, kind):
        ids = characters(c, registry, 3-c.player_id)
        if not ids: return ()
        lowest = min(c.state.entities[i].health for i in ids)
        return (RandomDamage(tuple(i for i in ids if c.state.entities[i].health == lowest),
            4, c.source_id, kind),)

    bodies = {
        RABBIT: rabbit, LOUD: loud,
        TASKMASTER: lambda c: summon(c, MINER, enemy=True),
        CATCH: lambda c: summon(c, GRUB, enemy=True),
        FIEND: lambda c: (*summon(c, FELBEAST, count=2),
            Damage(c.state.players[c.player_id].hero_id, 3, c.source_id, DamageKind.MINION_ABILITY)),
        ZOMBIE: lambda c: summon(c, ARMLESS, death=True),
        ARMLESS: lambda c: summon(c, EMPTY, death=True),
        ZERGLING: lambda c: summon(c, ZERGLING),
        HATCHLING: lambda c: shuffle(c, PATRIARCH, 1),
        JAILER: lambda c: shuffle(c, FRAGMENT, 2),
        CONDUCTOR: lambda c: (AddToHand(c.player_id, SLUDGE, c.source_id),),
        SALESMAN: lambda c: (AddToHand(c.player_id, OIL, c.source_id),),
        SWARMER: lambda c: (SummonJadeGolem(c.player_id, c.source_id, position=deathrattle_position(c),cause=SummonCause.capture(c)),),
        SQUIRREL: lambda c: shuffle(c, ACORN, 4),
        FRAGMENT: lambda c: (Heal(c.state.players[c.player_id].hero_id, 2, c.source_id, HealingKind.SPELL),),
        SLUDGE: lambda c: sludge(c, DamageKind.SPELL),
        'sludge_passive': lambda c: sludge(c, DamageKind.EFFECT),
        OIL: lambda c: (Damage(c.target_id, 0, c.source_id, DamageKind.SPELL),),
    }
    for cid, body in bodies.items(): registry.register_behavior(PREFIX + cid, body)
    battlecries = (RABBIT, CATCH, FIEND, ZERGLING, JAILER)
    deathrattles = (TASKMASTER, ZOMBIE, ARMLESS, HATCHLING, CONDUCTOR, SALESMAN, SWARMER, SQUIRREL)
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        kind = CardType[raw['type']]
        if raw['collectible'] != (cid in LEAVES):
            raise TargetValidationError('Named historical consumer changed its printed collection role')
        if kind == CardType.MINION:
            if raw['cost'] != 1 or type(raw['health']) is not int or cid != MINER and type(raw['attack']) is not int:
                raise TargetValidationError('Named historical minion requires its complete native body')
            if cid in battlecries: fields['battlecry'] = PREFIX + cid
            if cid in deathrattles: fields['deathrattle'] = PREFIX + cid
            if cid == LOUD: fields['triggers'] = (TriggerSpec('attack_finished', PREFIX + cid),)
            if cid == CATCH: fields['keywords'] = (Keyword.RUSH,)
            if cid == SWARMER: fields['keywords'] = (Keyword.STEALTH,)
            if cid == MINER: fields['keywords'] = (Keyword.TAUNT,)
        elif kind == CardType.SPELL and cid in (FRAGMENT, SLUDGE, OIL):
            fields.update(on_play=PREFIX + cid, spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')))
            if cid == FRAGMENT:
                fields.update(keywords=(Keyword.CASTS_WHEN_DRAWN,), cast_when_drawn=CastWhenDrawnSpec())
            elif cid == SLUDGE:
                fields.update(on_discard=PREFIX+'sludge_passive', on_destroyed=PREFIX+'sludge_passive')
            else:
                fields.update(hand_actions=(HandActionSpec('trade', 'trade', 1),),
                    targeting=TargetSpec(TargetMode.REQUIRED, (Zone.HERO, Zone.BOARD), (CardType.HERO, CardType.MINION)))
        else:
            raise TargetValidationError('Unreviewed named historical card kind')
        card = CardDefinition(cid, raw['name'], kind, cost=0 if cid in (FRAGMENT, OIL) else raw['cost'],
            attack=0 if cid == MINER or kind == CardType.SPELL else raw['attack'],
            health=raw['health'] if kind == CardType.MINION else 0, metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
