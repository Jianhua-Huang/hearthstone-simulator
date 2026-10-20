"""Original Highborne Mentor/Pupil and reviewed reachable past spell examples."""
import json
from pathlib import Path

from hs_sim.engine.carved_spells import CarvedSpellProfile,CastCarvedSpell
from hs_sim.engine.student_teaching import CreateStudentDiscovery
from hs_sim.engine.effects import Buff,Draw,GrantKeyword,Heal,HealBatch
from hs_sim.engine.model import CardDefinition,CardType,HealingKind,Keyword,SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='TIME_704';PUPIL='TIME_704t';GIFT='EX1_183';OVERFLOW='ULD_273'
POOL_ID='constructed.past.spells';P='cards.highborne.'
PROFILE=CarvedSpellProfile(PUPIL,CARD,teaching=True)
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/highborne-student-v1.json'
BATCH_HASH='ce83510df7d8de03f95613c498ed4035f87990eb0cf3fd42aef86ccab2b18dbd'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'));rows=(*data['cards'],*data['dependencies'],*data['existing_dependencies'])
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in rows)!=(CARD,PUPIL,GIFT,OVERFLOW,'EX1_279')or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)or data['evidence_only']or data['skipped']):
        raise TargetValidationError('Student teaching lost its complete creator, original pupil or reviewed spell records')
    return data


def register_highborne_student_cards(registry):
    def teach(c):
        if c.battlecry is None:raise ValueError('Student creation requires the original accepted Battlecry')
        return(CreateStudentDiscovery(c.battlecry.id,PUPIL,POOL_ID),)
    def cast(c):
        if c.battlecry is None:raise ValueError('Pupil casting requires its original accepted Battlecry')
        return(CastCarvedSpell(c.battlecry.id),)
    def gift(c):
        targets=tuple(i for i in c.state.players[c.player_id].board if c.state.entities[i].dormancy is None)
        return tuple(e for i in targets for e in(Buff(i,2,2,c.source_id),GrantKeyword(i,Keyword.TAUNT,c.source_id)))
    def overflow(c):
        ids=tuple(p.hero_id for p in c.state.players.values())+tuple(i for p in c.state.players.values()for i in p.board if c.state.entities[i].dormancy is None)
        return(HealBatch(tuple(Heal(i,5,c.source_id,HealingKind.SPELL)for i in ids)),Draw(c.player_id,5,c.source_id))
    for name,body in(('teach',teach),('cast',cast),('gift',gift),('overflow',overflow)):registry.register_behavior(P+name,body)
    data=load_batch()
    for row in data['existing_dependencies']:
        raw=row['record'];old=registry.card(raw['id'])
        if (old.cost,old.metadata)!=(raw['cost'],metadata_from_record(raw)):raise TargetValidationError('Original existing spell changed')
    for row,name in zip((*data['cards'],*data['dependencies']),('teach','cast','gift','overflow')):
        raw=row['record'];kind=CardType(raw['type'].lower())
        fields=dict(battlecry=P+name,attack=raw['attack'],health=raw['health'])if kind==CardType.MINION else dict(on_play=P+name,spell_school=SpellSchool(row['spell_school']))
        card=CardDefinition(raw['id'],raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**fields)
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_carved_spell_profile(PROFILE)
