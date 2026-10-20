"""Three real Ancient Words share original CAST-owned one-shot extra bodies."""
import json
from pathlib import Path

from hs_sim.engine.effects import RandomDamage
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Keyword, PlayerEffectSpec, SpellSchool
from hs_sim.engine.next_spell_bodies import NextSpellBodyProfile
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

PAST, PRESENT, LASH, HAWK = 'BE_221', 'BE_222', 'BE_223', 'BE_222t'
ROOTS = (PAST, PRESENT, LASH)
PREFIX = 'cards.ancient_words.'
PROGRAMS = {cid:PREFIX+'pending_'+cid for cid in ROOTS}
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/ancient-word-cards-v1.json'
BATCH_HASH = 'da8703f90c877d551bee97441fa806dc0d49977d259b3177a1849db3c0498f79'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['dependencies']) != (HAWK,) or
            data['existing_dependencies'] or data['choice_only'] or data['skipped'] or
            any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['cards']+data['dependencies']+data['evidence_only'])):
        raise TargetValidationError('Ancient Words require complete original roots, named token and enchantment evidence')
    return data


def register_ancient_word_cards(registry):
    data = load_batch()
    def past(c):
        return (DrawPhysicalGroup(c.player_id, c.source_id, (DrawGroupSlot(),), DrawGroupReward('cost_all', 2)),)
    def present(c):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(HAWK),), SummonCause.capture(c)),)
    def lash(c):
        return (RandomDamage(characters(c, registry, 3-c.player_id), 3, c.source_id, DamageKind.SPELL),)
    bodies = {PAST:past, PRESENT:present, LASH:lash}
    for cid, body in bodies.items():
        registry.register_behavior(PREFIX+'effect_'+cid, body)
        registry.register_behavior(PREFIX+'play_'+cid, lambda c,cid=cid,body=body: (
            *body(c), AddPlayerEffect(c.player_id, PROGRAMS[cid], c.source_id)))
    raw = data['dependencies'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('LIFESTEAL')) != ('MINION', 5, 5, 5, 1):
        raise TargetValidationError('Netherwing Dragonhawk changed its complete original Lifesteal face')
    card = CardDefinition(HAWK, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        keywords=(Keyword.LIFESTEAL,), metadata=metadata_from_record(raw))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    for item in data['cards']:
        raw = item['record']; cid = raw['id']
        if (raw['type'] != 'SPELL' or raw['cost'] != {PAST:3, PRESENT:5, LASH:1}[cid] or
                raw['tags'].get('SPELL_SCHOOL') != 6):
            raise TargetValidationError('Ancient Word changed its complete Shadow spell face')
        card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'], spell_school=SpellSchool.SHADOW,
            on_play=PREFIX+'play_'+cid, metadata=metadata_from_record(raw))
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
        registry.register_player_effect(PlayerEffectSpec(PROGRAMS[cid], cid))
        registry.register_next_spell_body_profile(NextSpellBodyProfile(PROGRAMS[cid], cid, PREFIX+'effect_'+cid))
