"""Captured Archmage uses actual original deaths and the native spell caster."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.automatic_targets import AutomaticTargetPreference
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.targeting import accepts_target
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ARCHMAGE='JAIL_974';FIREBALL='CS2_029';ROOTS=COLLECTIBLE_ROOTS=(ARCHMAGE,);DEPENDENCIES=();DEFERRED=('FIR_914','FIR_916');PREFIX='cards.simple_followup_p90.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p90-v1.json'
BATCH_HASH='9bc25a095df54d14df7f1b2a9912776436a77dc4c248d9860128562062c2c2aa'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or tuple(x['record']['id']for x in d['evidence_only'])!=DEFERRED:raise TargetValidationError('P90 complete locked scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('cards','existing_dependencies','evidence_only')for x in d[key]):raise TargetValidationError('P90 complete original row changed')
 return d

def register_simple_followup_p90_cards(registry):
 d=load_batch()
 if canonical_digest(asdict(registry.card(FIREBALL)))!=d['existing_dependency_definition_pins'][FIREBALL]:raise TargetValidationError('P90 requires unchanged complete Fireball')
 def archmage(c):
  death=c.death
  capture=c.deathrattle
  if capture is None or(capture.carrier_id,capture.player_id,capture.ability.behavior_id)!=(c.source_id,c.player_id,PREFIX+ARCHMAGE):raise ResolutionError('Captured Archmage requires its actual accepted Deathrattle')
  if death is not None and(death not in c.state.death_history or(death.entity_id,death.controller,death.zone)!=(c.source_id,c.player_id,Zone.BOARD)):raise ResolutionError('Captured Archmage lost its original friendly death')
  if sum((death is None or r.id!=death.id)and r.controller==c.player_id and r.zone==Zone.BOARD and r.card_id==ARCHMAGE for r in c.state.death_history)<4:return()
  hero=c.state.players[3-c.player_id].hero_id
  if not any(e.controller!=c.player_id and accepts_target(c.state,registry,c.source,registry.card(FIREBALL),e.id,automatic=True)for e in c.state.entities.values()):return(CastSpell(c.player_id,FIREBALL,c.source_id,hero,targeting='explicit'),)
  return(CastSpell(c.player_id,FIREBALL,c.source_id,target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE),)
 registry.register_behavior(PREFIX+ARCHMAGE,archmage)
 raw=d['cards'][0]['record'];definition=CardDefinition(ARCHMAGE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],deathrattle=PREFIX+ARCHMAGE,metadata=metadata_from_record(raw))
 registry.register_card(definition)
 if ARCHMAGE not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
