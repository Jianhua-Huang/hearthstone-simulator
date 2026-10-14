"""The existing pre-event state normalization, without events or callbacks."""
def normalize_event_state(state, reason, *, registry=None, cause_source=None, cause_target_id=None):
    from .death_causes import sync_state
    from .keyword_auras import refresh_hand_keyword_auras, refresh_conditional_keywords
    from .stat_auras import refresh_weapon_auras
    from .stat_relations import refresh_conditional_attacks
    refresh_conditional_attacks(state, registry)
    refresh_conditional_keywords(state)
    refresh_weapon_auras(state, include_dying=True)
    sync_state(state, reason, cause_source=cause_source, cause_target_id=cause_target_id)
    # Sources remain until the old death checkpoint; this does not allocate IDs.
    refresh_hand_keyword_auras(state, include_dying=True)
