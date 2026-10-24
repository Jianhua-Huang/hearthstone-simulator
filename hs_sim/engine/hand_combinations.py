"""Finite declared hand recipes, settled by the existing hand lifecycle driver."""
from dataclasses import dataclass

from .construction import ids, name
from .model import CardType, Zone


@dataclass(frozen=True)
class HandCombinationProfile:
    result_card_id: str
    left_card_id: str
    right_card_id: str
    version: str = 'hand-combination-v1'

    def __post_init__(self):
        ids((self.result_card_id, self.left_card_id, self.right_card_id), 'hand combination faces',
            unique=self.version == 'hand-combination-v1')
        name(self.version, 'hand combination policy')
        if self.version not in ('hand-combination-v1', 'hand-spell-mixture-v1'):
            raise ValueError('Unsupported native hand combination policy')
        if self.result_card_id in (self.left_card_id, self.right_card_id):
            raise ValueError('A hand recipe cannot contain its own result')


def validate_profiles(registry):
    seen = set(); mixtures = []
    for key, profile in registry.hand_combinations.items():
        if type(profile) is not HandCombinationProfile or profile.result_card_id != key:
            raise ValueError('Hand combination profile differs from its registered result')
        profile.__post_init__()
        if profile.version == 'hand-spell-mixture-v1':
            mixtures.append(profile)
            continue
        for cid in (profile.result_card_id, profile.left_card_id, profile.right_card_id):
            card = registry.card(cid)
            if cid in seen or card.kind != CardType.MINION or not card.hand_playable or card.shatter is not None:
                raise ValueError('Native hand combinations require disjoint ordinary minion faces')
            seen.add(cid)
    inputs, results, pairs = set(), set(), set()
    for profile in mixtures:
        pair = tuple(sorted((profile.left_card_id, profile.right_card_id)))
        if pair in pairs:
            raise ValueError('A physical hand mixture has ambiguous results')
        pairs.add(pair); results.add(profile.result_card_id); inputs.update(pair)
        cards = tuple(registry.card(cid) for cid in (profile.result_card_id, *pair))
        if (any(c.kind != CardType.SPELL or not c.hand_playable or not c.manual_playable or c.on_play is None or c.shatter is not None or
                c.choose_one is not None or c.secret is not None or c.quest is not None for c in cards) or
                len({c.cost for c in cards}) != 1):
            raise ValueError('Hand mixtures require equal-cost ordinary physical spell faces')
    if inputs & results or (inputs | results) & seen:
        raise ValueError('Hand mixtures cannot recurse or borrow another native family')


def next_pair(state, registry):
    for player in state.players.values():
        for key in sorted(registry.hand_combinations):
            profile = registry.hand_combinations[key]
            if profile.version != 'hand-combination-v1':
                continue
            left = [state.entities[i] for i in player.hand if state.entities[i].card_id == profile.left_card_id]
            right = [state.entities[i] for i in player.hand if state.entities[i].card_id == profile.right_card_id]
            for a in left:
                for b in right:
                    # Either unsilenced half still has its printed combination
                    # text. No invented keyword or counter is attached to it.
                    if not (a.silenced and b.silenced):
                        return player, profile, a, b
    return next_mixture_pair(state, registry)


def next_mixture_pair(state, registry):
    recipes = {tuple(sorted((p.left_card_id, p.right_card_id))): p
        for p in registry.hand_combinations.values() if p.version == 'hand-spell-mixture-v1'}
    if not recipes:
        return None
    for player in state.players.values():
        for index, identity in enumerate(player.hand):
            left = state.entities[identity]
            for other in player.hand[index+1:]:
                right = state.entities[other]
                profile = recipes.get(tuple(sorted((left.card_id, right.card_id))))
                if profile is not None and not (left.silenced and right.silenced):
                    return player, profile, left, right
    return None


def settle_hands(r, *, initial=False):
    from .shatter import inherit
    while pair := next_pair(r.state, r.registry):
        r.charge()
        player, profile, left, right = pair
        position = min(player.hand.index(left.id), player.hand.index(right.id))
        ordered = tuple(i for i in player.hand if i in (left.id, right.id))
        r.move(left, Zone.GRAVEYARD)
        r.move(right, Zone.GRAVEYARD)
        combined = r.create_entity(player.id, profile.result_card_id, Zone.HAND, position,
            hand_entry_reason='scenario' if initial else 'recombine',
            hand_entry_source_id=None if initial else ordered[0])
        # Minions retain their declared left material; mixtures retain the
        # oldest physical held source selected above. Both remain CN-pending.
        inherit(r, left, combined)
        r.emit('cards_recombined', source_id=ordered[0], target_id=combined.id,
            player_id=player.id, fragment_ids=ordered)
        from .hand_history import publish as publish_hand_entry
        publish_hand_entry(r, combined.hand_entry_id)
