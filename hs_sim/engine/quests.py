"""Public quest slots and resumable, instance-guarded progress/reward stages."""
from dataclasses import dataclass, replace

from .effects import Effect
from .lifecycle import attachment_id
from .model import (QUEST_FULL_BOARD_TURNS, QUEST_FULL_THEN_EMPTY_HAND,
                    QuestProgress, Zone, _int, _name)


def pair_parent(state, registry, record, *, accepting=False):
    """Use the original typed parent, never a later same-source spell attempt."""
    if record is None or record.quest_parent_cast_id is None:
        return None
    if not 1 <= record.quest_parent_cast_id < record.id:
        raise ValueError('Child quest lost its earlier original parent')
    parent = state.cast_history[record.quest_parent_cast_id-1]
    spec = registry.card(parent.card_id).quest
    if (record.origin != 'effect' or (parent.source_id,parent.player_id) !=
            (record.caster_id,record.player_id) or record.action < parent.action or not parent.payload_started or
            spec is None or spec.kind != 'paired_quest' or record.card_id not in tuple(s.card_id for s in spec.stages)):
        raise ValueError('Child quest changed its complete original paired-spell source')
    if accepting and (parent.completed or parent.interrupted):
        return None
    return parent


def _parent_for_quest(state, registry, entity):
    identity = entity.quest_progress.activation_cast_id
    if identity is None:
        return None
    if not 1 <= identity <= len(state.cast_history):
        raise ValueError('Quest lost its original activation cast')
    record = state.cast_history[identity-1]
    if ((record.player_id,record.card_id)!=(entity.controller,entity.card_id) or
            record.source_id not in (entity.id,entity.origin_entity_id) or not record.payload_started or record.failure is not None):
        raise ValueError('Quest changed its original physical activation source')
    return pair_parent(state, registry, record)


def compatible_main_quests(state, registry, player_id):
    active = [state.entities[i] for i in state.players[player_id].quests]
    original = {q.id:_parent_for_quest(state, registry, q) for q in active}
    main = [q for q in active if registry.card(q.card_id).quest.kind != 'sidequest']
    parents = [original[q.id] for q in main]
    if any(registry.card(q.card_id).quest.kind == 'paired_quest' for q in main):
        return False  # The source casts its children; it never occupies a quest slot.
    if len(main) <= 1:
        return True
    return all(p is not None for p in parents) and len({p.id for p in parents}) == 1


def validate_paired_definitions(registry):
    children = set()
    for card in registry.cards.values():
        spec = card.quest
        if spec is None or spec.kind != 'paired_quest':
            continue
        if card.on_play is not None:
            raise ValueError('A paired quest source uses only its two declared spell payloads')
        for stage in spec.stages:
            child = registry.card(stage.card_id)
            if (stage.card_id == card.id or stage.card_id in children or child.quest is None
                    or child.quest.kind != 'quest' or child.quest.stages != (stage,)):
                raise ValueError('Paired quests require two distinct complete ordinary quest declarations')
            children.add(stage.card_id)


def activation_error(state, registry, rules, player_id, card_id, *, cast=None):
    spec = registry.card(card_id).quest
    if spec is None:
        return None
    quests = [state.entities[i] for i in state.players[player_id].quests]
    from .secrets import area_count
    slots = 2 if spec.kind == 'paired_quest' else 1
    if area_count(state.players[player_id], registry) + slots > rules.max_secret_zone:
        return 'Secret/quest/ongoing area is full'
    if len(quests) + slots > rules.max_quests:
        return 'Quest area is full'
    if any(q.card_id == card_id for q in quests):
        return 'This quest is already active'
    if spec.kind != 'sidequest' and any(registry.card(q.card_id).quest.kind != 'sidequest' for q in quests):
        parent = pair_parent(state, registry, cast, accepting=True)
        if parent is None or any((_parent_for_quest(state, registry, q) is None or
                _parent_for_quest(state, registry, q).id != parent.id)
                for q in quests if registry.card(q.card_id).quest.kind != 'sidequest'):
            return 'A main quest or questline is already active'
    return None


def spell_payload(r, entity, record, *, repeated=False):
    """Quest text still owns ordinary casts, history, activation and capacity."""
    spec = r.registry.card(record.card_id).quest
    if activation_error(r.state, r.registry, r.rules, record.player_id, record.card_id, cast=record) is not None:
        r.emit('quest_activation_failed', player_id=record.player_id)
        return ()
    if spec.kind == 'paired_quest':
        return tuple(CastQuestChild(record.id, s.card_id) for s in spec.stages)
    if repeated:
        entity = r.create_entity(record.player_id, record.card_id, Zone.GRAVEYARD)
        entity.origin_entity_id = record.source_id
    activate(r, entity, cast=record)
    return ()


@dataclass(frozen=True)
class CastQuestChild(Effect):
    parent_cast_id: int
    card_id: str

    def __post_init__(self):
        from .model import _int, _name
        _int(self.parent_cast_id, 'quest parent cast', 1)
        _name(self.card_id, 'quest child spell')


def cast_child(r, effect):
    effect.__post_init__()
    from .spell_casts import CastSpell, cast_generated, cast_record
    parent = cast_record(r.state, effect.parent_cast_id)
    spec = r.registry.card(parent.card_id).quest
    if (not parent.payload_started or parent.completed or parent.interrupted or spec is None or
            spec.kind != 'paired_quest' or effect.card_id not in tuple(s.card_id for s in spec.stages)):
        raise ValueError('Child quest requires its actual still-executing paired spell')
    return cast_generated(r, CastSpell(parent.player_id, effect.card_id, parent.source_id),
        quest_parent_cast_id=parent.id)


def completed_plays(state):
    return tuple(play.id for play in state.play_history if play.completed)


def activate(r, entity, *, cast=None):
    if r.registry.card(entity.card_id).quest.kind == 'paired_quest':
        raise ValueError('A paired quest source must cast its original two quest spells')
    entity.quest_progress = QuestProgress(attachment_id(r.state), completed_before=completed_plays(r.state),
        activation_cast_id=None if cast is None else cast.id)
    r.move(entity, Zone.QUEST)
    r.emit('quest_started', source_id=entity.id, player_id=entity.controller,
           **public_progress(r.registry, entity))


def public_progress(registry, entity):
    spec, progress = registry.card(entity.card_id).quest, entity.quest_progress
    stage = spec.stages[progress.stage]
    return dict(quest_kind=spec.kind, stage=progress.stage + 1, stages=len(spec.stages),
                stage_card_id=stage.card_id, progress=progress.value, goal=stage.goal,
                completing=progress.completing)


def state_matches(r, entity, stage):
    """Finite native state subscriptions at ordinary notification boundaries.

    Check actual rules/capacity before allocating a detached behavior context.
    Ordinary named-event quests retain their existing fast path. The callback
    keeps this accepted snapshot even if an earlier reaction changes the area.
    """
    progress = entity.quest_progress
    if stage.events == (QUEST_FULL_BOARD_TURNS,):
        if r.state.active_player != entity.controller or not r.state.owner_turn_history:
            return False
        turn = r.state.owner_turn_history[-1]
        return (not turn.closed and (turn.player_id, turn.turn) == (entity.controller, r.state.turn)
            and f'owner_turn:{turn.id}' not in progress.keys
            and len(r.player(entity.controller).board) >= r.rules.max_board)
    if stage.events == (QUEST_FULL_THEN_EMPTY_HAND,):
        from .hand_capacity import hand_capacity
        player = r.player(entity.controller)
        return (progress.value == 0 and len(player.hand) >= hand_capacity(player, r.rules)
            or progress.value == 1 and 'full' in progress.keys and not player.hand)
    return False


@dataclass(frozen=True)
class AdvanceQuest(Effect):
    target_id: int
    instance_id: int
    stage: int
    amount: int = 1
    key: str | None = None

    def __post_init__(self):
        _int(self.target_id, 'quest target', 1)
        _int(self.instance_id, 'quest instance', 1)
        _int(self.stage, 'quest stage', 0)
        _int(self.amount, 'quest increment', 0)
        if self.key is not None:
            _name(self.key, 'quest key')
            if self.amount != 1:
                raise ValueError('A distinct quest key contributes exactly one progress')


@dataclass(frozen=True)
class ResetQuestProgress(Effect):
    target_id: int
    instance_id: int
    stage: int

    def __post_init__(self):
        AdvanceQuest(self.target_id, self.instance_id, self.stage)


@dataclass(frozen=True)
class CompleteQuestStage(ResetQuestProgress):
    pass


@dataclass(frozen=True)
class FinishQuestStage(ResetQuestProgress):
    pass


@dataclass(frozen=True)
class RemoveQuest(Effect):
    target_id: int

    def __post_init__(self):
        _int(self.target_id, 'quest target', 1)


def matching(r, effect):
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.zone != Zone.QUEST:
        return None
    progress = entity.quest_progress
    return entity if progress.id == effect.instance_id and progress.stage == effect.stage else None


def advance(r, effect):
    entity = matching(r, effect)
    if entity is None or entity.quest_progress.completing or not effect.amount:
        return
    progress = entity.quest_progress
    if effect.key is not None and effect.key in progress.keys:
        return
    goal = r.registry.card(entity.card_id).quest.stages[progress.stage].goal
    value = min(goal, progress.value + effect.amount)
    entity.quest_progress = replace(progress, value=value, completing=value == goal,
        keys=progress.keys + ((effect.key,) if effect.key is not None else ()))
    r.emit('quest_progressed', source_id=entity.id, player_id=entity.controller,
           amount=value - progress.value, **public_progress(r.registry, entity))
    if value == goal:
        return [CompleteQuestStage(entity.id, progress.id, progress.stage)]


def reset(r, effect):
    entity = matching(r, effect)
    if entity is None or entity.quest_progress.completing:
        return
    if entity.quest_progress.value:
        entity.quest_progress = replace(entity.quest_progress, value=0, keys=(), completed_before=completed_plays(r.state))
        r.emit('quest_progress_reset', source_id=entity.id, player_id=entity.controller,
               **public_progress(r.registry, entity))
    else:
        entity.quest_progress = replace(entity.quest_progress, completed_before=completed_plays(r.state))


def complete(r, effect):
    entity = matching(r, effect)
    if entity is None or not entity.quest_progress.completing:
        return
    spec = r.registry.card(entity.card_id).quest.stages[effect.stage]
    event = r.emit('quest_stage_completed', source_id=entity.id, player_id=entity.controller,
                   **public_progress(r.registry, entity))
    reward = r.call(spec.reward_behavior, entity.id, entity.controller, event=event)
    # Retain the slot while the reward resolves (possibly waiting on a choice).
    # The next stage never consumes the previous stage's excess or queued events.
    return [reward, FinishQuestStage(entity.id, effect.instance_id, effect.stage)]


def finish(r, effect):
    entity = matching(r, effect)
    if entity is None or not entity.quest_progress.completing:
        return
    spec = r.registry.card(entity.card_id).quest
    if spec.kind == 'repeatable_quest':
        r.emit('quest_completed', source_id=entity.id, player_id=entity.controller,
               **public_progress(r.registry, entity))
        # The physical quest and slot stay installed. A fresh instance makes
        # already-captured progress/reset/finish effects from the old cycle stale.
        entity.quest_progress = QuestProgress(attachment_id(r.state), completed_before=completed_plays(r.state),
            activation_cast_id=entity.quest_progress.activation_cast_id)
        r.emit('quest_stage_started', source_id=entity.id, player_id=entity.controller,
               **public_progress(r.registry, entity))
    elif effect.stage + 1 == len(spec.stages):
        r.emit('quest_completed', source_id=entity.id, player_id=entity.controller,
               **public_progress(r.registry, entity))
        entity.quest_progress = None
        r.move(entity, Zone.GRAVEYARD)
    else:
        entity.quest_progress = QuestProgress(effect.instance_id, effect.stage + 1, completed_before=completed_plays(r.state),
            activation_cast_id=entity.quest_progress.activation_cast_id)
        r.emit('quest_stage_started', source_id=entity.id, player_id=entity.controller,
               **public_progress(r.registry, entity))


def remove(r, effect):
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.zone != Zone.QUEST:
        return
    r.emit('quest_removed', source_id=entity.id, player_id=entity.controller,
           **public_progress(r.registry, entity))
    entity.quest_progress = None
    r.move(entity, Zone.GRAVEYARD)


def register_quests(mechanics):
    from .minion_type_history import register
    register(mechanics)
    for effect, handler in ((CastQuestChild, cast_child), (AdvanceQuest, advance), (ResetQuestProgress, reset),
                            (CompleteQuestStage, complete), (FinishQuestStage, finish), (RemoveQuest, remove)):
        mechanics.register(effect, handler)
