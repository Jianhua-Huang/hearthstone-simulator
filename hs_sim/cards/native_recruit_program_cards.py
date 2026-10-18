"""Five actual Silver Hand cards share controlled-card player stat programs."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand
from hs_sim.engine.model import (CardDefinition, CardType, Keyword, PlayerAuraSpec,
    PlayerEffectSpec, SpellSchool, TriggerSpec)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

OFFICER, RESCUER, REST, BLADE, TEAMWORK = ROOTS = (
    'MEND_800', 'MEND_801', 'MEND_802', 'MEND_803', 'MEND_900')
RECRUIT = 'CS2_101t'
PREFIX = 'cards.recruit_program.'
POLICY = 'controlled-minion-card-family-additive-player-aura-v1'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/native-recruit-program-v1.json'
BATCH_HASH = '9bf9669f0fa098b875f98d152bdd0c07553f8188ed16283d24e55c65186b662f'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['policy'] != POLICY or
            tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            tuple(x['record']['id'] for x in d['existing_dependencies']) != (RECRUIT,) or
            d['dependencies'] or d['skipped']):
        raise TargetValidationError('Recruit programs require their complete original source and exact scope')
    records = [x for k in ('cards', 'existing_dependencies', 'evidence_only') for x in d[k]]
    if any(canonical_digest(x['record']) != x['record_sha256'] for x in records):
        raise TargetValidationError('Recruit source row changed')
    raw = {x['record']['id']: x['record'] for x in records}
    for cid in d['recipient_ids']:
        r = raw[cid]
        if (r['type'], r['collectible'], r['cost'], r['attack'], r['health'], r['name_en']) != (
                'MINION', False, 1, 1, 1, 'Silver Hand Recruit'):
            raise TargetValidationError('Recruit family requires its original one-mana 1/1 identities')
    return d


def register_native_recruit_program_cards(registry):
    d = load_batch()
    if canonical_digest(asdict(registry.card(RECRUIT))) != d['existing_dependencies'][0]['definition_sha256']:
        raise TargetValidationError('The complete existing Silver Hand Recruit definition changed')
    recipients = tuple(d['recipient_ids'])
    programs = {OFFICER: (1, 0), RESCUER: (0, 1), BLADE: (1, 1)}
    for cid, (attack, health) in programs.items():
        program = PREFIX+cid
        registry.register_player_effect(PlayerEffectSpec(program, cid, auras=(
            PlayerAuraSpec(attack, health, recipients, 'controlled_minion_cards'),)))
        def upgrade(c, program=program):
            return (AddPlayerEffect(c.player_id, program, c.source_id),)
        registry.register_behavior(program, upgrade)
    def lost_shield(c):
        return ((AddPlayerEffect(c.player_id, PREFIX+RESCUER, c.source_id),)
            if c.event is not None and c.event.kind == 'shield_lost' and c.event.target_id == c.source_id else ())
    def summon(c, count, shield=False):
        material = SummonEntryMaterial(RECRUIT, keywords=(Keyword.DIVINE_SHIELD,) if shield else ())
        request = SummonByCard(c.player_id, (material,), SummonCause.capture(c))
        return (request,)*count
    registry.register_behavior(PREFIX+'shield_lost', lost_shield)
    registry.register_behavior(PREFIX+REST, lambda c: summon(c, 2, True))
    registry.register_behavior(PREFIX+TEAMWORK, lambda c: (*summon(c, 4), *(
        AddToHand(c.player_id, RECRUIT, c.source_id) for _ in range(4))))
    for item in d['cards']:
        raw = item['record']; cid = raw['id']; kind = CardType(raw['type'].lower())
        fields = dict(cost=raw['cost'], metadata=metadata_from_record(raw))
        if cid == OFFICER:
            fields.update(attack=raw['attack'], health=raw['health'], keywords=(Keyword.RUSH,), deathrattle=PREFIX+cid)
        elif cid == RESCUER:
            fields.update(attack=raw['attack'], health=raw['health'], keywords=(Keyword.DIVINE_SHIELD,),
                triggers=(TriggerSpec('shield_lost', PREFIX+'shield_lost'),))
        elif cid == BLADE:
            fields.update(attack=raw['attack'], durability=raw['health'], battlecry=PREFIX+cid)
        else:
            fields['on_play'] = PREFIX+cid
            if cid == REST:
                fields['spell_school'] = SpellSchool.HOLY
        card = CardDefinition(cid, raw['name'], kind, **fields)
        registry.register_card(card)
        if cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
