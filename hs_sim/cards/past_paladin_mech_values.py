"""Four actual past Paladin Mechs reuse ordinary cast, draw and summon ledgers."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.deck_conditions import CheckDeckCondition, DeckCondition
from hs_sim.engine.model import (CardDefinition, CardType, EndTurnSpec, HandDerivativeSpec,
    Keyword, PlayerSpellCountCostSpec, TriggerSpec)
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-paladin-mech-values-v1.json'
BATCH_HASH = 'a6aebc450607445057a3127962442f1cf7e554b07c7a85c4797678627da0cea9'
REFERENCE_PATH = ROOT/'data/cards/past-paladin-mech-local-reference-v1.json'
REFERENCE_HASH = '92bf7f1b4ac499111e6d8bb07d3ccd513fa4262c651351a493b8ffd33e16cdb8'
TOTEM, LIGHTBOT, PURATOR, SECURITY = LEAVES = ('JAM_010','MIS_918','NX2_023','YOG_510')
GIANT, RECRUIT = 'MIS_918t','CS2_101t'
DEPENDENCIES = (*LEAVES, GIANT)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_paladin_mech_values.'
HOLY = PlayerSpellCountCostSpec('cost.player-holy-cast-count-v1')
NO_NEUTRAL = DeckCondition(scope='current', predicate='no_neutral')
TYPES = ('draenei','undead','murloc','demon','mech','elemental','beast','totem','pirate','dragon','quilboar','naga')
SECURITY_QUERY = PoolQuery(kinds=(CardType.MINION,), exclude_card_ids=(SECURITY,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads(REFERENCE_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != REFERENCE_HASH or
            tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(v['record']['id'] for v in data['dependencies']) != DEPENDENCIES or
            tuple(v['record']['id'] for v in data['existing_dependencies']) != (RECRUIT,) or
            any(data[k] for k in ('cards','evidence_only','skipped')) or
            data['reference_canonical_sha256'] != REFERENCE_HASH or
            data['reference_document'] != REFERENCE_PATH.relative_to(ROOT).as_posix() or
            tuple(data['purator_tribe_order']) != TYPES or data['security_excludes_card_ids'] != [SECURITY] or
            data['holy_cost_profile'] != HOLY.profile_id or len(data['official_observations']) != 10 or
            len(reference['candidate_ids']) != 27 or len(reference['candidate_records']) != 27 or
            reference['runtime_bindings_added'] or reference['membership_uses_executable_coverage'] or
            any(data[k] for k in ('formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Past Paladin Mechs lost complete original sources, forms or finite policies')
    if any(canonical_digest(v['record']) != v['record_sha256'] for v in
            data['dependencies']+data['existing_dependencies']+reference['candidate_records']):
        raise TargetValidationError('Past Paladin Mechs require their whole unchanged raw rows')
    return data


def register_past_paladin_mech_values(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Past Paladin Mechs changed the complete original Recruit dependency')
    prepared = []
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        if cid in registry.cards:
            raise TargetValidationError('Past Paladin Mechs cannot overwrite a native identity: '+cid)
        if cid == TOTEM: fields['triggers'] = (TriggerSpec('turn_ended',PREFIX+'recruit',EndTurnSpec()),)
        if cid in (LIGHTBOT,GIANT):
            fields.update(player_spell_count_cost=HOLY,
                keywords=(Keyword.GIGANTIFY,) if cid == LIGHTBOT else (Keyword.GIGANTIC,))
        if cid == LIGHTBOT: fields['hand_derivatives'] = (HandDerivativeSpec(Keyword.GIGANTIFY,GIANT),)
        if cid == PURATOR: fields.update(keywords=(Keyword.TAUNT,),battlecry=PREFIX+'typed_draws')
        if cid == SECURITY: fields['deathrattle'] = PREFIX+'security'
        attack = raw['attack']
        if attack is None:
            if data['numeric_normalizations'].get(cid) != {'attack':0}:
                raise TargetValidationError('Missing printed Attack needs explicit complete zero evidence')
            attack = 0
        card = CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=attack,
            health=raw['health'],metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card); prepared.append(card)
    def recruit(c):
        return (SummonByCard(c.player_id,(SummonEntryMaterial(RECRUIT),),SummonCause.capture(c)),) if living_source(c) else ()
    def typed_draws(c):
        slots = tuple(DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,),tribes_any=(tribe,))) for tribe in TYPES)
        return (CheckDeckCondition(c.player_id,NO_NEUTRAL,(DrawPhysicalGroup(c.player_id,c.source_id,slots),)),)
    def security(c):
        return (DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(SECURITY_QUERY),),
            DrawGroupReward('set_stats_cost_all',5)),)
    for name,body in (('recruit',recruit),('typed_draws',typed_draws),('security',security)):
        registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
