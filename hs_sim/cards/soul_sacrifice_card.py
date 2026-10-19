"""Soul Immolation installs or improves the existing physical Collapsing Star."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import GrantHealthRule, ReplaceHeroPower
from hs_sim.engine.health_rules import power_damage_rule
from hs_sim.engine.model import CardDefinition, CardType, HeroPowerReference, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT='JAIL_EVENT_101'; STAR='JAIL_EVENT_101hp'; BODY='cards.soul_sacrifice.play'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/soul-sacrifice-v1.json'
BATCH_HASH='6a1e39c4efb56b869ced4ad295fe60aaa0ead2575fb190555f175b49eb860f46'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(ROOT,)
            or tuple(x['record']['id']for x in data['existing_dependencies'])!=(STAR,)
            or data['dependencies'] or data['evidence_only'] or any(
                canonical_digest(x['record'])!=x['record_sha256']
                for key in ('cards','existing_dependencies')for x in data[key])):
        raise TargetValidationError('Soul Immolation requires its complete original spell and power source')
    return data


def register_soul_sacrifice_card(registry):
    data=load_batch()
    if canonical_digest(asdict(registry.card(STAR)))!=data['existing_power_definition_sha256']:
        raise TargetValidationError('Soul Immolation must reuse the unchanged original Collapsing Star')

    def play(c):
        power=c.state.entities.get(c.state.players[c.player_id].hero_power_id)
        if power is not None and power.card_id==STAR:
            return (GrantHealthRule(power.id,power_damage_rule(),c.source_id),)
        reference=None if power is None else HeroPowerReference.capture(power)
        return (ReplaceHeroPower(c.player_id,STAR,reference,source_id=c.source_id),)

    registry.register_behavior(BODY,play)
    raw=data['cards'][0]['record']
    if raw['type']!='SPELL' or raw['cost']!=2 or raw['tags'].get('SPELL_SCHOOL')!=6:
        raise TargetValidationError('Soul Immolation changed its original two-mana Shadow face')
    card=CardDefinition(ROOT,raw['name'],CardType.SPELL,cost=2,spell_school=SpellSchool.SHADOW,
        on_play=BODY,metadata=replace(metadata_from_record(raw),deck_identity=ROOT))
    registry.register_card(card)
    if ROOT not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
