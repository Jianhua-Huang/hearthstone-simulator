"""Five P04 roots use existing targets, native choices and exact named cards."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.dark_gifts import public_gifts
from hs_sim.engine.effects import AddToHand, Damage, DamageBatch
from hs_sim.engine.model import (
    AttackPolicySpec, CardDefinition, CardType, ChooseBranch, ChooseOneSpec,
    CostSpec, DamageKind, Keyword, TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, DestroyCapturedMinion, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-fixed-p04-v1.json'
BATCH_HASH = '5199ba5b7fc7a1fdc4d3c3b126c21a45fd3a1c58fd32d9b06b2855ee8cfc9da4'
COGHAMMER = 'CORE_GVG_059'
NIGHTMARES = 'EDR_570'
SLEEP = 'EDR_490'
HORROR = 'EDR_654'
WASP = 'TLC_630'
INFESTATION = 'TLC_902'
BURST = 'EDR_570A'
POWER = 'EDR_570B'
FIGURE = 'EDR_490a'
WITS_END = 'EDR_490b'
TERROR = 'EDR_490t'
STINGER = 'TLC_630t'
GRUB = 'TLC_903t'
ROOTS = (NIGHTMARES, SLEEP, HORROR, WASP, INFESTATION)
DEPENDENCIES = (BURST, POWER, FIGURE, WITS_END, TERROR, STINGER)
CHOICE_ONLY = (BURST, POWER, FIGURE, WITS_END)
PREFIX = 'cards.simple_fixed_p04.'
MINION = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
ENEMY_MINION = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy')


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(d) != BATCH_HASH:
        raise TargetValidationError('P04 lost its complete reviewed source pin')
    if (tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES or
            tuple(d['choice_only_ids']) != CHOICE_ONLY or
            tuple(x['record']['id'] for x in d['skipped']) != (COGHAMMER,)):
        raise TargetValidationError('Unreviewed P04 roots, choices or named dependencies')
    for key in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only', 'skipped'):
        for row in d[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P04 complete source row changed')
    return d


def register_simple_fixed_p04_cards(registry):
    d = load_batch()
    existing, = d['existing_dependencies']
    if existing['record']['id'] != GRUB or canonical_digest(asdict(registry.card(GRUB))) != existing['definition_sha256']:
        raise TargetValidationError('P04 requires the complete existing Silithid Grub')
    raws = {x['record']['id']: x['record'] for x in d['cards'] + d['dependencies']}
    registry.register_target_predicate(TargetPredicateSpec(PREFIX+'damaged', damaged=True))

    def summon(c, cid, count=1):
        return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(cid),), SummonCause.capture(c)) for _ in range(count))

    def burst(c):
        return (DamageBatch(tuple(Damage(i, 1, c.source_id, DamageKind.SPELL)
                                  for p in (1, 2) for i in minions(c, registry, p))),)

    def power(c):
        return (BuffCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]), 2, 2, c.source_id),)

    def destroy(c):
        return (DestroyCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]), c.source_id),)

    def horror(c):
        return tuple(ModifyStoredCost(CardReference.capture(e), CostSpec(delta=-2), c.source_id)
                     for i in c.state.players[c.player_id].hand for e in (c.state.entities[i],)
                     if e.kind == CardType.MINION and public_gifts(e))

    def wasp(c):
        event = c.event
        if event is None or event.kind != 'damage_dealt' or event.target_id != c.source_id or event.amount <= 0:
            return ()
        return (AddToHand(c.player_id, STINGER, c.source_id),)

    bodies = {
        'burst': burst,
        'power': power,
        'nightmares_both': lambda c: (*burst(c), *power(c)),
        'figure': lambda c: summon(c, TERROR, 2),
        'destroy': destroy,
        'sleep_both': lambda c: (*summon(c, TERROR, 2), *destroy(c)),
        'horror': horror,
        'wasp': wasp,
        'infestation': lambda c: (AddToHand(c.player_id, STINGER, c.source_id), AddToHand(c.player_id, STINGER, c.source_id)),
        'stinger': lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL), *summon(c, GRUB)),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX+name, body)
    for row in d['cards'] + d['dependencies']:
        raw = row['record']
        cid = raw['id']
        kind = CardType(raw['type'].lower())
        choice = cid in CHOICE_ONLY
        if raw['collectible'] != (cid in ROOTS):
            raise TargetValidationError('P04 collectible identity changed')
        kwargs = {}
        if cid == NIGHTMARES:
            kwargs['choose_one'] = ChooseOneSpec((
                ChooseBranch(BURST, raws[BURST]['name'], PREFIX+'burst'),
                ChooseBranch(POWER, raws[POWER]['name'], PREFIX+'power', MINION, PREFIX+'damaged'),
            ), ChooseBranch(NIGHTMARES+':combined', '兼得', PREFIX+'nightmares_both', MINION, PREFIX+'damaged'))
        elif cid == SLEEP:
            kwargs['choose_one'] = ChooseOneSpec((
                ChooseBranch(FIGURE, raws[FIGURE]['name'], PREFIX+'figure'),
                ChooseBranch(WITS_END, raws[WITS_END]['name'], PREFIX+'destroy', ENEMY_MINION),
            ), ChooseBranch(SLEEP+':combined', '兼得', PREFIX+'sleep_both', ENEMY_MINION))
        elif cid == HORROR:
            kwargs.update(battlecry=PREFIX+'horror', keywords=(Keyword.TAUNT,))
        elif cid == WASP:
            kwargs.update(keywords=(Keyword.RUSH,), triggers=(TriggerSpec('damage_dealt', PREFIX+'wasp'),))
        elif cid == INFESTATION:
            kwargs['on_play'] = PREFIX+'infestation'
        elif cid == TERROR:
            kwargs.update(keywords=(Keyword.TAUNT,), attack_policies=(AttackPolicySpec('cannot_attack'),))
        elif cid == STINGER:
            kwargs.update(on_play=PREFIX+'stinger', targeting=TargetSpec())
        card = CardDefinition(
            cid, raw['name'], kind, cost=0 if choice else raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'] if kind == CardType.MINION else 0, choice_only=choice,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs,
        )
        registry.register_card(card)
        if not choice:
            registry.register_pool_card(PoolCard.from_definition(card))
