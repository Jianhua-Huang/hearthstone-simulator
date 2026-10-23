"""Source-bound persistent programs applied after material, before entry bodies."""
from dataclasses import dataclass

from .model import CardType, PlayerEffectSpec, SummonStats, Zone
from .pools import PoolQuery, matches_metadata
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
    mode: str = 'set'

    def __post_init__(self):
        from .model import _name
        _name(self.program_id, 'entry stat program'); _name(self.card_id, 'entry stat source')
        PoolQuery(tribes_any=self.tribes).__post_init__()
        if not self.tribes or type(self.stats) is not SummonStats:
            raise ValueError('Entry stats require a real tribe filter and complete typed values')
        self.stats.__post_init__()
        if self.stats.attack is None or self.stats.health is None or self.stats.health < 1:
            raise ValueError('Entry stat program requires both positive-health values')
        if type(self.mode)is not str or self.mode not in ('set', 'next_play_add'):
            raise ValueError('Unknown finite entry stat program mode')


def validate_profile(registry, profile):
    if type(profile) is not SummonEntryStatsProfile: raise ValueError('Expected SummonEntryStatsProfile')
    profile.__post_init__(); card = registry.card(profile.card_id)
    source = card.battlecry is not None
    if (card.kind != CardType.MINION or not source or
            registry.player_effect(profile.program_id) != PlayerEffectSpec(profile.program_id, profile.card_id)):
        raise ValueError('Entry stats require their original minion body and independent program')


def install(r, player_id, instance):
    profile = r.registry.summon_entry_stats_profiles.get(instance.spec_id)
    if profile is None: return
    from .battlecries import active_battlecry
    row = active_battlecry(r.state, instance.source_id, player_id)
    if row is None or not row.payload_started or row.payload.behavior_id != r.registry.card(profile.card_id).battlecry:
        raise ValueError('Entry stat program requires its real active original Battlecry')
    origin = {'battlecry_id':row.id}
    r.emit(ACCEPTED, source_id=instance.source_id, player_id=player_id, program_id=profile.program_id,
        instance_id=instance.id, **origin, created_turn=instance.created_turn,
        entered_order=instance.entered_order, _capture=False)


def _original_play_matches(registry, play, profile):
    face = play.played_face
    return matches_metadata(PoolQuery(kinds=(CardType.MINION,),tribes_any=profile.tribes),
        card_id=face.card_id,kind=face.kind,cost=0,meta=face.metadata,
        spell_school=face.spell_school,keywords=())


def _apply(r, entity, player_id, matching, reason, **window):
    from .lifecycle import apply_summon_stats
    from .player_effects import RemovePlayerEffect, remove
    from .effects import Buff
    from .resolver import _buff_to
    for instance in matching:
        profile = r.registry.summon_entry_stats_profiles[instance.spec_id]
        if profile.mode == 'set':
            apply_summon_stats(r.state, entity, profile.stats, source_id=instance.source_id, label='summon_entry_stats')
            enchantment_id = entity.enchantments[-1].id
        else:
            # Shared retirement; captured reactions run after the complete
            # original synchronous entry step, before its queued bodies.
            remove(r,RemovePlayerEffect(player_id,instance.id))
            enchantment_id = _buff_to(r,Buff(entity.id,profile.stats.attack,profile.stats.health,
                instance.source_id),entity,notify=False).id
        r.emit(APPLIED, source_id=instance.source_id, target_id=entity.id, player_id=player_id,
            program_id=profile.program_id, instance_id=instance.id, enchantment_id=enchantment_id,
            card_id=entity.card_id, presence_id=entity.board_presence_id, reason=reason, **window, _capture=False)
    if matching: r.refresh_auras()


def apply_paid_play(r, play, entity):
    """After counter/capacity acceptance, before source material enters/merges."""
    instances = tuple(e for e in r.player(play.player_id).player_effects
        if (p:=r.registry.summon_entry_stats_profiles.get(e.spec_id)) is not None and p.mode=='next_play_add')
    if not instances:return
    from .play_history import play_record
    if (play_record(r.state,play.id)!=play or play.kind!=CardType.MINION or play.minion_result is not None or
            (entity.id,entity.card_id,entity.controller,entity.zone)!=(play.source_id,play.card_id,play.player_id,Zone.PLAY)):
        raise ValueError('Next played buff requires its original accepted pending minion')
    matching=tuple(e for e in sorted(instances,key=lambda e:e.id)
        if _original_play_matches(r.registry,play,r.registry.summon_entry_stats_profiles[e.spec_id]))
    if not matching:return
    from .allocation_facts import SourceAllocationFact
    r.emit(ENTRY,target_id=entity.id,player_id=play.player_id,card_id=entity.card_id,reason='paid_play',
        presence_id=entity.board_presence_id,play_id=play.id,
        target_allocation=SourceAllocationFact.capture(r.state,entity).payload(),
        programs=tuple(e.id for e in matching),_capture=False)
    _apply(r,entity,play.player_id,matching,'paid_play',play_id=play.id)


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
        if (p:=r.registry.summon_entry_stats_profiles.get(e.spec_id)) is not None and p.mode!='next_play_add')
    if reason not in ('play', 'summon', 'stored', 'copy', 'reborn', 'resurrect'):
        raise ValueError('Unknown actual entry path for persistent stat program')
    if entity.zone != Zone.BOARD or entity.kind != CardType.MINION:
        raise ValueError('Entry stat program requires its actual board minion')
    matching = tuple(e for e in sorted(instances,key=lambda e:e.id)
        if has_any_tribe(r.registry,entity,r.registry.summon_entry_stats_profiles[e.spec_id].tribes))
    seen.add(key)
    r.emit(ENTRY, target_id=entity.id, player_id=entity.controller, presence_id=entity.board_presence_id,
        card_id=entity.card_id, reason=reason, programs=tuple(e.id for e in matching), _capture=False)
    _apply(r,entity,entity.controller,matching,reason)


def validate_boundary(game):
    if not game.registry.summon_entry_stats_profiles: return
    from .hero_health_history import effective_events
    from .allocation_facts import allocation_from_payload, validate_allocation
    from .play_history import play_record
    accepted = {}; applications = set(); entries = {}; completed = set(); consumed = set()
    def entry_key(event, data):
        return ('paid', data['play_id']) if data['reason']=='paid_play' else ('board',event.target_id,data['presence_id'])
    for event in effective_events(game._events):
        if event.kind not in (ACCEPTED, APPLIED, ENTRY): continue
        data = dict(event.data)
        if event.kind == ENTRY:
            key=entry_key(event,data);programs=data['programs'];paid=data['reason']=='paid_play'
            if paid:
                play=play_record(game._state,data['play_id'])
                fact=allocation_from_payload(data['target_allocation']);validate_allocation(game._state,game.registry,fact)
                if ((play.source_id,play.player_id,play.kind,play.card_id)!=(
                        event.target_id,event.player_id,CardType.MINION,data['card_id']) or
                        play.minion_result not in ('summoned','magnetized') or
                        (fact.entity_id,fact.card_id,fact.kind,fact.controller,fact.zone)!=(
                            play.source_id,play.card_id,CardType.MINION,play.player_id,Zone.PLAY)):
                    raise ValueError('Next-play stat window lost its original accepted pending source')
            elif type(data['presence_id']) is not int or not 0<data['presence_id']<game._state.next_order:
                raise ValueError('Entry stat window has an unknown original board presence')
            if (key in entries or event.target_id not in game._state.entities or
                    type(programs) is not tuple or len(programs)!=len(set(programs)) or
                    any(type(i)is not int or not 0<i<game._state.next_attachment_id for i in programs) or
                    any((event.player_id,identity)not in accepted for identity in programs)):
                raise ValueError('Entry stat window changed its original physical entry or accepted programs')
            for identity in programs:
                profile=game.registry.summon_entry_stats_profiles[accepted[(event.player_id,identity)][0]]
                if ((profile.mode=='next_play_add')!=paid or paid and
                        not _original_play_matches(game.registry,play,profile)):
                    raise ValueError('Entry stat window substituted its declared recipient policy')
            entries[key]=(event.player_id,programs,event.target_id,data['presence_id'])
            continue
        profile = game.registry.summon_entry_stats_profiles.get(data['program_id'])
        if profile is None: raise ValueError('Entry stat event lost its original declaration')
        if type(data['instance_id'])is not int or not 0<data['instance_id']<game._state.next_attachment_id:
            raise ValueError('Entry stat event has an invalid original program instance')
        key = (event.player_id, data['instance_id'])
        if event.kind == ACCEPTED:
            identity = data['battlecry_id']
            if type(identity)is not int or not 1 <= identity <= len(game._state.battlecry_history): raise ValueError('Unknown entry program Battlecry')
            row = game._state.battlecry_history[identity-1]
            valid=(row.payload_started and row.payload.behavior_id==game.registry.card(profile.card_id).battlecry and
                'play_id'not in data)
            if (key in accepted or not valid or (row.source_id, row.player_id) != (event.source_id, event.player_id)):
                raise ValueError('Entry stat program changed its original acceptance')
            accepted[key] = (profile.program_id, event.source_id, data['created_turn'], data['entered_order'])
        else:
            entry=entry_key(event,data);application=(entry,data['instance_id'])
            if (key not in accepted or accepted[key][:2] != (profile.program_id, event.source_id) or
                    type(data['enchantment_id'])is not int or not 0<data['enchantment_id']<game._state.next_attachment_id or
                    data['enchantment_id'] in applications or event.target_id not in game._state.entities or
                    data['reason'] not in ('play', 'summon', 'stored', 'copy', 'reborn', 'resurrect','paid_play') or
                    entry not in entries or entries[entry][0]!=event.player_id or
                    entries[entry][2:]!=(event.target_id,data['presence_id']) or
                    data['instance_id']not in entries[entry][1] or application in completed or
                    profile.mode!='set'and key in consumed):
                raise ValueError('Entry stat application lost its accepted source or original physical entry')
            applications.add(data['enchantment_id']);completed.add(application)
            if profile.mode!='set':consumed.add(key)
    if completed != {(entry,identity)for entry,(_,programs,_,_)in entries.items()for identity in programs}:
        raise ValueError('Entry stat window lost an actual original application')
    for player in game._state.players.values():
        for instance in player.player_effects:
            if instance.spec_id in game.registry.summon_entry_stats_profiles:
                if ((player.id,instance.id)in consumed or accepted.get((player.id, instance.id)) != (
                        instance.spec_id, instance.source_id, instance.created_turn, instance.entered_order)):
                    raise ValueError('Saved entry stat program has no original unconsumed acceptance')
