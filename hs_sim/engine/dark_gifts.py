"""The ten constructed Dark Gifts; minion generation pools remain explicit.

Recipes use ordinary creation attachments, the shared Battlecry max policy,
and attributed minion copies. No card text is interpreted as executable code.
"""
from dataclasses import dataclass, replace
from .card_creation import CreatedMinionGrant, DiscoveryMinionGift
from .effects import Effect, _source
from .model import Keyword, SummonStats
from .zones import CardReference


LIVING_NIGHTMARE_BEHAVIOR = 'core.dark_gifts.living_nightmare'
DARK_GIFT_VERSION = 'constructed-dark-gifts-32.2-v1'

DARK_GIFTS = (
    DiscoveryMinionGift('EDR_100t', '起床怒气',
        CreatedMinionGrant(attack=3, keywords=(Keyword.LIFESTEAL,))),
    DiscoveryMinionGift('EDR_100t1', '休憩饱足',
        CreatedMinionGrant(attack=2, health=2, keywords=(Keyword.ELUSIVE,))),
    DiscoveryMinionGift('EDR_100t2', '短小利爪',
        CreatedMinionGrant(attack=-2), cost_delta=-2, min_attack=3),
    DiscoveryMinionGift('EDR_100t3', '衣甲厚实',
        CreatedMinionGrant(health=4, keywords=(Keyword.TAUNT,))),
    DiscoveryMinionGift('EDR_100t5', '活体梦魇',
        CreatedMinionGrant(special='living_nightmare')),
    DiscoveryMinionGift('EDR_100t6', '梦境行者',
        CreatedMinionGrant(keywords=(Keyword.CHARGE,))),
    DiscoveryMinionGift('EDR_100t7', '粗暴唤醒',
        CreatedMinionGrant(special='rude_awakening')),
    DiscoveryMinionGift('EDR_100t8', '甜美梦境',
        CreatedMinionGrant(attack=4, health=5), destination='deck_top'),
    DiscoveryMinionGift('EDR_100t9', '回荡恐怖',
        CreatedMinionGrant(keywords=(Keyword.REBORN,), reborn_policy='full_health_enchantments')),
    DiscoveryMinionGift('EDR_100t13', '鹰身人之爪',
        CreatedMinionGrant(keywords=(Keyword.DIVINE_SHIELD, Keyword.WINDFURY))),
)


def dark_gift_pool(generation_target, mode='experimental', *, pool_id='constructed.dark_gifts'):
    """Complete gift inventory, independent of the caller's minion pool."""
    from .pools import DiscoveryGiftPool
    return DiscoveryGiftPool(pool_id, DARK_GIFT_VERSION, generation_target, mode,
                             DARK_GIFTS, complete=True)


def living_nightmare(context):
    """A real paid or accepted generated whole-minion body, never a summon."""
    from .effects import CopyMinion
    from .model import CardType, Zone
    from .summon_quantities import SummonCause
    generated = context.play is None
    if generated:
        from .whole_card_physical import PhysicalReplayProgress
        progress = context.physical
        ledger = context.state.whole_card_replay_ledger
        if (type(progress) is not PhysicalReplayProgress or progress.phase != 'running'
                or progress.kind != CardType.MINION or progress.player_id != context.player_id
                or progress.source is None or progress.source.entity_id != context.source_id
                or not 1 <= progress.child_id <= len(ledger.children)):
            raise ValueError('Living Nightmare requires its actual whole-minion body')
        child = ledger.children[progress.child_id - 1]
        root = ledger.roots[child.root_id - 1]
        if (child.physical != progress or root.active_child_id != child.id
                or progress.activation is None or LIVING_NIGHTMARE_BEHAVIOR not in progress.on_play):
            raise ValueError('Living Nightmare borrowed another generated activation')
    elif context.play.kind != CardType.MINION:
        raise ValueError('Living Nightmare requires its physical minion play')
    source = context.source
    if source.zone != Zone.BOARD:
        return ()
    board = context.state.players[context.player_id].board
    position = board.index(source.id) + 1 if source.id in board else None
    from .model import BoardPresenceReference
    original = BoardPresenceReference.capture(context.state, source.id) if generated else source.id
    return (CopyMinion(original, context.player_id, position=position,
                       cause=SummonCause.capture(context), stats=SummonStats(2, 2),
                       allow_dormant=True),)


def public_gifts(entity):
    """Gift names only; attachment identities and their sources stay private."""
    by_id = {g.id: g for g in DARK_GIFTS}
    result = []
    prefix = 'created_minion_grant:'
    for attachment in entity.enchantments:
        if attachment.label.startswith(prefix):
            gift = by_id.get(attachment.label[len(prefix):])
            if gift is not None:
                result.append({'id': gift.id, 'name': gift.label})
    return result


@dataclass(frozen=True)
class GrantDarkGift(Effect):
    """Attach a real gift to an existing stored minion; the caller owns delivery."""
    card: CardReference
    gift_id: str
    source_id: int | None = None

    def __post_init__(self):
        if type(self.card) is not CardReference:
            raise ValueError('Stored Dark Gift requires a physical CardReference')
        self.card.__post_init__()
        if type(self.gift_id) is not str or self.gift_id not in {g.id for g in DARK_GIFTS}:
            raise ValueError('Unknown constructed Dark Gift')
        _source(self.source_id)


def grant_stored(r, effect):
    from types import SimpleNamespace
    from .card_creation import install
    from .lifecycle import attachment_id
    from .model import CardType, CostSpec, Enchantment, Zone
    from .zones import reference_entity
    effect.__post_init__()
    entity = reference_entity(r, effect.card)
    if entity is None:
        return
    if entity.kind != CardType.MINION or entity.zone not in (Zone.HAND, Zone.DECK):
        raise ValueError('Dark Gifts require a stored minion')
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ValueError('Dark Gift source does not exist')
    gift = next(g for g in DARK_GIFTS if g.id == effect.gift_id)
    face = SimpleNamespace(kind=entity.kind, attack=entity.attack, keywords=entity.keywords,
        battlecry=next((a.behavior_id for a in entity.abilities if a.kind == 'battlecry' and not a.consumed), None))
    if not gift.eligible(face):
        raise ValueError('Stored minion is not eligible for this Dark Gift')
    if gift.cost_delta:
        entity.enchantments.append(Enchantment(attachment_id(r.state), source_id=effect.source_id,
            cost=gift.cost_delta, label='dark_gift_cost:'+gift.id))
    install(r.state, entity, SimpleNamespace(spell_repeat=None, source_id=effect.source_id,
        minion_grant=replace(gift.grant, identity=gift.id)),resolver=r)
    r.refresh_auras()


def register(mechanics):
    mechanics.register(GrantDarkGift, grant_stored)
