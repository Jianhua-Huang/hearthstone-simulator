"""Physical spell partition and one permanent normal-turn draw replacement."""
import json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption, Draw, RequestChoice
from hs_sim.engine.model import CardDefinition, CardType, PlayerEffectSpec, SpellSchool, Zone
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.turn_start_draws import DrawDeckEdge, TurnDrawReplacementProfile
from hs_sim.engine.zones import ReorderZone
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD,TOP,BOTTOM='BE_250','BE_250t','BE_250t2'
PROGRAM='cards.discs-norgannon.program'
INSTALL='cards.discs-norgannon.install'
DRAW='cards.discs-norgannon.draw'
PROMPT='选择从牌库顶或牌库底抽牌'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/discs-norgannon-v1.json'
BATCH_HASH='6a8d69bba131875aa3862806ebe42084a23fe72e26d0fed4acbf6b74db1fbdc6'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id'] for x in data['cards'])!=(CARD,) or
            tuple(x['record']['id'] for x in data['dependencies'])!=(TOP,BOTTOM) or
            tuple(x['record']['id'] for x in data['evidence_only'])!=('BE_250e',) or
            data['existing_dependencies'] or data['skipped'] or data['official_faces_verified']!=6 or
            data['numeric_normalizations']!={TOP:{'cost':0},BOTTOM:{'cost':0}}):
        raise TargetValidationError('Discs of Norgannon requires its complete root, two real options and passive source')
    for row in (*data['cards'],*data['dependencies'],*data['evidence_only']):
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Discs of Norgannon source record changed')
    return data


def register_discs_norgannon_card(registry):
    data=load_batch();raw=data['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['tags'].get('SPELL_SCHOOL'))!=('SPELL',2,1):
        raise TargetValidationError('Discs of Norgannon requires its actual two-Mana Arcane face')
    def install(c):
        deck=c.state.players[c.player_id].deck
        spells=tuple(i for i in deck if c.state.entities[i].kind==CardType.SPELL)
        others=tuple(i for i in deck if c.state.entities[i].kind!=CardType.SPELL)
        return (ReorderZone(c.player_id,Zone.DECK,spells+others),AddPlayerEffect(c.player_id,PROGRAM,c.source_id))
    def draw(c):
        instance=c.player_effect
        if (instance is None or instance.spec_id!=PROGRAM or c.state.active_player!=c.player_id or
                instance not in c.state.players[c.player_id].player_effects):
            raise ValueError('Discs requires its original scheduled owner-draw program')
        if not c.state.players[c.player_id].deck:return (Draw(c.player_id),)
        return (RequestChoice(c.player_id,tuple(ChoiceOption(edge,registry.card(cid).name,
            (DrawDeckEdge(c.player_id,edge),),card_id=cid)for edge,cid in (('top',TOP),('bottom',BOTTOM))),
            c.source_id,PROMPT),)
    registry.register_behavior(INSTALL,install);registry.register_behavior(DRAW,draw)
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=2,on_play=INSTALL,
        spell_school=SpellSchool.ARCANE,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    for row in data['dependencies']:
        face=row['record']
        registry.register_card(CardDefinition(face['id'],face['name'],CardType.SPELL,cost=0,
            choice_only=True,metadata=metadata_from_record(face)))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,CARD))
    registry.register_turn_draw_replacement_profile(TurnDrawReplacementProfile(PROGRAM,DRAW))
