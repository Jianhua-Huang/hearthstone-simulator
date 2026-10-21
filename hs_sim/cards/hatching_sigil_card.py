"""Sigil of Hatching shares the existing player clock and fixed summon group."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword, PlayerEffectSpec, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, TOKEN = 'BE_873', 'BE_873t'
PROGRAM = 'cards.hatching_sigil'
EXPIRE = PROGRAM+'.expire'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/hatching-sigil-v1.json'
BATCH_HASH = '1fc2ef02a1cd50dacec3fefdc8a3a3a45f6abe261129403cffcf08634759953a'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['dependencies']) != (TOKEN,) or
            any(data[k] for k in ('existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards']+data['dependencies'])):
        raise TargetValidationError('Hatching Sigil lost its complete original root and Shredclaw')
    return data


def register_hatching_sigil_card(registry):
    data = load_batch(); raw = data['cards'][0]['record']; token = data['dependencies'][0]['record']
    if ((raw['type'], raw['cost'], raw['tags'].get('CLASS'), raw['tags'].get('SPELL_SCHOOL'), raw['tags'].get('SIGIL')) !=
            ('SPELL', 4, 14, 6, 1) or
            (token['type'], token['cost'], token['attack'], token['health'], token['tags'].get('RUSH'),
                token['tags'].get('CARDRACE'), token['collectible']) != ('MINION', 2, 3, 1, 1, 20, False)):
        raise TargetValidationError('Hatching Sigil requires its actual Shadow Sigil and 3/1 Rush Beast')
    def expire(c):
        instance = c.player_effect
        if (instance is None or instance.spec_id != PROGRAM or instance.source_id != c.source_id or
                c.event is None or c.event.kind != 'player_effect_expired' or
                (c.event.source_id, c.event.player_id) != (c.source_id, c.player_id)):
            raise TargetValidationError('Hatching requires its actual original Sigil expiry')
        cause = SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(TOKEN),), cause) for _ in range(3))
    registry.register_behavior(EXPIRE, expire)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, CARD, kind='sigil', duration=1,
        tick_event='turn_started', on_expire=EXPIRE))
    for card in (CardDefinition(TOKEN, token['name'], CardType.MINION, cost=2, attack=3, health=1,
            keywords=(Keyword.RUSH,), metadata=metadata_from_record(token)),
            CardDefinition(CARD, raw['name'], CardType.SPELL, cost=4, spell_school=SpellSchool.SHADOW,
                ongoing_effect_id=PROGRAM, metadata=metadata_from_record(raw))):
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
