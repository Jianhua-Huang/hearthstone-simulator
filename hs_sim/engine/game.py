"""Public match API. All accepted actions commit at a stable resolution boundary."""
from __future__ import annotations
from .hand_capacity import hand_capacity
from .turn_clocks import AdvanceTurnTime, history_action_to_dict, snapshot_value as clock_snapshot

from copy import deepcopy
from dataclasses import asdict, dataclass
import random
from itertools import combinations
from math import comb

from .actions import UseMinionAbility, Action, Attack, EndTurn, PlayCard, UseHeroPower, UseLocation, UseHandAction, LaunchStarship, SelectChoice, action_from_dict, action_to_dict
from .errors import IllegalAction, ResolutionError, ResolutionLimitExceeded, SnapshotError
from .continuations import FrameCodec, validate_frame
from .choices import resume_choice
from .construction import MatchSetup, validate_setup
from .pools import GenerationContext
from .opening import BeginGame, validate_opening_boundary
from .model import CardType, Event, GameState, Keyword, OpeningState, PlayerState, Resource, TargetMode, Zone, validate_invariants
from .costs import quote_cost, payment_error
from .resources import mana_balance, refresh_mana
from .registry import Registry
from .resolver import BeginAttack, EndTurnPhase, Mechanics, PlayFromHand, Resolution, default_mechanics
from .rules import Ruleset
from .serialization import SNAPSHOT_SCHEMA_VERSION
from .combat import attack_error
from .targeting import legal_target_ids, target_choices, target_error
from .hero_powers import ActivateHeroPower, use_error
from .starships import ActivateStarship, construction, launch_error
from .minion_abilities import ActivateMinionAbility, ability_error, ability_definition, remaining_abilities, specification as minion_specification
from .locations import ActivateLocation, location_error
from .play_history import play_definition
from .hand_actions import ActivateHandAction, hand_action_error, quote_hand_action, specification, specifications
from .serialization import canonical_hash, event_from_dict, event_to_dict, rng_from_json, rng_to_json, state_from_dict, state_to_dict
from .actions import UseInteractable, Concede
from .interactables import ActivateInteractable, use_error as interactable_error


@dataclass(frozen=True)
class PlayerSetup:
    hero_card_id: str
    deck: tuple[str, ...] = ()
    hand: tuple[str, ...] = ()
    board: tuple[str, ...] = ()
    max_mana: int = 0
    mana: int = 0
    armor: int = 0
    weapon_card_id: str | None = None
    hero_power_card_id: str | None = None
    mana_cap: int | None = None
    temporary_mana: int = 0
    overload_owed: int = 0
    overload_locked: int = 0
    corpses: int = 0
    additional_hero_power_card_ids: tuple[str, ...] = ()
    hand_cap: int | None = None

    def __post_init__(self):
        if not isinstance(self.hero_card_id, str) or not self.hero_card_id:
            raise ValueError('hero_card_id must be a nonempty string')
        for field in ('weapon_card_id', 'hero_power_card_id'):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f'{field} must be a nonempty definition ID or None')
        for field in ('deck', 'hand', 'board', 'additional_hero_power_card_ids'):
            items = getattr(self, field)
            if not isinstance(items, tuple) or any(not isinstance(i, str) or not i for i in items):
                raise ValueError(f'{field} must be a tuple of definition IDs')
        for field in ('max_mana', 'mana', 'armor', 'temporary_mana', 'overload_owed', 'overload_locked', 'corpses'):
            if type(getattr(self, field)) is not int or getattr(self, field) < 0:
                raise ValueError(f'{field} must be a nonnegative integer')
        if self.mana_cap is not None and (type(self.mana_cap) is not int or self.mana_cap < 0):
            raise ValueError('mana_cap must be a nonnegative integer or None')
        if self.hand_cap is not None and (type(self.hand_cap) is not int or self.hand_cap < 1):
            raise ValueError('hand_cap must be a positive integer or None')
        if self.mana > max(0, self.max_mana - self.overload_locked + self.temporary_mana):
            raise ValueError('Starting mana exceeds available accounts')


@dataclass(frozen=True)
class Scenario:
    players: tuple[PlayerSetup, PlayerSetup]
    active_player: int = 1
    seed: int = 0
    name: str = 'scenario'
    generation_context: GenerationContext | None = None
    board_id: int | None = None

    def __post_init__(self):
        from .game_boards import validate_board_id
        validate_board_id(self.board_id)
        if not isinstance(self.players, tuple) or len(self.players) != 2 or any(not isinstance(p, PlayerSetup) for p in self.players):
            raise ValueError('Scenario requires exactly two PlayerSetup objects')
        if type(self.active_player) is not int or self.active_player not in (1, 2):
            raise ValueError('active_player must be 1 or 2')
        if type(self.seed) is not int or not isinstance(self.name, str):
            raise ValueError('Invalid scenario seed or name')
        if self.generation_context is not None:
            if type(self.generation_context) is not GenerationContext:
                raise ValueError('Expected GenerationContext')
            self.generation_context.__post_init__()

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - {'players', 'active_player', 'seed', 'name', 'generation_context', 'board_id'}:
            raise ValueError('Invalid scenario fields')
        value = dict(value)
        if value.get('generation_context') is not None:
            value['generation_context'] = GenerationContext.from_dict(value['generation_context'])
        players = value.pop('players', None)
        if not isinstance(players, list) or len(players) != 2:
            raise ValueError('Scenario JSON requires a two-player array')
        result = []
        for row in players:
            if not isinstance(row, dict):
                raise ValueError('Player setup must be an object')
            row = dict(row)
            for field in ('deck', 'hand', 'board', 'additional_hero_power_card_ids'):
                if field in row:
                    if not isinstance(row[field], list):
                        raise ValueError(f'{field} must be an array')
                    row[field] = tuple(row[field])
            result.append(PlayerSetup(**row))
        return cls(players=tuple(result), **value)


@dataclass(frozen=True)
class ActionResult:
    events: tuple[Event, ...]
    state_hash: str


class Game:
    """Owns state, deterministic RNG, and a versioned mechanism set.

    Use the factory methods. A Game is single-threaded; independent clones can
    be explored in parallel. Callback closures must be deterministic and pure.
    """
    def __init__(self):
        self._resolving = False
        self._frame = None
        self._match_setup = None
        self._generation_context = None
        self._information = None
        self._rewind = None

    def _require_boundary(self):
        if self._resolving:
            raise ResolutionError('This operation requires a completed action boundary')

    @classmethod
    def from_scenario(cls, scenario: Scenario, registry: Registry,
                      ruleset: Ruleset | None = None, mechanics: Mechanics | None = None):
        if not isinstance(scenario, Scenario):
            raise ValueError('Expected a Scenario')
        if ruleset is not None and type(ruleset) is not Ruleset:
            raise ValueError('Custom Ruleset subclasses cannot be restored; use a supported Ruleset')
        game = cls()
        game._generation_context = scenario.generation_context
        game.registry = registry
        registry.freeze()
        game.ruleset = ruleset or Ruleset()
        game.mechanics = (mechanics or default_mechanics()).freeze()
        game._registry_fingerprint = registry.fingerprint()
        game._rng = random.Random(scenario.seed)
        game._state = GameState(players={i: PlayerState(i, 0) for i in (1, 2)}, entities={},
            active_player=scenario.active_player, board_id=scenario.board_id)
        if game._generation_context is not None and game._generation_context.starting_decks is not None:
            for player_id, cards in enumerate(game._generation_context.starting_decks, 1):
                game._state.players[player_id].original_deck = cards
        game._events = []
        game._history = []
        resolution = Resolution(game)
        for player_id, setup in enumerate(scenario.players, 1):
            definition = registry.card(setup.hero_card_id)
            if definition.kind != CardType.HERO:
                raise ValueError('Hero setup requires a hero definition')
            hero = resolution.create_entity(player_id, setup.hero_card_id, Zone.HERO, ready=True)
            hero.armor = setup.armor
            player = game._state.players[player_id]
            player.hand_cap = setup.hand_cap
            if len(setup.hand) > hand_capacity(player, game.ruleset):
                raise ValueError('Initial hand exceeds player capacity')
            player.mana, player.max_mana = setup.mana, setup.max_mana
            player.mana_cap = game.ruleset.max_mana if setup.mana_cap is None else setup.mana_cap
            player.temporary_mana = setup.temporary_mana
            player.overload_owed, player.overload_locked = setup.overload_owed, setup.overload_locked
            player.mana_spent = max(0, setup.max_mana - setup.overload_locked + setup.temporary_mana - setup.mana)
            player.resources[Resource.CORPSES] = setup.corpses
            refresh_mana(player)
            for field, kind, zone in (('weapon_card_id', CardType.WEAPON, Zone.WEAPON),
                                      ('hero_power_card_id', CardType.HERO_POWER, Zone.HERO_POWER)):
                card_id = getattr(setup, field)
                if card_id is not None:
                    if registry.card(card_id).kind != kind:
                        raise ValueError(f'{field} requires a {kind} definition')
                    resolution.create_entity(player_id, card_id, zone, ready=True, hand_entry_reason='scenario')
                    if kind == CardType.HERO_POWER:
                        player.starting_hero_power_card_id = card_id
            for card_id in setup.additional_hero_power_card_ids:
                resolution.create_entity(player_id, card_id, Zone.HERO_POWER, additional_hero_power=True)
            for zone in (Zone.DECK, Zone.HAND, Zone.BOARD):
                for card_id in getattr(setup, zone.value):
                    definition = registry.card(card_id)
                    if definition.choice_only:
                        raise ResolutionError('Choice-only definitions cannot become physical cards')
                    if not definition.hand_playable or (zone == Zone.BOARD and definition.kind not in (CardType.MINION, CardType.LOCATION)):
                        raise ValueError(f'Invalid {definition.kind} in setup {zone}')
                    resolution.create_entity(player_id, card_id, zone, ready=True, hand_entry_reason='scenario')
        from .shatter import settle_hands
        settle_hands(resolution, initial=True)
        resolution.refresh_auras()
        from .invoke import synchronize as synchronize_galakrond
        synchronize_galakrond(game._state, registry)
        from .information import Information
        game._information = Information()
        from .mana_ranks import synchronize as synchronize_mana_ranks
        synchronize_mana_ranks(resolution)
        from .unidentified import synchronize as synchronize_unidentified
        synchronize_unidentified(resolution)
        game._information.sync(game)
        from .owner_turns import start_owner_turn
        start_owner_turn(game._state, len(game._events), origin='scenario')
        from .dormancy import capture_board_full
        initial_conditions = Resolution(game)
        from .hand_parity import synchronize as synchronize_hand_parity
        from .live_hand_spells import settle as settle_live_hand_spells
        settle_live_hand_spells(initial_conditions)
        synchronize_hand_parity(initial_conditions, initial=True)
        initial_work = [*initial_conditions._captured, *capture_board_full(initial_conditions)]
        initial_conditions._captured.clear()
        if initial_work:
            initial_conditions.run(initial_work)
        game._assert_stable()
        game._origin = game.snapshot()
        return game

    @classmethod
    def from_decks(cls, setup: MatchSetup, registry: Registry,
                   ruleset: Ruleset | None = None, mechanics: Mechanics | None = None):
        ruleset = ruleset or Ruleset()
        validate_setup(setup, registry, ruleset)
        scenario = Scenario(tuple(PlayerSetup(deck.hero_card_id, deck=deck.cards,
                            hero_power_card_id=deck.hero_power_card_id) for deck in setup.decks), seed=setup.seed,
                            board_id=setup.board_id, generation_context=GenerationContext(setup.policy.target_id, setup.policy.mode,
                                tuple(deck.cards for deck in setup.decks)))
        game = cls.from_scenario(scenario, registry, ruleset, mechanics)
        # The scenario used to construct physical entities is not a real
        # constructed turn. Opening can suspend or end before StartFirstTurn.
        game._state.owner_turn_history.clear()
        game._match_setup = setup
        from .opening_turn_order import choose as choose_turn_order,publish as publish_turn_order
        first,turn_order_proof = choose_turn_order(game)
        game._state.active_player = first
        game._state.opening = OpeningState(first, original_entities=tuple(tuple(p.deck) for p in game._state.players.values()))
        for player_id, deck in enumerate(setup.decks, 1):
            player = game._state.players[player_id]
            player.deck_class, player.runes, player.original_deck = deck.card_class, deck.runes, deck.cards
            from .sideboards import SideboardState
            player.sideboards = tuple(SideboardState(b.source_card_id, b.cards) for b in deck.sideboards)
        game._resolving = True
        try:
            resolution=Resolution(game)
            publish_turn_order(resolution,turn_order_proof)
            resolution.run([BeginGame()])
            game._information.sync(game)
            game._assert_stable()
        except Exception as exc:
            if isinstance(exc, ResolutionError):
                raise
            raise ResolutionError(f'Opening failed before a game was returned: {exc}') from exc
        finally:
            game._resolving = False
        game._origin = game.snapshot()
        return game

    @property
    def state(self):
        return deepcopy(self._state)

    @property
    def events(self):
        return tuple(deepcopy(self._events))

    @property
    def history(self):
        return deepcopy(self._history)

    @property
    def origin(self):
        return deepcopy(self._origin)

    def observe(self, viewer):
        """Detached player DTO; excludes engine IDs, RNG, frames and private data.

        The trusted host binds viewer to its authenticated seat. Passing a Game
        itself to an untrusted agent still exposes its omniscient host APIs.
        """
        self._require_boundary()
        return deepcopy(self._information.observe(self, viewer))

    def for_player(self, viewer):
        """Bind a trusted host-selected seat to the restricted JSON command API."""
        from .player_api import PlayerPort
        self._require_boundary()
        return PlayerPort(self, viewer)

    def player_events(self, viewer, *, after=0):
        """Event-time filtered log, with a viewer-local contiguous cursor."""
        from .information import player_id
        self._require_boundary()
        player_id(viewer)
        events = self._information.players[viewer].events
        if type(after) is not int or not 0 <= after <= len(events):
            raise ValueError('Invalid player event cursor')
        return deepcopy(events[after:])

    def clone(self):
        self._require_boundary()
        result = type(self)()
        result.registry, result.ruleset, result.mechanics = self.registry, self.ruleset, self.mechanics
        result._registry_fingerprint = self._registry_fingerprint
        result._state = deepcopy(self._state)
        result._frame = deepcopy(self._frame)
        result._match_setup = self._match_setup
        result._generation_context = self._generation_context
        result._information = deepcopy(self._information)
        result._rewind = deepcopy(self._rewind)
        result._rng = random.Random()
        result._rng.setstate(self._rng.getstate())
        result._events = deepcopy(self._events)
        result._history = deepcopy(self._history)
        result._origin = deepcopy(self._origin)
        return result

    def _hash_payload(self):
        payload = {'ruleset': asdict(self.ruleset), 'registry_fingerprint': self._registry_fingerprint,
                'mechanics_version': self.mechanics.signature, 'state': state_to_dict(self._state),
                'rng_state': rng_to_json(self._rng.getstate()),
                'resolution_frame': FrameCodec(self.mechanics, self.registry).encode(self._frame),
                'rewind_session': self._rewind.to_dict() if self._rewind is not None else None,
                'match_setup': self._match_setup.to_dict() if self._match_setup is not None else None,
                'generation_context': self._generation_context.to_dict() if self._generation_context is not None else None,
                'information': self._information.to_dict()}
        clock = clock_snapshot(self)
        if clock is not None: payload['turn_clock'] = clock
        from .vanished_cards import snapshot_value as vanished_snapshot
        vanished = vanished_snapshot(self)
        if vanished is not None: payload['vanished_cards'] = vanished
        return payload

    def state_hash(self):
        return canonical_hash(self._hash_payload())

    def snapshot(self):
        self._require_boundary()
        events = [event_to_dict(event) for event in self._events]
        return deepcopy({'schema_version': SNAPSHOT_SCHEMA_VERSION, **self._hash_payload(), 'events': events,
                         'events_hash': canonical_hash(events), 'state_hash': self.state_hash()})

    @classmethod
    def from_snapshot(cls, snapshot: dict, registry: Registry, mechanics: Mechanics | None = None):
        try:
            expected = {'schema_version', 'ruleset', 'registry_fingerprint', 'mechanics_version',
                        'state', 'rng_state', 'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information', 'events', 'events_hash', 'state_hash'}
            if isinstance(snapshot, dict):
                expected.update(key for key in ('turn_clock','vanished_cards') if key in snapshot)
            if not isinstance(snapshot, dict) or set(snapshot) != expected:
                raise ValueError('Snapshot fields do not match schema')
            if type(snapshot['schema_version']) is not int or snapshot['schema_version'] != SNAPSHOT_SCHEMA_VERSION:
                raise ValueError(f'Unsupported snapshot schema version; schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1} need their original engines')
            game = cls()
            game.registry = registry
            registry.freeze()
            game._registry_fingerprint = registry.fingerprint()
            if snapshot['registry_fingerprint'] != game._registry_fingerprint:
                raise ValueError('Registry version/fingerprint mismatch')
            game.mechanics = (mechanics or default_mechanics()).freeze()
            if snapshot['mechanics_version'] != game.mechanics.signature:
                raise ValueError('Mechanics version mismatch')
            game.ruleset = Ruleset(**snapshot['ruleset'])
            if snapshot['generation_context'] is not None:
                game._generation_context = GenerationContext.from_dict(snapshot['generation_context'])
            if snapshot['match_setup'] is not None:
                if type(snapshot['match_setup']) is not dict or 'board_id' not in snapshot['match_setup']:
                    raise ValueError('Saved match setup requires its explicit game board field')
                if any(type(d) is not dict or 'sideboards' not in d for d in snapshot['match_setup'].get('decks', ())):
                    raise ValueError('Saved decks require their explicit sideboard fields')
                game._match_setup = MatchSetup.from_dict(snapshot['match_setup'])
                validate_setup(game._match_setup, registry, game.ruleset)
            game._state = state_from_dict(snapshot['state'])
            game._frame = FrameCodec(game.mechanics, registry).decode(snapshot['resolution_frame'])
            from .information import Information
            game._information = Information.from_dict(snapshot['information'], game)
            if snapshot['rewind_session'] is not None:
                from .rewind import RewindSession
                game._rewind = RewindSession.from_dict(snapshot['rewind_session'], game)
            game._rng = random.Random()
            game._rng.setstate(rng_from_json(snapshot['rng_state']))
            if not isinstance(snapshot['events'], list):
                raise ValueError('Events must be an array')
            if canonical_hash(snapshot['events']) != snapshot['events_hash']:
                raise ValueError('Event digest mismatch')
            game._events = [event_from_dict(e) for e in snapshot['events']]
            for sequence, event in enumerate(game._events, 1):
                if type(event.sequence) is not int or event.sequence != sequence:
                    raise ValueError('Invalid event sequence')
                if type(event.action) is not int or not 0 <= event.action <= game._state.action_number:
                    raise ValueError('Invalid event action number')
                if not isinstance(event.kind, str) or not event.kind or type(event.amount) is not int:
                    raise ValueError('Invalid event record')
            from .health_floors import validate_event_results
            validate_event_results(game._state, registry, game._events)
            from .joust import validate_events as validate_joust_events
            validate_joust_events(game._state, registry, game._events)
            from .deck_reveals import validate_events as validate_deck_reveal_events
            validate_deck_reveal_events(game._state, registry, game._events)
            from .health_loss_floors import validate_event_results as validate_loss_floor_events
            validate_loss_floor_events(game._state, registry, game._events)
            from .resources import validate_armor_loss_events
            validate_armor_loss_events(game._state,game._events)
            from .death_neighbors import validate_events as validate_death_neighbor_events
            validate_death_neighbor_events(game._state, game._events)
            from .summon_entry_stats import validate_boundary as validate_entry_stat_programs
            validate_entry_stat_programs(game)
            from .summon_completions import validate_boundary as validate_summon_completions
            validate_summon_completions(game)
            from .resources import validate_mana_consumption_events
            validate_mana_consumption_events(game._state,game._events)
            from .equipment import validate_weapon_transfer_events
            validate_weapon_transfer_events(game._state,registry,game._events)
            from .zones import validate_stored_destruction_events
            validate_stored_destruction_events(game._state,registry,game._events)
            game._history = []
            from .resource_operations import validate_committed_events as validate_committed_resource_events
            validate_committed_resource_events(game)
            game._assert_stable()
            clock = clock_snapshot(game)
            if (clock is None and 'turn_clock' in snapshot or clock is not None and snapshot.get('turn_clock') != clock):
                raise ValueError('Saved turn-clock commitment differs from complete original time receipts')
            from .vanished_cards import snapshot_value as vanished_snapshot
            vanished = vanished_snapshot(game)
            if vanished is None and 'vanished_cards' in snapshot or vanished is not None and snapshot.get('vanished_cards') != vanished:
                raise ValueError('Saved original-card custody differs from complete disappearance receipts')
            if game.state_hash() != snapshot['state_hash']:
                raise ValueError('State digest mismatch')
            from .weapon_wear import validate_committed_events as validate_closed_wear
            validate_closed_wear(game)
            # A restored snapshot starts a new replay branch at this boundary.
            game._origin = game.snapshot()
            return game
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            raise SnapshotError(f'Invalid snapshot: {exc}') from exc

    def _assert_stable(self):
        from .natural_turn_end import validate_boundary as validate_natural_turn_end_boundary
        validate_natural_turn_end_boundary(self)
        from .controlled_turns import validate_boundary as validate_controlled_turn_boundary
        validate_controlled_turn_boundary(self)
        if self._match_setup is not None and self._match_setup.board_id != self._state.board_id:
            raise ValueError('Game board differs from its fixed constructed match setup')
        from .tourists import validate_boundary as validate_tourist_boundary
        validate_tourist_boundary(self)
        from .deck_size_rules import validate_boundary as validate_deck_size_boundary
        validate_deck_size_boundary(self)
        from .fabled_decks import validate_boundary as validate_fabled_boundary
        validate_fabled_boundary(self)
        from .modular_decks import validate_boundary as validate_modular_boundary
        validate_modular_boundary(self)
        from .sideboards import validate_boundary as validate_sideboard_boundary
        validate_sideboard_boundary(self)
        from .void_decks import validate_boundary as validate_void_boundary
        validate_void_boundary(self)
        from .excavate import validate_context as validate_excavation_context
        validate_excavation_context(self)
        if self._generation_context is not None:
            from .starting_generation import validate_context as validate_generation_context
            validate_generation_context(self._generation_context, self._state)
        if self._match_setup is not None and self._generation_context != GenerationContext(
                self._match_setup.policy.target_id, self._match_setup.policy.mode,
                tuple(deck.cards for deck in self._match_setup.decks)):
            raise ValueError('Generation context differs from the constructed match target/mode')
        validate_invariants(self._state, self.registry)
        from .card_discoveries import validate_boundary as validate_card_discovery_boundary
        validate_card_discovery_boundary(self)
        from .discovery_delivery import validate_boundary as validate_discovery_delivery_boundary
        validate_discovery_delivery_boundary(self)
        from .hand_mirrors import validate_game as validate_hand_mirrors
        validate_hand_mirrors(self)
        from .held_battlecry_forms import validate_game as validate_held_battlecry_forms
        validate_held_battlecry_forms(self)
        from .named_minion_boons import validate_game as validate_named_boons
        validate_named_boons(self)
        from .cost_presence import validate_game as validate_controlled_prices
        validate_controlled_prices(self)
        from .adjoining_spells import validate_game as validate_adjoining_spells
        validate_adjoining_spells(self)
        from .composed_spells import validate_game as validate_composed_spells
        validate_composed_spells(self)
        from .composed_locations import validate_game as validate_composed_locations
        validate_composed_locations(self)
        from .suspicious_discoveries import validate_game as validate_suspicious_discoveries
        validate_suspicious_discoveries(self)
        from .sham_trials import validate_game as validate_sham_trials
        validate_sham_trials(self)
        from .card_packs import validate_game as validate_card_packs
        validate_card_packs(self)
        from .coin_replacements import validate_boundary as validate_coin_replacements
        validate_coin_replacements(self)
        from .prison_playback import validate_boundary as validate_prison_playback
        validate_prison_playback(self)
        from .native_target_acceptance import validate_boundary as validate_native_target_acceptance
        validate_native_target_acceptance(self)
        from .native_attack_targets import validate_boundary as validate_native_attack_targets
        validate_native_attack_targets(self)
        from .native_active_targets import validate_boundary as validate_native_active_targets
        validate_native_active_targets(self)
        from .native_hand_targets import validate_boundary as validate_native_hand_targets
        validate_native_hand_targets(self)
        from .spell_target_groups import validate_boundary as validate_spell_target_groups
        validate_spell_target_groups(self)
        from .spell_mirrors import validate_game as validate_spell_mirrors
        validate_spell_mirrors(self)
        from .remaining_mana_numbers import validate_game as validate_remaining_numbers
        validate_remaining_numbers(self)
        from .infused_battlecries import validate_game as validate_infused_battlecries
        validate_infused_battlecries(self)
        from .rotating_discovery_classes import validate_game as validate_discovery_classes
        validate_discovery_classes(self)
        from .next_spell_bonuses import validate_game as validate_native_spell_bonuses
        validate_native_spell_bonuses(self)
        from .next_spell_bodies import validate_game as validate_next_spell_bodies
        validate_next_spell_bodies(self)
        from .colossal_reserves import validate_game as validate_colossal_reserves
        validate_colossal_reserves(self)
        from .scrambled_summons import validate_boundary as validate_scrambled_summons
        validate_scrambled_summons(self)
        from .mana_ranks import validate_state as validate_mana_rank_state
        validate_mana_rank_state(self._state, self.registry)
        from .unidentified import validate_state as validate_unidentified_state
        validate_unidentified_state(self._state, self.registry)
        from .choose_policies import boundary as validate_choose_policy_boundary
        validate_choose_policy_boundary(self)
        from .body_conditions import validate_boundary as validate_body_condition_boundary
        validate_body_condition_boundary(self)
        from .owner_turns import validate_boundary as validate_owner_turn_boundary
        validate_owner_turn_boundary(self)
        from .kindred import validate_boundary as validate_kindred_boundary
        validate_kindred_boundary(self)
        from .paid_hand_acceptance import validate_boundary as validate_paid_hand_boundary
        validate_paid_hand_boundary(self)
        from .hero_powers import validate_boundary as validate_power_boundary
        validate_power_boundary(self)
        from .battlecries import validate_boundary as validate_battlecry_boundary
        validate_battlecry_boundary(self)
        from .combos import validate_boundary as validate_combo_boundary
        validate_combo_boundary(self)
        from .combo_acceptance import validate_boundary as validate_combo_acceptance_boundary
        validate_combo_acceptance_boundary(self)
        from .deathrattles import validate_boundary as validate_deathrattle_boundary
        validate_deathrattle_boundary(self)
        from .end_turns import validate_boundary as validate_end_turn_boundary
        validate_end_turn_boundary(self)
        from .whole_card_replay_state import validate_boundary as validate_whole_card_replay_boundary
        validate_whole_card_replay_boundary(self)
        from .shatter import validate_boundary as validate_shatter_boundary
        validate_shatter_boundary(self)
        validate_frame(self)
        from .resources import validate_mana_consumption_events
        validate_mana_consumption_events(self._state,self._events)
        from .equipment import validate_weapon_transfer_events
        validate_weapon_transfer_events(self._state,self.registry,self._events)
        from .zones import validate_stored_destruction_events
        validate_stored_destruction_events(self._state,self.registry,self._events)
        from .invoke import validate_events as validate_invoke_events
        validate_invoke_events(self._state, self.registry, self._events)
        from .jade import validate_events as validate_jade_events
        validate_jade_events(self._state, self._events)
        from .cthun import validate_events as validate_cthun_events
        validate_cthun_events(self._state, self._events)
        from .hero_attack_history import validate_boundary as validate_hero_attack_boundary
        validate_hero_attack_boundary(self)
        from .character_attacks import validate_boundary as validate_character_attack_boundary
        validate_character_attack_boundary(self)
        from .resource_operations import validate_boundary as validate_resource_boundary
        validate_resource_boundary(self)
        from .resources import validate_corpse_boundary
        validate_corpse_boundary(self)
        from .overload_history import validate_boundary as validate_overload_boundary
        validate_overload_boundary(self)
        from .hero_health_history import validate_boundary as validate_hero_health_change_boundary
        validate_hero_health_change_boundary(self)
        from .armor_gains import validate_boundary as validate_armor_gain_boundary
        validate_armor_gain_boundary(self)
        from .armor_consumption import validate_events as validate_armor_consumption_events
        validate_armor_consumption_events(self._state, self.registry, self._events)
        from .recruit_stat_groups import validate_boundary as validate_recruit_stat_group_boundary
        validate_recruit_stat_group_boundary(self)
        from .rituals import validate_boundary as validate_ritual_boundary
        validate_ritual_boundary(self)
        from .armor_summon_rewards import validate_boundary as validate_armor_summon_reward_boundary
        validate_armor_summon_reward_boundary(self)
        from .health_history import validate_boundary as validate_health_boundary
        validate_health_boundary(self)
        from .deck_shuffles import validate_boundary as validate_shuffle_boundary
        validate_shuffle_boundary(self)
        from .location_uses import validate_boundary as validate_location_use_boundary
        validate_location_use_boundary(self)
        from .discard_history import validate_boundary as validate_discard_boundary
        validate_discard_boundary(self)
        from .successful_summons import validate_boundary as validate_successful_summon_boundary
        validate_successful_summon_boundary(self)
        from .summon_quantities import validate_boundary as validate_card_summon_boundary
        validate_card_summon_boundary(self)
        from .nythendra_reform import validate_boundary as validate_nythendra_boundary
        validate_nythendra_boundary(self)
        from .overdraw_returns import validate_boundary as validate_overdraw_boundary
        validate_overdraw_boundary(self)
        from .quest_hand_rewards import validate_boundary as validate_quest_hand_reward_boundary
        validate_quest_hand_reward_boundary(self)
        from .minion_base_programs import validate_boundary as validate_minion_bases
        validate_minion_bases(self)
        from .fixed_reward_splits import validate_boundary as validate_fixed_reward_splits
        validate_fixed_reward_splits(self)
        from .summon_quantities import validate_closed_events as validate_card_summon_events
        validate_card_summon_events(self)
        from .pool_summons import validate_boundary as validate_pool_summon_boundary,validate_closed_events as validate_pool_summon_events
        validate_pool_summon_boundary(self)
        validate_pool_summon_events(self)
        from .minion_families import validate_boundary as validate_minion_families
        validate_minion_families(self)
        from .ordered_group_batches import validate_boundary as validate_ordered_group_boundary,validate_closed_events as validate_ordered_group_events
        validate_ordered_group_boundary(self)
        validate_ordered_group_events(self)
        from .discovery_summons import validate_boundary as validate_discovery_summon_boundary,validate_closed_events as validate_discovery_summon_events
        validate_discovery_summon_boundary(self)
        validate_discovery_summon_events(self)
        from .hand_choice_followups import validate_boundary as validate_hand_followup_boundary
        validate_hand_followup_boundary(self)
        from .temporary_hands import validate_boundary as validate_temporary_hand_boundary
        validate_temporary_hand_boundary(self)
        from .future_hand_returns import validate_boundary as validate_future_hand_boundary
        validate_future_hand_boundary(self)
        from .consumed_cards import validate_boundary as validate_consumed_card_boundary
        validate_consumed_card_boundary(self)
        from .spell_auras import validate_boundary as validate_spell_aura_boundary
        validate_spell_aura_boundary(self)
        from .hand_deadlines import validate_boundary as validate_hand_deadline_boundary
        validate_hand_deadline_boundary(self)
        from .interactables import validate_boundary as validate_interactable_boundary
        validate_interactable_boundary(self)
        from .recruit_summons import validate_boundary as validate_recruit_summon_boundary,validate_closed_events as validate_recruit_summon_events
        validate_recruit_summon_boundary(self)
        validate_recruit_summon_events(self)
        from .resurrection_summons import validate_boundary as validate_resurrection_summon_boundary,validate_closed_events as validate_resurrection_summon_events
        validate_resurrection_summon_boundary(self)
        validate_resurrection_summon_events(self)
        from .ability_families import validate_boundary as validate_ability_family_boundary
        validate_ability_family_boundary(self)
        from .random_split_damage import validate_boundary as validate_split_damage_boundary
        validate_split_damage_boundary(self)
        from .random_split_damage import validate_closed_events as validate_closed_split_events
        validate_closed_split_events(self)
        from .hero_lethal_windows import validate_boundary as validate_hero_lethal_boundary
        validate_hero_lethal_boundary(self)
        from .concession import validate_boundary as validate_concession_boundary
        validate_concession_boundary(self)
        from .colossal import validate_boundary
        validate_boundary(self)
        from .summon_sources import validate_boundary as validate_resurrection_boundary
        validate_resurrection_boundary(self)
        from .discovery import validate_boundary as validate_discovery_boundary
        validate_discovery_boundary(self)
        from .generated_spell_healing import validate_boundary as validate_generated_healing_boundary
        validate_generated_healing_boundary(self)
        from .playable_spell_generation import validate_events as validate_playable_spell_events
        validate_playable_spell_events(self)
        from .assemble_offers import validate_boundary as validate_assembly_boundary
        validate_assembly_boundary(self)
        from .crafted_offers import validate_boundary as validate_craft_boundary
        validate_craft_boundary(self)
        from .pool_offers import validate_boundary as validate_offer_boundary
        validate_offer_boundary(self)
        from .spell_mana_budget import validate_boundary as validate_spell_budget_boundary
        validate_spell_budget_boundary(self)
        from .carved_spells import validate_boundary as validate_carved_boundary
        validate_carved_boundary(self)
        from .student_teaching import validate_boundary as validate_student_teaching_boundary
        validate_student_teaching_boundary(self)
        from .issued_spell_sets import validate_boundary as validate_issued_spell_sets_boundary
        validate_issued_spell_sets_boundary(self)
        from .live_hand_spells import validate_boundary as validate_live_hand_spell_boundary
        validate_live_hand_spell_boundary(self)
        from .native_stat_gains import validate_boundary as validate_native_stat_gain_boundary
        validate_native_stat_gain_boundary(self)
        from .cross_zone import validate_boundary as validate_cross_zone_boundary
        validate_cross_zone_boundary(self)
        from .hand_progress import validate_defining_history
        validate_defining_history(self)
        from .pools import validate_summon_boundary
        validate_summon_boundary(self)
        from .spell_repeats import validate_boundary as validate_repeat_boundary
        validate_repeat_boundary(self)
        from .spell_acceptance import validate_boundary as validate_spell_acceptance_boundary
        validate_spell_acceptance_boundary(self)
        from .spell_casts import validate_boundary as validate_cast_boundary
        validate_cast_boundary(self)
        from .draw_casts import validate_boundary as validate_draw_boundary
        validate_draw_boundary(self)
        from .hand_history import validate_publications
        validate_publications(self)
        from .spell_history import validate_boundary as validate_spell_batch_boundary
        validate_spell_batch_boundary(self)
        from .rewind import validate_boundary as validate_rewind_boundary
        validate_rewind_boundary(self)
        from .rewind_outcomes import validate_boundary as validate_outcome_boundary
        validate_outcome_boundary(self)
        from .minion_plays import validate_boundary as validate_minion_play_boundary
        validate_minion_play_boundary(self)
        if self._state.status == 'playing' and self._frame is None and self._state.action_windows:
            raise ValueError('Unsettled action window at action boundary')
        if self._frame is None and any(not p.completed and not p.interrupted for p in self._state.play_history):
            raise ValueError('Unsettled play at action boundary')
        deferred = self._frame is not None and self._frame.death_deferrals > 0
        validate_opening_boundary(self)
        from .turn_clocks import validate_boundary as validate_turn_clock
        validate_turn_clock(self)
        from .location_rune_locks import validate_boundary as validate_location_locks
        validate_location_locks(self)
        from .spell_mana_freeze import validate_boundary as validate_spell_mana_freeze
        validate_spell_mana_freeze(self)
        from .vanished_cards import validate_boundary as validate_vanished_cards
        validate_vanished_cards(self)
        self._information.validate(self)
        from .battlecry_weapon_outputs import validate_events as validate_weapon_output_events
        validate_weapon_output_events(self)
        from .aura_duration import validate_events as validate_aura_duration_events
        validate_aura_duration_events(self)
        from .deck_stat_distribution import validate_events as validate_deck_stat_distribution_events
        validate_deck_stat_distribution_events(self)
        from .timed_keywords import validate_boundary as validate_timed_keywords
        validate_timed_keywords(self)
        from .corpse_summon_rewards import validate_boundary as validate_corpse_summon_boundary
        validate_corpse_summon_boundary(self)
        from .summon_keyword_groups import validate_boundary as validate_outcast_summon_boundary
        validate_outcast_summon_boundary(self)
        from .turn_scheduling import validate_boundary as validate_turn_schedule
        validate_turn_schedule(self)
        from .joust import validate_boundary as validate_joust_boundary
        validate_joust_boundary(self)
        from .deck_reveals import validate_boundary as validate_deck_reveal_boundary
        validate_deck_reveal_boundary(self)
        from .card_creation import validate_boundary as validate_creation_boundary
        validate_creation_boundary(self)
        from .prepare import validate_boundary as validate_prepare_boundary
        validate_prepare_boundary(self)
        from .hand_turn_costs import validate_boundary as validate_hand_turn_costs
        validate_hand_turn_costs(self)
        for entity in self._state.entities.values():
            if any(a.expires_turn is not None and a.expires_turn < self._state.turn
                   for a in [*entity.abilities, *entity.enchantments]):
                raise ValueError('Expired attachment at action boundary')
        for player in self._state.players.values():
            if player.weapon_id is not None:
                weapon = self._state.entities[player.weapon_id]
                if not deferred and (weapon.durability <= 0 or weapon.doomed):
                    raise ValueError('Unsettled broken weapon at action boundary')
            hand_capacity(player, self.ruleset)  # Validate the account, including overfull held hands.
            if len(player.board) > self.ruleset.max_board:
                raise ValueError('Zone capacity exceeded')
            if (not 0 <= player.max_mana <= player.mana_cap or player.mana < 0 or
                    player.mana_spent > player.max_mana or
                    player.mana != max(0, mana_balance(player))):
                raise ValueError('Invalid mana state')
            if any(m.expires_turn is not None and m.expires_turn < self._state.turn for m in player.choose_both_modifiers):
                raise ValueError('Expired Choose Both policy at action boundary')
            if any(m.expires_turn is not None and m.expires_turn < self._state.turn for m in player.combo_modifiers):
                raise ValueError('Expired Combo modifier at action boundary')
            if any(m.expires_turn is not None and m.expires_turn < self._state.turn for m in player.battlecry_modifiers):
                raise ValueError('Expired Battlecry modifier at action boundary')
            if any(m.expires_turn is not None and m.expires_turn < self._state.turn for m in player.cost_modifiers):
                raise ValueError('Expired cost modifier at action boundary')
            for entity_id in player.board:
                entity = self._state.entities[entity_id]
                if not deferred and entity.active and (entity.doomed or
                        (entity.durability <= 0 if entity.kind == CardType.LOCATION else entity.health <= 0)):
                    raise ValueError('Unsettled dead minion at action boundary')
        if self._state.status == 'playing' and any(self._state.entities[p.hero_id].health <= 0 or
                                                  self._state.entities[p.hero_id].doomed for p in self._state.players.values()):
            from .hero_lethal_windows import permits_dying_wait
            if not permits_dying_wait(self):
                raise ValueError('A playing match cannot have a dead hero without a genuine complete fatal waiting boundary')
        for player in self._state.players.values():
            if len(player.quests) > self.ruleset.max_quests:
                raise ValueError('Quest capacity exceeded')
            from .secrets import area_count
            if area_count(player, self.registry) > self.ruleset.max_secret_zone:
                raise ValueError('Shared secret area capacity exceeded')
            secret_keys = [self.registry.card(self._state.entities[i].card_id).secret.key for i in player.secrets]
            if len(set(secret_keys)) != len(secret_keys):
                raise ValueError('Duplicate active secrets')
            from .player_effects import timed_count
            if timed_count(player, self.registry) > self.ruleset.max_ongoing_effects:
                raise ValueError('Ongoing effect capacity exceeded')
            cards = [self._state.entities[i].card_id for i in player.quests]
            from .quests import compatible_main_quests
            if len(set(cards)) != len(cards) or not compatible_main_quests(self._state, self.registry, player.id):
                raise ValueError('Duplicate or incompatible active quests')
            if self._state.status == 'playing' and self._frame is None and any(
                    self._state.entities[i].quest_progress.completing for i in player.quests):
                raise ValueError('Unsettled quest reward at action boundary')
        def derived(e):
            return (e.aura_attack, e.aura_health, e.attack_bonus, e.health_bonus, e.cost_modifier,
                    e.weapon_attack, frozenset(e.weapon_keywords), frozenset(e.aura_keywords),
                    frozenset(e.hand_aura_keywords), frozenset(e.conditional_keywords), e.conditional_attack, e.conditional_health,
                    frozenset(e.keywords), e.frozen_until_owner_turn)
        before = {i: derived(e) for i, e in self._state.entities.items()}
        Resolution(self).refresh_auras(include_dying=deferred, emit_freeze_changes=False)
        if before != {i: derived(e) for i, e in self._state.entities.items()}:
            raise ValueError('Stale derived attachment or aura values')

    def validate(self, action: Action):
        if type(action) is AdvanceTurnTime:
            from .turn_clocks import validate_input
            return validate_input(self, action)
        if type(action) is PlayCard:
            from .hand_admission import root_target_contract
            return self._validate_action(action, play_target_definition=root_target_contract(self, action))
        return self._validate_action(action)

    def _validate_action(self, action: Action, *, play_target_definition=None):
        self._require_boundary()
        # The codecs also reject boolean IDs, unknown fields and malformed values.
        try:
            action = action_from_dict(action_to_dict(action))
        except (ValueError, TypeError) as exc:
            raise IllegalAction(str(exc)) from exc
        state = self._state
        if state.status != 'playing':
            raise IllegalAction('The game has ended')
        if type(action) is Concede:
            return
        choice = state.pending_choice
        if choice is not None:
            if not isinstance(action, SelectChoice):
                raise IllegalAction('A pending choice must be resolved first')
            if action.player_id != choice.player_id or action.choice_id != choice.id:
                raise IllegalAction('Wrong choice owner or stale choice ID')
            if (set(action.option_ids) - {o.id for o in choice.options} or
                    not choice.min_count <= len(action.option_ids) <= choice.max_count):
                raise IllegalAction('Invalid choice options or selection count')
            return
        if isinstance(action, SelectChoice):
            raise IllegalAction('There is no pending choice')
        if state.opening is not None and state.opening.stage != 'complete':
            raise IllegalAction('The opening must finish before normal actions')
        if action.player_id != state.active_player:
            raise IllegalAction('It is not this player\'s turn')
        player = state.players[action.player_id]
        from .player_api import context_factory
        context = context_factory(self, player.id)
        if isinstance(action, EndTurn):
            return
        if isinstance(action, UseInteractable):
            if reason := interactable_error(state, self.registry, player.id,
                    action.entity_id, action.card_entity_id):
                raise IllegalAction(reason)
            return
        if isinstance(action, UseMinionAbility):
            reason = ability_error(state, self.registry, self.ruleset, player.id, action.entity_id,
                                   action.ability_id, action.target_id, context_factory=context)
            if reason is not None:
                raise IllegalAction(reason)
            return
        if isinstance(action, UseLocation):
            reason = location_error(state, self.registry, self.ruleset, player.id, action.entity_id, context_factory=context)
            if reason is None:
                source = state.entities[action.entity_id]
                reason = target_error(state, self.registry, source, self.registry.card(source.card_id), action.target_id, context_factory=context)
            if reason is not None:
                raise IllegalAction(reason)
            return
        if isinstance(action, LaunchStarship):
            if reason := launch_error(state, player.id, action.entity_id):
                raise IllegalAction(reason)
            return
        if isinstance(action, UseHandAction):
            if action.entity_id not in player.hand:
                raise IllegalAction('Hand action requires an owned hand card')
            source = state.entities[action.entity_id]
            reason = hand_action_error(state, self.registry, player, source, action.action_id, context_factory=context)
            if reason is not None:
                raise IllegalAction(reason)
            return
        if isinstance(action, UseHeroPower):
            if action.entity_id not in player.hero_power_ids:
                raise IllegalAction('This is not the current hero power')
            source = state.entities[action.entity_id]
            from .choose_one import selection_error, effective
            definition = self.registry.card(source.card_id)
            reason = selection_error(state,definition,player.id,action.branch_id,self.ruleset,entity=source)
            if reason is None:
                reason = use_error(state, self.registry, self.ruleset, player, source, context_factory=context, branch_id=action.branch_id)
            if reason is None:
                reason = target_error(state, self.registry, source, effective(definition,action.branch_id), action.target_id, context_factory=context)
            if reason is not None:
                raise IllegalAction(reason)
            return
        if isinstance(action, PlayCard):
            from .hand_admission import validate_hand_play
            return validate_hand_play(state, self.registry, self.ruleset, action,
                context=context, play_target_definition=play_target_definition)
        if isinstance(action, Attack):
            reason = attack_error(state, action.attacker_id, action.defender_id, player.id, registry=self.registry)
            if reason is not None:
                raise IllegalAction(reason)
            return
        raise IllegalAction('Unsupported action')

    def quote_cost(self, entity_id):
        """Immutable current price for an active hand card or current hero power."""
        self._require_boundary()
        player = self._state.players[self._state.active_player]
        if type(entity_id) is not int or (entity_id not in player.hand and entity_id not in player.hero_power_ids):
            raise IllegalAction('Cost query requires an active hand card or hero power')
        return quote_cost(self._state, self.registry, self._state.entities[entity_id])

    def quote_hand_action(self, entity_id, action_id):
        self._require_boundary()
        player = self._state.players[self._state.active_player]
        if type(entity_id) is not int or entity_id not in player.hand or type(action_id) is not str:
            raise IllegalAction('Hand price query requires an active hand card and action ID')
        source = self._state.entities[entity_id]
        spec = specification(self.registry, source, action_id)
        if spec is None:
            raise IllegalAction('This card has no such hand action')
        return quote_hand_action(self._state, self.registry, source, spec)

    def legal_targets(self, entity_id, *, branch_id=None):
        """Selectable IDs for an active hand card, hero power or location.

        This does not assert affordability or board space. None choices are
        represented by legal_actions according to the card's target mode.
        """
        self._require_boundary()
        player = self._state.players[self._state.active_player]
        locations = [i for i in player.board if self._state.entities[i].kind == CardType.LOCATION]
        if type(entity_id) is not int or (entity_id not in player.hand and entity_id not in player.hero_power_ids and entity_id not in locations):
            raise IllegalAction('Target query requires an active hand card, hero power or location')
        source = self._state.entities[entity_id]
        from .player_api import context_factory
        definition = self.registry.card(source.card_id)
        from .choose_one import effective, branches
        if branch_id not in branches(self._state,definition,player.id,entity=source):
            raise IllegalAction('Choose a currently available branch before querying targets')
        return legal_target_ids(self._state, self.registry, source,
                                play_definition(self._state, self.registry, source,branch_id=branch_id) if source.zone == Zone.HAND else effective(definition,branch_id),
                                context_factory=context_factory(self, player.id))

    def legal_ability_targets(self, entity_id, ability_id):
        self._require_boundary()
        player = self._state.players[self._state.active_player]
        if type(entity_id) is not int or entity_id not in player.board:
            raise IllegalAction('Ability target query requires a controlled board minion')
        source = self._state.entities[entity_id]
        ability = minion_specification(source, ability_id)
        if ability is None:
            raise IllegalAction('Missing or exhausted minion ability')
        from .player_api import context_factory
        return legal_target_ids(self._state, self.registry, source,
            ability_definition(self.registry, source, ability.activation),
            context_factory=context_factory(self, player.id))

    def legal_actions(self):
        self._require_boundary()
        if self._state.status != 'playing':
            return ()
        state, result = self._state, [Concede(1), Concede(2)]
        if state.pending_choice is not None:
            choice = state.pending_choice
            count = sum(comb(len(choice.options), n) for n in range(choice.min_count, choice.max_count + 1))
            if count > self.ruleset.max_choice_combinations:
                raise ResolutionLimitExceeded('Choice action enumeration exceeds combination limit; submit a selection directly')
            return (*result, *tuple(SelectChoice(choice.player_id, choice.id, ids)
                         for n in range(choice.min_count, choice.max_count + 1)
                         for ids in combinations(tuple(o.id for o in choice.options), n)))
        player = state.players[state.active_player]
        enemy = state.players[3 - player.id]
        from .player_api import context_factory
        context = context_factory(self, player.id)
        for entity_id in player.hand:
            source = state.entities[entity_id]
            for spec in specifications(self.registry, source):
                candidate = UseHandAction(player.id, entity_id, spec.id)
                try:
                    self.validate(candidate)
                except IllegalAction:
                    continue
                result.append(candidate)
            from .hand_admission import hand_plays
            result.extend(hand_plays(self, source, validator=self.validate, context=context))
        for entity_id in player.hero_power_ids:
            source = state.entities[entity_id]
            from .choose_one import branches, effective
            definition = self.registry.card(source.card_id)
            for branch_id in branches(state,definition,player.id,entity=state.entities[entity_id]):
                for target in target_choices(state, self.registry, source, effective(definition,branch_id), context_factory=context):
                    candidate = UseHeroPower(player.id, source.id, target, branch_id)
                    try:
                        self.validate(candidate)
                    except IllegalAction:
                        continue
                    result.append(candidate)
        for entity_id in player.board:
            source = state.entities[entity_id]
            if source.kind != CardType.LOCATION:
                continue
            for target in target_choices(state, self.registry, source, self.registry.card(source.card_id), context_factory=context):
                candidate = UseLocation(player.id, source.id, target)
                try:
                    self.validate(candidate)
                except IllegalAction:
                    continue
                result.append(candidate)
        for entity_id in player.board:
            source = state.entities[entity_id]
            for ability in remaining_abilities(source):
                spec = ability.activation
                for target in target_choices(state, self.registry, source,
                        ability_definition(self.registry, source, spec), context_factory=context):
                    candidate = UseMinionAbility(player.id, source.id, spec.id, target)
                    try:
                        self.validate(candidate)
                    except IllegalAction:
                        continue
                    result.append(candidate)
        for entity_id in player.board:
            if not state.entities[entity_id].interactable_object:
                continue
            for card_entity_id in player.hand:
                candidate = UseInteractable(player.id, entity_id, card_entity_id)
                try:
                    self.validate(candidate)
                except IllegalAction:
                    continue
                result.append(candidate)
        ship = construction(state, player.id)
        if ship is not None and launch_error(state, player.id, ship.id) is None:
            result.append(LaunchStarship(player.id, ship.id))
        for attacker in [player.hero_id, *player.board]:
            for defender in [enemy.hero_id, *enemy.board]:
                candidate = Attack(player.id, attacker, defender)
                try:
                    self.validate(candidate)
                except IllegalAction:
                    continue
                result.append(candidate)
        from .body_player_commands import independent_play_actions
        result.extend(independent_play_actions(self))
        result.append(EndTurn(player.id))
        return tuple(result)

    def _resolve_action(self, action: Action):
        """Execute one already validated input without cloning or external history."""
        self._require_boundary()
        working = self
        working._resolving = True
        if type(action) is not AdvanceTurnTime:
            working._state.action_number += 1
        if type(action) is AdvanceTurnTime:
            effect = None
        elif isinstance(action, PlayCard):
            effect = PlayFromHand(action)
        elif isinstance(action, Attack):
            effect = BeginAttack(action)
        elif isinstance(action, UseHeroPower):
            effect = ActivateHeroPower(action)
        elif isinstance(action, UseMinionAbility):
            effect = ActivateMinionAbility(action)
        elif isinstance(action, UseLocation):
            effect = ActivateLocation(action)
        elif isinstance(action, LaunchStarship):
            effect = ActivateStarship(action)
        elif isinstance(action, UseHandAction):
            effect = ActivateHandAction(action)
        elif isinstance(action, UseInteractable):
            effect = ActivateInteractable(action)
        else:
            effect = EndTurnPhase(action.player_id)
        try:
            resolution = Resolution(working)
            if type(action) is AdvanceTurnTime:
                from .turn_clocks import advance
                advance(resolution, action)
            elif type(action) is Concede:
                from .concession import concede
                concede(resolution, action.player_id)
            elif isinstance(action, SelectChoice):
                resume_choice(resolution, action)
            elif isinstance(action, (PlayCard, UseHeroPower)):
                from .rewind import start as start_rewind
                resolution.run(start_rewind(working, action))
            else:
                resolution.run([effect])
            from .turn_clocks import settle_expired
            settle_expired(resolution)
            working._information.sync(working)
            working._assert_stable()
            working._resolving = False
        except Exception as exc:
            # The transaction copy is discarded even for a broken trusted plugin.
            if isinstance(exc, ResolutionError):
                raise
            raise ResolutionError(f'Action resolution failed and was rolled back: {exc}') from exc

    def apply(self, action: Action) -> ActionResult:
        self.validate(action)
        from .controlled_turns import validate_external,drive
        validate_external(self,action)
        working=self.clone()
        start=len(working._events)
        working._resolve_action(action)
        try:
            drive(working)
        except Exception as exc:
            if isinstance(exc,ResolutionError):raise
            raise ResolutionError(f'Native turn failed and was rolled back: {exc}') from exc
        events = tuple(working._events[start:])
        digest = working.state_hash()
        working._history.append({'action': history_action_to_dict(action), 'state_hash': digest,
                                 'events_hash': canonical_hash([event_to_dict(e) for e in events])})
        self._state, self._rng = working._state, working._rng
        self._events, self._history = working._events, working._history
        self._frame = working._frame
        self._information = working._information
        self._rewind = working._rewind
        return ActionResult(deepcopy(events), digest)
