"""Native Battlecries keep original source and defender board residences."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import ChoiceOption, ForceAttack, RequestChoice
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, HandActionSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-forced-attack-v1.json'
BATCH_HASH='4969346f20ce3a1574358c97d06422536b15f355674bb73b63a4965bbd170785'
HOUND='JAIL_435';SABER='EDR_014';PREFIX='cards.native_forced_attack.'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(HOUND,SABER)
            or any(d[k]for k in ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Native forced Battlecry lost complete reviewed source')
    if any(canonical_digest(x['record'])!=x['record_sha256']for x in d['cards']):
        raise TargetValidationError('Native forced Battlecry original full row changed')
    return d


def register_native_forced_attack_cards(registry):
    def hound(c):
        if not living_source(c):return ()
        source=capture_board_presence(c.state,c.source_id)
        return tuple(ForceAttack(capture_board_presence(c.state,i),source)
            for i in minions(c,registry,3-c.source.controller))
    def saber(c):
        cost=c.play.cost if c.play is not None else quote_unselected_cost(c.state,registry,c.source).amount
        if cost>3 or not living_source(c):return ()
        source=asdict(capture_board_presence(c.state,c.source_id))
        options=tuple(ChoiceOption(json.dumps(dict(source=source,target=asdict(capture_board_presence(c.state,i))),sort_keys=True),
            'Original enemy minion')for i in minions(c,registry,3-c.source.controller))
        return (RequestChoice(c.player_id,options,c.source_id,min_count=0,max_count=0,
            sample_size=min(2,len(options)),on_select=PREFIX+'selected'),)if options else ()
    def selected(c):
        if c.choice is None or c.choice.selected_ids or not 1<=len(c.choice.choice.options)<=2:
            raise TargetValidationError('Dreamsaber lost its complete original sampled targets')
        rows=[json.loads(o.id)for o in c.choice.choice.options]
        sources=[BoardPresenceReference(**x['source'])for x in rows]
        targets=[BoardPresenceReference(**x['target'])for x in rows]
        if any(s!=sources[0]or s.entity_id!=c.source_id for s in sources)or len(set(targets))!=len(targets):
            raise TargetValidationError('Dreamsaber changed its original source or duplicated a target')
        return tuple(ForceAttack(s,t)for s,t in zip(sources,targets))
    for cid,body in ((HOUND,hound),(SABER,saber),('selected',selected)):
        registry.register_behavior(PREFIX+cid,body)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='MINION' or raw['tags'].get('BATTLECRY')!=1:
            raise TargetValidationError('Native forced consumer requires its actual minion Battlecry')
        kwargs=dict(hand_actions=(HandActionSpec('prepare','prepare',1),))if cid==HOUND else {}
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=metadata_from_record(raw),battlecry=PREFIX+cid,**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
