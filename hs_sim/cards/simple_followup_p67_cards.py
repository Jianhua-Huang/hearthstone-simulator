"""Complete Blood Fighter/King families and original hand, draw and cannon effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.cross_zone import TransformDefiningHandCard
from hs_sim.engine.deck_shuffles import ShuffleDeckCards
from hs_sim.engine.effects import (ChoiceOption, Draw, ForceAttack, InvokeBehavior,
    RequestChoice, ShuffleIntoDeck)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.fabled_decks import FabledSpec
from hs_sim.engine.health_loss import SetHeroHealth
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType, CostSpec,
    HandProgressSpec, Keyword, OpeningHook, Rarity, TriggerSpec, Zone)
from hs_sim.engine.physical_draw_groups import arrival_reference
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference, live_minion
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.temporary_cards import MakeHandCardTemporary
from hs_sim.engine.zones import (CardReference, DestroyStoredCard, DrawMatching, ModifyStoredCost, MoveCard)
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, deathrattle_position, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p67-v1.json'
BATCH_HASH = '7a3611b79298c2e14ab2cc9b894ceb3f9cd44abd31762895caf61f18832a7cc3'
LOGOSH, GARONA, CANNON, CATACOMBS, MORCHOK, SHIFTER = (
    'TIME_850', 'TIME_875', 'CAP_103', 'TLC_451', 'CATA_570', 'TIME_876')
BROLL, VALEERA, KING, KINGSLAYERS = 'TIME_850t', 'TIME_850t1', 'TIME_875t', 'TIME_875t1'
COLLECTIBLE_ROOTS = (LOGOSH, GARONA, CANNON, CATACOMBS, MORCHOK, SHIFTER)
DEPENDENCIES = (BROLL, VALEERA, KING, KINGSLAYERS)
ROOTS = COLLECTIBLE_ROOTS + DEPENDENCIES
FIGHTERS = (LOGOSH, BROLL, VALEERA)
PREFIX = 'cards.simple_followup_p67.'
CANNONEER = 'CAP_107t'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != COLLECTIBLE_ROOTS
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES
            or tuple(x['record']['id'] for x in d['existing_dependencies']) != (CANNONEER,) or d['skipped']):
        raise TargetValidationError('P67 complete original scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256'] for k in
            ('cards', 'dependencies', 'existing_dependencies', 'evidence_only') for x in d[k]):
        raise TargetValidationError('P67 full original source changed')
    return d


def automatic(c, material, callback):
    return RequestChoice(c.player_id, (ChoiceOption(json.dumps(material, sort_keys=True), 'Original material'),),
        c.source_id, min_count=0, max_count=0, on_select=PREFIX + callback)


def original(c):
    if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
        raise ResolutionError('P67 continuation lost its complete original material')
    return json.loads(c.choice.choice.options[0].id)


def stored_entity(state, ref):
    e = state.entities.get(ref.entity_id)
    return e if e is not None and (e.controller, e.zone, e.card_id, e.zone_epoch) == (
        ref.player_id, ref.zone, ref.card_id, ref.zone_epoch) else None


def card_reference(material):
    return CardReference(**dict(material, zone=Zone(material['zone'])))


def register_simple_followup_p67_cards(registry):
    d = load_batch()
    pin = d['existing_dependency_definition_pins'][CANNONEER]
    if canonical_digest(asdict(registry.card(CANNONEER))) != pin['sha256']:
        raise TargetValidationError('P67 requires the complete original native Cannoneer')

    def blood(c, suffix):
        options = tuple(ChoiceOption(json.dumps(dict(card=asdict(CardReference.capture(c.state.entities[i])),
            position=deathrattle_position(c), cause=asdict(SummonCause.capture(c)), suffix=suffix), sort_keys=True),
            'Original physical Blood Fighter') for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id in FIGHTERS)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'blood_selected'),) if options else ()

    def blood_selected(c):
        m = original(c)
        # Recreate no cause fields: the original native context is carried in a
        # registered payload through its public decoder, including physical source and action.
        from hs_sim.engine.summon_quantities import from_dict
        return (SummonStoredCard(card_reference(m['card']), c.player_id, position=m['position'],
            cause=from_dict(SummonCause, m['cause']), on_summon=PREFIX + 'blood_' + m['suffix']),)

    def blood_delivered(c, suffix):
        ref = MinionReference.capture(c.state.entities[c.target_id])
        return BuffCapturedMinion(ref, 5, 5, c.source_id), automatic(c, dict(ref=asdict(ref), suffix=suffix), 'blood_reward')

    def blood_reward(c):
        m = original(c); ref = MinionReference(**m['ref'])
        actor = live_minion(c.state, ref)
        if actor is None: return ()
        if m['suffix'] != 'attack':
            return (GrantCapturedKeyword(ref, Keyword.TAUNT if m['suffix'] == 'taunt' else Keyword.ELUSIVE, c.source_id),)
        attacker = BoardPresenceReference.capture(c.state, actor.id)
        options = tuple(ChoiceOption(json.dumps(dict(attacker=asdict(attacker),
            target=asdict(BoardPresenceReference.capture(c.state, i)) if c.state.entities[i].kind == CardType.MINION else i),
            sort_keys=True), 'Original current enemy') for i in characters(c, registry, 3-c.player_id))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'blood_attack_selected'),) if options else ()

    def blood_attack(c):
        m = original(c); target = m['target']
        return (ForceAttack(BoardPresenceReference(**m['attacker']),
            BoardPresenceReference(**target) if isinstance(target, dict) else target),)

    def garona(c):
        king = next((c.state.entities[i] for i in c.state.players[3-c.player_id].hand
            if c.state.entities[i].card_id == KING), None)
        return (DestroyStoredCard(CardReference.capture(king), c.source_id,
            on_destroy=(automatic(c, dict(enemy=3-c.player_id), 'halve'),)),) if king is not None else ()

    def halve(c):
        hero = c.state.entities[c.state.players[original(c)['enemy']].hero_id]
        return (SetHeroHealth(hero.id, hero.health // 2, c.source_id),)

    def king_opening(c):
        return (ShuffleDeckCards(3-c.player_id, c.player_id,
            (MoveCard(CardReference.capture(c.source), 3-c.player_id, Zone.DECK, position='random', source_id=c.source_id),),
            c.source_id),)

    def king_battlecry(c):
        return Draw(c.player_id, 1, c.source_id), automatic(c, asdict(MinionReference.capture(c.source)), 'king_return')

    def king_return(c):
        e = live_minion(c.state, MinionReference(**original(c)))
        return (ShuffleDeckCards(c.player_id, c.player_id, (ShuffleIntoDeck(e.id, c.player_id),), c.source_id),) if e is not None else ()

    def weapon(c, firing):
        row = completed_attack(c)
        if row is None or row.source_kind != CardType.HERO or row.declaration.player_id != c.player_id: return ()
        if not firing:
            return tuple(DrawMatching(pid, PoolQuery(rarities=(Rarity.LEGENDARY,)), empty_deck='skip', source_id=c.source_id)
                for pid in (c.player_id, 3-c.player_id))
        return tuple(automatic(c, asdict(MinionReference.capture(c.state.entities[i])), 'fire')
            for i in minions(c, registry, c.player_id) if c.state.entities[i].card_id == CANNONEER)

    def fire(c):
        actor = live_minion(c.state, MinionReference(**original(c)))
        return (InvokeBehavior('cards.native_followup.cannon', actor.id, actor.controller),) if actor is not None else ()

    def catacombs(c):
        options = tuple(ChoiceOption(json.dumps(asdict(CardReference.capture(c.state.entities[i])), sort_keys=True),
            'Original private deck card') for i in c.state.players[c.player_id].deck
            if c.state.entities[i].card_id != CATACOMBS)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=min(3, len(options)), on_select=PREFIX + 'catacombs_offer'),) if options else ()

    def catacombs_offer(c):
        if c.choice is None or c.choice.selected_ids or not 1 <= len(c.choice.choice.options) <= 3:
            raise ResolutionError('Catacombs lost its original complete sampled physical offer')
        options = []
        for n, offered in enumerate(c.choice.choice.options, 1):
            ref = card_reference(json.loads(offered.id))
            material = dict(card=asdict(ref), previous=[row.id for row in c.state.hand_entries])
            options.append(ChoiceOption('zone-' + str(n), registry.card(ref.card_id).name,
                (MoveCard(ref, c.player_id, Zone.HAND, source_id=c.source_id),
                    automatic(c, material, 'temporary')), card_id=ref.card_id))
        return (RequestChoice(c.player_id, tuple(options), c.source_id),)

    def temporary(c):
        m = original(c); ref = card_reference(m['card'])
        entries = [row for row in c.state.hand_entries if row.id not in m['previous'] and
            (row.entity_id, row.player_id, row.card_id, row.from_zone) == (ref.entity_id, ref.player_id, ref.card_id, Zone.DECK)]
        if not entries: return ()
        first = entries[0]; current = CardReference(first.entity_id, first.player_id, Zone.HAND, first.card_id, first.zone_epoch)
        e = stored_entity(c.state, current)
        return (MakeHandCardTemporary(current, c.state.turn, source_id=c.source_id),) if e is not None and e.hand_entry_id == first.id else ()

    def draw_budget(c, budget):
        return Draw(c.player_id, 1, c.source_id), automatic(c, dict(budget=budget,
            previous=[row.id for row in c.state.draw_history], hand_cursor=len(c.state.hand_entries)), 'discount')

    def discount(c):
        m = original(c)
        rows = [row for row in c.state.draw_history if row.id not in m['previous']]
        if not rows or (rows[0].source_id, rows[0].player_id, rows[0].parent_id) != (c.source_id, c.player_id, None):
            raise ResolutionError('Morchok lost its original actual draw root')
        ref = arrival_reference(c.state, rows[0].id, m['hand_cursor'])
        e = stored_entity(c.state, ref) if ref is not None else None
        if e is None: return ()
        remainder = max(0, m['budget'] - quote_unselected_cost(c.state, registry, e).amount)
        work = (ModifyStoredCost(ref, CostSpec(delta=-m['budget']), c.source_id),)
        return (*work, automatic(c, dict(budget=remainder), 'draw_more')) if remainder else work

    def shifter(c):
        if c.trigger is None or c.trigger.kind != 'defining_hand_source':
            raise ResolutionError('Shapeshifter requires its original native defining source')
        material = dict(target=asdict(CardReference.capture(c.source)), binding=c.trigger.id)
        options = tuple(ChoiceOption(json.dumps(dict(material, card_id=c.state.entities[i].card_id), sort_keys=True),
            'Original opponent hand minion') for i in c.state.players[3-c.player_id].hand
            if c.state.entities[i].kind == CardType.MINION)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'shift_selected'),) if options else ()

    def shift_selected(c):
        m = original(c)
        return (TransformDefiningHandCard(card_reference(m['target']), m['card_id'], m['binding']),)

    bodies = dict(blood_logosh=lambda c:blood(c,'attack'), blood_broll=lambda c:blood(c,'taunt'),
        blood_valeera=lambda c:blood(c,'elusive'), blood_selected=blood_selected,
        blood_attack=lambda c:blood_delivered(c,'attack'), blood_taunt=lambda c:blood_delivered(c,'taunt'),
        blood_elusive=lambda c:blood_delivered(c,'elusive'), blood_reward=blood_reward,
        blood_attack_selected=blood_attack, garona=garona, halve=halve, king_opening=king_opening,
        king_battlecry=king_battlecry, king_return=king_return, cannon=lambda c:weapon(c,True),
        kingslayers=lambda c:weapon(c,False), fire=fire, catacombs=catacombs, catacombs_offer=catacombs_offer, temporary=temporary,
        morchok=lambda c:draw_budget(c,10), draw_more=lambda c:draw_budget(c,original(c)['budget']),
        discount=discount, shifter=shifter, shift_selected=shift_selected)
    # Attack selection and delivered-recipient callbacks have separate identities.
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    for item in (*d['cards'], *d['dependencies']):
        raw = item['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kw = {}
        if cid in FIGHTERS:
            kw.update(keywords=({LOGOSH:(Keyword.RUSH,), BROLL:(Keyword.TAUNT,), VALEERA:(Keyword.ELUSIVE,)}[cid]),
                deathrattle=PREFIX + {LOGOSH:'blood_logosh', BROLL:'blood_broll', VALEERA:'blood_valeera'}[cid])
        if cid in (GARONA, KING, MORCHOK): kw['battlecry'] = PREFIX + {GARONA:'garona', KING:'king_battlecry', MORCHOK:'morchok'}[cid]
        if cid == KING: kw['opening_hooks'] = (OpeningHook('before_deal', PREFIX + 'king_opening'),)
        if cid in (CANNON, KINGSLAYERS): kw['triggers'] = (TriggerSpec('attack_finished', PREFIX + ('cannon' if cid == CANNON else 'kingslayers')),)
        if cid == CATACOMBS: kw['on_play'] = PREFIX + 'catacombs'
        if cid == SHIFTER: kw['defining_hand_source'] = HandProgressSpec('event', 1, on_complete=PREFIX + 'shifter', repeat=True, event='turn_started')
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'] if raw['cost'] is not None else d['numeric_normalizations'][cid]['cost'],
            attack=raw['attack'] if kind in (CardType.MINION, CardType.WEAPON) else 0,
            health=raw['health'] if kind == CardType.MINION else 0, durability=raw['health'] if kind == CardType.WEAPON else 0,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), metadata=metadata_from_record(raw), **kw)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_fabled(FabledSpec(LOGOSH, (BROLL, VALEERA)))
    registry.register_fabled(FabledSpec(GARONA, (KING, KINGSLAYERS)))
