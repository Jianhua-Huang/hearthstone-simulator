"""Test Subject: native copyable actual-target memory and ordinary spell shuffles."""
import json
from pathlib import Path
from hs_sim.engine.deathrattle_memory import ShuffleRememberedTargetSpell
from hs_sim.engine.model import CardDefinition, CardType, NativeDeathrattleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

SUBJECT = 'BOT_558'
DEPENDENCIES = (SUBJECT,)
COLLECTIBLE_ROOTS = ()
BODY = 'cards.past_targeted_spell_memory.shuffle'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/past-targeted-spell-memory-v1.json'
BATCH_HASH = 'a9445426f5266e8b771adbc3ec744f536a6ebb952d60a8af0c69c3e71b8a22c1'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(d['collectible_leaf_ids']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES or
            any(d[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only',
                'skipped', 'display_normalizations')) or
            d['numeric_normalizations'] != {SUBJECT: {'attack': 0}} or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in d['dependencies'])):
        raise TargetValidationError('Test Subject lost its full original source or reviewed zero-Attack normalization')
    return d


def register_past_targeted_spell_memory_cards(registry):
    def body(c):
        memory = None if c.deathrattle is None else c.deathrattle.ability.deathrattle_memory
        if memory is None or memory.spec.kind != 'targeted_spells':
            raise UnsupportedDefinitionError('Test Subject needs its complete original native spell memory')
        return tuple(ShuffleRememberedTargetSpell(c.deathrattle.id, i)
            for i in range(len(memory.targeted_spells)))
    registry.register_behavior(BODY, body)
    raw = load_batch()['dependencies'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS'),
            raw['tags'].get('RARITY'), raw['tags'].get('DEATHRATTLE')) != ('MINION', 1, None, 2, 6, 3, 1):
        raise TargetValidationError('Test Subject requires its real Priest rare 0/2 face')
    card = CardDefinition(SUBJECT, raw['name'], CardType.MINION, cost=1, attack=0, health=2,
        deathrattle=BODY, native_deathrattle=NativeDeathrattleSpec('targeted_spells'),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
