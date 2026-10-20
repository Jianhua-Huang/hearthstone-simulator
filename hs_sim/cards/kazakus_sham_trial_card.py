"""Godfather Kazakus: original trial choices composed from shared effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope
from hs_sim.engine.effects import ChangeControl, ChoiceOption, Draw, Heal, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.forced_attack_sequences import ForceEachMinionAttack
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, CostSpec, HealingKind, Zone
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sham_trials import (BeginShamTrial, CraftShamTrial, ShamTrialProfile,
    TrialComponent, TrialTier)
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, ModifyStoredCost, MoveCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

CARD = 'CAP_405'
VOIDLORD = 'CORE_LOOT_368'
PREFIX = 'cards.kazakus_trial.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/kazakus-sham-trial-v1.json'
BATCH_HASH = 'f26831960eaa772722d9de02d3ef59bf6479e0418f2b2183cf459391e109f001'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    rows = tuple(r for key in ('cards', 'dependencies', 'choice_only', 'existing_dependencies', 'evidence_only') for r in data[key])
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != (CARD,) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in rows) or
            len(data['choice_only']) != 12 or len(data['dependencies']) != 3 or len(rows) != 19):
        raise TargetValidationError('Trial requires the complete original root, choices, templates and existing Voidlord')
    return data


def register_kazakus_sham_trial_card(registry):
    data = load_batch()
    for cid, pin in data['existing_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('Trial changed its existing complete Voidlord dependency')

    def cast(c):
        if c.cast is None: raise ResolutionError('An immediate trial requires its actual CAST')
        return (BeginShamTrial(cast_id=c.cast.id),)

    def expire(c):
        if c.player_effect is None or c.event is None or c.event.kind != 'player_effect_expired':
            raise ResolutionError('A delayed trial requires its original player-clock expiry')
        return (BeginShamTrial(instance=c.player_effect, expiry_sequence=c.event.sequence),)

    def uninitialized(c): raise ResolutionError('An uninitialized trial has no selected original recipe')

    def steal(c):
        choices = tuple(ChoiceOption(json.dumps(asdict(CardReference.capture(c.state.entities[eid])), sort_keys=True),
            '随机手牌') for eid in c.state.players[3-c.player_id].hand)
        return (RequestChoice(c.player_id, choices, c.source_id, min_count=0, max_count=0,
            sample_size=min(2, len(choices)), on_select=PREFIX+'take_hand'),) if choices else ()

    def take_hand(c):
        if c.choice is None or c.choice.selected_ids or not 1 <= len(c.choice.choice.options) <= 2:
            raise ResolutionError('Trial theft requires its original automatic sampled cards')
        result = []
        for option in c.choice.choice.options:
            row = json.loads(option.id); row['zone'] = Zone(row['zone'])
            result.append(MoveCard(CardReference(**row), c.player_id, Zone.HAND, source_id=c.source_id))
        return tuple(result)

    def control(c):
        choices = tuple(ChoiceOption(json.dumps(asdict(BoardPresenceReference.capture(c.state, eid)), sort_keys=True),
            '随机敌方随从') for eid in minions(c, registry, 3-c.player_id))
        return (RequestChoice(c.player_id, choices, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX+'take_control'),) if choices else ()

    def take_control(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
            raise ResolutionError('Trial control requires its original automatic sampled residence')
        ref = BoardPresenceReference(**json.loads(c.choice.choice.options[0].id))
        entity = resolve_board_presence(c.state, ref)
        if entity is None or not entity.active or entity.health <= 0 or entity.doomed or entity.controller != 3-c.player_id:
            return ()
        return (ChangeControl(entity.id, c.player_id),)

    def discount(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[eid]),
            CostSpec(delta=-2, card_types=(CardType.MINION,)), c.source_id)
            for eid in c.state.players[c.player_id].hand if c.state.entities[eid].kind == CardType.MINION)

    bodies = {
        'craft': lambda c: (CraftShamTrial(c.player_id, c.source_id, CARD),),
        'cast': cast, 'expire': expire, 'uninitialized': uninitialized,
        'take_hand': take_hand, 'take_control': take_control,
        'CAP_405t1': lambda c: (ForceEachMinionAttack(),),
        'CAP_405t2': control, 'CAP_405t3': steal,
        'CAP_405t4': lambda c: (Draw(c.player_id, 3, c.source_id),),
        'CAP_405t5': lambda c: (BuffMinionsInZones(c.player_id, 3, 3,
            MinionScope(zones=(Zone.HAND, Zone.BOARD)), c.source_id),),
        'CAP_405t6': lambda c: (GenerateFromPool(c.player_id, 'constructed.minions',
            PoolQuery(kinds=(CardType.MINION,), min_cost=3, max_cost=3, collectible=True),
            count=3, destination='board', source_id=c.source_id, cause=SummonCause.capture(c)),),
        'CAP_405t7': discount,
        'CAP_405t8': lambda c: (Heal(c.state.players[c.player_id].hero_id, 12, c.source_id, HealingKind.SPELL),),
        'CAP_405t9': lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(VOIDLORD),), SummonCause.capture(c)),),
    }
    for name, body in bodies.items(): registry.register_behavior(PREFIX+name, body)
    templates = {t['template_card_id'] for t in data['tiers']}
    for item in (*data['cards'], *data['dependencies'], *data['choice_only']):
        raw = item['record']; cid = raw['id']; meta = metadata_from_record(raw)
        if canonical_digest(asdict(meta)) != canonical_digest(item['metadata']): raise TargetValidationError('Trial metadata changed')
        fields = dict(battlecry=PREFIX+'craft', attack=raw['attack'], health=raw['health']) if cid == CARD else (
            dict(manual_playable=False, on_play=PREFIX+'uninitialized') if cid in templates else dict(choice_only=True))
        # One exact Chinese localization is empty; the verified primary fallback
        # is the complete English name, never an invented replacement effect.
        definition = CardDefinition(cid, raw['name'] or raw['name_en'], CardType(raw['type'].lower()),
            cost=0 if raw['cost'] is None else raw['cost'], metadata=meta, **fields)
        registry.register_card(definition)
        if cid == CARD:
            member = PoolCard.from_definition(definition)
            if cid in registry.pool_cards:
                if registry.pool_cards[cid] != member: raise TargetValidationError('Trial changed an existing pool record')
            else: registry.register_pool_card(member)
    raw_by_id = {r['record']['id']: r['record'] for r in data['choice_only']}
    registry.register_sham_trial_profile(ShamTrialProfile(CARD,
        tuple(TrialComponent(cid, PREFIX+cid, raw_by_id[cid]['tags']['TAG_SCRIPT_DATA_NUM_1']) for cid in data['component_order']),
        tuple(TrialTier(t['template_card_id'], t['choice_card_id'], t['owner_starts']) for t in data['tiers']),
        PREFIX+'cast', PREFIX+'expire'))
