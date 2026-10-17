"""Original stealth attacks, Fabled siblings and native health/Fel consumers."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, ForceAttack,
    InvokeBehavior, RandomDamage, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.fabled_decks import FabledSpec
from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyMinion
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.locations import LocationFaceReference, RefreshLocation
from hs_sim.engine.model import (AppendageSpec, BoardPresenceReference, CardClass, CardDefinition,
    CardType, CostSpec, DamageKind, HandProgressSpec, HealthFlow, Keyword, SpellSchool,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.sacrifice import (BuffCapturedMinion, GrantCapturedKeyword, MinionReference,
    SetCapturedMinionStats, live_minion)
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p64-v1.json'
BATCH_HASH = 'f9d082bd6bc237e597fdf3aa77e8232a3e2d6b766761d3e09b688b68e221ea44'
BLOOD, ASSASSIN, STRIKE, SHAW, SILENCE, STAFF, SYLVANAS, ALLERIA, VEREESA, MASK, PRISON, NESPIRAH = (
    'CATA_300', 'CAP_000', 'CAP_001', 'CAP_005', 'CAP_006', 'JAIL_875',
    'TIME_609', 'TIME_609t1', 'TIME_609t2', 'DINO_428', 'CATA_527', 'CATA_527t2')
ROOTS = (BLOOD, ASSASSIN, STRIKE, SHAW, SILENCE, STAFF, SYLVANAS, ALLERIA, VEREESA, MASK, PRISON, NESPIRAH)
LIMBS = ('CATA_300t1', 'CATA_300t2', 'CATA_300t3')
SISTERS = (SYLVANAS, ALLERIA, VEREESA)
PREFIX, POOL_ID = 'cards.simple_followup_p64.', 'constructed.cards'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS
            or tuple(x['record']['id'] for x in d['existing_dependencies']) != LIMBS
            or any(d[k] for k in ('dependencies', 'skipped'))):
        raise TargetValidationError('P64 complete frozen scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for k in ('cards', 'existing_dependencies', 'evidence_only') for x in d[k]):
        raise TargetValidationError('P64 complete original source changed')
    return d


def automatic(c, material, callback):
    return RequestChoice(c.player_id, (ChoiceOption(json.dumps(material, sort_keys=True), 'Original material'),),
        c.source_id, min_count=0, max_count=0, on_select=PREFIX + callback)


def original(c):
    if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
        raise ResolutionError('P64 automatic continuation lost its original single material')
    return json.loads(c.choice.choice.options[0].id)


def register_simple_followup_p64_cards(registry):
    d = load_batch()
    for cid, pin in d['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('P64 existing appendage changed')

    def stealth_attack(c):
        return c.event is not None and c.event.kind == 'stealth_lost' and dict(c.event.data).get('reason') == 'attack'

    def held_attack(c):
        if not stealth_attack(c): return False
        rows = [r for r in c.state.character_attack_history if r.declaration_event_cursor == c.event.sequence
            and r.declaration.source_id == c.event.source_id and r.source_kind == CardType.MINION]
        return len(rows) == 1

    registry.register_trigger_condition(PREFIX + 'held_attack', held_attack)

    def assassin(c):
        if not stealth_attack(c): return ()
        attacker = c.state.entities[c.event.source_id]
        if attacker.kind != CardType.MINION or attacker.controller != c.player_id: return ()
        return (BuffCapturedMinion(MinionReference.capture(attacker), 2, 2, c.source_id),)

    def shaw(c):
        if not stealth_attack(c): return ()
        attacker = c.state.entities[c.event.source_id]
        if attacker.kind != CardType.MINION or attacker.controller != c.player_id: return ()
        options = tuple(ChoiceOption(json.dumps(asdict(CardReference.capture(c.state.entities[i])), sort_keys=True), 'Original hand card')
            for i in c.state.players[c.player_id].hand)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'shaw_selected'),) if options else ()

    def strike(c):
        ref = MinionReference.capture(c.state.entities[c.target_id])
        return (BuffCapturedMinion(ref, 3, 0, c.source_id), automatic(c, asdict(ref), 'strike_after'))

    def shaw_selected(c):
        material = original(c)
        material['zone'] = Zone(material['zone'])
        ref = CardReference(**material)
        if ref.zone != Zone.HAND or ref.player_id != c.player_id:
            raise ResolutionError('Shaw requires the original friendly hand reference')
        return (ModifyStoredCost(ref, CostSpec(delta=-3), c.source_id),)

    def strike_after(c):
        target = live_minion(c.state, MinionReference(**original(c)))
        return (RandomDamage(minions(c, registry, 3-c.player_id), target.attack, c.source_id, DamageKind.SPELL),
            ) if target is not None and Keyword.STEALTH in target.keywords else ()

    def blood(c):
        result = c.health_result
        if result is None: raise ResolutionError('Blackblood requires its actual original healing result')
        if result.flow != HealthFlow.HEALING.value or result.healed <= 0 or result.source_controller != c.player_id: return ()
        return (AttackRandomEnemyMinion(BoardPresenceReference.capture(c.state, c.source_id), c.player_id, c.source_id),)

    def sister_repeats(c, declaration):
        history = played_cards(c.state, c.player_id, kind=CardType.MINION,
            before_id=c.play.id if c.play is not None else None)
        others = set(SISTERS) - {declaration}
        return 1 + sum(row.card_id in others for row in history)

    def sylvanas(c):
        return tuple(InvokeBehavior(PREFIX + 'sylvanas_wave', c.source_id, c.player_id) for _ in range(sister_repeats(c, SYLVANAS)))

    def vereesa(c):
        return tuple(InvokeBehavior(PREFIX + 'vereesa_wave', c.source_id, c.player_id) for _ in range(sister_repeats(c, VEREESA)))

    def vereesa_wave(c):
        return tuple(BuffStoredCard(CardReference.capture(c.state.entities[i]), 1, 1, c.source_id)
            for i in c.state.players[c.player_id].deck if c.state.entities[i].kind == CardType.MINION)

    def staff(c):
        row = completed_attack(c)
        if row is None or row.source_kind != CardType.HERO or row.declaration.player_id != c.player_id: return ()
        hero = c.state.entities[row.declaration.source_id]
        return (DiscoverFromPool(c.player_id, POOL_ID, PoolQuery(collectible=True, class_mode='specified',
            classes=(CardClass.DRUID,), include_neutral=False), source_id=c.source_id,
            cost=CostSpec(delta=-hero.attack)),)

    def mask(c):
        target = c.state.entities[c.target_id]; ref = MinionReference.capture(target)
        return (SetCapturedMinionStats(ref, 8, 10, c.source_id), GrantCapturedKeyword(ref, Keyword.LIFESTEAL, c.source_id),
            automatic(c, dict(minion=asdict(ref), presence=asdict(BoardPresenceReference.capture(c.state, target.id))), 'mask_ready'))

    def mask_ready(c):
        material = original(c)
        if live_minion(c.state, MinionReference(**material['minion'])) is None: return ()
        defender = BoardPresenceReference(**material['presence'])
        options = tuple(ChoiceOption(json.dumps(dict(attacker=asdict(BoardPresenceReference.capture(c.state, i)),
            defender=asdict(defender)), sort_keys=True), 'Original enemy attacker') for i in minions(c, registry, 3-c.player_id)
            if i != defender.entity_id)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'mask_attack'),) if options else ()

    def mask_attack(c):
        material = original(c)
        return (ForceAttack(BoardPresenceReference(**material['attacker']), BoardPresenceReference(**material['defender']),
            combat_relation='any_minions'),)

    def fel_cast(c):
        cast = cast_record(c.state, dict(c.event.data)['cast_id'])
        if not cast.completed or not cast.payload_started or cast.failure is not None or cast.interrupted:
            raise ResolutionError('Nespirah requires actual successful spell completion')
        return cast.player_id == c.player_id and registry.card(cast.card_id).spell_school == SpellSchool.FEL

    def reopen(c):
        return (automatic(c, asdict(LocationFaceReference.capture(c.state, c.source_id)), 'reopen_ready'),) if fel_cast(c) else ()

    def reopen_ready(c):
        ref = LocationFaceReference(**original(c)); source = c.state.entities[ref.entity_id]
        if (source.zone != Zone.BOARD or source.kind != CardType.LOCATION or not source.active or source.doomed
                or source.durability <= 0 or LocationFaceReference.capture(c.state, source.id) != ref): return ()
        return (RefreshLocation(source.id, c.source_id),)

    def naga(c):
        return (GenerateFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,), collectible=True,
            tribes_any=('naga',), exclude_card_ids=tuple(d['printed_colossal_ids'])), source_id=c.source_id,
            cost=CostSpec(set_to=1)),) if fel_cast(c) else ()

    def silence(c):
        progress = progress_ability(c.source)
        amount = 3 if progress is not None and progress.progress_completions else 1
        return (Damage(c.target_id, amount, c.source_id, DamageKind.SPELL),)

    bodies = {ASSASSIN: assassin, SHAW: shaw, STRIKE: strike, 'strike_after': strike_after,
        'shaw_selected': shaw_selected,
        SILENCE: silence, 'held_done': lambda c: (), BLOOD: blood, SYLVANAS: sylvanas,
        'sylvanas_wave': lambda c: (DamageBatch(tuple(Damage(i, 2, c.source_id, DamageKind.MINION_ABILITY)
            for i in characters(c, registry, 3-c.player_id))),),
        ALLERIA: lambda c: (DiscoverFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.SPELL,),
            collectible=True, class_mode='current'), source_id=c.source_id, discoveries=sister_repeats(c, ALLERIA)),),
        VEREESA: vereesa, 'vereesa_wave': vereesa_wave, STAFF: staff, MASK: mask,
        'mask_ready': mask_ready, 'mask_attack': mask_attack,
        PRISON: lambda c: (Damage(c.target_id, 1, c.source_id),), 'reopen': reopen,
        'reopen_ready': reopen_ready, 'prison_death': lambda c: (SummonByCard(c.player_id,
            (SummonEntryMaterial(NESPIRAH),), SummonCause.capture(c)),), NESPIRAH: naga}
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    for row in d['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kw = {}
        if kind == CardType.SPELL: kw['on_play'] = PREFIX + cid
        if cid in (STRIKE, MASK): kw['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
        if cid in (SILENCE, PRISON): kw['targeting'] = TargetSpec()
        if cid in (ASSASSIN, SHAW): kw.update(keywords=(Keyword.STEALTH,), triggers=(TriggerSpec('stealth_lost', PREFIX + cid),))
        if cid == SILENCE: kw['hand_progress'] = HandProgressSpec('event', 1, on_complete=PREFIX + 'held_done',
            event='stealth_lost', condition_id=PREFIX + 'held_attack')
        if cid == BLOOD: kw.update(keywords=(Keyword.COLOSSAL,), colossal=tuple(AppendageSpec(i, 'left' if n == 0 else 'right')
            for n, i in enumerate(LIMBS)), triggers=(TriggerSpec('health_resolved', PREFIX + cid),))
        if cid in SISTERS: kw['battlecry'] = PREFIX + cid
        if cid == STAFF: kw.update(durability=raw['health'], triggers=(TriggerSpec('attack_finished', PREFIX + cid),))
        if cid == PRISON: kw.update(durability=raw['health'], on_use=PREFIX + cid, deathrattle=PREFIX + 'prison_death',
            triggers=(TriggerSpec('spell_cast_finished', PREFIX + 'reopen'),))
        if cid == NESPIRAH: kw['triggers'] = (TriggerSpec('spell_cast_finished', PREFIX + cid),)
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] if kind in (CardType.MINION, CardType.WEAPON) else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), metadata=metadata_from_record(raw), **kw)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_fabled(FabledSpec(SYLVANAS, (ALLERIA, VEREESA)))
