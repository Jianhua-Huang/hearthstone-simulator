"""Original distance plans and completed native producer delivery consumers."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.native_hand_targets import hand_target
from hs_sim.engine.bonus_effects import GrantRandomBonusEffects
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, Draw, ForceAttack,
    InvokeBehavior, RequestChoice, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.group_bonus import beneficiaries
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType, CostSpec,
    DamageKind, EndTurnSpec, HandProgressSpec, Keyword, RewindSpec, SpellSchool, TargetSpec,
    TriggerSpec, Zone)
from hs_sim.engine.ordered_group_batches import SummonOrderedGroup
from hs_sim.engine.ordered_summon_groups import OrderedGroupMember, OrderedSummonGroupSpec
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference, live_minion
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause, SummonEntryMaterial
from hs_sim.engine.targeting import accepts_target
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p65-v1.json'
BATCH_HASH = '8fb94204f8cc8ebffc846c00f033097dbc81ee2ed8604440a66cd6a9fe62d790'
MOTHER, DRAKREST, TOTEM, UMBRA, SHOT, ANCESTOR, WORMHOLE, SHADES, RIFT, OSK = (
    'BE_036', 'DINO_401', 'DINO_412', 'DINO_415', 'JAIL_515', 'TIME_213',
    'TIME_602', 'TIME_610', 'BE_EVENT_102', 'TLC_452t34')
ROOTS = (MOTHER, DRAKREST, TOTEM, UMBRA, SHOT, ANCESTOR, WORMHOLE, SHADES, RIFT, OSK)
SHADE = 'TIME_610t2'
PREFIX, POOL_ID = 'cards.simple_followup_p65.', 'constructed.cards'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS
            or tuple(x['record']['id'] for x in d['existing_dependencies']) != (SHADE,)
            or any(d[k] for k in ('dependencies', 'skipped'))):
        raise TargetValidationError('P65 complete frozen scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for k in ('cards', 'existing_dependencies', 'evidence_only') for x in d[k]):
        raise TargetValidationError('P65 complete original source changed')
    return d


def automatic(c, material, callback):
    return RequestChoice(c.player_id, (ChoiceOption(json.dumps(material, sort_keys=True), 'Original material'),),
        c.source_id, min_count=0, max_count=0, on_select=PREFIX + callback)


def original(c):
    if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
        raise ResolutionError('P65 automatic continuation lost its original single material')
    return json.loads(c.choice.choice.options[0].id)


def require_cast(c, cid):
    if c.cast is None or (c.cast.source_id, c.cast.player_id, c.cast.card_id) != (c.source_id, c.player_id, cid):
        raise ResolutionError('P65 producer continuation lost its original physical spell')
    return c.cast


def produced_refs(c, cid, family):
    cast = require_cast(c, cid)
    history = {'discovery': c.state.discovery_summon_history,
        'pool': c.state.pool_summon_history, 'ordered': c.state.ordered_group_history}[family]
    def cause(row): return row.request.group.cause if family == 'ordered' else row.spec.cause
    rows = [row for row in history if cause(row).cast_id == cast.id
        and (cause(row).source.entity_id, cause(row).player_id, cause(row).cast_card_id) == (c.source_id, c.player_id, cid)]
    if len(rows) != 1 or rows[0].status != 'completed':
        raise ResolutionError('P65 requires exactly its original complete native producer')
    return beneficiaries(c.state, rows[0])


def register_simple_followup_p65_cards(registry):
    d = load_batch()
    if canonical_digest(asdict(registry.card(SHADE))) != d['existing_dependency_definition_pins'][SHADE]:
        raise TargetValidationError('P65 original Shade dependency changed')

    def mother(c):
        refs = tuple(CardReference.capture(c.state.entities[i]) for i in c.state.players[c.player_id].hand)
        options = []
        for chosen, ref in enumerate(refs):
            order = (chosen,) + tuple(i for distance in range(1, 5) for i in (chosen-distance, chosen+distance) if 0 <= i < len(refs))
            effects = tuple(ModifyStoredCost(refs[i], CostSpec(delta=-(5-abs(i-chosen))), c.source_id) for i in order)
            options.append(ChoiceOption(str(ref.entity_id), registry.card(ref.card_id).name, effects, card_id=ref.card_id, entity_id=ref.entity_id))
        return (RequestChoice(c.player_id, tuple(options), c.source_id, targeting=hand_target()),) if options else ()

    def rift(c):
        cast = require_cast(c, RIFT); target = c.state.entities[c.target_id]
        board = c.state.players[target.controller].board; center = board.index(target.id)
        budget = 5 + spell_bonus(c.state, c.player_id, registry, registry.card(RIFT).spell_school, cast_id=cast.id)
        order = (center,) + tuple(i for distance in range(1, budget) for i in (center-distance, center+distance) if 0 <= i < len(board))
        return tuple(automatic(c, dict(reference=asdict(BoardPresenceReference.capture(c.state, e.id)),
            amount=budget-abs(i-center)), 'rift_hit') for i in order for e in (c.state.entities[board[i]],)
            if e.kind == CardType.MINION and e.active and e.health > 0 and not e.doomed and registry.card(e.card_id).interactable is None)

    def rift_hit(c):
        material = original(c); target = resolve_board_presence(c.state, BoardPresenceReference(**material['reference']))
        if target is None or target.kind != CardType.MINION or not target.active or target.health <= 0 or target.doomed: return ()
        return (Damage(target.id, material['amount'], c.source_id, DamageKind.SPELL, spell_bonus_multiplier=0),)

    def drakrest(c):
        row = completed_attack(c)
        if row is None or row.source_kind != CardType.MINION or row.declaration.source_id != c.source_id or row.delivery.attack_target_presence is None: return ()
        return (automatic(c, dict(attacker=asdict(row.declaration.attack_source_presence),
            defender=asdict(row.delivery.attack_target_presence)), 'drakrest_now'),)

    def drakrest_now(c):
        material = original(c); actor = resolve_board_presence(c.state, BoardPresenceReference(**material['attacker']))
        if actor is None or not actor.active or actor.health <= 0 or actor.doomed or actor.controller != c.player_id: return ()
        previous = BoardPresenceReference(**material['defender'])
        return (DamageBatch(tuple(Damage(i, actor.attack, actor.id, DamageKind.MINION_ABILITY)
            for i in minions(c, registry, 3-c.player_id) if BoardPresenceReference.capture(c.state, i) != previous)),)

    def totem(c):
        known = [(cid, row.metadata.tribes) for cid, row in registry.pool_cards.items()
            if row.kind == CardType.MINION and row.metadata is not None and row.metadata.tribes is not None]
        excluded = tuple(sorted(cid for cid, tribes in known if 'all' not in tribes and len(set(tribes)) < 2))
        operands = tuple(sorted({'all'} | {tribe for _, tribes in known for tribe in tribes}))
        return (GenerateFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,), collectible=True,
            tribes_any=operands, exclude_card_ids=excluded), source_id=c.source_id),)

    registry.register_trigger_condition(PREFIX + 'nature', lambda c: c.cast is not None
        and c.cast.player_id == c.player_id and registry.card(c.cast.card_id).spell_school == SpellSchool.NATURE)

    def ancestor(c):
        progress = progress_ability(c.source)
        if progress is None: raise ResolutionError('Ancestor requires its original declared held Nature facts')
        return (BuffCapturedMinion(MinionReference.capture(c.source), 1, 1, c.source_id),
            Draw(c.player_id, 1, c.source_id)) if progress.progress_completions else ()

    def shot_result(c):
        if c.health_result is None: raise ResolutionError('Shadow Barrage requires its original committed health result')
        return (InvokeHealthResult(PREFIX + 'shot_death', c.event),)

    def shot_death(c):
        result = c.health_result
        died = result.target_id == result.original_target_id and any(death.entity_id == result.original_target_id
            and death.cause is not None and death.cause.kind in ('damage', 'poison')
            and death.cause.result == result.payload() for death in c.state.death_history)
        if not died or not any(accepts_target(c.state, registry, c.source, registry.card(SHOT), i, automatic=True)
                for i in c.state.entities): return ()
        return (CastSpell(c.player_id, SHOT, c.source_id),)

    def umbra_after(c):
        return tuple(automatic(c, asdict(ref), 'trigger_original') for ref in produced_refs(c, UMBRA, 'discovery'))

    def trigger_original(c):
        ref = MinionReference(**original(c))
        return (TriggerDeathrattles(ref.entity_id, c.source_id),) if live_minion(c.state, ref) is not None else ()

    def worm_after(c):
        return tuple(automatic(c, asdict(ref), 'worm_ready') for ref in produced_refs(c, WORMHOLE, 'pool'))

    def worm_ready(c):
        ref = MinionReference(**original(c)); actor = live_minion(c.state, ref)
        if actor is None: return ()
        attacker = BoardPresenceReference.capture(c.state, actor.id)
        options = tuple(ChoiceOption(json.dumps(dict(attacker=asdict(attacker), defender=asdict(BoardPresenceReference.capture(c.state, i))
            if c.state.entities[i].kind == CardType.MINION else i), sort_keys=True), 'Original current enemy character')
            for i in characters(c, registry, 3-c.player_id))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'worm_attack'),) if options else ()

    def worm_attack(c):
        material = original(c); defender = material['defender']
        return (ForceAttack(BoardPresenceReference(**material['attacker']),
            BoardPresenceReference(**defender) if isinstance(defender, dict) else defender),)

    def shades(c):
        members = tuple(OrderedGroupMember('shade.' + str(i), SummonEntryMaterial(SHADE)) for i in range(4))
        return (SummonOrderedGroup(OrderedSummonGroupSpec(c.player_id, SummonCause.capture(c), members)),
            InvokeBehavior(PREFIX + 'shades_after', c.source_id, c.player_id))

    def shades_after(c):
        return tuple(automatic(c, dict(reference=asdict(ref), remaining=2), 'shade_bonus')
            for ref in produced_refs(c, SHADES, 'ordered'))

    def shade_bonus(c):
        material = original(c); ref = MinionReference(**material['reference'])
        if live_minion(c.state, ref) is None: return ()
        remaining = material['remaining']
        if type(remaining) is not int or remaining not in (1, 2): raise ResolutionError('Shade lost its bounded two original rewards')
        return (GrantRandomBonusEffects(ref.entity_id, 1, c.source_id),
            *((automatic(c, dict(reference=asdict(ref), remaining=remaining-1), 'shade_bonus'),) if remaining > 1 else ()))

    def osk(c):
        return tuple(automatic(c, asdict(MinionReference.capture(c.state.entities[i])), 'osk_ready')
            for i in minions(c, registry, 3-c.player_id))

    def osk_ready(c):
        actor = live_minion(c.state, MinionReference(**original(c)))
        if actor is None: return ()
        attacker = BoardPresenceReference.capture(c.state, actor.id)
        options = tuple(ChoiceOption(json.dumps(dict(attacker=asdict(attacker), defender=asdict(BoardPresenceReference.capture(c.state, i))),
            sort_keys=True), 'Original current other enemy minion') for i in minions(c, registry, 3-c.player_id) if i != actor.id)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'osk_attack'),) if options else ()

    def osk_attack(c):
        material = original(c)
        return (ForceAttack(BoardPresenceReference(**material['attacker']), BoardPresenceReference(**material['defender']),
            combat_relation='friendly_minions'),)

    bodies = {MOTHER: mother, RIFT: rift, 'rift_hit': rift_hit, DRAKREST: drakrest, 'drakrest_now': drakrest_now,
        TOTEM: totem, ANCESTOR: ancestor, 'nature_done': lambda c: (),
        SHOT: lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL, PREFIX + 'shot_result'),),
        'shot_result': shot_result, 'shot_death': shot_death,
        UMBRA: lambda c: (DiscoverFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,), collectible=True,
            min_cost=5, deathrattle=True, class_mode='current'), destination='board', cause=SummonCause.capture(c), source_id=c.source_id),
            InvokeBehavior(PREFIX + 'umbra_after', c.source_id, c.player_id)), 'umbra_after': umbra_after,
        'trigger_original': trigger_original,
        WORMHOLE: lambda c: (GenerateFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,), collectible=True,
            min_cost=3, max_cost=3, tribes_any=('beast',)), destination='board', source_id=c.source_id,
            cause=SummonCause.capture(c)), InvokeBehavior(PREFIX + 'worm_after', c.source_id, c.player_id)),
        'worm_after': worm_after, 'worm_ready': worm_ready, 'worm_attack': worm_attack,
        SHADES: shades, 'shades_after': shades_after, 'shade_bonus': shade_bonus,
        OSK: osk, 'osk_ready': osk_ready, 'osk_attack': osk_attack}
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    for row in d['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kw = {}
        if kind == CardType.SPELL: kw['on_play'] = PREFIX + cid
        if cid in (MOTHER, ANCESTOR, OSK): kw['battlecry'] = PREFIX + cid
        if cid == DRAKREST: kw.update(keywords=(Keyword.RUSH,), triggers=(TriggerSpec('attack_finished', PREFIX + cid),))
        if cid == TOTEM: kw['triggers'] = (TriggerSpec('turn_ended', PREFIX + cid, EndTurnSpec()),)
        if cid == ANCESTOR: kw['hand_progress'] = HandProgressSpec('event', 1, on_complete=PREFIX + 'nature_done',
            event='spell_cast_accepted', condition_id=PREFIX + 'nature')
        if cid in (WORMHOLE, SHADES): kw.update(keywords=(Keyword.REWIND,), rewind=RewindSpec())
        if cid in (RIFT, SHOT): kw['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy' if cid == SHOT else 'any')
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=(raw['attack'] if raw['attack'] is not None else d['numeric_normalizations'][cid]['attack']) if kind == CardType.MINION else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), metadata=metadata_from_record(raw), **kw)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
