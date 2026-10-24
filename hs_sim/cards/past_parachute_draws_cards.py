"""Patches, original Parachutes and printed charged Pirates over shared executors."""
import json
from pathlib import Path
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.model import CardDefinition, CardType, CastWhenDrawnSpec, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

PATCHES, PARACHUTE, PIRATE = 'VAC_933', 'VAC_933t', 'VAC_926t'
DEPENDENCIES = (PATCHES, PARACHUTE, PIRATE)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_parachute_draws.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/past-parachute-draws-v1.json'
BATCH_HASH = 'd25a1ff6b127b8ec65cf9919793909e1cd939b664ad657931ac1b076fef99f8f'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['collectible_leaf_ids'] != [PATCHES] or
            tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES or
            any(d[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only',
                'skipped', 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in d['dependencies'])):
        raise TargetValidationError('Parachutes require all three full original source and recipe identities')
    return d


def register_past_parachute_draws_cards(registry):
    def shuffle(c):
        return shuffled(c, tuple(AddToDeck(c.player_id, PARACHUTE, source_id=c.source_id) for _ in range(6)))
    def summon(c):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(PIRATE),), SummonCause.capture(c)),)
    registry.register_behavior(PREFIX+'shuffle', shuffle)
    registry.register_behavior(PREFIX+'summon', summon)
    rows = {x['record']['id']: x['record'] for x in load_batch()['dependencies']}
    root, spell, pirate = (rows[c] for c in DEPENDENCIES)
    if ((root['cost'], root['attack'], root['health'], root['tags'].get('BATTLECRY')) != (1, 1, 1, 1) or
            (spell['type'], spell['cost'], spell['tags'].get('CASTS_WHEN_DRAWN')) != ('SPELL', 1, 1) or
            (spell['attack'], spell['health']) != (pirate['attack'], pirate['health']) or
            (pirate['type'], pirate['cost'], pirate['attack'], pirate['health'], pirate['tags'].get('CHARGE')) != ('MINION', 1, 1, 1, 1)):
        raise TargetValidationError('Parachutes lost their real six-shuffle source or one charged Pirate recipe')
    for cid, raw in rows.items():
        kwargs = dict(metadata=metadata_from_record(raw), cost=raw['cost'])
        if cid == PATCHES:
            kwargs.update(attack=1, health=1, battlecry=PREFIX+'shuffle')
        elif cid == PARACHUTE:
            kwargs.update(on_play=PREFIX+'summon', keywords=(Keyword.CASTS_WHEN_DRAWN,),
                cast_when_drawn=CastWhenDrawnSpec())
        else:
            kwargs.update(attack=1, health=1, keywords=(Keyword.CHARGE,))
        card = CardDefinition(cid, raw['name'], CardType(raw['type'].lower()), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
