"""Historical one-cost grants, original history and existing owner-turn duration."""
import json
from pathlib import Path

from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.effects import AddCostModifier, Buff, Damage, Draw
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.joust import Joust, joust_result
from hs_sim.engine.model import (
    BoardPresenceReference, CardAbilityCondition, CardDefinition, CardType, CostSpec, DamageKind,
    Keyword, TargetMode, TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import (
    BuffCapturedMinion, GrantCapturedKeyword, GrantCapturedSpellDamage, MinionReference,
)
from hs_sim.engine.spell_casts import cast_record
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record


GUARDIAN, ROCKET, ETHEREAL, ASHTONGUE, LACKEY, TRAPPER, POGO, CLOCKER, SLITHERSPEAR, JOUSTER = (
    'BT_722', 'BT_723', 'BT_724', 'BT_727', 'CFM_066',
    'CFM_759', 'BOT_283', 'TSC_632', 'TSC_827', 'AT_133')
LEAVES = (GUARDIAN, ROCKET, ETHEREAL, ASHTONGUE, LACKEY, TRAPPER, POGO, CLOCKER, SLITHERSPEAR, JOUSTER)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_grants.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-grants-v1.json'
BATCH_HASH = 'b28761c43a81eb21322d682ea799b5e49c000e022b1edb33688dfa17e9fe7102'
SECRET = CardAbilityCondition('secret', basis='printed')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != LEAVES or
            any(data[key] for key in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped', 'numeric_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in data['dependencies'])):
        raise TargetValidationError('Historical grants lost their ten complete pinned source faces')
    return data


def register_past_one_cost_grant_cards(registry):
    def augment(c, keyword=None):
        if c.target_id is None:
            return ()
        ref = BoardPresenceReference.capture(c.state, c.target_id)
        grant = (GrantCapturedSpellDamage(ref, 1, c.source_id) if keyword is None else
            GrantCapturedKeyword(ref, keyword, c.source_id))
        return (Damage(ref.entity_id, 1, c.source_id, DamageKind.MINION_ABILITY), grant)

    def ashtongue(c):
        if c.event.target_id != c.source_id or c.event.amount <= 0:
            return ()
        return (Damage(c.state.players[c.player_id].hero_id, c.event.amount,
            c.source_id, DamageKind.MINION_ABILITY),)

    def trapper(c):
        if c.deathrattle is None:
            raise ResolutionError('Tuskarr Trapper needs its original Deathrattle activation')
        attack = c.death.attack if c.death is not None else c.source.attack
        return (Draw(c.player_id, 1, c.source_id),) if attack >= 2 else ()

    def pogo(c):
        if not living_source(c):
            return ()
        rows = tuple(p for p in played_cards(c.state, c.player_id, kind=CardType.MINION)
            if p.played_face.card_id == POGO)
        own_play = (c.play.id if c.play is not None and
            (c.play.source_id, c.play.card_id) == (c.source_id, POGO) else None)
        if own_play is None and c.battlecry is not None:
            # Native attachment identity survives control, but not a reset or
            # a fresh copy. Match the original committed payload, not a name
            # or every historical play of the same physical entity ID.
            matching = [p.id for p in rows if p.source_id == c.source_id and
                any(b.ability_id == c.battlecry.payload.ability_id for b in p.battlecries)]
            own_play = max(matching, default=None)
        count = sum(p.id != own_play for p in rows)
        return (BuffCapturedMinion(MinionReference.capture(c.source), 2*count, 2*count, c.source_id),) if count else ()

    def slitherspear(c):
        cast = cast_record(c.state, dict(c.event.data)['cast_id'])
        if (cast.source_id, cast.player_id, cast.target_id) != (c.event.source_id, c.event.player_id, c.event.target_id):
            raise ResolutionError('Slitherspear lost its original completed spell')
        if (cast.player_id != c.player_id or not living_source(c) or not cast.completed or
                not cast.payload_started or cast.failure is not None or cast.interrupted):
            return ()
        return (Buff(c.source_id, attack=1, source_id=c.source_id, until_owner_turn_start=c.player_id),)

    def joust_reward(c):
        result = joust_result(c.event)
        if result is None or result.player_id != c.player_id:
            raise ResolutionError('Gadgetzan Jouster lost its original Joust result')
        return (BuffCapturedMinion(MinionReference.capture(c.source), 1, 1, c.source_id),) if result.won and living_source(c) else ()

    bodies = {
        GUARDIAN: lambda c: augment(c, Keyword.DIVINE_SHIELD),
        ROCKET: lambda c: augment(c, Keyword.RUSH),
        ETHEREAL: lambda c: augment(c), ASHTONGUE: ashtongue,
        LACKEY: lambda c: (AddCostModifier(c.player_id, CostSpec(set_to=1,
            card_types=(CardType.SPELL,), ability=SECRET), uses_remaining=1,
            source_id=c.source_id, expires_turn=c.state.turn),),
        TRAPPER: trapper, POGO: pogo,
        CLOCKER: lambda c: (RandomBuffStoredMinion(c.player_id, attack=1, health=1,
            query=PoolQuery(tribes_any=('mech',)), source_id=c.source_id, tribe_basis='current'),),
        SLITHERSPEAR: slitherspear,
        JOUSTER: lambda c: (Joust(c.player_id, PREFIX+'joust_reward', c.source_id),),
        'joust_reward': joust_reward,
    }
    for cid, body in bodies.items():
        registry.register_behavior(PREFIX+cid, body)
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']
        if (raw['type'] != 'MINION' or raw['collectible'] is not True or raw['cost'] != 1 or
                type(raw['attack']) is not int or type(raw['health']) is not int):
            raise TargetValidationError('Historical grant lost its complete printed minion body')
        fields = {}
        if cid == ASHTONGUE:
            fields['triggers'] = (TriggerSpec('damage_dealt', PREFIX+cid),)
        elif cid == SLITHERSPEAR:
            fields['triggers'] = (TriggerSpec('spell_cast_finished', PREFIX+cid),)
        else:
            fields['deathrattle' if cid == TRAPPER else 'battlecry'] = PREFIX+cid
        if cid in (GUARDIAN, ROCKET, ETHEREAL):
            fields['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE, (Zone.BOARD,), (CardType.MINION,))
        if cid == CLOCKER:
            fields['keywords'] = (Keyword.DIVINE_SHIELD,)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1,
            attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
