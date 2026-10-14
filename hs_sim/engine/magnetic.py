"""Position-selected hand play fusion, expressed as removable attachments."""
from dataclasses import replace

from .errors import ResolutionError
from .lifecycle import attachment_id, refresh_entity
from .model import AbilityInstance, CardType, Enchantment, Keyword, MagneticRecord, Zone


# Play/zone-entry mechanics do not become ongoing abilities on the host.
ENTRY_ABILITIES = frozenset(('on_play','battlecry','combo','on_use','on_launch','on_awaken','dormant_trigger','hand_progress','printed_attack_permit'))
ENTRY_KEYWORDS = frozenset((Keyword.TWINSPELL,Keyword.MINIATURIZE,Keyword.GIGANTIFY,Keyword.MINI,Keyword.GIGANTIC,Keyword.ECHO,Keyword.SHATTER,Keyword.SHATTERED,Keyword.HERALD,Keyword.COLOSSAL,Keyword.MAGNETIC,Keyword.COMBO,Keyword.OUTCAST,Keyword.FINALE,
    Keyword.MANATHIRST,Keyword.QUICKDRAW,Keyword.CORRUPT,Keyword.CORRUPTED,Keyword.INFUSE,Keyword.INFUSED))


def host_eligible(state, registry, source, host):
    spec=registry.card(source.card_id)
    if (source.kind!=CardType.MINION or Keyword.MAGNETIC not in source.keywords or not spec.magnetic_tribes or
            host.kind!=CardType.MINION or host.zone!=Zone.BOARD or host.controller!=source.controller or
            host.id not in state.players[source.controller].board or not host.active or host.doomed or host.health<=0):
        return False
    from .tribes import has_any_tribe
    return has_any_tribe(registry, host, spec.magnetic_tribes)


def host_at_position(state, registry, source, position):
    board=state.players[source.controller].board
    if type(position) is not int or not 0<=position<len(board):
        return None
    host=state.entities[board[position]]
    return host if host_eligible(state,registry,source,host) else None


def play_definition(state, registry, source, position, *, branch_id=None):
    from .play_history import play_definition as ordinary_definition
    definition=ordinary_definition(state,registry,source,branch_id=branch_id)
    if host_at_position(state,registry,source,position) is not None:
        return replace(definition,requires_target=False,targeting=None,target_rule='any_entity')
    return definition


def transferable_ability(ability):
    # One semantic predicate for merge and persistent attachment validation.
    return ability.kind not in ENTRY_ABILITIES and not (
        ability.kind == 'keyword' and ability.keyword in ENTRY_KEYWORDS)


def transferable_abilities(source):
    return tuple(a for a in source.abilities if transferable_ability(a))


def merge(r, source, host, play):
    from .tribes import tribe_changes
    if not host_eligible(r.state,r.registry,source,host) or source.zone!=Zone.PLAY or source.health<=0:
        raise ResolutionError('Magnetic play no longer has its hand source or live host in its pending play')
    abilities=transferable_abilities(source)
    # Active abilities have per-host semantic keys; do not silently replace one.
    existing={a.activation.id for a in host.abilities if a.kind=='activated'}
    if any(a.kind=='activated' and a.activation.id in existing for a in abilities):
        raise ResolutionError('Magnetic active ability conflicts with its host')
    group=len(r.state.magnetic_history)+1
    enchantment=Enchantment(attachment_id(r.state),source_id=source.id,attack=source.attack,
                            health=source.health,label='magnetic',magnetic_id=group)
    grants=[replace(a,id=attachment_id(r.state),origin='granted',source_id=source.id,
                    remove_on_silence=True,magnetic_id=group,
                    deathrattle_grant_card_id=source.card_id if a.kind=='deathrattle' else None) for a in abilities]
    record=MagneticRecord(group,play.id,source.id,host.id,source.controller,source.card_id,host.card_id,
                          source.attack,source.health,enchantment.id,tuple(a.id for a in grants),
                          tribe_changes(host))
    r.state.magnetic_history.append(record)
    # This is storage for a consumed hand card, not a death or resurrection fact.
    r.move(source,Zone.GRAVEYARD)
    host.enchantments.append(enchantment);host.abilities.extend(grants)
    from .timed_keywords import arm
    arm(r.state, host)
    refresh_entity(host)
    r.refresh_auras()
    return record


def validate_magnetic_history(state, registry):
    from .play_history import play_record
    if type(state.magnetic_history) is not list:
        raise ValueError('Magnetic history must be a list')
    previous_play=0
    for index,record in enumerate(state.magnetic_history,1):
        if type(record) is not MagneticRecord:
            raise ValueError('Expected magnetic record')
        record.__post_init__()
        play=play_record(state,record.play_id)
        source=registry.card(record.card_id);host=registry.card(record.host_card_id)
        if (record.id!=index or record.play_id<=previous_play or
                (record.source_id,record.target_id,record.player_id,record.card_id)!=
                (play.source_id,play.magnetic_target_id,play.player_id,play.card_id) or
                record.source_id not in state.entities or record.target_id not in state.entities or
                not source.magnetic_tribes or host.kind!=CardType.MINION or
                max((record.enchantment_id,*record.ability_ids))>=state.next_attachment_id):
            raise ValueError('Invalid magnetic provenance')
        from .tribes import tribe_state_for
        original = tribe_state_for(registry, host.id, record.host_tribe_changes)
        if original is None or not original.matches_any(source.magnetic_tribes):
            raise ValueError('Original magnetic host tribes do not satisfy the merge')
        if any(c.source_id is not None and c.source_id not in state.entities for c in record.host_tribe_changes):
            raise ValueError('Unknown original magnetic tribe grant source')
        if any(c.expires_turn is not None and c.expires_turn < play.turn for c in record.host_tribe_changes):
            raise ValueError('Original magnetic host retained expired tribe changes')
        previous_play=record.play_id
    if {p.id for p in state.play_history if p.minion_result == "magnetized"}!={m.play_id for m in state.magnetic_history}:
        raise ValueError('Magnetic play history is incomplete')


def public_magnetic(entity, state):
    groups=sorted({a.magnetic_id for a in (*entity.enchantments,*entity.abilities) if a.magnetic_id is not None})
    return [state.magnetic_history[i-1].card_id for i in groups]
