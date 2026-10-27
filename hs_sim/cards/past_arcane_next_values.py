"""Actual Arcane next-use costs, scoped Spell Damage and held-play consumers."""
import json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier, Damage, Draw, RandomDamageBatch
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import is_honorable_kill
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, DamageKind, HandProgressSpec, Keyword,
    PlayerEffectSpec, PlayerSpellCountCostSpec, SpellSchool, TargetSpec, Zone)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .entry_native_cards import submitted_tribes
from .metadata import metadata_from_record
from .native_followup_cards import characters

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-next-values-v1.json'
BATCH_HASH = '7860b3abc6e6741e6470fda396d7fb33141a3ee54137d000b71798f5af81adf3'
LEAVES = ('AT_004','AV_212','DMF_057','RLK_818','RLK_819','SCH_353','TOY_800','TSC_948','TTN_085','YOG_082')
LYNX = 'RLK_819t'
DEPENDENCIES = (*LEAVES,LYNX)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_next_values.'
NEXT_DAMAGE = PREFIX+'next_spell_damage'
SCHOOL_PROFILE = 'cost.player-distinct-school-cast-count-v1'
HELD = HandProgressSpec('event',event='card_committed',condition_id=PREFIX+'held_naga',on_complete=PREFIX+'held_ready')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(v['record']['id']for v in data['dependencies']) != DEPENDENCIES or
            any(data[k]for k in('cards','existing_dependencies','evidence_only','skipped','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            len(data['official_observations']) != 22 or data['lynx_card_id'] != LYNX or
            data['all_cast_school_cost_profile'] != SCHOOL_PROFILE or
            data['ordinary_root_school_profile_unchanged'] != 'cost.player-distinct-spell-school-count-v1' or
            not set(LEAVES) <= set(reference['candidate_ids']) or
            any(canonical_digest(v['record']) != v['record_sha256']for v in data['dependencies'])):
        raise TargetValidationError('Past Arcane value consumers changed their full original data or finite policies')
    return data


def register_past_arcane_next_values(registry):
    data = load_batch(); prepared = []
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        if cid in registry.cards: raise TargetValidationError('Past Arcane values cannot overwrite an original identity: '+cid)
        if cid == LYNX:
            card = CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
                keywords=(Keyword.RUSH,),metadata=metadata_from_record(raw))
        else:
            if raw['type'] != 'SPELL' or raw['tags'].get('SPELL_SCHOOL') != 1:
                raise TargetValidationError('Past Arcane value consumer changed its original spell face')
            if cid in ('AT_004','DMF_057'):
                fields['targeting'] = TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
            elif cid in ('AV_212','TOY_800','YOG_082'):
                fields['targeting'] = TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))
            if cid == 'TSC_948': fields['hand_progress'] = HELD
            if cid == 'TTN_085': fields['player_spell_count_cost'] = PlayerSpellCountCostSpec(SCHOOL_PROFILE)
            card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.ARCANE,
                on_play=PREFIX+cid,
                metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Past Arcane values contradict original printed metadata: '+cid)
        prepared.append(card)

    def held_naga(c):
        if c.event is None or c.event.kind != 'card_committed' or c.event.player_id != c.player_id: return False
        row = play_record(c.state,dict(c.event.data)['play_id'])
        if (row.source_id,row.player_id) != (c.event.source_id,c.event.player_id):
            raise ResolutionError('Held Naga condition lost its original physical hand commitment')
        return row.kind == CardType.MINION and row.source_id != c.source_id and submitted_tribes(row).matches_any(('naga',))
    def scaled_count(c):
        if c.cast is None or (c.cast.source_id,c.cast.player_id) != (c.source_id,c.player_id):
            raise ResolutionError('Numeric Spell Damage consumer requires its actual current CAST')
        return max(0,1+spell_bonus(c.state,c.player_id,registry,SpellSchool.ARCANE,cast_id=c.cast.id))
    def portal(c):
        count = scaled_count(c); cause = SummonCause.capture(c)
        # The original resolver bounds this iterator before running any entry.
        return (SummonByCard(c.player_id,(SummonEntryMaterial(LYNX),),cause)for _ in range(count))
    def siphon_reward(c):
        if not is_honorable_kill(c.event,c.source_id): return ()
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(delta=-1),c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].kind == CardType.SPELL)
    def vial_reward(c):
        amount = c.health_result.damage_dealt
        return (AddCostModifier(c.player_id,CostSpec(delta=-amount),uses_remaining=1,source_id=c.source_id,
            expires_turn=c.state.turn),)if amount else ()
    def gifts(c):
        complete = any(a.kind == 'hand_progress' and a.hand_progress == HELD and a.progress_completions > 0
            for a in c.source.abilities)
        return (Draw(c.player_id,2 if complete else 1,c.source_id),)

    bodies = {
        'AT_004':lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL,spell_bonus_multiplier=2),),
        'AV_212':lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL,PREFIX+'siphon_reward'),),
        'siphon_reward':siphon_reward,
        'DMF_057':lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),
            AddCostModifier(c.player_id,CostSpec(delta=-2,card_types=(CardType.SPELL,)),uses_remaining=1,
                source_id=c.source_id,expires_turn=c.state.turn)),
        'RLK_818':lambda c:(RandomDamageBatch(characters(c,registry,3-c.player_id),3,1,c.source_id,DamageKind.SPELL),),
        'RLK_819':portal,'SCH_353':lambda c:(Draw(c.player_id,scaled_count(c),c.source_id),),
        'TOY_800':lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL,PREFIX+'vial_reward'),),
        'vial_reward':vial_reward,'TSC_948':gifts,'TTN_085':lambda c:(Draw(c.player_id,2,c.source_id),),
        'YOG_082':lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),AddPlayerEffect(c.player_id,NEXT_DAMAGE,c.source_id)),
        'held_ready':lambda c:(),
    }
    registry.register_trigger_condition(PREFIX+'held_naga',held_naga)
    for name,body in bodies.items(): registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(NEXT_DAMAGE,'YOG_082',kind='next_spell_damage_until_cast',spell_damage=2))
