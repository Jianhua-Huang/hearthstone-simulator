"""Genuine chain grants and complete Deathrattles from one original death."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.deathrattle_inheritance import GainDeathrattlesFromDeath
from hs_sim.engine.effects import ChoiceOption, GrantDeathrattle, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference, live_minion
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

SURFER, DEVOURER = 'ETC_104', 'RLK_538'
DEPENDENCIES = (SURFER, DEVOURER)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_deathrattle_acquisition.'
SURF, SELECTED, GAIN = (PREFIX+s for s in ('surf','selected','gain'))
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-deathrattle-acquisition-cards-v1.json'
BATCH_HASH = '9ad3515bfa66c731508d3e484194efdc854a41b37313610d9bd1e25d4a82ddf1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES or
            any(data[k] for k in ('cards','existing_dependencies','evidence_only','choice_only',
                'skipped','numeric_normalizations','display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Deathrattle acquisition lost its complete original source faces')
    return data


def register_past_deathrattle_acquisition_cards(registry):
    def surf(c):
        if c.deathrattle is None or c.deathrattle.ability.behavior_id != SURF:
            raise ResolutionError('Surfer requires its actual own Deathrattle invocation')
        options = tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(e)),sort_keys=True),
            'Random other minion',entity_id=i)
            for i,e in sorted(c.state.entities.items()) if i!=c.source_id and e.kind==CardType.MINION and
            e.zone==Zone.BOARD and e.active and e.health>0 and not e.doomed)
        return (RequestChoice(c.player_id,options,c.source_id,min_count=0,max_count=0,
            sample_size=1,on_select=SELECTED),) if options else ()

    def selected(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options)!=1:
            raise ResolutionError('Surfer lost its original single sampled recipient')
        ref = MinionReference(**json.loads(c.choice.choice.options[0].id))
        if live_minion(c.state,ref) is None:return ()
        # The text grants this fixed body only, never the source's other rattles.
        return (GrantDeathrattle(ref.entity_id,SURF,c.source_id),BuffCapturedMinion(ref,1,1,c.source_id))

    def gain(c):
        if c.event is None or c.event.kind!='minion_died':
            raise ResolutionError('Devourer requires its original minion death event')
        death_id = dict(c.event.data)['death_id']
        death = next((d for d in c.state.death_history if d.id==death_id),None)
        if death is None or death.entity_id!=c.event.target_id:
            raise ResolutionError('Devourer lost the exact original death')
        source=c.source
        if death.controller!=c.player_id or source.kind!=CardType.MINION or source.zone!=Zone.BOARD:
            return ()
        return (GainDeathrattlesFromDeath(death.id,MinionReference.capture(source)),)

    for key,body in ((SURF,surf),(SELECTED,selected),(GAIN,gain)):
        registry.register_behavior(key,body)
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id'];health=1 if cid==SURFER else 3
        if (raw['type'],raw['collectible'],raw['cost'],raw['attack'],raw['health'],
                raw['tags'].get('CLASS'),raw['tags'].get('DEATHRATTLE')) != (
                'MINION',True,1,1,health,12 if cid==SURFER else 9,1 if cid==SURFER else None):
            raise TargetValidationError('Deathrattle acquisition changed its original printed face')
        extra = dict(deathrattle=SURF) if cid==SURFER else dict(triggers=(TriggerSpec('minion_died',GAIN),))
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=1,health=health,
            metadata=metadata_from_record(raw),**extra)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
