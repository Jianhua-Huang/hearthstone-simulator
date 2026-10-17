"""Public quest slots and resumable, instance-guarded progress/reward stages."""
from dataclasses import dataclass, replace

from .effects import Effect
from .lifecycle import attachment_id
from .model import QuestProgress, Zone, _int, _name


def activation_error(state, registry, rules, player_id, card_id):
    spec = registry.card(card_id).quest
    if spec is None:
        return None
    quests = [state.entities[i] for i in state.players[player_id].quests]
    from .secrets import area_count
    if area_count(state.players[player_id], registry) >= rules.max_secret_zone:
        return 'Secret/quest/ongoing area is full'
    if len(quests) >= rules.max_quests:
        return 'Quest area is full'
    if any(q.card_id == card_id for q in quests):
        return 'This quest is already active'
    if spec.kind != 'sidequest' and any(registry.card(q.card_id).quest.kind != 'sidequest' for q in quests):
        return 'A main quest or questline is already active'
    return None


def completed_plays(state):
    return tuple(play.id for play in state.play_history if play.completed)


def activate(r, entity):
    entity.quest_progress = QuestProgress(attachment_id(r.state), completed_before=completed_plays(r.state))
    r.move(entity, Zone.QUEST)
    r.emit('quest_started', source_id=entity.id, player_id=entity.controller,
           **public_progress(r.registry, entity))


def public_progress(registry, entity):
    spec, progress = registry.card(entity.card_id).quest, entity.quest_progress
    stage = spec.stages[progress.stage]
    return dict(quest_kind=spec.kind, stage=progress.stage + 1, stages=len(spec.stages),
                stage_card_id=stage.card_id, progress=progress.value, goal=stage.goal,
                completing=progress.completing)


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
        entity.quest_progress = QuestProgress(attachment_id(r.state), completed_before=completed_plays(r.state))
        r.emit('quest_stage_started', source_id=entity.id, player_id=entity.controller,
               **public_progress(r.registry, entity))
    elif effect.stage + 1 == len(spec.stages):
        r.emit('quest_completed', source_id=entity.id, player_id=entity.controller,
               **public_progress(r.registry, entity))
        entity.quest_progress = None
        r.move(entity, Zone.GRAVEYARD)
    else:
        entity.quest_progress = QuestProgress(effect.instance_id, effect.stage + 1, completed_before=completed_plays(r.state))
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
    for effect, handler in ((AdvanceQuest, advance), (ResetQuestProgress, reset),
                            (CompleteQuestStage, complete), (FinishQuestStage, finish), (RemoveQuest, remove)):
        mechanics.register(effect, handler)
