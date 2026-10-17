"""Versioned, event-time player knowledge; never serialize engine objects to a player.

Game snapshots and replays remain trusted, omniscient artifacts. This projection
is a transport DTO, not a Python security sandbox or an action capability.
"""
from .hand_capacity import hand_capacity
from copy import deepcopy
from dataclasses import dataclass, field
import re

from .costs import quote_cost
from .model import CardType, Keyword, Zone


VIEW_VERSION = 'player-view-v93'
PUBLIC_ZONES = frozenset((Zone.HERO, Zone.BOARD, Zone.WEAPON, Zone.HERO_POWER, Zone.QUEST, Zone.PLAY))

# Deliberate allowlist: diagnostics, plugin events and arbitrary Event.data never
# pass through. Adding an engine event does not automatically publish its data.
PUBLIC_EVENTS = frozenset('''counter_policy_used limited_trigger_used game_created game_started game_ended turn_started turn_ended hand_capacity_changed
    turns_scheduled skip_turns_scheduled turn_skipped
    joust_resolved galakrond_invoked cards_removed_from_game
    interactable_installed interactable_install_skipped interactable_use_started interactable_used
    spell_cast_started spell_cast_finished spell_cast_failed
    timeline_rewound rewind_kept rewind_face_changed
    rewind_outcome_started rewind_outcome_finished card_dredged excavated imbued imbue_no_effect
    opening_hand_dealt mulligan_submitted mulligan_replaced mulligan_completed
    card_committed card_played card_drawn card_added_to_hand card_burned card_returned card_shuffled
    card_added_to_deck card_moved_to_deck card_moved_to_hand card_discarded card_destroyed_in_deck card_destroyed_in_hand deck_shuffled deck_reordered hand_reordered
    trade_started card_traded card_forged card_prepared starship_started starship_piece_added starship_launched starship_relaunched
    location_placed location_activated location_used location_destroyed location_opened location_face_changed
    location_cooldown_changed location_durability_changed
    quest_started quest_progressed quest_progress_reset quest_stage_completed quest_stage_started quest_completed quest_removed hero_attack_gained
    player_effect_added player_effect_ticked player_effect_expired player_effect_removed
    battlecry_modifier_added battlecry_modifier_used battlecry_modifier_removed battlecry_modifier_expired
    combo_modifier_added combo_modifier_used combo_modifier_removed combo_modifier_expired
    spell_modifier_added spell_modifier_used spell_modifier_removed spell_modifier_expired
    choose_both_modifier_added choose_both_modifier_used choose_both_modifier_removed choose_both_modifier_expired
    secret_set secret_revealed secret_removed spell_countered minion_countered attack_redirected spell_redirected
    minion_ability_started minion_ability_used
    minion_dormant minion_awakened dormancy_progressed
    minion_summoned minion_died minion_reborn minion_resurrected weapon_equipped weapon_destroyed weapon_changed weapon_transferred
    weapon_durability_spent hero_power_started hero_power_used hero_power_replaced hero_power_added hero_power_removed
    hero_power_trigger_started hero_power_triggered hero_power_trigger_failed
    hero_power_refreshed hero_power_limit_changed hero_replaced hero_died hero_recovered hero_health_set
    attack_declared attack_finished attack_cancelled damage_dealt damage_prevented healed
    shield_lost armor_gained armor_lost health_lost health_loss_replaced max_health_gained max_health_lost hero_health_stolen fatigue mana_spent health_spent armor_spent corpses_spent
    mana_changed mana_consumed overload_added resource_gained resource_spent stats_changed destroyed silenced
    transformed control_changed frozen unfrozen stealth_lost magnetized heralded'''.split())
CHOICE_EVENTS = frozenset(('choice_requested', 'choice_selected'))
PRIVATE_CARD_EVENTS = frozenset(('choose_branch_changed', 'stored_card_buffed', 'hand_card_upgraded', 'hand_progressed',
                               'card_shattered', 'cards_recombined', 'card_expired', 'hand_card_made_temporary', 'stored_keyword_granted',
                               'stored_card_transformed', 'counter_policy_added', 'card_spell_repeat_added', 'card_spell_repeat_removed',
                               'stored_spell_damage_granted'))
EVENT_KINDS = PUBLIC_EVENTS | CHOICE_EVENTS | PRIVATE_CARD_EVENTS | {'card_revealed', 'deck_card_revealed'}
_REF = re.compile(r'e([1-9][0-9]*)\Z')
_CHOICE = re.compile(r'c([1-9][0-9]*)\Z')


def player_id(value):
    if type(value) is not int or value not in (1, 2):
        raise ValueError('Viewer must be player 1 or 2')
    return value


def _fields(value, names, label):
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError(f'Invalid {label} fields')


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('Invalid information counter')


@dataclass
class Knowledge:
    next_ref: int = 1
    refs: dict[str, str] = field(default_factory=dict)
    known: dict[str, str] = field(default_factory=dict)
    next_choice: int = 1
    next_body_ref: int = 1
    body_refs: dict[str, str] = field(default_factory=dict)
    # Internal choice identifiers are kept only in this trusted ledger.
    pending: dict | None = None
    events: list[dict] = field(default_factory=list)

    def ref(self, entity_id):
        key = str(entity_id)
        if key not in self.refs:
            self.refs[key] = f'e{self.next_ref}'
            self.next_ref += 1
        return self.refs[key]

    def remember(self, entity):
        self.ref(entity.id)
        self.known[str(entity.id)] = entity.card_id

    def identity(self, entity_id):
        key = str(entity_id)
        if key not in self.refs:
            return None
        return {'ref': self.refs[key], 'card_id': self.known.get(key)}


class Information:
    def __init__(self):
        self.players = {i: Knowledge() for i in (1, 2)}

    def conceal(self, entity_id):
        """Entering a hidden deck or setaside retires live tracking handles."""
        for knowledge in self.players.values():
            knowledge.refs.pop(str(entity_id), None)
            knowledge.known.pop(str(entity_id), None)

    def hide_hand_identity(self, entity_id):
        """Keep the visible hand slot but forget identities invalidated by a hidden upgrade."""
        for knowledge in self.players.values():
            knowledge.known.pop(str(entity_id), None)

    def sync(self, game):
        state = game._state
        for entity in state.entities.values():
            if entity.zone in (Zone.DECK, Zone.SETASIDE):
                self.conceal(entity.id)
        for viewer, knowledge in self.players.items():
            # Allocate by visible slot order, never by global entity creation ID.
            for player in state.players.values():
                for entity_id in (player.hero_id, *player.hero_power_ids, player.weapon_id, *player.board, *player.quests):
                    if entity_id is not None:
                        knowledge.remember(state.entities[entity_id])
                for entity_id in player.hand:
                    knowledge.ref(entity_id)
                    if player.id == viewer:
                        knowledge.remember(state.entities[entity_id])
                for entity_id in player.secrets:
                    knowledge.ref(entity_id)
                    if player.id == viewer:
                        knowledge.remember(state.entities[entity_id])
            choice = state.pending_choice
            if choice is not None and choice.player_id == viewer:
                if knowledge.pending is None or knowledge.pending['internal_id'] != choice.id:
                    knowledge.pending = {
                        'internal_id': choice.id,
                        'option_ids': [o.id for o in choice.options],
                        'ref': f'c{knowledge.next_choice}',
                    }
                    knowledge.next_choice += 1
            else:
                knowledge.pending = None
            from .body_player_commands import sync_body_handles
            sync_body_handles(game,viewer,knowledge)

    def choice_view(self, game, viewer):
        from .serialization import preview_to_dict
        choice = game._state.pending_choice
        if choice is None:
            return None
        if choice.player_id != viewer:
            return {'player_id': choice.player_id}
        knowledge = self.players[viewer]
        return {
            'player_id': viewer, 'ref': knowledge.pending['ref'],
            'source': knowledge.identity(choice.source_id) if str(choice.source_id) in knowledge.known else None,
            'prompt': choice.prompt,
            'purpose': choice.purpose.value, 'min_count': choice.min_count, 'max_count': choice.max_count,
            'options': [
                {'ref': f'o{n}', 'label': option.label, 'card_id': option.card_id,
                 'entity': knowledge.identity(option.entity_id),
                 **({'preview': preview_to_dict(option.preview)} if option.preview is not None else {})}
                for n, option in enumerate(choice.options, 1)
            ],
        }

    def record(self, game, event):
        # Selection clears the engine's pending choice before emitting. Retain
        # its old mapping just long enough to translate this event, then sync.
        data = dict(event.data)
        from .nondeath_removal import removal_result
        removal = removal_result(event)
        remembered = ({viewer: {row[0]: k.known.get(str(row[0])) for row in removal[0]}
                       for viewer, k in self.players.items()} if removal is not None else None)
        pending = {i: k.pending for i, k in self.players.items()}
        self.sync(game)
        if event.kind == 'card_drawn' and data.get('casts_when_drawn'):
            entity = game._state.entities[event.target_id]
            for viewer, knowledge in self.players.items():
                if viewer == event.player_id or game.registry.card(entity.card_id).secret is None:
                    knowledge.remember(entity)
        if event.kind in ('card_committed', 'card_burned', 'secret_revealed', 'secret_removed', 'spell_countered', 'spell_cast_started'):
            entity_id = event.target_id if event.kind == 'card_burned' else event.source_id
            for knowledge in self.players.values():
                if event.kind not in ('card_committed', 'spell_cast_started') or game.registry.card(game._state.entities[entity_id].card_id).secret is None:
                    knowledge.remember(game._state.entities[entity_id])
        if event.kind not in EVENT_KINDS:
            return
        for viewer, knowledge in self.players.items():
            if event.kind == 'card_revealed' and viewer not in data['viewers']:
                continue
            if event.kind in PRIVATE_CARD_EVENTS and viewer != event.player_id:
                continue
            # Events concerning a hidden target's attributes are private. Draw,
            # generation and return expose a card back but no hidden attributes.
            if event.target_id is not None and event.kind not in (
                    'card_drawn', 'card_added_to_hand', 'card_returned', 'card_shuffled',
                    'card_added_to_deck', 'card_moved_to_deck', 'card_moved_to_hand', 'card_discarded', 'card_destroyed_in_deck', 'card_destroyed_in_hand',
                    'card_committed', 'card_played', 'hero_power_started', 'hero_power_used', 'hero_power_trigger_started', 'hero_power_triggered', 'card_forged',
                    'minion_ability_started', 'minion_ability_used', 'card_dredged', 'card_prepared'):
                if str(event.target_id) not in knowledge.known:
                    continue
            record = {
                'sequence': len(knowledge.events) + 1, 'kind': event.kind,
                'player_id': event.player_id, 'amount': event.amount,
                'source': knowledge.identity(event.source_id) if str(event.source_id) in knowledge.known or
                    event.kind in ('secret_set', 'card_committed', 'card_played') else None,
                'target': None if event.kind in ('card_shuffled', 'card_added_to_deck', 'card_moved_to_deck', 'card_dredged') else knowledge.identity(event.target_id),
                'choice': None, 'selected': None,
            }
            if event.kind == 'card_prepared' and viewer != event.player_id:
                record['source'] = record['target'] = None
            if event.kind == 'turns_scheduled':
                record['turns'] = list(data['players'])
            if event.kind == 'deck_card_revealed':
                from .deck_reveals import deck_reveal_result
                result = deck_reveal_result(event)
                chosen = result.card
                record['deck_reveal'] = dict(kind=result.kind.value, card=None if chosen is None else
                    dict(player_id=result.player_id, card_id=chosen.card.card_id, cost=chosen.cost))
            if event.kind == 'joust_resolved':
                from .joust import joust_result
                result = joust_result(event)
                face = lambda value: None if value is None else dict(player_id=value.card.player_id,
                    card_id=value.card.card_id, cost=value.cost)
                record['joust'] = dict(kind=result.kind.value, own=face(result.own),
                    opponent=face(result.opponent), won=result.won)
            if removal is not None:
                rows, reveal = removal
                record['removed_cards'] = [dict(player_id=owner, from_zone=zone,
                    card_id=card_id if (zone == Zone.BOARD.value or reveal or
                        zone == Zone.HAND.value and (owner == viewer or
                            remembered[viewer][entity_id] == card_id)) else None)
                    for entity_id, owner, zone, card_id in rows]
            if event.kind == 'location_face_changed':
                record['location_face'] = {key: data[key] for key in ('old_card_id', 'new_card_id')}
            if event.kind == 'timeline_rewound':
                record['rewind'] = {'after': data['player_cursors'][viewer - 1], 'attempt': event.amount}
            if event.kind == 'card_dredged':
                record['dredge'] = {'owner_id': data['owner_id'], 'revealed': data['reveal'],
                    'selected': {'card_id': data['card_id'], 'preview': deepcopy(data['preview'])}
                    if viewer == event.player_id or data['reveal'] else None}
            if event.kind == 'excavated':
                record['excavation'] = {key:data[key] for key in ('cycle','tier','maximum')}
            if event.kind in ('imbued', 'imbue_no_effect'):
                record['imbue'] = {'level':data['level']}
            if event.kind.startswith('quest_'):
                record['quest'] = {key: data[key] for key in ('quest_kind', 'stage', 'stages', 'stage_card_id', 'progress', 'goal', 'completing')}
            if event.kind.startswith('choose_both_modifier_'):
                record['choose_both_modifier'] = {key: deepcopy(data[key]) for key in ('kinds', 'origins', 'uses_remaining', 'expires_turn')}
            if event.kind.startswith('spell_modifier_'):
                record['spell_modifier'] = {key: data[key] for key in ('casts','class_mode','match','uses_remaining','expires_turn')}
            if event.kind.startswith('combo_modifier_'):
                record['combo_modifier'] = {key: deepcopy(data[key]) for key in ('repetitions','kinds','scope','match','uses_remaining','expires_turn','trigger')}
            if event.kind.startswith('battlecry_modifier_'):
                record['battlecry_modifier'] = {key: data[key] for key in ('repetitions','kinds','scope','match','uses_remaining','expires_turn')}
            if event.kind.startswith('player_effect_'):
                record['player_effect'] = {key: data[key] for key in (
                    'effect_key', 'card_id', 'effect_kind', 'remaining_turns')}
                if 'adaptations' in data:
                    record['player_effect']['adaptations'] = list(data['adaptations'])
            if event.kind == 'limited_trigger_used':
                record['trigger_keyword'] = data['trigger_keyword']
            if event.kind in ('counter_policy_added', 'counter_policy_used'):
                record['counter_policy'] = dict(kind=data['counter_kind'],
                    uses_remaining=data['uses_remaining'], expires_turn=data['expires_turn'])
            if event.kind in ('control_changed', 'minion_summoned') and viewer == event.player_id:
                from .counter_policies import private_policies
                record['counter_policies'] = private_policies(game._state.entities[event.target_id])
            if event.kind in ('minion_ability_started', 'minion_ability_used'):
                record['minion_ability'] = {'ability_id': data['ability_id'], 'card_id': data['ability_card_id']}
            if event.kind == 'choice_requested' and viewer == event.player_id:
                record['choice'] = self.choice_view(game, viewer)
            elif event.kind == 'choice_selected' and viewer == event.player_id:
                previous = pending[viewer]
                if previous is None or previous['internal_id'] != data['choice_id']:
                    raise ValueError('Missing event-time choice knowledge')
                record['selected'] = {
                    'ref': previous['ref'],
                    'options': [f'o{previous["option_ids"].index(i) + 1}' for i in data['option_ids']],
                }
            knowledge.events.append(record)

    def observe(self, game, viewer):
        viewer = player_id(viewer)
        state, knowledge = game._state, self.players[viewer]

        def entity_view(entity_id):
            if entity_id is None:
                return None
            entity = state.entities[entity_id]
            result = knowledge.identity(entity_id)
            if result is None:
                raise ValueError('Visible entity has no observation handle')
            if entity.zone == Zone.HAND:
                from .hand_deadlines import public_countdowns
                countdowns = public_countdowns(state, entity)
                if countdowns:
                    result['hand_deadlines'] = countdowns
            # A remembered enemy hand identity is not permission to inspect
            # later hidden modifications to its cost, health or attachments.
            if entity.zone == Zone.HAND and entity.controller != viewer:
                return result
            result.update(controller=entity.controller, zone=entity.zone.value)
            if entity.zone == Zone.SECRET:
                metadata = game.registry.card(entity.card_id).metadata
                result['classes'] = [c.value for c in metadata.classes] if metadata else []
                return result
            if entity.zone in PUBLIC_ZONES or (entity.zone == Zone.HAND and entity.controller == viewer):
                if entity.interactable_object:
                    from .interactables import used_in_latest_owner_turn
                    result.update(kind=CardType.MINION.value,
                        interactable={'used': used_in_latest_owner_turn(state, entity), 'uses_per_turn': 1})
                    return result
                result.update(attack=entity.attack, health=entity.health, max_health=entity.max_health,
                              kind=game.registry.card(entity.card_id).kind.value,
                              summoned_this_turn=entity.zone == Zone.BOARD and entity.summoned_turn == state.turn,
                              armor=entity.armor, keywords=sorted(k.value for k in entity.keywords),
                              frozen=entity.frozen, silenced=entity.silenced,
                              attacks_this_turn=entity.attacks_this_turn,
                              durability=entity.durability, uses_this_turn=entity.uses_this_turn,
                              use_limit=entity.use_limit)
                from .timed_keywords import public_durations
                result['keyword_durations'] = public_durations(entity)
                from .body_views import public_bodies
                result['bodies'] = public_bodies(entity, game.registry)
                if entity.kind == CardType.MINION:
                    from .dark_gifts import public_gifts
                    gifts = public_gifts(entity)
                    if gifts:
                        result['dark_gifts'] = gifts
                    from .tribes import tribe_state
                    current_tribes = tribe_state(game.registry, entity)
                    result['tribes'] = None if current_tribes is None else list(current_tribes.members)
                    result['tribes_excluded'] = [] if current_tribes is None else list(current_tribes.excluded)
                if entity.kind == CardType.HERO_POWER:
                    result['passive']=game.registry.card(entity.card_id).passive_hero_power
                    if entity.zone == Zone.HERO_POWER:
                        from .hero_powers import effective_use_limit
                        result['use_limit'] = effective_use_limit(state,entity)
                from .limited_triggers import public_triggers
                from .magnetic import public_magnetic
                result['magnetic_upgrades']=public_magnetic(entity,state)
                if game.registry.card(entity.card_id).herald_scaling:
                    result['herald_rank'] = entity.herald_rank
                if entity.galakrond_invocations is not None and (
                        entity.zone == Zone.HERO or entity.zone == Zone.HAND and entity.controller == viewer):
                    result['invoke_progress'] = entity.galakrond_invocations
                result['colossal_appendages']=[{'card_id':s.card_id,'side':s.side} for s in game.registry.card(entity.card_id).colossal] if Keyword.COLOSSAL in entity.keywords else []
                result['limited_triggers'] = public_triggers(entity)
                from .counter_policies import private_policies
                result['counter_policies'] = private_policies(entity) if entity.controller == viewer else None
                from .hand_progress import public_progress
                result['hand_progress'] = public_progress(entity)
                from .deathrattle_memory import public_summons
                summon_memory=public_summons(entity)
                if summon_memory:result['deathrattle_summons']=summon_memory
                if entity.kind==CardType.SPELL:
                    from .card_spell_repeats import public_repeats
                    result['card_spell_repeats']=public_repeats(entity)
                    from .native_spell_values import public_value
                    value=public_value(entity)
                    if value is not None:result['base_damage']=value
                if entity.zone == Zone.QUEST:
                    from .quests import public_progress
                    result['quest'] = public_progress(game.registry, entity)
                if entity.zone == Zone.BOARD and entity.kind == CardType.MINION:
                    result['dormancy'] = ({'remaining_turns': entity.dormancy.remaining_turns}
                                           if entity.dormancy is not None else None)
                if entity.kind == CardType.MINION and entity.zone == Zone.BOARD:
                    result['minion_abilities'] = [{'ability_id': a.activation.id, 'card_id': a.activation.card_id,
                        'used': a.consumed} for a in entity.abilities if a.kind == 'activated']
                if entity.kind == CardType.LOCATION:
                    result['location'] = {'cooldown_remaining': entity.location_cooldown,
                        'open': entity.zone == Zone.BOARD and entity.location_cooldown == 0 and entity.durability > 0 and not entity.doomed}
                if entity.components:
                    from .starships import launch_quote
                    result['starship'] = {'building': entity.starship_building,
                                          'components': list(entity.components),
                                          'launch_cost': launch_quote(state, entity).amount if entity.starship_building else None}
                if entity.zone in (Zone.HAND, Zone.HERO_POWER):
                    quote = quote_cost(state, game.registry, entity)
                    result['cost'] = {'amount': quote.amount, 'payment': quote.payment.value}
                choose = game.registry.card(entity.card_id).choose_one
                if choose is not None:
                    result['choose_one'] = [{'id':b.id,'label':b.label} for b in (*choose.branches,choose.combined)]
                    preset = entity.choose_branch
                    result['choose_selection'] = None if preset is None else {
                        'branch': preset.branch_id, 'origins': list(preset.origins), 'combination': preset.combination}
                if entity.zone == Zone.HAND:
                    if entity.controller == viewer:
                        from .hand_choice_followups import public_followups
                        followups = public_followups(state, game.registry, entity)
                        if followups:
                            result['play_followups'] = followups
                    lifetime = entity.hand_lifetime
                    result['temporary'] = ({'expires_turn': lifetime.expires_turn,
                                            'minimum_cost': lifetime.minimum_cost} if lifetime is not None else None)
                    result['magnetic_tribes']=list(game.registry.card(entity.card_id).magnetic_tribes)
                    from .play_history import preplay_conditions
                    result['play_conditions'] = preplay_conditions(state, entity, game.registry)
                    if entity.controller == viewer and entity.card_id in game.registry.kindred_target_profiles:
                        from .kindred_targets import matched
                        result['play_conditions']['kindred'] = matched(state, game.registry, entity,
                            game.registry.card(entity.card_id))
                    from .hand_actions import quote_hand_action
                    result['hand_actions'] = [
                        {'id': spec.id, 'kind': spec.kind, 'cost': {
                            'amount': quote_hand_action(state, game.registry, entity, spec).amount, 'payment': 'mana'}}
                        for spec in game.registry.card(entity.card_id).hand_actions]
                    from .prepare import public_state
                    result['preparation'] = public_state(state, entity)
                if game.registry.card(entity.card_id).disguised:
                    result['disguised'] = True
                    if entity.zone == Zone.PLAY:
                        from .play_history import play_record
                        from .disguised import play_destination
                        window = next(w for w in state.action_windows
                            if w.kind == 'minion' and w.source_id == entity.id)
                        destination = play_destination(game.registry, play_record(state, window.play_id))
                        result['play_side'] = 'friendly' if destination == viewer else 'enemy'

            return result

        players = []
        from .play_history import played_cards, spell_schools_from_plays, quests_from_plays
        from .herald import herald_count, herald_multiplier
        from .excavate import progress as excavation_progress
        from .imbue import progress as imbue_progress
        from .player_effects import public_effect
        from .battlecry_modifiers import public_modifier
        from .combo_modifiers import public_modifier as public_combo_modifier
        from .spell_modifiers import public_modifier as public_spell_modifier
        from .choose_policies import public_modifier as public_choose_modifier
        for player in state.players.values():
            item = {
                'id': player.id, 'hero': entity_view(player.hero_id),
                'hero_power': entity_view(player.hero_power_id), 'weapon': entity_view(player.weapon_id),
                'additional_hero_powers': [entity_view(i) for i in player.additional_hero_power_ids],
                'board': [entity_view(i) for i in player.board],
                'pending_plays': [entity_view(i) for i in player.pending_plays],
                'quests': [entity_view(i) for i in player.quests],
                'secrets': [entity_view(i) for i in player.secrets],
                'player_effects': [public_effect(game.registry, e) for e in player.player_effects],
                'battlecry_modifiers': [public_modifier(m) for m in player.battlecry_modifiers],
                'combo_modifiers': [public_combo_modifier(m) for m in player.combo_modifiers],
                'spell_modifiers': [public_spell_modifier(m) for m in player.spell_modifiers],
                'choose_both_modifiers': [public_choose_modifier(m) for m in player.choose_both_modifiers],
                'hand': [entity_view(i) for i in player.hand], 'hand_cap': hand_capacity(player, game.ruleset), 'deck_count': len(player.deck),
                # Hidden discards/removed entities must not leak through a full
                # graveyard count or through global death/attachment records.
                'known_graveyard': [knowledge.identity(i) for i in player.graveyard if str(i) in knowledge.known],
                'mana': player.mana, 'max_mana': player.max_mana, 'mana_cap': player.mana_cap,
                'temporary_mana': player.temporary_mana, 'overload_owed': player.overload_owed,
                'overload_locked': player.overload_locked,
                'hero_power_uses_this_turn': player.hero_power_uses_this_turn,
                'hero_class': player.hero_class.value if player.hero_class is not None else None,
                'cards_played_this_turn': len(played_cards(state,player.id,turn=state.turn)),
                'cards_played_total': len(played_cards(state,player.id)),
                'herald_count': herald_count(state, player.id),
                'excavation': excavation_progress(state, player.id),
                'imbue': imbue_progress(state, player.id),
                'herald_multiplier': herald_multiplier(state, player.id),
                'starships_launched': sum(record.player_id == player.id for record in state.starship_history),
                'resources': {r.value: count for r, count in player.resources.items()},
            }
            if player.id == viewer:
                item['spell_schools_played_this_turn'] = [school.value for school in
                    spell_schools_from_plays(played_cards(state, player.id, turn=state.turn))]
                item['quests_played_total'] = len(quests_from_plays(played_cards(state, player.id), game.registry))
            if game.registry.invoke_profile is not None and player.id == viewer:
                from .invoke import invoke_count
                item['invoke_count'] = invoke_count(state, player.id)
            if game.registry.jade_families and player.id == viewer:
                from .jade import jade_count
                item['jade_count'] = jade_count(state, player.id)
            if game.registry.cthun_profile is not None and player.id == viewer:
                from .cthun import cthun_ritual_stats
                attack, health = cthun_ritual_stats(state, game.registry, player.id)
                item['cthun_ritual'] = {'attack': attack, 'health': health}
            players.append(item)
        return {'version': VIEW_VERSION, 'viewer': viewer, 'turn': state.turn,
                'board_id': state.board_id,
                'limits': {'max_board': game.ruleset.max_board, 'max_hand': game.ruleset.max_hand,
                           'max_quests': game.ruleset.max_quests, 'max_ongoing_effects': game.ruleset.max_ongoing_effects,
                           'max_secret_zone': game.ruleset.max_secret_zone},
                'active_player': state.active_player, 'status': state.status, 'winner': state.winner,
                'opening_stage': state.opening.stage if state.opening is not None else None,
                'players': players, 'pending_choice': self.choice_view(game, viewer),
                'event_cursor': len(knowledge.events)}

    def to_dict(self):
        return deepcopy({'version': VIEW_VERSION, 'players': {
            str(i): dict(next_ref=k.next_ref, refs=k.refs, known=k.known,
                         next_choice=k.next_choice, next_body_ref=k.next_body_ref, body_refs=k.body_refs, pending=k.pending, events=k.events)
            for i, k in self.players.items()}})

    @classmethod
    def from_dict(cls, value, game):
        _fields(value, 'version players', 'information ledger')
        if value['version'] != VIEW_VERSION or type(value['players']) is not dict or set(value['players']) != {'1', '2'}:
            raise ValueError('Unsupported information ledger')
        result = cls()
        for i in (1, 2):
            row = value['players'][str(i)]
            _fields(row, 'next_ref refs known next_choice next_body_ref body_refs pending events', 'player knowledge')
            result.players[i] = Knowledge(**deepcopy(row))
        result.validate(game)
        return result

    def validate(self, game):
        for viewer, k in self.players.items():
            from .body_player_commands import validate_body_handles
            validate_body_handles(game,viewer,k)
            _integer(k.next_ref, 1)
            _integer(k.next_choice, 1)
            if type(k.refs) is not dict or type(k.known) is not dict or not set(k.known) <= set(k.refs):
                raise ValueError('Invalid knowledge maps')
            if any(type(ref) is not str for ref in k.refs.values()) or len(set(k.refs.values())) != len(k.refs):
                raise ValueError('Observation handles must be distinct strings')
            for key, ref in k.refs.items():
                if type(key) is not str or not key.isascii() or not key.isdigit() or str(int(key)) != key:
                    raise ValueError('Invalid internal knowledge identity')
                entity = game._state.entities.get(int(key))
                match = _REF.fullmatch(ref)
                if entity is None or entity.zone in (Zone.DECK, Zone.SETASIDE) or match is None or int(match[1]) >= k.next_ref:
                    raise ValueError('Invalid or trackable hidden-zone handle')
            for card_id in k.known.values():
                game.registry.card(card_id)
            for entity in game._state.entities.values():
                if entity.zone in PUBLIC_ZONES or (entity.zone in (Zone.HAND, Zone.SECRET) and entity.controller == viewer):
                    if k.known.get(str(entity.id)) != entity.card_id:
                        raise ValueError('Missing visible card knowledge')
                if entity.zone in (Zone.HAND, Zone.SECRET) and str(entity.id) not in k.refs:
                    raise ValueError('Missing visible hand slot')
            choice = game._state.pending_choice
            if choice is not None and choice.player_id == viewer:
                _fields(k.pending, 'internal_id option_ids ref', 'private choice mapping')
                _integer(k.pending['internal_id'], 1)
                ref = k.pending['ref']
                match = _CHOICE.fullmatch(ref) if type(ref) is str else None
                if (k.pending['internal_id'] != choice.id or k.pending['option_ids'] != [o.id for o in choice.options]
                        or match is None or int(match[1]) >= k.next_choice):
                    raise ValueError('Choice knowledge does not match suspended choice')
            elif k.pending is not None:
                raise ValueError('Stale private choice knowledge')
            if type(k.events) is not list:
                raise ValueError('Player events must be an array')
            for sequence, event in enumerate(k.events, 1):
                _validate_event(event, sequence, k, game.registry, viewer)


def _identity(value, knowledge, registry):
    if value is None:
        return
    _fields(value, 'ref card_id', 'observed identity')
    ref = value['ref']
    match = _REF.fullmatch(ref) if type(ref) is str else None
    if match is None or int(match[1]) >= knowledge.next_ref:
        raise ValueError('Invalid historical observation handle')
    if value['card_id'] is not None:
        registry.card(value['card_id'])


def _choice_ref(value, knowledge):
    match = _CHOICE.fullmatch(value) if type(value) is str else None
    if match is None or int(match[1]) >= knowledge.next_choice:
        raise ValueError('Invalid historical choice handle')


def _validate_event(event, sequence, knowledge, registry, viewer):
    fields = 'sequence kind player_id amount source target choice selected'
    if type(event) is dict and event.get('kind') == 'cards_removed_from_game':
        fields += ' removed_cards'
        rows = event.get('removed_cards')
        if (type(rows) is not list or not rows or type(event.get('amount')) is not int or
                event['amount'] != len(rows) or event.get('target') is not None or event.get('player_id') is not None):
            raise ValueError('Invalid public removal batch')
        for row in rows:
            _fields(row, 'player_id from_zone card_id', 'public removed card')
            player_id(row['player_id'])
            if row['from_zone'] not in (Zone.HAND.value, Zone.DECK.value, Zone.BOARD.value):
                raise ValueError('Invalid public removal source zone')
            face = row['card_id']
            if face is not None:
                definition = registry.card(face)
                if row['from_zone'] == Zone.BOARD.value and definition.kind != CardType.MINION:
                    raise ValueError('Public board removal requires a minion')
            if face is None and (row['from_zone'] == Zone.BOARD.value or
                    row['from_zone'] == Zone.HAND.value and row['player_id'] == viewer):
                raise ValueError('Visible removal must preserve its card face')
    if type(event) is dict and event.get('kind') == 'location_face_changed':
        fields += ' location_face'
        face = event.get('location_face')
        _fields(face, 'old_card_id new_card_id', 'public location face change')
        for card_id in face.values():
            if type(card_id) is not str or registry.card(card_id).kind != CardType.LOCATION:
                raise ValueError('Public location face requires location definitions')
        if face['old_card_id'] == face['new_card_id'] or event.get('target') is None:
            raise ValueError('Public location face change requires two different faces and a target')
        if type(event['target']) is not dict or event['target'].get('card_id') != face['new_card_id']:
            raise ValueError('Public location face event target differs from its new face identity')
    if type(event) is dict and event.get('kind') in ('counter_policy_added', 'counter_policy_used'):
        fields += ' counter_policy'
        validate_counter_policy_view(event.get('counter_policy'))
        if event.get('amount') != event['counter_policy']['uses_remaining']:
            raise ValueError('Counter event amount disagrees with remaining uses')
        if event['kind'] == 'counter_policy_added' and (event.get('player_id') != viewer or event['amount'] < 1):
            raise ValueError('Private counter grant leaked to another player')
    if type(event) is dict and event.get('kind') in ('control_changed', 'minion_summoned') and viewer == event.get('player_id'):
        fields += ' counter_policies'
        if type(event.get('counter_policies')) is not list:
            raise ValueError('Private carrier receipt requires a policy list')
        for policy in event['counter_policies']: validate_counter_policy_view(policy)
    if type(event) is dict and event.get('kind') == 'excavated':
        fields += ' excavation'
        detail = event.get('excavation')
        _fields(detail, 'cycle tier maximum', 'Excavation event')
        for field in detail: _integer(detail[field], 1)
        if detail['maximum'] not in (3,4) or detail['tier'] > detail['maximum'] or event.get('target') is not None or event.get('amount',0) < 1:
            raise ValueError('Invalid public Excavation progress')
    if type(event) is dict and event.get('kind') == 'card_dredged':
        from .serialization import preview_from_dict
        fields += ' dredge'
        detail = event.get('dredge')
        _fields(detail, 'owner_id revealed selected', 'Dredge event')
        player_id(detail['owner_id'])
        if type(detail['revealed']) is not bool or event.get('target') is not None:
            raise ValueError('Invalid Dredge visibility')
        selected_card = detail['selected']
        if (selected_card is not None) != (detail['revealed'] or viewer == event.get('player_id')):
            raise ValueError('Dredge selection disclosure disagrees with viewer')
        if selected_card is not None:
            _fields(selected_card, 'card_id preview', 'Dredge selected card')
            registry.card(selected_card['card_id']); preview_from_dict(selected_card['preview'])
    if type(event) is dict and event.get('kind') in ('imbued', 'imbue_no_effect'):
        fields += ' imbue'
        growth = event.get('imbue')
        _fields(growth, 'level', 'Imbue progress')
        _integer(growth['level'], 1 if event['kind'] == 'imbued' else 0)
        _integer(event.get('amount'), 1)
        if growth['level'] > event['amount'] - int(event['kind'] == 'imbue_no_effect'):
            raise ValueError('Invalid public Imbue growth')
    if type(event) is dict and event.get('kind') == 'timeline_rewound':
        fields += ' rewind'
        marker = event.get('rewind')
        _fields(marker, 'after attempt', 'Rewind marker')
        _integer(marker['after'])
        _integer(marker['attempt'], 1)
        if marker['after'] >= sequence or marker['attempt'] != event.get('amount'):
            raise ValueError('Invalid Rewind log boundary')
    if type(event) is dict and event.get('kind') == 'limited_trigger_used':
        fields += ' trigger_keyword'
        if event.get('trigger_keyword') not in (None, 'spellburst', 'frenzy') or type(event.get('amount')) is not int or event['amount'] < 0:
            raise ValueError('Invalid public trigger consumption')
    if type(event) is dict and str(event.get('kind', '')).startswith('choose_both_modifier_'):
        fields += ' choose_both_modifier'
        validate_choose_modifier_view(event.get('choose_both_modifier'), event.get('kind'))
    if type(event) is dict and str(event.get('kind', '')).startswith('spell_modifier_'):
        fields += ' spell_modifier'
        validate_spell_modifier_view(event.get('spell_modifier'), event.get('kind'))
    if type(event) is dict and str(event.get('kind', '')).startswith('combo_modifier_'):
        fields += ' combo_modifier'
        validate_combo_modifier_view(event.get('combo_modifier'), event.get('kind'))
    if type(event) is dict and str(event.get('kind', '')).startswith('battlecry_modifier_'):
        fields += ' battlecry_modifier'
        validate_battlecry_modifier_view(event.get('battlecry_modifier'), event.get('kind'))
    if type(event) is dict and str(event.get('kind', '')).startswith('player_effect_'):
        fields += ' player_effect'
        validate_player_effect_view(event.get('player_effect'), registry, event.get('kind'))
    if type(event) is dict and str(event.get('kind', '')).startswith('quest_'):
        fields += ' quest'
        validate_quest_view(event.get('quest'), registry)
    if type(event) is dict and event.get('kind') in ('minion_ability_started', 'minion_ability_used'):
        fields += ' minion_ability'
        ability = event.get('minion_ability')
        _fields(ability, 'ability_id card_id', 'public minion ability')
        if type(ability['ability_id']) is not str or not ability['ability_id'].strip():
            raise ValueError('Invalid public ability key')
        if ability['card_id'] is not None and not registry.card(ability['card_id']).choice_only:
            raise ValueError('Ability card must be a descriptor')
    if type(event) is dict and event.get('kind') == 'turns_scheduled':
        fields += ' turns'
        if type(event.get('turns')) is not list or not event['turns']:
            raise ValueError('Public turn schedule requires a nonempty player sequence')
        for player in event['turns']:
            player_id(player)
    if type(event) is dict and event.get('kind') == 'deck_card_revealed':
        fields += ' deck_reveal'
        result = event.get('deck_reveal')
        _fields(result, 'kind card', 'public deck reveal')
        owner = player_id(event.get('player_id'))
        if result['kind'] not in ('minion', 'spell') or event.get('target') is not None:
            raise ValueError('Public deck reveal leaked an identity handle or changed its range')
        face = result['card']
        if face is not None:
            _fields(face, 'player_id card_id cost', 'public revealed deck face')
            if player_id(face['player_id']) != owner or registry.card(face['card_id']).kind.value != result['kind']:
                raise ValueError('Public deck reveal changed its original owner or kind')
            _integer(face['cost'])
        if event.get('amount') != (0 if face is None else face['cost']):
            raise ValueError('Public deck reveal changed its original cost')
    if type(event) is dict and event.get('kind') == 'joust_resolved':
        fields += ' joust'
        result = event.get('joust')
        _fields(result, 'kind own opponent won', 'public Joust result')
        if result['kind'] not in ('minion', 'spell') or type(result['won']) is not bool:
            raise ValueError('Invalid public Joust profile or outcome')
        initiator = player_id(event.get('player_id'))
        for face, owner in ((result['own'], initiator), (result['opponent'], 3-initiator)):
            if face is not None:
                _fields(face, 'player_id card_id cost', 'public Joust face')
                if player_id(face['player_id']) != owner or registry.card(face['card_id']).kind.value != result['kind']:
                    raise ValueError('Public Joust face changed owner or kind')
                _integer(face['cost'])
        own, other = result['own'], result['opponent']
        if result['won'] != (own is not None and (other is None or own['cost'] > other['cost'])) or event.get('amount') != int(result['won']):
            raise ValueError('Public Joust outcome disagrees with revealed costs')
    _fields(event, fields, 'player event')
    _integer(event['sequence'], 1)
    if event['sequence'] != sequence or type(event['kind']) is not str or event['kind'] not in EVENT_KINDS:
        raise ValueError('Invalid player event sequence or kind')
    if event['player_id'] is not None:
        player_id(event['player_id'])
    if type(event['amount']) is not int:
        raise ValueError('Invalid player event amount')
    if event['kind'] == 'overload_added':
        _integer(event['amount'], 1)
        if event['player_id'] is None or event['source'] is not None or event['target'] is not None:
            raise ValueError('Overload fact requires a player amount without entity identities')
    if event['kind'] in ('card_spell_repeat_added','card_spell_repeat_removed'):
        if event['player_id']!=viewer or event['amount']<2 or event['target'] is None:
            raise ValueError('Invalid private card spell repeat event')
    if event['kind'] == 'hand_card_made_temporary':
        if event['player_id'] != viewer or event['target'] is None or event['amount'] != 0:
            raise ValueError('Invalid private temporary grant event')
    for field in ('source', 'target'):
        _identity(event[field], knowledge, registry)
    choice = event['choice']
    if choice is not None:
        _fields(choice, 'player_id ref source prompt purpose min_count max_count options', 'observed choice')
        if event['kind'] != 'choice_requested':
            raise ValueError('Choice payload on wrong event')
        player_id(choice['player_id'])
        _choice_ref(choice['ref'], knowledge)
        _identity(choice['source'], knowledge, registry)
        if type(choice['prompt']) is not str or choice['purpose'] not in ('effect', 'mulligan', 'rewind', 'dredge', 'pool_discovery', 'card_discovery', 'assemble'):
            raise ValueError('Invalid observed choice description')
        _integer(choice['min_count'])
        _integer(choice['max_count'])
        if type(choice['options']) is not list or not choice['min_count'] <= choice['max_count'] <= len(choice['options']):
            raise ValueError('Invalid observed options')
        for n, option in enumerate(choice['options'], 1):
            _fields(option, 'ref label card_id entity' + (' preview' if 'preview' in option else ''), 'observed option')
            if 'preview' in option:
                from .serialization import preview_from_dict
                if option['card_id'] is None: raise ValueError('Preview requires a card identity')
                preview_from_dict(option['preview'])
            if option['ref'] != f'o{n}' or type(option['label']) is not str:
                raise ValueError('Invalid observed option')
            _identity(option['entity'], knowledge, registry)
            if option['card_id'] is not None:
                registry.card(option['card_id'])
    selected = event['selected']
    if selected is not None:
        _fields(selected, 'ref options', 'observed selection')
        if event['kind'] != 'choice_selected':
            raise ValueError('Selection payload on wrong event')
        _choice_ref(selected['ref'], knowledge)
        if (type(selected['options']) is not list or
                any(type(i) is not str or not re.fullmatch(r'o[1-9][0-9]*', i) for i in selected['options']) or
                len(set(selected['options'])) != len(selected['options'])):
            raise ValueError('Invalid observed selection')


def validate_counter_policy_view(value):
    _fields(value, 'kind uses_remaining expires_turn', 'counter policy fact')
    if value['kind'] not in ('minion', 'spell'):
        raise ValueError('Invalid observed counter kind')
    _integer(value['uses_remaining'])
    if value['expires_turn'] is not None: _integer(value['expires_turn'], 1)


def reveal_hand_card(r, effect):
    from .errors import ResolutionError
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.zone != Zone.HAND:
        raise ResolutionError('RevealHandCard requires a current hand card')
    for viewer in effect.viewers:
        r.game._information.players[viewer].remember(entity)
    r.emit('card_revealed', target_id=entity.id, player_id=entity.controller, viewers=effect.viewers)


def validate_quest_view(value, registry):
    _fields(value, 'quest_kind stage stages stage_card_id progress goal completing', 'public quest')
    if value['quest_kind'] not in ('quest', 'questline', 'sidequest', 'repeatable_quest'):
        raise ValueError('Invalid public quest kind')
    for field in ('stage', 'stages', 'goal'):
        _integer(value[field], 1)
    _integer(value['progress'])
    if (value['stages'] != (3 if value['quest_kind'] == 'questline' else 1) or value['stage'] > value['stages']
            or value['progress'] > value['goal'] or type(value['completing']) is not bool
            or value['completing'] != (value['progress'] == value['goal'])):
        raise ValueError('Invalid public quest progress')
    registry.card(value['stage_card_id'])


def validate_choose_modifier_view(value, event_kind):
    from .choose_policies import declaration
    _fields(value, 'kinds origins uses_remaining expires_turn', 'public Choose Both modifier')
    if type(value['kinds']) is not list or type(value['origins']) is not list:
        raise ValueError('Choose Both public kinds and origins require arrays')
    declaration(tuple(CardType(k) for k in value['kinds']), tuple(value['origins']))
    remaining = value['uses_remaining']
    if remaining is not None: _integer(remaining, 0 if event_kind == 'choose_both_modifier_used' else 1)
    if event_kind == 'choose_both_modifier_used' and remaining is None:
        raise ValueError('Unlimited Choose Both policy cannot consume a use')
    if value['expires_turn'] is not None: _integer(value['expires_turn'], 1)
    if event_kind == 'choose_both_modifier_expired' and value['expires_turn'] is None:
        raise ValueError('Permanent Choose Both policy cannot expire')


def validate_battlecry_modifier_view(value, event_kind):
    from .model import BattlecryRepeatSpec
    from .battlecry_matching import battlecry_match_public_from_dict
    _fields(value, 'repetitions kinds scope match uses_remaining expires_turn', 'public Battlecry modifier')
    if type(value['kinds']) is not list: raise ValueError('Battlecry modifier kinds require a list')
    spec = BattlecryRepeatSpec(value['repetitions'], tuple(CardType(k) for k in value['kinds']),
                              value['scope'], battlecry_match_public_from_dict(value['match']))
    if spec.scope != 'friendly':
        raise ValueError('Public player Battlecry policies cannot require a physical self carrier')
    remaining=value['uses_remaining']
    if remaining is not None: _integer(remaining,0 if event_kind=='battlecry_modifier_used' else 1)
    if event_kind=='battlecry_modifier_used' and remaining is None: raise ValueError('Unlimited Battlecry modifier cannot be consumed')
    if value['expires_turn'] is not None: _integer(value['expires_turn'],1)
    if event_kind=='battlecry_modifier_expired' and value['expires_turn'] is None: raise ValueError('Permanent Battlecry modifier cannot expire')


def validate_combo_modifier_view(value, event_kind):
    from .model import ComboRepeatSpec
    from .combo_matching import combo_match_public_from_dict
    _fields(value, 'repetitions kinds scope match uses_remaining expires_turn trigger', 'public Combo modifier')
    if type(value['kinds']) is not list: raise ValueError('Combo modifier kinds require a list')
    spec=ComboRepeatSpec(value['repetitions'],tuple(CardType(k) for k in value['kinds']),
        value['scope'],combo_match_public_from_dict(value['match']))
    if spec.scope != 'friendly':
        raise ValueError('Public player Combo policies cannot require a physical self carrier')
    if value['trigger'] not in ('play','activation'):raise ValueError('Invalid public Combo policy trigger')
    remaining=value['uses_remaining']
    if remaining is not None: _integer(remaining,0 if event_kind=='combo_modifier_used' else 1)
    if event_kind=='combo_modifier_used' and remaining is None: raise ValueError('Unlimited Combo modifier cannot be consumed')
    if value['expires_turn'] is not None: _integer(value['expires_turn'],1)
    if event_kind=='combo_modifier_expired' and value['expires_turn'] is None: raise ValueError('Permanent Combo modifier cannot expire')


def validate_player_effect_view(value, registry, event_kind):
    _fields(value, 'effect_key card_id effect_kind remaining_turns' +
            (' adaptations' if 'adaptations' in value else ''), 'public player effect')
    spec = registry.player_effect(value['effect_key'])
    if (spec.kind == 'adaptations') != ('adaptations' in value):
        raise ValueError('Public Adaptation material differs from its player-effect kind')
    if spec.kind == 'adaptations':
        from .model import validate_adaptations
        if type(value['adaptations']) not in (tuple, list):
            raise ValueError('Public Adaptations require their ordered fixed choices')
        validate_adaptations(tuple(value['adaptations']))
    if value['card_id'] != spec.card_id or value['effect_kind'] != spec.kind:
        raise ValueError('Invalid public player effect definition')
    remaining = value['remaining_turns']
    if spec.kind in ('turn_rule','next_spell_damage'):
        if event_kind == 'player_effect_ticked':
            raise ValueError('Current-turn rules do not have countdown ticks')
        if event_kind == 'player_effect_expired':
            if type(remaining) is not int or remaining != 0:
                raise ValueError('Expired current-turn rule requires zero remaining turns')
        elif remaining is not None:
            raise ValueError('Current-turn rules have no owner countdown')
        return
    if spec.duration is None:
        if remaining is not None or event_kind in ('player_effect_expired', 'player_effect_ticked'):
            raise ValueError('Whole-game effects cannot expire')
    else:
        _integer(remaining)
        if (remaining > spec.duration or (remaining == 0) != (event_kind == 'player_effect_expired') or
                (event_kind == 'player_effect_added' and remaining not in
                    ((1, 2) if spec.next_turn_end else (spec.duration,)))):
            raise ValueError('Invalid public player effect countdown')


def validate_spell_modifier_view(value, event_kind):
    from .model import SpellRepeatSpec
    from .repeat_matching import repeat_match_public_from_dict
    _fields(value, 'casts class_mode match uses_remaining expires_turn', 'public spell modifier')
    SpellRepeatSpec(value['casts'], value['class_mode'], repeat_match_public_from_dict(value['match']))
    remaining=value['uses_remaining']
    if remaining is not None: _integer(remaining,0 if event_kind=='spell_modifier_used' else 1)
    if event_kind=='spell_modifier_used' and remaining is None: raise ValueError('Unlimited spell modifier cannot be consumed')
    if value['expires_turn'] is not None: _integer(value['expires_turn'],1)
    if event_kind=='spell_modifier_expired' and value['expires_turn'] is None: raise ValueError('Permanent spell modifier cannot expire')
