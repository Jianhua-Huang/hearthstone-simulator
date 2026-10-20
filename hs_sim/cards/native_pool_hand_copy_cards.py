"""Native current-value pool consumers and physical hand Deathrattle copies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, TargetSpec, Zone
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

CALLING, ELEMENTAL, AGENT = 'BE_252', 'BE_870', 'BE_541'
PREFIX, POOL = 'cards.native_pool_hand_copy.', 'constructed.cards'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-pool-and-hand-copy-v1.json'
BATCH_HASH = 'f62ba590210df027bbcfa1c8f14e2b3b54af88396a6305d8d7f7930756ba2d7a'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CALLING, ELEMENTAL, AGENT) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'])):
        raise TargetValidationError('Native pool/hand-copy cards require complete reviewed source records')
    return data


def register_native_pool_hand_copy_cards(registry):
    def calling(c):
        target = c.state.entities.get(c.target_id)
        if (target is None or target.zone != Zone.BOARD or target.kind != CardType.MINION or
                target.controller != c.player_id or not target.active or target.doomed or target.health <= 0):
            return ()
        cost = max(0, local_cost(target)[0])
        return (SummonFromPool(c.player_id, POOL,
            PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=cost, max_cost=cost),
            source_id=c.source_id, cause=SummonCause.capture(c)),)

    def elemental(c):
        attack = max(0, c.source.attack)
        return (DiscoverFromPool(c.player_id, POOL,
            PoolQuery(kinds=(CardType.SPELL,), collectible=True, min_cost=attack, max_cost=attack),
            source_id=c.source_id, cost=CostSpec(set_to=0), expires_turn=c.state.turn),)

    def agent(c):
        options = []
        for eid in c.state.players[c.player_id].hand:
            entity = c.state.entities[eid]
            definition = registry.card(entity.card_id)
            if (definition.kind == CardType.MINION and entity.card_id != c.source.card_id and
                    active_abilities(entity, 'deathrattle')):
                options.append(ChoiceOption(json.dumps(asdict(CardReference.capture(entity)), sort_keys=True),
                    definition.name, card_id=entity.card_id, entity_id=entity.id))
        # One option per physical slot, including duplicate printed cards. The
        # existing automatic sampled-choice path owns RNG and durable delivery.
        return (RequestChoice(c.player_id, tuple(options), c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX+'copy'),) if options else ()

    def copy(c):
        result = c.choice
        if (result is None or result.selected_ids or len(result.choice.options) != 1 or
                (result.choice.source_id, result.choice.player_id) != (c.source_id, c.player_id)):
            raise ResolutionError('Agent requires its original single sampled physical hand card')
        value = json.loads(result.choice.options[0].id)
        value['zone'] = Zone(value['zone'])
        return (CopyCard(CardReference(**value), c.player_id, mode='current', source_id=c.source_id),)

    registry.register_behavior(PREFIX+'calling', calling)
    registry.register_behavior(PREFIX+'elemental', elemental)
    registry.register_behavior(PREFIX+'agent', lambda c: (
        InvokeBehavior(PREFIX+'agent.now', c.source_id, c.player_id),))
    registry.register_behavior(PREFIX+'agent.now', agent)
    registry.register_behavior(PREFIX+'copy', copy)
    rows = {x['record']['id']: x['record'] for x in load_batch()['cards']}
    if (rows[CALLING]['type'], rows[CALLING]['cost'], rows[CALLING]['tags'].get('SPELL_SCHOOL')) != ('SPELL', 2, 1):
        raise TargetValidationError('Constellar Calling changed its complete Arcane spell face')
    for cid, flag, expected in ((ELEMENTAL, 'BATTLECRY', (3, 2, 2)), (AGENT, 'DEATHRATTLE', (2, 3, 2))):
        raw = rows[cid]
        if (raw['type'] != 'MINION' or (raw['cost'], raw['attack'], raw['health']) != expected or
                raw['tags'].get(flag) != 1):
            raise TargetValidationError('Native pool/hand-copy minion changed its complete printed face')
    for cid in (CALLING, ELEMENTAL, AGENT):
        raw = rows[cid]
        if cid == CALLING:
            card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'],
                spell_school=SCHOOLS[1], on_play=PREFIX+'calling', metadata=metadata_from_record(raw),
                targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='friendly'))
        else:
            card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
                health=raw['health'], metadata=metadata_from_record(raw),
                battlecry=PREFIX+'elemental' if cid == ELEMENTAL else None,
                deathrattle=PREFIX+'agent' if cid == AGENT else None)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
