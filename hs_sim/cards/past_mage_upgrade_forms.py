"""Complete physical Flurry, Ruby Spellstone and Rune forms, plus Deep Breath."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.captured_minion_spell_groups import DamageCapturedMinionGroup
from hs_sim.engine.effects import Damage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.mana_ranks import ManaRankFamily
from hs_sim.engine.model import (CardClass, CardDefinition, CardType, DamageKind,
    HandActionSpec, HandProgressSpec, TargetSpec, Zone)
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_target_sequences import FreezeRandomEnemyMinions
from hs_sim.targets import TargetValidationError, canonical_digest
from .entry_native_cards import submitted_tribes
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-mage-upgrade-forms-v1.json'
BATCH_HASH = '1a3792c7ea39a21a4bb1bd8dbf364d66430166dab602276c3a29e20711544fba'
POLICY = 'cn37-local-past-mage-upgrade-forms-v1'
LEAVES = ('BAR_305','LOOT_103','TTN_477','ONY_006')
TOKENS = ('BAR_305t','BAR_305t2','LOOT_103t1','LOOT_103t2','TTN_477t1')
DEPENDENCIES = LEAVES + TOKENS
COLLECTIBLE_ROOTS = ()
FLURRY = ('BAR_305','BAR_305t','BAR_305t2')
RUBY = ('LOOT_103','LOOT_103t1','LOOT_103t2')
RUNE = ('TTN_477','TTN_477t1')
RANK = ManaRankFamily('cards.flurry.ranks-v1', FLURRY)
PREFIX = 'cards.past_mage_upgrade_forms.'
POOL = 'constructed.cards'
SPELLS = PoolQuery(kinds=(CardType.SPELL,), collectible=True)
MAGE_SPELLS = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='specified',
    classes=(CardClass.MAGE,), include_neutral=False)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or
            tuple(d['collectible_leaf_ids']) != LEAVES or tuple(d['new_token_ids']) != TOKENS or
            tuple(row['record']['id'] for row in d['dependencies']) != DEPENDENCIES or
            d['form_families'] != dict(ranked=list(FLURRY), spellstone=list(RUBY), forge=list(RUNE)) or
            len(d['official_observations']) != 18 or
            any(d[k] for k in ('cards','existing_dependencies','new_standard_roots',
                'source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in d['dependencies'])):
        raise TargetValidationError('Past Mage upgrades require all nine complete original forms')
    path = ROOT/d['reference_document']
    if (hashlib.sha256(path.read_bytes()).hexdigest() != d['reference_sha256'] or
            not set(LEAVES) <= set(json.loads(path.read_text(encoding='utf8'))['candidate_ids'])):
        raise TargetValidationError('Past Mage upgrades lost their complete original source scope')
    return d


def register_past_mage_upgrade_forms(registry):
    d = load_batch()
    prepared = []
    for row in d['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        if (raw['type'] != 'SPELL' or cid in registry.cards or cid in registry.pool_cards or
                canonical_digest(asdict(metadata_from_record(raw))) != canonical_digest(row['metadata'])):
            raise TargetValidationError('Past Mage upgrade changed an original spell face: '+cid)
        if cid in RUBY[:2]:
            fields['hand_progress'] = HandProgressSpec('event',2,RUBY[RUBY.index(cid)+1],
                event='card_committed',condition_id=PREFIX+'elemental',upgrade_cost_policy='clear_local')
        if cid == RUNE[0]: fields['hand_actions'] = (HandActionSpec('forge','forge',2,RUNE[1]),)
        if cid in RUNE: fields['targeting'] = TargetSpec()
        if cid == 'ONY_006': fields['targeting'] = TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        cost = d['numeric_normalizations'].get(cid,{}).get('cost',raw['cost'])
        card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=cost,on_play=PREFIX+cid,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card)
        prepared.append(card)

    def elemental(c):
        if c.event is None or c.event.kind != 'card_committed':
            raise ResolutionError('Ruby Spellstone requires the original committed hand play')
        record = play_record(c.state,dict(c.event.data)['play_id'])
        if (record.source_id,record.player_id) != (c.event.source_id,c.event.player_id):
            raise ResolutionError('Ruby Spellstone lost its original committed play identity')
        return (record.player_id == c.player_id and record.kind == CardType.MINION and
            record.source_id != c.source_id and submitted_tribes(record).matches_any(('elemental',)))

    def breath(c):
        primary = c.state.entities.get(c.target_id)
        if primary is None: return ()
        living = set(minions(c,registry,primary.controller))
        if primary.id not in living: return ()
        board = c.state.players[primary.controller].board; index = board.index(primary.id)
        refs = tuple(MinionReference.capture(c.state.entities[i])
            for i in board[max(0,index-1):index+2] if i in living)
        amount = 1 + sum(c.state.entities[i].kind == CardType.SPELL
            for i in c.state.players[c.player_id].hand if i != c.source_id)
        return (DamageCapturedMinionGroup(refs,(amount,)*len(refs),c.source_id),)

    for count,cid in enumerate(FLURRY,1):
        registry.register_behavior(PREFIX+cid,lambda c,count=count:
            (FreezeRandomEnemyMinions(c.player_id,c.cast.id,c.source_id,count),))
    for count,cid in enumerate(RUBY,1):
        registry.register_behavior(PREFIX+cid,lambda c,count=count:
            (GenerateFromPool(c.player_id,POOL,MAGE_SPELLS,count,source_id=c.source_id),))
    for count,cid in enumerate(RUNE,1):
        registry.register_behavior(PREFIX+cid,lambda c,count=count:
            (*tuple(Damage(c.target_id,3,c.source_id,DamageKind.SPELL) for _ in range(count)),
                GenerateFromPool(c.player_id,POOL,SPELLS,count,source_id=c.source_id)))
    registry.register_behavior(PREFIX+'ONY_006',breath)
    registry.register_trigger_condition(PREFIX+'elemental',elemental)
    for card in prepared:
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_mana_rank_family(RANK)
