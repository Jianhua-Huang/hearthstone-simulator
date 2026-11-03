"""A fixed original summon group followed by ordinary bound forced attacks."""
from .runtime_copy import deepcopy
from dataclasses import dataclass,replace

from .effects import Effect,ForceAttack,_integer
from .model import BoardPresenceReference,CardType,Zone,_name,validate_combat_relation
from .original_summon_groups import ordered_recipients
from .owner_turns import validate_accepted_prefix
from .registry import RuleContext


@dataclass(frozen=True)
class SummonAttackProfile:
    card_id:str
    token_id:str
    count:int
    combat_relation:str='opponent'
    request_card_ids:tuple[str,...]=()
    target_policy:str='original'

    def __post_init__(self):
        _name(self.card_id,'summon attack spell');_name(self.token_id,'summon attack token')
        _integer(self.count,'original summon attack requests',1)
        validate_combat_relation(self.combat_relation)
        if self.target_policy not in ('original','lowest_health_enemy_if_no_deck_minions','opponent_played_minion'):
            raise ValueError('Unsupported original summon attack target policy')
        if type(self.request_card_ids) is not tuple:
            raise ValueError('Fixed summon attacks require an immutable ordered request pattern')
        for cid in self.request_card_ids:_name(cid,'original summon attack material')
        if self.request_card_ids and (len(self.request_card_ids)!=self.count or self.request_card_ids[0]!=self.token_id):
            raise ValueError('Fixed summon attack pattern differs from its original count or first face')
        if self.target_policy=='original' and self.request_card_ids:
            raise ValueError('Original targeted summon attacks retain their one repeated face')
        if self.target_policy=='lowest_health_enemy_if_no_deck_minions' and self.combat_relation!='opponent':
            raise ValueError('Lowest Health enemy attacks require the opponent combat relation')

    @property
    def card_ids(self):
        return self.request_card_ids or (self.token_id,)*self.count


def validate_profile(registry,profile):
    if type(profile)is not SummonAttackProfile:raise ValueError('Typed fixed summon attack profile required')
    profile.__post_init__();card=registry.card(profile.card_id);token=registry.card(profile.token_id)
    if(card.kind!=CardType.SPELL or card.choice_only or card.ongoing_effect_id is not None or
            card.quest is not None or token.kind!=CardType.MINION or token.choice_only):
        raise ValueError('Fixed summon attacks require a native spell and physical minion')
    if profile.target_policy=='opponent_played_minion':
        if (card.secret is None or card.on_play is not None or card.secret.events!=('card_played',) or
                card.secret.turn!='opponent' or card.targeting is not None or profile.request_card_ids):
            raise ValueError('Played-minion summon attacks require an original opponent-played Secret')
    elif card.on_play is None or card.secret is not None:
        raise ValueError('Fixed spell-body summon attacks require an ordinary native spell')
    for cid in profile.card_ids:
        material=registry.card(cid)
        if material.kind!=CardType.MINION or material.choice_only:
            raise ValueError('Fixed summon pattern requires complete physical minion faces')
    if profile.target_policy=='lowest_health_enemy_if_no_deck_minions' and card.targeting is not None:
        raise ValueError('Automatic minimum-Health group cannot prescribe an action target')


def played_minion(state,event,player_id):
    from .play_history import play_record
    if event is None or event.kind!='card_played':
        raise ValueError('Secret summon attacks require their original completed minion event')
    row=play_record(state,dict(event.data).get('play_id'))
    if (not row.completed or row.countered or row.interrupted or row.kind!=CardType.MINION or
            row.player_id==player_id or row.minion_result!='summoned' or row.minion_entry is None or
            (row.source_id,row.player_id)!=(event.source_id,event.player_id) or row.turn!=state.turn or
            not row.action<=event.action<=state.action_number):
        raise ValueError('Secret summon attacks borrowed another physical minion hand play')
    return row


def profile_for(registry,c):
    if type(c)is not RuleContext:raise ValueError('Original summon attacks require their original native context')
    source=c.state.entities.get(c.source_id)
    profile=None if source is None else registry.summon_attack_profiles.get(source.card_id)
    if profile is not None and profile.target_policy=='opponent_played_minion':
        validate_profile(registry,profile)
        if c.cast is not None or source.zone!=Zone.GRAVEYARD or source.controller!=c.player_id:
            raise ValueError('Secret summon attacks require their original revealed physical source')
        played_minion(c.state,c.event,c.player_id)
        return profile
    cast=c.cast
    if(cast is None or cast not in c.state.cast_history or cast.source_id!=c.source_id or cast.player_id!=c.player_id or
            cast.completed or cast.interrupted or not cast.payload_started):
        raise ValueError('Original summon attacks lost the active physical spell')
    profile=registry.summon_attack_profiles.get(cast.card_id)
    if profile is None:raise ValueError('Unregistered original summon attack source')
    validate_profile(registry,profile);return profile


@dataclass(frozen=True)
class AttackSummonedGroup(Effect):
    original:RuleContext
    target:BoardPresenceReference|None=None

    def __post_init__(self):
        if type(self.original)is not RuleContext or self.target is not None and type(self.target)is not BoardPresenceReference:
            raise ValueError('Original summon attacks require native context and target residence')
        if self.target is not None:self.target.__post_init__()


def validate_request(registry,effect,state=None,events=None):
    effect.__post_init__();old=effect.original;profile=profile_for(registry,old)
    if profile.target_policy=='opponent_played_minion':
        row=played_minion(old.state,old.event,old.player_id)
        if effect.target!=row.minion_entry.reference:
            raise ValueError('Secret summon attacks changed the original played minion residence')
        if events is not None:
            from .hero_health_history import effective_events
            actual=effective_events(events)
            if sum(e==old.event for e in actual)!=1 or not any(e.kind=='secret_revealed' and
                    (e.source_id,e.player_id,e.action)==(old.source_id,old.player_id,old.state.action_number) and
                    e.sequence>old.event.sequence for e in actual):
                raise ValueError('Secret summon attacks lost their actual reveal after the original minion play')
    elif profile.target_policy=='original':
        if (effect.target is None or old.target_id!=effect.target.entity_id or
                BoardPresenceReference.capture(old.state,old.target_id)!=effect.target):
            raise ValueError('Summon attacks changed their original accepted target')
    elif effect.target is not None or old.target_id is not None:
        raise ValueError('Automatic minimum-Health group borrowed an explicit original target')
    if state is not None:validate_accepted_prefix(old.state,state,registry)


def execute(r,effect):
    validate_request(r.registry,effect,r.state,r.game.events);old=effect.original;profile=profile_for(r.registry,old)
    current=replace(old,state=deepcopy(r.state),cast=None if old.cast is None else r.state.cast_history[old.cast.id-1])
    ids=ordered_recipients(old,current,r.registry,profile.card_ids)
    if profile.target_policy=='lowest_health_enemy_if_no_deck_minions':
        if any(r.state.entities[eid].kind==CardType.MINION for eid in r.player(old.player_id).deck):return ()
        from .forced_attack_sequences import AttackLowestHealthEnemy
        return tuple(AttackLowestHealthEnemy(BoardPresenceReference(
            r.state.successful_summon_history[i-1].entity_id,
            r.state.successful_summon_history[i-1].minion.entered_order),old.player_id,old.source_id)for i in ids)
    return tuple(ForceAttack(BoardPresenceReference(r.state.successful_summon_history[i-1].entity_id,
        r.state.successful_summon_history[i-1].minion.entered_order),effect.target,
        combat_relation=profile.combat_relation)for i in ids)


def register(mechanics):mechanics.register(AttackSummonedGroup,execute)
