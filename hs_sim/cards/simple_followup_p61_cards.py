"""Frozen public choices, original location faces and ordinary effect consumers."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.cross_zone import TransformMinionIntoCopy
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Damage, DestroyBatch, GrantDeathrattle,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.locations import AdvanceLocationFace, LocationFaceReference
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, DamageKind, Keyword,
    TargetMode, TargetSpec, Zone)
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import (BuffCapturedMinion, GrantCapturedKeyword,
    MinionReference, SetCapturedMinionStats, live_minion)
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.targeting import target_choices
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p61-v1.json'
BATCH_HASH = '7a936978f6a63676e3b530e5b4d814a91de82be118227f146db6673d32e5cc2c'
DANCE, ROAR, WAVES, ANNIHILATION = 'DINO_414', 'CATA_554', 'TIME_701', 'JAIL_510'
PAST, PRESENT, FUTURE, HOLD = 'TIME_044', 'TIME_044t1', 'TIME_044t2', 'TIME_446'
CENARIUS, SPIRIT, ANCIENT = 'EDR_209', 'EDR_261', 'EDR_209t5'
ROOTS = (DANCE, ROAR, WAVES, ANNIHILATION, PAST, PRESENT, FUTURE, HOLD, CENARIUS, SPIRIT)
PREFIX, POOL_ID = 'cards.simple_followup_p61.', 'constructed.cards'
DEMONS = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=5, tribes_any=('demon',))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS
            or tuple(x['record']['id'] for x in data['existing_dependencies']) != (ANCIENT,)
            or tuple(x['record']['id'] for x in data['evidence_only']) != ('CATA_307', 'CATA_307e')
            or any(data[k] for k in ('dependencies', 'skipped'))):
        raise TargetValidationError('P61 frozen complete scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for x in data['cards'] + data['existing_dependencies'] + data['evidence_only']):
        raise TargetValidationError('P61 complete original source changed')
    return data


def register_simple_followup_p61_cards(registry):
    data = load_batch()
    if canonical_digest(asdict(registry.card(ANCIENT))) != data['existing_dependency_definition_pins'][ANCIENT]:
        raise TargetValidationError('P61 existing Ancient dependency changed')

    def targets(c, relation='any'):
        domain = replace(registry.card(c.source.card_id), targeting=TargetSpec(TargetMode.IF_AVAILABLE,
            zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation=relation))
        return tuple(i for i in target_choices(c.state, registry, c.source, domain) if i is not None)

    def dance(c):
        ref = MinionReference.capture(c.state.entities[c.target_id])
        options = tuple(ChoiceOption(str(i), registry.card(c.state.entities[i].card_id).name,
            (TransformMinionIntoCopy(ref, MinionReference.capture(c.state.entities[i]), c.source_id),),
            entity_id=i) for i in targets(c) if i != c.target_id)
        return (RequestChoice(c.player_id, options, c.source_id,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))),) if options else ()

    def roar(c):
        dragon = any(has_any_tribe(registry, c.state.entities[i], ('dragon',))
            for i in c.state.players[c.player_id].hand)
        first = SetCapturedMinionStats(MinionReference.capture(c.state.entities[c.target_id]),
            health=1, source_id=c.source_id)
        return (first, InvokeBehavior(PREFIX + 'roar_second', c.source_id, c.player_id, c.target_id)) if dragon else (first,)

    def roar_second(c):
        options = tuple(ChoiceOption(str(i), registry.card(c.state.entities[i].card_id).name,
            (SetCapturedMinionStats(MinionReference.capture(c.state.entities[i]), health=1, source_id=c.source_id),),
            entity_id=i) for i in targets(c, 'enemy') if i != c.target_id)
        return (RequestChoice(c.player_id, options, c.source_id,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy')),) if options else ()

    def waves(c):
        options = tuple(ChoiceOption(canonical_digest(asdict(CardReference.capture(c.state.entities[i]))),
            registry.card(c.state.entities[i].card_id).name, card_id=c.state.entities[i].card_id, entity_id=i)
            for i in c.state.players[c.player_id].deck)
        return (RequestChoice(c.player_id, options, c.source_id, sample_size=min(3, len(options)),
            on_select=PREFIX + 'waves_selected'),) if options else ()

    def waves_selected(c):
        if c.choice is None or len(c.choice.selected_ids) != 1:
            raise ResolutionError('Waveshaping requires its original single selection')
        refs = {canonical_digest(asdict(ref)): ref for i in c.state.players[c.player_id].deck
            for ref in (CardReference.capture(c.state.entities[i]),)}
        offered = tuple(o.id for o in c.choice.choice.options)
        selected = c.choice.selected_ids[0]
        if selected not in offered: raise ResolutionError('Waveshaping lost its original offered card')
        order = (selected,) + tuple(i for i in offered if i != selected)
        return tuple(MoveCard(refs[key], c.player_id, Zone.HAND if key == selected else Zone.DECK,
            position='bottom', source_id=c.source_id) for key in order if key in refs)

    def annihilation(c):
        targets = tuple(i for player in (1, 2) for i in minions(c, registry, player))
        return (DestroyBatch(targets, c.source_id), InvokeBehavior(PREFIX + 'annihilation_recruit', c.source_id, c.player_id))

    def annihilation_recruit(c):
        refs = tuple(CardReference.capture(c.state.entities[i]) for i in c.state.players[c.player_id].deck[-3:]
            if c.state.entities[i].kind == CardType.MINION and has_any_tribe(registry, c.state.entities[i], ('demon',)))
        return tuple(SummonStoredCard(ref, c.player_id, cause=SummonCause.capture(c)) for ref in refs)

    def gnomeregan(c):
        ref = MinionReference.capture(c.state.entities[c.target_id])
        face = LocationFaceReference.capture(c.state, c.source_id)
        effects = []
        if face.card_id != PAST: effects.append(GrantDeathrattle(ref.entity_id, PREFIX + 'gnome_death', c.source_id))
        effects.append(BuffCapturedMinion(ref, 2, 1, c.source_id))
        if face.card_id == FUTURE: effects.append(GrantCapturedKeyword(ref, Keyword.DIVINE_SHIELD, c.source_id))
        else: effects.append(AdvanceLocationFace(face, PRESENT if face.card_id == PAST else FUTURE, c.source_id))
        return tuple(effects)

    def hold_condition(c):
        return () if any(c.state.entities[i].kind == CardType.MINION for i in c.state.players[c.player_id].deck) else (
            AddCostModifier(c.player_id, CostSpec(set_to=1, card_types=(CardType.MINION,)), uses_remaining=1, source_id=c.source_id),)

    def cenarius(c):
        return tuple(RequestChoice(c.player_id, (ChoiceOption('buff', 'Give your other minions +1/+3'),
            ChoiceOption('summon', 'Summon a 5/5 Ancient with Taunt')), c.source_id,
            on_select=PREFIX + 'cenarius_selected') for _ in range(3))

    def cenarius_selected(c):
        if c.choice is None or len(c.choice.selected_ids) != 1: raise ResolutionError('Cenarius lost its original choice')
        if c.choice.selected_ids == ('summon',):
            return (SummonByCard(c.player_id, (SummonEntryMaterial(ANCIENT),), SummonCause.capture(c)),)
        if c.choice.selected_ids != ('buff',): raise ResolutionError('Unknown Cenarius branch')
        return tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[i]), 1, 3, c.source_id)
            for i in minions(c, registry, c.player_id) if i != c.source_id)

    def spirit_grant(c, ref):
        return (GrantDeathrattle(ref.entity_id, PREFIX + 'spirit_death', c.source_id), BuffCapturedMinion(ref, 2, 2, c.source_id))

    def spirit_death(c):
        options = tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])), sort_keys=True),
            'Original friendly minion', entity_id=i) for i in minions(c, registry, c.player_id))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'spirit_selected'),) if options else ()

    def spirit_selected(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
            raise ResolutionError('Spirit lost its original single random recipient')
        ref = MinionReference(**json.loads(c.choice.choice.options[0].id))
        return spirit_grant(c, ref) if live_minion(c.state, ref) is not None else ()

    bodies = {DANCE: dance, ROAR: roar, 'roar_second': roar_second, WAVES: waves, 'waves_selected': waves_selected,
        ANNIHILATION: annihilation, 'annihilation_recruit': annihilation_recruit,
        'gnome': gnomeregan, 'gnome_death': lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 2,
            c.source_id, DamageKind.MINION_ABILITY),), HOLD: lambda c: (DiscoverFromPool(c.player_id, POOL_ID, DEMONS,
            source_id=c.source_id), InvokeBehavior(PREFIX + 'hold_condition', c.source_id, c.player_id)),
        'hold_condition': hold_condition, CENARIUS: cenarius, 'cenarius_selected': cenarius_selected,
        SPIRIT: lambda c: spirit_grant(c, MinionReference.capture(c.state.entities[c.target_id])),
        'spirit_death': spirit_death, 'spirit_selected': spirit_selected}
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    target = TargetSpec(TargetMode.REQUIRED, zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    for row in data['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kw = {}
        if cid in (DANCE, ROAR, WAVES, SPIRIT, CENARIUS, ANNIHILATION): kw['on_play'] = PREFIX + cid
        if cid in (DANCE, SPIRIT): kw['targeting'] = target
        if cid == ROAR: kw['targeting'] = replace(target, relation='enemy')
        if kind == CardType.LOCATION:
            kw.update(durability=raw['health'], on_use=PREFIX + (cid if cid == HOLD else 'gnome'))
            if cid != HOLD: kw['targeting'] = target
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] if kind == CardType.MINION else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), metadata=metadata_from_record(raw), **kw)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
