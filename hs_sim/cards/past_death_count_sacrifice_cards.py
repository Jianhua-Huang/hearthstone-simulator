"""Real full-board Cultists, original named Boar deaths and weapon followup."""
import json
from pathlib import Path

from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.effects import Damage,DamageBatch,DestroyAllManaCrystals,EquipWeapon
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,EndTurnSpec,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import SacrificeFullNamedBoard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery,death_candidates
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CULTIST,BOAR,RA,SWORD='ULD_705','SW_075','ULD_705t','SW_075t'
DEPENDENCIES=(CULTIST,BOAR,RA,SWORD)
COLLECTIBLE_ROOTS=()
PREFIX='cards.past_death_count_sacrifice.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-death-count-sacrifice-v1.json'
BATCH_HASH='e9a660c006bda7bdf1d194365b0e4e8307b870ffa253aad0090b39e6ba75ba67'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(d['collectible_leaf_ids'])!=(CULTIST,BOAR) or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            d['display_normalizations']!={BOAR:{'@':''}} or
            any(d[k]for k in ('cards','existing_dependencies','evidence_only','choice_only','skipped','numeric_normalizations')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Cultist and Boar lost their complete original source and dependencies')
    return d


def register_past_death_count_sacrifice_cards(registry):
    def cultist(c):
        return(SacrificeFullNamedBoard(c.player_id,CULTIST,RA,SummonCause.capture(c)),)

    def boar(c):
        rows=death_candidates(c.state,registry,c.player_id,DeathQuery(cards=PoolQuery(card_ids=(BOAR,))))
        return(EquipWeapon(c.player_id,SWORD),)if len(rows)>=10 else()

    def ra(c):
        opponent=c.state.players[3-c.player_id]
        ids=(opponent.hero_id,*(i for i in opponent.board if(e:=c.state.entities[i]).kind==CardType.MINION and
            e.active and e.health>0 and not e.doomed))
        return(DamageBatch(tuple(Damage(i,20,c.source_id,DamageKind.MINION_ABILITY)for i in ids)),)

    def sword(c):
        row=completed_attack(c)
        if (row is None or row.source_kind!=CardType.HERO or row.declaration.player_id!=c.player_id or
                row.combat is None or row.combat.weapon_id!=c.source_id):return ()
        return(DestroyAllManaCrystals(3-c.player_id),)

    for key,body in (('cultist',cultist),('boar',boar),('ra',ra),('sword',sword)):
        registry.register_behavior(PREFIX+key,body)
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id'];extra={}
        expected=(10,20,20)if cid==RA else((10,15,3)if cid==SWORD else(1,1,1))
        kind=CardType.WEAPON if cid==SWORD else CardType.MINION
        if (raw['type']!=kind.value.upper() or(raw['cost'],raw['attack'],raw['health'])!=expected or
                raw['collectible']!=(cid in(CULTIST,BOAR)) or raw['tags'].get('CLASS')!=12):
            raise TargetValidationError('Cultist, Boar or real reward changed its printed face')
        if cid==CULTIST:extra['battlecry']=PREFIX+'cultist'
        elif cid==BOAR:extra['deathrattle']=PREFIX+'boar'
        elif cid==RA:extra['triggers']=(TriggerSpec('turn_ended',PREFIX+'ra',EndTurnSpec('controller')),)
        else:extra['triggers']=(TriggerSpec('attack_finished',PREFIX+'sword'),)
        if cid!=SWORD:extra['health']=raw['health']
        else:extra['durability']=raw['health']
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack'],
            metadata=metadata_from_record(raw),**extra)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
