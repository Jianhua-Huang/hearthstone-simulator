"""Fixed real Adapt recipes composed from existing effects and sampled choices.

There is no Adapt effect handler, persistent state, new keyword or second choice
interpreter. Install these choice faces/Plant in the host registry explicitly,
then return adapt(ctx, target_ids, registry) from a real source's behavior.
"""
import json
from pathlib import Path

from hs_sim.targets import canonical_digest
from .effects import (Buff, ChoiceOption, GrantDeathrattle, GrantKeyword,
                      RequestChoice, Summon, _integer, _player, _source)
from .model import ADAPTATION_CHOICES, CardClass, CardDefinition, CardMetadata, CardType, Keyword, TimedKeywordSpec, Zone

VERSION = 'adapt-options-v1'
CHOICE_IDS = ADAPTATION_CHOICES
PLANT_ID = 'UNG_999t2t1'
SPORES_BEHAVIOR = 'adapt.living_spores.v1'
PIN = 'ce578d34a829b2de078bd288a0681488c952fa2f179bdd1c14ea594e8988c2c3'
_KEYWORDS = {'UNG_999t6': Keyword.TAUNT, 'UNG_999t7': Keyword.WINDFURY,
             'UNG_999t8': Keyword.DIVINE_SHIELD, 'UNG_999t13': Keyword.POISONOUS,
             'UNG_999t5': Keyword.ELUSIVE}
_STATS = {'UNG_999t3': (3, 0), 'UNG_999t4': (0, 3), 'UNG_999t14': (1, 1)}


def records():
    """Pinned complete raw evidence, not a target patch or generation inventory."""
    path = Path(__file__).resolve().parents[2] / 'data/support/adapt-basics.json'
    value = json.loads(path.read_text(encoding='utf-8'))
    if canonical_digest(value) != PIN:
        raise ValueError('Adapt source records differ from the supported snapshot')
    return {row['id']: row['data'] for row in value['records']}


def _plants(ctx):
    position = None if ctx.death is None else ctx.death.position
    return (Summon(ctx.player_id, PLANT_ID, position),
            Summon(ctx.player_id, PLANT_ID, None if position is None else position + 1))


def register_adapt_options(registry):
    """Install only required option faces and the complete 1/1 Plant token."""
    raw = records()
    registry.register_behavior(SPORES_BEHAVIOR, _plants)
    meta = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    for cid in CHOICE_IDS:
        registry.register_card(CardDefinition(cid, raw[cid]['name'], CardType.SPELL,
                                              choice_only=True, metadata=meta))
    tags = raw[PLANT_ID]['tags']
    registry.register_card(CardDefinition(PLANT_ID, raw[PLANT_ID]['name'], CardType.MINION,
        cost=tags['COST'], attack=tags['ATK'], health=tags['HEALTH'], metadata=meta))


def _effect(ctx, entity, cid):
    if cid in _STATS:
        return Buff(entity.id, *_STATS[cid], source_id=ctx.source_id)
    if cid in _KEYWORDS:
        return GrantKeyword(entity.id, _KEYWORDS[cid], source_id=ctx.source_id)
    if cid == 'UNG_999t10':
        # The text says "your next turn", relative to the adapting actor.
        player = 'controller' if entity.controller == ctx.player_id else 'opponent'
        return GrantKeyword(entity.id, Keyword.STEALTH, source_id=ctx.source_id,
                            duration=TimedKeywordSpec(Keyword.STEALTH, player=player))
    if cid == 'UNG_999t2':
        return GrantDeathrattle(entity.id, SPORES_BEHAVIOR, source_id=ctx.source_id)
    raise ValueError('Unknown Adapt recipe')


def adapt(ctx, target_ids, registry):
    """One shared random three-of-ten offer for the captured board minions.

Call once per actual adaptation, including each round of Volcanosaur. Existing
keywords never remove options. Group membership is supplied by the source;
selection and individual attachment checkpoints retain their ordinary policy.
"""
    _player(ctx.player_id)
    _source(ctx.source_id)
    if ctx.source_id is None or ctx.source_id not in ctx.state.entities:
        raise ValueError('Adapt requires its physical source')
    if type(target_ids) is not tuple:
        raise ValueError('Adapt targets require a unique immutable tuple')
    for eid in target_ids:
        _integer(eid, 'Adapt target', 1)
        if eid not in ctx.state.entities:
            raise ValueError('Adapt target does not exist')
    if len(set(target_ids)) != len(target_ids):
        raise ValueError('Adapt targets require a unique immutable tuple')
    # Validate every fixed outcome, including outcomes sampling may omit.
    for cid in CHOICE_IDS:
        definition = registry.card(cid)
        if not definition.choice_only or definition.kind != CardType.SPELL:
            raise ValueError('Adapt options must be registered choice-only spell faces')
    plant = registry.card(PLANT_ID)
    if (plant.kind, plant.attack, plant.health) != (CardType.MINION, 1, 1):
        raise ValueError('Living Spores requires the registered 1/1 Plant token')
    registry.behavior(SPORES_BEHAVIOR)
    targets = tuple(ctx.state.entities[eid] for eid in target_ids
        if ctx.state.entities[eid].kind == CardType.MINION and
           ctx.state.entities[eid].zone == Zone.BOARD and ctx.state.entities[eid].active)
    if not targets:
        return ()
    options = tuple(ChoiceOption(cid, registry.card(cid).name,
        tuple(_effect(ctx, entity, cid) for entity in targets), card_id=cid) for cid in CHOICE_IDS)
    return (RequestChoice(ctx.player_id, options, source_id=ctx.source_id,
                          prompt='选择一项进化', sample_size=3),)
