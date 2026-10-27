"""Actual Heat Wave uses original Quickdraw and the shared target pipeline."""
import json
from pathlib import Path

from hs_sim.engine.captured_minion_spell_groups import DamageCapturedMinionGroup
from hs_sim.engine.effects import Damage,DamageBatch
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,SpellSchool,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/heatwave-inverse-quickdraw-v1.json'
BATCH_HASH = 'fa0ccc792ec2ce9826fc89ab494d043f78deeea2ce69c0052bcb67e0d0c5a5fa'
CARD = 'WW_377'
BODY = 'cards.heatwave.native'
COLLECTIBLE_ROOTS = ()


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['schema'] != 1 or
            tuple(r['record']['id'] for r in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped')) or
            data['target_condition'] != 'unless_quickdraw' or data['source_scope_bound'] is not False or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False):
        raise TargetValidationError('Heat Wave lost its full original source or declared scope')
    row = data['cards'][0]
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Heat Wave changed its complete original face')
    return data


def register_heatwave_card(registry):
    row = load_batch()['cards'][0];raw = row['record']
    if (raw['type'],raw['cost'],raw['collectible'],raw['tags'].get('QUICKDRAW'),row['spell_school']) != ('SPELL',2,True,1,'fire'):
        raise TargetValidationError('Heat Wave requires its true 2-mana Fire Quickdraw spell')
    if CARD in registry.cards:raise TargetValidationError('Heat Wave cannot overwrite an original definition')
    card = CardDefinition(CARD,raw['name'],CardType.SPELL,cost=2,metadata=metadata_from_record(raw),
        spell_school=SpellSchool.FIRE,keywords=(Keyword.QUICKDRAW,),on_play=BODY,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'),target_condition='unless_quickdraw')
    registry._validate_card(card)
    if CARD in registry.pool_cards and registry.pool_card(CARD) != PoolCard.from_definition(card):
        raise TargetValidationError('Heat Wave differs from its original complete pool metadata')

    def native(c):
        enemy = c.state.players[3-c.player_id]
        if c.spell_conditions.quickdraw:
            return (DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)
                for i in (enemy.hero_id,*minions(c,registry,3-c.player_id)))),)
        primary = c.state.entities.get(c.target_id)
        living = set(minions(c,registry,3-c.player_id))
        if primary is None or primary.id not in living:return ()
        index = enemy.board.index(primary.id)
        refs = tuple(MinionReference.capture(c.state.entities[i]) for i in enemy.board[max(0,index-1):index+2] if i in living)
        return (DamageCapturedMinionGroup(refs,(2,)*len(refs),c.source_id),)

    registry.register_behavior(BODY,native)
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
