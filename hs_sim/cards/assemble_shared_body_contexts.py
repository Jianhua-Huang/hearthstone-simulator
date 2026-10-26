"""Review existing effect bodies for the actual shared-pool activation windows."""
import hashlib
import json
from pathlib import Path

from hs_sim.targets import TargetValidationError, canonical_digest

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/assemble-shared-body-contexts-v1.json'
BATCH_HASH = '1dbe32b8920730fa764e31cdd14897c4a4ad871fa2c7b5097af4e9412dac29da'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value) != BATCH_HASH or value['schema'] != 1 or
            len(value['amendments']) != 175 or
            len({a['card_id'] for a in value['amendments']}) != 175 or
            value['preserve_pending_timings'] is not True or
            hashlib.sha256((ROOT/value['source_pool_manifest']).read_bytes()).hexdigest() != value['source_pool_sha256']):
        raise TargetValidationError('Shared effect-body review lost its complete original scope')
    return value


def register_assemble_shared_body_contexts(registry):
    for row in load_batch()['amendments']:
        fragments = registry.assemble_templates if row['fragment_kind']=='template' else registry.assemble_projections
        fragment = fragments.get(row['card_id'])
        if (fragment is None or fragment.suffix.behavior_id != row['behavior_id'] or
                set(row['add_timings']) & set(fragment.suffix.pending_timings)):
            raise TargetValidationError('Shared effect-body review changed its original body or a deferred timing')
        # The prefix still owns every original condition, usage budget and
        # event window. This adds no callbacks, events or timing combinations.
        registry.extend_assemble_suffix_timings(row['card_id'], tuple(row['add_timings']),
            expected_template_sha256=row['expected_fragment_sha256'])
