"""Playable Mimiron with an explicit, user-approved community approximation."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path

from hs_sim.engine.costs import quote_generated_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, RequestChoice
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import (CardDefinition, CardType, ChoicePurpose, Keyword,
    PaymentType, Rarity, Resource)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = 'BE_588'
COLLECTIBLE_ROOTS = (ROOT,)
POLICY = 'mimiron-community-v1'
BODY = 'cards.mimiron.'+POLICY
DATA = Path(__file__).resolve().parents[2] / 'data/cards/mimiron-community-v1.json'
PIN = '2528e20448458fc614bc77aca94b9c86e13cb952c53531e59295b522c5cb2a26'


def load_policy():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    if (canonical_digest(data) != PIN or data['policy_id'] != POLICY or
            data['official_pool_complete'] is not False or
            data['official_ranking_verified'] is not False or
            canonical_digest(data['root']['record']) != data['root']['record_sha256'] or
            len(data['candidates']) != 13 or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['candidates'])):
        raise TargetValidationError('Mimiron community policy changed its reviewed scope or originals')
    return data


@dataclass(frozen=True)
class TechScore:
    card_id: str
    score: int
    quoted_cost: int
    payable_now: bool


def living_board(state, player_id):
    return tuple(e for i in state.players[player_id].board for e in (state.entities[i],)
        if e.kind == CardType.MINION and e.active and e.health > 0 and not e.doomed)


def value(entity):
    return max(1, entity.attack+entity.health)


def silence_value(registry, entity):
    if entity.silenced:
        return 0
    printed = registry.card(entity.card_id)
    buffs = max(0, entity.attack-printed.attack)+max(0, entity.max_health-printed.health)
    keywords = sum(k in entity.keywords for k in (
        Keyword.TAUNT, Keyword.REBORN, Keyword.LIFESTEAL, Keyword.WINDFURY))
    return buffs+3*keywords+3*bool(active_abilities(entity,'deathrattle'))+2*(Keyword.DIVINE_SHIELD in entity.keywords)


def scores(registry, state, player_id, *, max_board=7, policy=None):
    """Pure heuristic: public board/resources and own generated cost quotes only.

    It does not inspect either player's hidden hand/deck/Secret identities, use
    their original decklists, simulate plays or consume RNG/cost modifiers.
    """
    data = load_policy() if policy is None else policy
    own = living_board(state, player_id)
    enemy = living_board(state, 3-player_id)
    player = state.players[player_id]
    hero = state.entities[player.hero_id]
    enemy_hero = state.entities[state.players[3-player_id].hero_id]
    budgets = {PaymentType.MANA:player.mana, PaymentType.HEALTH:max(0,hero.health-1),
        PaymentType.OPPONENT_HEALTH:max(0,enemy_hero.health-1),
        PaymentType.ARMOR:hero.armor, PaymentType.CORPSES:player.resources[Resource.CORPSES]}
    enemy_silence = tuple(silence_value(registry,e) for e in enemy)
    legends = tuple(e for e in enemy if registry.card(e.card_id).metadata is not None and
        registry.card(e.card_id).metadata.rarity == Rarity.LEGENDARY)
    beasts = tuple(e for e in enemy if has_any_tribe(registry,e,('beast',)))
    locations = tuple(state.entities[i] for i in state.players[3-player_id].board
        if state.entities[i].kind == CardType.LOCATION)
    enemy_count = sum(state.entities[i].kind == CardType.MINION
        for i in state.players[3-player_id].board)
    utility = {
        'silence_one':6*max(enemy_silence,default=0),
        'battlecry_tax':7,
        'next_turn_tax':9,
        'defensive_taunt':10+min(20,sum(max(0,e.attack) for e in enemy)),
        'legendary_removal':6*max((value(e) for e in legends),default=0),
        'beast_removal':6*max((value(e) for e in beasts),default=0),
        'location_removal':24*len(locations),
        'silence_board':6*(sum(enemy_silence)-sum(silence_value(registry,e) for e in own)),
        'steal_minion':10*max((value(e) for e in enemy),default=0)
            if enemy_count >= 4 and len(player.board) < max_board else 0,
        'small_board_clear':6*(sum(value(e) for e in enemy if e.attack <= 2)-
            sum(value(e) for e in own if e.attack <= 2)),
        'armor_removal':4*enemy_hero.armor,
        'deck_cleanup':3,
        'anti_freeze':8*sum(value(e) for e in own if e.frozen),
    }
    result = []
    # Validate every fixed candidate even if it will not reach the top three.
    for row in data['candidates']:
        card = registry.card(row['card_id'])
        if card.kind != CardType.MINION or not card.hand_playable or card.choice_only:
            raise TargetValidationError('Mimiron requires every reviewed physical tech adapter')
        quote = quote_generated_cost(state,registry,player_id,card.id)
        score = utility[row['role']]+card.attack+card.health-2*quote.amount
        result.append(TechScore(card.id,score,quote.amount,quote.amount <= budgets[quote.payment]))
    return tuple(result)


def recommend(rows):
    # Stable sort preserves the versioned physical list order for equal scores.
    ranked = sorted(rows,key=lambda row:-row.score)
    selected = [row.card_id for row in ranked if row.payable_now][:2]
    selected.extend(row.card_id for row in ranked if row.card_id not in selected)
    return tuple(selected[:3])


def register_mimiron_community_card(registry):
    data = load_policy()
    for row in data['candidates']:
        if canonical_digest(asdict(registry.card(row['card_id']))) != row['definition_sha256']:
            raise TargetValidationError('Mimiron community policy changed a complete tech adapter')
    raw = data['root']['record']
    if (raw['id'],raw['type'],raw['cost'],raw['attack'],raw['health']) != (ROOT,'MINION',1,2,1):
        raise TargetValidationError('Mimiron lost its original one-cost 2/1 face')

    def body(c):
        if c.battlecry is None:
            raise ValueError('Mimiron requires its real accepted Battlecry')
        if not any(has_any_tribe(registry,e,('mech',)) for e in living_board(c.state,c.player_id)):
            return ()
        selected = recommend(scores(registry,c.state,c.player_id,policy=data))
        options = tuple(ChoiceOption('tech-'+str(n),registry.card(cid).name,
            (AddToHand(c.player_id,cid,c.source_id),),card_id=cid)
            for n,cid in enumerate(selected,1))
        return (RequestChoice(c.player_id,options,c.source_id,prompt='发现一张针对牌',
            purpose=ChoicePurpose.CARD_DISCOVERY),)

    registry.register_behavior(BODY,body)
    card = CardDefinition(ROOT,raw['name'],CardType.MINION,cost=1,attack=2,health=1,
        battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
