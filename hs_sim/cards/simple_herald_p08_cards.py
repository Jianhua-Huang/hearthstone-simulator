"""P08 real location Herald, exact hand tokens and captured owner-end branches."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand, Draw
from hs_sim.engine.herald import Herald
from hs_sim.engine.imbue import Imbue
from hs_sim.engine.model import CardDefinition, CardType, EndTurnSpec, Keyword, SpellSchool, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-herald-p08-v1.json'
BATCH_HASH = 'df4aed74555a0e25aac68a8033549d47e5d7d51e1e27806a89b3a5291dc904d2'
SHRINE = 'CATA_492'
RITUAL = 'CATA_561'
GATHERER = 'EDR_871'
NOZDORMU = 'CATA_473'
BREEZLING = 'CATA_561t'
WISP = 'EDR_851t'
ROOTS = (SHRINE, RITUAL, GATHERER, NOZDORMU)
PREFIX = 'cards.simple_herald_p08.'
EXISTING = ('EDR_851p', WISP, 'CATA_725t', 'CATA_565t')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('P08 lost its complete reviewed source pin')
    if (tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['dependencies']) != (BREEZLING,) or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != EXISTING or data['skipped']):
        raise TargetValidationError('Unreviewed P08 roots or dependencies')
    for key in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only', 'skipped'):
        for row in data[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P08 complete source row changed')
    links = {cid: [o['face'].get('childIds', []) for o in data['official_observations']['observations']
                   if o['card_id'] == cid] for cid in (SHRINE, RITUAL, GATHERER)}
    if (links[SHRINE] != [[127045,125432,125433,125435]]*2 or
            links[RITUAL] != [[127071,125442,127584,125443,127053]]*2 or
            links[GATHERER] != [[114056,116450]]*2):
        raise TargetValidationError('P08 lost its complete exact official root associations')
    return data


def register_simple_herald_p08_cards(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('P08 requires its unchanged complete existing dependency')

    def nozdormu(c):
        result = []
        for eid in minions(c, registry, c.player_id):
            entity = c.state.entities[eid]
            original = MinionReference.capture(entity)
            result.append(BuffCapturedMinion(original, 3, 3, c.source_id) if Keyword.DIVINE_SHIELD in entity.keywords else
                          GrantCapturedKeyword(original, Keyword.DIVINE_SHIELD, c.source_id))
        return tuple(result)

    registry.register_behavior(PREFIX+'shrine', lambda c: (
        Herald(c.player_id,c.source_id), Draw(c.player_id,source_id=c.source_id)))
    registry.register_behavior(PREFIX+'ritual', lambda c: (
        Herald(c.player_id,c.source_id), AddToHand(c.player_id,BREEZLING,c.source_id), AddToHand(c.player_id,BREEZLING,c.source_id)))
    registry.register_behavior(PREFIX+'gatherer', lambda c: (
        AddToHand(c.player_id,WISP,c.source_id), Imbue(c.player_id,c.source_id)))
    registry.register_behavior(PREFIX+'nozdormu', nozdormu)
    for row in data['cards'] + data['dependencies']:
        raw = row['record'];cid = raw['id'];kind = CardType(raw['type'].lower());kwargs = {}
        if cid == SHRINE:
            if (raw['tags']['CARDTYPE'],raw['cost'],raw['health'],raw['tags'].get('HERALD')) != (39,4,2,1):
                raise TargetValidationError('Shrine requires its complete real Location face')
            kwargs.update(durability=2,on_use=PREFIX+'shrine')
        elif cid == RITUAL:
            if raw['tags'].get('SPELL_SCHOOL') != 4 or raw['tags'].get('HERALD') != 1:
                raise TargetValidationError('Ritual requires its actual Nature Herald spell face')
            kwargs.update(on_play=PREFIX+'ritual',spell_school=SpellSchool.NATURE,keywords=(Keyword.HERALD,))
        else:
            kwargs.update(attack=raw['attack'],health=raw['health'])
            if cid == GATHERER:kwargs['battlecry'] = PREFIX+'gatherer'
            elif cid == NOZDORMU:kwargs['triggers'] = (TriggerSpec('turn_ended',PREFIX+'nozdormu',EndTurnSpec()),)
            else:
                if (raw['dbf_id'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CARDRACE'),
                        raw['tags'].get('RUSH'),raw['collectible']) != (127584,1,1,1,18,1,False):
                    raise TargetValidationError('Unknown complete official Breezling face')
                kwargs['keywords'] = (Keyword.RUSH,)
        card = CardDefinition(cid,raw['name'],kind,cost=raw['cost'],
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
