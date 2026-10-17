"""Native Stegodon samples one original group, damages once, then freezes it."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption, Damage, DamageBatch, RequestChoice
from hs_sim.engine.kindred import repeat_components
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, KindredProfile
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import FreezeCapturedMinion, MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-kindred-group-v1.json'
BATCH_HASH = '53b335410d6405c75edc7ac11f513aa2afc3c1d490155779fcd91692f81bd303'
STEGODON = 'DINO_413'
PREFIX = 'cards.native_kindred_group.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (STEGODON,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'])):
        raise TargetValidationError('Native sampled Kindred source changed')
    return data


def original_group(c):
    if c.kindred is None or c.kindred.card_id != STEGODON or c.choice is None:
        raise ValueError('Stegodon requires its original sampled Kindred group')
    from hs_sim.engine.kindred import validate_prepared_choice
    validate_prepared_choice(c.kindred, c.choice)
    if len(c.choice.choice.options) > 2:
        raise ValueError('Stegodon sampled more than its original two minions')
    refs = tuple(MinionReference(**json.loads(o.id)) for o in c.choice.choice.options)
    if (len({r.entity_id for r in refs}) != len(refs) or
            any(r.player_id != 3-c.player_id or r.entity_id != o.entity_id or r.card_id != o.card_id
                for r, o in zip(refs, c.choice.choice.options))):
        raise ValueError('Stegodon group changed its original enemy allocation')
    return refs


def register_native_kindred_group_cards(registry):
    def prepare(c):
        if c.kindred is None or c.kindred.card_id != STEGODON:
            raise ValueError('Stegodon requires actual native Kindred acceptance')
        options = tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])), sort_keys=True),
            'Original enemy minion', card_id=c.state.entities[i].card_id, entity_id=i)
            for i in minions(c, registry, 3-c.player_id))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=min(2, len(options)) if options else None,
            on_select=PREFIX+'selected', kindred=c.kindred),)

    def selected(c):
        refs = original_group(c)
        hits = DamageBatch(tuple(Damage(r.entity_id, 2, c.source_id, DamageKind.MINION_ABILITY) for r in refs))
        return (hits, *repeat_components(c, prepared_choice=c.choice))

    def freeze(c):
        return tuple(FreezeCapturedMinion(ref, c.source_id) for ref in original_group(c))

    for name, body in (('wrapper', lambda c: ()), ('prepare', prepare), ('selected', selected), ('freeze', freeze)):
        registry.register_behavior(PREFIX+name, body)
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY'),
            raw['tags'].get('KINDRED')) != ('MINION', 4, 3, 4, 1, 1):
        raise TargetValidationError('Stegodon requires its complete actual native face')
    card = CardDefinition(STEGODON, raw['name'], CardType.MINION, cost=4, attack=3, health=4,
        metadata=metadata_from_record(raw), battlecry=PREFIX+'wrapper')
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_kindred_profile(KindredProfile(STEGODON, 'body', wrapper=PREFIX+'wrapper',
        prepare=PREFIX+'prepare', active=PREFIX+'freeze'))
