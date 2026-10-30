"""Five actual native consumers of committed play, attack, entry and discard facts."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.character_attacks import completed_attack, completed_minion_keywords
from hs_sim.engine.effects import Damage, ReturnToHand
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,TriggerSpec,Zone
from hs_sim.engine.play_history import played_cards,play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import GrantCapturedKeyword,MinionReference
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-native-conditional-triggers-v1.json'
BATCH_HASH='42a3cdadac919b83e3d85ddfa66e7bcab7ad360f4f165f3e715eb3e867b5ed4d'
VANESSA,KORVAS,ETC,LIADRIN,ZAVAS=ROOTS=('CS3_005','CS3_019','DMF_529','RLK_924','UNG_836')
DEPENDENCIES=EXISTING=()
EVIDENCE=('MIS_701',)
PREFIX='cards.past_native_conditional_triggers.'


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION' or any(type(raw[k])is not int for k in ('cost','attack','health')):
        raise TargetValidationError('Native conditional consumer requires its complete original minion face')
    fields={}
    if cid==VANESSA:fields.update(combo=PREFIX+cid,keywords=(Keyword.COMBO,))
    elif cid==ZAVAS:fields['on_discard']=PREFIX+cid
    else:fields['triggers']=(TriggerSpec({KORVAS:'card_played',ETC:'attack_finished',LIADRIN:'minion_summoned'}[cid],PREFIX+cid),)
    if cid==KORVAS:fields['keywords']=(Keyword.CHARGE,Keyword.LIFESTEAL)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            any(d[k]for k in ('dependencies','existing_dependencies','complete_past_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated')) or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=12):
        raise TargetValidationError('Native conditional consumers changed full source roles or claimed full support')
    for row in d['cards']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original native conditional row')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed complete past source')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids'] or any(
            row['record']!=rows[row['record']['id']]for row in d['cards']):raise TargetValidationError('Cropped original past source')
    return d


def register_past_native_conditional_triggers(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Native conditional consumer changed or replaced another original face')
        registry._validate_card(card);prepared.append(card)
    def vanessa(c):
        if c.play is None:raise ValueError('Vanessa requires its actual original Combo play')
        rows=played_cards(c.state,3-c.player_id,before_id=c.play.id)
        if not rows:return ()
        row=rows[-1];material=row.minion_copy_material if row.kind==CardType.MINION else row.played_face
        return (CopyCard(material,c.player_id,mode='base',source_id=c.source_id),)
    def korvas(c):
        if c.event is None or c.event.kind!='card_played':raise ValueError('Korvas requires its actual completed physical play')
        row=play_record(c.state,dict(c.event.data)['play_id'])
        if not row.completed or (row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
            raise ValueError('Korvas lost its actual completed physical play')
        if row.player_id!=c.player_id or not living_source(c):return ()
        if row.submitted_cost is None:raise ValueError('Korvas requires original submitted card keywords')
        has_outcast=any(not a.consumed and a.kind=='keyword'and a.keyword==Keyword.OUTCAST
            for a in row.submitted_cost.quote.quote_input.abilities)
        return (ReturnToHand(c.source_id),) if has_outcast else ()
    def etc(c):
        row=completed_attack(c)
        if row is None or row.source_kind!=CardType.MINION or row.combat.player_id!=c.player_id or not living_source(c):return ()
        keywords=completed_minion_keywords(c,registry)
        return (Damage(c.state.players[3-c.player_id].hero_id,2,c.source_id,DamageKind.MINION_ABILITY),) if Keyword.RUSH in keywords else ()
    def liadrin(c):
        if c.event is None or c.event.player_id!=c.player_id or not living_source(c):return ()
        target=c.state.entities.get(c.event.target_id)
        if (target is None or target.kind!=CardType.MINION or target.zone!=Zone.BOARD or target.controller!=c.player_id or
                not target.active or target.health<=0 or target.doomed or target.attack>=c.source.attack):return ()
        ref=MinionReference.capture(target)
        return tuple(GrantCapturedKeyword(ref,k,c.source_id)for k in (Keyword.DIVINE_SHIELD,Keyword.RUSH))
    def zavas(c):
        if c.discard is None:raise ValueError('Zavas requires its actual original native discard')
        return (BuffStoredCard(c.discard,2,2,source_id=c.source_id),ReturnToHand(c.source_id,discard=c.discard))
    for cid,body in ((VANESSA,vanessa),(KORVAS,korvas),(ETC,etc),(LIADRIN,liadrin),(ZAVAS,zavas)):
        registry.register_behavior(PREFIX+cid,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
