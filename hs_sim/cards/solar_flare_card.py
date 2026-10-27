"""Real Solar Flare reuses original board pricing and ordinary SPELL damage."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage,DamageBatch
from hs_sim.engine.model import BoardMinionCostSpec,CardDefinition,CardType,DamageKind,SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/solar-flare-elemental-price-v1.json'
BATCH_HASH = '7e3ac70117594650e6b2706f38362eee6c4959f3023bca02f986d65515718611'
CARD = 'GDB_305'
BODY = 'cards.solar_flare.native'
PROFILE = 'cost.board-friendly-elementals-v1'
COLLECTIBLE_ROOTS = ()


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['schema'] != 1 or
            tuple(r['record']['id'] for r in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped')) or
            data['board_price_profile'] != PROFILE or data['source_scope_bound'] is not False or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False):
        raise TargetValidationError('Solar Flare lost its complete original source or scope')
    if any(canonical_digest(r['record']) != r['record_sha256'] for r in data['cards']):
        raise TargetValidationError('Solar Flare changed its complete original face')
    return data


def register_solar_flare_card(registry):
    row = load_batch()['cards'][0];raw = row['record']
    if (raw['type'],raw['cost'],raw['collectible'],row['spell_school']) != ('SPELL',5,True,'fire'):
        raise TargetValidationError('Solar Flare requires its true 5-mana Fire spell')
    if CARD in registry.cards:raise TargetValidationError('Solar Flare cannot overwrite an original definition')
    card = CardDefinition(CARD,raw['name'],CardType.SPELL,cost=5,metadata=metadata_from_record(raw),
        spell_school=SpellSchool.FIRE,board_minion_cost=BoardMinionCostSpec('friendly',PROFILE),on_play=BODY)
    registry._validate_card(card)
    if CARD in registry.pool_cards and registry.pool_card(CARD) != PoolCard.from_definition(card):
        raise TargetValidationError('Solar Flare differs from original complete pool metadata')
    registry.register_behavior(BODY,lambda c:(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)
        for i in(c.state.players[3-c.player_id].hero_id,*minions(c,registry,3-c.player_id)))),))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
