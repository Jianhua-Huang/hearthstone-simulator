"""Three historical native Battlecries composed from ordinary effect writers."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.damage_history import hero_damage_taken
from hs_sim.engine.effects import Buff, ChoiceOption, Damage, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.hero_health_targets import HeroDamageTakenTargetProfile
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, DamageKind, TargetMode, TargetSpec, Zone
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.return_followups import ReturnCapturedMinion
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

STUNNER, SLINGER, WHELP = 'BT_711', 'DED_503', 'TOY_386'
DEPENDENCIES = (STUNNER, SLINGER, WHELP)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_conditional_battlecries.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-conditional-battlecries-v1.json'
BATCH_HASH = 'ee38fe6cfd1a453b618d3b2afec3b49476e0450c473d753f65358dae9f6a21c8'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(r['record']['id'] for r in data['dependencies']) != DEPENDENCIES or
            any(data[k] for k in ('cards','existing_dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['dependencies'])):
        raise TargetValidationError('Conditional historical Battlecries lost their complete original faces')
    return data


def register_past_conditional_battlecry_cards(registry):
    def own(c): return next(p for p in c.observation['players'] if p['id'] == c.player_id)
    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'secret','v1'), lambda c: bool(own(c)['secrets']))

    def stunner(c):
        if c.target_id is None or not c.state.players[c.player_id].secrets: return ()
        target = c.state.entities.get(c.target_id)
        if target is None or target.zone!=Zone.BOARD or target.kind!=CardType.MINION or not target.active or target.doomed or target.health<=0:
            return ()
        return (ReturnCapturedMinion(MinionReference.capture(target),
            c.source_id, to_owner=True, cost=CostSpec(delta=2)),)

    def slinger(c):
        amount = hero_damage_taken(c.state, c.player_id, turn=c.state.turn)
        return (Damage(c.target_id, amount, c.source_id, DamageKind.MINION_ABILITY),) if amount and c.target_id is not None else ()

    def rewards(c, ref):
        return (BuffStoredCard(ref, 1, 1, c.source_id), Buff(c.source_id, 1, 1, c.source_id))

    def whelp(c):
        held = tuple(e for i in c.state.players[c.player_id].hand for e in (c.state.entities[i],)
            if e.kind == CardType.MINION and has_any_tribe(registry, e, ('dragon',)))
        if not held: return ()
        if len(held) == 1: return rewards(c, CardReference.capture(held[0]))
        options = tuple(ChoiceOption(json.dumps(asdict(CardReference.capture(e)),sort_keys=True),
            registry.card(e.card_id).name, card_id=e.card_id, entity_id=e.id) for e in held)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX+'whelp_selected'),)

    def selected(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
            raise ResolutionError('Whelp requires its original one automatically sampled physical Dragon')
        row = json.loads(c.choice.choice.options[0].id); row['zone'] = Zone(row['zone'])
        return rewards(c, CardReference(**row))

    for key, body in (('stunner_now',stunner),('slinger_now',slinger),('whelp_now',whelp),('whelp_selected',selected)):
        registry.register_behavior(PREFIX+key, body)
    for key in ('stunner','slinger','whelp'):
        registry.register_behavior(PREFIX+key, lambda c,key=key: (InvokeBehavior(PREFIX+key+'_now',
            c.source_id,c.player_id,c.target_id,None if c.play is None else c.play.id),))
    expected = {STUNNER:(1,2,7),SLINGER:(2,1,9),WHELP:(2,1,12)}
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']
        if (raw['type']!='MINION' or raw['cost']!=1 or raw['collectible']is not True or
                raw['tags'].get('BATTLECRY')!=1 or
                (raw['attack'],raw['health'],raw['tags'].get('CLASS')) != expected[cid]):
            raise TargetValidationError('Conditional Battlecry lost its native one-cost minion face')
        key = {STUNNER:'stunner',SLINGER:'slinger',WHELP:'whelp'}[cid]
        kwargs = {} if cid==WHELP else dict(targeting=TargetSpec(TargetMode.IF_AVAILABLE,
            zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='any' if cid==STUNNER else 'enemy'),
            target_rule=PREFIX+'secret' if cid==STUNNER else 'any_entity')
        card = CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=raw['attack'],health=raw['health'],
            battlecry=PREFIX+key,metadata=metadata_from_record(raw),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_hero_health_target_profile(HeroDamageTakenTargetProfile(SLINGER))
