"""Reviewed health spells and current Core faces using existing public effects."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Buff, Damage, DamageBatch, Draw, Heal, InvokeBehavior, RandomDamage
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, HealingKind, Keyword,
                                 TargetMode, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .core_secret_cards import enemy_minions
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/health-followup-effects-v1.json'
BATCH_HASH = '2f1dd0f35b090301e900ca5edfd3a769ff3c3453097ae66a14052499da79e870'
PREFIX = 'cards.health_followup.'
ALIASES = {
    'CORE_CS1_112': ('CS1_112', 'on_play', 'm2.holy_nova'),
    'CORE_CS2_024': ('CS2_024', 'on_play', 'm2.frostbolt'),
    'CORE_CS2_028': ('CS2_028', 'on_play', 'm5.blizzard'),
    'CORE_EX1_134': ('EX1_134', 'combo', 'm5.si7'),
}
SCRIPTS = {'CORE_BOT_222': 'soul_bomb', 'CORE_ICC_055': 'drain_soul',
           'CORE_SW_442': 'void_shard', 'CATA_302': 'mend',
           'CATA_485': 'torrent', 'CATA_582': 'rift'}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Health followup cards differ from the reviewed full source pin')
    return data


def followup(c, name):
    return InvokeBehavior(PREFIX+name, c.source_id, c.player_id, c.target_id,
                          None if c.play is None else c.play.id)


def register_health_followup_cards(registry):
    def soul_bomb(c):
        return (DamageBatch(tuple(Damage(eid, 4, c.source_id, DamageKind.SPELL)
                                  for eid in (c.target_id, c.state.players[c.player_id].hero_id))),)

    def mend(c):
        # Full healing requests the current maximum, retaining overheal/conversion semantics.
        return (Heal(c.target_id, c.state.entities[c.target_id].max_health,
                     c.source_id, HealingKind.SPELL), Draw(c.player_id, 1))

    def rift(c):
        candidates = []
        for player in c.state.players.values():
            candidates.extend(eid for eid in player.board for e in (c.state.entities[eid],)
                              if e.kind == CardType.MINION and e.active and e.health > 0
                              and not e.doomed and registry.card(e.card_id).interactable is None)
        return (DamageBatch(tuple(Damage(eid, 1, c.source_id, DamageKind.SPELL) for eid in candidates)),
                followup(c, 'rift_attack'))

    bodies = {
        'soul_bomb': soul_bomb,
        'drain_soul': lambda c: (Damage(c.target_id, 3, c.source_id, DamageKind.SPELL),),
        'void_shard': lambda c: (Damage(c.target_id, 4, c.source_id, DamageKind.SPELL),),
        'mend': mend,
        'torrent': lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL), followup(c, 'torrent_random')),
        'torrent_random': lambda c: (RandomDamage(enemy_minions(c, registry), 1, c.source_id, DamageKind.SPELL),),
        'rift': rift,
        'rift_attack': lambda c: (Buff(c.state.players[c.player_id].hero_id, attack=3,
                                      source_id=c.source_id, expires_turn=c.state.turn),),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX+name, body)
    for row in load_batch()['cards']:
        raw, recipe = row['record'], row['recipe']
        if (canonical_digest(raw) != row['record_sha256'] or raw['cost'] != recipe['cost']
                or raw['collectible'] is not True):
            raise TargetValidationError('Health followup card lost its complete reviewed face')
        kind = CardType(raw['type'].lower())
        metadata = replace(metadata_from_record(raw), deck_identity=recipe['deck_identity'])
        school = SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))
        if raw['id'] in ALIASES:
            alias, entry, behavior = ALIASES[raw['id']]
            original = registry.card(alias)
            if (recipe['alias'] != alias or getattr(original, entry) != behavior
                    or (original.kind, original.cost, original.attack, original.health) !=
                    (kind, raw['cost'], raw['attack'] or 0, raw['health'] or 0)):
                raise TargetValidationError('Current Core face differs from its reviewed executable alias')
            definition = replace(original, id=raw['id'], name=raw['name'],
                                 metadata=metadata, spell_school=school)
        else:
            if (kind != CardType.SPELL or recipe['alias'] is not None
                    or SCRIPTS.get(raw['id']) != recipe['script']):
                raise TargetValidationError('Unreviewed health followup body')
            target = recipe['target']
            if target not in (None, 'minion', 'character'):
                raise TargetValidationError('Unreviewed health followup target domain')
            targeting = (None if target is None else TargetSpec(TargetMode.REQUIRED,
                zones=(Zone.BOARD,) if target == 'minion' else (Zone.HERO, Zone.BOARD),
                kinds=(CardType.MINION,) if target == 'minion' else (CardType.HERO, CardType.MINION)))
            keywords = (Keyword.LIFESTEAL,) if raw['tags'].get('LIFESTEAL') == 1 else ()
            definition = CardDefinition(raw['id'], raw['name'], kind, cost=raw['cost'],
                metadata=metadata, spell_school=school, targeting=targeting, keywords=keywords,
                on_play=PREFIX+recipe['script'])
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
