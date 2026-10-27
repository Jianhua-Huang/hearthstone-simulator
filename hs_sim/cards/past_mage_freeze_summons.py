"""Real past Mage freezing, adjacent damage and original named dependencies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.captured_minion_spell_groups import DamageCapturedMinionGroup
from hs_sim.engine.effects import AddToHand, ChoiceOption, Damage, DamageBatch, Destroy, Freeze, GrantSpellDamage
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, HandActionSpec, HandDerivativeSpec, Keyword, SpellSchool, TargetSpec, Zone
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.sacrifice import FreezeCapturedMinion, MinionReference
from hs_sim.engine.spell_targets import ApplySpellTarget
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-mage-freeze-summons-v1.json'
BATCH_HASH = 'e8ee56a37341647584904c758d9c50565495ccd00396410fd8c68250dfb52017'
LEAVES = ('CFM_021','EX1_275','UNG_955','DEEP_032','ICC_836','SW_107','MAW_013','GIL_801',
    'DAL_577','CS2_027','BT_072','UNG_018','SW_108','VAC_428','SCH_509')
TOKENS = ('DAL_577ts','CS2_mirror')
EXISTING = ('CS2_033','UNG_809t1','SW_108t')
DEPENDENCIES = LEAVES+TOKENS
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_mage_freeze_summons.'
MINION = TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(r['record']['id']for r in data['dependencies']) != DEPENDENCIES or
            tuple(r['record']['id']for r in data['existing_dependencies']) != EXISTING or
            len(data['official_observations']) != 40 or not set(LEAVES) <= set(reference['candidate_ids']) or
            data['numeric_normalizations'] != {'CFM_021':{'cost':0},'CS2_mirror':{'cost':0,'attack':0}} or
            any(data[k]for k in ('cards','evidence_only','skipped','display_normalizations','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(r['record']) != r['record_sha256']for r in (*data['dependencies'],*data['existing_dependencies']))):
        raise TargetValidationError('Past Mage freeze/summons lost their complete original sources')
    return data


def register_past_mage_freeze_summons(registry):
    data = load_batch();prepared = []
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Past Mage freeze/summons changed an existing original dependency: '+cid)
    for row in data['dependencies']:
        raw = row['record'];cid = raw['id'];fields = {};zero = data['numeric_normalizations'].get(cid,{})
        if cid in registry.cards:raise TargetValidationError('Past Mage freeze/summons cannot overwrite '+cid)
        if cid == 'CS2_mirror':
            if raw['type'] != 'MINION':raise TargetValidationError('Mirror Image dependency changed its original minion type')
            fields.update(attack=0,health=raw['health'],keywords=(Keyword.TAUNT,))
        else:
            if raw['type'] != 'SPELL':raise TargetValidationError('Past Mage spell dependency changed its original type')
            fields.update(on_play=PREFIX+cid,spell_school=SpellSchool(row['spell_school'])if row['spell_school']is not None else None)
            if cid in ('EX1_275','UNG_955','DEEP_032','MAW_013','GIL_801','DAL_577','DAL_577ts','SW_108','VAC_428','SCH_509'):
                fields['targeting'] = MINION
            elif cid in ('CFM_021','BT_072'):fields['targeting'] = TargetSpec(relation='enemy')
            elif cid == 'UNG_018':fields['targeting'] = TargetSpec()
            if cid == 'ICC_836':fields['use_rule'] = PREFIX+'enemy_minion'
            if cid == 'SW_107':fields['hand_actions'] = (HandActionSpec('trade','trade',1),)
            if cid == 'DAL_577':fields.update(keywords=(Keyword.TWINSPELL,),hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL,'DAL_577ts'),))
            if cid == 'SCH_509':fields['keywords'] = (Keyword.COMBO,)
        card = CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=zero.get('cost',raw['cost']),metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Past Mage freeze/summons differs from original printed metadata: '+cid)
        prepared.append(card)

    def adjacent(c):
        primary = c.state.entities.get(c.target_id)
        if primary is None:return ()
        living = set(minions(c,registry,primary.controller))
        if primary.id not in living:return ()
        board = c.state.players[primary.controller].board;index = board.index(primary.id)
        return tuple(MinionReference.capture(c.state.entities[i])for i in board[max(0,index-1):index+2]if i in living)
    def cone(c):
        refs = adjacent(c)
        return (*tuple(FreezeCapturedMinion(ref,c.source_id)for ref in refs),DamageCapturedMinionGroup(refs,(1,)*len(refs),c.source_id))if refs else()
    def meteor(c):
        refs = adjacent(c)
        return (DamageCapturedMinionGroup(refs,tuple(15 if ref.entity_id == c.target_id else 4 for ref in refs),c.source_id),)if refs else()
    def soul(c):
        refs = adjacent(c)
        return (*tuple(FreezeCapturedMinion(ref,c.source_id)for ref in refs),
            Damage(c.state.players[c.player_id].hero_id,len(refs),c.source_id,DamageKind.SPELL))if refs else()
    def breath(c):
        refs = tuple(MinionReference.capture(c.state.entities[i])for i in minions(c,registry,3-c.player_id))
        return (ChooseRandomEffects(c.player_id,c.source_id,tuple(ChoiceOption(str(ref.entity_id),'原敌方随从',
            (ApplySpellTarget(ref,c.source_id,'damage',2),FreezeCapturedMinion(ref,c.source_id)))for ref in refs)),)if refs else()
    def ray(c):
        return (Damage(c.target_id,2,c.source_id,DamageKind.SPELL),)if c.state.entities[c.target_id].frozen else(Freeze(c.target_id,c.source_id),)
    def snap(c):
        return (Destroy(c.target_id,c.source_id),)if c.state.entities[c.target_id].frozen else(Freeze(c.target_id,c.source_id),)
    def brain(c):
        ref = MinionReference.capture(c.state.entities[c.target_id])
        return (FreezeCapturedMinion(ref,c.source_id),*((ApplySpellTarget(ref,c.source_id,'damage',3),)if c.spell_conditions.combo else()))
    def summoned(c,cid):
        request = SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c))
        return (request,request)
    bodies = {
        'CFM_021':lambda c:(Freeze(c.target_id,c.source_id),),'EX1_275':cone,'UNG_955':meteor,'DEEP_032':soul,'ICC_836':breath,
        'SW_107':lambda c:(DamageBatch(tuple(Damage(i,3,c.source_id,DamageKind.SPELL)for p in (1,2)for i in minions(c,registry,p))),),
        'MAW_013':lambda c:(RemoveFromGame((MinionReference.capture(c.state.entities[c.target_id]),),c.source_id,reveal=True),),
        'GIL_801':snap,'DAL_577':ray,'DAL_577ts':ray,
        'CS2_027':lambda c:summoned(c,'CS2_mirror'),
        'BT_072':lambda c:(Freeze(c.target_id,c.source_id),*summoned(c,'CS2_033')),
        'UNG_018':lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),AddToHand(c.player_id,'UNG_809t1',c.source_id)),
        'SW_108':lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),AddToHand(c.player_id,'SW_108t',c.source_id)),
        'VAC_428':lambda c:(GrantSpellDamage(c.target_id,1,c.source_id),)if c.state.entities[c.target_id].controller == c.player_id else(Freeze(c.target_id,c.source_id),),
        'SCH_509':brain,
    }
    def enemy_minion(c):
        return any(e.get('kind') == CardType.MINION.value and e.get('health',0)>0 and not e.get('interactable')
            for p in c.observation['players']if p['id'] == 3-c.player_id for e in p['board'])
    registry.register_use_rule(PREFIX+'enemy_minion',enemy_minion,visibility='player')
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
