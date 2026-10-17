"""Three complete named Dreadseeds retain ordinary dormancy and native causes."""
import json
from pathlib import Path

from hs_sim.engine.effects import Buff, Damage, DamageBatch, Draw, InvokeBehavior
from hs_sim.engine.model import CardDefinition, CardType, ChooseBranch, ChooseOneSpec, DamageKind, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-dreadseed-v1.json'
BATCH_HASH = 'f106a00dba5805af3ac0f504bd4b97a3ba034e7d345e62e5250d5ccad1b0817b'
SLUMBER, HARVEST, CORRUPTER = ROOTS = ('EDR_820', 'EDR_840', 'EDR_841')
HOUND, CROW, SERPENT = SEEDS = ('EDR_840t', 'EDR_840t1', 'EDR_840t2')
SUMMON_BRANCH, DAMAGE_BRANCH = CHOICE_ONLY = ('EDR_820a', 'EDR_820b')
DEPENDENCIES = (*SEEDS, *CHOICE_ONLY)
EVIDENCE_ONLY = ('EDR_840t1e', 'EDR_840t1e1', 'EDR_840t2e1', 'EDR_840te')
TURNS = {HOUND: 2, CROW: 1, SERPENT: 3}
PREFIX = 'cards.native_dreadseed.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['evidence_only']) != EVIDENCE_ONLY or
            tuple(data['seed_ids']) != SEEDS or data['seed_turns'] != TURNS or
            tuple(data['choice_only_ids']) != CHOICE_ONLY or data['existing_dependencies'] or data['skipped']):
        raise TargetValidationError('Dreadseeds require their complete reviewed source and exact named inventory')
    for group in ('cards', 'dependencies', 'evidence_only'):
        for row in data[group]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('Incomplete original Dreadseed source row')
    return data


def register_native_dreadseed_cards(registry):
    data = load_batch()
    raws = {x['record']['id']: x['record'] for x in data['cards'] + data['dependencies']}

    def summon(c, count=1):
        request = SummonByCard(c.player_id, tuple(SummonEntryMaterial(cid) for cid in SEEDS),
            SummonCause.capture(c), selection='random',
            position=deathrattle_position(c) if c.deathrattle is not None else None)
        return (request,) * count

    def damage(c):
        return (DamageBatch(tuple(Damage(i, 2, c.source_id, DamageKind.SPELL)
            for player in (1, 2) for i in minions(c, registry, player))),)

    bodies = {
        'summon': summon,
        'harvest': lambda c: (Draw(c.player_id, 1, c.source_id), *summon(c)),
        'two': lambda c: summon(c, 2),
        'damage': damage,
        'both': lambda c: (*summon(c, 2), InvokeBehavior(PREFIX + 'damage', c.source_id, c.player_id)),
        'awaken': lambda c: (Buff(c.state.players[c.player_id].hero_id, attack=3,
                                 source_id=c.source_id, expires_turn=c.state.turn),),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for cid in (*ROOTS, *DEPENDENCIES):
        raw = raws[cid]
        choice = cid in CHOICE_ONLY
        kind = CardType(raw['type'].lower())
        if (raw['collectible'] != (cid in ROOTS) or type(raw['cost']) is not int or
                raw['tags'].get('SPELL_SCHOOL') is not None):
            raise TargetValidationError('Dreadseed faces require their complete original collectible/cost/school facts')
        kwargs = {}
        if cid in SEEDS:
            if kind != CardType.MINION or type(raw['attack']) is not int or type(raw['health']) is not int:
                raise TargetValidationError('Seed requires complete original minion stats')
            kwargs.update(dormant_turns=TURNS[cid],
                keywords=() if cid == HOUND else (Keyword.ELUSIVE,) if cid == CROW else (Keyword.TAUNT, Keyword.LIFESTEAL))
            if cid == HOUND:
                kwargs['on_awaken'] = PREFIX + 'awaken'
        elif cid == CORRUPTER:
            kwargs.update(battlecry=PREFIX + 'summon', deathrattle=PREFIX + 'summon')
        elif cid == HARVEST:
            kwargs['on_play'] = PREFIX + 'harvest'
        elif cid == SLUMBER:
            kwargs['choose_one'] = ChooseOneSpec((
                ChooseBranch(SUMMON_BRANCH, raws[SUMMON_BRANCH]['name'], PREFIX + 'two'),
                ChooseBranch(DAMAGE_BRANCH, raws[DAMAGE_BRANCH]['name'], PREFIX + 'damage'),
            ), ChooseBranch(SLUMBER + ':combined', '兼得', PREFIX + 'both'))
        card = CardDefinition(cid, raw['name'], kind, cost=0 if choice else raw['cost'],
            attack=raw['attack'] or 0, health=raw['health'] if kind == CardType.MINION else 0,
            choice_only=choice, metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        if not choice:
            registry.register_pool_card(PoolCard.from_definition(card))
