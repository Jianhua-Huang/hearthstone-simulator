"""Explicit card/behavior registry with a versioned replay identity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Callable, Mapping, Sequence, TypeAlias

from .effects import Effect
from .model import HeroPowerRecord, BattlecryRecord, ComboRecord, DeathrattleCapture, HeroPowerPayloadCapture, EndTurnCapture, KindredActivation, KindredProfile
from .model import SummonProducerProfile
from .model import EndTurnActivationProfile, EndTurnCandidateProfile, RepeatWitnessProfile, CostQueryProfile
from .model import AppendageSpec, SecretSpec, ActionWindow, PlayRecord, AbilityInstance, LimitedTriggerSpec, HandProgressSpec, DeckSacrificeSpec, SpellCastRecord, DrawRecord, CastWhenDrawnSpec
from .pools import GenerationContext, PoolCard, PoolDefinition, validate_pools
from .model import PlayerEffect, PlayerEffectSpec, QuestSpec, ActivatedAbilitySpec, AuraSpec, CardClass, CardDefinition, CardMetadata, CardType, ChoiceResult, CostSpec, CostAuraSpec, DeathRecord, Entity, Event, GameState, HandActionSpec, HealthRule, Keyword, OpeningHook, PaymentType, SpellSchool, TargetSpec, TriggerSpec, Zone


class UnsupportedDefinitionError(ValueError):
    """A requested card or behavior has not been implemented in this ruleset."""


@dataclass(frozen=True)
class RuleContext:
    """A behavior's view of state; the engine supplies a detached state snapshot."""

    state: GameState
    source_id: int
    player_id: int
    target_id: int | None = None
    event: Event | None = None
    death: DeathRecord | None = None
    choice: ChoiceResult | None = None
    player_effect: PlayerEffect | None = None
    window: ActionWindow | None = None
    play: PlayRecord | None = None
    trigger: AbilityInstance | None = None
    cast: 'SpellCastRecord | None' = None
    draw: DrawRecord | None = None
    rewind_attempt: int = 0
    power: 'HeroPowerRecord | None' = None
    battlecry: BattlecryRecord | None = None
    combo: ComboRecord | None = None
    deathrattle: DeathrattleCapture | None = None
    power_payload: HeroPowerPayloadCapture | None = None
    end_turn: EndTurnCapture | None = None
    physical: object | None = None
    discard: object | None = None
    kindred: KindredActivation | None = None

    @property
    def destruction(self):
        from .zones import destruction_result
        return destruction_result(self.event)

    @property
    def hero_lethal(self):
        from .hero_lethal_windows import context_reference
        return context_reference(self)

    @property
    def resource_result(self):
        from .resource_operations import resource_result
        return resource_result(self.event)

    @property
    def armor_result(self):
        from .resources import armor_loss_result
        return armor_loss_result(self.event)

    @property
    def mana_result(self):
        from .resources import mana_consumption_result
        return mana_consumption_result(self.event)

    @property
    def health_result(self):
        from .health_outcomes import health_result
        return health_result(self.event)

    @property
    def spell_conditions(self):
        """Shared conditions without representing an effect cast as a hand play."""
        return self.physical if self.physical is not None else self.cast if self.cast is not None else self.play

    @property
    def generated_activation(self):
        """Trusted body acceptance, independent of physical paid-hand history."""
        return None if self.physical is None else self.physical.activation

    @property
    def source(self) -> Entity:
        return self.state.entities[self.source_id]


@dataclass(frozen=True)
class PlayerRuleContext:
    """Detached player DTOs for legality, with no internal IDs or full GameState.

    Hand backs contain slot/controller information, but no hidden attributes.
    Trusted callbacks must remain pure and must not capture an external Game.
    """
    player_id: int
    observation: dict
    source: dict
    target: dict | None = None


Behavior: TypeAlias = Callable[[RuleContext], Sequence[Effect]]
TargetRule: TypeAlias = Callable[[RuleContext], bool]


def _any_character(context: RuleContext) -> bool:
    entity = context.state.entities.get(context.target_id)
    return entity is not None and entity.active and entity.is_character and entity.zone in (Zone.HERO, Zone.BOARD) and entity.health > 0


def _triggerable_deathrattle(context: RuleContext) -> bool:
    from .deathrattles import triggerable_deathrattles
    entity = context.state.entities.get(context.target_id)
    return (entity is not None and entity.zone == Zone.BOARD and entity.kind == CardType.MINION
        and entity.active and not entity.doomed and entity.health > 0
        and bool(triggerable_deathrattles(context.state, entity)))


def _name(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")


def _number(value: object, field: str, minimum: int | None = None) -> None:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = "" if minimum is None else f" >= {minimum}"
        raise ValueError(f"{field} must be an integer{suffix}")


class Registry:
    """Definitions are immutable once a match has frozen this registry.

    Fingerprints include normalized definitions and behavior identifiers, NOT
    Python callback implementation code.  Change version whenever callback
    semantics change; otherwise old replay compatibility cannot be guaranteed.
    """

    def __init__(self, version: str) -> None:
        _name(version, "version")
        self._version = version
        self._cards: dict[str, CardDefinition] = {}
        self._hand_mirror_ids = frozenset()
        self._assemble_templates = {}
        self._player_effects: dict[str, PlayerEffectSpec] = {}
        self._kindred_profiles: dict[str, KindredProfile] = {}
        self._spell_target_profiles = {}
        self._turn_draw_profiles = {}
        self._spell_value_profiles = {}
        self._hero_health_target_profiles = {}
        self._kindred_target_profiles = {}
        self._corpse_summon_profiles = {}
        self._corpse_gain_profiles = {}
        self._summon_attack_profiles = {}
        self._summon_producer_profiles: dict[str, SummonProducerProfile] = {}
        self._end_turn_profiles: dict[str, EndTurnActivationProfile] = {
            'end_turn.effect': EndTurnActivationProfile('end_turn.effect'),
            'end_turn.phase': EndTurnActivationProfile('end_turn.phase', kind='phase', cause_events=('turn_started',)),
        }
        self._end_turn_candidate_profiles: dict[str, EndTurnCandidateProfile] = {
            'end_turn.candidates': EndTurnCandidateProfile('end_turn.candidates'),
        }
        self._repeat_witness_profiles: dict[str, RepeatWitnessProfile] = {
            'repeat.witness.controlled': RepeatWitnessProfile('repeat.witness.controlled'),
            'repeat.witness.active_live': RepeatWitnessProfile(
                'repeat.witness.active_live', include_dormant=False,
                include_starship_building=False, include_doomed=False,
                require_positive_health=True),
        }
        self._cost_query_profiles: dict[str, CostQueryProfile] = {
            'repeat.cost.accepted_hand': CostQueryProfile('repeat.cost.accepted_hand'),
        }
        self._body_target_profiles = {}
        self._body_target_bindings = {}
        self._body_root_target_bindings = {}
        self._indirect_battlecry_bindings = {}
        self._historical_battlecry_bindings = {}
        self._generated_whole_target_bindings = {}
        self._pool_cards: dict[str, PoolCard] = {}
        self._pools: dict[tuple[str, str, str], PoolDefinition] = {}
        self._generation_families: dict[str, tuple[str, ...]] = {}
        self._generation_family_members: dict[str, str] = {}
        self._excavation_profiles = {}
        self._imbue_profiles = {}
        self._invoke_profile = None
        self._mana_rank_families = {}
        self._mana_rank_forms = {}
        self._unidentified_families = {}
        self._unidentified_bases = {}
        self._unidentified_members = set()
        self._board_card_families = {}
        self._board_card_members = {}
        self._tourists = {}
        self._sideboards = {}
        self._deck_size_rules = {}
        self._fabled = {}
        self._modular_profiles = {}
        self._modular_modules = {}
        self._modular_faces = {}
        self._jade_families = {}
        self._cthun_profile = None
        from .choose_one import DISPATCH, dispatch
        self._behaviors: dict[str, Behavior] = {DISPATCH: lambda c: dispatch(self, c)}
        from .dark_gifts import LIVING_NIGHTMARE_BEHAVIOR, living_nightmare
        self._behaviors[LIVING_NIGHTMARE_BEHAVIOR] = living_nightmare
        self._secret_conditions: dict[str, TargetRule] = {}
        self._trigger_conditions: dict[str, TargetRule] = {'always': lambda c: True}
        self._target_rules: dict[str, TargetRule] = {"any_character": _any_character, "any_entity": lambda ctx: ctx.target_id in ctx.state.entities,
            "triggerable_deathrattle": _triggerable_deathrattle}
        self._use_rules: dict[str, TargetRule] = {"always": lambda ctx: True}
        # Only these engine-owned predicates may inspect the legacy context
        # during player validation; their inputs are audited in player_api.
        self._target_visibility = {name: 'builtin' for name in self._target_rules}
        self._target_predicates = {}
        self._player_target_rules = {}
        self._use_visibility = {name: 'builtin' for name in self._use_rules}
        self._frozen = False

    @property
    def version(self) -> str:
        return self._version

    @property
    def cards(self) -> Mapping[str, CardDefinition]:
        if self._assemble_templates:
            from .assemble_faces import AssembleCardCatalog
            return AssembleCardCatalog(self)
        return MappingProxyType(self._cards)

    @property
    def assemble_templates(self):
        return MappingProxyType(self._assemble_templates)

    def register_assemble_template(self, template):
        from .assemble_faces import AssembleTemplate, validate_template
        self._require_mutable()
        if type(template) is not AssembleTemplate:
            raise ValueError('Expected AssembleTemplate')
        validate_template(self,template)
        if template.card_id in self._assemble_templates:
            raise ValueError('Duplicate assembly template')
        self._assemble_templates[template.card_id] = template

    @property
    def pool_cards(self) -> Mapping[str, PoolCard]:
        return MappingProxyType(self._pool_cards)

    @property
    def generation_families(self):
        """Reviewed same-card editions, independent of pool weights/copy limits."""
        return MappingProxyType(self._generation_families)

    def register_generation_family(self, card_ids):
        self._require_mutable()
        if type(card_ids) is not tuple or len(card_ids) < 2:
            raise ValueError('Generation family requires an immutable group of editions')
        for card_id in card_ids:
            _name(card_id, 'generation family card')
        if card_ids != tuple(sorted(set(card_ids))):
            raise ValueError('Generation family editions must be unique and sorted')
        if any(cid in self._generation_family_members for cid in card_ids):
            raise ValueError('Duplicate or overlapping generation family')
        self._generation_families[card_ids[0]] = card_ids
        self._generation_family_members.update((cid, card_ids[0]) for cid in card_ids)

    def generation_family(self, card_id):
        _name(card_id, 'generation source card')
        key = self._generation_family_members.get(card_id)
        return (card_id,) if key is None else self._generation_families[key]

    @property
    def player_effects(self) -> Mapping[str, PlayerEffectSpec]:
        return MappingProxyType(self._player_effects)

    @property
    def kindred_profiles(self):return MappingProxyType(self._kindred_profiles)

    @property
    def spell_target_profiles(self):return MappingProxyType(self._spell_target_profiles)

    @property
    def turn_draw_profiles(self):return MappingProxyType(self._turn_draw_profiles)

    @property
    def spell_value_profiles(self):return MappingProxyType(self._spell_value_profiles)

    @property
    def hero_health_target_profiles(self):return MappingProxyType(self._hero_health_target_profiles)

    @property
    def kindred_target_profiles(self):return MappingProxyType(self._kindred_target_profiles)

    @property
    def corpse_summon_profiles(self):return MappingProxyType(self._corpse_summon_profiles)

    @property
    def corpse_gain_profiles(self):return MappingProxyType(self._corpse_gain_profiles)

    @property
    def summon_attack_profiles(self):return MappingProxyType(self._summon_attack_profiles)

    def register_summon_attack_profile(self,profile):
        self._require_mutable()
        from .summon_attack_groups import validate_profile
        validate_profile(self,profile)
        if profile.card_id in self._summon_attack_profiles:raise ValueError('Duplicate native summon attack profile')
        self._summon_attack_profiles[profile.card_id]=profile

    def register_corpse_gain_profile(self, profile):
        self._require_mutable()
        from .corpse_gains import validate_profile
        validate_profile(self, profile)
        if profile.card_id in self._corpse_gain_profiles:
            raise ValueError('Duplicate native corpse gain profile')
        self._corpse_gain_profiles[profile.card_id] = profile

    def register_corpse_summon_profile(self,profile):
        self._require_mutable()
        from .corpse_summon_rewards import validate_profile
        validate_profile(self,profile)
        if profile.card_id in self._corpse_summon_profiles:raise ValueError('Duplicate native corpse summon profile')
        self._corpse_summon_profiles[profile.card_id]=profile

    def register_spell_target_profile(self,profile):
        self._require_mutable()
        from .spell_target_conditions import validate_profile
        validate_profile(self,profile)
        if profile.card_id in self._spell_target_profiles:raise ValueError('Duplicate native spell target profile')
        self._spell_target_profiles[profile.card_id]=profile

    def register_turn_draw_profile(self,profile):
        self._require_mutable()
        from .turn_start_draws import validate_profile
        validate_profile(self,profile)
        if profile.card_id in self._turn_draw_profiles:raise ValueError('Duplicate native turn draw profile')
        self._turn_draw_profiles[profile.card_id]=profile

    def register_spell_value_profile(self,profile):
        self._require_mutable()
        from .native_spell_values import validate_profile
        validate_profile(self,profile)
        if profile.card_id in self._spell_value_profiles:raise ValueError('Duplicate native spell value profile')
        self._spell_value_profiles[profile.card_id]=profile

    def register_hero_health_target_profile(self,profile):
        self._require_mutable()
        from .hero_health_targets import validate_profile
        validate_profile(self,profile)
        if profile.card_id in self._hero_health_target_profiles:raise ValueError('Duplicate native hero-health target profile')
        self._hero_health_target_profiles[profile.card_id]=profile

    def register_kindred_profile(self,profile):
        self._require_mutable()
        from .kindred import validate_profile
        validate_profile(self,profile)
        if profile.card_id in self._kindred_profiles:raise ValueError('Duplicate native Kindred profile')
        if profile.mode=='body':
            users=[c.id for c in self._cards.values()if profile.wrapper in(c.on_play,c.battlecry)]
            if users!=[profile.card_id]:raise ValueError('A native Kindred wrapper must identify one reviewed definition')
            from .kindred import request
            self._behaviors[profile.wrapper]=lambda c,card_id=profile.card_id:request(c,card_id)
        self._kindred_profiles[profile.card_id]=profile

    def register_kindred_target_profile(self, profile):
        self._require_mutable()
        from .kindred_targets import validate_profile
        validate_profile(self, profile)
        if profile.card_id in self._kindred_target_profiles:
            raise ValueError('Duplicate native targeted Kindred profile')
        self._kindred_target_profiles[profile.card_id] = profile

    def register_player_effect(self, spec: PlayerEffectSpec) -> None:
        self._require_mutable()
        if type(spec) is not PlayerEffectSpec:
            raise ValueError('Expected PlayerEffectSpec')
        spec.__post_init__()
        from .repeat_source_conditions import validate_source_declaration
        for repeat in (*spec.deathrattle_repeats, *spec.end_turn_repeats):
            validate_source_declaration(self, repeat, allow_source=False)
        if spec.id in self._player_effects:
            raise ValueError('Duplicate player effect specification')
        self._player_effects[spec.id] = spec

    def player_effect(self, spec_id: str) -> PlayerEffectSpec:
        _name(spec_id, 'player effect specification')
        try:
            return self._player_effects[spec_id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported player effect: {spec_id}') from None

    @property
    def summon_producer_profiles(self) -> Mapping[str, SummonProducerProfile]:
        return MappingProxyType(self._summon_producer_profiles)

    def register_summon_producer_profile(self, profile: SummonProducerProfile) -> None:
        self._require_mutable()
        if type(profile) is not SummonProducerProfile:
            raise ValueError('Typed logical summon producer profile required')
        profile.__post_init__()
        if profile.id in self._summon_producer_profiles:
            raise ValueError('Duplicate logical summon producer profile')
        self._summon_producer_profiles[profile.id] = profile

    def summon_producer_profile(self, profile_id: str) -> SummonProducerProfile:
        _name(profile_id, 'logical summon producer profile')
        try:
            return self._summon_producer_profiles[profile_id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported logical summon producer: {profile_id}') from None

    @property
    def end_turn_profiles(self) -> Mapping[str, EndTurnActivationProfile]:
        return MappingProxyType(self._end_turn_profiles)

    def register_end_turn_profile(self, profile: EndTurnActivationProfile) -> None:
        self._require_mutable()
        if type(profile) is not EndTurnActivationProfile:
            raise ValueError('Expected EndTurnActivationProfile')
        profile.__post_init__()
        if profile.id in self._end_turn_profiles:
            raise ValueError('Duplicate end-turn activation profile')
        self._end_turn_profiles[profile.id] = profile

    def end_turn_profile(self, profile_id: str) -> EndTurnActivationProfile:
        _name(profile_id, 'end-turn activation profile')
        try:
            return self._end_turn_profiles[profile_id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported end-turn activation profile: {profile_id}') from None

    @property
    def end_turn_candidate_profiles(self) -> Mapping[str, EndTurnCandidateProfile]:
        return MappingProxyType(self._end_turn_candidate_profiles)

    def register_end_turn_candidate_profile(self, profile: EndTurnCandidateProfile) -> None:
        self._require_mutable()
        if type(profile) is not EndTurnCandidateProfile:
            raise ValueError('Expected EndTurnCandidateProfile')
        profile.__post_init__()
        if profile.id in self._end_turn_candidate_profiles:
            raise ValueError('Duplicate end-turn candidate profile')
        self._end_turn_candidate_profiles[profile.id] = profile

    def end_turn_candidate_profile(self, profile_id: str) -> EndTurnCandidateProfile:
        _name(profile_id, 'end-turn candidate profile')
        try:
            return self._end_turn_candidate_profiles[profile_id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported end-turn candidate profile: {profile_id}') from None

    @property
    def repeat_witness_profiles(self) -> Mapping[str, RepeatWitnessProfile]:
        return MappingProxyType(self._repeat_witness_profiles)

    def register_repeat_witness_profile(self, profile: RepeatWitnessProfile) -> None:
        self._require_mutable()
        if type(profile) is not RepeatWitnessProfile:
            raise ValueError('Expected RepeatWitnessProfile')
        profile.__post_init__()
        if profile.id in self._repeat_witness_profiles:
            raise ValueError('Duplicate repeat witness profile')
        self._repeat_witness_profiles[profile.id] = profile

    def repeat_witness_profile(self, profile_id: str) -> RepeatWitnessProfile:
        _name(profile_id, 'repeat witness profile')
        try:
            return self._repeat_witness_profiles[profile_id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported repeat witness profile: {profile_id}') from None

    @property
    def cost_query_profiles(self) -> Mapping[str, CostQueryProfile]:
        return MappingProxyType(self._cost_query_profiles)

    def register_cost_query_profile(self, profile: CostQueryProfile) -> None:
        self._require_mutable()
        if type(profile) is not CostQueryProfile:
            raise ValueError('Expected CostQueryProfile')
        profile.__post_init__()
        if profile.id in self._cost_query_profiles:
            raise ValueError('Duplicate cost query profile')
        self._cost_query_profiles[profile.id] = profile

    def cost_query_profile(self, profile_id: str) -> CostQueryProfile:
        if type(profile_id) is not str:
            raise ValueError('Cost query profile ID requires a string')
        _name(profile_id, 'cost query profile')
        try:
            return self._cost_query_profiles[profile_id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported cost query profile: {profile_id}') from None

    @property
    def body_target_profiles(self):
        return MappingProxyType(self._body_target_profiles)

    def register_body_target_profile(self, profile) -> None:
        from .body_targets import BodyTargetProfile
        self._require_mutable()
        if type(profile) is not BodyTargetProfile:
            raise ValueError('Expected exact typed BodyTargetProfile')
        profile.__post_init__()
        if profile.id in self._body_target_profiles:
            raise ValueError('Duplicate body target profile')
        self._body_target_profiles[profile.id] = profile

    def body_target_profile(self, profile_id):
        if type(profile_id) is not str:
            raise ValueError('Body target profile ID requires a string')
        _name(profile_id, 'body target profile')
        try:
            return self._body_target_profiles[profile_id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported body target profile: {profile_id}') from None

    @property
    def body_target_bindings(self):
        return MappingProxyType(self._body_target_bindings)

    def register_body_target_binding(self, binding):
        from .body_target_authority import validate_binding
        self._require_mutable()
        validate_binding(self, binding)
        key = (binding.declaration_card_id, binding.family, binding.profile_id)
        if key in self._body_target_bindings:
            raise ValueError('Duplicate body target declaration binding')
        profile = self.body_target_profile(binding.profile_id)
        for other in self._body_target_bindings.values():
            if ((other.declaration_card_id, other.family) == (binding.declaration_card_id, binding.family)
                    and self.body_target_profile(other.profile_id).origin == profile.origin
                    and set(other.origins) & set(binding.origins)):
                raise ValueError('Ambiguous body target profiles for this declaration and physical origin')
        self._body_target_bindings[key] = binding

    def body_target_binding(self, declaration_card_id, family, profile_id):
        from .errors import IllegalAction
        for value in (declaration_card_id, family, profile_id):
            if type(value) is not str:
                raise ValueError('Body target binding key requires exact strings')
            _name(value, 'body target binding key')
        try:
            return self._body_target_bindings[(declaration_card_id, family, profile_id)]
        except KeyError:
            raise IllegalAction('Physical body has no trusted binding for the requested target policy') from None

    @property
    def body_root_target_bindings(self):
        return MappingProxyType(self._body_root_target_bindings)

    def register_body_root_target_binding(self, binding):
        from .body_root_targets import validate_root_binding
        self._require_mutable()
        validate_root_binding(self, binding)
        key = (binding.carrier_card_id, binding.profile_id)
        if key in self._body_root_target_bindings:
            raise ValueError('Duplicate ordinary root/body targeting policy')
        self._body_root_target_bindings[key] = binding

    def body_root_target_binding(self, carrier_card_id, profile_id):
        from .errors import IllegalAction
        for value in (carrier_card_id, profile_id):
            if type(value) is not str:
                raise ValueError('Root target policy key requires exact strings')
            _name(value, 'root target policy key')
        try:
            return self._body_root_target_bindings[(carrier_card_id, profile_id)]
        except KeyError:
            raise IllegalAction('Physical carrier has no trusted ordinary root/body target policy') from None

    @property
    def indirect_battlecry_bindings(self):
        return MappingProxyType(self._indirect_battlecry_bindings)

    def register_indirect_battlecry_binding(self, binding):
        from .indirect_body_targets import validate_binding
        self._require_mutable(); validate_binding(self,binding)
        key = binding.carrier_card_id,binding.profile_id
        if key in self._indirect_battlecry_bindings:
            raise ValueError('Duplicate connected indirect Battlecry binding')
        self._indirect_battlecry_bindings[key] = binding

    def indirect_battlecry_binding(self, carrier_card_id, profile_id):
        from .errors import IllegalAction
        for value in (carrier_card_id,profile_id): _name(value,'indirect Battlecry key')
        try:
            return self._indirect_battlecry_bindings[(carrier_card_id,profile_id)]
        except KeyError:
            raise IllegalAction('Physical carrier has no connected indirect Battlecry policy') from None

    @property
    def generated_whole_target_bindings(self):
        return MappingProxyType(self._generated_whole_target_bindings)

    @property
    def historical_battlecry_bindings(self):
        return MappingProxyType(self._historical_battlecry_bindings)

    def register_historical_battlecry_binding(self, binding):
        from .historical_body_targets import validate_binding
        self._require_mutable(); validate_binding(self,binding)
        key=binding.carrier_card_id,binding.profile_id
        if key in self._historical_battlecry_bindings: raise ValueError('Duplicate historical Battlecry source binding')
        self._historical_battlecry_bindings[key]=binding

    def historical_battlecry_binding(self, carrier_card_id, profile_id):
        from .errors import IllegalAction
        for value in (carrier_card_id,profile_id): _name(value,'historical Battlecry key')
        try: return self._historical_battlecry_bindings[(carrier_card_id,profile_id)]
        except KeyError:
            raise IllegalAction('Carrier has no connected historical Battlecry producer') from None

    def register_generated_whole_target_binding(self, binding):
        from .generated_body_targets import validate_binding
        self._require_mutable(); validate_binding(self,binding)
        key=binding.carrier_card_id,binding.profile_id
        if key in self._generated_whole_target_bindings: raise ValueError('Duplicate generated whole target source')
        self._generated_whole_target_bindings[key]=binding

    def generated_whole_target_binding(self, carrier_card_id, profile_id):
        from .errors import IllegalAction
        for value in (carrier_card_id,profile_id): _name(value,'generated whole target key')
        try: return self._generated_whole_target_bindings[(carrier_card_id,profile_id)]
        except KeyError: raise IllegalAction('Physical carrier has no connected generated target policy') from None

    @property
    def pools(self) -> Mapping[tuple[str, str, str], PoolDefinition]:
        return MappingProxyType(self._pools)

    def register_pool_card(self, card: PoolCard) -> None:
        self._require_mutable()
        if type(card) is not PoolCard:
            raise ValueError('Expected PoolCard')
        card.__post_init__()
        if card.card_id in self._pool_cards:
            raise ValueError('Duplicate pool inventory card')
        self._pool_cards[card.card_id] = card

    def register_pool(self, pool: PoolDefinition) -> None:
        self._require_mutable()
        if type(pool) is not PoolDefinition:
            raise ValueError('Expected PoolDefinition')
        pool.__post_init__()
        if pool.key in self._pools:
            raise ValueError('Duplicate generation pool for target/mode')
        self._pools[pool.key] = pool

    def pool_card(self, card_id: str) -> PoolCard:
        try:
            return self._pool_cards[card_id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Missing generation metadata: {card_id}') from None

    @property
    def excavation_profiles(self):
        return MappingProxyType(self._excavation_profiles)

    def register_excavation_profile(self, profile):
        from .excavate import ExcavationProfile
        self._require_mutable()
        if type(profile) is not ExcavationProfile: raise ValueError('Expected ExcavationProfile')
        profile.__post_init__()
        if profile.key in self._excavation_profiles: raise ValueError('Duplicate Excavation profile')
        self._excavation_profiles[profile.key] = profile

    def excavation_profile(self, profile_id, context):
        try: return self._excavation_profiles[(profile_id,context.target_id,context.mode)]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported Excavation profile: {profile_id}/{context.target_id}/{context.mode}') from None

    @property
    def imbue_profiles(self):
        return MappingProxyType(self._imbue_profiles)

    def register_imbue_profile(self, profile):
        from .imbue import ImbueProfile
        self._require_mutable()
        if type(profile) is not ImbueProfile:
            raise ValueError('Expected ImbueProfile')
        profile.__post_init__()
        if profile.id in self._imbue_profiles:
            raise ValueError('Duplicate Imbue profile')
        self._imbue_profiles[profile.id] = profile

    @property
    def invoke_profile(self):
        return self._invoke_profile

    def register_invoke_profile(self, profile):
        from .invoke import InvokeProfile
        self._require_mutable()
        if type(profile) is not InvokeProfile:
            raise ValueError('Expected InvokeProfile')
        profile.__post_init__()
        if self._invoke_profile is not None:
            raise ValueError('Invoke profile is already registered')
        self._invoke_profile = profile

    @property
    def jade_families(self):
        return MappingProxyType(self._jade_families)

    @property
    def mana_rank_families(self):
        return MappingProxyType(self._mana_rank_families)

    def mana_rank_family(self, card_id):
        return self._mana_rank_forms.get(card_id)

    def register_mana_rank_family(self, family):
        from .mana_ranks import ManaRankFamily
        self._require_mutable()
        if type(family) is not ManaRankFamily:
            raise ValueError('Expected ManaRankFamily')
        family.__post_init__()
        if family.id in self._mana_rank_families or any(cid in self._mana_rank_forms for cid in family.forms):
            raise ValueError('Duplicate mana rank family or shared form')
        self._mana_rank_families[family.id] = family
        self._mana_rank_forms.update({cid: family for cid in family.forms})

    @property
    def unidentified_families(self):
        return MappingProxyType(self._unidentified_families)

    def unidentified_family(self, card_id):
        """Only an unidentified base can acquire a bonus; results never reroll."""
        return self._unidentified_bases.get(card_id)

    def register_unidentified_family(self, family):
        from .unidentified import UnidentifiedFamily
        self._require_mutable()
        if type(family) is not UnidentifiedFamily:
            raise ValueError('Expected UnidentifiedFamily')
        family.__post_init__()
        members = (family.base, *family.forms)
        if family.id in self._unidentified_families or any(cid in self._unidentified_members for cid in members):
            raise ValueError('Duplicate unidentified family or shared form')
        self._unidentified_families[family.id] = family
        self._unidentified_bases[family.base] = family
        self._unidentified_members.update(members)

    @property
    def cthun_profile(self):
        return self._cthun_profile

    @property
    def tourists(self):
        return MappingProxyType(self._tourists)

    def register_tourist(self, spec):
        from .tourists import TouristSpec
        self._require_mutable()
        if type(spec) is not TouristSpec:
            raise ValueError('Expected exact TouristSpec')
        spec.__post_init__()
        if spec.card_id in self._tourists:
            raise ValueError('Duplicate Tourist source')
        self._tourists[spec.card_id] = spec

    @property
    def sideboards(self):
        return MappingProxyType(self._sideboards)

    def register_sideboard(self, profile):
        from .sideboards import SideboardProfile
        self._require_mutable()
        if type(profile) is not SideboardProfile:
            raise ValueError('Expected exact SideboardProfile')
        profile.__post_init__()
        if profile.source_card_id in self._sideboards:
            raise ValueError('Duplicate sideboard source')
        self._sideboards[profile.source_card_id] = profile

    @property
    def deck_size_rules(self):
        return MappingProxyType(self._deck_size_rules)

    def register_deck_size_rule(self, rule):
        from .deck_size_rules import DeckSizeRule
        self._require_mutable()
        if type(rule) is not DeckSizeRule:
            raise ValueError('Expected exact DeckSizeRule')
        rule.__post_init__()
        if rule.source_card_id in self._deck_size_rules:
            raise ValueError('Duplicate deck-size source')
        self._deck_size_rules[rule.source_card_id] = rule

    @property
    def fabled(self):
        return MappingProxyType(self._fabled)

    def register_fabled(self, spec):
        from .fabled_decks import FabledSpec
        self._require_mutable()
        if type(spec) is not FabledSpec:
            raise ValueError('Expected exact FabledSpec')
        spec.__post_init__()
        if spec.source_card_id in self._fabled:
            raise ValueError('Duplicate Fabled root')
        self._fabled[spec.source_card_id] = spec

    @property
    def board_card_families(self):
        return MappingProxyType(self._board_card_families)

    def board_card_family(self, card_id):
        return self._board_card_members.get(card_id)

    def register_board_card_family(self, family):
        from .game_boards import BoardCardFamily
        self._require_mutable()
        if type(family) is not BoardCardFamily:
            raise ValueError('Expected exact BoardCardFamily')
        family.__post_init__()
        if family.id in self._board_card_families or any(cid in self._board_card_members for cid in family.members):
            raise ValueError('Duplicate board family or shared form')
        self._board_card_families[family.id] = family
        self._board_card_members.update({cid: family for cid in family.members})

    def register_cthun_profile(self, profile):
        from .cthun import CthunProfile
        self._require_mutable()
        if type(profile) is not CthunProfile:
            raise ValueError('Expected CthunProfile')
        profile.__post_init__()
        if self._cthun_profile is not None:
            raise ValueError('Cthun profile is already registered')
        self._cthun_profile = profile

    def register_jade_family(self, family):
        from .jade import JadeGolemFamily
        self._require_mutable()
        if type(family) is not JadeGolemFamily:
            raise ValueError('Expected JadeGolemFamily')
        family.__post_init__()
        if family.id in self._jade_families:
            raise ValueError('Duplicate Jade family')
        self._jade_families[family.id] = family

    def imbue_profile(self, profile_id):
        try:
            return self._imbue_profiles[profile_id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported Imbue profile: {profile_id}') from None

    def pool(self, pool_id: str, context: GenerationContext) -> PoolDefinition:
        try:
            return self._pools[(pool_id, context.target_id, context.mode)]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported generation pool: {pool_id}/{context.target_id}/{context.mode}') from None

    def _require_mutable(self) -> None:
        if self._frozen:
            raise ValueError("registry is frozen; construct a new version to add rules")

    def register_card(self, definition: CardDefinition) -> None:
        self._require_mutable()
        from .assemble_faces import PREFIX as assembly_prefix
        if isinstance(definition,CardDefinition) and definition.id.startswith(assembly_prefix):
            raise ValueError('Assembled identities require reviewed recipe resolution')
        from .modular_decks import PREFIX, option_ids
        if isinstance(definition, CardDefinition) and (
                definition.id.startswith(PREFIX) or definition.id in option_ids(self)):
            raise ValueError('Modular blueprints, options and compiled identities use their dedicated construction API')
        from .choose_one import normalize
        if isinstance(definition, CardDefinition): definition = normalize(definition)
        self._validate_card(definition)
        if definition.id in self._cards:
            raise ValueError(f"duplicate card definition: {definition.id}")
        from .repeat_source_conditions import validate_source_declaration
        for spec in (*definition.spell_repeats, *definition.battlecry_repeats,
                     *definition.combo_repeats, *definition.deathrattle_repeats,
                     *definition.hero_power_repeats, *definition.end_turn_repeats):
            validate_source_declaration(self, spec)
        from .repeat_matching import validate_repeat_cost_declaration
        for spec in definition.spell_repeats:
            validate_repeat_cost_declaration(self, spec)
        self._cards[definition.id] = definition
        if definition.hand_mirror is not None:self._hand_mirror_ids=self._hand_mirror_ids|{definition.id}

    @property
    def hand_mirror_ids(self):
        return self._hand_mirror_ids

    @property
    def modular_profiles(self):
        return MappingProxyType(self._modular_profiles)

    @property
    def modular_modules(self):
        return MappingProxyType(self._modular_modules)

    @property
    def modular_faces(self):
        return MappingProxyType(self._modular_faces)

    def register_modular_profile(self, profile):
        from .modular_decks import ModularProfile, option_ids
        self._require_mutable()
        if type(profile) is not ModularProfile:
            raise ValueError('Expected ModularProfile')
        profile.__post_init__()
        members = {profile.source_card_id, *profile.module_card_ids, *profile.cosmetic_card_ids}
        if members & (option_ids(self) | set(self._cards)):
            raise ValueError('Duplicate or physically occupied modular blueprint/options')
        self._modular_profiles[profile.source_card_id] = profile

    def register_modular_module(self, definition):
        from .modular_decks import validate_module
        self._require_mutable()
        validate_module(self, definition)
        if (definition.id in self._modular_modules or not any(definition.id in p.module_card_ids
                for p in self._modular_profiles.values())):
            raise ValueError('Duplicate module or module outside registered functional options')
        self._modular_modules[definition.id] = definition

    def register_behavior(self, id: str, handler: Behavior) -> None:
        self._require_mutable()
        _name(id, "behavior ID")
        if not callable(handler):
            raise ValueError("behavior handler must be callable")
        if id in self._behaviors:
            raise ValueError(f"duplicate behavior definition: {id}")
        self._behaviors[id] = handler

    def register_secret_condition(self, id: str, handler: TargetRule) -> None:
        self._require_mutable()
        _name(id, 'secret condition ID')
        if id in self._secret_conditions or not callable(handler):
            raise ValueError('Duplicate or invalid secret condition')
        self._secret_conditions[id] = handler

    def secret_condition(self, id: str) -> TargetRule:
        try:
            return self._secret_conditions[id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported secret condition: {id}') from None

    def register_trigger_condition(self, id: str, handler: TargetRule) -> None:
        self._require_mutable()
        _name(id, 'trigger condition ID')
        if id in self._trigger_conditions or not callable(handler):
            raise ValueError('Duplicate or invalid trigger condition')
        self._trigger_conditions[id] = handler

    def trigger_condition(self, id: str) -> TargetRule:
        try:
            return self._trigger_conditions[id]
        except KeyError:
            raise UnsupportedDefinitionError(f'Unsupported trigger condition: {id}') from None

    def validate_limited_trigger(self, spec):
        if type(spec) is not LimitedTriggerSpec:
            raise ValueError('Expected LimitedTriggerSpec')
        spec.__post_init__()
        self.behavior(spec.behavior_id)
        self.trigger_condition(spec.condition_id)
        if spec.end_turn is not None:
            self.trigger_condition(spec.end_turn.condition_id)

    def validate_hand_progress(self, spec, source_kind=None):
        if type(spec) is not HandProgressSpec:
            raise ValueError('Expected HandProgressSpec')
        spec.__post_init__()
        if Zone.DECK in spec.zones and source_kind is not None and source_kind != CardType.MINION:
            raise ValueError('Native deck event listeners require an ordinary minion')
        self.trigger_condition(spec.condition_id)
        for behavior in (spec.on_progress, spec.on_complete):
            if behavior is not None:
                self.behavior(behavior)
        if spec.upgrade_card_id is not None:
            target = self.card(spec.upgrade_card_id)
            if not target.hand_playable or target.starship_for or target.kind not in (CardType.MINION, CardType.SPELL, CardType.WEAPON):
                raise ValueError('Progress upgrade requires an ordinary playable form')
            spell_minion=(source_kind,target.kind)==(CardType.SPELL,CardType.MINION)and spec.kind=='event'and spec.event=='spell_cast_accepted'
            if source_kind is not None and ((source_kind != target.kind and not spec.health_to_durability and not spell_minion) or
                    spec.health_to_durability and (source_kind, target.kind) != (CardType.MINION, CardType.WEAPON)):
                raise ValueError('Invalid hand progress type conversion')

    def validate_defining_hand_binding(self, entity, binding):
        from .model import validate_defining_hand_spec
        binding.__post_init__()
        validate_defining_hand_spec(binding.hand_progress)
        original = self.card(binding.defining_card_id)
        if (original.defining_hand_source != binding.hand_progress or binding.source_id != entity.id or
                original.kind != entity.kind or
                entity.zone not in (Zone.HAND, Zone.DECK) or
                entity.kind not in (CardType.MINION, CardType.SPELL, CardType.WEAPON) or entity.components):
            raise ValueError('Defining source differs from its native declaration or physical carrier')

    def card(self, id: str) -> CardDefinition:
        _name(id, "card ID")
        from .assemble_faces import PREFIX as assembly_prefix, resolve_face
        if id.startswith(assembly_prefix):
            return resolve_face(self,id)
        try:
            return self._cards[id]
        except KeyError:
            raise UnsupportedDefinitionError(f"unsupported card definition: {id}") from None

    def register_target_rule(self, id: str, handler: TargetRule, *, visibility='omniscient') -> None:
        self._require_mutable()
        _name(id, "target rule ID")
        if not callable(handler):
            raise ValueError("target rule handler must be callable")
        if id in self._target_rules:
            raise ValueError(f"duplicate target rule definition: {id}")
        if visibility not in ('omniscient', 'player'):
            raise ValueError('Target visibility must be omniscient or player')
        self._target_rules[id] = handler
        self._target_visibility[id] = visibility

    def register_target_predicate(self, spec) -> None:
        """Register an engine-owned predicate from immutable explicit filters."""
        from .target_predicates import TargetPredicateSpec, evaluate
        self._require_mutable()
        if type(spec) is not TargetPredicateSpec:
            raise ValueError('Expected exact TargetPredicateSpec')
        spec.__post_init__()
        if spec.id in self._target_rules:
            raise ValueError('Duplicate target rule definition: ' + spec.id)
        self._target_predicates[spec.id] = spec
        self._target_rules[spec.id] = lambda context: evaluate(spec, self, context)
        self._target_visibility[spec.id] = 'builtin'

    def target_predicate(self, id: str):
        """Return a declarative rule, or None for a known callback rule."""
        self.target_rule(id)
        return self._target_predicates.get(id)

    def register_player_target_rule(self, spec, handler) -> None:
        """Explicitly bind a pure DTO predicate to original-input reconstruction."""
        from .player_target_inputs import PlayerTargetRuleSpec
        self._require_mutable()
        if type(spec) is not PlayerTargetRuleSpec:
            raise ValueError('Expected exact PlayerTargetRuleSpec')
        spec.__post_init__()
        self.register_target_rule(spec.id, handler, visibility='player')
        self._player_target_rules[spec.id] = spec

    def player_target_rule(self, id: str):
        self.target_rule(id)
        return self._player_target_rules.get(id)

    def target_visibility(self, id: str) -> str:
        self.target_rule(id)
        return self._target_visibility[id]

    def target_rule(self, id: str) -> TargetRule:
        _name(id, "target rule ID")
        try:
            return self._target_rules[id]
        except KeyError:
            raise UnsupportedDefinitionError(f"unsupported target rule definition: {id}") from None

    def behavior(self, id: str) -> Behavior:
        _name(id, "behavior ID")
        try:
            return self._behaviors[id]
        except KeyError:
            raise UnsupportedDefinitionError(f"unsupported behavior definition: {id}") from None

    def register_use_rule(self, id: str, handler: TargetRule, *, visibility='omniscient') -> None:
        self._require_mutable()
        _name(id, 'use rule ID')
        if id in self._use_rules or not callable(handler):
            raise ValueError('Duplicate or invalid use rule')
        if visibility not in ('omniscient', 'player'):
            raise ValueError('Use visibility must be omniscient or player')
        self._use_rules[id] = handler
        self._use_visibility[id] = visibility

    def use_visibility(self, id: str) -> str:
        self.use_rule(id)
        return self._use_visibility[id]

    def use_rule(self, id: str) -> TargetRule:
        try:
            return self._use_rules[id]
        except KeyError:
            raise UnsupportedDefinitionError(f'unsupported use rule: {id}') from None

    @staticmethod
    def _validate_card(card: CardDefinition) -> None:
        if not isinstance(card, CardDefinition):
            raise ValueError("definition must be a CardDefinition")
        from .discard_history import validate_definition as validate_discard_definition
        validate_discard_definition(card)
        from .zones import validate_destroyed_definition
        validate_destroyed_definition(card)
        from .intrinsic_costs import validate_definition_intrinsics
        validate_definition_intrinsics(card)
        _name(card.id, "card ID")
        _name(card.name, "card name")
        from .native_conditions import validate_definition as validate_native_conditions
        validate_native_conditions(card)
        if card.native_deathrattle is not None:
            from .model import NativeDeathrattleSpec
            if (type(card.native_deathrattle)is not NativeDeathrattleSpec or card.kind!=CardType.MINION or
                    not card.deathrattle or not card.hand_playable or card.choice_only or card.starship_for):
                raise ValueError('Native Deathrattle memory requires an ordinary printed minion body')
            card.native_deathrattle.__post_init__()
            if card.native_deathrattle.kind in ('draw_link','discard_link')and not card.battlecry:
                raise ValueError('Native draw linkage requires its actual Battlecry')
        if card.hand_mirror is not None:
            from .model import HandMirrorSpec
            if type(card.hand_mirror)is not HandMirrorSpec or card.kind!=CardType.MINION or not card.hand_playable or card.starship_for:
                raise ValueError('Native hand mirror requires a physical minion declaration')
            card.hand_mirror.__post_init__()
        from .model import validate_reborn_policy
        validate_reborn_policy(card.reborn_policy, Keyword.REBORN if Keyword.REBORN in card.keywords else None)
        if card.reborn_policy is not None and (card.kind != CardType.MINION or card.choice_only or
                card.starship_for or any(s.keyword == Keyword.REBORN for s in card.timed_keywords)):
            raise ValueError('Native full-health Reborn requires an ordinary removable minion keyword')
        if not isinstance(card.kind, CardType):
            raise ValueError(f"card {card.id} kind must be a CardType")
        if type(card.manual_playable) is not bool:
            raise ValueError('manual_playable must be boolean')
        if type(card.requires_weapon) is not bool:
            raise ValueError('requires_weapon must be boolean')
        if card.requires_weapon and not card.hand_playable:
            raise ValueError('Weapon play prerequisite requires a physical hand card')
        if not card.manual_playable and not card.hand_playable:
            raise ValueError('Manual play prohibition requires a physical hand/deck card')
        if type(card.cost_payment) is not PaymentType:
            raise ValueError('Native card cost payment requires PaymentType')
        if card.cost_payment != PaymentType.MANA and not (card.hand_playable or
                (card.kind == CardType.HERO_POWER and not card.passive_hero_power)):
            raise ValueError('Native alternative payment requires a payable card or hero power')
        from .disguised import validate_definition as validate_disguised
        validate_disguised(card)
        from .timed_keywords import validate_definition
        validate_definition(card)
        from .choose_one import normalize
        normalize(card)
        if card.combo is not None:
            if (card.kind not in (CardType.MINION,CardType.WEAPON,CardType.HERO) or card.choice_only or
                    Keyword.COMBO not in card.keywords):
                raise ValueError('Combo declaration requires a physical Combo card')
            _name(card.combo,'Combo behavior')
        if card.battlecry is not None:
            if (card.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO) or card.choice_only):
                raise ValueError('Battlecry requires a physical minion, weapon or hero')
            _name(card.battlecry, 'Battlecry behavior')
        if type(card.choose_both) is not bool or card.choose_both and card.kind != CardType.MINION:
            raise ValueError('Choose Both requires a minion carrier')
        from .model import RewindSpec
        if (Keyword.REWIND in card.keywords) != (card.rewind is not None):
            raise ValueError('Rewind requires a marker and declaration')
        if card.rewind is not None:
            if type(card.rewind) is not RewindSpec:
                raise ValueError('Rewind requires a typed declaration')
            if card.kind == CardType.HERO_POWER:
                if card.on_use is None or card.choice_only or card.rewind.next_card_id is not None:
                    raise ValueError('Rewind hero powers require an active payload and a per-activation budget without hand faces')
            elif not card.hand_playable or card.kind not in (CardType.SPELL,CardType.MINION) or (card.on_play is None and card.battlecry is None and card.combo is None):
                raise ValueError('Rewind requires a spell/minion play effect or active hero power')
            card.rewind.__post_init__()
        if (Keyword.CASTS_WHEN_DRAWN in card.keywords) != (card.cast_when_drawn is not None):
            raise ValueError('Casts When Drawn requires a marker and declaration')
        if card.cast_when_drawn is not None:
            if type(card.cast_when_drawn) is not CastWhenDrawnSpec or card.kind != CardType.SPELL or not card.hand_playable:
                raise ValueError('Casts When Drawn requires a physical spell')
            card.cast_when_drawn.__post_init__()
        if card.target_condition is not None:
            if (card.target_condition not in ('combo', 'outcast', 'finale', 'manathirst', 'quickdraw') or not card.hand_playable or
                    card.kind == CardType.LOCATION or not (card.requires_target or card.targeting)):
                raise ValueError('Invalid conditional play target declaration')
            if Keyword(card.target_condition) not in card.keywords:
                raise ValueError('Conditional targeting requires its printed keyword')
        if type(card.choice_only) is not bool:
            raise ValueError('choice_only must be boolean')
        from .interactables import validate_definition as validate_interactable_definition
        validate_interactable_definition(card)
        if type(card.herald_scaling) is not bool or card.herald_scaling and (
                card.kind != CardType.MINION or card.choice_only or card.starship_for or card.colossal):
            raise ValueError('Herald scaling requires a physical non-composite appendage/Soldier')
        if card.herald_soldier_for is not None and (
                not isinstance(card.herald_soldier_for, CardClass) or not card.herald_scaling):
            raise ValueError('Herald Soldier mapping requires a class and scaling')
        if type(card.colossal) is not tuple or any(type(s) is not AppendageSpec for s in card.colossal):
            raise ValueError('Colossal requires an immutable AppendageSpec tuple')
        for spec in card.colossal:spec.__post_init__()
        if (Keyword.COLOSSAL in card.keywords)!=bool(card.colossal) or card.colossal and (card.kind!=CardType.MINION or card.choice_only or card.starship_for):
            raise ValueError('Colossal requires a physical non-composite minion and explicit appendages')
        if (type(card.magnetic_tribes) is not tuple or len(set(card.magnetic_tribes))!=len(card.magnetic_tribes) or
                any(type(t) is not str or not t.strip() for t in card.magnetic_tribes)):
            raise ValueError('Magnetic requires an immutable set of host tribes')
        if (Keyword.MAGNETIC in card.keywords)!=bool(card.magnetic_tribes) or card.magnetic_tribes and (card.kind!=CardType.MINION or card.choice_only or card.starship_for):
            raise ValueError('Magnetic requires a physical minion, marker and host tribes')
        if card.manathirst is not None and (type(card.manathirst) is not int or card.manathirst < 1):
            raise ValueError('Manathirst threshold must be a positive integer')
        if (Keyword.MANATHIRST in card.keywords) != (card.manathirst is not None):
            raise ValueError('Manathirst requires matching keyword and threshold')
        if type(card.limited_triggers) is not tuple or any(type(t) is not LimitedTriggerSpec for t in card.limited_triggers):
            raise ValueError('Limited triggers require an immutable specification tuple')
        for spec in card.limited_triggers:
            spec.__post_init__()
            from .limited_triggers import supports_carrier
            if not supports_carrier(card.kind,spec):
                raise ValueError('Invalid limited trigger card type')
        if ({s.keyword for s in card.limited_triggers if s.keyword is not None} !=
                set(card.keywords).intersection((Keyword.SPELLBURST, Keyword.FRENZY))):
            raise ValueError('Spellburst/Frenzy markers require matching trigger definitions')
        if card.hand_progress is not None:
            if type(card.hand_progress) is not HandProgressSpec or card.kind not in (CardType.MINION, CardType.SPELL, CardType.WEAPON) or card.choice_only or card.starship_for:
                raise ValueError('Invalid hand progress definition')
            card.hand_progress.__post_init__()
        if card.defining_hand_source is not None:
            from .model import validate_defining_hand_spec
            validate_defining_hand_spec(card.defining_hand_source)
            if card.kind not in (CardType.MINION, CardType.SPELL, CardType.WEAPON) or card.choice_only or card.starship_for:
                raise ValueError('Defining hand source requires an ordinary physical card')
        markers = set(card.keywords).intersection((Keyword.CORRUPT, Keyword.INFUSE))
        expected = {card.hand_progress.keyword} if card.hand_progress is not None and card.hand_progress.keyword else set()
        if markers != expected:
            raise ValueError('Corrupt/Infuse markers require matching hand progress')
        if card.choice_only and (card.kind != CardType.SPELL or card.cost or card.attack or card.health or
                card.on_play is not None or card.keywords or card.hand_actions or card.opening_hooks or
                card.targeting is not None or card.requires_target or card.spell_damage):
            raise ValueError('Choice-only definitions describe options, not playable effects')
        if (type(card.starship_for) is not tuple or len(set(card.starship_for)) != len(card.starship_for) or
                any(not isinstance(c, CardClass) for c in card.starship_for)):
            raise ValueError('Starship classes require a unique CardClass tuple')
        if card.starship_for and (card.kind != CardType.MINION or card.attack or card.health or
                                  Keyword.STARSHIP_PIECE in card.keywords):
            raise ValueError('Starship bodies require an empty minion template without Starship Piece')
        if (card.on_launch is not None or Keyword.STARSHIP_PIECE in card.keywords) and card.kind != CardType.MINION:
            raise ValueError('Starship abilities require minions')
        if (type(card.activated_abilities) is not tuple or
                any(type(a) is not ActivatedAbilitySpec for a in card.activated_abilities)):
            raise ValueError('activated_abilities must be an immutable specification tuple')
        action_keywords = {Keyword.TITAN,Keyword.OLD_GOD} & set(card.keywords)
        if card.activated_abilities or action_keywords:
            count = 4 if action_keywords == {Keyword.OLD_GOD} else 3
            if (card.kind != CardType.MINION or card.starship_for or len(action_keywords) != 1 or
                    len(card.activated_abilities) != count or len({a.id for a in card.activated_abilities}) != count):
                if Keyword.OLD_GOD in action_keywords:
                    raise ValueError('Old God policy requires an ordinary minion with four distinct abilities')
                raise ValueError('Titan policy requires an ordinary minion with three distinct abilities')
            for ability in card.activated_abilities:
                ability.__post_init__()
        quest_keywords = {Keyword.QUEST, Keyword.QUESTLINE, Keyword.SIDEQUEST} & set(card.keywords)
        if card.quest is not None:
            if type(card.quest) is not QuestSpec or card.kind != CardType.SPELL or card.choice_only:
                raise ValueError('Quest requires a physical spell definition')
            card.quest.__post_init__()
            from .choose_one import DISPATCH
            if any(DISPATCH in (stage.progress_behavior, stage.reward_behavior) for stage in card.quest.stages):
                raise ValueError('Quest progress and rewards cannot dispatch an immediate Choose One branch')
            quest_keyword = Keyword.QUEST if card.quest.kind == 'repeatable_quest' else Keyword(card.quest.kind)
            if quest_keywords != {quest_keyword} or card.quest.stages[0].card_id != card.id:
                raise ValueError('Quest keyword and first stage must match its definition')
            if card.requires_target or card.targeting is not None:
                raise ValueError('Quest activation cannot require a target')
        elif quest_keywords:
            raise ValueError('Quest keyword requires an explicit QuestSpec')
        if card.secret is not None:
            from .choose_one import DISPATCH
            if (type(card.secret) is not SecretSpec or card.kind != CardType.SPELL or card.choice_only or
                    card.quest is not None or card.ongoing_effect_id is not None or
                    card.on_play is not None or
                    card.requires_target or card.targeting is not None or Keyword.SECRET not in card.keywords):
                raise ValueError('Secret requires an untargeted physical spell with its own SecretSpec')
            card.secret.__post_init__()
            if card.secret.behavior_id == DISPATCH:
                raise ValueError('Secret future text cannot dispatch an immediate Choose One branch')
        elif Keyword.SECRET in card.keywords:
            raise ValueError('Secret keyword requires SecretSpec')
        if card.ongoing_effect_id is not None:
            _name(card.ongoing_effect_id, 'ongoing effect ID')
            if (card.kind != CardType.SPELL or card.choice_only or card.quest is not None or
                    card.on_play is not None or card.requires_target or card.targeting is not None):
                raise ValueError('Ongoing activation requires an untargeted physical spell without quest')
        if card.dormant_turns is not None:
            _number(card.dormant_turns, 'dormant_turns', 0)
        if type(card.dormant_board_full) is not bool:
            raise ValueError('dormant_board_full must be boolean')
        if card.dormant_board_full and (card.kind != CardType.MINION or card.dormant_turns is not None or
                card.permanent_dormancy or card.starship_for or card.choice_only):
            raise ValueError('Full-board awakening requires an indefinite ordinary dormant minion')
        if type(card.permanent_dormancy) is not bool:
            raise ValueError('permanent_dormancy must be boolean')
        if card.permanent_dormancy and (card.kind != CardType.MINION or
                card.dormant_turns is not None or card.on_awaken is not None):
            raise ValueError('Permanent dormancy requires an indefinite minion without awakening')
        if (card.dormant_turns != 0 or card.on_awaken or card.dormant_triggers) and (
                card.kind != CardType.MINION or card.starship_for):
            raise ValueError('Dormancy definitions require ordinary minions')
        if type(card.dormant_triggers) is not tuple:
            raise ValueError('dormant_triggers must be an immutable tuple')
        if type(card.hand_actions) is not tuple or any(type(s) is not HandActionSpec for s in card.hand_actions):
            raise ValueError('hand_actions must be an immutable tuple of HandActionSpec')
        if card.hand_actions and not card.hand_playable:
            raise ValueError('Hand actions require a hand-playable definition')
        if len({s.id for s in card.hand_actions}) != len(card.hand_actions):
            raise ValueError('Duplicate hand action ID')
        for spec in card.hand_actions:
            spec.__post_init__()
            if spec.kind == 'prepare' and card.kind not in (CardType.MINION, CardType.SPELL):
                raise ValueError('Prepare currently supports minion and spell cards')
        if card.metadata is not None:
            if type(card.metadata) is not CardMetadata:
                raise ValueError('Expected CardMetadata')
            card.metadata.__post_init__()
            if card.metadata.subtypes and card.kind != CardType.MINION:
                raise ValueError('Printed subtypes require a minion definition')
            if card.choice_only and card.metadata.collectible:
                raise ValueError('Choice-only definitions cannot be collectible')
        if not isinstance(card.opening_hooks, tuple) or any(type(h) is not OpeningHook for h in card.opening_hooks):
            raise ValueError('opening_hooks must be an immutable tuple of OpeningHook')
        for hook in card.opening_hooks:
            hook.__post_init__()
        if type(card.hero_card) is not bool or type(card.keep_hero_class) is not bool:
            raise ValueError('Hero flags must be boolean')
        from .effects import validate_additional_power_policy
        validate_additional_power_policy(card.additional_power_policy)
        if card.additional_power_policy != 'preserve' and not card.hero_card:
            raise ValueError('Additional power replacement policy requires a playable hero')
        _number(card.hero_armor, 'hero armor', 0)
        if (card.hero_card or card.hero_armor or card.keep_hero_class) and card.kind != CardType.HERO:
            raise ValueError('Hero card fields require a hero definition')
        if card.hero_card and card.initial_hero_power is None:
            raise ValueError('Playable heroes require their replacement hero power')
        if (card.hero_armor or card.keep_hero_class) and not card.hero_card:
            raise ValueError('Hero card fields require a playable hero')
        if card.initial_hero_power is not None:
            _name(card.initial_hero_power, 'initial_hero_power')
            if card.kind != CardType.HERO:
                raise ValueError('Only heroes define an initial hero power')
        if card.spell_school is not None and (not isinstance(card.spell_school, SpellSchool) or card.kind != CardType.SPELL):
            raise ValueError('Spell schools require a spell definition and SpellSchool')
        if not isinstance(card.health_rules, tuple) or any(not isinstance(rule, HealthRule) for rule in card.health_rules):
            raise ValueError('health_rules must be a tuple of HealthRule')
        if card.health_rules and card.kind not in (CardType.HERO, CardType.MINION, CardType.WEAPON):
            raise ValueError('Health rules require an in-play aura holder')
        from .health_floors import validate_face as validate_floor_face
        if any(rule.operation.value == 'floor' for rule in card.health_rules):
            validate_floor_face(card)
        for rule in card.health_rules:
            rule.__post_init__()
            if card.kind == CardType.WEAPON and rule.redirect_to == 'self':
                raise ValueError('Weapons cannot receive redirected health effects')
        if (not isinstance(card.cost_auras, tuple) or any(type(a) is not CostAuraSpec for a in card.cost_auras)):
            raise ValueError('cost_auras must be a tuple of CostAuraSpec')
        if card.cost_auras and card.kind not in (CardType.MINION, CardType.WEAPON, CardType.LOCATION):
            raise ValueError('Cost auras require a minion, weapon or location')
        for aura in card.cost_auras:
            aura.__post_init__()
        from .costs import validate_cost_aura_definition
        validate_cost_aura_definition(card)
        if card.deck_sacrifice is not None:
            if type(card.deck_sacrifice) is not DeckSacrificeSpec or card.kind != CardType.MINION:
                raise ValueError('Deck sacrifice auras require a minion and DeckSacrificeSpec')
            card.deck_sacrifice.__post_init__()
        from .model import KeywordAuraSpec
        from .model import AttackPolicySpec
        if type(card.attack_policies) is not tuple or any(type(s) is not AttackPolicySpec for s in card.attack_policies):
            raise ValueError('attack_policies requires an immutable AttackPolicySpec tuple')
        if card.attack_policies and (card.kind not in (CardType.MINION, CardType.HERO, CardType.WEAPON) or card.choice_only):
            raise ValueError('Attack policies require a physical character or weapon')
        for spec in card.attack_policies:
            spec.__post_init__()
            if spec.mode=='friendly_ignore_taunt' and card.kind!=CardType.MINION:
                raise ValueError('Friendly Taunt bypass requires a native minion source')
        from .keyword_auras import validate_definition as validate_keyword_aura_definition
        validate_keyword_aura_definition(card)
        from .model import DeathrattleRepeatSpec
        if (type(card.deathrattle_repeats) is not tuple or
                any(type(s) is not DeathrattleRepeatSpec for s in card.deathrattle_repeats)):
            raise ValueError('deathrattle_repeats requires DeathrattleRepeatSpec declarations')
        if card.deathrattle_repeats and card.kind!=CardType.MINION:
            raise ValueError('Deathrattle repeat auras require a minion carrier')
        for spec in card.deathrattle_repeats: spec.__post_init__()
        from .model import HeroPowerRepeatSpec
        if (type(card.hero_power_repeats) is not tuple or
                any(type(s) is not HeroPowerRepeatSpec for s in card.hero_power_repeats)):
            raise ValueError('hero_power_repeats requires HeroPowerRepeatSpec declarations')
        if card.hero_power_repeats and card.kind != CardType.MINION:
            raise ValueError('Hero power repeat aura sources must be minions')
        for spec in card.hero_power_repeats: spec.__post_init__()
        from .model import EndTurnRepeatSpec
        if (type(card.end_turn_repeats) is not tuple or
                any(type(s) is not EndTurnRepeatSpec for s in card.end_turn_repeats)):
            raise ValueError('end_turn_repeats requires EndTurnRepeatSpec declarations')
        if card.end_turn_repeats and card.kind != CardType.MINION:
            raise ValueError('End-turn repeat aura sources must be minions')
        for spec in card.end_turn_repeats: spec.__post_init__()
        from .model import BattlecryRepeatSpec
        if (type(card.battlecry_repeats) is not tuple or
                any(type(a) is not BattlecryRepeatSpec for a in card.battlecry_repeats)):
            raise ValueError('battlecry_repeats requires a tuple of BattlecryRepeatSpec')
        if card.battlecry_repeats and card.kind != CardType.MINION:
            raise ValueError('Battlecry repeat aura sources must be minions')
        for spec in card.battlecry_repeats: spec.__post_init__()
        from .model import ComboRepeatSpec
        if (type(card.combo_repeats) is not tuple or
                any(type(a) is not ComboRepeatSpec for a in card.combo_repeats)):
            raise ValueError('combo_repeats requires a tuple of ComboRepeatSpec')
        if card.combo_repeats and card.kind != CardType.MINION:
            raise ValueError('Combo repeat aura sources must be minions')
        for spec in card.combo_repeats: spec.__post_init__()
        from .model import SpellRepeatSpec
        if type(card.retain_rewind_outcomes) is not bool or (card.retain_rewind_outcomes and card.kind != CardType.MINION):
            raise ValueError('Rewind retention must be a boolean minion ability')
        if (type(card.spell_repeats) is not tuple or
                any(type(a) is not SpellRepeatSpec for a in card.spell_repeats)):
            raise ValueError('spell_repeats requires a tuple of SpellRepeatSpec')
        if card.spell_repeats and card.kind != CardType.MINION:
            raise ValueError('Spell repeat aura sources must be minions')
        for spec in card.spell_repeats:
            spec.__post_init__()
        from .model import SummonQuantitySpec
        if type(card.summon_quantities) is not tuple or any(type(x) is not SummonQuantitySpec for x in card.summon_quantities):
            raise ValueError('Typed summon quantity declarations required')
        for x in card.summon_quantities:x.__post_init__()
        if card.summon_quantities:
            from .summon_quantities import validate_face as validate_quantity_face
            validate_quantity_face(card)
        from .model import HealthLossFloorSpec
        if type(card.health_loss_floors) is not tuple or any(type(s) is not HealthLossFloorSpec for s in card.health_loss_floors):
            raise ValueError('health_loss_floors requires a tuple of typed specifications')
        if card.health_loss_floors:
            from .health_loss_floors import validate_face
            validate_face(card)
        for spec in card.health_loss_floors: spec.__post_init__()
        from .model import HealthLossReplacementSpec
        if (type(card.health_loss_replacements) is not tuple or
                any(type(a) is not HealthLossReplacementSpec for a in card.health_loss_replacements)):
            raise ValueError('health_loss_replacements requires a tuple of specifications')
        if card.health_loss_replacements and card.kind != CardType.MINION:
            raise ValueError('Health loss replacement sources must be minions')
        for spec in card.health_loss_replacements:
            spec.__post_init__()
        from .model import WeaponWearSpec
        if type(card.weapon_wear_policies)is not tuple or any(type(s)is not WeaponWearSpec for s in card.weapon_wear_policies):raise ValueError('Expected typed weapon wear declarations')
        for s in card.weapon_wear_policies:
            s.__post_init__()
            expected=CardType.WEAPON if s.profile.scope=='self_weapon'else CardType.MINION
            if card.kind!=expected:raise ValueError('Wear profile has another physical carrier type')
        if card.corpse_value is not None:
            _number(card.corpse_value, 'corpse_value', 0)
            if card.kind != CardType.MINION:
                raise ValueError('Only minions may define corpse_value')
        for field in ("cost", "attack", "health"):
            _number(getattr(card, field), f"card {card.id} {field}", 0)
        if card.kind in (CardType.MINION, CardType.HERO) and card.health < 1 and not card.starship_for:
            raise ValueError(f"card {card.id} requires positive health")
        _number(card.durability, 'durability', 0)
        _number(card.uses_per_turn, 'uses_per_turn', 1)
        _name(card.use_rule, 'use_rule')
        if type(card.requires_board_space) is not bool:
            raise ValueError('requires_board_space must be boolean')
        if (card.kind in (CardType.WEAPON, CardType.LOCATION)) != (card.durability > 0):
            raise ValueError('Weapons and locations require positive durability')
        if card.kind in (CardType.HERO_POWER, CardType.LOCATION):
            if not card.passive_hero_power:
                _name(card.on_use, 'active ability on_use')
            if card.on_play is not None:
                raise ValueError('Hero powers and locations use on_use, not on_play')
        elif card.on_use is not None or card.uses_per_turn != 1 or card.use_rule != 'always' or card.requires_board_space:
            raise ValueError('Only hero powers and locations have use behavior and limits')
        if type(card.passive_hero_power) is not bool:
            raise ValueError('passive_hero_power must be boolean')
        if card.passive_hero_power and (card.kind != CardType.HERO_POWER or card.on_use is not None or
                not card.triggers or card.cost != 0 or card.uses_per_turn != 1 or card.use_rule != 'always' or
                card.requires_board_space or card.requires_target or card.targeting is not None or
                card.target_rule != 'any_entity' or card.rewind is not None):
            raise ValueError('Passive powers require triggers and no manual activation declaration')
        if card.kind in (CardType.WEAPON, CardType.HERO_POWER, CardType.LOCATION) and card.health != 0:
            raise ValueError('Weapons and hero powers have no character health')
        if card.kind == CardType.LOCATION and (card.attack or any(k!=Keyword.HERALD for k in card.keywords) or card.uses_per_turn != 1):
            raise ValueError('Locations permit printed Herald, no combat keywords/attack, and use cooldowns instead of use limits')
        if card.kind == CardType.WEAPON:
            from .equipment import WEAPON_KEYWORDS
            supported = WEAPON_KEYWORDS | {Keyword.SPELLBURST, Keyword.CORRUPT, Keyword.INFUSE,
                Keyword.CORRUPTED, Keyword.INFUSED, Keyword.FINALE, Keyword.MANATHIRST,
                Keyword.QUICKDRAW, Keyword.HERALD, Keyword.INVOKE, Keyword.COMBO}
            if any(k not in supported for k in card.keywords):
                raise ValueError('Unsupported weapon keyword')
        if not isinstance(card.keywords, tuple) or any(not isinstance(k, Keyword) for k in card.keywords):
            raise ValueError(f"card {card.id} keywords must be a tuple of Keyword values")
        if len(set(card.keywords)) != len(card.keywords):
            raise ValueError(f"card {card.id} contains duplicate keywords")
        if Keyword.DEATHRATTLE_SUPPRESSOR in card.keywords and card.kind != CardType.MINION:
            raise ValueError('Native Deathrattle prohibition sources must be minions')
        if Keyword.HERO_POWER_SUPPRESSOR in card.keywords and (card.kind != CardType.MINION or card.starship_for or
                Keyword.STARSHIP_PIECE in card.keywords):
            raise ValueError('Native Hero Power prohibition sources must be ordinary minions')
        if type(card.requires_target) is not bool:
            raise ValueError(f"card {card.id} requires_target must be boolean")
        _name(card.target_rule, f"card {card.id} target_rule")
        _number(card.spell_damage, f"card {card.id} spell_damage", 0)
        from .health_rules import validate_school_spell_damage_definition
        validate_school_spell_damage_definition(card)
        from .hero_powers import validate_use_aura_definition
        validate_use_aura_definition(card)
        from .cleave import validate_definition as validate_cleave_definition
        validate_cleave_definition(card)
        if card.spell_damage and card.kind not in (CardType.MINION, CardType.HERO):
            raise ValueError('Only in-play characters can provide spell damage')
        if card.targeting is not None:
            if not isinstance(card.targeting, TargetSpec):
                raise ValueError('targeting must be a TargetSpec')
            card.targeting.__post_init__()
            if card.requires_target:
                raise ValueError('Use targeting or requires_target, not both')
        for field in ("on_play", "battlecry", "combo", "deathrattle", "on_launch", "on_awaken", "on_discard", "on_destroyed"):
            value = getattr(card, field)
            if value is not None:
                _name(value, f"card {card.id} {field}")
        if type(card.stored_deathrattle) is not bool:
            raise ValueError('Stored Deathrattle permission requires bool')
        if card.stored_deathrattle and (card.kind != CardType.MINION or not card.hand_playable or
                card.deathrattle is None or card.on_discard is not None or card.on_destroyed is not None or card.starship_for):
            raise ValueError('Stored Deathrattle requires an independent physical native minion declaration')
        if not isinstance(card.triggers, tuple):
            raise ValueError(f"card {card.id} triggers must be a tuple")
        for trigger in (*card.triggers, *card.dormant_triggers):
            if not isinstance(trigger, TriggerSpec):
                raise ValueError(f"card {card.id} triggers must contain TriggerSpec values")
            _name(trigger.event, "trigger event")
            _name(trigger.behavior_id, "trigger behavior_id")
            trigger.__post_init__()
            if trigger.end_turn is not None and card.kind not in (CardType.MINION,CardType.WEAPON,CardType.LOCATION,CardType.HERO_POWER,CardType.HERO):
                raise ValueError('Classified end-turn declarations require supported trigger carriers')
        from .stat_relations import validate_definition as validate_stat_relation_definition
        validate_stat_relation_definition(card)
        from .stat_auras import validate_definition as validate_stat_aura_definition
        validate_stat_aura_definition(card)
        if card.deathrattle is not None and card.kind not in (CardType.MINION, CardType.WEAPON, CardType.LOCATION, CardType.HERO):
            raise ValueError('Only minions, weapons and locations support deathrattles')
        if card.triggers and card.kind not in (CardType.MINION, CardType.WEAPON, CardType.LOCATION, CardType.HERO_POWER, CardType.HERO):
            raise ValueError('This card type cannot carry event triggers')

    def validate(self) -> None:
        from .turn_start_draws import validate_profile as validate_turn_draw_profile
        for profile in self._turn_draw_profiles.values():validate_turn_draw_profile(self,profile)
        from .native_spell_values import validate_profile as validate_spell_value_profile
        for profile in self._spell_value_profiles.values():validate_spell_value_profile(self,profile)
        from .hero_health_targets import validate_profile as validate_hero_health_target_profile
        for profile in self._hero_health_target_profiles.values():validate_hero_health_target_profile(self,profile)
        from .kindred_targets import validate_profile as validate_kindred_target_profile
        for profile in self._kindred_target_profiles.values():validate_kindred_target_profile(self,profile)
        from .summon_attack_groups import validate_profile as validate_summon_attack_profile
        for profile in self._summon_attack_profiles.values():validate_summon_attack_profile(self,profile)
        from .corpse_gains import validate_profile as validate_corpse_gain_profile
        for profile in self._corpse_gain_profiles.values():validate_corpse_gain_profile(self, profile)
        from .corpse_summon_rewards import validate_profile as validate_corpse_summon_profile
        for profile in self._corpse_summon_profiles.values():validate_corpse_summon_profile(self,profile)
        from .spell_target_conditions import validate_profile as validate_spell_target_profile
        for profile in self._spell_target_profiles.values():validate_spell_target_profile(self,profile)
        if self._hand_mirror_ids!=frozenset(cid for cid,c in self._cards.items()if c.hand_mirror is not None):
            raise ValueError('Compiled native mirror declarations differ from registered faces')
        from .assemble_faces import validate_templates
        validate_templates(self)
        from .modular_decks import validate_profiles as validate_modular_profiles
        validate_modular_profiles(self)
        from .fabled_decks import validate_specs as validate_fabled_specs
        validate_fabled_specs(self)
        from .deck_size_rules import validate_rules as validate_deck_size_rules
        validate_deck_size_rules(self)
        from .sideboards import validate_profiles as validate_sideboard_profiles
        validate_sideboard_profiles(self)
        from .historical_body_targets import validate_binding as validate_historical_binding
        for key,binding in self._historical_battlecry_bindings.items():
            validate_historical_binding(self,binding)
            if key != (binding.carrier_card_id,binding.profile_id):
                raise ValueError('Historical Battlecry binding changed its registered identity')
        from .generated_body_targets import validate_binding as validate_generated_target_binding
        for key,binding in self._generated_whole_target_bindings.items():
            validate_generated_target_binding(self,binding)
            if key != (binding.carrier_card_id,binding.profile_id):
                raise ValueError('Generated whole target binding differs from its registered identity')
        from .indirect_body_targets import validate_binding as validate_indirect_binding
        for key,binding in self._indirect_battlecry_bindings.items():
            validate_indirect_binding(self,binding)
            if key != (binding.carrier_card_id,binding.profile_id):
                raise ValueError('Indirect Battlecry binding differs from its registered identity')
        from .player_target_inputs import PlayerTargetRuleSpec
        for rule_id, spec in self._player_target_rules.items():
            if (type(spec) is not PlayerTargetRuleSpec or spec.id != rule_id
                    or self._target_visibility.get(rule_id) != 'player'):
                raise ValueError('Player target rule differs from its registered original-input identity')
            spec.__post_init__()
        from .target_predicates import TargetPredicateSpec
        for rule_id, spec in self._target_predicates.items():
            if (type(spec) is not TargetPredicateSpec or spec.id != rule_id or
                    self._target_visibility.get(rule_id) != 'builtin'):
                raise ValueError('Declarative target rule differs from its registered engine-owned identity')
            spec.__post_init__()
        from .body_root_targets import validate_root_binding
        for key, binding in self._body_root_target_bindings.items():
            validate_root_binding(self, binding)
            if key != (binding.carrier_card_id, binding.profile_id):
                raise ValueError('Root targeting policy identity differs from its registered key')
        from .body_target_authority import validate_binding
        for key, binding in self._body_target_bindings.items():
            validate_binding(self, binding)
            if key != (binding.declaration_card_id, binding.family, binding.profile_id):
                raise ValueError('Body target binding identity differs from its registered key')
        from .body_targets import BodyTargetProfile
        for profile_id, profile in self._body_target_profiles.items():
            if type(profile) is not BodyTargetProfile or profile.id != profile_id:
                raise ValueError('Body target profile identity differs from its registered key')
            profile.__post_init__()
        for profile in self._end_turn_profiles.values():
            profile.__post_init__()
        for profile in self._end_turn_candidate_profiles.values():
            profile.__post_init__()
        for profile in self._repeat_witness_profiles.values():
            profile.__post_init__()
        for profile_id, profile in self._cost_query_profiles.items():
            if type(profile) is not CostQueryProfile or profile.id != profile_id:
                raise ValueError('Cost query profile identity differs from its registered key')
            profile.__post_init__()
        from .repeat_source_conditions import validate_source_declaration
        family_members = {}
        for key, members in self._generation_families.items():
            if (type(members) is not tuple or len(members) < 2 or
                    any(type(cid) is not str or not cid.strip() for cid in members) or
                    members != tuple(sorted(set(members))) or key != members[0] or
                    any(cid in family_members for cid in members)):
                raise ValueError('Invalid registered generation family')
            family_members.update((cid, key) for cid in members)
        if family_members != self._generation_family_members:
            raise ValueError('Generation family lookup differs from its complete declarations')
        validate_pools(self)
        from .imbue import validate_profiles as validate_imbue_profiles
        validate_imbue_profiles(self)
        from .invoke import validate_profile as validate_invoke_profile
        validate_invoke_profile(self)
        from .mana_ranks import validate_families as validate_mana_rank_families
        validate_mana_rank_families(self)
        from .unidentified import validate_families as validate_unidentified_families
        validate_unidentified_families(self)
        from .game_boards import validate_families as validate_board_families
        validate_board_families(self)
        from .tourists import validate_specs as validate_tourist_specs
        validate_tourist_specs(self)
        from .jade import validate_families as validate_jade_families
        validate_jade_families(self)
        from .cthun import validate_profile as validate_cthun_profile
        validate_cthun_profile(self)
        from .excavate import validate_profiles
        validate_profiles(self)
        from .shatter import validate_definitions
        validate_definitions(self)
        from .temporary_cards import validate_definitions as validate_hand_repeats
        validate_hand_repeats(self)
        from .hand_derivatives import validate_definitions as validate_derivatives
        validate_derivatives(self)
        from .rewind import validate_definitions as validate_rewind_definitions
        validate_rewind_definitions(self)
        for profile in self._summon_producer_profiles.values():
            profile.__post_init__()
        logical_units = {profile.unit_id for profile in self._summon_producer_profiles.values()}
        for spec in self._player_effects.values():
            if any(declaration.unit_id not in logical_units for declaration in spec.producer_quantities):
                raise ValueError('Player effect refers to an unknown logical summon unit')
            spec.__post_init__()
            for repeat in (*spec.deathrattle_repeats, *spec.end_turn_repeats):
                validate_source_declaration(self, repeat, allow_source=False)
            if self.card(spec.card_id).choice_only:
                raise ValueError('Player effects require a physical display card')
            for behavior_id in (spec.on_expire, *(t.behavior_id for t in spec.triggers)):
                if behavior_id is not None:
                    self.behavior(behavior_id)
            for trigger in spec.triggers:
                if trigger.end_turn is not None: self.trigger_condition(trigger.end_turn.condition_id)
            for aura in spec.auras:
                for card_id in aura.card_ids:
                    if self.card(card_id).kind != CardType.MINION:
                        raise ValueError('Player stat auras only filter minion definitions')
        ship_classes = set()
        herald_classes = set()
        for card in (*self._cards.values(), *self._modular_modules.values()):
            for aura in (*card.auras, *card.keyword_auras):
                for card_id in aura.card_ids:
                    if self.card(card_id).kind != CardType.MINION:
                        raise ValueError('Native card identity auras only filter registered minions')
            if card.choose_one is not None:
                for selected in (*card.choose_one.branches,card.choose_one.combined):
                    self.behavior(selected.behavior_id)
                    if selected.targeting is not None: self.target_rule(selected.target_rule)
            if card.cast_when_drawn is not None and card.cast_when_drawn.after_draw is not None:
                self.behavior(card.cast_when_drawn.after_draw)
            if card.herald_soldier_for is not None:
                if card.herald_soldier_for in herald_classes:
                    raise ValueError('Multiple Herald Soldiers registered for one class')
                herald_classes.add(card.herald_soldier_for)
            for spec in card.colossal:
                limb=self.card(spec.card_id)
                if limb.kind!=CardType.MINION or limb.choice_only or limb.starship_for or limb.colossal:
                    raise ValueError('Appendages must be physical, non-composite, non-Colossal minions')
            self._validate_card(card)
            for spec in (*card.spell_repeats, *card.battlecry_repeats,
                         *card.combo_repeats, *card.deathrattle_repeats,
                         *card.hero_power_repeats, *card.end_turn_repeats):
                validate_source_declaration(self, spec)
            from .repeat_matching import validate_repeat_cost_declaration
            for spec in card.spell_repeats:
                validate_repeat_cost_declaration(self, spec)
            if ship_classes.intersection(card.starship_for):
                raise ValueError('Multiple Starship bodies registered for one class')
            ship_classes.update(card.starship_for)
            references = (card.interactable.behavior_id if card.interactable is not None else None,
                          card.on_play, card.battlecry, card.combo, card.on_use, card.on_launch, card.on_awaken, card.deathrattle, card.on_discard, card.on_destroyed,
                          *(trigger.behavior_id for trigger in (*card.triggers, *card.dormant_triggers)),
                          *(hook.behavior_id for hook in card.opening_hooks))
            for behavior_id in references:
                if behavior_id is not None:
                    self.behavior(behavior_id)
            for trigger in (*card.triggers,*card.dormant_triggers):
                if trigger.end_turn is not None:
                    self.trigger_condition(trigger.end_turn.condition_id)
            if card.quest is not None:
                for stage in card.quest.stages:
                    self.behavior(stage.progress_behavior)
                    self.behavior(stage.reward_behavior)
                    if stage.card_id != card.id and not self.card(stage.card_id).choice_only:
                        raise ValueError('Additional quest stages require nonphysical descriptors')
            if card.secret is not None:
                self.secret_condition(card.secret.condition_id)
                self.behavior(card.secret.behavior_id)
            if card.ongoing_effect_id is not None:
                spec = self.player_effect(card.ongoing_effect_id)
                if spec.kind == 'persistent' or spec.card_id != card.id:
                    raise ValueError('Ongoing spells require their own timed effect specification')
            for spec in card.activated_abilities:
                self.validate_activation(spec)
            for spec in card.limited_triggers:
                self.validate_limited_trigger(spec)
            if card.hand_progress is not None:
                self.validate_hand_progress(card.hand_progress, card.kind)
            if card.defining_hand_source is not None:
                self.validate_hand_progress(card.defining_hand_source, card.kind)
            for spec in card.hand_actions:
                self.use_rule(spec.use_rule)
                if spec.on_use is not None:
                    self.behavior(spec.on_use)
                if spec.upgrade_card_id is not None and self.card(spec.upgrade_card_id).kind != card.kind:
                    raise ValueError('Forge upgrade must preserve card type')
            if card.requires_target or card.targeting is not None:
                self.target_rule(card.target_rule)
            if card.kind in (CardType.HERO_POWER, CardType.LOCATION):
                self.use_rule(card.use_rule)
            if card.initial_hero_power is not None and self.card(card.initial_hero_power).kind != CardType.HERO_POWER:
                raise ValueError('Initial hero power must identify a hero power definition')
            if card.native_deathrattle is not None and card.native_deathrattle.kind=='summon_growth':
                token=self.card(card.native_deathrattle.card_id)
                if token.kind!=CardType.MINION or token.choice_only:
                    raise ValueError('Native Deathrattle summon requires its complete physical minion dependency')

    def validate_activation(self, spec):
        spec.__post_init__()
        self.behavior(spec.behavior_id)
        self.use_rule(spec.use_rule)
        if spec.targeting is not None:
            self.target_rule(spec.target_rule)
        if spec.card_id is not None and not self.card(spec.card_id).choice_only:
            raise ValueError('Ability display card must be a nonphysical choice-only descriptor')

    def freeze(self) -> None:
        self.validate()
        self._frozen = True

    def fingerprint(self) -> str:
        self.validate()
        def definition_data(card):
            data = asdict(card)
            if data['reborn_policy'] is None:
                data.pop('reborn_policy')
            if data['hand_mirror'] is None:
                data.pop('hand_mirror')
            if data['native_condition'] is None:
                data.pop('native_condition')
            if data['dormant_board_full'] is False:
                data.pop('dormant_board_full')
            if data['native_deathrattle'] is None:
                data.pop('native_deathrattle')
            if data['cost_payment'] == PaymentType.MANA:
                data.pop('cost_payment')
            if not data['permanent_dormancy']:
                data.pop('permanent_dormancy')
            if data['manual_playable']:
                data.pop('manual_playable')
            if not data['requires_weapon']:
                data.pop('requires_weapon')
            if not data['pay_health_if_hero_healed']:
                data.pop('pay_health_if_hero_healed')
            if data['hero_power_use_aura'] is None:
                data.pop('hero_power_use_aura')
            if data['defining_hand_source'] is None:
                data.pop('defining_hand_source')
            for spec in data['limited_triggers']:
                if spec['reset'] == 'instance': spec.pop('reset')
            for spec in data['cost_auras']:
                if not spec['first_per_turn']: spec.pop('first_per_turn')
                if spec['every_nth_per_turn'] is None: spec.pop('every_nth_per_turn')
            return data
        definitions = []
        for card_id in sorted(self._cards):
            data = definition_data(self._cards[card_id])
            if data['interactable'] is None:
                data.pop('interactable')
            if data['on_discard'] is None:
                data.pop('on_discard')
            if data['on_destroyed'] is None:
                data.pop('on_destroyed')
            if not data['stored_deathrattle']:
                data.pop('stored_deathrattle')
            data["keywords"] = sorted(data["keywords"])
            definitions.append(data)
        payload = {"version": self.version, "cards": definitions,
                   "player_effects": [{k:v for k,v in asdict(self._player_effects[i]).items()
                                       if (k != 'target_policy' or v is not None) and
                                          (k != 'allowed_card_types' or v) and
                                          (k != 'next_turn_end' or v)} for i in sorted(self._player_effects)],
                   "summon_producer_profiles": [asdict(self._summon_producer_profiles[i]) for i in sorted(self._summon_producer_profiles)],
                   "end_turn_profiles": [asdict(self._end_turn_profiles[i]) for i in sorted(self._end_turn_profiles)],
                   "end_turn_candidate_profiles": [asdict(self._end_turn_candidate_profiles[i]) for i in sorted(self._end_turn_candidate_profiles)],
                   "repeat_witness_profiles": [asdict(self._repeat_witness_profiles[i]) for i in sorted(self._repeat_witness_profiles)],
                   "cost_query_profiles": [asdict(self._cost_query_profiles[i]) for i in sorted(self._cost_query_profiles)],
                   "pool_cards": [asdict(self._pool_cards[i]) for i in sorted(self._pool_cards)],
                   "pools": [asdict(self._pools[i]) for i in sorted(self._pools)],
                   "excavation_profiles": [asdict(self._excavation_profiles[i]) for i in sorted(self._excavation_profiles)],
                   "imbue_profiles": [asdict(self._imbue_profiles[i]) for i in sorted(self._imbue_profiles)],
                   "behaviors": sorted(self._behaviors), "target_rules": sorted(self._target_rules),
                   "secret_conditions": sorted(self._secret_conditions),
                   "trigger_conditions": sorted(self._trigger_conditions),
                   "use_rules": sorted(self._use_rules),
                   "target_visibility": self._target_visibility, "use_visibility": self._use_visibility}
        # Preserve old registry fingerprints when this additive API is unused.
        if self._kindred_profiles:
            payload['kindred_profiles']=[asdict(self._kindred_profiles[k])for k in sorted(self._kindred_profiles)]
        if self._spell_target_profiles:
            payload['spell_target_profiles']=[asdict(self._spell_target_profiles[k])for k in sorted(self._spell_target_profiles)]
        if self._turn_draw_profiles:
            payload['turn_draw_profiles']=[asdict(self._turn_draw_profiles[k])for k in sorted(self._turn_draw_profiles)]
        if self._spell_value_profiles:
            payload['spell_value_profiles']=[asdict(self._spell_value_profiles[k])for k in sorted(self._spell_value_profiles)]
        if self._hero_health_target_profiles:
            payload['hero_health_target_profiles']=[asdict(self._hero_health_target_profiles[k])for k in sorted(self._hero_health_target_profiles)]
        if self._generation_families:
            payload['generation_families'] = [self._generation_families[k] for k in sorted(self._generation_families)]
        if self._kindred_target_profiles:
            payload['kindred_target_profiles']=[asdict(self._kindred_target_profiles[k])for k in sorted(self._kindred_target_profiles)]
        if self._corpse_summon_profiles:
            payload['corpse_summon_profiles']=[asdict(self._corpse_summon_profiles[k])for k in sorted(self._corpse_summon_profiles)]
        if self._corpse_gain_profiles:
            payload['corpse_gain_profiles']=[asdict(self._corpse_gain_profiles[k])for k in sorted(self._corpse_gain_profiles)]
        if self._summon_attack_profiles:
            payload['summon_attack_profiles']=[asdict(self._summon_attack_profiles[k])for k in sorted(self._summon_attack_profiles)]
        if self._assemble_templates:
            payload['assemble_templates'] = [asdict(self._assemble_templates[k]) for k in sorted(self._assemble_templates)]
        if self._invoke_profile is not None:
            payload['invoke_profile'] = asdict(self._invoke_profile)
        if self._mana_rank_families:
            payload['mana_rank_families'] = [asdict(self._mana_rank_families[k]) for k in sorted(self._mana_rank_families)]
        if self._unidentified_families:
            payload['unidentified_families'] = [asdict(self._unidentified_families[k]) for k in sorted(self._unidentified_families)]
        if self._board_card_families:
            payload['board_card_families'] = [asdict(self._board_card_families[k]) for k in sorted(self._board_card_families)]
        if self._tourists:
            payload['tourists'] = [asdict(self._tourists[k]) for k in sorted(self._tourists)]
        if self._sideboards:
            payload['sideboards'] = [asdict(self._sideboards[k]) for k in sorted(self._sideboards)]
        if self._deck_size_rules:
            payload['deck_size_rules'] = [asdict(self._deck_size_rules[k]) for k in sorted(self._deck_size_rules)]
        if self._fabled:
            payload['fabled'] = [asdict(self._fabled[k]) for k in sorted(self._fabled)]
        if self._modular_profiles:
            payload['modular_profiles'] = [asdict(self._modular_profiles[k]) for k in sorted(self._modular_profiles)]
            payload['modular_modules'] = [definition_data(self._modular_modules[k]) for k in sorted(self._modular_modules)]
            payload['modular_faces'] = [asdict(self._modular_faces[k]) for k in sorted(self._modular_faces)]
        if self._jade_families:
            payload['jade_families'] = [asdict(self._jade_families[k]) for k in sorted(self._jade_families)]
        if self._cthun_profile is not None:
            payload['cthun_profile'] = asdict(self._cthun_profile)
        if self._body_target_profiles:
            payload['body_target_profiles'] = [asdict(self._body_target_profiles[i]) for i in sorted(self._body_target_profiles)]
        if self._body_target_bindings:
            payload['body_target_bindings'] = [asdict(self._body_target_bindings[k]) for k in sorted(self._body_target_bindings)]
        if self._body_root_target_bindings:
            payload['body_root_target_bindings'] = [asdict(self._body_root_target_bindings[k]) for k in sorted(self._body_root_target_bindings)]
        if self._indirect_battlecry_bindings:
            payload['indirect_battlecry_bindings'] = [asdict(self._indirect_battlecry_bindings[k]) for k in sorted(self._indirect_battlecry_bindings)]
        if self._historical_battlecry_bindings:
            payload['historical_battlecry_bindings'] = [asdict(self._historical_battlecry_bindings[k]) for k in sorted(self._historical_battlecry_bindings)]
        if self._generated_whole_target_bindings:
            payload['generated_whole_target_bindings'] = [asdict(self._generated_whole_target_bindings[k]) for k in sorted(self._generated_whole_target_bindings)]
        if self._target_predicates:
            payload['target_predicates'] = [{k:v for k,v in asdict(self._target_predicates[i]).items()
                if k != 'printed_rarities' or v} for i in sorted(self._target_predicates)]
        if self._player_target_rules:
            payload['player_target_rules'] = [asdict(self._player_target_rules[i]) for i in sorted(self._player_target_rules)]
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
