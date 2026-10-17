"""Complete reachable reward, artwork, character-grant and power dependencies."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.adapt import CHOICE_IDS, PLANT_ID
from hs_sim.engine.adapt_memory import recipe, validate_options
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, DamageBatch, GrantDeathrattle,
    GrantKeyword, GrantTrigger, RandomDamage, RefreshHeroPower, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.jade import CLASSIC, VERSION, JadeGolemFamily
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, EndTurnSpec,
    HeroPowerReference, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.play_history import starting_deck_identity
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import (BuffCapturedMinion, GrantCapturedDeathrattle,
    GrantCapturedKeyword, MinionReference, live_minion)
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack, living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, deathrattle_position

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p71-v1.json'
BATCH_HASH = '6c7f3eeaf52930e2acaafd4111c54f752b406f79ded5682c7952d975a8f02b74'
PORTAL_SPELL, PORTAL, GALVADON = 'UNG_829t1', 'UNG_829t2', 'UNG_954t1'
JADES = ('CFM_712_t01', 'CFM_712_t04', 'CFM_712_t07', 'CFM_712_t20')
AVATAR, STAR, SHELL, IMP = 'TIME_209t2', 'JAIL_EVENT_101hp', 'TLC_513hp', 'UNG_829t3'
COLLECTIBLE_ROOTS = ()
DEPENDENCIES = (PORTAL_SPELL, PORTAL, GALVADON, *JADES, AVATAR, STAR, SHELL)
ROOTS = DEPENDENCIES
SOURCE_ROOTS = ('TLC_602', 'TIME_209', 'JAIL_504', 'JAIL_EVENT_101', 'TLC_513')
PREFIX = 'cards.simple_followup_p71.'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['cards'] or d['collectible_candidate_roots'] or d['skipped']
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES
            or tuple(d['source_candidate_roots']) != SOURCE_ROOTS):
        raise TargetValidationError('P71 requires its complete dependency-only source scope')
    if any(canonical_digest(x['record']) != x['record_sha256'] for key in
            ('dependencies', 'existing_dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('P71 complete original raw record changed')
    return d


def automatic(c, material, callback):
    return RequestChoice(c.player_id, (ChoiceOption(json.dumps(material, sort_keys=True), 'Original material'),),
        c.source_id, min_count=0, max_count=0, on_select=PREFIX + callback)


def original(c):
    if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
        raise ResolutionError('P71 callback lost its complete original material')
    return json.loads(c.choice.choice.options[0].id)


def register_simple_followup_p71_cards(registry):
    d = load_batch()
    for cid, pin in d['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin['sha256']:
            raise TargetValidationError('P71 requires its complete original dependency: ' + cid)

    def portal_spell(c):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(PORTAL),), SummonCause.capture(c)),)

    def portal(c):
        request = SummonByCard(c.player_id, (SummonEntryMaterial(IMP),), SummonCause.capture(c))
        return request, request

    def galvadon(c):
        return (automatic(c, dict(reference=asdict(MinionReference.capture(c.source)), remaining=5), 'adapt_next'),) if living_source(c) else ()

    def adapt_next(c):
        m = original(c); ref = MinionReference(**m['reference'])
        if m['remaining'] <= 0 or live_minion(c.state, ref) is None: return ()
        validate_options(registry)
        target = live_minion(c.state, ref)
        request = RequestChoice(c.player_id, tuple(ChoiceOption(cid, registry.card(cid).name,
            (recipe(c.player_id, c.source_id, target, cid),), card_id=cid) for cid in CHOICE_IDS),
            c.source_id, prompt='选择一项进化', sample_size=3)
        options = []
        for option in request.options:
            guarded = []
            for effect in option.effects:
                if type(effect) is Buff:
                    guarded.append(BuffCapturedMinion(ref, effect.attack, effect.health, effect.source_id))
                elif type(effect) is GrantKeyword:
                    guarded.append(GrantCapturedKeyword(ref, effect.keyword, effect.source_id,
                        effect.expires_turn, effect.duration))
                elif type(effect) is GrantDeathrattle:
                    guarded.append(GrantCapturedDeathrattle(ref, PREFIX + 'spores', effect.source_id))
                else:
                    raise ResolutionError('Galvadon encountered an unsupported native Adapt recipe')
            options.append(replace(option, effects=tuple(guarded)))
        return replace(request, options=tuple(options)), automatic(c, dict(m, remaining=m['remaining']-1), 'adapt_next')

    def spores(c):
        p = deathrattle_position(c); cause = SummonCause.capture(c)
        return (SummonByCard(c.player_id, (SummonEntryMaterial(PLANT_ID),), cause, position=p),
            SummonByCard(c.player_id, (SummonEntryMaterial(PLANT_ID),), cause, position=None if p is None else p+1))

    def avatar(c):
        target = c.state.entities.get(c.target_id)
        if target is None: return ()
        material = (dict(minion=asdict(MinionReference.capture(target))) if target.kind == CardType.MINION else
            dict(hero=target.id, player=c.player_id))
        material['turn'] = c.state.turn
        return (GrantTrigger(target.id, 'attack_finished', PREFIX + 'avatar_damage', c.source_id,
                    expires_turn=c.state.turn), automatic(c, material, 'avatar_buff'))

    def avatar_buff(c):
        m = original(c)
        if 'minion' in m:
            target = live_minion(c.state, MinionReference(**m['minion']))
        else:
            target = c.state.entities.get(m['hero'])
            if target is None or (target.id, target.controller, target.zone) != (
                    c.state.players[m['player']].hero_id, m['player'], Zone.HERO) or target.health <= 0:
                return ()
        return (Buff(target.id, 2, 0, c.source_id, expires_turn=m['turn']),) if target is not None else ()

    def avatar_damage(c):
        row = completed_attack(c)
        if row is None or row.declaration.source_id != c.source_id: return ()
        kind = DamageKind.MINION_ABILITY if c.source.kind == CardType.MINION else DamageKind.EFFECT
        return (DamageBatch(tuple(Damage(i, 2, c.source_id, kind) for i in characters(c, registry, 3-c.player_id))),)

    def star(c):
        return (RandomDamage(characters(c, registry, 3-c.player_id), 2, c.source_id, DamageKind.HERO_POWER),)

    def star_refresh(c):
        if (c.event is None or c.event.player_id != c.player_id or
                c.source_id not in c.state.players[c.player_id].hero_power_ids or c.source.zone != Zone.HERO_POWER):
            return ()
        target = c.state.entities.get(c.event.target_id)
        return (RefreshHeroPower(c.player_id, HeroPowerReference.capture(c.source)),) if target is not None and has_any_tribe(
            registry, target, ('demon',)) else ()

    def shell(c):
        # Unknown Scenario origins remain explicit; the shared query does not
        # invent physical membership from original card names.
        starting_deck_identity(c.state)
        return (automatic(c, dict(remaining=2), 'shell_next'),)

    def shell_next(c):
        m = original(c)
        if m['remaining'] <= 0: return ()
        entities, _ = starting_deck_identity(c.state); original_ids = set(entities[c.player_id-1])
        options = tuple(ChoiceOption(json.dumps(dict(card=asdict(CardReference.capture(c.state.entities[i])),
            remaining=m['remaining']), sort_keys=True), 'Original nonstarting physical deck card')
            for i in c.state.players[c.player_id].deck if i not in original_ids)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'shell_draw'),) if options else ()

    def shell_draw(c):
        m = original(c); card = dict(m['card']); card['zone'] = Zone(card['zone'])
        return (MoveCard(CardReference(**card), c.player_id, Zone.HAND, draw=True, source_id=c.source_id),
            automatic(c, dict(remaining=m['remaining']-1), 'shell_next'))

    bodies = dict(portal_spell=portal_spell, portal=portal, galvadon=galvadon, adapt_next=adapt_next,
        spores=spores, avatar=avatar, avatar_buff=avatar_buff, avatar_damage=avatar_damage,
        star=star, star_refresh=star_refresh, shell=shell, shell_next=shell_next, shell_draw=shell_draw)
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    for row in d['dependencies']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kwargs = {}
        if cid == PORTAL_SPELL: kwargs['on_play'] = PREFIX + 'portal_spell'
        if cid == PORTAL:
            kwargs.update(permanent_dormancy=True, dormant_turns=None,
                dormant_triggers=(TriggerSpec('turn_ended', PREFIX + 'portal', EndTurnSpec()),))
        if cid == GALVADON: kwargs['battlecry'] = PREFIX + 'galvadon'
        if cid == AVATAR:
            kwargs.update(on_play=PREFIX + 'avatar', targeting=TargetSpec(zones=(Zone.HERO, Zone.BOARD),
                kinds=(CardType.HERO, CardType.MINION), relation='friendly'))
        if cid in (STAR, SHELL): kwargs['on_use'] = PREFIX + ('star' if cid == STAR else 'shell')
        if cid == STAR: kwargs['triggers'] = (TriggerSpec('minion_summoned', PREFIX + 'star_refresh'),)
        if kind == CardType.SPELL: kwargs['spell_school'] = SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))
        definition = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'] or 0, metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(definition)
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(definition))
    family = JadeGolemFamily(CLASSIC, VERSION, JADES)
    if CLASSIC not in registry.jade_families: registry.register_jade_family(family)
    elif registry.jade_families[CLASSIC] != family:
        raise TargetValidationError('P71 requires the complete original classic Jade artwork profile')
