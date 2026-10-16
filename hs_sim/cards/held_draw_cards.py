"""Native held-turn growth, self discard and spell-count form switching."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Draw,Freeze
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import (CardDefinition,CardType,ChooseBranch,ChooseOneSpec,HandProgressSpec,
    TargetMode,TargetSpec,Zone)
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.zones import CardReference,DiscardCard,DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/held-progress-forms-v1.json'
BATCH_HASH='427b5cb04c40f759f21c536df74d104de3e2d7af73b75ce22e75529729d074cc'
PREFIX='cards.held_draw.'
SCRIPTS={'EDR_843':'forest','EDR_843a':'forest_spell','EDR_843b':'forest_minion','EDR_843t1':'forest_both',
    'FIR_911':'grove','JAIL_803':'frost','JAIL_803t':'frost_elemental'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Held draw forms lost their complete reviewed pin')
    return value


def register_held_draw_cards(registry):
    data=load_batch();raws={r['record']['id']:r['record']for r in data['cards']}
    if (raws['EDR_843']['tags']['TAG_SCRIPT_DATA_NUM_1'],raws['JAIL_803']['tags']['TAG_SCRIPT_DATA_NUM_1'],
        raws['FIR_911']['tags']['TAG_SCRIPT_DATA_NUM_1'],raws['FIR_911']['tags']['TAG_SCRIPT_DATA_NUM_2'])!=(3,3,1,3):
        raise TargetValidationError('Held draw native counters differ from reviewed source values')
    for link in data['gallery_links']:
        cid=link['root_id'];gallery=link['gallery_record']
        if gallery['id']!=raws[cid]['dbf_id']:raise TargetValidationError('Held form gallery lost its actual root')
        expected={'EDR_843':('EDR_843a','EDR_843b','EDR_843t1'),'JAIL_803':('JAIL_803t',),'FIR_911':()}[cid]
        if not {raws[x]['dbf_id']for x in expected}<=set(gallery.get('child_ids')or()):
            raise TargetValidationError('Held draw forms lost their complete CN child links')
    registry.register_trigger_condition(PREFIX+'own_end',lambda c:c.event is not None and c.event.player_id==c.player_id)
    registry.register_trigger_condition(PREFIX+'own_cast',lambda c:c.cast is not None and c.cast.player_id==c.player_id)
    def draw_kind(c,kind):return DrawMatching(c.player_id,PoolQuery(kinds=(kind,)),'skip',source_id=c.source_id)
    def grove(c):
        ability=progress_ability(c.source)
        if ability is None or ability.hand_progress!=registry.card('FIR_911').hand_progress:
            raise TargetValidationError('Smoldering Grove lost its native physical growth progress')
        return (Draw(c.player_id,1+ability.progress_completions,c.source_id),)
    def grove_end(c):
        if c.trigger is None or c.trigger.hand_progress!=registry.card('FIR_911').hand_progress:
            raise TargetValidationError('Smoldering Grove end requires its original completed progress')
        return (DiscardCard(CardReference.capture(c.source),c.source_id),)if c.trigger.progress_completions>=3 else ()
    def frost(c):return (*((Freeze(c.target_id,c.source_id),)if c.target_id is not None else()),Draw(c.player_id,2,c.source_id))
    bodies=dict(forest_spell=lambda c:(draw_kind(c,CardType.SPELL),),forest_minion=lambda c:(draw_kind(c,CardType.MINION),),
        forest_both=lambda c:(draw_kind(c,CardType.SPELL),draw_kind(c,CardType.MINION)),grove=grove,grove_end=grove_end,frost=frost,frost_elemental=frost)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={};school=raw['tags'].get('SPELL_SCHOOL')
        if canonical_digest(raw)!=row['record_sha256']or SCRIPTS.get(cid)!=recipe['script']or raw['collectible']!=recipe['root']:
            raise TargetValidationError('Held draw recipe differs from its full source face')
        if cid=='EDR_843':
            branches=tuple(ChooseBranch(x,raws[x]['name'],PREFIX+SCRIPTS[x])for x in ('EDR_843a','EDR_843b','EDR_843t1'))
            kwargs.update(choose_one=ChooseOneSpec(branches[:2],branches[2]),
                hand_progress=HandProgressSpec('event',3,'EDR_843t1',event='turn_ended',condition_id=PREFIX+'own_end'))
        elif not recipe['choice_only']:kwargs['on_play'if kind==CardType.SPELL else'battlecry']=PREFIX+recipe['script']
        if cid=='FIR_911':kwargs['hand_progress']=HandProgressSpec('event',1,on_complete=PREFIX+'grove_end',repeat=True,event='turn_ended',condition_id=PREFIX+'own_end')
        if cid=='JAIL_803':kwargs['hand_progress']=HandProgressSpec('event',3,'JAIL_803t',event='spell_cast_accepted',condition_id=PREFIX+'own_cast')
        if cid in ('JAIL_803','JAIL_803t'):
            kwargs['targeting']=TargetSpec(TargetMode.REQUIRED if kind==CardType.SPELL else TargetMode.IF_AVAILABLE,
                zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION),relation='enemy')
        if kind==CardType.SPELL:
            if school is not None and school not in SCHOOLS:raise TargetValidationError('Unknown held draw spell school')
            kwargs['spell_school']=SCHOOLS.get(school)
        # Option descriptors use the existing zero-cost/nonphysical contract;
        # the full raw option cost remains pinned and the real root pays two.
        card=CardDefinition(cid,raw['name'],kind,cost=0 if recipe['choice_only']else raw['cost'],attack=raw['attack']or 0,health=raw['health']or 0,
            choice_only=recipe['choice_only'],metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card)
        if not recipe['choice_only']:registry.register_pool_card(PoolCard.from_definition(card))
