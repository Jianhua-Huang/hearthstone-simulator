"""Explicit player predicates and nonrecursive original observation inputs.

The DTO is an accepted input, never a substitute GameState. Live payment
proofs additionally reconstruct its exact public projection from their complete
before state; closed receipts retain immutable inputs and physical facts.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import re
from types import SimpleNamespace

from .effects import _behavior
from .model import CardType, PaidTargetObservation, SpellSchool, Zone


@dataclass(frozen=True)
class PlayerTargetRuleSpec:
    id: str
    version: str

    def __post_init__(self):
        _behavior(self.id)
        _behavior(self.version)


HEADER = frozenset('version viewer turn board_id limits active_player status winner opening_stage players pending_choice event_cursor'.split())
PLAYER = frozenset('id hero hero_power weapon additional_hero_powers board pending_plays quests secrets player_effects battlecry_modifiers combo_modifiers spell_modifiers choose_both_modifiers hand hand_cap deck_count known_graveyard mana max_mana mana_cap temporary_mana overload_owed overload_locked hero_power_uses_this_turn hero_class cards_played_this_turn cards_played_total herald_count excavation imbue herald_multiplier starships_launched resources'.split())
ENTITY = frozenset('ref card_id controller zone attack health max_health kind summoned_this_turn armor keywords frozen silenced attacks_this_turn durability uses_this_turn use_limit keyword_durations bodies tribes tribes_excluded passive magnetic_upgrades herald_rank colossal_appendages limited_triggers counter_policies hand_progress card_spell_repeats quest dormancy minion_abilities location starship cost choose_one choose_selection temporary magnetic_tribes play_conditions hand_actions classes'.split())
SLOTS = (('hero', Zone.HERO, False), ('hero_power', Zone.HERO_POWER, False),
         ('weapon', Zone.WEAPON, False), ('additional_hero_powers', Zone.HERO_POWER, True),
         ('board', Zone.BOARD, True), ('pending_plays', Zone.PLAY, True),
         ('quests', Zone.QUEST, True), ('secrets', Zone.SECRET, True), ('hand', Zone.HAND, True))
PRIVATE_KEYS = frozenset('state entities enchantments abilities rng_state information source_json origin_hash original_state_hash registry_fingerprint body_target_profile_id tribe_changes'.split())

ENTITY |= {'invoke_progress', 'preparation', 'disguised', 'play_side', 'interactable'}
ENTITY |= {'base_damage'}


def _interactable_view(row, controller, zone):
    """Validate the existing minimal public carrier, never its hidden stats."""
    use = row.get('interactable')
    if (zone != Zone.BOARD or set(row) != {'ref', 'card_id', 'controller', 'zone', 'kind', 'interactable'}
            or type(row['card_id']) is not str or not row['card_id'].strip()
            or type(row['controller']) is not int or row['controller'] != controller
            or row['zone'] != Zone.BOARD.value or row['kind'] != CardType.MINION.value
            or type(use) is not dict or set(use) != {'used', 'uses_per_turn'}
            or type(use['used']) is not bool
            or type(use['uses_per_turn']) is not int or use['uses_per_turn'] != 1):
        raise ValueError('Original player interactable requires its exact minimal public BOARD view')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _cards(value):
    for player in value['players']:
        for name, zone, many in SLOTS:
            rows = player[name] if many else [player[name]]
            for row in rows:
                if row is not None:
                    yield player['id'], zone, row
        for row in player['known_graveyard']:
            yield player['id'], Zone.GRAVEYARD, row


def decode(proof, *, require_active_player=True):
    if type(proof) is not PaidTargetObservation:
        raise ValueError('Player target inputs require exact immutable observation proof')
    value = json.loads(proof.observation_json)
    if canonical(value) != proof.observation_json or type(value) is not dict or set(value) != HEADER:
        raise ValueError('Player target observation requires exact canonical public fields')
    from .information import VIEW_VERSION
    if value['version'] != VIEW_VERSION or type(value['viewer']) is not int or value['viewer'] not in (1, 2):
        raise ValueError('Player target observation lost its exact view version or seat')
    from .game_boards import validate_board_id
    validate_board_id(value['board_id'])
    if (type(value['turn']) is not int or value['turn'] < 1 or require_active_player and value['active_player'] != value['viewer']
            or type(value['active_player']) is not int or value['active_player'] not in (1,2) or value['status'] != 'playing'
            or value['winner'] is not None or value['pending_choice'] is not None
            or type(value['event_cursor']) is not int or value['event_cursor'] < 0):
        raise ValueError('Player target observation is not its active paid boundary')
    if type(value['players']) is not list or [p.get('id') for p in value['players'] if type(p) is dict] != [1, 2]:
        raise ValueError('Player target observation requires both ordered seats')
    for p in value['players']:
        if set(p) - {'invoke_count', 'jade_count', 'cthun_ritual', 'spell_schools_played_this_turn', 'quests_played_total'} != PLAYER or type(p['id']) is not int:
            raise ValueError('Player target observation lost complete public player fields')
        if p['id'] == value['viewer']:
            schools = p.get('spell_schools_played_this_turn')
            if (type(schools) is not list or
                    any(type(school) is not str or school not in {s.value for s in SpellSchool} for school in schools) or
                    schools != sorted(set(schools))):
                raise ValueError('Own played-school input requires ordered distinct actual spell schools')
        elif 'spell_schools_played_this_turn' in p:
            raise ValueError('Played-school input is private to its own viewer')
        if p['id'] == value['viewer']:
            count = p.get('quests_played_total')
            if (type(count) is not int or count < 0 or type(p['cards_played_total']) is not int or
                    count > p['cards_played_total']):
                raise ValueError('Own played-Quest input requires an exact complete hand-play count')
        elif 'quests_played_total' in p:
            raise ValueError('Played-Quest input is private to its own viewer')
        if 'invoke_count' in p and (p['id'] != value['viewer'] or
                type(p['invoke_count']) is not int or p['invoke_count'] < 0):
            raise ValueError('Private Invoke count requires the viewer and an exact nonnegative integer')
        if 'jade_count' in p and (p['id'] != value['viewer'] or
                type(p['jade_count']) is not int or p['jade_count'] < 0):
            raise ValueError('Private Jade count requires the viewer and an exact nonnegative integer')
        if 'cthun_ritual' in p:
            ritual = p['cthun_ritual']
            if (p['id'] != value['viewer'] or type(ritual) is not dict or
                    set(ritual) != {'attack', 'health'} or
                    any(type(v) is not int or v < 1 for v in ritual.values())):
                raise ValueError('Private Cthun ritual requires only the viewer and exact numeric stats')
        for name in ('additional_hero_powers', 'board', 'pending_plays', 'quests', 'secrets', 'hand', 'known_graveyard',
                     'player_effects', 'battlecry_modifiers', 'combo_modifiers', 'spell_modifiers', 'choose_both_modifiers'):
            if type(p[name]) is not list:
                raise ValueError('Player target public slots require lists')
        if type(p['hand_cap']) is not int or p['hand_cap'] < 1:
            raise ValueError('Player target hand capacity requires a positive integer')
        for name in ('deck_count', 'mana', 'max_mana', 'mana_cap', 'temporary_mana', 'overload_owed',
                     'overload_locked', 'hero_power_uses_this_turn', 'cards_played_this_turn',
                     'cards_played_total', 'herald_count', 'herald_multiplier', 'starships_launched'):
            if type(p[name]) is not int or p[name] < 0:
                raise ValueError('Player target public counters require exact nonnegative integers')
    refs = []
    for controller, zone, row in _cards(value):
        if type(row) is not dict or not {'ref', 'card_id'} <= set(row) or set(row) - ENTITY:
            raise ValueError('Player target entity view contains nonpublic or missing fields')
        if 'interactable' in row:
            _interactable_view(row, controller, zone)
        if 'base_damage' in row and (row.get('kind')!=CardType.SPELL.value or type(row['base_damage'])is not int or row['base_damage']<0):
            raise ValueError('Visible native spell base damage requires its exact nonnegative value')
        if 'invoke_progress' in row and (
                zone != Zone.HERO and not (zone == Zone.HAND and controller == value['viewer']) or
                type(row['invoke_progress']) is not int or not 0 <= row['invoke_progress'] <= 4):
            raise ValueError('Invoke progress requires a visible physical hero card and exact bounded integer')
        if 'play_conditions' in row:
            conditions = row['play_conditions']
            if type(conditions) is not dict:
                raise ValueError('Public play conditions require an explicit object')
            if 'kindred' in conditions and (zone != Zone.HAND or controller != value['viewer']
                    or type(conditions['kindred']) is not bool):
                raise ValueError('Native Kindred target fact is a boolean private to its own hand')
        if 'preparation' in row:
            prepared = row['preparation']
            if zone != Zone.HAND or controller != value['viewer']:
                raise ValueError('Preparation is private to the visible hand')
            if prepared is not None and (type(prepared) is not dict or
                    set(prepared) != {'turn', 'mana_spent', 'playable'} or
                    type(prepared['turn']) is not int or not 1 <= prepared['turn'] <= value['turn'] or
                    type(prepared['mana_spent']) is not int or prepared['mana_spent'] < 1 or
                    type(prepared['playable']) is not bool or
                    prepared['playable'] != (prepared['turn'] != value['turn'])):
                raise ValueError('Invalid public Preparation state')
        if 'disguised' in row and row['disguised'] is not True:
            raise ValueError('Disguised must be the printed public permission')
        if 'play_side' in row and (zone != Zone.PLAY or row.get('disguised') is not True or
                row['play_side'] not in ('friendly', 'enemy')):
            raise ValueError('Disguised play side requires a public pending play')
        if 'choose_selection' in row and row['choose_selection'] is not None:
            from .model import ChooseBranchSelection
            preset = row['choose_selection']
            if type(preset) is not dict or set(preset) != {'branch', 'origins', 'combination'} or type(preset['origins']) is not list:
                raise ValueError('Player preselection requires only its public declaration')
            # Structural DTO validation is independent of host-only registry access.
            ChooseBranchSelection(row['card_id'], preset['branch'], tuple(preset['origins']), preset['combination'])
        ref = row['ref']
        if type(ref) is not str or re.fullmatch(r'e[1-9][0-9]*', ref) is None:
            raise ValueError('Player target entity view requires an opaque public reference')
        refs.append(ref)
        if zone == Zone.HAND and controller != value['viewer'] and set(row) != {'ref', 'card_id'}:
            raise ValueError('Player target inputs cannot expose hidden opposing-hand attributes')
        if zone == Zone.GRAVEYARD and set(row) != {'ref', 'card_id'}:
            raise ValueError('Remembered graveyard identities cannot expose state')
    if len(refs) != len(set(refs)) or set(refs) != {ref for _, ref in proof.references}:
        raise ValueError('Player target observation references differ from complete original slots')
    def visit(item):
        if type(item) is dict:
            if set(item) & PRIVATE_KEYS:
                raise ValueError('Player target observation contains private engine data')
            for child in item.values(): visit(child)
        elif type(item) is list:
            for child in item: visit(child)
    visit(value)
    return value


def capture(game, state, source):
    if game._state is not state:
        raise ValueError('Original player inputs require the actual current game boundary')
    game._information.sync(game)
    value = game._information.observe(game, source.controller)
    refs = {row['ref'] for _, _, row in _cards(value)}
    knowledge = game._information.players[source.controller]
    bindings = tuple(sorted((int(i), ref) for i, ref in knowledge.refs.items() if ref in refs))
    result = PaidTargetObservation(canonical(value), bindings)
    result.__post_init__()
    return result


def validate_origin(registry, origin, source, *, play=None, prior=(), require_active_player=True):
    proof = origin.observation
    if proof is None:
        return
    value = decode(proof,require_active_player=require_active_player)
    if (value['viewer'], value['turn']) != (source.controller, origin.turn):
        raise ValueError('Original player target observation changed its source seat or turn')
    facts = {f.id: f for f in origin.entities}
    reverse = {ref: entity_id for entity_id, ref in proof.references}
    if any(i not in facts for i in reverse.values()):
        raise ValueError('Original player target reference exceeds its physical universe')
    for controller, zone, row in _cards(value):
        fact = facts[reverse[row['ref']]]
        if (fact.controller, fact.zone) != (controller, zone):
            raise ValueError('Original player target view borrowed a different zone or controller')
        if row['card_id'] is not None and row['card_id'] != fact.card_id:
            raise ValueError('Original player target view changed its known card face')
        if zone not in (Zone.GRAVEYARD, Zone.SECRET) and not (zone == Zone.HAND and controller != source.controller):
            expected = {'card_id': fact.card_id, 'controller': controller,
                        'zone': zone.value, 'kind': fact.kind.value}
            inert = registry.card(fact.card_id).interactable is not None
            if inert:
                _interactable_view(row, controller, zone)
                if (fact.kind != CardType.MINION or
                        (fact.active, fact.doomed, fact.attack, fact.health, fact.max_health,
                            fact.damage, fact.durability, fact.keywords, fact.tribe_changes) !=
                        (False, False, 0, 1, 1, 0, 0, (), ())):
                    raise ValueError('Original interactable carrier contains ordinary combat facts')
            else:
                if 'interactable' in row:
                    raise ValueError('Ordinary physical card cannot borrow an interactable view')
                expected.update(attack=fact.attack, health=fact.health, max_health=fact.max_health,
                    durability=fact.durability, keywords=sorted(k.value for k in fact.keywords))
            if any(row.get(k) != v or type(row.get(k)) is not type(v) for k, v in expected.items()):
                raise ValueError('Original player target view differs from its complete physical facts')
            if fact.kind == CardType.MINION and not inert:
                from .tribes import tribe_state_for
                tribes = tribe_state_for(registry, fact.card_id, fact.tribe_changes)
                if (row.get('tribes'), row.get('tribes_excluded')) != (
                        None if tribes is None else list(tribes.members), [] if tribes is None else list(tribes.excluded)):
                    raise ValueError('Original player target view changed its effective tribes')
    own = value['players'][source.controller - 1]
    if tuple(reverse[row['ref']] for row in own['hand']) != origin.hand or tuple(reverse[row['ref']] for row in own['board']) != origin.board:
        raise ValueError('Original player target view lost its complete own hand or board order')
    expected_ids = {f.id for f in origin.entities if f.zone in {s[1] for s in SLOTS}}
    actual_ids = {reverse[row['ref']] for _, z, row in _cards(value) if z != Zone.GRAVEYARD}
    if actual_ids != expected_ids:
        raise ValueError('Original player target view omitted or added a physical current slot')
    if play is not None:
        if own['max_mana'] != play.mana_crystals:
            raise ValueError('Original player target view changed its accepted mana crystals')
        for p in value['players']:
            owned = [r for r in prior if r.player_id == p['id']]
            if (p['cards_played_total'], p['cards_played_this_turn']) != (len(owned), sum(r.turn == origin.turn for r in owned)):
                raise ValueError('Original player target view changed its actual preceding plays')
        from .play_history import spell_schools_from_plays
        expected = [school.value for school in spell_schools_from_plays(
            r for r in prior if r.player_id == source.controller and r.turn == origin.turn)]
        if own['spell_schools_played_this_turn'] != expected:
            raise ValueError('Original player target view changed its actual preceding spell schools')
        from .play_history import quests_from_plays
        expected_quests = len(quests_from_plays((r for r in prior if r.player_id == source.controller), registry))
        if own['quests_played_total'] != expected_quests:
            raise ValueError('Original player target view changed its actual preceding Quest plays')


def factory(proof, *, require_active_player=True):
    """Rebuild every callback input from one accepted DTO; copy per call."""
    value = decode(proof,require_active_player=require_active_player)
    from .player_api import visible_entities
    from .registry import PlayerRuleContext
    visible = visible_entities(value)
    refs = dict(proof.references)
    def context(source_id, target_id):
        source = visible.get(refs.get(source_id))
        if source is None:
            raise ValueError('Original player target source must have its own visible hand view')
        target = visible.get(refs.get(target_id))
        return PlayerRuleContext(value['viewer'], deepcopy(value), deepcopy(source), deepcopy(target))
    return context


def validate_full_state(state, registry, source, proof, *, require_active_player=True):
    """Reproject complete original payment inputs without storing GameState."""
    value = decode(proof,require_active_player=require_active_player)
    from .information import Information
    from .rules import Ruleset
    limits = value['limits']
    allowed = {'max_board', 'max_hand', 'max_quests', 'max_ongoing_effects', 'max_secret_zone'}
    if type(limits) is not dict or set(limits) != allowed:
        raise ValueError('Original player target limits lost their public schema')
    rules = Ruleset(**limits)
    information = Information()
    knowledge = information.players[source.controller]
    knowledge.refs = {str(i): ref for i, ref in proof.references}
    reverse = {ref: str(i) for i, ref in proof.references}
    knowledge.known = {reverse[row['ref']]: row['card_id'] for _, _, row in _cards(value) if row['card_id'] is not None}
    # Projection reads only the event count; no synthetic events are published.
    class EventCount:
        def __len__(self): return value['event_cursor']
    knowledge.events = EventCount()
    host = SimpleNamespace(_state=state, registry=registry, ruleset=rules)
    if canonical(information.observe(host, source.controller)) != proof.observation_json:
        raise ValueError('Original player target observation differs from its complete payment state projection')


def live_factory(r, source):
    from .player_api import visible_entities
    from .registry import PlayerRuleContext
    r.game._information.sync(r.game)
    value = r.game._information.observe(r.game, source.controller)
    visible = visible_entities(value)
    ref = r.game._information.players[source.controller].refs.get(str(source.id))
    if ref in visible:
        source_view = visible[ref]
        refs = r.game._information.players[source.controller].refs
        def context(source_id, target_id):
            return PlayerRuleContext(source.controller, deepcopy(value), deepcopy(source_view),
                                     deepcopy(visible.get(refs.get(str(target_id)))))
        return context
    from .targeting import effect_target_context
    return effect_target_context(r, source)


def rewind_root_observation(game, anchor):
    """Use the actual saved knowledge of this retry's initial paid window."""
    if game is None or game._rewind is None:
        raise ValueError('Player target retry requires its genuine original information session')
    session = game._rewind
    if session.action != anchor.action or session.before != anchor.before:
        raise ValueError('Player target retry borrowed another original observation window')
    information = deepcopy(session.information)
    host = SimpleNamespace(_state=anchor.before, registry=game.registry, ruleset=game.ruleset,
                           _information=information)
    host.observe = lambda viewer: information.observe(host, viewer)
    return capture(host, anchor.before, anchor.before.entities[anchor.action.entity_id])
