"""Native Irida and complete Paladin Mech candidates for an actual past source."""
import json
from pathlib import Path

from hs_sim.engine.effects import RandomBuff
from hs_sim.engine.model import (AuraSpec, CardDefinition, CardType, EndTurnSpec,
    Keyword, PlayerEffectSpec, TriggerSpec)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.void_decks import GetFromVoid, SendDeckToVoid
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p72-v1.json'
BATCH_HASH = 'befaa9135fb6fd7d7e65b34a1bc34efe321a5dade00a72725d198411578bf878'
IRIDA = 'JAIL_719'
GLOW, MINIBOT, COBALT, SHOTBOT, MUMMY, BUBBLE, EGG, ROBOSAUR, SKY, COPTER, BUSY = (
    'BOT_906', 'GVG_058', 'GVG_062', 'YOD_010', 'ULD_217', 'TSC_059',
    'BOT_537', 'BOT_537t', 'DRG_225', 'DRG_225t', 'WORK_002')
COLLECTIBLE_ROOTS = (IRIDA,)
DEPENDENCIES = (GLOW, MINIBOT, COBALT, SHOTBOT, MUMMY, BUBBLE, EGG, ROBOSAUR, SKY, COPTER, BUSY)
ROOTS = COLLECTIBLE_ROOTS + DEPENDENCIES
PREFIX = 'cards.simple_followup_p72.'
VOID = PREFIX + 'void'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != COLLECTIBLE_ROOTS
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES
            or d['existing_dependencies'] or d['skipped']):
        raise TargetValidationError('P72 complete source scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for key in ('cards', 'dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('P72 complete original row changed')
    return d


def register_simple_followup_p72_cards(registry):
    d = load_batch()

    def begin(c):
        return (SendDeckToVoid(c.player_id, c.source_id), AddPlayerEffect(c.player_id, VOID, c.source_id))

    def acquire(c):
        return (GetFromVoid(c.player_id, 2, c.source_id),) if c.event.player_id == c.player_id else ()

    def cobalt(c):
        if c.event is None or c.event.player_id != c.player_id or c.event.target_id == c.source_id:
            return ()
        target = c.state.entities.get(c.event.target_id)
        return (GrantCapturedKeyword(MinionReference.capture(c.source), Keyword.DIVINE_SHIELD, c.source_id),) if (
            target is not None and has_any_tribe(registry, target, ('mech',))) else ()

    def mummy(c):
        return (RandomBuff(tuple(i for i in minions(c, registry, c.player_id) if i != c.source_id),
            1, 0, c.source_id),)

    def bubble(c):
        refs = tuple(MinionReference.capture(c.state.entities[i]) for i in minions(c, registry, c.player_id)
            if i != c.source_id and has_any_tribe(registry, c.state.entities[i], ('mech',)))
        return tuple(GrantCapturedKeyword(ref, keyword, c.source_id)
            for ref in refs for keyword in (Keyword.DIVINE_SHIELD, Keyword.TAUNT))

    def egg(c):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(ROBOSAUR),), SummonCause.capture(c),
            position=deathrattle_position(c)),)

    def sky(c):
        cause = SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(COPTER),), cause) for _ in range(2))

    def busy(c):
        return tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[i]), 1, 1, c.source_id)
            for i in minions(c, registry, c.player_id) if c.state.entities[i].attack == 1)

    for name, body in dict(begin=begin, acquire=acquire, cobalt=cobalt, mummy=mummy,
            bubble=bubble, egg=egg, sky=sky, busy=busy).items():
        registry.register_behavior(PREFIX + name, body)
    registry.register_player_effect(PlayerEffectSpec(VOID, IRIDA,
        triggers=(TriggerSpec('turn_started', PREFIX + 'acquire'),)))

    for row in d['cards'] + d['dependencies']:
        raw = row['record']; cid = raw['id']; kwargs = {}
        if cid == IRIDA: kwargs.update(keywords=(Keyword.LIFESTEAL,), battlecry=PREFIX + 'begin')
        if cid == GLOW: kwargs.update(keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',))
        if cid == MINIBOT: kwargs['keywords'] = (Keyword.DIVINE_SHIELD,)
        if cid in (SHOTBOT, MUMMY): kwargs['keywords'] = (Keyword.REBORN,)
        if cid == COBALT: kwargs['triggers'] = (TriggerSpec('minion_summoned', PREFIX + 'cobalt'),)
        if cid == MUMMY: kwargs['triggers'] = (TriggerSpec('turn_ended', PREFIX + 'mummy', EndTurnSpec()),)
        if cid == BUBBLE: kwargs['battlecry'] = PREFIX + 'bubble'
        if cid == EGG: kwargs['deathrattle'] = PREFIX + 'egg'
        if cid == SKY: kwargs.update(battlecry=PREFIX + 'sky', auras=(AuraSpec(attack=1, tribes_any=('mech',)),))
        if cid == BUSY: kwargs['battlecry'] = PREFIX + 'busy'
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'], metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
