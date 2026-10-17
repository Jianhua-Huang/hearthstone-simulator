"""Native summons, guarded combat and actual current-type card rewards."""
from dataclasses import asdict, replace
from itertools import combinations
import json
from pathlib import Path

from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.bonus_effects import GrantRandomBonusEffects
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import ChoiceOption, ForceAttack, RandomDamage, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.group_bonus import beneficiaries
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType,
    DamageKind, EndTurnSpec, Keyword, PlayerEffectSpec, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE, RandomSplitDamage
from hs_sim.engine.sacrifice import (BuffCapturedMinion, GrantCapturedDeathrattle,
    MinionReference, live_minion)
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.recruit_summons import RecruitEntryMaterial
from hs_sim.engine.summon_sources import SummonFromStoredCandidates
from hs_sim.engine.tribes import tribe_state
from hs_sim.engine.zones import CardReference, DestroyStoredCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack
from .health_cards import SCHOOLS
from .metadata import RACES, metadata_from_record, validate_race_pin
from .native_followup_cards import characters, deathrattle_position, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p66-v1.json'
BATCH_HASH = 'a19fdf044b70bd8eae7934e66c6bde72415f93b025683f1a43de830c274801cc'
ANKYLODON, HOUND, SPEAR, MAIEV, VINE, HERENN, CHALLENGER, MANASTORM, SPLITTER, MUG, STORYTELLER = (
    'DINO_422', 'FIR_953', 'EDR_842', 'JAIL_850', 'TLC_465', 'TLC_810', 'CORE_BT_120', 'JAIL_122',
    'CATA_979', 'CORE_WON_141', 'TLC_254')
ROOTS = (ANKYLODON, HOUND, SPEAR, MAIEV, VINE, HERENN, CHALLENGER, MANASTORM, SPLITTER, MUG, STORYTELLER)
PREFIX, POOL_ID = 'cards.simple_followup_p66.', 'constructed.cards'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS
            or any(d[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))):
        raise TargetValidationError('P66 original complete scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256'] for k in ('cards', 'evidence_only') for x in d[k]):
        raise TargetValidationError('P66 full original source changed')
    return d


def automatic(c, material, callback):
    return RequestChoice(c.player_id, (ChoiceOption(json.dumps(material, sort_keys=True), 'Original material'),),
        c.source_id, min_count=0, max_count=0, on_select=PREFIX + callback)


def original(c):
    if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
        raise ResolutionError('P66 automatic continuation lost its original material')
    return json.loads(c.choice.choice.options[0].id)


def register_simple_followup_p66_cards(registry):
    d = load_batch(); validate_race_pin()

    def producer(c, family, request):
        history = c.state.pool_summon_history
        material = dict(family=family, previous=[row.id for row in history], cause=canonical_digest(asdict(request.cause)))
        return request, automatic(c, material, 'producer_after')

    def producer_after(c):
        material = original(c); history = c.state.pool_summon_history
        rows = [row for row in history if row.id not in material['previous'] and
            canonical_digest(asdict(row.spec.cause)) == material['cause']]
        if len(rows) != 1 or rows[0].status != 'completed':
            raise ResolutionError('P66 requires its one original complete native producer')
        return tuple(automatic(c, asdict(ref), 'beast_attack') for ref in beneficiaries(c.state, rows[0]))

    def beasts(c):
        return producer(c, 'pool', GenerateFromPool(c.player_id, POOL_ID,
            PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=3, max_cost=3, tribes_any=('beast',)),
            count=2, destination='board', source_id=c.source_id, cause=SummonCause.capture(c), board_position=deathrattle_position(c)))

    def beast_attack(c):
        actor = live_minion(c.state, MinionReference(**original(c)))
        if actor is None: return ()
        attacker = BoardPresenceReference.capture(c.state, actor.id)
        options = tuple(ChoiceOption(json.dumps(dict(attacker=asdict(attacker),
            defender=asdict(BoardPresenceReference.capture(c.state, i)) if c.state.entities[i].kind == CardType.MINION else i),
            sort_keys=True), 'Original current enemy') for i in characters(c, registry, 3-c.player_id))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'beast_selected'),) if options else ()

    def beast_selected(c):
        m = original(c); target = m['defender']
        return (ForceAttack(BoardPresenceReference(**m['attacker']),
            BoardPresenceReference(**target) if isinstance(target, dict) else target),)

    def herenn(c):
        return (automatic(c, dict(remaining=2, refs=[]), 'herenn_select'),)

    def herenn_select(c):
        m = original(c)
        candidates = tuple(CardReference.capture(e) for i in c.state.players[c.player_id].deck
            for e in (c.state.entities[i],) if e.kind == CardType.MINION and active_abilities(e, 'deathrattle'))
        cause = SummonCause.capture(c)
        tail = dict(remaining=m['remaining'], refs=m['refs'], candidates=[asdict(r) for r in candidates],
            previous=[row.id for row in c.state.card_summon_history], cause=canonical_digest(asdict(cause)))
        return (SummonFromStoredCandidates(c.player_id, candidates, cause=cause), automatic(c, tail, 'herenn_after'))

    def herenn_after(c):
        m = original(c); candidates = {canonical_digest(r) for r in m['candidates']}
        rows = [row for row in c.state.card_summon_history if row.id not in m['previous']
            and canonical_digest(asdict(row.request.cause)) == m['cause']
            and len(row.request.materials) == 1 and type(row.request.materials[0]) is RecruitEntryMaterial
            and canonical_digest(asdict(row.request.materials[0].reference)) in candidates]
        if not rows: return ()  # Native empty/full request did not deliver a physical card.
        if len(rows) != 1 or rows[0].status != 'completed':
            raise ResolutionError('Herenn lost its original complete physical selection')
        first = rows[0].deliveries[0] if rows[0].deliveries else None
        ref = None
        if first is not None and first.outcome == 'delivered':
            f = first.entity
            ref = asdict(MinionReference(f.entity_id, f.controller, f.card_id, f.zone_epoch, f.entered_order))
        refs = [*m['refs'], ref]
        if m['remaining'] == 2:
            return (automatic(c, dict(remaining=1, refs=refs), 'herenn_select'),)
        return (automatic(c, refs, 'recruits_fight'),) if len(refs) == 2 and all(refs) else ()

    def recruits_fight(c):
        refs = tuple(MinionReference(**r) for r in original(c)); actors = tuple(live_minion(c.state, r) for r in refs)
        if any(e is None for e in actors): return ()
        return (ForceAttack(*(BoardPresenceReference.capture(c.state, e.id) for e in actors), combat_relation='friendly_minions'),)

    def hound(c):
        row = completed_attack(c)
        if (row is None or row.declaration.source_id != c.source_id or row.source_kind != CardType.MINION
                or row.delivery.attack_target_presence is None): return ()
        return (automatic(c, asdict(row.declaration.attack_source_presence), 'hound_split'),)

    def hound_split(c):
        actor = resolve_board_presence(c.state, BoardPresenceReference(**original(c)))
        if actor is None or actor.controller != c.player_id or not actor.active or actor.health <= 0 or actor.doomed: return ()
        return (RandomSplitDamage(c.player_id, None, c.source_id, actor.attack,
            profile=NON_SPELL_PROFILE, kind=DamageKind.MINION_ABILITY),)

    def spear(c):
        row = completed_attack(c)
        if row is None or row.source_kind != CardType.HERO or row.declaration.player_id != c.player_id: return ()
        defender = row.delivery.attack_target_presence
        candidates = tuple(i for i in characters(c, registry, 3-c.player_id)
            if (BoardPresenceReference.capture(c.state, i) != defender if c.state.entities[i].kind == CardType.MINION else i != row.delivery.target_id))
        hero = c.state.entities[row.declaration.source_id]
        return (RandomDamage(candidates, hero.attack, c.source_id, DamageKind.EFFECT),)

    def maiev(c):
        if c.event.player_id != c.player_id or c.event.source_id is None or c.event.source_id == c.source_id: return ()
        target = c.state.entities[c.event.source_id]
        if target.kind != CardType.MINION or target.zone != Zone.BOARD or target.controller != c.player_id or not target.active or target.doomed or target.health <= 0: return ()
        ref = MinionReference.capture(target)
        return BuffCapturedMinion(ref, 3, 3, c.source_id), automatic(c, asdict(ref), 'sleep_original')

    def sleep_original(c):
        actor = live_minion(c.state, MinionReference(**original(c)))
        return (MakeDormant(actor.id, 1, c.source_id),) if actor is not None else ()

    def vine(c):
        options = tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])), sort_keys=True),
            'Original friendly minion') for i in minions(c, registry, c.player_id))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'vine_bonus'),) if options else ()

    def vine_bonus(c):
        ref = MinionReference(**original(c))
        if live_minion(c.state, ref) is None: return ()
        return GrantRandomBonusEffects(ref.entity_id, 1, c.source_id), automatic(c, asdict(ref), 'vine_grant')

    def vine_grant(c):
        return (GrantCapturedDeathrattle(MinionReference(**original(c)), PREFIX + 'vine', c.source_id),)

    def challenger(c):
        if c.target_id is None: return ()
        refs = (MinionReference.capture(c.source), MinionReference.capture(c.state.entities[c.target_id]))
        return (automatic(c, dict(refs=[asdict(r) for r in refs]), 'battle'),)

    def battle(c):
        m = original(c); refs = tuple(MinionReference(**r) for r in m['refs'])
        actors = tuple(live_minion(c.state, r) for r in refs)
        if any(e is None for e in actors): return ()
        previous = m.get('previous')
        if previous is not None and not any(row.declaration.id not in previous and row.terminal is not None
                and row.terminal.status == 'completed' and row.declaration.source_id == refs[0].entity_id
                for row in c.state.character_attack_history): return ()
        tail = dict(refs=m['refs'], previous=[row.declaration.id for row in c.state.character_attack_history])
        return (ForceAttack(*(BoardPresenceReference.capture(c.state, e.id) for e in actors)), automatic(c, tail, 'battle'))

    def storm(c):
        if c.event.player_id != c.player_id: return ()
        cast = cast_record(c.state, dict(c.event.data)['cast_id'])
        if not cast.completed or not cast.payload_started or cast.interrupted or cast.failure is not None:
            raise ResolutionError('Manastorm requires an actual successful completed spell')
        cost = registry.card(cast.card_id).cost
        return (GenerateFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,), collectible=True,
            min_cost=cost, max_cost=cost), destination='board', source_id=c.source_id, cause=SummonCause.capture(c)),)

    def split(c):
        options = tuple(ChoiceOption(json.dumps(dict(reference=asdict(CardReference.capture(e)),
            cost=quote_unselected_cost(c.state, registry, e).amount), sort_keys=True), registry.card(e.card_id).name,
            card_id=e.card_id, entity_id=e.id) for i in c.state.players[c.player_id].hand
            for e in (c.state.entities[i],) if e.kind == CardType.SPELL)
        return (RequestChoice(c.player_id, options, c.source_id, on_select=PREFIX + 'split_selected'),) if options else ()

    def split_selected(c):
        if c.choice is None or len(c.choice.selected) != 1: raise ResolutionError('Split lost its selected original spell')
        m = json.loads(c.choice.selected[0].id); r = dict(m['reference']); r['zone'] = Zone(r['zone'])
        request = GenerateFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.SPELL,), collectible=True,
            min_cost=m['cost'], max_cost=m['cost']), count=2, source_id=c.source_id)
        return (DestroyStoredCard(CardReference(**r), c.source_id, on_destroy=(request,)),)

    def tribe_group(c, limit):
        typed = []
        states = []
        for i in minions(c, registry, c.player_id):
            e = c.state.entities[i]; state = tribe_state(registry, e)
            if state is None: raise ResolutionError('Distinct-type recipient facts are unknown: ' + e.card_id)
            typed.append(MinionReference.capture(e)); states.append(state)
        # The pinned client race table supplies the actual constructed universe,
        # independently of executable coverage. Explicit current types extend it.
        universe = set(RACES.values()) - {'all'}
        for state in states: universe.update(set(state.members) - {'all'}); universe.update(state.excluded)
        choices = [tuple(t for t in sorted(universe) if state.matches_any((t,))) for state in states]
        def distinct(indices, offset=0, used=frozenset()):
            return offset == len(indices) or any(distinct(indices, offset+1, used | {t})
                for t in choices[indices[offset]] if t not in used)
        groups = ()
        for size in range(min(limit, len(typed)), 0, -1):
            groups = tuple(group for group in combinations(range(len(typed)), size) if distinct(group))
            if groups: break
        options = tuple(ChoiceOption(json.dumps([asdict(typed[i]) for i in group], sort_keys=True),
            'Original different-type minions') for group in groups)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'tribe_selected'),) if options else ()

    def tribe_selected(c):
        return tuple(BuffCapturedMinion(MinionReference(**r), 1, 1, c.source_id) for r in original(c))

    bodies = dict(beasts=beasts, producer_after=producer_after,
        beast_attack=beast_attack, beast_selected=beast_selected, herenn=herenn,
        herenn_select=herenn_select, herenn_after=herenn_after, recruits_fight=recruits_fight,
        hound=hound, hound_split=hound_split, spear=spear, maiev=maiev, sleep_original=sleep_original,
        vine=vine, vine_bonus=vine_bonus, vine_grant=vine_grant, challenger=challenger, battle=battle,
        install_storm=lambda c: (AddPlayerEffect(c.player_id, PREFIX + 'storm', c.source_id),), storm=storm,
        split=split, split_selected=split_selected, mug=lambda c: tribe_group(c, 3),
        storyteller=lambda c: tribe_group(c, len(c.state.players[c.player_id].board)), tribe_selected=tribe_selected)
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    registry.register_player_effect(PlayerEffectSpec(PREFIX + 'storm', MANASTORM,
        triggers=(TriggerSpec('spell_cast_finished', PREFIX + 'storm'),)))
    for item in d['cards']:
        raw = item['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kw = {}
        if cid in (HERENN, CHALLENGER, MANASTORM, SPLITTER, MUG):
            kw['battlecry'] = PREFIX + {HERENN:'herenn', CHALLENGER:'challenger', MANASTORM:'install_storm', SPLITTER:'split', MUG:'mug'}[cid]
        if cid == CHALLENGER: kw['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy', mode=TargetMode.IF_AVAILABLE)
        if cid == ANKYLODON: kw.update(keywords=(Keyword.TAUNT,), deathrattle=PREFIX + 'beasts')
        if cid == VINE: kw['deathrattle'] = PREFIX + 'vine'
        if cid in (HOUND, SPEAR):
            kw['triggers'] = (TriggerSpec('attack_finished', PREFIX + ('hound' if cid == HOUND else 'spear')),)
            if cid == HOUND: kw['keywords'] = (Keyword.RUSH,)
        if cid == MAIEV: kw['triggers'] = (TriggerSpec('card_played', PREFIX + 'maiev'),)
        if cid == STORYTELLER: kw['triggers'] = (TriggerSpec('turn_ended', PREFIX + 'storyteller', EndTurnSpec()),)
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], attack=raw['attack'] if kind in (CardType.MINION,CardType.WEAPON) else 0,
            health=raw['health'] if kind == CardType.MINION else 0, durability=raw['health'] if kind == CardType.WEAPON else 0,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=metadata_from_record(raw), **kw)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
