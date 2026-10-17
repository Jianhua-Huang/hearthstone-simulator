"""Three actual Silvermoon faces share native location and health executors."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption, Damage, RequestChoice
from hs_sim.engine.excess_damage import DamageExcessToHero
from hs_sim.engine.locations import AdvanceLocationFace, LocationFaceReference
from hs_sim.engine.model import CardDefinition, CardType, DamageKind
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference, live_minion
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

FACES = ('TIME_810', 'TIME_810t1', 'TIME_810t2')
PREFIX = 'cards.silvermoon_location.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-silvermoon-locations-v1.json'
BATCH_HASH = '3e8f0f6f6860e6e93c5305b91cbd9c9db5804291270ea67000165144487ed763'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != FACES or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'])):
        raise TargetValidationError('Silvermoon requires all three complete reviewed location faces')
    return data


def register_native_silvermoon_location_cards(registry):
    def advance(ref, source):
        index = FACES.index(ref.card_id)
        return () if index == 2 else (AdvanceLocationFace(ref, FACES[index+1], source),)

    def body(c):
        ref = LocationFaceReference.capture(c.state, c.source_id)
        if ref.card_id not in FACES:
            raise ValueError('Silvermoon requires its original actual location face')
        targets = minions(c, registry, 3-c.player_id)
        if ref.card_id == FACES[2] and targets:
            health = min(c.state.entities[i].health for i in targets)
            targets = tuple(i for i in targets if c.state.entities[i].health == health)
        if not targets:
            return advance(ref, c.source_id)
        options = tuple(ChoiceOption(json.dumps(dict(location=asdict(ref),
            target=asdict(MinionReference.capture(c.state.entities[i]))), sort_keys=True),
            'Original enemy minion') for i in targets)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
                              sample_size=1, on_select=PREFIX + 'selected'),)

    def selected(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
            raise ValueError('Silvermoon lost its actual one sampled automatic material')
        material = json.loads(c.choice.choice.options[0].id)
        if type(material) is not dict or set(material) != {'location', 'target'}:
            raise ValueError('Silvermoon changed its original material fields')
        ref = LocationFaceReference(**material['location'])
        target = MinionReference(**material['target'])
        ref.__post_init__(); target.__post_init__()
        if ref.card_id not in FACES or (ref.entity_id, ref.controller_id) != (c.source_id, c.player_id):
            raise ValueError('Silvermoon borrowed another source face or original player')
        if ref.card_id == FACES[0]:
            damage = () if live_minion(c.state, target) is None else (
                Damage(target.entity_id, 5, c.source_id, DamageKind.EFFECT),)
        else:
            damage = (DamageExcessToHero(target, 5, c.source_id, kind=DamageKind.EFFECT),)
        return (*damage, *advance(ref, c.source_id))

    registry.register_behavior(PREFIX + 'body', body)
    registry.register_behavior(PREFIX + 'selected', selected)
    for row in load_batch()['cards']:
        raw = row['record']
        definition = CardDefinition(raw['id'], raw['name'], CardType.LOCATION, cost=raw['cost'],
            durability=raw['health'], on_use=PREFIX + 'body', metadata=metadata_from_record(raw))
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
