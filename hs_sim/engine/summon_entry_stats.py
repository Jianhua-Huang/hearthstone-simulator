"""Source-bound persistent programs applied after material, before entry bodies."""
from dataclasses import dataclass

from .model import CardType, PlayerEffectSpec, SummonStats, Zone
from .pools import PoolQuery
from .tribes import has_any_tribe

ACCEPTED = 'summon_entry_stat_program_accepted'
APPLIED = 'summon_entry_stats_applied'
ENTRY = 'summon_entry_stat_window'


@dataclass(frozen=True)
class SummonEntryStatsProfile:
    program_id: str
    card_id: str
    tribes: tuple[str, ...]
    stats: SummonStats

    def __post_init__(self):
        from .model import _name
        _name(self.program_id, 'entry stat program'); _name(self.card_id, 'entry stat source')
        PoolQuery(tribes_any=self.tribes).__post_init__()
        if not self.tribes or type(self.stats) is not SummonStats:
            raise ValueError('Entry stats require a real tribe filter and complete typed values')
        self.stats.__post_init__()
        if self.stats.attack is None or self.stats.health is None or self.stats.health < 1:
            raise ValueError('Entry stat program requires both positive-health values')


def validate_profile(registry, profile):
    if type(profile) is not SummonEntryStatsProfile: raise ValueError('Expected SummonEntryStatsProfile')
    profile.__post_init__(); card = registry.card(profile.card_id)
    if (card.kind != CardType.MINION or card.battlecry is None or
            registry.player_effect(profile.program_id) != PlayerEffectSpec(profile.program_id, profile.card_id)):
        raise ValueError('Entry stats require their original minion Battlecry and independent permanent program')


def install(r, player_id, instance):
    profile = r.registry.summon_entry_stats_profiles.get(instance.spec_id)
    if profile is None: return
    from .battlecries import active_battlecry
    row = active_battlecry(r.state, instance.source_id, player_id)
    if row is None or not row.payload_started or row.payload.behavior_id != r.registry.card(profile.card_id).battlecry:
        raise ValueError('Entry stat program requires its real active original Battlecry')
    r.emit(ACCEPTED, source_id=instance.source_id, player_id=player_id, program_id=profile.program_id,
        instance_id=instance.id, battlecry_id=row.id, created_turn=instance.created_turn,
        entered_order=instance.entered_order, _capture=False)


def apply_entry(r, entity, reason):
    if not r.registry.summon_entry_stats_profiles or reason == 'transform': return
    key = (entity.id, entity.board_presence_id)
    cached = getattr(r, '_entry_stat_windows', None)
    if cached is None or cached[0] != id(r.state):
        from .hero_health_history import effective_events
        seen = {(e.target_id, dict(e.data)['presence_id']) for e in effective_events(r.game._events) if e.kind == ENTRY}
        r._entry_stat_windows = (id(r.state), seen)
    else: seen = cached[1]
    if key in seen: return
    instances = tuple(e for e in r.player(entity.controller).player_effects
        if e.spec_id in r.registry.summon_entry_stats_profiles)
    if reason not in ('play', 'summon', 'stored', 'copy', 'reborn', 'resurrect'):
        raise ValueError('Unknown actual entry path for persistent stat program')
    if entity.zone != Zone.BOARD or entity.kind != CardType.MINION:
        raise ValueError('Entry stat program requires its actual board minion')
    matching = tuple(e for e in sorted(instances,key=lambda e:e.id)
        if has_any_tribe(r.registry,entity,r.registry.summon_entry_stats_profiles[e.spec_id].tribes))
    seen.add(key)
    r.emit(ENTRY, target_id=entity.id, player_id=entity.controller, presence_id=entity.board_presence_id,
        card_id=entity.card_id, reason=reason, programs=tuple(e.id for e in matching), _capture=False)
    from .lifecycle import apply_summon_stats
    for instance in matching:
        profile = r.registry.summon_entry_stats_profiles[instance.spec_id]
        apply_summon_stats(r.state, entity, profile.stats, source_id=instance.source_id, label='summon_entry_stats')
        r.emit(APPLIED, source_id=instance.source_id, target_id=entity.id, player_id=entity.controller,
            program_id=profile.program_id, instance_id=instance.id, enchantment_id=entity.enchantments[-1].id,
            card_id=entity.card_id, presence_id=entity.board_presence_id, reason=reason, _capture=False)
    if matching: r.refresh_auras()


def validate_boundary(game):
    if not game.registry.summon_entry_stats_profiles: return
    from .hero_health_history import effective_events
    accepted = {}; applications = set(); entries = {}; completed = set()
    for event in effective_events(game._events):
        if event.kind not in (ACCEPTED, APPLIED, ENTRY): continue
        data = dict(event.data)
        if event.kind == ENTRY:
            key=(event.target_id,data['presence_id']);programs=data['programs']
            if (key in entries or event.target_id not in game._state.entities or
                    type(key[1]) is not int or not 0<key[1]<game._state.next_order or
                    type(programs) is not tuple or len(programs)!=len(set(programs)) or
                    any((event.player_id,identity)not in accepted for identity in programs)):
                raise ValueError('Entry stat window changed its original physical entry or accepted programs')
            entries[key]=(event.player_id,programs)
            continue
        profile = game.registry.summon_entry_stats_profiles.get(data['program_id'])
        if profile is None: raise ValueError('Entry stat event lost its original declaration')
        key = (event.player_id, data['instance_id'])
        if event.kind == ACCEPTED:
            identity = data['battlecry_id']
            if not 1 <= identity <= len(game._state.battlecry_history): raise ValueError('Unknown entry program Battlecry')
            row = game._state.battlecry_history[identity-1]
            if (key in accepted or not row.payload_started or row.payload.behavior_id != game.registry.card(profile.card_id).battlecry or
                    (row.source_id, row.player_id) != (event.source_id, event.player_id)):
                raise ValueError('Entry stat program changed its original acceptance')
            accepted[key] = (profile.program_id, event.source_id, data['created_turn'], data['entered_order'])
        else:
            entry=(event.target_id,data['presence_id']);application=(entry,data['instance_id'])
            if (key not in accepted or accepted[key][:2] != (profile.program_id, event.source_id) or
                    data['enchantment_id'] in applications or data['enchantment_id'] >= game._state.next_attachment_id or
                    event.target_id not in game._state.entities or data['presence_id'] >= game._state.next_order or
                    data['reason'] not in ('play', 'summon', 'stored', 'copy', 'reborn', 'resurrect') or
                    entry not in entries or entries[entry][0]!=event.player_id or
                    data['instance_id']not in entries[entry][1] or application in completed):
                raise ValueError('Entry stat application lost its accepted source or original physical entry')
            applications.add(data['enchantment_id']);completed.add(application)
    if completed != {(entry,identity)for entry,(_,programs)in entries.items()for identity in programs}:
        raise ValueError('Entry stat window lost an actual original application')
    for player in game._state.players.values():
        for instance in player.player_effects:
            if instance.spec_id in game.registry.summon_entry_stats_profiles and accepted.get((player.id, instance.id)) != (
                    instance.spec_id, instance.source_id, instance.created_turn, instance.entered_order):
                raise ValueError('Saved entry stat program has no original acceptance')
