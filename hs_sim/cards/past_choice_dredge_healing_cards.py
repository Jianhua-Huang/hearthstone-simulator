"""Historical consumers of native branches, physical draws and next healing."""
import json
from pathlib import Path

from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.dredge import Dredge
from hs_sim.engine.model import CardDefinition, CardType, ChooseBranch, ChooseOneSpec, Keyword, PlayerEffectSpec, Zone
from hs_sim.engine.next_healing_conversion import UNTIL_USED_KIND
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference, DrawMatching, MoveCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record


REEF, PIPER, SURVEYOR, KVALDIR = 'DED_001', 'ETC_375', 'TSC_642', 'YOG_300'
LEAVES = (REEF, PIPER, SURVEYOR, KVALDIR)
SHARK_CHOICE, TURTLE_CHOICE, SHARK, TURTLE, BOTH, DRAW_CHOICE, DISCOVER_CHOICE = (
    'DED_001a', 'DED_001b', 'DED_001at', 'DED_001bt', 'DED_001c', 'ETC_375a', 'ETC_375b')
OPTION_RECORDS = (SHARK_CHOICE, TURTLE_CHOICE)
CHOICE_ONLY = (DRAW_CHOICE, DISCOVER_CHOICE)
DEPENDENCIES = LEAVES + (SHARK, TURTLE, BOTH, DRAW_CHOICE, DISCOVER_CHOICE)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_choice_dredge_healing.'
PROGRAM = PREFIX + 'next_healing'
POOL = 'constructed.cards'
BEAST = PoolQuery(tribes_any=('beast',))
DISCOVER_BEAST = PoolQuery(tribes_any=('beast',), collectible=True, class_mode='current')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-choice-dredge-healing-v1.json'
BATCH_HASH = '17db91a6a449c4bc4835b295f0003d7821ba363b239d1405ba732e4541874de9'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(d['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in d['dependencies']) != DEPENDENCIES or
            tuple(d['choice_only_ids']) != CHOICE_ONLY or
            d['official_face_unavailable_ids'] != [BOTH, DRAW_CHOICE, DISCOVER_CHOICE] or
            tuple(row['record']['id'] for row in d['evidence_only']) != OPTION_RECORDS or
            any(d[k] for k in ('cards', 'existing_dependencies', 'choice_only', 'skipped',
                'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in d['dependencies'] + d['evidence_only'])):
        raise TargetValidationError('Historical choices lost their full roots, forms or client-only descriptors')
    return d


def register_past_choice_dredge_healing_cards(registry):
    data = load_batch()
    raws = {row['record']['id']: row['record'] for row in data['dependencies'] + data['evidence_only']}
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, KVALDIR, kind=UNTIL_USED_KIND))

    def reef(c, form):
        return (TransformCapturedMinion(MinionReference.capture(c.source), form, c.source_id),) \
            if living_source(c) and c.source.card_id == REEF else ()

    def draw_beast(c):
        return (DrawMatching(c.player_id, BEAST, 'skip', source_id=c.source_id),)

    def discover_beast(c):
        return (DiscoverFromPool(c.player_id, POOL, DISCOVER_BEAST, source_id=c.source_id),)

    def selected_mech(c):
        entity = c.state.entities.get(c.target_id)
        if (entity is None or entity.zone != Zone.DECK or entity.controller != c.player_id or
                not has_any_tribe(registry, entity, ('mech',))):
            return ()
        return (MoveCard(CardReference.capture(entity), c.player_id, Zone.HAND, draw=True, source_id=c.source_id),)

    bodies = {
        SHARK_CHOICE: lambda c: reef(c, SHARK),
        TURTLE_CHOICE: lambda c: reef(c, TURTLE),
        REEF + ':combined': lambda c: reef(c, BOTH),
        DRAW_CHOICE: draw_beast,
        DISCOVER_CHOICE: discover_beast,
        PIPER + ':combined': lambda c: (*draw_beast(c), *discover_beast(c)),
        SURVEYOR: lambda c: (Dredge(c.player_id, source_id=c.source_id, on_select=PREFIX+'selected_mech'),),
        'selected_mech': selected_mech,
        KVALDIR: lambda c: (AddPlayerEffect(c.player_id, PROGRAM, c.source_id),),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX+name, body)
    for cid in DEPENDENCIES:
        raw = raws[cid]
        kind = CardType(raw['type'].lower())
        choice = cid in CHOICE_ONLY
        if (raw['collectible'] != (cid in LEAVES) or raw['cost'] != 1 or
                kind != (CardType.SPELL if cid in (DRAW_CHOICE, DISCOVER_CHOICE) else CardType.MINION)):
            raise TargetValidationError('Historical choices require their complete printed identities')
        fields = {}
        if cid in (REEF, PIPER):
            options = (SHARK_CHOICE, TURTLE_CHOICE) if cid == REEF else (DRAW_CHOICE, DISCOVER_CHOICE)
            fields['choose_one'] = ChooseOneSpec(tuple(ChooseBranch(i, raws[i]['name'], PREFIX+i) for i in options),
                ChooseBranch(cid+':combined', '兼得', PREFIX+cid+':combined'))
        elif cid in (SURVEYOR, KVALDIR):
            fields['battlecry'] = PREFIX+cid
        elif cid in (SHARK, TURTLE, BOTH):
            fields['keywords'] = tuple(k for tag, k in (('RUSH', Keyword.RUSH), ('TAUNT', Keyword.TAUNT))
                if raw['tags'].get(tag) == 1)
        card = CardDefinition(cid, raw['name'], kind, cost=0 if choice else 1,
            attack=raw['attack'] or 0, health=raw['health'] or 0, choice_only=choice,
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        if not choice:
            registry.register_pool_card(PoolCard.from_definition(card))
