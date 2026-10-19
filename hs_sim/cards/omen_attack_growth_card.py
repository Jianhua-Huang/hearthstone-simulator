"""Omen's complete face; attached native growth feeds ordinary area damage."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Keyword, NativeDeathrattleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'EDR_421'
PREFIX = 'cards.omen_attack_growth.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/omen-attack-growth-v1.json'
BATCH_HASH = '46a037e56bf7040e3dabc8e08c4ab2c49b2c91f6be32fab37fbcc8f648db42c4'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or any(data[k] for k in
            ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Omen requires his complete reviewed original face')
    row = data['cards'][0]
    raw = row['record']
    if (canonical_digest(raw) != row['record_sha256'] or
            (raw['type'],raw['cost'],raw['attack'],raw['health']) != ('MINION',10,6,12) or
            any(raw['tags'].get(t) != 1 for t in ('RUSH','WINDFURY','DEATHRATTLE','TAG_SCRIPT_DATA_NUM_1'))):
        raise TargetValidationError('Omen lost his original body, keywords or initial damage')
    return data


def register_omen_attack_growth_card(registry):
    raw = load_batch()['cards'][0]['record']
    def burst(c):
        memory = None if c.deathrattle is None else c.deathrattle.ability.deathrattle_memory
        if memory is None or memory.spec.kind != 'attack_damage_growth':
            raise UnsupportedDefinitionError('Omen requires his original accepted Deathrattle damage material')
        enemy = c.state.players[3-c.player_id]
        amount = raw['tags']['TAG_SCRIPT_DATA_NUM_1']+memory.growth_steps
        return (DamageBatch(tuple(Damage(i,amount,c.source_id,DamageKind.MINION_ABILITY)
            for i in (enemy.hero_id,*enemy.board))),)
    registry.register_behavior(PREFIX+'burst',burst)
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=10,attack=6,health=12,
        keywords=(Keyword.RUSH,Keyword.WINDFURY),deathrattle=PREFIX+'burst',
        native_deathrattle=NativeDeathrattleSpec('attack_damage_growth'),metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
