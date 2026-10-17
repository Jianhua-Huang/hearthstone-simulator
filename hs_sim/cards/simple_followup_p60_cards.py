"""Source-reviewed quest rewards, native weapons and actual starting-hand consumer."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import CopyMinion, RandomDamage, ReplaceHeroPower
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType, CostSpec,
    DamageKind, Keyword, TriggerSpec, Zone)
from hs_sim.engine.pools import FillHandFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.starting_hands import ReplaceHandWithTemporaryStartingHand
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import AddToDeck, CardReference, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p60-v1.json'
BATCH_HASH = '092903f3de4fefa0b165104f5270553b33781a56ba7fcde3b6495ba7e2f89ed7'
BARNABUS, QUEEN, MEGAFIN, SULFURAS, POWER = ('UNG_116t', 'UNG_920t1', 'UNG_942t', 'UNG_934t1', 'UNG_934t2')
SOLITOS, FLOWER, FISH, ANCIENT, WHISPER = ('TLC_817t5', 'TLC_239t', 'TIME_706', 'EDR_209t5', 'JAIL_887t3')
ROOTS = (BARNABUS, QUEEN, MEGAFIN, SULFURAS, POWER, SOLITOS, FLOWER, FISH, ANCIENT, WHISPER)
RAPTOR = 'UNG_920t2'
PREFIX, POOL_ID = 'cards.simple_followup_p60.', 'constructed.cards'
MURLOCS = PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('murloc',))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS
            or tuple(x['record']['id'] for x in data['existing_dependencies']) != (RAPTOR,)
            or any(data[k] for k in ('dependencies', 'skipped'))):
        raise TargetValidationError('P60 frozen complete scope changed')
    for row in data['cards'] + data['existing_dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('P60 complete original source row changed')
    return data


def register_simple_followup_p60_cards(registry):
    data = load_batch()
    if canonical_digest(asdict(registry.card(RAPTOR))) != data['existing_dependency_definition_pins'][RAPTOR]:
        raise TargetValidationError('P60 exact existing Raptor definition changed')

    def barnabus(c):
        refs = tuple(CardReference.capture(c.state.entities[i]) for i in c.state.players[c.player_id].deck
            if c.state.entities[i].kind == CardType.MINION)
        return tuple(ModifyStoredCost(ref, CostSpec(set_to=0, card_types=(CardType.MINION,)), c.source_id) for ref in refs)

    def flower(c):
        attack = completed_attack(c)
        if (attack is None or attack.source_kind != CardType.HERO or attack.declaration.player_id != c.player_id
                or attack.combat.weapon_id != c.source_id):
            return ()
        refs = tuple(MinionReference.capture(c.state.entities[i]) for i in minions(c, registry, c.player_id))
        return tuple(BuffCapturedMinion(ref, 2, 2, c.source_id) for ref in refs)

    bodies = {BARNABUS: barnabus,
        QUEEN: lambda c: shuffled(c, tuple(AddToDeck(c.player_id, RAPTOR, source_id=c.source_id) for _ in range(20))),
        MEGAFIN: lambda c: (FillHandFromPool(GenerateFromPool(c.player_id, POOL_ID, MURLOCS, source_id=c.source_id)),),
        SULFURAS: lambda c: (ReplaceHeroPower(c.player_id, POWER, source_id=c.source_id),),
        POWER: lambda c: (RandomDamage(characters(c, registry, 3-c.player_id), 8, c.source_id, DamageKind.HERO_POWER),),
        SOLITOS: lambda c: (CopyMinion(BoardPresenceReference.capture(c.state, c.source_id), c.player_id,
            cause=SummonCause.capture(c)),),
        'solitos_death': lambda c: (RandomDamage(characters(c, registry, 3-c.player_id), 5, c.source_id, DamageKind.MINION_ABILITY),),
        FLOWER: flower, FISH: lambda c: (ReplaceHandWithTemporaryStartingHand(c.player_id, c.source_id),)}
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    for row in data['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kwargs = {}
        if cid in (BARNABUS, QUEEN, MEGAFIN, SULFURAS, SOLITOS, FISH): kwargs['battlecry'] = PREFIX + cid
        if cid == QUEEN: kwargs['keywords'] = (Keyword.RUSH,)
        if cid == SOLITOS: kwargs.update(keywords=(Keyword.TAUNT, Keyword.REBORN), deathrattle=PREFIX + 'solitos_death')
        if cid in (ANCIENT, WHISPER): kwargs['keywords'] = (Keyword.TAUNT,)
        if cid == POWER: kwargs['on_use'] = PREFIX + cid
        if cid == FLOWER: kwargs['triggers'] = (TriggerSpec('attack_finished', PREFIX + cid),)
        if kind == CardType.WEAPON: kwargs['durability'] = raw['health']
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] if kind in (CardType.MINION, CardType.WEAPON) else 0,
            health=raw['health'] if kind == CardType.MINION else 0, metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
