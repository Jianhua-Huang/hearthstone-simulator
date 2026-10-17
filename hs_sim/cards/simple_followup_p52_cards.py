"""Reviewed native board, physical deck, Mana and personal spell consumers."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import ChoiceOption, Damage, DamageBatch, RequestChoice, SpendMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (AppendageSpec, CardDefinition, CardType, DamageKind,
    EndTurnSpec, HandActionSpec, Keyword, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.sacrifice import BuffCapturedMinion, DestroyCapturedMinion, MinionReference
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import ChooseFromZone, CopyCard, DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p52-v1.json'
BATCH_HASH = '0ee50e4fe5146250674d566bf15b03a10aa881b416eb328cd0ee7993607038b6'
VULCANOS = 'CATA_488'
EXECUTIONER = 'JAIL_461'
RAT = 'JAIL_882'
HELLRAISER = 'JAIL_734'
CROOK = 'CATA_EVENT_400'
TRAVELER = 'TIME_434'
SHADOW = 'TIME_434t'
CYCLE = 'TLC_235'
ENVOY = 'EDR_873'
SUPPLICANT = 'CATA_786'
MEND = 'TIME_018'
ASSIGNED = (VULCANOS, EXECUTIONER, RAT, HELLRAISER, CROOK, TRAVELER, CYCLE, ENVOY, SUPPLICANT, MEND)
SKIPPED = (TRAVELER, ENVOY, MEND)
ROOTS = tuple(cid for cid in ASSIGNED if cid not in SKIPPED)
DEPENDENCIES = (SHADOW,)
EXISTING = ('CATA_488t', 'CATA_488t2')
PREFIX = 'cards.simple_followup_p52.'
POOL_ID = 'constructed.cards'
SPELLS = PoolQuery(kinds=(CardType.SPELL,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != EXISTING or
            tuple(x['record']['id'] for x in data['skipped']) != SKIPPED or data['evidence_only']):
        raise TargetValidationError('P52 complete reviewed native recipes changed')
    for row in data['cards'] + data['dependencies'] + data['existing_dependencies'] + data['skipped']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('P52 complete original source row changed')
    return data


def minion_cost(cost):
    return PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=cost, max_cost=cost)


def register_simple_followup_p52_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('P52 original Plume dependency changed: ' + cid)

    def vulcanos(c):
        ids = tuple(i for player in (1, 2) for i in minions(c, registry, player) if i != c.source_id)
        return (DamageBatch(tuple(Damage(i, 3, c.source_id, DamageKind.MINION_ABILITY) for i in ids)),)

    def executioner(c):
        source = c.source
        board = c.state.players[source.controller].board
        if source.id not in board:
            return ()
        index = board.index(source.id)
        adjacent = {board[i] for i in (index - 1, index + 1) if 0 <= i < len(board)}
        options = tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])), sort_keys=True),
            'Original adjacent minion')
            for i in minions(c, registry, source.controller) if i in adjacent)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
                              sample_size=1, on_select=PREFIX + 'destroy_neighbor'),) if options else ()

    def destroy_neighbor(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
            raise ResolutionError('Executioner lost its original single sampled neighbor')
        reference = MinionReference(**json.loads(c.choice.choice.options[0].id))
        return (DestroyCapturedMinion(reference, c.source_id),)

    def rat(c):
        cards = tuple(c.state.entities[i] for i in c.state.players[c.player_id].deck
                      if c.state.entities[i].kind == CardType.SPELL)
        return shuffled(c, tuple(CopyCard(CapturedCardCopyMaterial.capture(c.state, card), c.player_id,
            destination=Zone.DECK, mode='current', source_id=c.source_id) for card in cards))

    def rat_draw(c):
        return (DrawMatching(c.player_id, SPELLS, 'skip', source_id=c.source_id),)

    def hellraiser(c):
        if not c.state.players[c.player_id].deck:
            return (BuffCapturedMinion(MinionReference.capture(c.source), 4, 4, c.source_id),)
        return (ChooseFromZone(c.player_id, c.player_id, Zone.DECK, operation='take',
            distinct='entity', source_id=c.source_id, discovery=True),)

    def crook(c):
        return (SpendMana(c.player_id, None, c.source_id, PREFIX + 'spent'),)

    def spent(c):
        result = c.mana_result
        if result is None or (result.player_id, result.source_id, result.requested) != (c.player_id, c.source_id, None):
            raise ResolutionError('Crook requires the original complete all-Mana debit')
        return (SummonFromPool(c.player_id, POOL_ID, minion_cost(result.actual), source_id=c.source_id,
                               cause=SummonCause.capture(c)),)

    def cycle(c):
        if c.target_id is None:
            raise ResolutionError('Life Cycle requires its original selected minion')
        target = c.state.entities[c.target_id]
        cost = quote_unselected_cost(c.state, registry, target).amount
        position = c.state.players[target.controller].board.index(target.id)
        follow = SummonFromPool(target.controller, POOL_ID, minion_cost(cost), source_id=c.source_id,
            position=position, cause=SummonCause.capture(c))
        return (DestroyCapturedMinion(MinionReference.capture(target), c.source_id, (follow,)),)

    def supplicant(c):
        record = play_record(c.state, dict(c.event.data)['play_id'])
        if (record.source_id, record.player_id) != (c.event.source_id, c.event.player_id) or not record.completed:
            raise ResolutionError('Supplicant lost its completed personal spell play')
        if record.player_id != c.player_id or record.kind != CardType.SPELL or record.countered:
            return ()
        query = PoolQuery(kinds=(CardType.SPELL,), collectible=True, min_cost=record.cost,
            max_cost=record.cost, class_mode='other', include_neutral=False)
        return (CastFromPool(c.player_id, POOL_ID, query, source_id=c.source_id),)

    bodies = {VULCANOS: vulcanos, EXECUTIONER: executioner, 'destroy_neighbor': destroy_neighbor,
              RAT: rat, 'rat_draw': rat_draw,
              HELLRAISER: hellraiser, CROOK: crook, 'spent': spent, CYCLE: cycle, SUPPLICANT: supplicant}
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for row in data['cards'] + data['dependencies']:
        raw = row['record']
        cid = raw['id']
        kind = CardType(raw['type'].lower())
        kwargs = {}
        if cid in (EXECUTIONER, RAT, HELLRAISER, CROOK):
            kwargs['battlecry'] = PREFIX + cid
        if cid == VULCANOS:
            kwargs.update(keywords=(Keyword.COLOSSAL,),
                colossal=(AppendageSpec(EXISTING[0], 'left'), AppendageSpec(EXISTING[1], 'right')),
                triggers=(TriggerSpec('turn_ended', PREFIX + cid, EndTurnSpec()),))
        if cid == EXECUTIONER:
            kwargs['disguised'] = True
        if cid == RAT:
            kwargs['deathrattle'] = PREFIX + 'rat_draw'
        if cid == HELLRAISER:
            kwargs['keywords'] = (Keyword.TAUNT,)
        if cid == CROOK:
            kwargs['hand_actions'] = (HandActionSpec('prepare', 'prepare', 1),)
        if cid == CYCLE:
            kwargs.update(on_play=PREFIX + cid, targeting=TargetSpec(TargetMode.REQUIRED,
                zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
        if cid == SUPPLICANT:
            kwargs['triggers'] = (TriggerSpec('card_played', PREFIX + cid),)
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'] or 0, metadata=metadata_from_record(raw),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
